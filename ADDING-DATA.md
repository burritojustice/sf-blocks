# Adding data to sf-blocks

sf-blocks is the one copy of San Francisco's map data that Joiner, Block Party and other maps read live. Anything added here shows up in those apps without changing them (Block Party needs one line; see below). So every change goes through a pull request, where it can be checked before it's live.

## What goes where

| You have | It goes in | Built by |
| --- | --- | --- |
| Areas people join rows to or want to know a block is in: districts, neighborhoods, historic districts | `data/boundaries/` | `scripts/add_boundary_set.py` (below) |
| Points or lines for a map layer: schools, stations, bike lanes | `data/layers/` | `scripts/build_layers.py` |
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

## After it's merged

- **Joiner:** the set appears right away in the tab given (Other by default), named by its title. Nothing to change in Joiner.
- **Block Party:** to show it as a map layer and a card row ("Historic district: Liberty-Hill"), add one line to `AREA_LAYERS` near the `Areas` module in Block Party's `index.html`, with a short key, the set id and a color: `{ k: 'historic', set: 'historic_districts', color: '#A8441B', layer: 'Historic districts', row: 'Historic district' }`. If you want it in Block Party's offline backup too, add `data/boundaries/<id>.geojson` to its `data/sf-blocks.json`.
- **Backup copies:** each app keeps copies for when sf-blocks can't be reached. Its **Refresh sf-blocks copies** action runs every Monday (or by hand) and opens a pull request when sf-blocks changed.

## Rules

- **Pull requests, not direct commits to `main`.** The apps read `main` live; the **Check data** action runs on every pull request.
- **Don't rename or move published files.** Live links would break. Add the new path, update the apps, then remove the old one.
- **Public data only.** No names, emails or phone numbers of private people. Contact lists only when the city or the organization publishes them, with `source_url` and `checked` columns.
- **Note the source.** The set's `page` in `sources.json` links to where it came from; the action fills it in for DataSF.
- **Version:** the action bumps `VERSION` and adds a `CHANGELOG.md` entry. By hand, do the same.

## Repository settings the actions need

In each repo (sf-blocks, Joiner, Block Party): **Settings → Actions → General → Workflow permissions**: choose **Read and write permissions** and tick **Allow GitHub Actions to create and approve pull requests**.

## Not automated (yet)

- **Block Party's `AREA_LAYERS` line** is by hand, because color and wording are choices. sf-blocks could carry them per set in `sources.json` so Block Party picks sets up on its own.
- **People without write access** can't run actions. They could open an issue with a form ("Suggest a boundary set": dataset link, name field) that a maintainer turns into a run.
- **Scheduled refreshes** of DataSF sets that change (precincts after redistricting, say) could run monthly; most sets change rarely.
