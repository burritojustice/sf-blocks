#!/usr/bin/env python3
# sf-blocks 2026.10.27.2: master copy, ported from civic-joy-fund/joiner's scripts/get_layers.mjs (v42).
"""Build the boundary sets in data/boundaries/ from DataSF (or local files) for Joiner, Block Party and
anything else that joins to San Francisco's areas.

    python3 scripts/get_layers.py                      all layers in data/boundaries/sources.json
    python3 scripts/get_layers.py zip_codes ...        just these layers
    python3 scripts/get_layers.py --file zip_codes=~/Downloads/SF_ZIP_Codes.geojson
                                                       use a file you exported instead of downloading
    python3 scripts/get_layers.py --check              re-validate the files already in data/boundaries

Each layer in sources.json comes from one of:
  dataset      a DataSF (Socrata) dataset id, downloaded as GeoJSON from the portal
  localFiles   GeoJSON files already in this repo (Who's on First, in data/uploads/wof/)
  dissolve     another layer's features merged by a shared property ({from, by}: precincts into districts)

Cleaning: keeps only the configured properties, sets feature.id to the join key, rounds coordinates
(6 decimals, about 10 cm), merges duplicate keys into one MultiPolygon when the layer allows it, and
sorts features by key so reruns produce small diffs. Dates like 2022-01-01T00:00:00.000 become
2022-01-01.

bbox: the FeatureCollection's "bbox" covers only polygon parts that touch mainlandBbox, so fitting the
map to a layer doesn't zoom out to the Farallones (part of District 4 and one census tract). The full
extent is kept as "extent". Regional layers use their whole extent.

Writes data/boundaries/<id>.geojson (one feature per line) and the manifest data/boundaries/index.json,
which the apps read. Output is byte-for-byte what get_layers.mjs wrote for the same input, apart from
the "retrieved" date and the manifest's _doc line. Standard library only.
"""
import json, math, re, sys, unicodedata, urllib.request
from datetime import date
from functools import cmp_to_key
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'boundaries'
CONFIG_FILE = OUT / 'sources.json'
SODA_LIMIT = 50000


def die(msg):
    print('error: ' + msg, file=sys.stderr)
    sys.exit(1)


# ── JSON written the way JavaScript's JSON.stringify writes it ──────────────────────────────────────
# Python and JavaScript both print the shortest float that reads back the same, but differ on whole
# numbers (-122.0 vs -122) and exponents (1e-05 vs 0.00001), so numbers are formatted here.

def js_num(x):
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        return 'null'
    if x == 0:
        return '0'
    if x.is_integer() and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)
    if 'e' not in r:
        return r
    mant, exp = r.split('e')
    exp = int(exp)
    if -7 <= exp < 21:                       # JS uses plain notation here; Python switched to e-notation
        sign = '-' if mant.startswith('-') else ''
        digits = mant.lstrip('-').replace('.', '')
        point = 1 + exp                      # position of the decimal point within digits
        if point <= 0:
            s = '0.' + '0' * -point + digits
        elif point >= len(digits):
            s = digits + '0' * (point - len(digits))
        else:
            s = digits[:point] + '.' + digits[point:]
        return sign + s
    return f"{mant}e{'+' if exp > 0 else '-'}{abs(exp)}"


def js_str(v):
    """String(v) in JavaScript"""
    if v is None:
        return 'null'
    if isinstance(v, (bool, int, float)):
        return js_num(v)
    return str(v)


def stringify(v, indent=None, _level=0):
    if v is None:
        return 'null'
    if isinstance(v, (bool, int, float)):
        return js_num(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        if not v:
            return '[]'
        items = [stringify(x, indent, _level + 1) for x in v]
    elif isinstance(v, dict):
        if not v:
            return '{}'
        items = [json.dumps(str(k), ensure_ascii=False) + (': ' if indent else ':') + stringify(x, indent, _level + 1)
                 for k, x in v.items()]
    else:
        raise TypeError(type(v))
    o, c = ('[', ']') if isinstance(v, (list, tuple)) else ('{', '}')
    if not indent:
        return o + ','.join(items) + c
    pad, inner = ' ' * indent * _level, ' ' * indent * (_level + 1)
    return o + '\n' + ',\n'.join(inner + i for i in items) + '\n' + pad + c


def js_len(s):
    """String length in UTF-16 code units, as JavaScript counts it"""
    return len(s.encode('utf-16-le')) // 2


# ── sort order: Intl.Collator('en', {numeric: true}) ────────────────────────────────────────────────
# ICU's root order: spaces, then punctuation, symbols, digits (compared as numbers), letters. Case and
# accents only break ties ('base' sensitivity ignores them entirely).
PUNCT = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def _units(s):
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            out.append((3, int(s[i:j]), ''))
            i = j
            continue
        base = ''.join(c for c in unicodedata.normalize('NFD', ch) if not unicodedata.combining(c))
        if ch.isspace():
            out.append((0, 0, ch))
        elif base.isalpha():
            out.append((4, 0, base.casefold()))
        elif ch in PUNCT:
            out.append((1, PUNCT.index(ch), ''))
        else:
            out.append((2, ord(ch), ''))
        i += 1
    return out


def _ties(s):
    """what 'variant' sensitivity compares once the base letters and numbers are equal: accents, then
    case (lowercase first). Leading zeros never count ("09" and "9" are equal; input order stays)."""
    accents, case = [], []
    for ch in re.sub(r'\d+', '', s):
        accents.append(''.join(c for c in unicodedata.normalize('NFD', ch) if unicodedata.combining(c)))
        case.append(ch.isupper())
    return accents, case


def collate(a, b, tiebreak):
    ua, ub = _units(a), _units(b)
    if ua != ub:
        return -1 if ua < ub else 1
    if not tiebreak or a == b:
        return 0
    ta, tb = _ties(a), _ties(b)
    return 0 if ta == tb else -1 if ta < tb else 1


natural_key = cmp_to_key(lambda a, b: collate(a, b, False))    # sensitivity: 'base', as get_layers.mjs
locale_key = cmp_to_key(lambda a, b: collate(a, b, True))      # localeCompare, as JoinKit's dissolve


# ── geometry helpers ────────────────────────────────────────────────────────────────────────────────
def jround(n, p):
    """Math.round(n * 10^p) / 10^p (halves round up, as in JavaScript)"""
    f = 10 ** p
    return math.floor(n * f + 0.5) / f


def clean_ring(ring, p):
    out = []
    for c in ring:
        pt = [jround(c[0], p), jround(c[1], p)]
        if not out or out[-1][0] != pt[0] or out[-1][1] != pt[1]:
            out.append(pt)
    if out and (out[0][0] != out[-1][0] or out[0][1] != out[-1][1]):
        out.append([out[0][0], out[0][1]])
    return out if len(out) >= 4 else None


def to_polygons(geom, p):
    """always a list of polygons (MultiPolygon coordinates)"""
    if not geom:
        return []
    t = geom.get('type')
    polys = [geom['coordinates']] if t == 'Polygon' else geom['coordinates'] if t == 'MultiPolygon' else None
    if polys is None:
        raise ValueError(f'expected Polygon/MultiPolygon, got {t}')
    out = []
    for rings in polys:
        cleaned = [r for r in (clean_ring(r, p) for r in rings) if r]
        if cleaned:
            out.append(cleaned)
    return out


def empty_bbox():
    return [math.inf, math.inf, -math.inf, -math.inf]


def extend_bbox(b, ring):
    for x, y in ((c[0], c[1]) for c in ring):
        if x < b[0]: b[0] = x
        if y < b[1]: b[1] = y
        if x > b[2]: b[2] = x
        if y > b[3]: b[3] = y
    return b


def intersects(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def bboxes(features, mainland):
    extent, view, offshore = empty_bbox(), empty_bbox(), 0
    for f in features:
        for poly in f['geometry']['coordinates']:
            pb = extend_bbox(empty_bbox(), poly[0])
            extend_bbox(extent, poly[0])
            if intersects(pb, mainland):
                extend_bbox(view, poly[0])
            else:
                offshore += 1
    return extent, (view if math.isfinite(view[0]) else extent), offshore


# ── dissolve: JoinKit 0.3's dissolve, ported ────────────────────────────────────────────────────────
# Shared edges cancel and the rest are chained into rings. Neighbors must share vertices exactly (true
# of files cut from one map); otherwise the group falls back to a MultiPolygon of its members.
def pt_key(p):
    return f'{p[0]:.7f},{p[1]:.7f}'


def signed_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return a / 2


def polys_of(g):
    if not g:
        return []
    return [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates'] if g['type'] == 'MultiPolygon' else []


def ring_contains(ring, x, y):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def dissolve_geometries(geoms):
    polys = [p for g in geoms for p in polys_of(g)]
    if len(polys) <= 1:
        return {'type': 'Polygon', 'coordinates': polys[0]} if polys else None
    edges = {}
    for poly in polys:
        for r, ring in enumerate(poly):
            rr = ring if (signed_area(ring) > 0) == (r == 0) else ring[::-1]    # outers CCW, holes CW
            for i in range(len(rr) - 1):
                a, b = rr[i], rr[i + 1]
                ka, kb = pt_key(a), pt_key(b)
                if ka == kb:
                    continue
                k = ka + '|' + kb if ka < kb else kb + '|' + ka
                if k in edges:
                    edges[k]['n'] += 1
                else:
                    edges[k] = {'a': a, 'b': b, 'ka': ka, 'kb': kb, 'n': 1}
    left = [e for e in edges.values() if e['n'] == 1]
    starts = {}
    for e in left:
        starts.setdefault(e['ka'], []).append(e)
    used, rings = set(), []
    for e0 in left:
        if id(e0) in used:
            continue
        ring, e, guard = [e0['a']], e0, 0
        while e is not None and id(e) not in used and guard < 1e6:
            guard += 1
            used.add(id(e))
            ring.append(e['b'])
            if e['kb'] == e0['ka']:
                break
            e = next((x for x in starts.get(e['kb'], []) if id(x) not in used), None)
        if pt_key(ring[0]) != pt_key(ring[-1]) or len(ring) < 4:
            return None
        rings.append(ring)
    outers = [[r] for r in rings if signed_area(r) > 0]
    if not outers:
        return None
    for h in (r for r in rings if signed_area(r) <= 0):
        homes = sorted((o for o in outers if ring_contains(o[0], h[0][0], h[0][1])), key=lambda o: abs(signed_area(o[0])))
        if homes:
            homes[0].append(h)
    return {'type': 'Polygon', 'coordinates': outers[0]} if len(outers) == 1 else {'type': 'MultiPolygon', 'coordinates': outers}


def dissolve(fc, prop):
    groups = {}
    for f in fc['features']:
        v = (f.get('properties') or {}).get(prop)
        if v is None or v == '':
            continue
        groups.setdefault(js_str(v), []).append(f)
    features = []
    for k in sorted(groups, key=locale_key):
        fs = groups[k]
        geom = dissolve_geometries([f['geometry'] for f in fs]) or \
            {'type': 'MultiPolygon', 'coordinates': [p for f in fs for p in polys_of(f['geometry'])]}
        features.append({'type': 'Feature', 'id': k, 'properties': {prop: k, 'name': k, 'parts': len(fs)}, 'geometry': geom})
    return {'type': 'FeatureCollection', 'features': features}


# ── one layer ───────────────────────────────────────────────────────────────────────────────────────
def load(layer, cfg, files):
    if layer['id'] in files:
        path = files[layer['id']]
        print(f'  reading {path}')
        return json.loads(path.read_text(encoding='utf-8')), 'file:' + path.name
    if layer.get('dissolve'):
        src_id, by = layer['dissolve']['from'], layer['dissolve']['by']
        src = OUT / f'{src_id}.geojson'
        if not src.exists():
            raise RuntimeError(f'build "{src_id}" first (dissolve source)')
        print(f'  dissolving {src_id} by {by}')
        return dissolve(json.loads(src.read_text(encoding='utf-8')), by), f'{src_id} dissolved by {by}'
    if layer.get('localFiles'):
        features = []
        for f in layer['localFiles']:
            print(f'  reading {f}')
            features += json.loads((ROOT / f).read_text(encoding='utf-8'))['features']
        return {'type': 'FeatureCollection', 'features': features}, ' + '.join(layer['localFiles'])
    url = f"{cfg['portal']}/resource/{layer['dataset']}.geojson?$limit={SODA_LIMIT}"
    print(f'  fetching {url}')
    req = urllib.request.Request(url, headers={'Accept': 'application/geo+json, application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode('utf-8')), url


DATE_T = re.compile(r'^(\d{4}-\d\d-\d\d)T00:00:00(\.000)?$')


def clean(layer, gj, cfg):
    if not isinstance(gj, dict) or gj.get('type') != 'FeatureCollection' or not isinstance(gj.get('features'), list):
        raise ValueError('not a GeoJSON FeatureCollection')
    if len(gj['features']) >= SODA_LIMIT:
        print(f"  ! {len(gj['features'])} features — hit the download limit, data may be cut off")
    p = cfg.get('precision', 6)
    by_key, warnings = {}, []
    for f in gj['features']:
        props = f.get('properties') or {}
        raw = props.get(layer['key'])
        key = '' if raw is None else js_str(raw).strip()
        if not key:
            warnings.append(f'dropped a feature with no "{layer["key"]}"')
            continue
        polys = to_polygons(f.get('geometry'), p)
        if not polys:
            warnings.append(f'dropped "{key}": empty geometry')
            continue
        if key in by_key:
            if not layer.get('mergeByKey'):
                raise ValueError(f'duplicate key "{key}" — set "mergeByKey": true if parts should be combined')
            by_key[key]['geometry']['coordinates'].extend(polys)
            by_key[key]['_parts'] += 1
            continue
        kept = {}
        for k in layer['keep']:
            v = props.get(k)
            if v is not None and v != '':
                kept[k] = DATE_T.sub(r'\1', v.strip()) if isinstance(v, str) else v
        by_key[key] = {'type': 'Feature', 'id': key, 'properties': kept,
                       'geometry': {'type': 'MultiPolygon', 'coordinates': polys}, '_parts': 1}
    merged = [f"{f['id']}×{f['_parts']}" for f in by_key.values() if f['_parts'] > 1]
    features = [{k: v for k, v in f.items() if k != '_parts'} for f in sorted(by_key.values(), key=lambda f: natural_key(f['id']))]
    if layer.get('expectCount') and len(features) != layer['expectCount']:
        warnings.append(f"expected {layer['expectCount']} features, got {len(features)}")
    return features, merged, warnings


def serialize(fc):
    """one feature per line: readable diffs, still compact"""
    head = {k: v for k, v in fc.items() if k != 'features'}
    return stringify(head)[:-1] + ',"features":[\n' + ',\n'.join(stringify(f) for f in fc['features']) + '\n]}\n'


def manifest_entry(layer, fc, nbytes, source):
    e = {'id': layer['id'], 'label': layer['label']}
    if layer.get('short'): e['short'] = layer['short']
    e['tab'] = layer.get('tab')
    if layer.get('default'): e['default'] = True
    e.update(file=f"{layer['id']}.geojson", key=layer['key'], name=layer.get('name'))
    for k in ('nameTemplate', 'labelTemplate', 'labelExtras'):
        if layer.get(k): e[k] = layer[k]
    if layer.get('match'): e['match'] = layer['match']
    if layer.get('regional'): e['regional'] = True
    if layer.get('dissolve'): e['dissolve'] = layer['dissolve']
    e.update(count=len(fc['features']), bbox=fc['bbox'], extent=fc['extent'], bytes=nbytes)
    if layer.get('dataset'): e['dataset'] = layer['dataset']
    e.update(page=layer.get('page'), source=source, retrieved=date.today().isoformat())
    return {k: v for k, v in e.items() if not (k in ('tab', 'name', 'page') and v is None)}


def process_layer(layer, cfg, files):
    print(f"{layer['id']} ({layer.get('dataset') or 'local files'})")
    gj, source = load(layer, cfg, files)
    features, merged, warnings = clean(layer, gj, cfg)
    extent, view, offshore = bboxes(features, [-180, -90, 180, 90] if layer.get('regional') else cfg['mainlandBbox'])
    fc = {'type': 'FeatureCollection', 'name': layer['id'], 'bbox': [jround(n, 5) for n in view],
          'extent': [jround(n, 5) for n in extent], 'features': features}
    text = serialize(fc)
    (OUT / f"{layer['id']}.geojson").write_text(text, encoding='utf-8')
    n = js_len(text)
    print(f"  → data/boundaries/{layer['id']}.geojson  {len(features)} features, {n / 1024:.0f} kB"
          + (f", merged {' '.join(merged)}" if merged else '') + (f', {offshore} offshore part(s) outside bbox' if offshore else ''))
    for w in warnings:
        print('  ! ' + w)
    return manifest_entry(layer, fc, n, source)


def check(layer):
    f = OUT / f"{layer['id']}.geojson"
    if not f.exists():
        print(f"{layer['id']}: missing — run without --check")
        return False
    fc = json.loads(f.read_text(encoding='utf-8'))
    ids = [x['id'] for x in fc['features']]
    problems = []
    if len(set(ids)) != len(ids): problems.append('duplicate feature ids')
    if any(x['properties'].get(layer['key']) is None for x in fc['features']): problems.append(f'features missing "{layer["key"]}"')
    if layer.get('expectCount') and len(ids) != layer['expectCount']: problems.append(f"expected {layer['expectCount']}, got {len(ids)}")
    print(f"{layer['id']}: {len(ids)} features" + (' — ' + '; '.join(problems) if problems else ' ok'))
    return not problems


def main(argv):
    cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    files, only, check_only = {}, [], False
    it = iter(argv)
    for a in it:
        if a == '--check':
            check_only = True
        elif a == '--file':
            ident, _, p = (next(it, '') or '').partition('=')
            if not ident or not p:
                die('--file needs <layer-id>=<path>')
            files[ident] = Path(p).expanduser()
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        else:
            only.append(a)
    known = {l['id'] for l in cfg['layers']}
    for ident in only + list(files):
        if ident not in known:
            die(f'unknown layer "{ident}" — see data/boundaries/sources.json')
    named = set(only) | set(files)
    selected = [l for l in cfg['layers'] if not named or l['id'] in named]

    if check_only:
        return 0 if all([check(l) for l in selected]) else 1

    OUT.mkdir(parents=True, exist_ok=True)
    index_file = OUT / 'index.json'
    index = json.loads(index_file.read_text(encoding='utf-8')) if index_file.exists() else {'layers': []}
    entries = {e['id']: e for e in index['layers']}
    failed = 0
    for layer in selected:
        try:
            entries[layer['id']] = process_layer(layer, cfg, files)
        except Exception as e:   # one bad layer shouldn't stop the rest
            failed += 1
            print(f"  ✗ {layer['id']}: {e}", file=sys.stderr)
    out = {'_doc': 'Written by scripts/get_layers.py — do not edit by hand.', 'portal': cfg['portal'],
           'layers': [entries[l['id']] for l in cfg['layers'] if l['id'] in entries]}
    index_file.write_text(stringify(out, indent=2) + '\n', encoding='utf-8')
    print(f"\nwrote data/boundaries/index.json ({len(out['layers'])} layers)" + (f', {failed} failed' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
