# Changelog

## 2026.11.13.8
- Proposed map layer `bus_stops` (fields to review)

## 2026.11.13
- Proposed map layer `storm_drains` (fields to review)

## 2026.11.12
- **`matcher/google-drive.js`:** `createSheet()` also returns the new sheet's tabs with their ids, which Block Party's project sheets use to link to each tab.
- `VERSION` held two lines after #38 and #39 merged; it's one again.

## 2026.11.11.8
- **`matcher/google-drive.js`:** `createSheet(title, tabs)` makes a new Google Sheet in the person's Drive (still only the drive.file permission), for Block Party's Save to Google Sheets. Nothing else changes.
## 2026.11.11.7
- **Street facts** (new, `scripts/build_facts.py`, standard library): what each street block's card shows, worked out ahead of time so apps don't have to read tiles and boundaries for every card. One row per CNN (17,176), built from files already here and matching Block Party's cards exactly on the blocks checked (Valencia, Holloway, …):
  - `data/facts/streets.json` (1.8 MB, 0.47 MB gzipped): lots, homes, land use and zoning (parcels within 14 m, or 25 m on the same street); street trees by name; businesses (storefronts shown, addresses, and those hidden as not storefronts, by kind); people and homes from the 2020 census blocks; and the Supervisor, Assembly, State Senate, US House, BART, CBD, Cultural and Historic districts.
  - `data/facts/lots.json` (1.9 MB, 0.38 MB gzipped): each block's lot ids and census blocks, for growing a selection and for exports, so apps load it only then.
  - Intersections aren't in it: their cards add up half of each street, which apps still do from the tiles.
- `region.json` has `facts` pointing at both files.
- **"Add or refresh data" → Kind: Street facts** rebuilds them. They also rebuild by themselves after a Map layer build of street trees or businesses, or a Boundary set build of census blocks or a district set. Takes about 7 minutes.

## 2026.11.11.6
- **OSM ways** (2026-11-10): 135,428 pieces from 65,763 ways; 94,219 run along no city street (`data/osm/ways.pmtiles`, `data/osm/gaps/`). © OpenStreetMap contributors, ODbL.

## 2026.11.11
- **OSM ways** (new, `scripts/build_osm.py`, standard library): OpenStreetMap's streets, alleys, paths, bike paths, stairs, sidewalks and crosswalks in San Francisco, split where they meet, each piece with a lasting id (`w<way>:n<first node>-n<last node>`) and the CNNs of the city street it runs along, if any. For picking paths the city's street file doesn't have (Golden Gate Park, SF State, the Presidio) and separated bike paths (O'Shaughnessy).
  - Writes `data/osm/ways.pmtiles` (every piece, each its own feature with its id; sidewalks from zoom 15), `data/osm/gaps/<way id % 16>.json` (the pieces that run along no city street, by id, so an app can draw a picked one) and `data/osm/index.json`.
  - **"Add or refresh data" → Kind: OSM ways** builds it: downloads Geofabrik's Northern California extract, clips it to the city with osmium, keeps `highway=*` ways (sidewalks included), runs the script and tippecanoe, and reports counts by kind, how many run along a city street, sizes with and without sidewalks, and gap pieces in Golden Gate Park, SF State, along O'Shaughnessy and in the Presidio.
  - Data © OpenStreetMap contributors, under the ODbL; the derived files are too.

## 2026.11.10
- **Search index** (`data/search/`, new) for the apps' Address / Places search, built by the new `scripts/build_search.py` (standard library):
  - `businesses.json`: 100,485 open business locations in the city (DataSF `g8m3-pdis`, 2026-11-10): name, owner when it differs, address, self-reported NAICS code, kind (from `business_kinds.json`, so non-storefronts can rank last) and the point.
  - `addresses/<first character>.json`: 224,348 addresses on 2,066 streets from the Enterprise Addressing System (`3mea-di5p`, 2026-11-09), each with its point, lot and CNN. Split by the street name's first character so an app loads only the street it needs (`index.json` maps each street to its file).
  - `landmarks.json`: 186 named places from the same list (City Hall, …).
  - `naics.json`: the 2022 NAICS titles (2,129 codes, 2 to 6 digits), so "restaurants" can find NAICS 7225. The workbook is kept as `data/uploads/naics_2022_codes.xlsx`.
- `region.json` has `search` pointing at `data/search/index.json`.
- **"Add or refresh data" can rebuild it:** Kind **Search index**.

## 2026.11.08.2
- **Businesses tiles rebuilt** with the per-category counts from 2026.11.08.1: 42,862 addresses from 101,038 registrations in the region (DataSF `g8m3-pdis`, 2026-11-08).
- **"Add or refresh data" fixed for map layers:** it asked for tippecanoe tag 2.82.0, which doesn't exist (the project's tags stop at 2.79.0 though its code says 2.82.0). It now fetches that exact commit (`4f26211`), the same build used here.

## 2026.11.08.1
- **Businesses: counts by category on each dot.** `scripts/build_tiles.py` has a new group option, `counts`. With `"counts": "cat"` (now on for businesses), each address carries `n_food`, `n_retail`, `n_services`, `n_other` (all registrations) and `shown_food` … `shown_other` (storefronts), added up when addresses are stacked on one point. The overview zooms keep them too (an overview field ending in `*` takes every field it starts). Block Party uses them to size and show a dot by the categories you've picked, so two restaurants among 50 offices shrink to a small food dot. **The businesses tiles need a rebuild to get the new fields:** run "Add or refresh data" (Kind: Map layer, id `businesses`), or wait for the next refresh.

## 2026.11.07.5
- **Matcher: parcels.** SF Planning's parcels (the same pmtiles file Block Party uses, 2023 land use and zoning):
  - **Parcels** button on the map: lot lines from zoom 15.
  - **Pick parcels when fixing:** the fix bar has Streets | Parcels. Click lots to add them to a row (new `parcels` and `parcel_addresses` columns, kept alongside the block or intersection) or to a polygon, or click again to take them out. Hovering shows the address, land use and homes.
  - **List the parcels in each polygon:** a checkbox under "List for each polygon". Each lot whose middle is inside becomes a row with `type` parcel, its `blklot`, address, `landuse` and `homes`, and the polygon's GeoJSON gets a `parcels` list. In the polygon's details, parcels can be removed like blocks.
  - The selected row's or polygon's parcels are tinted on the map.

## 2026.11.07.4
- **Matcher learns from fixes.** After you fix rows on the map, the Results card offers **Share with sf-blocks**, which opens GitHub with your fixes as a new file in `tests/corrections/` to propose, or **Save fixes**. Only the location text and the CNNs go in.
- **`scripts/test_matcher.py`** runs every fix through `match_blocks.py`: how many it gets right, `--failing` for the ones it still gets wrong (the to-do list for the matcher), `--update` to record a new baseline. The pull-request check now runs it too, so a change that breaks a fix it used to get right fails the check.
- `tests/corrections/2026-11-07-examples.csv` starts it off with today's cases (Mt Vernon, Embarcadero, Octavai, Mision, and "near school", which it still gets wrong).

## 2026.11.07.3
- **Column guessing (`--suggest`, and Matcher's column notes) no longer takes a notes column for locations.** A lone street name no longer counts as a location ("near school" was finding School Alley), and short values count against a column, so "busy", "red zone" and "near BART" don't add up to "locations 100%". Real location columns score the same as before.

## 2026.11.07.2
- **match_blocks.py reads "Mt", "Ft" and "Pt" as Mount, Fort and Point** at the start of a street name, like "St" for Saint. "Cayuga and Mt Vernon" was matching Vernon St (which doesn't meet Cayuga) instead of Mount Vernon Ave.
- **"Embarcadero" is The Embarcadero** without a spelling note or lower confidence.
- **A misspelled cross street is looked for among the streets that cross the other one,** so "Hayes & Octavai" finds Hayes and Octavia (medium confidence, with a note). In a 4,000-row test, 19 rows that had no match or only a street now match an intersection; nothing else changed.
- **Matcher: Save to Google Sheet.** For a Sheet opened from Google Drive: a new tab with the results (asks before replacing one from an earlier save), or Matcher's columns added to the original tab after checking the tab still lines up with what was loaded.
- **Matcher: fix misspellings in your own columns.** When the matcher read "Mision" as Mission, the Results card offers to fix the spelling in your column too, in every save.
- **Matcher: fixing a row on the map shows street names,** because the lines are now drawn under the basemap's labels and the results fade while you pick. The fix bar says what the row will change to ("Change to CNN 22091000, Cayuga Ave and Mount Vernon Ave").
- **Matcher: the table shows the rest of your columns** after Matcher's own ("Your columns" turns them off).
- Matcher: the column menu opens wider so more sample values show; the avatar is in the top left; Open in Block Party passes intersections too; new description.

## 2026.11.07
- **Matcher: column menus show what's in each column.** Each entry has the column's name and number, what the matcher thinks is in it ("street names 100%"), and a few sample values in smaller type.
- **Matcher: the real header row is found** when a sheet has a title or note above it, instead of naming the columns "column 1, column 2…".
- **Matcher: Open in Joiner and Open in Block Party.** Joiner gets the results as if the GeoJSON had been dropped on it; Block Party opens with the matched blocks selected.
- "One column describes each location" is now "Location info is in one column", to match "Street and cross street are in separate columns".
- Matcher README: the Google setup steps now include what got sign-in working: one app name, no logo, a home page that loads, and nothing submitted for verification.

## 2026.11.06.4
- **Matcher: Open from Google Drive is turned on** for burritojustice.github.io (`matcher/google.json` has the Google Cloud values).
- **Matcher README: the Google setup steps match today's Google Cloud console.** Sign-in settings are now under Google Auth Platform (Branding, Audience, Data Access, Clients); the API key is under APIs & Services › Credentials. Adds the `https://docs.google.com/*` website the key needs for the picker, how to tell the project number from the project ID, and a table of common errors.
- **Assessor blocks** (`assessor_blocks`, 5,413): the city's assessor blocks, made by joining the active lots in DataSF's Parcels – Active and Retired (`acdm-wktn`, 227,969 lots) by `block_num`. Each block has `block_num` ("0587", "2494A") and `parts` (how many lots). They're tighter than census blocks and match how lots are numbered (`mapblklot` starts with the block). 67 blocks whose lots leave gaps too wide to close stay as their separate lots; blocks split by an alley are two shapes. About 3.4 MB.
- **`get_layers.py` can narrow and page a download, and dissolve a set by its own field.** In `sources.json`, `select` and `where` (SoQL) narrow the download, which then comes in pages of 50,000. `dissolveBy` joins the downloaded features by one of their fields. Lots join with their own dissolve: coordinates snapped to about 10 cm, edges split where a neighbor's corner touches them, condos stacked on one footprint counted once, small gaps closed, holes under 2,000 m² dropped, and outlines simplified to 0.4 m. `--file` takes several files joined with commas. The precinct dissolve is unchanged.

## 2026.11.06.3
- **Matcher's icon is now four big puzzle pieces:** three teal and one magenta, filling the whole icon, with see-through gaps so it works on light and dark tab bars. The roads are gone. The phone home-screen icon puts it on white.
- **Browsers pick up icon changes.** The icon links carry a version (`favicon.svg?v=7`), so browsers fetch the new icon instead of showing the one they saved. Bump it whenever the icon changes.

## 2026.11.06.2
- **Matcher has an icon.** Four puzzle pieces fitted together over two crossing streets, with the fourth piece in yellow: blocks fitting into the street grid. `matcher/favicon.svg` for browser tabs, 16 and 32 px PNGs for browsers without SVG icons, and a 180 px `apple-touch-icon.png` for phone home screens.

## 2026.11.06
- **Matcher: Open from Google Drive.** Google's own file picker: pick a Google Sheet (every tab comes in, and the Sheet menu picks the one with the most rows) or a CSV, Excel or GeoJSON file stored in Drive. It asks only for permission to open the files you pick. It needs a one-time Google Cloud setup; the values go in `matcher/google.json`, and the steps are in `matcher/README.md`. `matcher/google-drive.js` is self-contained so Joiner and Block Party can copy it.
- **Matcher: Satellite.** A Map / Satellite switch on the map (Esri World Imagery under the street labels). It remembers your choice.
- **Matcher: remove single blocks and intersections from a polygon.** Click a matched polygon in the table to list its blocks and intersections; click one to see it on the map, Remove to take it out, or Remove all intersections. Fix on the map now adds or removes intersections too, not just blocks.
- **Matcher: Start over** clears everything without reloading the page. After a file loads, the Load card shrinks to one line (the file name, Load another, Start over), and the sidebar scrolls so each new step is in view down to its buttons, Save included.

## 2026.11.05.4
- **Matcher: choose the polygons before matching.** After a GeoJSON loads, the table lists its polygons with their areas. Select them with the checkboxes or by clicking on the map, then **Delete selected** (Bring back undoes it), **Keep as polygons** (saved as they are, with no matching), or **Match these**.
- **Matcher: blocks only, or blocks and intersections.** A choice under "List for each polygon". The command line has the same choice: `match_polygons.py --no-intersections`.
- **Matcher: "Just a polygon".** After matching, Fix on a polygon offers Just a polygon, for shapes that aren't about streets; Change the polygon list goes back to the list. Kept polygons are saved with their own properties, `shape: polygon only`, and no blocks.

## 2026.11.05.3
- **Matcher suggests the columns.** After a file loads, it looks through the first 80 rows of every column for street names, pairs of street names ("Bush and Sutter") and locations it can match, then picks the columns and labels each one ("Corridor · street names 100%", "Where is it · locations 90%"). Headers don't have to say "Street" or "Location". A column you've already picked is left alone.
- **Matcher: clicking a polygon before Match no longer clears the map.**
- **Matcher:** the note when Safari 18 falls back to the older Python is now a quiet console message.
- **`match_blocks.py --suggest`** prints the same column report and suggestion for a CSV. New library functions `column_report()` and `suggest_columns()`; matching itself is unchanged (byte-identical on 4,000 test rows).

## 2026.11.05.2
- **Matcher works on Safari 18.** Pyodide 314 crashes while starting there ("Out of bounds memory access"); Safari 26, Chrome and Firefox are fine. When Python fails to start, Matcher now starts again with Pyodide 0.27 (Python 3.12), which gives the same results; tested identical to the command line. If neither starts, it says to update the browser or try Chrome or Firefox.

## 2026.11.05.1
- **Matcher** (`matcher/`, at https://burritojustice.github.io/sf-blocks/matcher/): a web page that runs `match_blocks.py` and `match_polygons.py` in the browser with Pyodide. Drop in a CSV, Excel workbook or GeoJSON, paste a link or rows, pick the columns, and see the results on a map and in a table, with the rows that need a look first. Fix a row by clicking the right block or intersection, or mark it as no match; for polygons, add or remove blocks. Save as CSV (the command line's columns), GeoJSON or Excel. Files never leave the browser.
- **`match_blocks.py` streams:** `match_rows()` matches one row at a time and yields its results, and the command line writes each row as it's matched instead of reading the whole file first. `manual()` gives the output columns for blocks or intersections picked by hand. Output is byte-identical to before.
- **`match_polygons.py` streams too:** `match_features()` yields each polygon's rows and feature; output is byte-identical.
- **About 4 times faster:** the fuzzy spelling search skips street names too long or short to pass its cutoff, and looks each spelling up once. Same answers: 4,000 test rows go from 21.5 s to 4.9 s with identical output.

## 2026.11.05
- **`match_blocks.py` reads streets from two columns:** `--street Street --cross Cross` for a CSV where the street and cross street are already split out. One cross street is matched as an intersection ("Hayes" / "Octavia"); two ("Sansome" / "Bush and Sutter") as the block between them, and `--cross2` takes the second from its own column. Spelling fixes work as before ("Divisdero" → Divisadero). The free-text `--column` mode is unchanged.

## 2026.11.04.1
- **Businesses stacked by point:** the city puts many addresses on the same point (1601 and 1603 Church St; every suite of an office building; mailbox stores like 548 Market St with 250 addresses). About half of all business addresses shared a point with another, so one dot hid the others. With `"stack": true` in a layer's `group`, groups on the same point become one feature: `n`, `shown`, color and label cover them all (storefronts first, then by street number), `addresses` counts the addresses, and each item in `items` carries its own `address`. Points with one address are unchanged.

## 2026.11.04
- **Businesses from Registered Business Locations** (`g8m3-pdis`), limited to open locations (no location or business end date): the same 127,981 rows as Active Business Locations, plus what that view leaves out:
  - **Industry:** each business's self-reported NAICS code (`naics`, filled for 79%) and its sector (`sector`: Retail, Real estate and rental, Professional services…).
  - **Category** (`cat`): food & drink (by license or NAICS 722), retail (44–45), services (81: hair, nails, repair, laundry…), or everything else. Each address point is colored by its most storefront-like business: food, then retail, services, other. In SF: 8,556 food, 4,700 retail, 5,953 services, 81,704 other.
  - **Mailing city and ZIP** (`mail_place`), when the mailing address isn't the business's own.
- **Landlords by industry:** `business_kinds.json` gains `naics`: every business coded 5311 (lessors of real estate: people and companies registering rentals, 11,821 in SF) gets the kind "property", hidden in Block Party until "Show all registrations".
- `build_tiles.py`: a layer can have a `where` filter for its download, `empty_with`, and fields joined with `+`.

## 2026.11.03.2
- **Business names on each address point:** `name` (the first storefront's business name) and `name_all` (the first of any), so the apps can label addresses on the map without reading the `items` list. `businesses.pmtiles` is 5.5 MB (was 4.6).
- **No personal names as labels:** a business name is used for a label only when it reads as a company (Inc, LLC, Co…) or differs from the owner's name. A sole proprietor's or landlord's own name ("Anne Perkins" for owner "Perkins Anne M") is left off the map; it stays on cards and in exports. In a Mission tile, 1,030 of 1,308 points get a label. A few bare personal names still get through (a stylist's name under a salon's registration, say).
- The placeholder business name "Same As Ownership" is dropped, like "N/A".

## 2026.11.03
- **Map layers** in `data/tiles/`, built by the new `scripts/build_tiles.py` from `data/tiles/sources.json`, and listed in `region.json` as `tiles`:
  - **Street trees** (`street_trees.pmtiles`, 4.8 MB): 138,778 trees with species, genus, trunk diameter, status, planted date, site, caretaker, CNN and address. Current.
  - **Businesses** (`businesses.pmtiles`, 4.6 MB): 100,913 businesses at 69,727 addresses, grouped by address, with business name, owner, mailing address, license, start date, and a food / licensed / other category. Owners that aren't storefronts are labelled from `business_kinds.json`. Current.
  - **Curbs and islands** (`curbs.pmtiles`, 2.7 MB, zooms 13–17): 7,195 lines. 2016.
  - **Building footprints** (`buildings.pmtiles`, 8.3 MB): 177,023 buildings with id, block and lot, height, ground level and peak, in metres. 2016, heights from 2010 LiDAR.
  - Each has a stats file: numbers and dates (min, max, mean, median, std dev, quantile breaks, dates by year) and category counts.
- **"Add or refresh data"** (was "Add or refresh a boundary set"): a Kind choice, Boundary set or Map layer. A new map layer's first run proposes its fields (field report and a draft entry in `sources.json`), and a second run on the branch builds it; big raw downloads are archived as releases. tippecanoe is built once and cached.
- **Contact data:** city-published registries are kept, owner names and mailing addresses included (see CLAUDE.md and ADDING-DATA.md).

## 2026.11.02.2
- **Density breaks:** the census sets' `choropleth` has `breaks` (5,000 · 10,000 · 20,000 · 40,000 · 80,000 · 160,000 people per sq mi). Each class doubles the one before (a log scale), and Joiner and Block Party both use them, so the same block gets the same color in both.
- **The Add action checks its own pull request.** GitHub doesn't run other workflows on a pull request an action opened, so "Check data" never ran on them (it showed as failed with no steps). The action now runs the same checks before it opens the pull request, and the report says they passed.

## 2026.11.02
- **Census blocks 2020** (`census_blocks`, DataSF p2fw-hsrv): 5,986 blocks with population (`pop20`), housing units (`housing20`), land area (`aland20`, m²) and people per square mile (`density`). Block and tract ids have their leading zeros back (`060750101011001`, tract `010101`), so they match other census data by GEOID.
- **Census tracts** now carry `pop20`, `housing20`, `aland20` and `density`, summed from the blocks (both total 873,965 people).
- `get_layers.py` can add fields to a set, set in `sources.json`: `pad` (zero-pad ids), `numbers` (keep counts as numbers), `rollup` (sum another set's fields, like blocks into tracts) and `derive` (one field divided by another, like density). `choropleth` tells the apps which field to color a set by, and how. See ADDING-DATA.md.
- `add_boundary_set.py` keeps up to 12 fields (was 6) and skips shape sizes, label points and load times, so counts like `housing20` aren't left out.

## 2026.10.30
- Added boundary set `community_benefit_district` (Community Benefit Districts): 16 areas named by `community_benefit_district`, from DataSF [c28a-f6gs](https://data.sf.gov/d/c28a-f6gs). Raw copy: `data/uploads/Community_Benefits_Districts_20261030.geojson`.

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
