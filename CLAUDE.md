# sf-blocks: notes for Claude

The **main copy** of San Francisco's street-block data and matching scripts, shared by civic-joy-fund/block-party, burritojustice/sf-striping and others. Those projects keep copies, and each copied script's first line names the sf-blocks version it came from. Read `README.md` for the data format and definitions, and `CHANGELOG.md` for history.

## Working rules

- **Ship as a PR:** make a branch, commit, push it, and open the PR (`gh api repos/burritojustice/sf-blocks/pulls -f head=<branch> -f base=main ...`; GraphQL is blocked here).
- **Version every change:** bump `VERSION` (date style, `2026.10.23`), the version in each changed script's first line, and add an entry at the top of `CHANGELOG.md`. Docs-only changes don't need it.
- **Change here first:** then copy the files into Block Party (and other users) with their "Copied from burritojustice/sf-blocks <version>" header, and open a PR there too.
- **Dates are YYYY-MM-DD:** `build_data.py`'s `ymd()` normalizes both the API's and the Export's date formats.
- **Standard library only:** the Python scripts use no other packages, so anyone can run them.
- **Keep streets.json the full build:** the committed file is the `--slopes --areas` build. Don't replace it with a plain build that drops those fields.

## Scripts

- **`scripts/build_data.py`** turns `data/sf_streets.csv` and `data/sf_intersections.csv` into `data/streets.json`.
  - A missing CSV is downloaded from DataSF's API; `--download` refreshes them. Column names are read case-insensitively, so manual Exports work too.
  - `--slopes` samples Terrarium DEM tiles (cached in `.tile-cache/`) for `slope_avg` / `slope_max`.
  - `--areas` tags each block with `hood_analysis|sffind|planning|realtor|wof` from `data/boundaries/`, checking at 25/50/75% along the block. A block on a boundary gets "; "-joined names, most-covered first.
  - Optional fields are appended after `geom`. Read fields by `SEG_FIELDS.index(...)`, never by position.
- **`scripts/match_blocks.py`**: free-text block descriptions in a CSV to CNNs.
- **`scripts/match_polygons.py`**: polygons in GeoJSON to the blocks and intersections inside them. Narrow strips list blocks running along them; wider areas list blocks fully or partly inside. It also retries medians and falls back to the nearest block. Planned: port it to a single `match.js` for a web matching tool (see Block Party's `TODO.md`).

## Data

- **`data/boundaries/`** is copied from civic-joy-fund/joiner, which downloads the boundary sets from DataSF and owns the neighborhood-name crosswalk.
- **The CSV's `nhood`** is DPW's realtor-style neighborhood. `analysis_neighborhood` is the city's own assignment, and boundary streets can sit on either side.

## Gotchas

- **Network from Claude's sandbox:** DataSF and the Terrarium S3 bucket are blocked, so `--download` and `--slopes` hang there. Ask John for the CSVs, or run `--areas` alone and merge the new fields into the existing slopes `streets.json`.
- **Shallow clones:** the fetch refspec only covers `main`. After pushing a branch, run `git config --add remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` and `git branch -u origin/<branch>`.
