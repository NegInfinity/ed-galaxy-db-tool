## What is it

This is a tool written primarily to find colonization candidates in elite dangerous, though it can do a bit more. It works from CLI, uses spansh database dumps for initialization. 
You can use it to find colonization targets within range from specific faction, (known) systems within certain range, all systems owned by a faction, or just list factions.

## Disclaimer

This is unsupported, comes with no warranty, issues will not be tracked and patches will not be accepted. If you want to change anything - fork it. The code is mostly LLM-generated meaning not top tier either. 
It exists because such query cannot be done by [spansh.co.uk](https://spansh.co.uk/) at the time of writing. The tool is not affiliated with spansh.

**You must build the database before it can be used.** The script will create one on the first run, but it'll be empty. See "initialization" below.

## License

Because the vast majority of code is LLM-generated, the license is Unlicense or, public domain. 

## Requirements

This is a CLI tool, you need to know CLI and python. It uses ijson and requests, requirements are provided. `pip install -r requirmenets.txt` should make it useable. 

## Help

To get full list of options, use: `galaxy_db.py -h`. Currently, it is:

```
usage: galaxy_db.py [-h] [--db DB] [--drop-index] [--rebuild-index]
                    [--dump-to DUMP_TO] [--restore-from RESTORE_FROM]
                    {update-systems,update-pop,list-factions,query-faction,query-radius,find-colony-candidates} ...

Galaxy Database Manager

positional arguments:
  {update-systems,update-pop,list-factions,query-faction,query-radius,find-colony-candidates}
                        Command to execute
    update-systems      Update systems table from gzipped JSON file
    update-pop          Update population data table from gzipped JSON file
    list-factions       List all factions or those matching a pattern
    query-faction       Find systems controlled by a faction
    query-radius        Find systems within radius from coordinates
    find-colony-candidates
                        Find colonization candidates for a faction

options:
  -h, --help            show this help message and exit
  --db DB               Database file path (default: galaxy_grid.sqlite)
  --drop-index          Drop index before db operations
  --rebuild-index       Rebuild index after database operations
  --dump-to DUMP_TO     Dump to file after all operations
  --restore-from RESTORE_FROM
                        Restore from file before all operations
```

For individual option help, use that option with -h key: `galaxy_db.py list-factions -h`

## Initialization

Download `systems.json.gz` from spansh, "data dump" section. All discovered galaxy, minimal data. Later you can use `systems_1day.json.gz` and `systems_1month.json.gz` to later update the database. 

Initial build of the database:

Slow way (4.5 hours, will create `galaxy_grid.sqlite`):  
```
galaxy_db.py update-systems systems.json.gz 
```

Expect 22 gigabyte database. Do this on SSD. HDD is likely unfeasible or will take days.

Fast way (17 minutes or so, requires about 32 GB of RAM):  
```
galaxy_db.py --db ":memory:" --dump-to test.sqlite --drop-index update-systems systems.json.gz 
```

This "fast way" database on the first load this will spend around 15 minutes rebuilding index with no progress indicator. You will then have to load `test.sqlite` either using `--db` option or rename it into `galaxy_grid.sqlite`.

This will give you basic spatial data, which is, at the time of writing, 170 million systems.

To add population data for populated systems, use:  
```
galaxy_db.py update-pop galaxy_populated.json.gz 
```

This will load basic system data, after that you can run queries for factions. Only controlling factions are stored.

## Queries

List factions: `galaxy_db.py list-factions`

By name: `galaxy_db.py list-factions ques` This will list all factions with "ques" in the name.

Systems in range: `galaxy_db.py query-radius 0 0 0 25`This will list all systems within 25 Ly from Sol

And now the important part: Colony candidates.  
```
galaxy_db.py find-colony-candidates --from Sol "Nahuaru Crimson Bridge Int" 200
```
200 is range, Sol is system name, "...Brigade..." is faction name. Ranges are in light-years.

This will find systems belonging to this faction, within 200 Ly range from Sol, and then find all colonization target systems within the range. This will take a while. "Target" means unpopulated system within 15 Ly range (you can override it) from faction-owned system. You will not get body data this way, only mainStar, name, id64, and distance from reference. 

## Helper script

About that `filter.py`. You can redirect galaxy_db output to file
```
galaxy_db.py find-colony-candidates --from Sol "Nahuaru Crimson Bridge Int" 200 > candidates.txt
```
This will result in something like this:
```
Finding colony candidates for 'Nahuaru Crimson Bridge Int'
Candidate search radius: 15.0 LY
Using reference system: Sol (search radius: 200.0 LY)
Found 131 systems controlled by 'Nahuaru Crimson Bridge Int' within 200.0 LY of Sol
Processed 64/131 faction systems (48.9%) - Found 310 candidate systems - Time elapsed: 10.1s

Processed all 131 faction systems in 19.2 seconds
Found 401 candidate systems before deduplication
Found 401 unique colony candidates

Colony Candidates:
==================================================
Candidate #1
System: Scorpii Sector HR-W c1-26 (ID64: 7230745219826)
Coordinates: (15.34, -4.72, 174.19)
Main star: M (Red dwarf) Star
No population data available

Closest faction system: HIP 86062 (8.56 LY)
Distance from reference system 'Sol': 174.93 LY
--------------------------------------------------
Candidate #2
...
```

There will be a ton of systems with a single star, only stars, no landable planets, and so on. Not interesting for colonization.

Then you can use `filter.py candidates.txt` (redirect to file with `filter.py candidates.txt >filtered.txt` or use `tee` on unix-like/wsl), and it will SLOWLY filter through the list, looking for "interesting" systems. Interesting means it has planets, it has landable planets and landable planets with atmosphere, though it queries atmosphere by atmosphere type, and not pressure. To verify this information it is using direct EDSM calls and no database to get planetary data, meaning it will be processing one system per second. It will eventually filter through the list and print systems that are likely to be useful. 

That will be all. Have fun.

## Schema, rate limits, etc.

The filter script adheres to EDSM rate limits (which is why it checks 1 system per second), the database schema can found within Python file. The script uses sqlite3. 
