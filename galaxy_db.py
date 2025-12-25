#!/usr/bin/env python3
import gzip
import ijson
import sqlite3
import sys
import time
import datetime
from math import floor, sqrt
import argparse
from dataclasses import dataclass
from typing import Optional, List, Tuple, Union, Dict

GRID = 25.0

@dataclass
class SystemData:
	id64: int
	x: float
	y: float
	z: float
	name: str
	mainStar: str

@dataclass
class PopulationData:
	id64: int
	population: Optional[int]
	security: str
	controllingFaction: str
	primaryEconomy: str
	secondaryEconomy: str

class AdaptiveUpdateTracker:
	"""Tracks record processing progress and triggers commits based on count/time thresholds.
	Dynamically adjusts time-check frequency for optimal performance."""
	
	def __init__(self, batch_size, time_interval=5.0, initial_time_check_batch=100,
				 min_time_check_batch=10, max_time_check_batch=10000, rate_smoothing=0.3):
		"""
		Initialize adaptive tracker.
		
		Args:
			batch_size (int): Commit after processing this many records.
			time_interval (float): Max seconds between commits (default: 5.0).
			initial_time_check_batch (int): Initial record count between time checks (default: 100).
			min_time_check_batch (int): Minimum records between time checks (default: 10).
			max_time_check_batch (int): Maximum records between time checks (default: 10000).
			rate_smoothing (float): EMA smoothing factor for rate calculation (0.0-1.0, default: 0.3).
		"""
		self.batch_size = batch_size
		self.time_interval = time_interval
		self.time_check_batch = initial_time_check_batch
		self.min_time_check_batch = min_time_check_batch
		self.max_time_check_batch = max_time_check_batch
		self.rate_smoothing = rate_smoothing
		
		self.start_time = time.time()
		self.last_commit_time = self.start_time
		self.last_commit_total = 0  # Records count at last commit
		self.total_count = 0
		self.records_since_time_check = 0
		self.ema_rate = None  # Exponential moving average of processing rate

	def should_commit(self):
		"""Increment record count and determine if commit is needed."""
		self.total_count += 1
		self.records_since_time_check += 1
		
		# Check batch condition
		if self.batch_size > 0 and self.total_count % self.batch_size == 0:
			self._reset_timer()
			return True
		
		# Periodically check time condition
		if self.records_since_time_check >= self.time_check_batch:
			self.records_since_time_check = 0
			if time.time() - self.last_commit_time >= self.time_interval:
				self._reset_timer()
				return True
		
		return False

	def _reset_timer(self):
		"""Update commit timestamp, reset counters, and adaptively adjust time_check_batch."""
		current_time = time.time()
		elapsed = current_time - self.last_commit_time
		records_since_commit = self.total_count - self.last_commit_total

		# Update EMA of processing rate (records/sec)
		if elapsed > 0 and records_since_commit > 0:
			current_rate = records_since_commit / elapsed
			if self.ema_rate is None:
				self.ema_rate = current_rate
			else:
				self.ema_rate = (
					self.rate_smoothing * current_rate +
					(1 - self.rate_smoothing) * self.ema_rate
				)
			
			# Calculate new time_check_batch: aim for 1 time-check per time_interval seconds
			new_batch = self.ema_rate * self.time_interval
			self.time_check_batch = int(round(
				max(self.min_time_check_batch, min(self.max_time_check_batch, new_batch))
			))

		# Reset state for next interval
		self.last_commit_time = current_time
		self.last_commit_total = self.total_count
		self.records_since_time_check = 0

	def print_stats(self, item_type, final=False):
		"""Print processing statistics with context-appropriate messaging."""
		elapsed = time.time() - self.start_time
		rate = self.total_count / elapsed if elapsed > 0 else 0
		
		if final:
			prefix = f'Done. Total {item_type}: {self.total_count:,}'
		else:
			prefix = f'{self.total_count:,} {item_type} updated …'
		
		print(prefix)
		print(f"Elapsed time: {elapsed:.2f}s ({datetime.timedelta(seconds=int(elapsed))})")
		print(f"Average rate: {rate:.1f} {item_type}/second")
		print(f"Current time-check batch: {self.time_check_batch}")
		
def gkey(x, y, z):
	"""Calculate grid coordinates from full coordinates"""
	return (int(floor(x/GRID)), int(floor(y/GRID)), int(floor(z/GRID)))

def is_any_faction(name: str) -> bool:
	return name == "ANY"

class GalaxyDatabase:
	def __init__(self, db_path, restore_from=None):
		self.db_path = db_path
		self.conn = None
		self._connect()
		self._configure_connection()
		if restore_from:
			self._restore_from_file(restore_from)
		self._initialize_schema()

	def _connect(self):
		"""Establish database connection"""
		if self.conn:
			self.conn.close()
		self.conn = sqlite3.connect(self.db_path)

	def _configure_connection(self):
		"""Apply performance optimizations to connection"""
		pragmas = [
			("journal_mode", "WAL"),
			("synchronous", "NORMAL"),
			("cache_size", "-100000"),  # 100MB cache
			("temp_store", "MEMORY"),
			("mmap_size", "1073741824")  # 1GB mmap
		]
		cursor = self.conn.cursor()
		for key, value in pragmas:
			cursor.execute(f"PRAGMA {key} = {value}")
		self.conn.commit()

	def _initialize_schema(self):
		self._create_tables()
		self.create_indexes()

	def _create_tables(self):
		"""Create tables if they don't exist"""
		cursor = self.conn.cursor()
		
		# Existing systems table
		cursor.execute('''
		CREATE TABLE IF NOT EXISTS systems (
			id64 INTEGER PRIMARY KEY,
			grid_x INTEGER NOT NULL,
			grid_y INTEGER NOT NULL, 
			grid_z INTEGER NOT NULL,
			x REAL NOT NULL,
			y REAL NOT NULL,
			z REAL NOT NULL,
			name TEXT NOT NULL,
			main_star TEXT NOT NULL
		)
		''')
		
		# New population data table
		cursor.execute('''
		CREATE TABLE IF NOT EXISTS population_data (
			id64 INTEGER PRIMARY KEY,
			population INTEGER,
			security TEXT,
			controllingFaction TEXT,
			primaryEconomy TEXT,
			secondaryEconomy TEXT
		)
		''')
		
		self.conn.commit()
		pass

	def drop_indexes(self):
		"""Drop indexes if they exist"""
		cursor = self.conn.cursor()

		# Indexes for systems table
		cursor.execute('''
		DROP INDEX IF EXISTS idx_grid_coords
		''')
		
		cursor.execute('''
		DROP INDEX IF EXISTS idx_sys_name
		''')

		# Indexes for population_data table
		cursor.execute('''
		DROP INDEX IF EXISTS idx_controlling_faction 
		''')
		
		self.conn.commit()
		pass

	def create_indexes(self):
		"""Create indexes if they don't exist"""
		cursor = self.conn.cursor()

		# Indexes for systems table
		cursor.execute('''
		CREATE INDEX IF NOT EXISTS idx_grid_coords 
		ON systems (grid_x, grid_y, grid_z)
		''')
		
		# cursor.execute('''
		# CREATE INDEX IF NOT EXISTS idx_id64 
		# ON systems (id64)
		# ''')		
		
		cursor.execute('''
		CREATE INDEX IF NOT EXISTS idx_sys_name 
		ON systems (name)
		''')

		# Indexes for population_data table
		cursor.execute('''
		CREATE INDEX IF NOT EXISTS idx_controlling_faction 
		ON population_data (controllingFaction)
		''')
		
		self.conn.commit()
		pass

	def query_grid_cell_range(self, min_gx, max_gx, min_gy, max_gy, min_gz, max_gz):
		"""Query all systems in a range of grid cells"""
		cursor = self.conn.cursor()
		cursor.execute('''
		SELECT id64, x, y, z, name, main_star 
		FROM systems 
		WHERE grid_x BETWEEN ? AND ? 
		  AND grid_y BETWEEN ? AND ?
		  AND grid_z BETWEEN ? AND ?
		''', (min_gx, max_gx, min_gy, max_gy, min_gz, max_gz))
		
		return [
			SystemData(
				id64=row[0],
				x=row[1],
				y=row[2],
				z=row[3],
				name=row[4],
				mainStar=row[5]
			)
			for row in cursor.fetchall()
		]

	def get_system_by_id64(self, id64):
		"""Get system details by id64"""
		cursor = self.conn.cursor()
		cursor.execute('''
		SELECT id64, x, y, z, name, main_star
		FROM systems
		WHERE id64 = ?
		''', (id64,))
		
		row = cursor.fetchone()
		if not row:
			return None
			
		return SystemData(
			id64=row[0],
			x=row[1],
			y=row[2],
			z=row[3],
			name=row[4],
			mainStar=row[5]
		)

	def get_system_by_name(self, name):
		"""Get system details by name"""
		cursor = self.conn.cursor()
		cursor.execute('''
		SELECT id64, x, y, z, name, main_star
		FROM systems
		WHERE name = ?
		''', (name,))
		
		row = cursor.fetchone()
		if not row:
			return None
			
		return SystemData(
			id64=row[0],
			x=row[1],
			y=row[2],
			z=row[3],
			name=row[4],
			mainStar=row[5]
		)

	def get_population_by_id64(self, id64):
		"""Get population data by id64"""
		cursor = self.conn.cursor()
		cursor.execute('''
		SELECT id64, population, security, controllingFaction, 
			   primaryEconomy, secondaryEconomy
		FROM population_data
		WHERE id64 = ?
		''', (id64,))
		
		row = cursor.fetchone()
		if not row:
			return None
			
		return PopulationData(
			id64=row[0],
			population=row[1],
			security=row[2],
			controllingFaction=row[3],
			primaryEconomy=row[4],
			secondaryEconomy=row[5]
		)
		
	def get_systems_by_id64s(self, id64_iterable):
		"""Get system details for multiple id64 values (preserves input order)"""
		id64_list = list(id64_iterable)
		if not id64_list:
			return []
		
		unique_ids = set(id64_list)
		placeholders = ','.join('?' * len(unique_ids))
		cursor = self.conn.cursor()
		cursor.execute(f'''
			SELECT id64, x, y, z, name, main_star
			FROM systems
			WHERE id64 IN ({placeholders})
		''', tuple(unique_ids))
		
		systems_map = {
			row[0]: SystemData(
				id64=row[0],
				x=row[1],
				y=row[2],
				z=row[3],
				name=row[4],
				mainStar=row[5]
			)
			for row in cursor.fetchall()
		}
		
		return [systems_map.get(id64) for id64 in id64_list]

	def get_populations_by_id64s(self, id64_iterable):
		"""Get population data for multiple id64 values (preserves input order)"""
		id64_list = list(id64_iterable)
		if not id64_list:
			return []
		
		unique_ids = set(id64_list)
		placeholders = ','.join('?' * len(unique_ids))
		cursor = self.conn.cursor()
		cursor.execute(f'''
			SELECT id64, population, security, controllingFaction, 
				primaryEconomy, secondaryEconomy
			FROM population_data
			WHERE id64 IN ({placeholders})
		''', tuple(unique_ids))
		
		populations_map = {
			row[0]: PopulationData(
				id64=row[0],
				population=row[1],
				security=row[2],
				controllingFaction=row[3],
				primaryEconomy=row[4],
				secondaryEconomy=row[5]
			)
			for row in cursor.fetchall()
		}
		
		return [populations_map.get(id64) for id64 in id64_list]

	def get_factions(self, pattern=None):
		"""Get list of factions with system counts, optionally filtered by pattern"""
		cursor = self.conn.cursor()
		if pattern:
			cursor.execute('''
			SELECT controllingFaction, COUNT(*) as count
			FROM population_data
			WHERE controllingFaction != '' AND controllingFaction LIKE ?
			GROUP BY controllingFaction
			ORDER BY controllingFaction COLLATE NOCASE
			''', (pattern,))
		else:
			cursor.execute('''
			SELECT controllingFaction, COUNT(*) as count
			FROM population_data
			WHERE controllingFaction != ''
			GROUP BY controllingFaction
			ORDER BY controllingFaction COLLATE NOCASE
			''')
		return cursor.fetchall()

	def query_systems_by_faction(self, faction_name):
		"""Query systems controlled by a specific faction"""
		cursor = self.conn.cursor()

		any_faction = is_any_faction(faction_name)
		where_clause = "p.controllingFaction != ''" if any_faction else "p.controllingFaction = ?"
		params = () if any_faction else (faction_name,)

		cursor.execute(f'''
		SELECT 
			s.id64, s.x, s.y, s.z, s.name, s.main_star,
			p.population, p.security, p.controllingFaction,
			p.primaryEconomy, p.secondaryEconomy
		FROM population_data p
		JOIN systems s ON p.id64 = s.id64
		WHERE {where_clause}
		''', params)
		
		results = []
		for row in cursor.fetchall():
			system = SystemData(
				id64=row[0],
				x=row[1],
				y=row[2],
				z=row[3],
				name=row[4],
				mainStar=row[5]
			)
			population = PopulationData(
				id64=row[0],
				population=row[6],
				security=row[7],
				controllingFaction=row[8],
				primaryEconomy=row[9],
				secondaryEconomy=row[10]
			)
			results.append((system, population))
		return results

	def update_systems(self, systems_gz):
		"""Update systems table from gzipped JSON file"""
		cursor = self.conn.cursor()
		tracker = AdaptiveUpdateTracker(batch_size=50_000, time_interval=5.0, max_time_check_batch=50_000)
		cursor.execute("BEGIN TRANSACTION")
		
		with gzip.open(systems_gz, 'rb') as f:
			for obj in ijson.items(f, 'item', use_float=True):
				name = obj['name']
				mainStar = obj.get('mainStar', "N/A")
				c = obj['coords']
				x, y, z = c['x'], c['y'], c['z']
				id64 = obj['id64']
				grid_x, grid_y, grid_z = gkey(x, y, z)
				
				cursor.execute('''
				INSERT OR REPLACE INTO systems 
				(id64, grid_x, grid_y, grid_z, x, y, z, name, main_star)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
				''', (id64, grid_x, grid_y, grid_z, x, y, z, name, mainStar))
				
				if tracker.should_commit():
					self.conn.commit()
					cursor.execute("BEGIN TRANSACTION")
					tracker.print_stats('systems')
		
		self.conn.commit()
		cursor.execute("ANALYZE")
		self.conn.commit()
		tracker.print_stats('systems', final=True)

	def _restore_from_file(self, src_path: str):
		"""Atomic loading of the database"""
		print(f"Restoring DB from {src_path}...")

		start = time.time()
		def progress(status, remaining, total):
			delta = datetime.timedelta(seconds=(time.time() - start))
			print(f"status: {status}, {remaining}/{total}, elapsed: {delta}")
			pass

		try:
			with sqlite3.connect(src_path) as src:
				src.backup(self.conn, progress=progress)
			delta = datetime.timedelta(seconds=(time.time() - start))
			print(f"Restore complete in {delta}")
		except Exception as e:
			print("Restore failed: ", e)

	def dump_to_file(self, dump_path: str):
		"""Atomic dump to disk (use after in-memory load)"""
		print(f"Dumping DB to {dump_path}...")

		start = time.time()
		def progress(status, remaining, total):
			delta = datetime.timedelta(seconds=(time.time() - start))
			print(f"status: {status}, {remaining}/{total}, elapsed: {delta}")
			pass

		try:
			with sqlite3.connect(dump_path) as target:
				self.conn.backup(target, progress=progress)
			delta = datetime.timedelta(seconds=(time.time() - start))
			print(f"Dump complete in {delta}")
		except Exception as e:
			print("Dump failed: ", e)

	def update_population_data(self, pop_gz):
		"""Update population data table from gzipped JSON file"""
		cursor = self.conn.cursor()
		tracker = AdaptiveUpdateTracker(batch_size=50_000, time_interval=5.0)
		cursor.execute("BEGIN TRANSACTION")
		
		with gzip.open(pop_gz, 'rb') as f:
			for obj in ijson.items(f, 'item', use_float=True):
				try:
					id64 = obj['id64']
					population = obj.get('population')
					security = obj.get('security', '')
					primary_economy = obj.get('primaryEconomy', '')
					secondary_economy = obj.get('secondaryEconomy', '')

					if not population or not primary_economy:
						continue
					
					controlling_faction = ''
					if 'controllingFaction' in obj and isinstance(obj['controllingFaction'], dict):
						controlling_faction = obj['controllingFaction'].get('name', '')
					
					cursor.execute('''
					INSERT OR REPLACE INTO population_data 
					(id64, population, security, controllingFaction, 
					 primaryEconomy, secondaryEconomy)
					VALUES (?, ?, ?, ?, ?, ?)
					''', (id64, population, security, controlling_faction,
						  primary_economy, secondary_economy))
					
					if tracker.should_commit():
						self.conn.commit()
						cursor.execute("BEGIN TRANSACTION")
						tracker.print_stats('population records')
				except Exception as e:
					print(f"Error processing record: {e}", file=sys.stderr)
					continue
		
		self.conn.commit()
		cursor.execute("ANALYZE")
		self.conn.commit()
		tracker.print_stats('population records', final=True)
		
	def close(self):
		"""Safely close database connection"""
		if self.conn:
			self.conn.close()
			self.conn = None

	def __del__(self):
		"""Ensure connection is closed on object destruction"""
		self.close()

	def __enter__(self):
		"""Context manager support"""
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		"""Context manager cleanup"""
		self.close()

def query_systems_by_radius(db, center_x, center_y, center_z, radius):
	"""Find systems within a given radius from coordinates"""
	# Calculate grid cell range to search
	min_gx = int(floor((center_x - radius) / GRID))
	max_gx = int(floor((center_x + radius) / GRID))
	min_gy = int(floor((center_y - radius) / GRID))
	max_gy = int(floor((center_y + radius) / GRID))
	min_gz = int(floor((center_z - radius) / GRID))
	max_gz = int(floor((center_z + radius) / GRID))
	
	# Get candidate systems from relevant grid cells
	candidate_systems = db.query_grid_cell_range(
		min_gx, max_gx, min_gy, max_gy, min_gz, max_gz
	)
	
	# Filter by actual distance
	results = []
	radius_sq = radius * radius
	for system in candidate_systems:
		dx = system.x - center_x
		dy = system.y - center_y
		dz = system.z - center_z
		dist_sq = dx*dx + dy*dy + dz*dz
		
		if dist_sq <= radius_sq:
			population = db.get_population_by_id64(system.id64)
			results.append((system, population, sqrt(dist_sq)))  # Return actual distance
	
	return results

def print_system_with_population(system, population):
	"""Print system and population data in readable format"""
	print(f"System: {system.name} (ID64: {system.id64})")
	print(f"Coordinates: ({system.x:.2f}, {system.y:.2f}, {system.z:.2f})")
	print(f"Main star: {system.mainStar}")
	
	if population:
		pop_str = f"{population.population:,}" if population.population else "Unknown"
		print(f"Population: {pop_str}")
		print(f"Security: {population.security}")
		print(f"Controlling Faction: {population.controllingFaction}")
		print(f"Primary Economy: {population.primaryEconomy}")
		print(f"Secondary Economy: {population.secondaryEconomy}")
	else:
		print("No population data available")

def find_colony_candidates(db, args):
	"""Find colonization candidates for a faction"""
	# Parse range arguments
	if args.reference_system:
		if len(args.ranges) < 1:
			print("Error: When using --from, reference_range is required")
			sys.exit(1)
		reference_range = args.ranges[0]
		candidate_range = args.ranges[1] if len(args.ranges) > 1 else 15.0
	else:
		candidate_range = args.ranges[0] if args.ranges else 15.0
		reference_range = None
	
	print(f"Finding colony candidates for '{args.faction_name}'")
	print(f"Candidate search radius: {candidate_range} LY")

	any_faction = is_any_faction(args.faction_name)
	
	ref_system = None
	if args.reference_system:
		print(f"Using reference system: {args.reference_system} (search radius: {reference_range} LY)")
		ref_system = db.get_system_by_name(args.reference_system)
		if ref_system is None:
			print(f"Error: Reference system '{args.reference_system}' not found")
			sys.exit(1)
		
		# Get systems around reference system
		ref_results = query_systems_by_radius(
			db, ref_system.x, ref_system.y, ref_system.z, reference_range
		)
		
		# Filter to get faction-controlled systems
		faction_systems = []
		for sys, pop, dist in ref_results:  # dist is distance from ref_system
			if pop is not None and ((pop.controllingFaction == args.faction_name) or (any_faction and pop.controllingFaction)):
				faction_systems.append((sys, pop))
		
		print(f"Found {len(faction_systems)} systems controlled by '{args.faction_name}' "
			  f"within {reference_range} LY of {args.reference_system}")
	else:
		faction_systems = db.query_systems_by_faction(args.faction_name)
		print(f"Found {len(faction_systems)} systems controlled by '{args.faction_name}'")
	
	if not faction_systems:
		print(f"No systems found controlled by '{args.faction_name}' in the search area")
		sys.exit(0)
	
	# Create mapping for quick faction system lookup
	faction_system_map = {sys.id64: sys for sys, pop in faction_systems}
	
	# Track closest faction system for each candidate
	candidate_info: Dict[int, Tuple[float, int]] = {}  # id64 -> (distance, faction_sys_id)
	
	# Find candidate systems
	start_time = time.time()
	last_update = start_time
	update_interval = 10  # seconds
	
	total_faction_systems = len(faction_systems)
	for i, (faction_sys, faction_pop) in enumerate(faction_systems, 1):
		# Query systems around this faction system
		candidates = query_systems_by_radius(
			db, faction_sys.x, faction_sys.y, faction_sys.z, candidate_range
		)
		
		for candidate_sys, candidate_pop, dist_to_faction in candidates:
			# Skip if this is the faction system itself
			if candidate_sys.id64 == faction_sys.id64:
				continue
			
			# Check if candidate is unowned (no population data or empty controlling faction)
			if candidate_pop is None or candidate_pop.controllingFaction == '':
				# Update candidate info if this is the closest faction system found so far
				current = candidate_info.get(candidate_sys.id64)
				if current is None or dist_to_faction < current[0]:
					candidate_info[candidate_sys.id64] = (dist_to_faction, faction_sys.id64)
		
		# Progress update
		current_time = time.time()
		if current_time - last_update > update_interval:
			elapsed = current_time - start_time
			candidates_found = len(candidate_info)
			print(f"Processed {i}/{total_faction_systems} faction systems "
				  f"({i/total_faction_systems:.1%}) - "
				  f"Found {candidates_found} candidate systems - "
				  f"Time elapsed: {elapsed:.1f}s")
			last_update = current_time
	
	total_time = time.time() - start_time
	print(f"\nProcessed all {total_faction_systems} faction systems in {total_time:.1f} seconds")
	print(f"Found {len(candidate_info)} candidate systems before deduplication")
	
	if not candidate_info:
		print("No colony candidates found")
		sys.exit(0)
	
	# Get details for candidate systems
	candidate_systems = db.get_systems_by_id64s(candidate_info.keys())
	candidate_populations = db.get_populations_by_id64s(candidate_info.keys())
	
	# Create mappings
	candidate_systems_map = {s.id64: s for s in candidate_systems if s is not None}
	candidate_populations_map = {p.id64: p for p in candidate_populations if p is not None}
	
	# Filter valid candidates and remove any that might have owners
	valid_candidates = []
	for id64, (dist, faction_id) in candidate_info.items():
		sys = candidate_systems_map.get(id64)
		pop = candidate_populations_map.get(id64)
		if sys is None:
			continue
		# Final check to ensure system is unowned
		if pop is None or pop.controllingFaction == '':
			valid_candidates.append((sys, pop, dist, faction_id))
	
	print(f"Found {len(valid_candidates)} unique colony candidates")
	if not valid_candidates:
		print("No valid colony candidates found after final verification")
		sys.exit(0)
	
	# Print results with distance information
	print("\nColony Candidates:")
	print("=" * 50)
	for i, (sys, pop, dist_to_faction, faction_sys_id) in enumerate(valid_candidates, 1):
		faction_sys = faction_system_map.get(faction_sys_id)
		if not faction_sys:
			continue  # Shouldn't happen, but safety check
		
		# Calculate distance to reference system if applicable
		dist_to_ref = None
		if ref_system:
			dx = ref_system.x - sys.x
			dy = ref_system.y - sys.y
			dz = ref_system.z - sys.z
			dist_to_ref = sqrt(dx*dx + dy*dy + dz*dz)
		
		# Print candidate details
		print(f"Candidate #{i}")
		print_system_with_population(sys, pop)
		print(f"\nClosest faction system: {faction_sys.name} ({dist_to_faction:.2f} LY)")
		if ref_system:
			print(f"Distance from reference system '{ref_system.name}': {dist_to_ref:.2f} LY")
		print("-" * 50)

def build_parser():
	parser = argparse.ArgumentParser(description='Galaxy Database Manager')
	parser.add_argument('--db', default='galaxy_grid.sqlite',
						help='Database file path (default: galaxy_grid.sqlite)')
	parser.add_argument('--drop-index', help='Drop index before db operations', action='store_true')
	parser.add_argument('--rebuild-index', help='Rebuild index after database operations', action='store_true')
	parser.add_argument('--dump-to', default=None, help='Dump to file after all operations')
	parser.add_argument('--restore-from', default=None, help='Restore from file before all operations')
	
	subparsers = parser.add_subparsers(dest='command', required=True,
									  help='Command to execute')
	
	# Update systems command
	update_systems_parser = subparsers.add_parser('update-systems',
												 help='Update systems table from gzipped JSON file')
	update_systems_parser.add_argument('file', help='Gzipped JSON file with systems data')
	
	# Update population command
	update_pop_parser = subparsers.add_parser('update-pop',
											 help='Update population data table from gzipped JSON file')
	update_pop_parser.add_argument('file', help='Gzipped JSON file with population data')
	
	# List factions command
	list_factions_parser = subparsers.add_parser('list-factions',
											help='List all factions or those matching a pattern')
	list_factions_parser.add_argument('pattern', nargs='?', default=None,
									help='Pattern to match faction names (SQL LIKE syntax with %% and _ wildcards)')
	# Query by faction command
	query_faction_parser = subparsers.add_parser('query-faction',
											   help='Find systems controlled by a faction')
	query_faction_parser.add_argument('faction_name', help='Name of the controlling faction')
	
	# Query by radius command
	query_radius_parser = subparsers.add_parser('query-radius',
											  help='Find systems within radius from coordinates')
	query_radius_parser.add_argument('x', type=float, help='X coordinate of center')
	query_radius_parser.add_argument('y', type=float, help='Y coordinate of center')
	query_radius_parser.add_argument('z', type=float, help='Z coordinate of center')
	query_radius_parser.add_argument('radius', type=float, help='Search radius in light years')
	
	# Find colony candidates command
	find_colony_parser = subparsers.add_parser('find-colony-candidates',
											  help='Find colonization candidates for a faction')
	find_colony_parser.add_argument('faction_name', help='Name of the faction')
	find_colony_parser.add_argument('--from', dest='reference_system', metavar='SYSTEM_NAME',
								   help='Reference system name for initial search')
	find_colony_parser.add_argument('ranges', nargs='*', type=float,
								   help='''If --from is used: [reference_range] [candidate_range]. 
										   Otherwise: [candidate_range]. 
										   Default candidate_range is 15.0.''')
	return parser

def process_commands(args):
	with GalaxyDatabase(args.db, args.restore_from) as db:
		if args.drop_index:
			print(f"Dropping database indexes")
			db.drop_indexes()
			print(f"Done dropping database indexes")
			pass

		if args.command == 'update-systems':
			print(f"Updating systems from {args.file}...")
			db.update_systems(args.file)
		
		elif args.command == 'update-pop':
			print(f"Updating population data from {args.file}...")
			db.update_population_data(args.file)

		elif args.command == 'list-factions':
			print("Listing factions...")
			factions = db.get_factions(pattern=args.pattern)
			if not factions:
				if args.pattern:
					print(f"No factions found matching pattern '{args.pattern}'")
				else:
					print("No factions found in database")
				sys.exit(0)
			
			print(f"Found {len(factions)} factions:")
			print("-" * 50)
			for faction_name, count in factions:
				print(f"{faction_name} ({count} systems)")
						
		elif args.command == 'query-faction':
			print(f"Searching for systems controlled by '{args.faction_name}'...")
			results = db.query_systems_by_faction(args.faction_name)
			
			if not results:
				print(f"No systems found controlled by '{args.faction_name}'")
				sys.exit(0)
			
			print(f"Found {len(results)} systems controlled by '{args.faction_name}':\n")
			for system, population in results:
				print_system_with_population(system, population)
		
		elif args.command == 'query-radius':
			print(f"Searching for systems within {args.radius} LY of "
				  f"({args.x}, {args.y}, {args.z})...")
			results = query_systems_by_radius(
				db, args.x, args.y, args.z, args.radius
			)
			
			if not results:
				print(f"No systems found within {args.radius} LY of "
					  f"({args.x}, {args.y}, {args.z})")
				sys.exit(0)
			
			print(f"Found {len(results)} systems within {args.radius} LY:\n")
			for system, population, _ in results:
				print_system_with_population(system, population)
				print("=" * 50)
		
		elif args.command == 'find-colony-candidates':
			find_colony_candidates(db, args)

		if args.rebuild_index:
			print(f"Rebuilding database indexes")
			db.create_indexes()
			print(f"Done rebuilding database indexes")

		if args.dump_to:
			db.dump_to_file(args.dump_to)

def main():
	parser = build_parser()
	args = parser.parse_args()
	process_commands(args)

if __name__ == '__main__':
	main()
