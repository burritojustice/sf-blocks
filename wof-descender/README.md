# Descender

The descendants of any [Who's On First](https://whosonfirst.org) place, with their shapes: neighbourhoods in San Francisco, counties in Arizona, boroughs in London. A Python script and a web page that do the same thing and write the same files:

- **GeoJSON:** a FeatureCollection, one Feature per place.
- **CSV:** the same fields, with the shape as WKT in the last column.

It reads the [Spelunker](https://spelunker.whosonfirst.org)'s Descendants page (for example [San Francisco's neighbourhoods](https://spelunker.whosonfirst.org/id/85922583/descendants?isdeprecated=0&placetype=neighbourhood)) with the same filters the page has, then downloads each record from data.whosonfirst.org.

## The script

Python 3.9 or later, standard library only.

```
python3 wof-descender/descender.py 85922583 -p neighbourhood --isdeprecated 0
python3 wof-descender/descender.py "https://spelunker.whosonfirst.org/id/85922583/descendants?isdeprecated=0&placetype=neighbourhood"
python3 wof-descender/descender.py 85688719 -p county --iscurrent 1 -o arizona_counties
python3 wof-descender/descender.py 101750367 -p borough,macrohood --iscurrent 1
python3 wof-descender/descender.py 101750367 --facets
```

| Option | What it does |
|---|---|
| `<id or URL>` | A WOF id, or a Spelunker link. The link's `placetype`, `country`, `iscurrent` and `isdeprecated` are used. |
| `-p`, `--placetype` | Placetype(s) of the descendants: `neighbourhood`, `county`, `borough`… Repeat the option or separate with commas. The Spelunker takes one placetype per request, so each one is listed in turn. |
| `--country` | Two-letter country code. |
| `--iscurrent` | `1` current, `0` not current, `-1` unknown. |
| `--isdeprecated` | `0` leaves out deprecated places, `1` keeps only those. Leave it off to get both. |
| `--facets` | Shows how many descendants there are by placetype, country and status, then stops. Running with no `-p` does the same. |
| `--ids-only` | Lists ids, placetypes, names and repos without downloading anything. |
| `-o`, `--out` | Output name, without the extension. The default is `<id>-<placetypes>`, e.g. `85922583-neighbourhood`. |
| `--no-csv` | Writes the GeoJSON only. |
| `--all-properties` | The GeoJSON keeps every WOF property instead of the fields below. |
| `--cache DIR` | Keeps the downloaded records in a folder, so a rerun doesn't download them again. |
| `--workers N` | How many requests to make at once (default 4). |
| `--serve [PORT]` | Runs the web page on this computer (see below). |

### Fields

| Field | What it is |
|---|---|
| `wof_id`, `name`, `placetype` | From the record. |
| `status` | One of: `deprecated`, `superseded`, `ceased`, `current` (`mz:is_current` 1), `not current` (0), or `unverified` (−1 or missing, meaning never reviewed). In SF, the unverified neighbourhoods (Excelsior, Inner Sunset, Bayview…) are in use, and together with the current ones they cover the city. |
| `is_current` | `mz:is_current` as it is. |
| `country` | `wof:country`. |
| `parent_id`, `parent` | `wof:parent_id` and its name. |
| `<placetype>_id`, `<placetype>` | Ancestors between the place you asked about and each record, with names. For example, `macrohood` for SF neighbourhoods, or `borough` for London neighbourhoods. A column only appears when some record has that ancestor. |
| `inception`, `cessation`, `deprecated` | EDTF dates. Blank when unknown (`uuuu`). |
| `superseded_by` | Ids, separated by `;`. |
| `lastmodified` | YYYY-MM-DD. |
| `src_geom` | Where the shape came from. |
| `lbl_latitude`, `lbl_longitude` | Label point. If there is none, the centroid. |
| `area_m2` | `geom:area_square_m`, rounded to whole square metres. |
| `repo`, `spelunker`, `geojson` | The record's repo, its Spelunker page, and its data.whosonfirst.org file. |

Places are sorted by placetype (in the order asked for), then by name.

## The web page

https://burritojustice.github.io/sf-blocks/wof-descender/

1. Enter an id or paste a Spelunker link.
2. Tick one or more placetypes. Counts come from the Spelunker.
3. Set country, current and deprecated if you need to.
4. Press **Get**.

The places appear on the map and in a list. **Download GeoJSON** and **Download CSV (WKT)** save the same files the script writes. **Same thing on the command line** gives the script command for the current choices.

The page's link records the choices, so you can bookmark or share it: `?id=85922583&placetype=neighbourhood`. Add `&isdeprecated=any` to include deprecated places, which are left out by default. A link with a placetype starts downloading when it opens; add `&go=0` to stop that. `?url=<Spelunker link>` also works.

The map is Protomaps white, with the creek fix and a satellite switch, like Matcher and Block Party.

### The Spelunker has to be reached through a helper

The Spelunker doesn't let other websites read its descendant pages (no CORS header on them), so the page can't read them directly. It tries these in order:

1. `?spelunker=<address>` in the page's link.
2. `/spelunker` on the page's own server. `descender.py --serve` provides it.
3. The `proxy` address in `descender.json`.
4. The Spelunker itself, in case it allows other sites one day.

**On your computer:** in a copy of sf-blocks, run the command below and open http://localhost:8765/wof-descender/. It serves the repo folder and passes `/spelunker/id/…` requests on to the Spelunker.

```
python3 wof-descender/descender.py --serve
```

**On GitHub Pages:** deploy `proxy/worker.js` as a Cloudflare Worker (the free plan is plenty), then put its address in `descender.json`:

```json
{ "proxy": "https://wof-descender.<your-account>.workers.dev" }
```

The Worker only passes on GET requests for `/id/<id>/descendants`, `/id/<id>/descendants/facets` and `/id/<id>/spr`, and caches answers for a day. Until a proxy is set, the hosted page explains this and gives the script command instead.

## Files

| File | What it is |
|---|---|
| `descender.py` | The script, and `--serve` for the page |
| `index.html`, `descender.js`, `descender.css` | The page |
| `descender.json` | The page's settings (`proxy`) |
| `proxy/worker.js` | The Cloudflare Worker proxy |

`descender.js` mirrors `descender.py`: the fields, `status()`, the sort, and the GeoJSON, CSV and WKT writers, with numbers written the way JavaScript's `JSON.stringify` writes them. For the same choices, the files are byte-for-byte the same. If you change one, change the other.

Who's On First data is under [various open licenses](https://whosonfirst.org/docs/licenses/), mostly CC-BY. Credit Who's On First when you publish it.
