# Changelog

## 2026.10.28.2
- Added boundary set `historic_districts` (Historic Districts): 199 areas named by `name_1`, from DataSF [63x5-g3m4](https://data.sf.gov/d/63x5-g3m4). Raw copy: `data/uploads/Historic_Districts_20261028.geojson`.

## 2026.10.28
- **[ADDING-DATA.md](ADDING-DATA.md):** what goes where, and how to add or refresh a boundary set three ways (from DataSF in the browser, from an uploaded file, or the command line), what to check, what happens in Joiner and Block Party after merging, and what isn't automated yet.
- **"Add or refresh a boundary set" Action** and `scripts/add_boundary_set.py`: give it a set id and a DataSF dataset (id or page link) or a file in `data/uploads/`. It saves the raw download in `data/uploads/`, picks the field that names each area (or uses the one you give), joins pieces that share a name, adds the set to `sources.json`, builds it, bumps the version, and opens a pull request with the fields, counts and a Joiner link that reads the branch. A refresh that changes nothing does nothing.
- **"Check data" Action** on every pull request: JSON files parse and `get_layers.py --check` passes.

## 2026.10.27.2
- New `scripts/get_layers.py` builds `data/boundaries/` from `sources.json`: a standard-library Python port of Joiner's `get_layers.mjs` (v42), including JoinKit's dissolve for the districts made from precincts. Built from the same input, all 16 sets and `index.json` come out byte-for-byte the same as the Node script's; rebuilding each committed set from itself gives the same file back. Joiner's copy of the script is retired.
- `sources.json`: Who's on First is read from `data/uploads/wof/`. The boundary files and `index.json` are unchanged; the next rebuild drops the Cultural Districts aliases still inside `index.json` (they're in `data/aliases.json`).

## 2026.10.27
sf-blocks becomes the San Francisco data repo for Joiner and Block Party, not just the street blocks. Nothing existing moved or changed; everything here is added.

- `data/boundaries/`: all 16 of Joiner's boundary sets (was 5), with Joiner's manifest `index.json` and its build config as `sources.json`. Adds supervisor districts, ZIPs, census tracts, Cultural Districts, Bay Area counties and ZIPs, election precincts, and US House, State Senate, Assembly and BART districts.
- `data/aliases.json`: other names for areas, in one place. Block Party's neighborhood aliases and Joiner's Cultural District aliases.
- `data/layers/` and `scripts/build_layers.py`: Block Party's map layers (schools, stations, health care, Muni, bike, Slow Streets, city lands) and the script that builds them, now reading raw downloads from `data/uploads/` (Block Party's top-level `layers/`). Rebuilt files are byte-identical to Block Party's.
- `data/Land_Use_with_Active_Parcel_Information.pmtiles`, from Block Party.
- `data/uploads/`: the raw downloads, the Cultural Districts export (2026-10-25), and Who's On First's SF data from Joiner.
- `reference/`: SF Planning's neighborhood group list and `scripts/build_neighborhood_groups.py` from Block Party (now reading `data/aliases.json` and writing `reference/neighborhood-groups/neighborhood_groups.json`), and the Cultural Districts contacts template from Joiner.
- `region.json`: name, home view, bbox, basemap keys and paths, for apps opening this region.
- `.nojekyll`, so GitHub Pages serves every file as is.

## 2026.10.23
- `build_data.py --areas` tags every segment with the neighborhoods it falls in from each boundary set in `data/boundaries/`: `hood_analysis` (Analysis Neighborhoods), `hood_sffind` (SF Find), `hood_planning` (Planning Neighborhood Groups), `hood_realtor` (Realtor), `hood_wof` (Who's on First). Each is checked at 25%, 50%, and 75% along the block; a block on a boundary gets both names, most-covered first, joined with "; ". Boundary files are copied from civic-joy-fund/joiner; a missing one is skipped. About 16,000 of 16,400 active blocks agree with the streets file's own `analysis_neighborhood`; the rest are boundary streets the city assigned to the other side.

## 2026.10.22
- New `scripts/match_polygons.py`: lists the blocks and intersections inside each polygon of a GeoJSON file. Street strips (narrow, or long and up to 60 m wide) list the blocks running along them and leave out cross streets; wider areas list blocks fully or partly inside. Strips with nothing inside retry 10 m around the outline (medians between divided roadways), and polygons off the street grid get the nearest block within 40 m. Writes a CSV (one row per polygon and CNN) and a GeoJSON copy of the polygons with `block_cnns`, `partial_cnns`, `intersection_cnns`, and `nearest_cnn`.

## 2026.10.11
- `build_data.py` downloads `data/sf_streets.csv` and `data/sf_intersections.csv` from DataSF's API when they're missing; `--download` refreshes them. The dataset names, ids, and pages are listed at the top of the script. Column names are read case-insensitively, so a manual Export from the dataset page works too. Output is unchanged for the same data, except dates.
- Dates are stored as YYYY-MM-DD (`date_dropped`, `data_as_of`), whichever way the CSV wrote them. The API writes `2013-11-07T00:00:00.000` and the site's Export writes `11/07/2013`, which would otherwise show up as-is on Block Party's "Retired" pill.

## 2026.10.08
- `build_data.py --slopes`: adds `slope_avg` and `slope_max` (percent × 10, -1 if unknown) to every segment in `streets.json`, from AWS Terrarium elevation tiles at zoom 15 sampled at five points along the block, the same way Block Party's profile chart does. Downloads about 250 tiles once into `.tile-cache/` (git-ignored). Without the flag, the output is unchanged.

## 2026.10.06
First version as its own repo, split out of civic-joy-fund/block-party.

- `streets.json`: segments and intersections from DataSF Streets – Active and Retired and List of Intersections only (data as of the exports in `data/`).
- `match_blocks.py`:
  - Between-cross-streets, block number, address, intersection, and street-only matching, with confidence and notes.
  - Cross streets checked against every street meeting at an intersection, not just the one named on each segment.
  - Streets with gaps in the city data match by position along the street.
  - Intersection points within 15 m of each other are treated as one.
  - Directional names ("South Van Ness", "West Portal") and exact names starting with common words ("Front St") resolve.
  - Intersections return the intersection CNN and a POINT, with touching blocks in `nearby_cnns`.
