# Changelog

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
