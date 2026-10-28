# data/boundaries/

The polygon sets that apps join rows to. Each `<id>.geojson` is a FeatureCollection whose `feature.id` is the set's join key, with only the properties apps use, coordinates rounded to 6 decimals and features sorted by key.

- **`index.json`**: the manifest apps read (Joiner builds its tabs from it): each set's label, key, name field, feature count, bbox and size.
- **`sources.json`**: how each set is built: DataSF dataset id, page, key, name field, fields kept, match rules. Its `tab` and label fields are Joiner's display settings.
- Other names for areas are in `../aliases.json`, not here.

## Sets and sources

| Set | Key | Features | Source |
|---|---|---|---|
| `supervisor_districts` | `sup_dist` | 11 | DataSF `cqbw-m5m3` |
| `zip_codes` | `zip_code` | 27 | DataSF `srq6-hmpi` |
| `sf_find_neighborhoods` | `name` | 117 | DataSF `pty2-tcw4` |
| `analysis_neighborhoods` | `nhood` | 41 | DataSF `p5b7-5n3h` |
| `planning_neighborhoods` | `neighborho` | 37 | DataSF `mw29-m2za` |
| `realtor_neighborhoods` | `nbrhood` | 92 | DataSF `5gzd-g9ns` |
| `wof_neighbourhoods` | `name` | 116 | Who's On First, from `../uploads/wof/` |
| `census_tracts` | `geoid` | 242 | DataSF `sevw-6tgi` (2020 tracts) |
| `cultural_districts` | `district_name` | 10 | DataSF `5xmc-5bjj`, export of 2026-10-25 in `../uploads/` |
| `bay_area_counties` | `county` | 9 | A California county boundaries file (the nine counties, simplified to about 20 m) |
| `bay_area_zip_codes` | `zip` | 323 | DataSF `4kz9-76pb`, CSV export (simplified to about 10 m) |
| `election_precincts` | `prec_2022` | 514 | DataSF `d6x4-hefw` (2022 precincts) |
| `us_house_districts` | `cong22` | 4 | Precincts merged by district |
| `state_senate_districts` | `sen22` | 3 | Precincts merged by district |
| `assembly_districts` | `assemb22` | 4 | Precincts merged by district |
| `bart_districts` | `bart22` | 3 | Precincts merged by district |

## Rebuilding

```
python3 scripts/get_layers.py --file cultural_districts=data/uploads/Cultural_Districts_20261025.geojson
python3 scripts/get_layers.py zip_codes          # downloads from DataSF
python3 scripts/get_layers.py --check            # re-validate what's here
```

Save any export in `../uploads/` with its date in the name first. A new set goes in `sources.json` before it's built; districts merged from another set come after that set.
