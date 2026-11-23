#!/usr/bin/env python3
# sf-blocks 2026.11.23: master copy, moved here from civic-joy-fund/block-party.
"""Build the small map overlay files in data/layers/ from the raw downloads in data/uploads/.

    python3 scripts/build_layers.py              # reads data/uploads/, writes data/layers/ and its index.json
    python3 scripts/build_layers.py --index      # only rewrites data/layers/index.json from the files there
    python3 scripts/build_layers.py shoreline    # builds only the layers named
    python3 scripts/build_layers.py --download   # fetch fresh copies of every dataset first

Standard library only. Any dataset in SOURCES with no file in data/uploads/ is downloaded from DataSF's API
first, named like a DataSF Export: dataset title plus a date stamp ("Muni_Simple_Routes_20261011.geojson").
A manual Export works too; leave the file name alone. The script finds each file by title, taking the
newest stamp when there are several, so old downloads can stay. Older hand-renamed files
(SF_muni_lines.geojson etc.) are found by the keywords in `also`.

Schools is never re-downloaded once a file exists, because that file has hand-added columns
(short_name, elevation); see the note in SOURCES.

Only the fields the map uses are kept, and coordinates are rounded to 5 decimals (about 1 m).
Each output records its source dataset and the file it came from. Muni geometry is passed through
as published (no merging); see README "Map layers".

Downloads use https://data.sf.gov/resource/<id>.geojson (or .csv), which has the same column names
as the site's Export.
"""
import argparse, csv, json, math, re, sys, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / 'data' / 'uploads', ROOT / 'data' / 'layers'

# out name -> where it comes from. 'title' is the DataSF dataset title, which is also how downloads are named.
SOURCES = {
    # NOAA Office of Coast Survey historical surveys (T-sheets), exported through Selecter: one GeoJSON per
    # survey in data/uploads/shoreline/, built into one layer with a survey field (not from DataSF)
    'shoreline': {'title': 'NOAA historical shoreline surveys (T-sheets)', 'id': None, 'format': 'GeoJSON',
                  'url': 'https://shoreline.noaa.gov/t-sheets.html', 'also': ['shoreline'], 'folder': 'shoreline'},
    # built from the shoreline layer (build_shoreline), not downloaded
    'shoreline_water': {'title': 'NOAA historical shoreline surveys (T-sheets): water areas', 'id': None, 'format': 'GeoJSON',
                        'url': 'https://shoreline.noaa.gov/t-sheets.html', 'also': []},
    'muni': {'title': 'Muni Simple Routes', 'id': '9exe-acju', 'format': 'GeoJSON',
             'url': 'https://data.sf.gov/Transportation/Muni-Simple-Routes/9exe-acju/about_data',
             'also': ['muni']},
    'bike': {'title': 'MTA Bike Network Linear Features', 'id': 'ygmz-vaxd', 'format': 'GeoJSON',
             'url': 'https://data.sf.gov/Transportation/MTA-Bike-Network-Linear-Features/ygmz-vaxd/about_data',
             'also': ['bike']},
    # The file in layers/ is this dataset plus columns added after download: short_name (used for the map
    # label), elevation, and, coming, enrollment joined from the California Department of Education. That
    # join gets its own documented workflow (maybe its own repo, since it works statewide), so a raw DataSF
    # download here would be missing short_name; the build falls back to the full school name.
    'schools': {'title': 'Schools', 'id': '7e7j-59qk', 'format': 'GeoJSON',
                'url': 'https://data.sf.gov/Economy-and-Community/Schools/7e7j-59qk/about_data',
                'also': ['school']},
    'stations': {'title': 'City-owned Facilities: Fire and Police', 'id': 'wt27-4jim', 'format': 'CSV',
                 'url': 'https://data.sf.gov/City-Infrastructure/City-owned-Facilities-Fire-and-Police/wt27-4jim/about_data',
                 'also': ['sffd', 'station']},
    'slow': {'title': 'Slow Streets', 'id': 'hkz3-itiu', 'format': 'GeoJSON',
             'url': 'https://data.sf.gov/Transportation/Slow-Streets/hkz3-itiu/about_data',
             'also': ['slow']},
    'lands': {'title': 'City Lands', 'id': 'gtnh-hgvs', 'format': 'GeoJSON',
              'url': 'https://data.sf.gov/City-Infrastructure/City-Lands/gtnh-hgvs/about_data',
              'also': ['city_lands', 'citylands']},
    'health': {'title': 'Health Care Facilities', 'id': 'jhsu-2pka', 'format': 'CSV',
               'url': 'https://data.sf.gov/Health-and-Social-Services/Health-Care-Facilities/jhsu-2pka/about_data',
               'also': ['health']},
}


# How apps list each layer (data/layers/index.json): a label, and the field to split it by, if any.
LAYER_INFO = {
    'muni': {'label': 'Muni routes', 'category': 'service', 'name': 'route'},
    'bike': {'label': 'Bike network', 'category': 'cls', 'name': 'kind'},
    'slow': {'label': 'Slow Streets', 'category': 'status', 'name': 'corridor'},
    'schools': {'label': 'Schools', 'category': 'type', 'name': 'name'},
    'stations': {'label': 'Fire and police stations', 'category': 'kind', 'name': 'name'},
    'health': {'label': 'Health care facilities', 'category': 'kind', 'name': 'name'},
    'lands': {'label': 'City-owned land', 'category': 'cat', 'name': 'name'},
    'shoreline': {'label': 'Shoreline 1850–1857', 'category': 'survey', 'name': 'kind',
                  'colors': {'1850–52': '#1C7ED6', '1853': '#E8590C', '1857': '#2F9E44'}},
    # draw 'water': apps paint it in the basemap's water color, just above the basemap's water and under its
    # roads, so land that was water then shows as water
    'shoreline_water': {'label': 'Water in the 1850s', 'category': 'survey', 'name': 'survey', 'draw': 'water',
                        'colors': {'1850–52': '#1C7ED6', '1853': '#E8590C', '1857': '#2F9E44'}},
}


def cats(feats, field):
    """the category field's values, most common first, with counts (up to 24), for apps' chips and keys"""
    if not field:
        return None
    n = {}
    for f in feats:
        v = (f.get('properties') or {}).get(field)
        if v not in (None, ''):
            n[str(v)] = n.get(str(v), 0) + 1
    return dict(sorted(n.items(), key=lambda kv: -kv[1])[:24]) or None


def write_index():
    """data/layers/index.json: every layer file here, with its label, geometry, fields and source, so apps can
    list them without knowing them (Joiner's Layers menu). Same shape as data/tiles/index.json's entries."""
    layers = []
    for key, info in LAYER_INFO.items():
        p = OUT / f'{key}.geojson'
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        feats, src = d['features'], d.get('source') or {}
        kinds = sorted({(f.get('geometry') or {}).get('type', '').replace('Multi', '') for f in feats} - {''})
        fields = {}
        for f in feats:
            for k, v in (f.get('properties') or {}).items():
                if v in (None, ''):
                    continue
                t = 'number' if isinstance(v, (int, float)) and not isinstance(v, bool) else 'text'
                if fields.get(k) != 'text':
                    fields[k] = t
        layers.append({'id': key, 'label': info['label'], 'file': p.name, 'format': 'geojson',
                       'geometry': kinds[0] if len(kinds) == 1 else kinds, 'features': len(feats), 'bytes': p.stat().st_size,
                       'fields': fields, 'category': info.get('category'), 'name': info.get('name'),
                       'categories': cats(feats, info.get('category')), 'colors': info.get('colors'), 'draw': info.get('draw'),
                       'title': src.get('title'), 'dataset': src.get('id'), 'page': src.get('url'), 'data_as_of': src.get('data_as_of')})
    out = OUT / 'index.json'
    out.write_text(json.dumps({'_doc': 'Small map layers: data/layers/<file>, GeoJSON, built by scripts/build_layers.py.', 'layers': layers}, indent=1) + '\n')
    print(f'{out.relative_to(ROOT)}: {len(layers)} layers', flush=True)


def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


API = 'https://data.sf.gov/resource/{id}.{ext}?$limit=200000'


def download(key):
    src = SOURCES[key]
    ext = 'csv' if src['format'] == 'CSV' else 'geojson'
    name = re.sub(r'[^A-Za-z0-9-]+', '_', src['title']).strip('_')
    path = SRC / f'{name}_{date.today():%Y%m%d}.{ext}'
    print(f'downloading {src["title"]} -> layers/{path.name}', flush=True)
    req = urllib.request.Request(API.format(id=src['id'], ext=ext), headers={'User-Agent': 'block-party'})
    tmp = path.with_suffix(path.suffix + '.part')
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, 'wb') as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)
    return path


def stamp(p):
    """the date stamp DataSF adds to downloads, or 0"""
    m = re.findall(r'(20\d{6})', p.stem)
    return int(m[-1]) if m else 0


def find(key):
    src = SOURCES[key]
    files = [p for p in SRC.iterdir() if p.is_file() and p.suffix.lower() in ('.geojson', '.json', '.csv')]
    by_title = [p for p in files if norm(p.stem).startswith(norm(src['title']))]
    hits = by_title or [p for p in files if any(w in p.name.lower() for w in src['also'])]
    if not hits:
        return None
    hits.sort(key=lambda p: (stamp(p), p.stat().st_mtime))
    if len(hits) > 1:
        print(f'  {key}: {len(hits)} candidate files, using the newest ({hits[-1].name})', flush=True)
    return hits[-1]


def rnd(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 5), round(c[1], 5)]
    return [rnd(x) for x in c]


def dedupe_line(coords):
    out = []
    for c in coords:
        if not out or out[-1] != c:
            out.append(c)
    return out


def geom(g):
    if not g:
        return None
    c = rnd(g['coordinates'])
    if g['type'] == 'LineString':
        c = dedupe_line(c)
    elif g['type'] == 'MultiLineString':
        c = [dedupe_line(l) for l in c]
    return {'type': g['type'], 'coordinates': c}


def feat(g, props):
    return {'type': 'Feature', 'geometry': g, 'properties': {k: v for k, v in props.items() if v not in (None, '')}}


def write(name, feats, src, data_as_of=None):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f'{name}.geojson'
    meta = {k: SOURCES[name][k] for k in ('title', 'id', 'url')}
    meta.update({'file': src.name, 'data_as_of': data_as_of})
    p.write_text(json.dumps({'type': 'FeatureCollection', 'source': meta, 'features': feats}, separators=(',', ':')))
    print(f'{p.relative_to(ROOT)}: {len(feats)} features, {p.stat().st_size / 1024:.0f} KB  (from {src.name})', flush=True)


def as_of(p):
    """latest data_as_of in a GeoJSON download, as a date"""
    dates = [f['properties'].get('data_as_of') or '' for f in json.loads(p.read_text())['features']]
    return max(dates)[:10] or None if dates else None


def build_muni(p):
    feats = []
    for f in json.loads(p.read_text())['features']:
        pr = f['properties']
        if pr.get('service_ca') == 'Other':     # FBUS, KBUS, NBUS, TBUS: rail-replacement buses
            continue
        g = geom(f['geometry'])
        if g:
            feats.append(feat(g, {'route': pr['route_name'].strip(), 'service': pr.get('service_ca'), 'dir': pr.get('direction')}))
    feats.sort(key=lambda f: (f['properties']['route'], f['properties'].get('dir', '')))
    write('muni', feats, p, as_of(p))


BIKE_KIND = {'SEPARATED BIKEWAY': 'separated', 'BIKE LANE': 'lane', 'BIKE PATH': 'path',
             'BIKE ROUTE': 'route', 'NEIGHBORWAY': 'neighborway'}
BARRIER_WORDS = [  # (pattern, short word); first match wins for each part
    (r'SAFE.?HIT|K71', 'posts'), (r'CONCRETE ISLAND', 'concrete island'), (r'CONCRETE', 'concrete'),
    (r'PARKING', 'parking'), (r'K-?RAIL', 'k-rail'), (r'CURB', 'curb'), (r'SPEED BUMP', 'bumps'),
]


def barrier(s):
    if not s:
        return None
    out = []
    for part in re.split(r'[;:]', s.upper()):
        for pat, word in BARRIER_WORDS:
            if re.search(pat, part):
                if word not in out:
                    out.append(word)
                break
    return ', '.join(out) or None


def build_bike(p):
    feats = []
    for f in json.loads(p.read_text())['features']:
        pr = f['properties']
        g = geom(f['geometry'])
        kind = BIKE_KIND.get((pr.get('symbology') or '').strip())
        if not g or not kind:
            continue
        cnn = (pr.get('cnn') or '').strip()
        feats.append(feat(g, {'kind': kind, 'cls': pr.get('facility_t'), 'barrier': barrier(pr.get('barrier')),
                              'cnn': int(cnn) if cnn.isdigit() else None}))
    write('bike', feats, p, as_of(p))


def build_schools(p):
    feats = []
    for f in json.loads(p.read_text())['features']:
        pr = f['properties']
        g = geom(f['geometry'])
        if not g:
            continue
        name = (pr.get('short_name') or pr.get('school') or '').strip()
        feats.append(feat(g, {'name': name, 'type': pr.get('entity_type'),
                              'public': str(pr.get('public_yesno')).lower() in ('true', '1')}))
    write('schools', feats, p, as_of(p))


def read_csv(p):
    """rows with column names lowercased and spaces turned to underscores, so the API's names
    (facility_name) and the site Export's ("Facility Name") read the same"""
    with open(p, newline='', encoding='utf-8-sig', errors='replace') as fh:
        return [{re.sub(r'\s+', '_', (k or '').strip().lower()): v for k, v in r.items()} for r in csv.DictReader(fh)]


def build_stations(p):
    feats = []
    for r in read_csv(p):
        try:
            x, y = float(r['longitude']), float(r['latitude'])
        except (KeyError, ValueError):
            continue
        kind = 'fire' if 'fire' in (r.get('jurisdiction') or '').lower() else 'police'
        feats.append(feat({'type': 'Point', 'coordinates': rnd([x, y])},
                          {'name': (r.get('common_name') or '').strip(), 'kind': kind}))
    write('stations', feats, p)


# DataSF's facility names are in title case, which mangles acronyms ("Ucsf", "Sfgh")
ACRONYMS = {'Ucsf': 'UCSF', 'Sfgh': 'SFGH', 'Ahf': 'AHF', 'Baart': 'BAART', 'Lpc': 'LPC', 'Pace': 'PACE'}


def tidy_name(s):
    s = re.sub(r'\s+', ' ', s.replace(' ', ' ')).strip()
    return ' '.join(ACRONYMS.get(w, w) for w in s.split(' '))


def ymd(v):
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', v or '') or re.match(r'(\d{2})/(\d{2})/(\d{4})', v or '')
    if not m:
        return None
    a, b, c = m.groups()
    return f'{a}-{b}-{c}' if len(a) == 4 else f'{c}-{a}-{b}'


def build_slow(p):
    """one feature per block; slw_st = 0 marks blocks that were planned and then dropped"""
    feats = []
    for f in json.loads(p.read_text())['features']:
        pr = f['properties']
        if str(pr.get('slw_st', '1')).strip() in ('0', '0.0'):
            continue
        g = geom(f['geometry'])
        cnn = str(pr.get('cnn') or '').split('.')[0].strip()
        if not g or not cnn.isdigit():
            continue
        feats.append(feat(g, {'cnn': int(cnn), 'corridor': (pr.get('extents') or '').strip(),
                              'status': (pr.get('status') or '').strip(), 'type': (pr.get('type') or '').strip(),
                              'installed': ymd(pr.get('install_date'))}))
    write('slow', feats, p, as_of(p))


# City Lands "category" -> the short key the map filters on (Layers menu checkboxes)
LAND_CATS = {
    'Unified School District': 'school', 'Recreation & Park': 'park', 'Fire': 'fire', 'Police': 'police',
    'Health': 'health', 'Public Health': 'health', 'Port': 'port', 'Public Library': 'library', 'MTA': 'mta',
    'Public Works': 'works', 'PUC/Water': 'puc', 'PUC/Wastewater': 'puc', 'PUC/Hetch Hetchy': 'puc',
    'SFHA': 'housing', 'Real Estate': 'realestate', 'OCII - Former SFRA': 'ocii',
}
KX, KY = 111320 * math.cos(math.radians(37.76)), 110540


def simplify(ring, tol=0.5):
    """Douglas-Peucker on a closed ring, tolerance in meters; keeps at least 4 points"""
    if len(ring) <= 5:
        return ring
    pts = [(x * KX, y * KY) for x, y in ring]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        vx, vy = bx - ax, by - ay
        L = math.hypot(vx, vy)
        best, bi = 0, None
        for i in range(a + 1, b):
            px, py = pts[i]
            d = abs(vx * (ay - py) - vy * (ax - px)) / L if L else math.hypot(px - ax, py - ay)
            if d > best:
                best, bi = d, i
        if bi is not None and best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    out = [c for c, k in zip(ring, keep) if k]
    return out if len(out) >= 4 else ring


def build_lands(p):
    """City-owned parcels. 'Open space' is any non-park parcel named as one (Rec and Park's own open
    spaces stay under parks)."""
    feats = []
    for f in json.loads(p.read_text())['features']:
        pr, g = f['properties'], f['geometry']
        if not g or g['type'] not in ('Polygon', 'MultiPolygon'):
            continue
        cat = LAND_CATS.get((pr.get('category') or '').strip(), 'other')
        name = re.sub(r'\s+', ' ', (pr.get('land_name') or '').strip())
        if cat != 'park' and 'OPEN SPACE' in name.upper():
            cat = 'openspace'
        polys = [g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']
        out = []
        for poly in polys:
            rings = [simplify(dedupe_line(rnd(r))) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                out.append(rings)
        if not out:
            continue
        geom_out = {'type': 'Polygon', 'coordinates': out[0]} if len(out) == 1 else {'type': 'MultiPolygon', 'coordinates': out}
        feats.append(feat(geom_out, {'name': name, 'cat': cat, 'dept': (pr.get('department_name') or '').strip(),
                                     'addr': (pr.get('address') or '').strip(), 'id': pr.get('land_id')}))
    write('lands', feats, p, as_of(p))


def build_health(p):
    feats = []
    for r in read_csv(p):
        m = re.search(r'POINT \(([-\d.]+) ([-\d.]+)\)', r.get('point') or '')
        if not m:
            continue
        ftype = (r.get('facility_type') or '').strip()
        feats.append(feat({'type': 'Point', 'coordinates': rnd([float(m[1]), float(m[2])])},
                          {'name': tidy_name(r.get('facility_name') or ''), 'type': ftype,
                           'kind': 'hospital' if 'hospital' in ftype.lower() else 'clinic',
                           'services': (r.get('services') or '').strip()}))
    write('health', feats, p)


# NOAA's ATTRIBUTE codes in plain words
SHORE_KIND = {'Natural.Mean High Water': 'Mean high water', 'Natural.Apparent.Marsh Or Swamp': 'Marsh or swamp (edge)',
              'Man-made': 'Man-made', 'Man-made.Wharf Or Quay': 'Wharf or quay', 'Undetermined Alongshore Feature': 'Alongshore feature',
              'Shoreline/Alongshore Feature Boundary': 'Shoreline / alongshore boundary', 'Undetermined.Approximate': 'Approximate'}
# each survey file's register number → the survey's name on the map
SHORE_SURVEY = {'CA37A02': '1850–52', 'CA37B07': '1853', 'CA37B08': '1857'}


JOIN_MAX_M, JOIN_TOUCH_M = 150, 1


def line_ends(g):
    c = g['coordinates'] if g['type'] == 'LineString' else [p for l in g['coordinates'] for p in l]
    return c[0], c[-1]


def _m(a, b):
    return math.hypot((a[0] - b[0]) * 88000, (a[1] - b[1]) * 111000)   # meters, near 37.8° N


def min_m(pt, pts):
    return min((_m(pt, q) for q in pts), default=1e9)


def line_m(g):
    ls = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
    return sum(_m(a, b) for c in ls for a, b in zip(c, c[1:]))


def build_shoreline(folder):
    """data/uploads/shoreline/*.geojson (one per survey) → one layer, with empty and system fields left out.
    NOAA's CARTOGRAPHIC LIMIT lines ("User Added Line") are of two sorts: short pieces that join two shoreline
    lines where the digitized survey has a break (kept, as kind "Joining line"), and the edges of the map
    sheet (left out): any that's long (over JOIN_MAX_M) or doesn't meet a shoreline line at both ends."""
    feats, files = [], sorted(folder.glob('*.geojson'))
    for p in files:
        reg = next((k for k in SHORE_SURVEY if k in p.name), None)
        if not reg:
            print(f'  shoreline: {p.name} has no known survey number in its name, skipped', flush=True)
            continue
        src = json.loads(p.read_text())['features']
        is_cl = lambda f: ((f.get('properties') or {}).get('CLASS') or '').upper() == 'CARTOGRAPHIC LIMIT'
        ends = [pt for f in src if not is_cl(f) and f.get('geometry') for pt in line_ends(f['geometry'])]
        joins = edges = 0
        for f in src:
            pr, g = f.get('properties') or {}, geom(f.get('geometry'))
            if not g:
                continue
            if is_cl(f):
                a, b = line_ends(f['geometry'])
                if line_m(f['geometry']) > JOIN_MAX_M or min_m(a, ends) > JOIN_TOUCH_M or min_m(b, ends) > JOIN_TOUCH_M:
                    edges += 1; continue
                joins += 1
                feats.append(feat(g, {'id': pr.get('FEATURE_ID'), 'survey': SHORE_SURVEY[reg], 'register': reg,
                                      'kind': 'Joining line', 'class': 'Joining line', 'note': 'Joins two shoreline lines where the digitized survey has a break (NOAA: User Added Line)'}))
                continue
            note = (pr.get('INFORM') or '').replace('\x00', '').strip()
            att = pr.get('ATTRIBUTE') or ''
            feats.append(feat(g, {'id': pr.get('FEATURE_ID'), 'survey': SHORE_SURVEY[reg], 'register': reg,
                                  'year': int(str(pr.get('SRC_DATE'))[:4]) if str(pr.get('SRC_DATE') or '')[:4].isdigit() else None,
                                  'sheet': pr.get('SOURCE_ID'), 'kind': SHORE_KIND.get(att, att), 'class': (pr.get('CLASS') or '').capitalize(),
                                  'note': note or None}))
        print(f'  shoreline {SHORE_SURVEY[reg]}: {joins} joining lines kept, {edges} sheet edges left out', flush=True)
    if files:
        write('shoreline', feats, files[-1], None)
        write('shoreline_water', shoreline_water(feats), files[-1], None)


# Water areas from the shoreline surveys. A survey of the whole shore (1850–52): its shoreline pieces (mean high
# water, joining lines, seawalls; not wharves, marsh edges or rocks) are chained end to end into one line along SF's shore,
# with gaps up to WATER_BRIDGE_M bridged straight across. Its two ends are then closed along WATER_FRAME,
# a ring out in open water (west of Yerba Buena Island, so the island isn't painted as water), on the
# side away from WATER_LAND (a point that's always been land). Only surveys of the whole shore (WATER_END_M). So the polygon is the water between the
# historic shore and the frame: drawn under the basemap's roads, land that was water then (fill) shows as
# water, and over today's water it's the same color. Only the shore north of the county line, in SF.
# A survey of part of the shore (1853, 1857: the northeast waterfront) uses every line it has instead
# (_partial_water): see there.
WATER_KINDS = {'Mean high water', 'Joining line', 'Man-made', 'Approximate', 'Shoreline / alongshore boundary'}
WATER_BRIDGE_M = 1200
WATER_FRAME = [(-122.54, 37.7065), (-122.35, 37.7065), (-122.35, 37.79), (-122.376, 37.79), (-122.376, 37.817), (-122.54, 37.817)]
WATER_LAND = (-122.44, 37.76)
WATER_END_M = 500


def _in_ring(pt, ring):
    x, y, inside = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _on_frame(pt):
    """the nearest point on WATER_FRAME to pt: (segment index, distance along it 0–1, the point)"""
    best = None
    for i, a in enumerate(WATER_FRAME):
        b = WATER_FRAME[(i + 1) % len(WATER_FRAME)]
        dx, dy = (b[0] - a[0]) * 0.79, b[1] - a[1]
        t = max(0, min(1, (((pt[0] - a[0]) * 0.79) * dx + (pt[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        d = _m(pt, q)
        if best is None or d < best[0]:
            best = (d, i, t, q)
    return best[1:]


def _frame_walk(fa, fb, forward):
    """the frame's corners passed going from point fa to point fb (each from _on_frame), one way round"""
    n, (ia, ta, qa), (ib, tb, qb) = len(WATER_FRAME), fa, fb
    out, i = [qa], ia
    if forward:
        if ia == ib and tb >= ta:
            return out + [qb]
        while True:
            i = (i + 1) % n; out.append(WATER_FRAME[i])
            if i == ib:
                return out + [qb]
    if ia == ib and tb <= ta:
        return out + [qb]
    out.append(WATER_FRAME[i])
    while i != (ib + 1) % n:
        i = (i - 1) % n; out.append(WATER_FRAME[i])
    return out + [qb]


PART_BRIDGE_M = 150   # 1853 needs 101 m, where its sheet cuts off the south side of Mission Creek
PART_SPLICE_M = 8     # a pier line whose two ends are this close to the shore becomes part of it
# the box for a survey of part of the shore: east from its south end, round the frame's northeast corner
# (west of Yerba Buena Island), north to its west end
PART_NE = [(-122.35, 37.79), (-122.376, 37.79), (-122.376, 37.817)]


def _chain(segs, bridge):
    """join the two nearest loose ends again and again while they're within bridge m; longest first,
    with the gaps over 1 m that were bridged"""
    chains, gaps = [list(c) for c in segs if len(c) > 1], []
    while len(chains) > 1:
        best = None
        for i, a in enumerate(chains):
            for j in range(i + 1, len(chains)):
                b = chains[j]
                for ra in (0, 1):
                    for rb in (0, 1):
                        d = _m(a[-1] if not ra else a[0], b[0] if not rb else b[-1])
                        if best is None or d < best[0]:
                            best = (d, i, j, ra, rb)
        d, i, j, ra, rb = best
        if d > bridge:
            break
        a = chains[i][::-1] if ra else chains[i]
        b = chains[j][::-1] if rb else chains[j]
        if d > 1:
            gaps.append(round(d))
        chains[i] = a + (b[1:] if d < 1 else b)
        chains.pop(j)
    return sorted(chains, key=_len_m, reverse=True), gaps


def _len_m(c):
    return sum(_m(p, q) for p, q in zip(c, c[1:]))


def _crossings(ring):
    """how many times the ring crosses itself (segments in a grid, so it's quick)"""
    segs = list(zip(ring, ring[1:] + ring[:1]))
    side = lambda p, q, r: (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    grid = {}
    for i, (a, b) in enumerate(segs):
        for gx in range(int(min(a[0], b[0]) * 500), int(max(a[0], b[0]) * 500) + 1):
            for gy in range(int(min(a[1], b[1]) * 500), int(max(a[1], b[1]) * 500) + 1):
                grid.setdefault((gx, gy), []).append(i)
    seen, n = set(), 0
    for cell in grid.values():
        for x in range(len(cell)):
            for y in range(x + 1, len(cell)):
                i, j = cell[x], cell[y]
                if abs(i - j) < 2 or (i == 0 and j == len(segs) - 1) or (i, j) in seen:
                    continue
                seen.add((i, j))
                (a, b), (c, e) = segs[i], segs[j]
                if side(a, b, c) * side(a, b, e) < 0 and side(c, e, a) * side(c, e, b) < 0:
                    n += 1
    return n


def _partial_water(survey, feats):
    """Water for a survey of part of the shore, from every line it has (not the sheet edges, already left
    out, or the few pieces past the frame's north edge). The lines, apart from alongshore features, are
    chained into one shore (gaps up to PART_BRIDGE_M bridged); alongshore features and leftover pieces whose
    two ends touch the shore (piers) are spliced into it, so piers show as land; the shore is closed with a
    box to the north and east (PART_NE); closed loops inside the water become holes (islands, piers drawn as
    rings), and loops on land become water of their own (ponds). Lines that touch nothing stay lines."""
    lines, loops = [], []
    for f in feats:
        pr, g = f['properties'], f['geometry']
        if pr['survey'] != survey:
            continue
        for c in ([g['coordinates']] if g['type'] == 'LineString' else g['coordinates']):
            c = [tuple(p) for p in c]
            if any(p[1] >= WATER_FRAME[-1][1] for p in c) or len(c) < 2:
                continue
            if len(c) > 3 and _m(c[0], c[-1]) < 1:
                loops.append(c)
            else:
                lines.append((c, pr['kind']))
    chains, gaps = _chain([c for c, k in lines if k != 'Alongshore feature'], PART_BRIDGE_M)
    if not chains:
        return None
    shore = chains[0]
    if (shore[0][1] - shore[0][0]) < (shore[-1][1] - shore[-1][0]):
        shore = shore[::-1]   # north-west end first
    close = lambda sh: sh + [(PART_NE[0][0], sh[-1][1])] + PART_NE + [(sh[0][0], PART_NE[-1][1])]
    if _crossings(close(shore)):
        print(f'  shoreline water {survey}: the shore crosses itself once closed, no water area', flush=True)
        return None
    near = lambda p: min(range(len(shore)), key=lambda i: _m(shore[i], p))
    spliced = left = 0
    for pc in sorted(chains[1:] + [c for c, k in lines if k == 'Alongshore feature'], key=len, reverse=True):
        a, b = near(pc[0]), near(pc[-1])
        if _m(shore[a], pc[0]) > PART_SPLICE_M or _m(shore[b], pc[-1]) > PART_SPLICE_M:
            left += 1; continue
        if b < a:
            a, b, pc = b, a, pc[::-1]
        if _len_m(shore[a:b + 1]) > 3 * _len_m(pc) + 50:   # it runs along the shore, not out from it
            left += 1; continue
        cand = shore[:a] + pc + shore[b + 1:]
        if _crossings(close(cand)):
            left += 1; continue
        shore = cand; spliced += 1
    ring = close(shore)
    holes, ponds = [], []
    for lp in loops:
        mid = (sum(p[0] for p in lp) / len(lp), sum(p[1] for p in lp) / len(lp))
        (holes if _in_ring(mid, ring) else ponds).append(lp)
    rnd = lambda r: [[round(x, 6), round(y, 6)] for x, y in r] + [[round(r[0][0], 6), round(r[0][1], 6)]]
    polys = [[rnd(ring)] + [rnd(h) for h in holes]] + [[rnd(p)] for p in ponds]
    g = {'type': 'Polygon', 'coordinates': polys[0]} if len(polys) == 1 else {'type': 'MultiPolygon', 'coordinates': polys}
    km = round(_len_m(shore) / 1000, 1)
    print(f'  shoreline water {survey}: one shore of {km} km ({len(gaps)} gaps bridged, the longest {max(gaps, default=0)} m), '
          f'{spliced} pier lines spliced in, {len(holes)} islands, {len(ponds)} ponds, {left} lines left as lines; closed with a box to the north and east', flush=True)
    return feat(g, {'survey': survey, 'shore_km': km,
                    'note': 'Water between the surveyed shore and a box out in the bay to the north and east; the survey covers only part of the shore'})


def shoreline_water(feats):
    out = []
    for survey in sorted({f['properties']['survey'] for f in feats}):
        segs = []
        for f in feats:
            pr, g = f['properties'], f['geometry']
            if pr['survey'] != survey or pr['kind'] not in WATER_KINDS:
                continue
            for c in ([g['coordinates']] if g['type'] == 'LineString' else g['coordinates']):
                if all(WATER_FRAME[0][1] - 0.002 < p[1] < WATER_FRAME[-1][1] for p in c):
                    segs.append([tuple(p) for p in c])
        # chain: join the two nearest loose ends again and again, while they're within WATER_BRIDGE_M
        chains = [s for s in segs if len(s) > 1]
        while len(chains) > 1:
            best = None
            for i, a in enumerate(chains):
                for j in range(i + 1, len(chains)):
                    b = chains[j]
                    for ra in (0, 1):
                        for rb in (0, 1):
                            d = _m(a[-1] if not ra else a[0], b[0] if not rb else b[-1])
                            if best is None or d < best[0]:
                                best = (d, i, j, ra, rb)
            d, i, j, ra, rb = best
            if d > WATER_BRIDGE_M:
                break
            a = chains[i][::-1] if ra else chains[i]
            b = chains[j][::-1] if rb else chains[j]
            chains[i] = a + (b[1:] if d < 1 else b)
            chains.pop(j)
        shore = max(chains, key=lambda c: sum(_m(p, q) for p, q in zip(c, c[1:])), default=None)
        if not shore or len(shore) < 3:
            continue
        fa, fb = _on_frame(shore[-1]), _on_frame(shore[0])
        # only a survey of the whole shore: both ends reach the frame (the county line). A survey of part of
        # it (1853 and 1857: the northeast waterfront) can't be closed without inventing shore, so it gets none.
        gap = max(_m(shore[-1], fa[2]), _m(shore[0], fb[2]))
        if gap > WATER_END_M:
            w = _partial_water(survey, feats)
            if w:
                out.append(w)
            continue
        ring = None
        for fw in (True, False):
            r = shore + _frame_walk(fa, fb, fw)[:-1]
            if not _in_ring(WATER_LAND, r):
                ring = r
                break
        if not ring:
            print(f'  shoreline water {survey}: couldn\'t close the shore away from land, skipped', flush=True)
            continue
        ring = [[round(x, 6), round(y, 6)] for x, y in ring]
        ring.append(ring[0])
        out.append(feat({'type': 'Polygon', 'coordinates': [ring]}, {'survey': survey, 'shore_km': round(sum(_m(p, q) for p, q in zip(shore, shore[1:])) / 1000, 1),
                    'note': 'Water between the surveyed shore and a line out in the bay and ocean; shore gaps up to 1.2 km bridged straight across'}))
        print(f'  shoreline water {survey}: {len(segs)} shore pieces → one shore of {out[-1]["properties"]["shore_km"]} km, closed offshore', flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--download', action='store_true', help='download fresh copies of every dataset (except schools) first')
    ap.add_argument('--index', action='store_true', help='only rewrite data/layers/index.json from the files already there')
    ap.add_argument('only', nargs='*', help='build only these layers (muni, bike, shoreline…); all when none')
    a = ap.parse_args()
    if a.index:
        write_index()
        return
    SRC.mkdir(exist_ok=True)
    jobs = {'muni': build_muni, 'bike': build_bike, 'schools': build_schools,
            'stations': build_stations, 'health': build_health, 'slow': build_slow, 'lands': build_lands,
            'shoreline': build_shoreline}
    for key, fn in jobs.items():
        if a.only and key not in a.only:
            continue
        # a layer built from a folder of files (shoreline) gets the folder
        p = (SRC / SOURCES[key]['folder']) if SOURCES[key].get('folder') and (SRC / SOURCES[key]['folder']).is_dir() else find(key)
        if (not p or (a.download and key != 'schools')) and SOURCES[key]['id']:
            try:
                p = download(key)
            except Exception as e:
                print(f'  couldn\'t download {SOURCES[key]["title"]} ({e})', flush=True)
        if p:
            fn(p)
        else:
            src = SOURCES[key]
            print(f'skipped {key}: no "{src["title"]}" download in layers/'
                  + (f' (get it from {src["url"]})' if src['url'] else ''), flush=True)
    write_index()


if __name__ == '__main__':
    main()
