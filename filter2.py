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
	url: str
	numStars: int = 0
	numPlanets: int = 0
	numLandable: int = 0
	numAtmosphere: int = 0
	numRings: int = 0
	numBelts: int = 0
	numRocky: int = 0
	numHmc: int = 0
	numElws: int = 0
	numWws: int = 0
	numBlackHoles: int = 0
	numNStars: int = 0

	# def getScore(self):
	# 	result = 0
	# 	result += self.numStars
	# 	result += self.numPlanets
	# 	result += self.numRings
	# 	result += self.numLandable * 2
	# 	result += self.numAtmosphere * 4
	# 	result += self.numElws * 8
	# 	result += self.numWws * 6
	# 	result += self.numBlackHoles * 50
	# 	result += self.numNStars * 20
	# 	return result
	def getScore(self):
		badStarClasses = ["T (Brown dwarf) Star"]
		result = 0
		if self.mainStar in badStarClasses:
			result -= 10
		result += self.numStars
		result += self.numPlanets
		result += self.numRings * 2
		result += self.numBelts * 4
		result += self.numLandable * 3
		numCmmCandidates = self.numRocky + self.numHmc
		result += numCmmCandidates * 4
		result += self.numAtmosphere * 5
		result += self.numElws * 15
		result += self.numWws * 12
		result += self.numBlackHoles * 20
		result += self.numNStars * 10
		return result

	def writeStats(self, output):
		output.write(f"{self.name}\n")
		output.write(f"Score: {self.getScore()}\n")
		output.write(f"Main star: {self.mainStar}\n")
		output.write(f"{self.url}\n")
		if self.numStars > 0:
			output.write(f"Stars: {self.numStars}\n")
		if self.numPlanets > 0:
			output.write(f"Planets: {self.numPlanets}\n")
		if self.numLandable > 0:
			output.write(f"Landable: {self.numLandable}\n")
		if self.numBlackHoles > 0:
			output.write(f"(!)Black Holes: {self.numBlackHoles}\n")
		if self.numNStars > 0:
			output.write(f"(!)Neutron Stars: {self.numNStars}\n")
		if self.numAtmosphere > 0:
			output.write(f"Atmosphere: {self.numAtmosphere}\n")
		if self.numBelts > 0:
			output.write(f"Belts: {self.numBelts}\n")
		if self.numRings > 0:
			output.write(f"Rings: {self.numRings}\n")
		if self.numRocky > 0:
			output.write(f"Rocky: {self.numRocky}\n")
		if self.numHmc > 0:
			output.write(f"HMC: {self.numHmc}\n")
		if self.numElws > 0:
			output.write(f"Earth-like: {self.numElws}\n")
		if self.numWws > 0:
			output.write(f"Water-worlds: {self.numWws}\n")

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
		url = data.get('url', "")
		bodies = data.get('bodies', [])
		numLandable = 0
		numAtmosphere = 0
		numRings = 0
		numBelts = 0
		numHmc = 0
		numRocky = 0
		numWws = 0
		numElws = 0
		numBhs = 0
		numNeutrons = 0
		
		
		for body in bodies:
			bodyType = body.get('type', '')
			if bodyType == 'Star':
				starCount += 1
				subType = body.get("subType", "")
				if subType == "Black Hole":
					numBhs += 1
				elif subType == "Neutron Star":
					numNeutrons += 1
				if belts := body.get("belts", None):
					numBelts += len(belts)
				if body.get('isMainStar', False):
					starType = body.get('subType', '')
			elif bodyType == 'Planet':
				subType = body.get("subType", "")
				landable = body.get('isLandable', False)
				if rings := body.get("rings", None):
					# numRings += 1
					numRings += len(rings)
				if subType == "Water world":
					numWws += 1
				elif subType == "Rocky body":
					if landable:
						numRocky += 1
				elif subType == "High metal content world":
					if landable:
						numHmc += 1
				elif subType == "Earth-like world":
					numElws += 1
				if landable:
					numLandable += 1
					if body.get('atmosphereType', "") != "No atmosphere":
						numAtmosphere += 1
				planetCount += 1

		if (planetCount > 0) and ((numLandable > 0) or (numAtmosphere > 0)):
			tmp = PlanetData(
				name=sys_name,
				mainStar=starType,
				url=url,
				numStars=starCount,
				numPlanets=planetCount,
				numLandable=numLandable,
				numAtmosphere=numAtmosphere,
				numRings=numRings,
				numBelts=numBelts,
				numRocky=numRocky,
				numHmc=numHmc,
				numElws=numElws,
				numWws=numWws,
				numBlackHoles=numBhs,
				numNStars=numNeutrons
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
		
		scored = []
		# Output results
		for cur in filtered:
			# args.output.write(f"{cur.name}\n")
			# args.output.write(f"Score: {cur.getScore()}\n")
			# args.output.write(f"Main star: {cur.mainStar}\n")
			# args.output.write(f"Stars: {cur.numStars:>2} planets: {cur.numPlanets:>2}\n")
			# args.output.write(f"Landable: {cur.numLandable} Atmosphere: {cur.numAtmosphere}\n")
			# args.output.write(f"Rings: {cur.numRings} Rocky: {cur.numRocky}\n")
			# args.output.write(f"Earth-like: {cur.numElws} Water-worlds: {cur.numWws}\n")
			cur.writeStats(args.output)
			args.output.write(f"{'-'*40}\n")
			scored.append(cur)

		scored = sorted(scored, key=lambda x: -x.getScore())
		args.output.write(f"{'='*40}:\n")
		args.output.write(f"Sorted: {len(scored)}:\n")
		args.output.write(f"{'='*40}:\n")

		for cur in scored:
			args.output.write(f"{cur.name}: {cur.getScore()}\n")
			args.output.write(f"{'-'*40}\n")
			cur.writeStats(args.output)
			args.output.write(f"{'='*40}\n")		
			
	finally:
		args.input.close()
		if args.output is not sys.stdout:
			args.output.close()

if __name__ == '__main__':
	main()