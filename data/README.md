# data/

San Francisco's map data, served as is from https://burritojustice.github.io/sf-blocks/data/… so apps can load any file by its path.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/apps-and-data-dark.svg">
  <img src="../docs/apps-and-data-light.svg" alt="sf-blocks holds the data; the apps read it live and keep a backup. sf-blocks feeds Joiner, Block Party and sf-striping; Airtable and JoinKit (Selecter's join code) feed Joiner; Civic Joy Fund's and other organizations' copies are updated from Joiner and Block Party." width="760">
</picture>

More in [docs/apps-and-data.md](../docs/apps-and-data.md).

| Path | What | Where it comes from | Rebuild with |
|---|---|---|---|
| `boundaries/` | 17 polygon sets to join to, plus `index.json` and `sources.json` | DataSF, Who's On First, and precincts merged into districts. See [boundaries/README.md](boundaries/README.md) | `scripts/get_layers.py` |
| `layers/` | City points, lines and polygons drawn on maps | DataSF. See [layers/README.md](layers/README.md) | `scripts/build_layers.py` |
| `uploads/` | Raw downloads the two folders above are built from | DataSF exports, Who's On First. See [uploads/README.md](uploads/README.md) | (downloads, not built) |
| `sf_streets.csv` | Every street block, active and retired, one row per CNN | DataSF [Streets – Active and Retired](https://data.sf.gov/Geographic-Locations-and-Boundaries/Streets-Active-and-Retired/3psu-pn9h/about_data) (`3psu-pn9h`) | `build_data.py --download` |
| `sf_intersections.csv` | Every intersection and the streets that meet there | DataSF [List of Intersections only](https://data.sf.gov/Geographic-Locations-and-Boundaries/List-of-Intersections-only/sw2d-qfup/about_data) (`sw2d-qfup`) | `build_data.py --download` |
| `streets.json` | Compact blocks and intersections with slopes and neighborhood fields; what the maps load | The two CSVs, Terrarium elevation tiles, `boundaries/` | `build_data.py --slopes --areas` (always the full build) |
| `Land_Use_with_Active_Parcel_Information.pmtiles` | Parcels with land use and zoning, as vector tiles (24 MB) | DataSF `h5vv-2u24`, SF Planning land use 2023 | one-off; see Block Party's CHANGELOG v32 |
| `aliases.json` | Other names people use for areas, by boundary set | By hand | edit it; it's the only alias list |

## How the apps get these files

Joiner and Block Party read `../region.json` first, then each file they need from the live site. If the site can't be reached, or a file is missing there, they use their own backup copy at the same path, listed in their `data/sf-blocks.json` with the sf-blocks version it came from. `scripts/copy_sf_blocks.py` in each app refreshes those copies from a checkout of this repo. sf-striping keeps copies only.

**Don't move or rename a file here** without keeping the old path until every app has updated: apps load files by path.
