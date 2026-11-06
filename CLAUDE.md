# sf-blocks: notes for Claude

The **main copy** of San Francisco's map data: boundaries, aliases, city layers, street blocks, public reference lists, and the scripts that build them. Joiner and Block Party (burritojustice is the primary home of both; civic-joy-fund runs its own copies) and burritojustice/sf-striping load files **live** from this repo's GitHub Pages site and keep a **backup copy** each, stamped with the sf-blocks version. Other cities would get their own repo with the same layout. Read `README.md` for the data format and definitions, and `CHANGELOG.md` for history.

## Working rules

- **Ship as a PR:** make a branch, commit, push it, and open the PR (`gh api repos/burritojustice/sf-blocks/pulls -f head=<branch> -f base=main ...`; GraphQL is blocked here).
- **Check a PR is still open before pushing to its branch** (`gh api repos/burritojustice/sf-blocks/pulls/<n> --jq .merged_at`). A commit pushed after the merge never reaches `main`, and editing the closed PR hides it. If it was merged, branch from `main`, cherry-pick, and open a new PR.
- **Version every change:** bump `VERSION` (date style, `2026.10.23`), the version in each changed script's first line, and add an entry at the top of `CHANGELOG.md`. Docs-only changes don't need it.
- **Change here first:** then copy the files into Block Party (and other users) with their "Copied from burritojustice/sf-blocks <version>" header, and open a PR there too.
- **Dates are YYYY-MM-DD:** `build_data.py`'s `ymd()` normalizes both the API's and the Export's date formats.
- **Standard library only:** the Python scripts use no other packages, so anyone can run them.
- **Keep streets.json the full build:** the committed file is the `--slopes --areas` build. Don't replace it with a plain build that drops those fields.

## Layout

- `region.json`: what an app needs to open the region (home view, bbox, basemap keys, paths).
- `data/boundaries/`: polygons to join to; `index.json` manifest, `sources.json` build config (copied from Joiner's `config/layers.json`; its `tab` and label fields are Joiner display settings).
- `data/aliases.json`: the one list of other names for areas, by boundary set id. Don't add aliases anywhere else.
- `data/layers/`: city points, lines and polygons; built by `build_layers.py` from `data/uploads/`.
- `data/uploads/`: raw downloads and exports, dated names, never edited by hand.
- `reference/`: public contact lists only (published by the city or the organization). Never private contacts.
- `data/tiles/`: map layers built by `scripts/build_tiles.py` from `sources.json` (`.pmtiles` when big, else `.geojson`), each with `<id>.stats.json` (numbers, dates, category counts) and the manifest `index.json`. `business_kinds.json` is the reviewed list of non-storefront owners.
- **Contact data:** city-published registries (Active Business Locations, SF Planning's group list) are public and are kept, owner names and mailing addresses included, because they're how organizers reach neighbors. They show on cards and in exports, never as map labels, and reports in PRs name companies only, not people.
- Live URLs: `https://burritojustice.github.io/sf-blocks/<path>`. Moving or renaming a file breaks live links, so add the new path and keep the old one until the apps are updated.

## Scripts

- **Adding data:** follow `ADDING-DATA.md`. Boundary sets and map layers both go through the "Add or refresh data" Action (Kind: Boundary set runs `scripts/add_boundary_set.py`; Map layer runs `scripts/build_tiles.py`, with tippecanoe built and cached in the Action). New or refreshed boundary sets go through `scripts/add_boundary_set.py` (the Action runs it and opens a PR with preview links). `.github/workflows/check.yml` validates every PR. This sandbox can't reach DataSF; the Action can, so for a new dataset either have John run the Action or ask him for the export.

- **`scripts/build_data.py`** turns `data/sf_streets.csv` and `data/sf_intersections.csv` into `data/streets.json`.
  - A missing CSV is downloaded from DataSF's API; `--download` refreshes them. Column names are read case-insensitively, so manual Exports work too.
  - `--slopes` samples Terrarium DEM tiles (cached in `.tile-cache/`) for `slope_avg` / `slope_max`.
  - `--areas` tags each block with `hood_analysis|sffind|planning|realtor|wof` from `data/boundaries/`, checking at 25/50/75% along the block. A block on a boundary gets "; "-joined names, most-covered first.
  - Optional fields are appended after `geom`. Read fields by `SEG_FIELDS.index(...)`, never by position.
- **`scripts/match_blocks.py`**: free-text block descriptions in a CSV to CNNs.
- **`scripts/match_polygons.py`**: polygons in GeoJSON to the blocks and intersections inside them. Narrow strips list blocks running along them; wider areas list blocks fully or partly inside. It also retries medians and falls back to the nearest block.
- **`matcher/`** is the web page for both matchers. `worker.js` (a module worker; Pyodide 314 refuses classic workers) loads Pyodide from jsDelivr, fetches the two scripts and `data/streets.json` from the site, and calls `match_rows`, `match_features` and `manual`. Keep those functions' signatures, and keep the scripts standard library only so they run there unchanged. `matcher.js` mirrors `OUT_FIELDS`, `CSV_FIELDS` and `from_columns()`; change them together.
  - Testing: Playwright doesn't intercept a worker's requests, so serve Pyodide locally and open `matcher/?pyodide=<local url>/`. Compare Matcher's saved CSV with the command line's output; they should be identical.

## Data

- **`data/boundaries/`** is built by `scripts/get_layers.py` from `sources.json` (ported from Joiner's `get_layers.mjs`, which is retired; for the same input it writes the same bytes). It sorts the way JavaScript's `Intl.Collator('en', {numeric: true})` does and writes numbers the way `JSON.stringify` does, so keep those helpers if you change it. DataSF is blocked from Claude's sandbox: rebuild from exports with `--file <id>=<path>`.
- **The CSV's `nhood`** is DPW's realtor-style neighborhood. `analysis_neighborhood` is the city's own assignment, and boundary streets can sit on either side.

## Gotchas

- **Network from Claude's sandbox:** DataSF, Protomaps and jsDelivr are blocked here even when allowed in claude.ai settings, and the Terrarium S3 bucket too, so `--download` and `--slopes` hang there. Ask John for the CSVs, or run `--areas` alone and merge the new fields into the existing slopes `streets.json`.
- **Shallow clones:** the fetch refspec only covers `main`. After pushing a branch, run `git config --add remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` and `git branch -u origin/<branch>`.
