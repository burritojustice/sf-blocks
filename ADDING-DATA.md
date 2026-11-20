# Adding data to sf-blocks

sf-blocks is the one copy of San Francisco's map data that Joiner, Block Party and other maps read live. Anything added here shows up in those apps without changing them (Block Party needs one line; see below). So every change goes through a pull request, where it can be checked before it's live.

## What goes where

| You have | It goes in | Built by |
| --- | --- | --- |
| Areas people join rows to or want to know a block is in: districts, neighborhoods, historic districts | `data/boundaries/` | `scripts/add_boundary_set.py` (below) |
| Points or lines for a map layer: schools, stations, bike lanes | `data/layers/` | `scripts/build_layers.py` |
| Big map layers: street trees, businesses, curbs, building footprints | `data/tiles/` | `scripts/build_tiles.py` (below) |
| A public contact list that goes with areas (published by the city or the group itself) | `reference/<name>/` | by hand, with a README; never private contacts |
| Other names people use for an area ("Calle 24") | `data/aliases.json`, under the set's id | by hand |

Raw downloads and exports always go in `data/uploads/` with their date in the name (`Historic_Districts_20261028.geojson`), and are never edited afterwards.

## Adding a boundary set

Any of these three ways ends with a pull request. Its description lists the fields, says which one names the areas, and links to Joiner reading that branch so you can check it before merging.

### 1. From DataSF, in the browser (anyone with write access)

1. On GitHub, open **Actions → Add areas → Run workflow**, on `main`.
2. Fill in:
   - **Source**: the DataSF dataset id (`63x5-g3m4`) or just paste the dataset's page link.
   - **Id**: lowercase words joined by `_`, plural: `historic_districts`. The apps and links use it, so don't change it later.
   - **Name field**: leave blank the first time. The action picks the field that names each area (a name-like, readable field, not an id).
   - **Title**: leave blank for the dataset's own name, or write the one people know.
   - **Where it goes in Joiner**: Other, unless it's one of the existing kinds.
3. In a minute or two there's a pull request. Open the **Joiner** link in it, choose the set, and check the area list:
   - Names, not numbers or codes? If it picked the wrong field, run the action again on the PR's branch (the **Use workflow from** menu) with **Name field** set from the field table in the PR.
   - The right number of areas? Pieces that share a name become one area, which the PR says.
4. Merge. GitHub Pages updates in about a minute.

### 2. From a file you have (an export, or data that isn't on DataSF)

1. On GitHub, open `data/uploads/` → **Add file → Upload files**. Name the file with its date, then pick **Create a new branch … and start a pull request**.
2. Open **Actions → Add areas → Run workflow**, choose that branch under **Use workflow from**, and put the file's path (`data/uploads/Historic_Districts_20261028.geojson`) in **Source**.
3. The action builds the set on your branch and comments on the pull request with the report. Check it and merge as above.

GeoJSON only, in longitude/latitude (WGS 84). From a shapefile or other formats, convert first (for example at mapshaper.org, "Export → GeoJSON", with "proj wgs84" if it isn't already).

### 3. From the command line

```
python3 scripts/add_boundary_set.py --id historic_districts --source 63x5-g3m4
python3 scripts/add_boundary_set.py --id historic_districts --source data/uploads/Historic_Districts_20261028.geojson
python3 scripts/add_boundary_set.py --id historic_districts --name name_1     # choose the name field
python3 scripts/add_boundary_set.py --id historic_districts                  # refresh from its dataset
```

Then branch, commit, push and open the pull request yourself. `python3 scripts/get_layers.py --help` covers rebuilding sets directly.

### Refreshing a set

Run **Actions → Rebuild data** with **Areas** and the set's id (or the script with just `--id`). It downloads the dataset again, keeps the same name field and settings, and opens a pull request only if something changed.

## Adding fields to a set

Sometimes a set needs more than the city publishes: ids with their leading zeros back, a rate worked out from two fields, totals from a smaller set, or numbers from a different dataset. These go in the set's entry in `data/boundaries/sources.json`, so they're redone every time the set is rebuilt (by the Action or `get_layers.py`):

```json
"pad":     { "geoid20": 15 },
"numbers": ["pop20", "housing20", "aland20"],
"rollup":  { "from": "census_blocks", "by": "tractce20", "to": "tractce", "sum": ["pop20", "housing20", "aland20"] },
"derive":  { "density": { "divide": ["pop20", "aland20"], "times": 2589988.11, "round": 0 } },
"choropleth": { "prop": "density", "label": "People per sq mi", "palette": "viridis", "breaks": [5000, 10000, 20000, 40000, 80000, 160000] }
```

- **`pad`** zero-pads ids back to their width. Census ids that went through a number column lose their leading zero and stop matching.
- **`numbers`** keeps counts as numbers rather than text.
- **`rollup`** adds up another set's fields into this one (blocks into tracts). That set must come earlier in `sources.json`.
- **`derive`** divides one field by another (here people per square mile; land area is in square metres).
- **`choropleth`** tells Joiner and Block Party which field to color the set by, its name, palette and class breaks (here each break doubles the last, a log scale). Without `breaks`, the apps use quantiles.

Edit the entry in a pull request, then run **Rebuild data** (Areas, the set's id) on that branch to rebuild it.

**Data from somewhere else** (school enrollment from the state, say) is a different case: it's its own dataset with its own source and date. The plan is to save it in `data/uploads/` like any download, and add a `"join"` step that matches it to the set by a shared key (the school's CDS code) and copies the chosen fields in. It isn't built yet.

## Adding a map layer

For points, lines or polygons people look at on the map rather than join rows to: trees, businesses, curbs, building footprints.

1. **Actions → Add a map layer → Run workflow**: the DataSF dataset (its link or id), a short **id** (`street_trees`), and the **year** the data describes (`2016`, or blank for current). Socrata's "updated" date can be years after the data itself (building footprints say 2026; they're from 2016), so check it.
2. One run does everything. It reads the dataset's fields and suggests what to keep (readable, mostly filled, not system fields), which text fields to use as **categories** (a few values that repeat: status, type), and, for a point dataset with a `cnn` field, to draw the streets instead of points. It writes that as the layer's own file, `data/tiles/sources/<id>.json`, downloads every row, and builds `data/tiles/<id>.pmtiles` (or `.geojson` when small: under 20,000 features and 5 MB), `<id>.stats.json` and the manifest `index.json`. The raw download goes in `data/uploads/` when it's under 10 MB, and otherwise into a GitHub release (archived, not served to the apps).
3. Its pull request has the build report, the field report (each field's type, how often it's filled, distinct values, examples, keep or drop), and **preview links**: Joiner and Block Party reading that branch, so you can see the layer before merging.
4. To change something, edit `data/tiles/sources/<id>.json` on the pull request's branch (GitHub's pencil button is fine). Saving it **rebuilds the layer by itself** and adds a commit to the pull request:
   - `fields`: remove what you don't want, and set each one's type, `int`, `num1` (one decimal), `date`, `id` (a number that's an identifier) or `text`. `"a|b"` uses the first of two fields with a value.
   - `categories`: fields to count each value of (species, license type), for chips and legends.
   - `geometry`: for a dataset keyed by street, `{"cnn": "cnn"}` draws each row as that street's line from `data/streets.json` (a corner's CNN as its point) instead of the dataset's point; `{"cnns": "<field>"}` takes a field listing several CNNs. Add `"stack_by_cnn": {"keep": ["status", …]}` so rows on the same street become one line with `n` rows, the most common value of each `keep` field, and every row in `items`.
   - `enrich`: fields added on every build, so refreshing from DataSF keeps them. `{"elevation": {"field": "elev_m"}}` adds ground height in meters (Terrarium tiles, the same as Block Party's slopes; about 1 m accurate, NAVD88-like); `{"cnn": {"field": "cnn", "within_m": 30}}` the nearest street block; `{"areas": {"supervisor_districts": "district"}}` the area each feature is in; `{"extra": {"file": "data/uploads/<id>/extra.csv", "key": "<id field>"}}` hand-made columns joined by id (rows the city later drops just fall out). Lengths and heights are stored in meters, and the manifest's `units` says so; the apps show feet or meters.
   - `tiles`: `minzoom` / `maxzoom` for full detail (15, like Parcels, by default), and an optional `overview` (zooms 10–14 with only a few fields, thinned where dense) to show the spread when zoomed out.
5. Merge. The **Check data** check fails if a layer the pull request adds or edits isn't built from its current entry, so a layer can't be merged without its files.

To refresh a layer from its dataset, run **Actions → Rebuild data** with **Map layer** and its id. **Rebuild data** also rebuilds the search index, the OSM ways and the street facts (no id needed). Older layers' entries are in `data/tiles/sources.json`; new ones each get a file in `data/tiles/sources/`, so two pull requests adding layers never touch the same lines.

**Stats** (`<id>.stats.json`): for each number and date field, min, max, mean, median, standard deviation and quantile breaks for 5, 7 and 10 classes (dates also by year); for each category field, how many rows have each value (the top 60, then a count of the rest). The apps use these for legends, palettes and chips without reading the tiles.

**Layers keyed by street** (`geometry: {cnn}`, like the utility excavation permits): the dataset's latitude and longitude are only one point per CNN, so each row is drawn as the street it's on. The manifest entry has `"join": "cnn"` (apps match it by id, not by location) and `cnn_missing`, the rows whose CNN isn't in `streets.json` (retired streets); those keep their own point. The build report says how many.

**Businesses** are grouped by address, then stacked: addresses the city puts on the same point (neighbors like 1601 and 1603 Church, the suites of one building) become one point, each business keeping its own `address` in `items`. So one point per spot, with `n` businesses and each one's name, owner, mailing address, license and start date in `items`. They come from Registered Business Locations (open locations), which carries each business's NAICS code, so each gets a category (food & drink, retail, services, other) and sector. Owners that aren't storefronts you'd hand a notice to (cafeteria contractors, parking operators, antennas, ATMs, landlords) are labelled from the reviewed list `data/tiles/business_kinds.json` (by owner, or by NAICS code: 5311 for landlords); any other owner at 25+ addresses gets "Registered at many addresses" until it's added to `owners` or `storefronts` there. Each build's report lists new ones (companies by name; people only counted).

## After it's merged

- **Joiner:** the set appears right away in the tab given (Other by default), named by its title. Nothing to change in Joiner.
- **Block Party:** to show it as a map layer and a card row ("Historic district: Liberty-Hill"), add one line to `AREA_LAYERS` near the `Areas` module in Block Party's `index.html`, with a short key, the set id and a color: `{ k: 'historic', set: 'historic_districts', color: '#A8441B', layer: 'Historic districts', row: 'Historic district' }`. If you want it in Block Party's offline backup too, add `data/boundaries/<id>.geojson` to its `data/sf-blocks.json`.
- **Backup copies:** each app keeps copies for when sf-blocks can't be reached. Its **Refresh sf-blocks copies** action runs every Monday (or by hand) and opens a pull request when sf-blocks changed.

## Rules

- **Pull requests, not direct commits to `main`.** The apps read `main` live; the **Check data** action runs on every pull request you open, and the actions start it on the pull requests they open.
- **Don't rename or move published files.** Live links would break. Add the new path, update the apps, then remove the old one.
- **Public data only.** No names, emails or phone numbers of private people, except in registries the city itself publishes (Active Business Locations), which are kept because they're how organizers reach their neighbors. Other contact lists only when the city or the organization publishes them, with `source_url` and `checked` columns.
- **Note the source.** The set's `page` in `sources.json` links to where it came from; the action fills it in for DataSF.
- **Version:** don't edit `VERSION` or `CHANGELOG.md` in a pull request. Add a note in `changes/<name>.md` (one `- ` line per change); the actions do this themselves. After the merge, the **Stamp version** action sets `VERSION`, moves the notes into `CHANGELOG.md` and stamps the changed scripts' first lines (`changes/README.md`).

## Repository settings the actions need

In each repo (sf-blocks, Joiner, Block Party): **Settings → Actions → General → Workflow permissions**: choose **Read and write permissions** and tick **Allow GitHub Actions to create and approve pull requests**.

## Not automated (yet)

- **Block Party's `AREA_LAYERS` line** is by hand, because color and wording are choices. sf-blocks could carry them per set in `sources.json` so Block Party picks sets up on its own.
- **People without write access** can't run actions. They could open an issue with a form ("Suggest a boundary set": dataset link, name field) that a maintainer turns into a run.
- **Scheduled refreshes** of DataSF sets that change (precincts after redistricting, say) could run monthly; most sets change rarely.
