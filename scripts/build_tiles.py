#!/usr/bin/env python3
# sf-blocks 2026.11.18.6
"""Build map layers (points, lines, polygons too big for a plain GeoJSON file) into data/tiles/.

    python3 scripts/build_tiles.py                     every layer in data/tiles/sources.json and data/tiles/sources/
    python3 scripts/build_tiles.py street_trees        just these
    python3 scripts/build_tiles.py --file street_trees=trees.csv   use a download you already have
    python3 scripts/build_tiles.py --profile tkzw-k3nq  field report for a DataSF dataset (Markdown), to choose fields
    python3 scripts/build_tiles.py --profile 63x5-g3m4 --add historic_sites --year 2015
                                                       ...and add an entry for it in data/tiles/sources/historic_sites.json
    python3 scripts/build_tiles.py --check             re-validate index.json against the files; warn about layers not built
    python3 scripts/build_tiles.py --check --require bus_stops   ...and fail unless these are built from their current entries

New layers each get their own file, data/tiles/sources/<id>.json (the layer's entry), so two pull requests adding
layers never touch the same lines. sources.json keeps the older ones; both are read, sources.json first.

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
bizcat (food / licensed, from license descriptions), bizcategory:lic,naics (food / retail / services / other), sector (a NAICS
code's sector), and "a+b+c" to join fields (a street address with its city and ZIP).
Layer options: drop {field: regex} empties matching values; same_as {field: other} empties a field equal
to another; kinds {file, by} labels rows from a reviewed list (business_kinds.json); group {by, list, keep}
makes one feature per value of `by` with a count `n`, `shown` (rows without a kind), `name` / `name_all` (the first row's name, for labels) and the rows as JSON in `items`;
`counts: <field>` adds `n_<value>` and `shown_<value>` for each value of that field (so a map can size a dot by the categories it shows); tiles {minzoom,
maxzoom, overview: {minzoom, maxzoom, fields}}: the detail zooms carry every field, the overview (thinned
where dense) only its fields (a name ending in * takes every field it starts).
Layers keyed by street (sf-blocks#52): geometry {cnn: <field>} draws each row as that street's line from
data/streets.json (an intersection's CNN as its corner point), and geometry {cnns: <field>} a field listing
several CNNs as one MultiLineString; a row whose CNNs aren't in streets.json keeps its own point, if it has
one. stack_by_cnn {keep: [fields]} then makes one feature per street (or set of streets): `n` rows, the most
common value of each `keep` field, `n_<value>` for the first `keep` field, and the rows as JSON in `items`.
The manifest marks these "join": "cnn".

Needs tippecanoe and tile-join on PATH (or --tippecanoe DIR) for tiled layers. Standard library only.
"""
import argparse, csv, io, json, math, os, re, statistics, subprocess, sys, tempfile, time, urllib.parse, urllib.request
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
    if layer.get('where'): sel += '&$where=' + urllib.parse.quote(layer['where'])
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
    if kind in ('text', 'naics'): return v
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
    if kind == 'sector': return SECTORS.get(re.sub(r'\D', '', v)[:2])
    raise SystemExit(f'unknown field type {kind}')


# NAICS sectors (first two digits), for businesses
SECTORS = {'11': 'Agriculture', '21': 'Mining', '22': 'Utilities', '23': 'Construction', '31': 'Manufacturing', '32': 'Manufacturing',
           '33': 'Manufacturing', '42': 'Wholesale', '44': 'Retail', '45': 'Retail', '48': 'Transportation', '49': 'Warehousing',
           '51': 'Information', '52': 'Finance and insurance', '53': 'Real estate and rental', '54': 'Professional services',
           '55': 'Management', '56': 'Admin and support', '61': 'Education', '62': 'Health care', '71': 'Arts and recreation',
           '72': 'Food and lodging', '81': 'Other services', '92': 'Public administration'}


def business_category(lic, naics):
    """food (restaurants, bars, markets, caterers: by license or NAICS 722), retail (NAICS 44–45), services (81: hair,
    nails, repair, laundry…), or other."""
    n = re.sub(r'\D', '', naics or '')
    if (lic and FOOD.search(lic)) or n.startswith('722'): return 'food'
    if n[:2] in ('44', '45'): return 'retail'
    if n[:2] == '81': return 'services'
    return 'other'


def field_types(layer):
    t = {n: s.split(':', 1)[0] for n, s in layer['fields'].items()}
    for n in layer.get('ids', []): t[n] = 'id'
    return t


def props_of(layer, src):
    out = {}
    for name, spec in layer['fields'].items():
        kind, _, cols = spec.partition(':')
        val = None
        if kind == 'bizcategory':            # license descriptions, NAICS code
            a, b = cols.split(',')
            out[name] = business_category(src.get(a) or '', src.get(b) or ''); continue
        if '+' in cols:                       # several fields joined: "1 Main St, Oakland, CA 94612"
            parts = [str(src.get(c) or '').strip() for c in cols.split('+')]
            out[name] = ', '.join(x for x in [parts[0], ' '.join(x for x in parts[1:] if x)] if x) or None; continue
        for c in cols.split('|'):
            val = convert(kind, src.get(c))
            if val is not None: break
        if kind == 'bizcat' and val is None: val = 'other'
        out[name] = val
    for f, rx in (layer.get('drop') or {}).items():
        if out.get(f) is not None and re.search(rx, str(out[f])): out[f] = None
    for f, other in (layer.get('same_as') or {}).items():
        if out.get(f) and out.get(other) and str(out[f]).strip().lower() == str(out[other]).strip().lower(): out[f] = None
    for f, other in (layer.get('empty_with') or {}).items():     # mail_place goes when mail does
        if not out.get(other): out[f] = None
    return out


def geometry_of(layer, row):
    if 'geometry' in row and 'type' in row: return row['geometry']
    pt = layer.get('point') or {}
    if 'wkt' in pt:
        m = re.match(r'\s*POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)', row.get(pt['wkt']) or '')
        return {'type': 'Point', 'coordinates': [float(m[1]), float(m[2])]} if m else None
    try: return {'type': 'Point', 'coordinates': [float(row[pt['lon']]), float(row[pt['lat']])]}
    except (KeyError, TypeError, ValueError): return None


# ---------- streets, for layers keyed by CNN ----------
_streets = None


def streets():
    """CNN → the street's line (lon/lat), and intersection CNN → its corner, from data/streets.json"""
    global _streets
    if _streets is None:
        raw = json.loads((ROOT / 'data' / 'streets.json').read_text())
        F, N = {f: i for i, f in enumerate(raw['seg_fields'])}, {f: i for i, f in enumerate(raw['node_fields'])}
        lines, corners = {}, {}
        for r in raw['segs']:
            g, pts, x, y = r[F['geom']], [], 0, 0
            for i in range(0, len(g), 2):
                x, y = (g[0], g[1]) if i == 0 else (x + g[i], y + g[i + 1])
                pts.append([round(x / 1e5, 7), round(y / 1e5, 7)])
            if len(pts) > 1: lines[int(r[F['cnn']])] = pts
        for r in raw['nodes']:
            if r[N['cnn']]: corners[int(r[N['cnn']])] = [round(r[N['x']] / 1e5, 7), round(r[N['y']] / 1e5, 7)]
        _streets = (lines, corners)
    return _streets


def cnns_of(layer, src):
    """the CNNs a row is on, from geometry {cnn} or {cnns} (a list: commas, semicolons, bars or spaces)"""
    g = layer.get('geometry') or {}
    raw = src.get(g['cnn']) if 'cnn' in g else src.get(g.get('cnns'))
    out = []
    for part in re.split(r'[,;|\s]+', str(raw if raw is not None else '')):
        try: n = int(float(part))
        except ValueError: continue
        if n and n not in out: out.append(n)
    return out


def cnn_geometry(cnns):
    """one line, several (MultiLineString), or a corner's point; None if none of them is in streets.json"""
    lines, corners = streets()
    ls = [lines[c] for c in cnns if c in lines]
    if ls: return {'type': 'LineString', 'coordinates': ls[0]} if len(ls) == 1 else {'type': 'MultiLineString', 'coordinates': ls}
    pts = [corners[c] for c in cnns if c in corners]
    if pts: return {'type': 'Point', 'coordinates': pts[0]} if len(pts) == 1 else {'type': 'MultiPoint', 'coordinates': pts}
    return None


def stack_by_cnn(layer, records):
    """rows on the same street(s) become one feature: n, the common value of each keep field, items"""
    conf = layer.get('stack_by_cnn') or {}
    keep, at, out = conf.get('keep', []), defaultdict(list), []
    for p, geom, key in records: at[key].append((p, geom))
    for key, rows in at.items():
        if key is None:                               # no CNN on streets.json: each row as it is
            out += [({**p, 'n': 1}, g) for p, g in rows]; continue
        props = {'cnn' if len(key) == 1 else 'cnns': key[0] if len(key) == 1 else ','.join(map(str, key)), 'n': len(rows)}
        for f in keep:
            v = Counter(p.get(f) for p, _ in rows if p.get(f) is not None).most_common(1)
            if v: props[f] = v[0][0]
        if keep:
            for v, k in Counter(p.get(keep[0]) or 'other' for p, _ in rows).items(): props[f'n_{v}'] = k
        items = [{k: v for k, v in p.items() if v is not None and k not in SKIP_ITEM} for p, _ in rows]
        props['items'] = json.dumps(items, separators=(',', ':'), ensure_ascii=False)
        out.append((props, rows[0][1]))
    return out


SKIP_ITEM = {'cnn', 'cnns', 'x', 'y', 'latitude', 'longitude', 'lat', 'lon'}


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
    by_naics = sorted((conf.get('naics') or {}).items(), key=lambda kv: -len(kv[0]))
    for p, _ in records:
        o = p.get(by)
        n = re.sub(r'\D', '', p.get('naics') or '')
        p['kind'] = (named.get(o) or (None if o in keep else next((k for pre, k in by_naics if n.startswith(pre)), None))
                     or (None if o in keep else rule.get('kind') if o and len(addrs[o]) >= rule.get('min_addresses', 1e9) else None))
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
        # map labels: a business name that isn't a person's. `same_as` emptied `owner` where it matched the
        # business name, so a name with no separate owner is only used when it reads as a company (a sole
        # proprietor's or landlord's own name stays off the map; it's still on cards and in exports)
        words = lambda v: {w for w in re.findall(r'[a-z]+', (v or '').lower()) if len(w) > 1}
        def label(i):
            d = i.get('dba')
            if not d: return None
            if COMPANY.search(d): return d
            o = i.get('owner')
            # no separate owner, or the business name is the owner's own words reordered ("Anne Perkins" /
            # "Perkins Anne M"): a person's name
            if not o or words(d) <= words(o): return None
            last = re.findall(r'[a-z]+', d.lower())
            # "Joe Wittenbrook" / "Wittenbrook Joseph": a short name ending in the owner's surname
            return None if len(last) <= 3 and last and last[-1] in words(o) else d
        first = next((label(i) for i in items if not i.get('kind') and label(i)), None)
        props = {by: key, 'n': len(rows), 'shown': sum(1 for p, _ in rows if not p.get('kind')),
                 # for map labels: the first storefront's name (name), or the first of any (name_all)
                 'name': first, 'name_all': next((label(i) for i in items if label(i)), None),
                 'food': any(p.get('cat') == 'food' for p, _ in rows), 'items': json.dumps(items, separators=(',', ':'), ensure_ascii=False)}
        # the address's color: its most storefront-like business that isn't hidden (food, retail, services, other)
        cats = {p.get('cat') for p, _ in rows if not p.get('kind')} or {p.get('cat') for p, _ in rows}
        props['cat'] = next((c for c in ('food', 'retail', 'services', 'other') if c in cats), 'other')
        if g.get('counts'):
            c = g['counts']
            for v, k in Counter(p.get(c) or 'other' for p, _ in rows).items(): props[f'n_{v}'] = k
            for v, k in Counter(p.get(c) or 'other' for p, _ in rows if not p.get('kind')).items(): props[f'shown_{v}'] = k
        for f in g.get('keep', []):
            v = Counter(p.get(f) for p, _ in rows if p.get(f)).most_common(1)
            if v: props[f] = v[0][0]
        feats.append((props, {'type': 'Point', 'coordinates': list(pts.most_common(1)[0][0])}))
    return stack(g, feats) if g.get('stack') else feats


# `stack`: groups that land on the same point become one feature (the city puts 1601 and 1603 Church on one
# point, and every suite of an office building), so one dot can't hide another. Its first group (one with
# storefronts, then by street number) gives the label, color and `by`; `addresses` (`by`, plural) counts the groups, and each
# item carries its own `by` value.
plural = lambda w: w + ('es' if w.endswith('s') else 's')


def stack(g, feats):
    by, at = g['by'], defaultdict(list)
    for p, geom in feats: at[tuple(geom['coordinates'])].append(p)
    num = lambda v: int(m.group()) if (m := re.match(r'\d+', str(v or ''))) else 0
    out = []
    for c, ps in at.items():
        if len(ps) == 1:
            out.append((ps[0], {'type': 'Point', 'coordinates': list(c)})); continue
        ps.sort(key=lambda p: (p['shown'] == 0, num(p.get(by)), str(p.get(by))))
        items = [{**i, by: p.get(by)} for p in ps for i in json.loads(p['items'])]
        cats = {p['cat'] for p in ps if p['shown']} or {p['cat'] for p in ps}
        q = {**ps[0], plural(by): len(ps), 'n': sum(p['n'] for p in ps), 'shown': sum(p['shown'] for p in ps),
             'name': next((p['name'] for p in ps if p['name']), None), 'name_all': next((p['name_all'] for p in ps if p['name_all']), None),
             'food': any(p['food'] for p in ps), 'cat': next(k for k in ('food', 'retail', 'services', 'other') if k in cats),
             'items': json.dumps(items, separators=(',', ':'), ensure_ascii=False)}
        # per-value counts add up
        for k in {k for p in ps for k in p if k.startswith(('n_', 'shown_'))}: q[k] = sum(p.get(k, 0) for p in ps)
        out.append((q, {'type': 'Point', 'coordinates': list(c)}))
    return out


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
                        *sum((['-y', f] for f in overview_fields(ov['fields'], feats)), []), '--drop-densest-as-needed', str(src)], check=True)
        parts.insert(0, over)
    out = OUT / f"{layer['id']}.pmtiles"
    if len(parts) > 1:
        subprocess.run([tool('tile-join', tdir), '-q', '-f', '-o', str(out), *map(str, parts)], check=True,
                       stderr=subprocess.DEVNULL)
    else: detail.replace(out)
    return out, (ov['minzoom'] if ov else lo), hi


def overview_fields(names, feats):
    have = sorted({k for p, _ in feats for k in p})
    return [f for n in names for f in ([k for k in have if k.startswith(n[:-1])] if n.endswith('*') else [n])]


def counted(g, feats):
    # the n_<value> / shown_<value> fields `counts` added, for the manifest
    return {k: 'count' for k in sorted({k for p, _ in feats for k in p if re.match(r'(n|shown)_', k)})} if g.get('counts') else {}


def build(layer, src_rows, bbox, tdir):
    records, skipped, by_cnn, missing, keys = [], 0, bool(layer.get('geometry')), Counter(), []
    for row in src_rows:
        src = row.get('properties', row) if 'type' in row and 'geometry' in row else row
        geom, key = None, None
        if by_cnn:                                      # the street's line, else the row's own point
            cnns = cnns_of(layer, src)
            geom = cnn_geometry(cnns)
            if geom: key = tuple(sorted(cnns))
            else: missing['no cnn' if not cnns else 'cnn not in streets.json'] += 1
        geom = geom or geometry_of(layer, row)
        if not geom or not in_bbox(geom, bbox): skipped += 1; continue
        props = props_of(layer, src)
        records.append((props, {'type': geom['type'], 'coordinates': rnd(geom['coordinates'])}))
        keys.append(key)
    review = apply_kinds(layer, records)
    stats = stats_for(layer, records)
    feats = (stack_by_cnn(layer, [(p, g, k) for (p, g), k in zip(records, keys)]) if layer.get('stack_by_cnn')
             else group(layer, records) if layer.get('group') else records)
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
    simple = lambda t: 'number' if t in ('int', 'num', 'num1') else t if t in ('date', 'id') else 'text'   # naics, sector, category: text
    rowf = {**{n: simple(t) for n, t in field_types(layer).items()}, **({'kind': 'text'} if layer.get('kinds') else {})}
    if layer.get('group'):
        g = layer['group']
        fields_out = {g['by']: 'text', **{f: rowf.get(f, 'text') for f in g.get('keep', [])},
                      **({plural(g['by']): 'count'} if g.get('stack') else {}),
                      'n': 'count', 'shown': 'count', **counted(g, feats), 'name': 'text', 'name_all': 'text', 'cat': 'text', 'food': 'bool', 'items': 'json'}
    elif layer.get('stack_by_cnn'):
        keep = layer['stack_by_cnn'].get('keep', [])
        fields_out = {'cnn': 'id', 'cnns': 'text', 'n': 'count', **{f: rowf.get(f, 'text') for f in keep},
                      **{k: 'count' for k in sorted({k for p, _ in feats for k in p if k.startswith('n_')})}, 'items': 'json'}
    else: fields_out = rowf
    entry = {'id': layer['id'], 'label': layer['label'], 'year': layer.get('year'), 'file': out.name,
             'format': 'pmtiles' if tiled else 'geojson', 'layer': layer['id'], 'bytes': out.stat().st_size,
             'features': len(feats), 'records': len(records), 'geometry': gtypes.most_common(1)[0][0] if gtypes else None,
             **({'minzoom': zmin, 'maxzoom': zmax, 'detailzoom': (layer.get('tiles') or {}).get('minzoom', 15)} if tiled else {}),
             'fields': fields_out,
             'stats': f"{layer['id']}.stats.json", 'dataset': layer.get('dataset'), 'page': layer.get('page'),
             'retrieved': date.today().isoformat(), 'source': entry_hash(layer)}
    if layer.get('group'):
        entry['grouped_by'] = layer['group']['by']
        entry['items_fields'] = {f: rowf.get(f, 'text') for f in layer['group']['list'] + ([layer['group']['by']] if layer['group'].get('stack') else [])}
        if layer['group'].get('stack'): entry['stacked'] = True
    if by_cnn:
        # apps match these by CNN, not by location (sf-blocks#52)
        entry['join'] = 'cnn'
        entry['cnn_field'] = 'cnn' if layer.get('stack_by_cnn') else (layer['geometry'].get('cnn') or layer['geometry'].get('cnns'))
        entry['cnn_missing'] = sum(missing.values())
        if layer.get('stack_by_cnn'):
            entry['stacked_by'] = 'cnn'
            entry['items_fields'] = {f: t for f, t in rowf.items() if f not in SKIP_ITEM}
        log(f"  {len(records) - sum(missing.values()):,} rows on streets; " + (', '.join(f'{n:,} {why}' for why, n in missing.items()) or 'every CNN found'))
    log(f"  → data/tiles/{out.name}: {len(feats):,} features from {len(records):,} rows ({skipped:,} outside the region or without a location), "
        f"{out.stat().st_size / 1e6:.1f} MB")
    return entry, review, skipped


# ---------- the layers' entries ----------
def load_sources():
    """every layer's entry: sources.json first, then data/tiles/sources/<id>.json by name"""
    layers = json.loads((OUT / 'sources.json').read_text())['layers']
    d = OUT / 'sources'
    if d.is_dir():
        for p in sorted(d.glob('*.json')):
            e = json.loads(p.read_text())
            if e.get('id') != p.stem: raise SystemExit(f'{p}: its id should be {p.stem!r}')
            if any(l['id'] == e['id'] for l in layers): raise SystemExit(f'{e["id"]} is in sources.json and in {p.name}')
            layers.append(e)
    return layers


def changed_since(base):
    """ids of layers added or edited since a git commit (for the checks and the rebuild on a pull request)"""
    def at(path):
        r = subprocess.run(['git', 'show', f'{base}:{path}'], cwd=ROOT, capture_output=True, text=True)
        return json.loads(r.stdout) if r.returncode == 0 else None
    old = {l['id']: l for l in (at('data/tiles/sources.json') or {'layers': []})['layers']}
    r = subprocess.run(['git', 'ls-tree', '--name-only', base, 'data/tiles/sources/'], cwd=ROOT, capture_output=True, text=True)
    for path in r.stdout.split():
        e = at(path)
        if e: old[e['id']] = e
    return [l['id'] for l in load_sources() if old.get(l['id']) != l]


def entry_hash(layer):
    """a short fingerprint of a layer's entry, kept in index.json, so a check can tell a stale build"""
    import hashlib
    return hashlib.sha1(json.dumps(layer, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def check(index, layers, require):
    """files present for every built layer; warn about listed layers not built (or built from an older
    entry); fail for those in `require`"""
    built = {l['id']: l for l in index['layers']}
    bad = [l['id'] for l in index['layers'] if not (OUT / l['file']).exists() or not (OUT / l['stats']).exists()]
    for l in index['layers']: log(f"{l['id']}: {l['features']:,} features, {l['file']}" + (' MISSING' if l['id'] in bad else ' ok'))
    stale = []
    for l in layers:
        b = built.get(l['id'])
        why = 'not built' if not b else 'built from an older entry' if b.get('source') and b['source'] != entry_hash(l) else None
        if why:
            stale.append(l['id'])
            log(f"{'ERROR' if l['id'] in require else 'warning'}: {l['id']} is {why}. "
                f"Run Actions → Rebuild data with {l['id']} (or edit its entry on a pull request, which rebuilds it).")
    missing = [i for i in require if i not in {l['id'] for l in layers}]
    for i in missing: log(f'ERROR: {i} is not in the sources')
    return bool(bad or missing or set(require) & set(stale))


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
    """An entry for a new layer, in data/tiles/sources/<id>.json, with what the profile suggests: the fields
    worth keeping, text fields with a few values as categories (for chips and legends), and a point dataset
    keyed by street (a `cnn` field) drawn as its streets. Built straight away by the action; edit it on the
    pull request to change it, and the layer is rebuilt."""
    if any(l['id'] == layer_id for l in load_sources()): raise SystemExit(f'{layer_id} is already listed')
    meta = json.loads(get(f'{PORTAL}/api/views/{ds}.json'))
    cols = [c for c in meta['columns'] if not c['fieldName'].startswith(':')]
    geo = [c for c in cols if c['dataTypeName'] in GEOM]
    sample = json.loads(get(f'{PORTAL}/resource/{ds}.json?$limit=2000&$order=:id'))
    want = {k.strip() for k in (keep or '').split(',') if k.strip()}
    fields, cats = {}, []
    for c in cols:
        f, t = c['fieldName'], c['dataTypeName']
        if t in GEOM or (SKIP.search(f) and f not in want): continue
        vals = [r[f] for r in sample if r.get(f) not in (None, '')]
        filled = len(vals) / max(1, len(sample))
        if f in want or (not want and filled >= 0.02):
            fields[f] = f"{TYPE.get(t, 'text')}:{f}"
            # categories: text with 2–40 values that repeat, not an address or a name
            dist = len(set(map(str, vals)))
            if TYPE.get(t, 'text') == 'text' and 2 <= dist <= 40 and dist < len(vals) / 3 and not CONTACT.search(f) and not re.search(r'name|street|address', f, re.I):
                cats.append(f)
    for f in ('cnn', 'cnn_id', 'cnn_sgmt_pkey'):      # street ids: numbers, but no stats
        if f in fields: fields[f] = f'id:{f}'
    entry = {'id': layer_id, 'label': label or meta['name'], 'dataset': ds, 'page': f'{PORTAL}/d/{ds}',
             'year': year or 'current', 'fields': fields, 'categories': cats, 'tiles': {'minzoom': 15, 'maxzoom': 15}}
    if geo and geo[0]['dataTypeName'] in ('point', 'location') and not any(c['dataTypeName'] not in ('point', 'location') for c in geo):
        entry.update(format='csv', point={'wkt': geo[0]['fieldName']})
        # one point per street block: draw the streets instead (sf-blocks#52)
        cnn = next((f for f in ('cnn', 'cnn_id') if f in fields), None)
        if cnn: entry.update(geometry={'cnn': cnn}, stack_by_cnn={'keep': cats[:3]})
    else: entry['format'] = 'geojson'
    (OUT / 'sources').mkdir(exist_ok=True)
    (OUT / 'sources' / f'{layer_id}.json').write_text(json.dumps(entry, indent=2, ensure_ascii=False) + '\n')
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
    ap.add_argument('--changed-since', metavar='COMMIT', help='print the ids of layers added or edited since this commit')
    ap.add_argument('--require', default='', help='with --check: layer ids (comma separated) that must be built from their current entries')
    ap.add_argument('--add', metavar='ID', help='with --profile: add an entry for this new layer in data/tiles/sources/<ID>.json')
    ap.add_argument('--label'); ap.add_argument('--year'); ap.add_argument('--keep', help='fields to keep, comma separated')
    a = ap.parse_args()
    if a.profile and a.add:
        md = profile(a.profile)
        e = add(a.add, a.profile, a.label, a.year, a.keep)
        md += (f'\n\n### Its entry: `data/tiles/sources/{a.add}.json`\n\n```json\n' + json.dumps(e, indent=2, ensure_ascii=False) + '\n```\n\n'
               'To change it, edit that file on the pull request\'s branch: remove fields you don\'t want, set each type (int, num1, date, id…), '
               'list `categories`, check `year`. Saving the edit rebuilds the layer.')
        print(md)
        if a.report: Path(a.report).write_text(md + '\n')
        return
    if a.profile:
        md = profile(a.profile)
        print(md)
        if a.report: Path(a.report).write_text(md + '\n')
        return
    if a.changed_since:
        print(' '.join(changed_since(a.changed_since))); return
    conf = {'layers': load_sources()}
    index_file = OUT / 'index.json'
    index = json.loads(index_file.read_text()) if index_file.exists() else {'layers': []}
    if a.check:
        sys.exit(1 if check(index, conf['layers'], [i for i in re.split(r'[,\s]+', a.require) if i]) else 0)
    bbox = json.loads((ROOT / 'region.json').read_text())['bbox']
    bbox = [bbox[0] - 0.02, bbox[1] - 0.02, bbox[2] + 0.02, bbox[3] + 0.02]
    files = dict(x.split('=', 1) for x in a.file)
    layers = [l for l in conf['layers'] if not a.ids or l['id'] in a.ids]
    if a.ids and len(layers) != len(a.ids): raise SystemExit(f'not in the sources: {set(a.ids) - {l["id"] for l in layers}}')
    report = []
    for layer in layers:
        log(f"{layer['id']} ({layer.get('dataset') or files.get(layer['id'])})")
        rows = read_file(layer, files[layer['id']]) if layer['id'] in files else fetch(layer, a.raw)
        entry, review, skipped = build(layer, rows, bbox, a.tippecanoe)
        index['layers'] = [l for l in index['layers'] if l['id'] != entry['id']] + [entry]
        report.append(f"- **{layer['label']}** (`{layer['id']}`): {entry['features']:,} features from {entry['records']:,} rows, "
                      f"{entry['bytes'] / 1e6:.1f} MB `{entry['file']}`; {skipped:,} rows outside the region or without a location. Data year: {layer.get('year')}."
                      + (f" Drawn as streets by CNN; {entry['cnn_missing']:,} rows with a CNN that isn't in streets.json (kept at their own point when they have one)." if entry.get('join') == 'cnn' else ''))
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
    index['_doc'] = 'Map layers: data/tiles/<file>, built by scripts/build_tiles.py from sources.json and sources/<id>.json. Read with PMTiles (format pmtiles) or as GeoJSON.'
    index_file.write_text(json.dumps({'_doc': index['_doc'], 'layers': index['layers']}, indent=2, ensure_ascii=False) + '\n')
    if a.report: Path(a.report).write_text('\n'.join(report) + '\n')
    print('\n'.join(report))


if __name__ == '__main__':
    main()
