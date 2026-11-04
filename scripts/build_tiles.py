#!/usr/bin/env python3
# sf-blocks 2026.11.03.2
"""Build map layers (points, lines, polygons too big for a plain GeoJSON file) into data/tiles/.

    python3 scripts/build_tiles.py                     every layer in data/tiles/sources.json
    python3 scripts/build_tiles.py street_trees        just these
    python3 scripts/build_tiles.py --file street_trees=trees.csv   use a download you already have
    python3 scripts/build_tiles.py --profile tkzw-k3nq  field report for a DataSF dataset (Markdown), to choose fields
    python3 scripts/build_tiles.py --profile 63x5-g3m4 --add historic_sites --year 2015
                                                       ...and add a first entry for it to sources.json
    python3 scripts/build_tiles.py --check             re-validate index.json against the files

For each layer it downloads the dataset from DataSF (all rows, in pages), keeps the fields in its `fields`
(name → "type:source", "a|b" = the first source with a value), drops rows outside the region's bbox, and
writes:
  data/tiles/<id>.pmtiles   with tippecanoe, when the layer is big (over 20,000 features or 5 MB); or
  data/tiles/<id>.geojson   when it's small enough to load whole
  data/tiles/<id>.stats.json  numbers and dates: min, max, mean, median, std dev, quantile breaks (5, 7 and
                            10 classes), dates by year; categories: each value's count
  data/tiles/index.json     the manifest the apps read

Field types: text, lower, int, id (a number that's an identifier: no stats), num, num1 (one decimal), date
(YYYY-MM-DD), latin / common / genus (from "Latin name :: Common name"), before_bar (text before "|"),
bizcat (food / licensed / other, from license descriptions).
Layer options: drop {field: regex} empties matching values; same_as {field: other} empties a field equal
to another; kinds {file, by} labels rows from a reviewed list (business_kinds.json); group {by, list, keep}
makes one feature per value of `by` with a count `n`, `shown` (rows without a kind), `name` / `name_all` (the first row's name, for labels) and the rows as JSON in `items`; tiles {minzoom,
maxzoom, overview: {minzoom, maxzoom, fields}}: the detail zooms carry every field, the overview (thinned
where dense) only its fields.

Needs tippecanoe and tile-join on PATH (or --tippecanoe DIR) for tiled layers. Standard library only.
"""
import argparse, csv, io, json, math, os, re, statistics, subprocess, sys, tempfile, time, urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'tiles'
PORTAL = 'https://data.sf.gov'
PAGE = 50000
TILE_IF = {'features': 20000, 'bytes': 5_000_000}
FOOD = re.compile(r'RESTAURANT|FOOD|CAFETERIA|BARS?/TAVERNS|RETAIL MKTS|BAKER|CATER|TAKE-OUT|COMMISSAR|FARMERS MARKET|CONCESSION|KITCHEN|FAST FOOD', re.I)
csv.field_size_limit(1 << 30)


def log(*a): print(*a, file=sys.stderr, flush=True)


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'sf-blocks build_tiles.py'})
            with urllib.request.urlopen(req, timeout=300) as r: return r.read()
        except Exception as e:
            if i == tries - 1: raise
            log(f'  retry ({e})'); time.sleep(5 * (i + 1))


def fetch(layer, raw_dir=None):
    """All rows from DataSF: CSV rows (dicts) or GeoJSON features, paged by row id."""
    ds, fmt = layer['dataset'], layer.get('format', 'csv')
    sel = ('&$select=' + ','.join(layer['select'])) if layer.get('select') else ''
    rows, off = [], 0
    raw = open(Path(raw_dir) / f"{layer['id']}.{'csv' if fmt == 'csv' else 'geojsonl'}", 'w') if raw_dir else None
    while True:
        url = f'{PORTAL}/resource/{ds}.{fmt}?$limit={PAGE}&$offset={off}&$order=:id{sel}'
        body = get(url).decode('utf-8')
        if fmt == 'csv':
            page = list(csv.DictReader(io.StringIO(body)))
            if raw: raw.write(body if off == 0 else body.split('\n', 1)[1] if '\n' in body else '')
        else:
            page = json.loads(body)['features']
            if raw: raw.writelines(json.dumps(f, separators=(',', ':')) + '\n' for f in page)
        rows += page; off += PAGE
        log(f'  {len(rows):,} rows')
        if len(page) < PAGE: break
    if raw: raw.close()
    return rows


def read_file(layer, path):
    path = Path(path)
    if path.suffix == '.csv': return list(csv.DictReader(open(path, newline='', encoding='utf-8')))
    text = path.read_text(encoding='utf-8')
    if text.lstrip().startswith('{') and '"FeatureCollection"' in text[:2000]: return json.loads(text)['features']
    return [json.loads(l) for l in text.splitlines() if l.strip()]


# ---------- fields ----------
def species_parts(v):
    latin, _, common = (v or '').partition('::')
    latin, common = latin.strip(), common.strip()
    genus = latin.split(' ')[0] if latin and not latin.lower().startswith('tree') else None
    return latin or None, common or None, genus


def convert(kind, v):
    if v is None: return None
    v = v.strip() if isinstance(v, str) else v
    if v == '': return None
    if isinstance(v, dict): v = v.get('url') or json.dumps(v)
    if kind in ('text',): return v
    if kind == 'lower': return v.lower()
    if kind in ('int', 'id'):
        try: return int(float(v))
        except ValueError: return None
    if kind in ('num', 'num1'):
        try: x = float(v)
        except ValueError: return None
        return round(x, 1) if kind == 'num1' else x
    if kind == 'date':
        m = re.match(r'(\d{4})[-/](\d\d)[-/](\d\d)', v)
        return f'{m[1]}-{m[2]}-{m[3]}' if m and 1800 < int(m[1]) <= date.today().year + 1 else None
    if kind == 'latin': return species_parts(v)[0]
    if kind == 'common': return species_parts(v)[1]
    if kind == 'genus': return species_parts(v)[2]
    if kind == 'before_bar': return v.split('|')[0].strip() or None
    if kind == 'bizcat': return 'food' if FOOD.search(v) else 'licensed'
    raise SystemExit(f'unknown field type {kind}')


def field_types(layer):
    t = {n: s.split(':', 1)[0] for n, s in layer['fields'].items()}
    for n in layer.get('ids', []): t[n] = 'id'
    return t


def props_of(layer, src):
    out = {}
    for name, spec in layer['fields'].items():
        kind, _, cols = spec.partition(':')
        val = None
        for c in cols.split('|'):
            val = convert(kind, src.get(c))
            if val is not None: break
        if kind == 'bizcat' and val is None: val = 'other'
        out[name] = val
    for f, rx in (layer.get('drop') or {}).items():
        if out.get(f) is not None and re.search(rx, str(out[f])): out[f] = None
    for f, other in (layer.get('same_as') or {}).items():
        if out.get(f) and out.get(other) and str(out[f]).strip().lower() == str(out[other]).strip().lower(): out[f] = None
    return out


def geometry_of(layer, row):
    if 'geometry' in row and 'type' in row: return row['geometry']
    pt = layer.get('point') or {}
    if 'wkt' in pt:
        m = re.match(r'\s*POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)', row.get(pt['wkt']) or '')
        return {'type': 'Point', 'coordinates': [float(m[1]), float(m[2])]} if m else None
    try: return {'type': 'Point', 'coordinates': [float(row[pt['lon']]), float(row[pt['lat']])]}
    except (KeyError, TypeError, ValueError): return None


def rnd(c):
    return [rnd(x) for x in c] if c and isinstance(c[0], list) else [round(c[0], 7), round(c[1], 7)]


def in_bbox(geom, bb):
    def walk(c):
        if c and isinstance(c[0], (int, float)): return bb[0] <= c[0] <= bb[2] and bb[1] <= c[1] <= bb[3]
        return any(walk(x) for x in c)
    return geom and geom.get('coordinates') and walk(geom['coordinates'])


# ---------- kinds and grouping ----------
def apply_kinds(layer, records):
    k = layer.get('kinds')
    if not k: return []
    conf = json.loads((OUT / k['file']).read_text())
    by, named, keep = k['by'], conf.get('owners', {}), set(conf.get('storefronts', []))
    rule = conf.get('rule') or {}
    addrs = defaultdict(set)
    for p, _ in records: addrs[p.get(by)].add(p.get('address'))
    over = sorted((len(a), o) for o, a in addrs.items() if o and len(a) >= rule.get('min_addresses', 1e9))
    for p, _ in records:
        o = p.get(by)
        p['kind'] = named.get(o) or (None if o in keep else rule.get('kind') if o and len(addrs[o]) >= rule.get('min_addresses', 1e9) else None)
    # owners the rule caught that aren't in either list yet, for the report
    return [(n, o) for n, o in reversed(over) if o not in named and o not in keep]


def group(layer, records):
    g = layer['group']; by = g['by']; buckets = defaultdict(list)
    for p, geom in records: buckets[p.get(by)].append((p, geom))
    feats = []
    for key, rows in buckets.items():
        if key is None:
            feats += [(p, geom) for p, geom in rows]; continue
        pts = Counter(tuple(geom['coordinates']) for _, geom in rows)
        items = [{f: p.get(f) for f in g['list'] if p.get(f) is not None} for p, _ in rows]
        items.sort(key=lambda i: (i.get('kind') is not None, (i.get('dba') or i.get('owner') or '').lower()))
        label = lambda i: i.get('dba') or i.get('owner')
        first = next((label(i) for i in items if not i.get('kind') and label(i)), None)
        props = {by: key, 'n': len(rows), 'shown': sum(1 for p, _ in rows if not p.get('kind')),
                 # for map labels: the first storefront's name (name), or the first of any (name_all)
                 'name': first, 'name_all': next((label(i) for i in items if label(i)), None),
                 'food': any(p.get('cat') == 'food' for p, _ in rows), 'items': json.dumps(items, separators=(',', ':'), ensure_ascii=False)}
        for f in g.get('keep', []):
            v = Counter(p.get(f) for p, _ in rows if p.get(f)).most_common(1)
            if v: props[f] = v[0][0]
        feats.append((props, {'type': 'Point', 'coordinates': list(pts.most_common(1)[0][0])}))
    return feats


# ---------- stats ----------
def quantiles(vals, k):
    if len(vals) < k: return sorted(set(vals))
    return [round(x, 4) for x in statistics.quantiles(vals, n=k, method='inclusive')]


def num_stats(vals, total):
    vals = sorted(vals)
    if not vals: return {'n': 0, 'missing': total}
    return {'n': len(vals), 'missing': total - len(vals), 'min': vals[0], 'max': vals[-1],
            'mean': round(statistics.fmean(vals), 4), 'median': statistics.median(vals),
            'std': round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0,
            'quantiles': {str(k): quantiles(vals, k) for k in (5, 7, 10)}}


def date_stats(vals, total):
    if not vals: return {'n': 0, 'missing': total}
    ords = sorted(date.fromisoformat(v).toordinal() for v in vals)
    d = lambda o: date.fromordinal(int(round(o))).isoformat()
    years = Counter(v[:4] for v in vals)
    return {'n': len(ords), 'missing': total - len(ords), 'min': d(ords[0]), 'max': d(ords[-1]),
            'mean': d(statistics.fmean(ords)), 'median': d(statistics.median(ords)),
            'std_days': round(statistics.pstdev(ords), 1) if len(ords) > 1 else 0,
            'quantiles': {str(k): [d(q) for q in quantiles(ords, k)] for k in (5, 7, 10)},
            'by_year': dict(sorted(years.items()))}


def cat_stats(vals, total, top=60):
    c = Counter(vals)
    out = {'n': len(vals), 'missing': total - len(vals), 'distinct': len(c), 'values': dict(c.most_common(top))}
    if len(c) > top: out['others'] = sum(v for _, v in c.most_common()[top:])
    return out


def stats_for(layer, records):
    types, total, fields = field_types(layer), len(records), {}
    cats = set(layer.get('categories', []))
    names = list(layer['fields']) + (['kind'] if layer.get('kinds') else [])
    for name in names:
        vals = [p[name] for p, _ in records if p.get(name) is not None]
        t = types.get(name, 'text')
        if t in ('int', 'num', 'num1'): fields[name] = {'type': 'number', **num_stats(vals, total)}
        elif t == 'date': fields[name] = {'type': 'date', **date_stats(vals, total)}
        elif name in cats: fields[name] = {'type': 'category', **cat_stats(vals, total)}
    return {'id': layer['id'], 'records': total, 'built': date.today().isoformat(), 'fields': fields}


# ---------- tiles ----------
def tool(name, d):
    p = Path(d) / name if d else None
    return str(p) if p and p.exists() else name


def tile(layer, feats, tdir):
    t = layer.get('tiles') or {}
    tmp = Path(tempfile.mkdtemp(prefix='tiles-'))
    src = tmp / 'in.geojsonl'
    with open(src, 'w', encoding='utf-8') as f:
        for p, geom in feats:
            f.write(json.dumps({'type': 'Feature', 'geometry': geom, 'properties': {k: v for k, v in p.items() if v is not None}},
                               separators=(',', ':'), ensure_ascii=False) + '\n')
    tc, base = tool('tippecanoe', tdir), ['-q', '-f', '-l', layer['id'], '--no-feature-limit', '--no-tile-size-limit']
    lo, hi = t.get('minzoom', 15), t.get('maxzoom', 15)
    detail = tmp / 'detail.pmtiles'
    subprocess.run([tc, *base, '-o', str(detail), '-Z', str(lo), '-z', str(hi), '-r1', str(src)], check=True)
    parts = [detail]
    ov = t.get('overview')
    if ov:
        over = tmp / 'over.pmtiles'
        subprocess.run([tc, '-q', '-f', '-l', layer['id'], '-o', str(over), '-Z', str(ov['minzoom']), '-z', str(ov['maxzoom']),
                        *sum((['-y', f] for f in ov['fields']), []), '--drop-densest-as-needed', str(src)], check=True)
        parts.insert(0, over)
    out = OUT / f"{layer['id']}.pmtiles"
    if len(parts) > 1:
        subprocess.run([tool('tile-join', tdir), '-q', '-f', '-o', str(out), *map(str, parts)], check=True,
                       stderr=subprocess.DEVNULL)
    else: detail.replace(out)
    return out, (ov['minzoom'] if ov else lo), hi


def build(layer, src_rows, bbox, tdir):
    records, skipped = [], 0
    for row in src_rows:
        geom = geometry_of(layer, row)
        if not geom or not in_bbox(geom, bbox): skipped += 1; continue
        props = props_of(layer, row.get('properties', row) if 'type' in row and 'geometry' in row else row)
        records.append((props, {'type': geom['type'], 'coordinates': rnd(geom['coordinates'])}))
    review = apply_kinds(layer, records)
    stats = stats_for(layer, records)
    feats = group(layer, records) if layer.get('group') else records
    size = sum(len(json.dumps(g['coordinates'])) + len(json.dumps(p)) for p, g in feats)
    tiled = len(feats) > TILE_IF['features'] or size > TILE_IF['bytes']
    for old in OUT.glob(f"{layer['id']}.*"):
        if old.suffix in ('.pmtiles', '.geojson'): old.unlink()
    if tiled: out, zmin, zmax = tile(layer, feats, tdir)
    else:
        out, zmin, zmax = OUT / f"{layer['id']}.geojson", None, None
        with open(out, 'w', encoding='utf-8') as f:
            f.write('{"type":"FeatureCollection","features":[\n')
            f.write(',\n'.join(json.dumps({'type': 'Feature', 'geometry': g, 'properties': {k: v for k, v in p.items() if v is not None}},
                                          separators=(',', ':'), ensure_ascii=False) for p, g in feats))
            f.write('\n]}\n')
    (OUT / f"{layer['id']}.stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False) + '\n')
    gtypes = Counter(g['type'].replace('Multi', '') for _, g in feats)
    # field → number, date, id or text; grouped layers list each row's fields under items_fields
    simple = lambda t: 'number' if t in ('int', 'num', 'num1') else t if t in ('date', 'id') else 'text'
    rowf = {**{n: simple(t) for n, t in field_types(layer).items()}, **({'kind': 'text'} if layer.get('kinds') else {})}
    if layer.get('group'):
        g = layer['group']
        fields_out = {g['by']: 'text', **{f: rowf.get(f, 'text') for f in g.get('keep', [])},
                      'n': 'count', 'shown': 'count', 'name': 'text', 'name_all': 'text', 'food': 'bool', 'items': 'json'}
    else: fields_out = rowf
    entry = {'id': layer['id'], 'label': layer['label'], 'year': layer.get('year'), 'file': out.name,
             'format': 'pmtiles' if tiled else 'geojson', 'layer': layer['id'], 'bytes': out.stat().st_size,
             'features': len(feats), 'records': len(records), 'geometry': gtypes.most_common(1)[0][0] if gtypes else None,
             **({'minzoom': zmin, 'maxzoom': zmax, 'detailzoom': (layer.get('tiles') or {}).get('minzoom', 15)} if tiled else {}),
             'fields': fields_out,
             'stats': f"{layer['id']}.stats.json", 'dataset': layer.get('dataset'), 'page': layer.get('page'),
             'retrieved': date.today().isoformat()}
    if layer.get('group'):
        entry['grouped_by'] = layer['group']['by']
        entry['items_fields'] = {f: rowf.get(f, 'text') for f in layer['group']['list']}
    log(f"  → data/tiles/{out.name}: {len(feats):,} features from {len(records):,} rows ({skipped:,} outside the region or without a location), "
        f"{out.stat().st_size / 1e6:.1f} MB")
    return entry, review, skipped


# ---------- profile: choose fields before building ----------
COMPANY = re.compile(r'\b(inc|llc|l\.?p|ltd|co|corp|corporation|company|companies|group|partners(hip)?|trust|bank|na|association|assn|foundation|services|management|holdings|properties|realty|investments?|associates|university|institute|hospital|center|church|city|state)\b\.?', re.I)
SKIP = re.compile(r'^(:|shape_|data_(as_of|loaded_at)|globalid|objectid$)', re.I)
CONTACT = re.compile(r'owner|mail|address|phone|email|contact', re.I)


def profile(ds, sample=5000):
    meta = json.loads(get(f'{PORTAL}/api/views/{ds}.json'))
    count = int(json.loads(get(f'{PORTAL}/resource/{ds}.json?$select=count(*)'))[0]['count'])
    rows = json.loads(get(f'{PORTAL}/resource/{ds}.json?$limit={sample}&$order=:id'))
    cols = [c for c in meta['columns'] if not c['fieldName'].startswith(':')]
    upd = meta.get('rowsUpdatedAt')
    lines = [f"## {meta['name']} ({ds})", '', f"{count:,} rows · data last updated {date.fromtimestamp(upd).isoformat() if upd else '?'} · {PORTAL}/d/{ds}", '',
             f'From the first {len(rows):,} rows:', '', '| Field | Type | Filled | Distinct | Avg size | Examples | Suggest |', '|---|---|---|---|---|---|---|']
    keep_bytes = 0
    for c in cols:
        f, t = c['fieldName'], c['dataTypeName']
        vals = [r[f] for r in rows if r.get(f) not in (None, '')]
        sv = [json.dumps(v) if not isinstance(v, str) else v for v in vals]
        filled, dist = len(vals) / max(1, len(rows)), len(set(sv))
        avg = sum(map(len, sv)) / max(1, len(sv))
        if t in ('point', 'line', 'polygon', 'multipolygon', 'multiline', 'location'): why = 'geometry'; keep_bytes += avg * filled
        elif dist == 1 and len(vals) > 1: why = 'drop: the same on every row'
        elif SKIP.search(f) or filled < 0.02: why = 'drop: empty' if filled < 0.02 else 'drop: system field'
        elif dist == len(vals) and t == 'text' and avg > 30: why = 'drop? different on every row'
        else: why = 'keep (contact)' if CONTACT.search(f) else 'keep'
        if why.startswith('keep'): keep_bytes += avg * filled + len(f)
        ex = ', '.join(sorted(set(s[:24] for s in sv), key=sv.count, reverse=True)[:3]).replace('|', '/')
        lines.append(f'| `{f}` | {t} | {filled:.0%} | {dist:,} | {avg:.0f} B | {ex} | {why} |')
    est = count * (keep_bytes + 60)
    lines += ['', f"Kept fields come to about {est / 1e6:.0f} MB as GeoJSON. "
              + (f'Over {TILE_IF["bytes"] // 1_000_000} MB or {TILE_IF["features"]:,} features, so it would be tiled: '
                 f'roughly {est * 0.05 / 1e6:.0f}–{est * 0.15 / 1e6:.0f} MB of .pmtiles for points, less once you drop fields (lines and polygons vary).'
                 if est > TILE_IF['bytes'] or count > TILE_IF['features'] else 'Small enough for a plain GeoJSON file.')]
    return '\n'.join(lines)


TYPE = {'number': 'num', 'calendar_date': 'date', 'text': 'text', 'checkbox': 'text', 'url': 'text'}
GEOM = {'point': 'Point', 'location': 'Point', 'line': 'LineString', 'multiline': 'LineString', 'polygon': 'Polygon', 'multipolygon': 'Polygon'}


def add(layer_id, ds, label=None, year=None, keep=None):
    """A first entry for a new layer in sources.json: the fields the profile would keep, for review in the PR."""
    conf_file = OUT / 'sources.json'; conf = json.loads(conf_file.read_text())
    if any(l['id'] == layer_id for l in conf['layers']): raise SystemExit(f'{layer_id} is already in sources.json')
    meta = json.loads(get(f'{PORTAL}/api/views/{ds}.json'))
    cols = [c for c in meta['columns'] if not c['fieldName'].startswith(':')]
    geo = [c for c in cols if c['dataTypeName'] in GEOM]
    sample = json.loads(get(f'{PORTAL}/resource/{ds}.json?$limit=2000&$order=:id'))
    want = {k.strip() for k in (keep or '').split(',') if k.strip()}
    fields = {}
    for c in cols:
        f, t = c['fieldName'], c['dataTypeName']
        if t in GEOM or (SKIP.search(f) and f not in want): continue
        filled = sum(1 for r in sample if r.get(f) not in (None, '')) / max(1, len(sample))
        if f in want or (not want and filled >= 0.02): fields[f] = f"{TYPE.get(t, 'text')}:{f}"
    entry = {'id': layer_id, 'label': label or meta['name'], 'dataset': ds, 'page': f'{PORTAL}/d/{ds}',
             'year': year or 'current', 'fields': fields, 'categories': [], 'tiles': {'minzoom': 15, 'maxzoom': 15}}
    if geo and geo[0]['dataTypeName'] in ('point', 'location') and not any(c['dataTypeName'] not in ('point', 'location') for c in geo):
        entry.update(format='csv', point={'wkt': geo[0]['fieldName']})
    else: entry['format'] = 'geojson'
    conf['layers'].append(entry)
    conf_file.write_text(json.dumps(conf, indent=2, ensure_ascii=False) + '\n')
    return entry


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--file', action='append', default=[], help='id=path: use this download instead of fetching')
    ap.add_argument('--raw', help='save the raw downloads in this folder (to archive them)')
    ap.add_argument('--tippecanoe', help='folder with tippecanoe and tile-join')
    ap.add_argument('--profile', metavar='DATASET')
    ap.add_argument('--report', help='write a Markdown report here')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--add', metavar='ID', help='with --profile: add a first entry for this new layer to sources.json')
    ap.add_argument('--label'); ap.add_argument('--year'); ap.add_argument('--keep', help='fields to keep, comma separated')
    a = ap.parse_args()
    if a.profile and a.add:
        md = profile(a.profile)
        e = add(a.add, a.profile, a.label, a.year, a.keep)
        md += ('\n\n### Added to `data/tiles/sources.json` (not built yet)\n\n```json\n' + json.dumps(e, indent=2, ensure_ascii=False) + '\n```\n\n'
               'Edit the entry on this branch: remove fields you don\'t want, set each `type` (int, num1, date, id…), list `categories`, and '
               'check `year`. Then run the action again on this branch, with the same id, to build the layer.')
        print(md)
        if a.report: Path(a.report).write_text(md + '\n')
        return
    if a.profile:
        md = profile(a.profile)
        print(md)
        if a.report: Path(a.report).write_text(md + '\n')
        return
    conf = json.loads((OUT / 'sources.json').read_text())
    index_file = OUT / 'index.json'
    index = json.loads(index_file.read_text()) if index_file.exists() else {'layers': []}
    if a.check:
        bad = [l['id'] for l in index['layers'] if not (OUT / l['file']).exists() or not (OUT / l['stats']).exists()]
        for l in index['layers']: log(f"{l['id']}: {l['features']:,} features, {l['file']}" + (' MISSING' if l['id'] in bad else ' ok'))
        sys.exit(1 if bad else 0)
    bbox = json.loads((ROOT / 'region.json').read_text())['bbox']
    bbox = [bbox[0] - 0.02, bbox[1] - 0.02, bbox[2] + 0.02, bbox[3] + 0.02]
    files = dict(x.split('=', 1) for x in a.file)
    layers = [l for l in conf['layers'] if not a.ids or l['id'] in a.ids]
    if a.ids and len(layers) != len(a.ids): raise SystemExit(f'not in sources.json: {set(a.ids) - {l["id"] for l in layers}}')
    report = []
    for layer in layers:
        log(f"{layer['id']} ({layer.get('dataset') or files.get(layer['id'])})")
        rows = read_file(layer, files[layer['id']]) if layer['id'] in files else fetch(layer, a.raw)
        entry, review, skipped = build(layer, rows, bbox, a.tippecanoe)
        index['layers'] = [l for l in index['layers'] if l['id'] != entry['id']] + [entry]
        report.append(f"- **{layer['label']}** (`{layer['id']}`): {entry['features']:,} features from {entry['records']:,} rows, "
                      f"{entry['bytes'] / 1e6:.1f} MB `{entry['file']}`; {skipped:,} rows outside the region or without a location. Data year: {layer.get('year')}.")
        if review:
            rule = json.loads((OUT / layer['kinds']['file']).read_text())['rule']['min_addresses']
            # companies by name; owners that look like people are only counted (the report goes in a public PR)
            co = [(n, o) for n, o in review if COMPANY.search(o)]
            people = len(review) - len(co)
            report.append(f"  - Owners at {rule}+ addresses not in `{layer['kinds']['file']}` yet, shown as \"Registered at many addresses\" "
                          "until they're listed: " + ('; '.join(f'{o} ({n})' for n, o in co[:40]) or 'no companies')
                          + (f"; and {people} that look like people (landlords registering each rental), left to the rule and not named here" if people else ''))
    order = [l['id'] for l in conf['layers']]
    index['layers'].sort(key=lambda l: order.index(l['id']) if l['id'] in order else 99)
    index['_doc'] = 'Map layers: data/tiles/<file>, built by scripts/build_tiles.py from sources.json. Read with PMTiles (format pmtiles) or as GeoJSON.'
    index_file.write_text(json.dumps({'_doc': index['_doc'], 'layers': index['layers']}, indent=2, ensure_ascii=False) + '\n')
    if a.report: Path(a.report).write_text('\n'.join(report) + '\n')
    print('\n'.join(report))


if __name__ == '__main__':
    main()
