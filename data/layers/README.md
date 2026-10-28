# data/layers/

City layers that apps draw on the map (Block Party's Layers menu). Each is trimmed to the fields the map uses, with coordinates rounded to 5 decimals (about 1 m), and records its source dataset and the file it was built from.

| File | Kind | Source (DataSF) | Built from, in `../uploads/` |
|---|---|---|---|
| `schools.geojson` | points | [Schools](https://data.sf.gov/Economy-and-Community/Schools/7e7j-59qk/about_data) `7e7j-59qk` | `sf_schools.geojson` (has hand-added `short_name` and elevation, so never re-downloaded) |
| `stations.geojson` | points | [City-owned Facilities: Fire and Police](https://data.sf.gov/City-Infrastructure/City-owned-Facilities-Fire-and-Police/wt27-4jim/about_data) `wt27-4jim` | `SFFD_SFPD_stations.csv` |
| `health.geojson` | points | [Health Care Facilities](https://data.sf.gov/Health-and-Social-Services/Health-Care-Facilities/jhsu-2pka/about_data) `jhsu-2pka` | `sf_health_care_facilities.csv` |
| `muni.geojson` | lines | [Muni Simple Routes](https://data.sf.gov/Transportation/Muni-Simple-Routes/9exe-acju/about_data) `9exe-acju` | `muni_lines.geojson` |
| `bike.geojson` | lines | [MTA Bike Network Linear Features](https://data.sf.gov/Transportation/MTA-Bike-Network-Linear-Features/ygmz-vaxd/about_data) `ygmz-vaxd` | `sf_bike_lanes.geojson` |
| `slow.geojson` | lines | [Slow Streets](https://data.sf.gov/Transportation/Slow-Streets/hkz3-itiu/about_data) `hkz3-itiu` | `Slow_Streets_20261012.geojson` |
| `lands.geojson` | polygons | [City Lands](https://data.sf.gov/City-Infrastructure/City-Lands/gtnh-hgvs/about_data) `gtnh-hgvs` | `City_Lands_20261013.geojson` |

## Rebuilding

`python3 scripts/build_layers.py` finds each source in `../uploads/` by its dataset title, taking the newest date stamp, and rebuilds all seven. `--download` fetches fresh copies from DataSF first (except schools). The dataset list is `SOURCES` at the top of the script.
