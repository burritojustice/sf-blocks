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

1. On GitHub, open **Actions → Add or refresh a boundary set → Run workflow**, on `main`.
2. Fill in:
   - **Set id**: lowercase words joined by `_`, plural: `historic_districts`. The apps and links use it, so don't change it later.
   - **Source**: the DataSF dataset id (`63x5-g3m4`) or just paste the dataset's page link.
   - **Name field**: leave blank the first time. The action picks the field that names each area (a name-like, readable field, not an id).
   - **Title**: leave blank for the dataset's own name, or write the one people know.
   - **Joiner tab**: Other, unless it's one of the existing kinds.
3. In a minute or two there's a pull request. Open the **Joiner** link in it, choose the set, and check the area list:
   - Names, not numbers or codes? If it picked the wrong field, run the action again on the PR's branch (the **Use workflow from** menu) with **Name field** set from the field table in the PR.
   - The right number of areas? Pieces that share a name become one area, which the PR says.
4. Merge. GitHub Pages updates in about a minute.

### 2. From a file you have (an export, or data that isn't on DataSF)

1. On GitHub, open `data/uploads/` → **Add file → Upload files**. Name the file with its date, then pick **Create a new branch … and start a pull request**.
2. Open **Actions → Add or refresh a boundary set → Run workflow**, choose that branch under **Use workflow from**, and put the file's path (`data/uploads/Historic_Districts_20261028.geojson`) in **Source**.
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

Run the action (or the script) with just the **Set id**. It downloads the dataset again, keeps the same name field and settings, and opens a pull request only if something changed.

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

Edit the entry in a pull request, then run the Action with just the set id to rebuild it.

**Data from somewhere else** (school enrollment from the state, say) is a different case: it's its own dataset with its own source and date. The plan is to save it in `data/uploads/` like any download, and add a `"join"` step that matches it to the set by a shared key (the school's CDS code) and copies the chosen fields in. It isn't built yet.

## Adding a map layer

For points, lines or polygons people look at on the map rather than join rows to: trees, businesses, curbs, building footprints.

1. **Actions → Add or refresh data → Run workflow**, Kind **Map layer**, a new **Set id** (`street_trees`), the DataSF dataset in **Source**, and the **Year** the data describes (`2016`, or `current`). Socrata's "updated" date can be years after the data itself (building footprints say 2026; they're from 2016), so check it.
2. The first run doesn't build anything. Its pull request has a **field report** (each field's type, how often it's filled, how many distinct values, examples, and keep or drop) and a size estimate, and adds a first entry for the layer to `data/tiles/sources.json`.
3. On the PR's branch, edit that entry:
   - `fields`: remove what you don't want, and set each one's type, `int`, `num1` (one decimal), `date`, `id` (a number that's an identifier) or `text`. `"a|b"` uses the first of two fields with a value.
   - `categories`: fields to count each value of (species, license type), for chips and legends.
   - `tiles`: `minzoom` / `maxzoom` for full detail (15, like Parcels, by default), and an optional `overview` (zooms 10–14 with only a few fields, thinned where dense) to show the spread when zoomed out.
4. Run the action again **on that branch** with the same id. It downloads every row, keeps the chosen fields, and writes `data/tiles/<id>.pmtiles` (or `.geojson` when small: under 20,000 features and 5 MB), `<id>.stats.json` and the manifest `index.json`. The raw download goes in `data/uploads/` when it's under 10 MB, and otherwise into a GitHub release (archived, not served to the apps).
5. Check the report in the PR, then merge.

A layer already in `sources.json` is rebuilt from its dataset whenever the action runs with its id.

**Stats** (`<id>.stats.json`): for each number and date field, min, max, mean, median, standard deviation and quantile breaks for 5, 7 and 10 classes (dates also by year); for each category field, how many rows have each value (the top 60, then a count of the rest). The apps use these for legends, palettes and chips without reading the tiles.

**Businesses** are grouped by address: one point per address, with `n` businesses and each one's name, owner, mailing address, license and start date in `items`. Owners that aren't storefronts you'd hand a notice to (cafeteria contractors, parking operators, antennas, ATMs, landlords) are labelled from the reviewed list `data/tiles/business_kinds.json`; any other owner at 25+ addresses gets "Registered at many addresses" until it's added to `owners` or `storefronts` there. Each build's report lists new ones (companies by name; people only counted).

## After it's merged

- **Joiner:** the set appears right away in the tab given (Other by default), named by its title. Nothing to change in Joiner.
- **Block Party:** to show it as a map layer and a card row ("Historic district: Liberty-Hill"), add one line to `AREA_LAYERS` near the `Areas` module in Block Party's `index.html`, with a short key, the set id and a color: `{ k: 'historic', set: 'historic_districts', color: '#A8441B', layer: 'Historic districts', row: 'Historic district' }`. If you want it in Block Party's offline backup too, add `data/boundaries/<id>.geojson` to its `data/sf-blocks.json`.
- **Backup copies:** each app keeps copies for when sf-blocks can't be reached. Its **Refresh sf-blocks copies** action runs every Monday (or by hand) and opens a pull request when sf-blocks changed.

## Rules

- **Pull requests, not direct commits to `main`.** The apps read `main` live; the **Check data** action runs on every pull request you open, and the Add action runs the same checks on its own pull requests.
- **Don't rename or move published files.** Live links would break. Add the new path, update the apps, then remove the old one.
- **Public data only.** No names, emails or phone numbers of private people, except in registries the city itself publishes (Active Business Locations), which are kept because they're how organizers reach their neighbors. Other contact lists only when the city or the organization publishes them, with `source_url` and `checked` columns.
- **Note the source.** The set's `page` in `sources.json` links to where it came from; the action fills it in for DataSF.
- **Version:** the action bumps `VERSION` and adds a `CHANGELOG.md` entry. By hand, do the same.

## Repository settings the actions need

In each repo (sf-blocks, Joiner, Block Party): **Settings → Actions → General → Workflow permissions**: choose **Read and write permissions** and tick **Allow GitHub Actions to create and approve pull requests**.

## Not automated (yet)

- **Block Party's `AREA_LAYERS` line** is by hand, because color and wording are choices. sf-blocks could carry them per set in `sources.json` so Block Party picks sets up on its own.
- **People without write access** can't run actions. They could open an issue with a form ("Suggest a boundary set": dataset link, name field) that a maintainer turns into a run.
- **Scheduled refreshes** of DataSF sets that change (precincts after redistricting, say) could run monthly; most sets change rarely.
