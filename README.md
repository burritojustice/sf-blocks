# sf-blocks

San Francisco street blocks and intersections, and the code that matches street descriptions to them.

This is the master copy of the street data and matching logic shared by:

- [civic-joy-fund/block-party](https://github.com/civic-joy-fund/block-party): find a block and its CNN for a block party application
- [burritojustice/sf-striping](https://github.com/burritojustice/sf-striping): SFMTA striping diagrams mapped to blocks

Those projects **keep their own copies** of the files they use, so each one works on its own and nothing breaks if this repo changes or moves. Each copied file starts with a line saying which version it came from (see `VERSION`).

## Files

| Path | What it is |
|---|---|
| `data/sf_streets.csv` | DataSF export: Streets – Active and Retired |
| `data/sf_intersections.csv` | DataSF export: List of Intersections only |
| `data/streets.json` | Compact data built from the two CSVs (~2.5 MB, ~650 KB gzipped); what the maps load |
| `scripts/build_data.py` | CSVs → `data/streets.json` |
| `scripts/match_blocks.py` | Matches free-text locations to blocks; also a library used by sf-striping |
| `scripts/match_polygons.py` | Polygons (GeoJSON) → the blocks and intersections inside them |
| `VERSION` | Date-style version of the data and code, e.g. `2026.10.06` |

## Data sources

From DataSF:

- **Streets – Active and Retired** → `data/sf_streets.csv`
  https://data.sf.gov/Geographic-Locations-and-Boundaries/Streets-Active-and-Retired/3psu-pn9h/about_data
- **List of Intersections only** → `data/sf_intersections.csv`
  https://data.sf.gov/Geographic-Locations-and-Boundaries/List-of-Intersections-only/sw2d-qfup/about_data

Both CSVs are committed so the build works right away. If one is missing, `build_data.py` downloads it from DataSF's API (`https://data.sf.gov/resource/<id>.csv`); `python3 scripts/build_data.py --download` refreshes both before building. A manual Export from the pages above also works: save it under the name shown. The dataset ids and pages are also listed at the top of the script.

The GeoJSON version of the streets dataset isn't needed; the CSV has the same geometry as WKT.

## streets.json

One row per street segment (active and retired), with: CNN, street name, from and to cross streets, left and right address ranges, from and to intersection CNNs, layer, active and accepted flags, neighborhood, analysis neighborhood, supervisor district, ZIP, one-way, class code, date dropped, and geometry. Coordinates are stored as integers (degrees × 100,000, about 1 m) and delta-encoded. Strings are stored once in a shared table.

It also lists every intersection: its CNN, coordinates, and the streets that meet there.

**CNNs:** an intersection's CNN is the same number the streets file uses for segment ends (`f_node_cnn` / `t_node_cnn`), and no CNN is both a segment and an intersection, so one CNN field can hold either.

### How the intersections file is used

`build_data.py` reads `sf_intersections.csv` for the list of streets meeting at each intersection; coordinates come from the street segments, since the CSV has none. For about 615 of the ~9,800 intersections it names a street that no segment touches at that corner. Without the CSV, the build prints a warning and uses names from the segments; everything still works without those extra names.

Not used yet: the `theOrder` column (the city's order of cross streets along each street).

### Neighborhoods (optional)

`python3 scripts/build_data.py --areas` adds one field per neighborhood set: `hood_analysis`, `hood_sffind`, `hood_planning`, `hood_realtor`, `hood_wof`, from the boundary files in `data/boundaries/` (copied from civic-joy-fund/joiner, which downloads them from DataSF; Who's on First from its own data). Each is checked at 25%, 50%, and 75% along the block, so a block on a boundary gets both names ("Mission; Castro/Upper Market", most-covered first). The streets file's own `nhood` is the city's assignment to its realtor-style neighborhoods, and `analysis_neighborhood` its Analysis Neighborhood; both stay as they are.

Use `--slopes --areas` together for the full file.

### Slopes (optional)

`python3 scripts/build_data.py --slopes` adds two fields to every segment: `slope_avg` (start-to-end grade) and `slope_max` (steepest quarter), both unsigned percent × 10, or -1 if unknown. They come from AWS Terrarium elevation tiles at zoom 15 (about 10 m resolution in SF), sampled at five points along the block. The tiles download once into `.tile-cache/`. Block Party uses these for its "flat to moderate" filter.

## Dead ends and one-way streets

Not stored; worked out from the data when it's loaded:

- **Dead end:** an end of a drivable segment where no other drivable street meets it. Paper streets and pedestrian paths don't count as a way through, which matters because the city often continues a street past its last driveable block as a paper segment (20th St past Noe, Cumberland St past Church). A segment's `f_st`/`t_st` repeating its own street name is a hint but not reliable: of about 500 such segments only ~120 are dead ends. About 36 ends touch another street's line with no intersection between them (Comerford St meets Church and Sanchez with no shared corner; several private streets around Stonestown and Sunnyside); Block Party treats an end within 1.5 m of another drivable, non-freeway street as open, and uses that street's name where the city's is a placeholder like "START: 1-99 BLOCK".
- **One-way:** `oneway` = `F` means traffic runs from the `f_st` end to the `t_st` end, `T` the reverse, `B` both ways. The geometry doesn't always run from `f_st` to `t_st`, so compare the line's ends to the from-intersection's location before deciding which way the arrow points.

## The matcher

`scripts/match_blocks.py` turns descriptions into blocks:

- "Sanchez between 27th St and Duncan", "Ford St between 17th/18th, Sanchez and Noe"
- "100 block of Winfield", "600 - 700 block of Shotwell"
- "300 Otsego Ave"
- "Haight and Masonic" (an intersection)
- a short street on its own ("Coventry Court"), and several blocks in one description

Cross streets are checked against the streets that actually meet the named street, so misspellings and missing suffixes usually resolve. It also handles streets with gaps in the city data (matched by position along the street), directional names ("South Van Ness", "West Portal"), and intersections recorded as two nearby points.

Run on a CSV:

```
python3 scripts/match_blocks.py applications.csv                       # writes applications_matched.csv
python3 scripts/match_blocks.py applications.csv --column "Location"   # a different column
```

Output adds: `type` (block or intersection), `cnn`, `nearby_cnns` (for intersections), street, cross streets, address range, supervisor district, neighborhood, `wkt` (LINESTRING / POINT), `confidence` (high / medium / low / none), `method`, and `notes`. A description naming several blocks becomes several rows.

As a library (how sf-striping uses it): `Streets(*load("data/streets.json"))`, then `try_between`, `match_cross`, `candidates`, `intersection`, and `between`.

Standard library only; no installs.

## Updating

1. Download fresh exports from DataSF into `data/` with the same names.
2. `python3 scripts/build_data.py`
3. Bump `VERSION`, update the version in the header line of both scripts, and add a CHANGELOG entry.
4. Copy the changed files into the projects that use them: `data/streets.json`, and `scripts/build_data.py` / `scripts/match_blocks.py` where they have them, updating their header lines to the new version.

## Matching polygons

`scripts/match_polygons.py` takes a GeoJSON file of polygons (drawn in Felt, Selecter, etc.) and lists the blocks and intersections inside each one:

```
python3 scripts/match_polygons.py projects.geojson      # writes projects_cnns.csv and projects_cnns.geojson next to it
```

- **Street strips** (narrower than 35 m, or at least 4 times as long as wide and under 60 m): blocks running along the strip, with half the block inside or an inside stretch covering half the strip. Cross streets that only cut across are left out; their corners are in the intersection list. `full` = 90%+ of the block inside, otherwise `partial`.
- **Areas** (anything wider): blocks in any direction, `full` at 90%+, `partial` from 10%.
- **Intersections**: corners inside the polygon or within 3 m of its edge. Corners where only one block meets are marked `end`.
- **Medians**: a strip with no blocks inside is matched again counting 10 m around it, which catches medians and planting strips between the two sides of a divided street (noted in the `note` column).
- **Off the grid**: a polygon with nothing inside (a parcel, stairs, a plaza) gets the nearest block within 40 m, status `nearest`.
- Felt's text labels (`"felt:type": "Text"`) are skipped.

Thresholds are flags: `--thin-m`, `--max-strip-m`, `--min-partial`, `--near-m`. Standard library only.
