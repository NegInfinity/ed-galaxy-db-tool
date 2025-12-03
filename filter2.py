import argparse
import re
import sys
import requests
import time
import os
import json
import hashlib
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

CACHE_DIR = ".edsm_data"

def ensure_cache_dir():
	"""Create cache directory if it doesn't exist"""
	if not os.path.exists(CACHE_DIR):
		os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_filename(system_name: str, endpoint: str) -> str:
	"""Generate cache filename using SHA-1 hash of system name"""
	ensure_cache_dir()
	safe_name = hashlib.sha1(system_name.encode('utf-8')).hexdigest()
	return os.path.join(CACHE_DIR, f"{endpoint}_{safe_name}.json")

def load_from_cache(cache_file: str) -> Optional[Dict]:
	"""Load data from cache file if it exists and is valid"""
	if not os.path.exists(cache_file):
		return None
	
	try:
		with open(cache_file, 'r') as f:
			return json.load(f)
	except (json.JSONDecodeError, OSError):
		# Invalid cache file - delete it and return None
		try:
			os.remove(cache_file)
		except OSError:
			pass
		return None

def save_to_cache(cache_file: str, data: Dict):
	"""Save data to cache file"""
	try:
		with open(cache_file, 'w') as f:
			json.dump(data, f)
	except OSError:
		# Failed to save cache - non-critical error
		pass

def fetch_bodies(system_name: str) -> Tuple[Dict[str, Any], bool]:
	"""Fetch bodies (stars/planets) from EDSM with caching"""
	cache_file = get_cache_filename(system_name, "bodies")
	cached_data = load_from_cache(cache_file)
	if cached_data is not None:
		return cached_data, False
	
	url = "https://www.edsm.net/api-system-v1/bodies"
	params = {"systemName": system_name}
	try:
		r = requests.get(url, params=params, timeout=15)
		r.raise_for_status()
		data = r.json()
		save_to_cache(cache_file, data)
		return data, True
	except Exception as e:
		error_data = {"error": str(e), "system": system_name, "msgnum": 999}
		return error_data, True

def fetch_info(system_name: str) -> Tuple[Optional[Dict[str, Any]], bool]:
	"""Fetch coords + information from EDSM with caching"""
	cache_file = get_cache_filename(system_name, "info")
	cached_data = load_from_cache(cache_file)
	if cached_data is not None:
		return cached_data, False
	
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
		data = r.json()
		save_to_cache(cache_file, data)
		return data, True
	except Exception:
		return None, True

def fetch_full_system(system_name: str) -> Tuple[Dict[str, Any], bool]:
	"""Combine bodies + info into one structure with request tracking"""
	bodies_data, bodies_requested = fetch_bodies(system_name)
	
	info_requested = False
	# Only fetch info if we have valid system data
	if "bodies" in bodies_data or "id" in bodies_data:
		info_data, info_requested = fetch_info(system_name)
		if info_data:
			bodies_data["coords"] = info_data.get("coords")
			bodies_data["information"] = info_data.get("information", {})
	
	total_requested = bodies_requested or info_requested
	return bodies_data, total_requested

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
	"""
	Process system names and yield interesting planets
	"""
	total = len(system_names)

	for idx, sys_name in enumerate(system_names, 1):
		print(f"[{idx}/{total}] Fetching {sys_name}...", file=sys.stderr)
		data, requested = fetch_full_system(sys_name)
		
		# Skip processing if no valid data
		if not data or ("msgnum" in data and data["msgnum"] != 100):
			print(f"No valid data for {sys_name}", file=sys.stderr)
			# Sleep only if we made actual requests
			if idx < total and requested:
				time.sleep(1)
			continue

		starCount = 0
		planetCount = 0
		starType = ''
		numBodies = data.get('bodyCount', 0)
		bodies = data.get('bodies', [])
		hasLandable = False
		hasAtmosphere = False
		
		for body in bodies:
			bodyType = body.get('type', '')
			if bodyType == 'Star':
				starCount += 1
				if body.get('isMainStar', False):
					starType = body.get('subType', '')
			elif bodyType == 'Planet':
				if body.get('isLandable', False):
					hasLandable = True
					if body.get('atmosphereType', "") != "No atmosphere":
						hasAtmosphere = True
				planetCount += 1

		if (planetCount > 0) and (hasLandable or hasAtmosphere):
			tmp = PlanetData(
				name=sys_name,
				mainStar=starType,
				numStars=starCount,
				numPlanets=planetCount,
				hasLandable=hasLandable,
				hasAtmosphere=hasAtmosphere
			)
			yield tmp
		
		# Sleep only if we made actual API requests and not on last item
		if idx < total and requested:
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
		for cur in filtered:
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