import argparse
import re
import sys
import requests
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional

def fetch_bodies(system_name: str) -> Dict[str, Any]:
	"""Fetch bodies (stars/planets) from EDSM."""
	url = "https://www.edsm.net/api-system-v1/bodies"
	params = {"systemName": system_name}
	try:
		r = requests.get(url, params=params, timeout=15)
		r.raise_for_status()
		return r.json()
	except Exception as e:
		return {"error": str(e), "system": system_name, "msgnum": 999}

def fetch_info(system_name: str) -> Optional[Dict[str, Any]]:
	"""Fetch coords + information (allegiance, population, etc.)."""
	url = "https://www.edsm.net/api-v1/system"
	params = {
		"systemName": system_name,
		"showCoordinates": 1,
		"showInformation": 1,
		"showPermit": 1
	}
	try:
		r = requests.get(url, params=params, timeout=15)
		r.raise_for_status()
		return r.json()
	except Exception:
		return None

def fetch_full_system(system_name: str) -> Dict[str, Any]:
	"""Combine bodies + info into one structure."""
	bodies_data = fetch_bodies(system_name)
	
	# If we got actual data (not an error), try to enrich it
	if "bodies" in bodies_data or "id" in bodies_data:
		info = fetch_info(system_name)
		if info:
			bodies_data["coords"] = info.get("coords")
			bodies_data["information"] = info.get("information", {})

	return bodies_data	
	# return {system_name.strip(): bodies_data}

def extract_matches(input_file, pattern):
	"""
	Process input file and return all regex matches as a list
	
	Args:
		input_file: File-like object to read from
		pattern: Compiled regex pattern
	
	Returns:
		List of matched strings
	"""
	matches = []
	for line in input_file:
		match = pattern.search(line)
		if match:
			matches.append(match.group(0))
	return matches

@dataclass
class PlanetData:
	name: str
	mainStar: str
	numStars: int = 0
	numPlanets: int = 0
	hasLandable: bool = False
	hasAtmosphere: bool = False

def filter_system_names(system_names: list[str]):
	# results = []
	total = len(system_names)

	for idx, sys_name in enumerate(system_names, 1):
		print(f"[{idx}/{total}] Fetching {sys_name}...", file=sys.stderr)
		data = fetch_full_system(sys_name)
		if not data:
			print(f"no data for {sys_name}")

		# print(data)
		# print(type(data))
		starCount = 0
		planetCount = 0
		starType = ''
		numBodies = data['bodyCount']
		bodies = data['bodies']
		hasLandable = False
		hasAtmosphere = False
		for bodyIdx, body in enumerate(bodies):
			bodyType = body['type']
			if bodyType == 'Star':
				starCount += 1
				if body['isMainStar']:
					starType = body['subType']
			elif bodyType == 'Planet':
				if body['isLandable']:
					hasLandable = True
					if body['atmosphereType'] != "No atmosphere":
						hasAtmosphere = True
				planetCount += 1
			# print(body)

		# print(f"mainStar: {starType}")
		# print(f"starCount: {starCount}")
		# print(f"planetCount: {planetCount}")
		# print(f"numBodies: {numBodies}")
		# print(f"hasLandable: {hasLandable}")
		# print(f"hasAtmosphere: {hasAtmosphere}")

		if (planetCount > 0) and (hasLandable or hasAtmosphere):
			tmp = PlanetData(sys_name, starType, starCount, planetCount, hasLandable, hasAtmosphere)
			# print(tmp)
			# results.append((sys_name, hasLandable, hasAtmosphere))
			yield tmp
		# results.update(data)
		
		# Two requests per system → sleep 1s → ~120 requests/minute (EDSM limit)
		if idx < total:
			time.sleep(1)

def main():
	parser = argparse.ArgumentParser(description='Extract system names from log files')
	parser.add_argument('input', type=argparse.FileType('r'), help='Input logfile to process')
	parser.add_argument('-o', '--output', type=argparse.FileType('w'), default=sys.stdout,
						help='Output file (default: stdout)')
	
	args = parser.parse_args()
	
	# Fixed regex pattern with decimal numbers only
	pattern = re.compile(r'(?<=System: ).*(?= \(ID64: [0-9]+\))')
	
	try:
		# Get all matches as a list
		matches = extract_matches(args.input, pattern)
		filtered = filter_system_names(matches)
		
		# Output results
		# for match in matches:
		# 	args.output.write(f"{match}\n")
		for cur in filtered:
			print(cur)
			args.output.write(f"{cur.name}\n")
			args.output.write(f"Main star: {cur.mainStar}\n")
			args.output.write(f"Stars: {cur.numStars:>2} planets: {cur.numPlanets:>2}\n")
			args.output.write(f"Landable: {cur.hasLandable} Atmosphere: {cur.hasAtmosphere}\n")
			args.output.write(f"{'-'*40}\n")
			
	finally:
		args.input.close()
		if args.output is not sys.stdout:
			args.output.close()

if __name__ == '__main__':
	main()