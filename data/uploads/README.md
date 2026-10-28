# data/uploads/

Raw files as downloaded or exported, kept so every file in `../boundaries/` and `../layers/` can be rebuilt without going back to the source. Don't edit them by hand; download a new copy instead.

- **Names:** a DataSF Export keeps its own name with the date it was exported (`Slow_Streets_20261012.geojson`). Keep that name. Several dates of one dataset can sit side by side; the build scripts take the newest.
- **Older files** without a date (`sf_schools.geojson`, `muni_lines.geojson`…) are found by keywords in `build_layers.py`. `sf_schools.geojson` has columns added by hand, so it's never replaced by a download.
- **`wof/`**: Who's On First neighbourhoods, macrohoods and microhoods for San Francisco, the source of `../boundaries/wof_neighbourhoods.geojson`. `raw/` holds the per-place files they were assembled from.

## Adding a download

1. On the dataset's DataSF page, choose Export and GeoJSON (or CSV for point tables with latitude and longitude).
2. Save it here with the date in the name.
3. Rebuild: `python3 scripts/build_layers.py` for map layers, or `python3 scripts/get_layers.py --file <set>=data/uploads/<file>` for a boundary set.
4. Ship it as an sf-blocks release (new `VERSION`, CHANGELOG entry).

The scripts can download from DataSF's API themselves, but Claude's cloud sessions can't reach data.sf.gov, so in those sessions attach the export instead.
