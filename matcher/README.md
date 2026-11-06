# Matcher

https://burritojustice.github.io/sf-blocks/matcher/

Match street names, intersections and polygons to San Francisco blocks (CNNs) in the browser. Drop in a CSV, Excel workbook or GeoJSON, paste a link or rows, check the results on a map, fix the ones that need it, and save a CSV, GeoJSON or Excel file.

It runs sf-blocks' own `scripts/match_blocks.py` and `scripts/match_polygons.py` with [Pyodide](https://pyodide.org), so its answers are the command line's answers. Files stay in the browser.

| File | What it does |
|---|---|
| `index.html` | The page: Load, What to match, Results, the map and the table |
| `matcher.js` | Reading files and links, guessing columns, sending rows to the worker in batches, the map, the table, fixing on the map, saving |
| `worker.js` | Loads Pyodide and the scripts, and runs `match_rows`, `match_features` and `manual` |
| `matcher.css` | Styles |

Libraries, pinned: MapLibre GL 5.16.0, PapaParse 5.4.1, SheetJS 0.20.3 (from SheetJS's own CDN; the npm copy is out of date), Pyodide 314.0.7.

For testing without the CDN, `?pyodide=<url>/` loads Pyodide from another copy.
