#!/usr/bin/env python3
# sf-blocks 2026.11.11.7
"""Facts per street block (CNN), so apps can fill a block's card without reading tiles and boundaries.

    python3 scripts/build_facts.py            writes data/facts/streets.json and data/facts/lots.json

streets.json is what a card shows; lots.json (each block's lot ids and census blocks) is only for growing a
selection to the lots around it and for exports, so apps load it when they need it.

Everything comes from files already in this repo, worked out the way Block Party's cards work them out:
  lots         parcels (data/Land_Use_with_Active_Parcel_Information.pmtiles, zoom 15) with a corner within 14 m
               of the middle 70% of the block, or 25 m when the lot's address is on the same street. Gives the
               lots (by assessor block), homes (residential units), land use and zoning, each counted by lot.
  trees        street trees (data/tiles/street_trees.pmtiles) with the block's CNN, within 40 m, counted by name.
  businesses   business locations (data/tiles/businesses.pmtiles) within 60 m whose address is on the block's
               street and inside its address ranges: how many show (storefronts), at how many addresses, and
               how many are hidden as not storefronts, by kind.
  census       2020 census blocks (data/boundaries/census_blocks.geojson) 12 m to each side at 25/50/75% along:
               people and homes, each block's share being the street's length over the block's perimeter.
  areas        elected and special districts (data/boundaries/) at 25/50/75% along, on the centerline and 12 m
               to each side, most-covered first. Each is an index into that set's list in "areas".

Intersections aren't here: their cards add up half of each street, which apps still do from the tiles.
Standard library only. Rebuilt by the "Add or refresh data" Action whenever a source above changes.
"""
import gzip, json, math, re, sys, zlib
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'facts' / 'streets.json'
KX, KY = 111320 * math.cos(37.76 * math.pi / 180), 110540      # metres per degree, as in the apps
NEAR_M, ADDR_M, TREE_M, BIZ_M, SIDE_M = 14, 25, 40, 60, 12
AREA_SETS = [  # key in the apps, boundary set, field kept for the apps' chips
    ('sup', 'supervisor_districts', ['sup_dist', 'sup_name']),
    ('asm', 'assembly_districts', ['assemb22']),
    ('sen', 'state_senate_districts', ['sen22']),
    ('house', 'us_house_districts', ['cong22']),
    ('bart', 'bart_districts', ['bart22']),
    ('cbd', 'community_benefit_district', ['community_benefit_district']),
    ('cult', 'cultural_districts', ['district_name']),
    ('hist', 'historic_districts', ['name_1']),
]
SUFFIX = r'^(ST|AVE?|BLVD|WAY|DR|CT|PL|TER|LN|RD|ALY|CIR|HWY|PARK|PLZ|EXPY|WALK|STWY|TUNL)$'


def log(*a): print(*a, file=sys.stderr, flush=True)


def street_key(s):
    """The apps' streetKey: upper case, no leading zeros, no street type."""
    s = re.sub(r'\b0+(\d)', r'\1', (s or '').upper())
    return ' '.join(w for w in s.split(' ') if w and not re.match(SUFFIX, w))


# ---------- PMTiles (v3) and vector tiles, enough to read every tile at one zoom ----------
def varint(b, i):
    n = s = 0
    while True:
        c = b[i]; i += 1; n |= (c & 0x7F) << s; s += 7
        if c < 0x80: return n, i


def unzip(data, how):
    if how == 2: return gzip.decompress(data)
    if how == 1 or how == 0: return data
    raise ValueError(f'compression {how} not supported')


def tile_zxy(tid):
    """PMTiles tile id → (z, x, y) along the Hilbert curve."""
    acc, z = 0, 0
    while True:
        n = 4 ** z
        if acc + n > tid: break
        acc += n; z += 1
    pos, n = tid - acc, 1 << z
    x = y = 0; t = pos; s = 1
    while s < n:
        rx = 1 & (t // 2); ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1: x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx; y += s * ry; t //= 4; s *= 2
    return z, x, y


def pmtiles(path, zoom):
    """Every tile at `zoom`: yields (x, y, decompressed bytes)."""
    b = path.read_bytes()
    assert b[:7] == b'PMTiles' and b[7] == 3, f'{path}: not PMTiles v3'
    u64 = lambda o: int.from_bytes(b[o:o + 8], 'little')
    root_off, root_len, leaf_off, data_off = u64(8), u64(16), u64(40), u64(56)
    comp, tcomp = b[97], b[98]

    def entries(off, length):
        d = unzip(b[off:off + length], comp); i = 0
        n, i = varint(d, i); ids, last = [], 0
        for _ in range(n): v, i = varint(d, i); last += v; ids.append(last)
        runs = []; lens = []; offs = []
        for _ in range(n): v, i = varint(d, i); runs.append(v)
        for _ in range(n): v, i = varint(d, i); lens.append(v)
        for k in range(n):
            v, i = varint(d, i)
            offs.append(offs[k - 1] + lens[k - 1] if v == 0 and k > 0 else v - 1)
        return zip(ids, runs, lens, offs)

    def walk(off, length):
        for tid, run, ln, o in entries(off, length):
            if run == 0: yield from walk(leaf_off + o, ln)
            else:
                for r in range(run): yield tid + r, o, ln
    for tid, o, ln in walk(root_off, root_len):
        z, x, y = tile_zxy(tid)
        if z == zoom: yield x, y, unzip(b[data_off + o:data_off + o + ln], tcomp)


def pb(buf):
    """Protocol buffer fields: yields (field, wire type, value)."""
    i, n = 0, len(buf)
    while i < n:
        key, i = varint(buf, i); f, w = key >> 3, key & 7
        if w == 0: v, i = varint(buf, i)
        elif w == 2: ln, i = varint(buf, i); v = buf[i:i + ln]; i += ln
        elif w == 1: v = buf[i:i + 8]; i += 8
        elif w == 5: v = buf[i:i + 4]; i += 4
        else: raise ValueError('wire type')
        yield f, w, v


def packed(buf):
    out, i = [], 0
    while i < len(buf): v, i = varint(buf, i); out.append(v)
    return out


def mvt(data, layer_name):
    """Features of one layer: (props, rings of tile coordinates, extent)."""
    import struct
    for f, _, v in pb(data):
        if f != 3: continue
        name, keys, vals, feats, extent = '', [], [], [], 4096
        for g, _, w in pb(v):
            if g == 1: name = w.decode()
            elif g == 2: feats.append(w)
            elif g == 3: keys.append(w.decode())
            elif g == 4:
                val = None
                for h, wt, x in pb(w):
                    if h == 1: val = x.decode()
                    elif h == 2: val = struct.unpack('<f', x)[0]
                    elif h == 3: val = struct.unpack('<d', x)[0]
                    elif h in (4, 5): val = x
                    elif h == 6: val = (x >> 1) ^ -(x & 1)
                    elif h == 7: val = bool(x)
                vals.append(val)
            elif g == 5: extent = w
        if name != layer_name: continue
        for ft in feats:
            tags, geom = [], []
            for g, _, w in pb(ft):
                if g == 2: tags = packed(w)
                elif g == 4: geom = packed(w)
            props = {keys[tags[k]]: vals[tags[k + 1]] for k in range(0, len(tags) - 1, 2)}
            rings, ring, x, y, i = [], [], 0, 0, 0
            while i < len(geom):
                cmd, cnt = geom[i] & 7, geom[i] >> 3; i += 1
                if cmd in (1, 2):
                    for _ in range(cnt):
                        dx, dy = geom[i], geom[i + 1]; i += 2
                        x += (dx >> 1) ^ -(dx & 1); y += (dy >> 1) ^ -(dy & 1)
                        if cmd == 1 and ring: rings.append(ring); ring = []
                        ring.append((x, y))
                elif cmd == 7 and ring: rings.append(ring); ring = []
            if ring: rings.append(ring)
            yield props, rings, extent


def tile_lonlat(z, x, y, px, py, extent):
    n = 2 ** z
    lon = (x + px / extent) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
    return lon, lat


# ---------- geometry, in metres (lon * KX, lat * KY) like the apps ----------
def seg_dist(px, py, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]; L2 = vx * vx + vy * vy or 1
    u = max(0, min(1, ((px - a[0]) * vx + (py - a[1]) * vy) / L2))
    return math.hypot(a[0] + u * vx - px, a[1] + u * vy - py)


def line_dist(px, py, pts):
    return min(seg_dist(px, py, pts[k - 1], pts[k]) for k in range(1, len(pts))) if len(pts) > 1 else math.hypot(px - pts[0][0], py - pts[0][1])


def middle(pts, f0, f1):
    """The part of a line (in metres) from f0 to f1 of its length (Parcels' middle())."""
    cum = [0]
    for k in range(1, len(pts)): cum.append(cum[-1] + math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]))
    L = cum[-1]

    def at(d):
        k = 1
        while k < len(pts) - 1 and cum[k] < d: k += 1
        u = (d - cum[k - 1]) / ((cum[k] - cum[k - 1]) or 1)
        return (pts[k - 1][0] + u * (pts[k][0] - pts[k - 1][0]), pts[k - 1][1] + u * (pts[k][1] - pts[k - 1][1]))
    return [at(L * f0)] + [pts[k] for k in range(1, len(pts) - 1) if L * f0 < cum[k] < L * f1] + [at(L * f1)]


def along(coords, f):
    """A point f of the way along, measured in degrees (the apps' along())."""
    seg = [math.hypot(coords[k][0] - coords[k - 1][0], coords[k][1] - coords[k - 1][1]) for k in range(1, len(coords))]
    d, k = sum(seg) * f, 0
    while k < len(seg) - 1 and d > seg[k]: d -= seg[k]; k += 1
    u = d / seg[k] if seg and seg[k] else 0
    a = coords[k]; b = coords[k + 1] if k + 1 < len(coords) else a
    return a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])


def in_ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi: inside = not inside
        j = i
    return inside


def in_poly(x, y, parts):
    return any(in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]) for p in parts)


class Grid:
    """Things by the cells their box touches, for finding what's near a point or box quickly (metres)."""
    def __init__(self, cell=100): self.cell, self.cells = cell, defaultdict(list)

    def add(self, item, box):
        c = self.cell
        for i in range(int(box[0] // c), int(box[2] // c) + 1):
            for j in range(int(box[1] // c), int(box[3] // c) + 1): self.cells[i, j].append(item)

    def near(self, box):
        c, seen = self.cell, set()
        for i in range(int(box[0] // c), int(box[2] // c) + 1):
            for j in range(int(box[1] // c), int(box[3] // c) + 1):
                for it in self.cells.get((i, j), ()):
                    if id(it) not in seen: seen.add(id(it)); yield it


def bbox(pts, pad=0):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# ---------- inputs ----------
def load_streets():
    raw = json.loads((ROOT / 'data' / 'streets.json').read_text())
    S, F = raw['strings'], {f: i for i, f in enumerate(raw['seg_fields'])}
    segs = []
    for r in raw['segs']:
        g, pts, x, y = r[F['geom']], [], 0, 0
        for i in range(0, len(g), 2):
            x, y = (g[0], g[1]) if i == 0 else (x + g[i], y + g[i + 1])
            pts.append((x / 1e5, y / 1e5))
        if len(pts) < 2: continue
        m = [(p[0] * KX, p[1] * KY) for p in pts]
        rng = [(min(a, b), max(a, b)) for a, b in ((r[F['lf_fadd']], r[F['lf_toadd']]), (r[F['rt_fadd']], r[F['rt_toadd']])) if a or b]
        segs.append({'cnn': r[F['cnn']], 'street': S[r[F['streetname']]], 'coords': pts, 'm': m, 'mid': middle(m, 0.15, 0.85),
                     'key': street_key(S[r[F['streetname']]]), 'ranges': rng})
    return segs, raw.get('data_as_of')


def tile_index():
    return {l['id']: l for l in json.loads((ROOT / 'data' / 'tiles' / 'index.json').read_text())['layers']}


def points(path, layer, zoom, ident):
    """Point features of a tiled layer, de-duplicated (tiles overlap at their edges)."""
    seen, out = set(), []
    for x, y, data in pmtiles(path, zoom):
        for props, rings, ext in mvt(data, layer):
            if not rings: continue
            k = ident(props)
            if k in seen: continue
            seen.add(k)
            lon, lat = tile_lonlat(zoom, x, y, *rings[0][0], ext)
            out.append((props, lon * KX, lat * KY))
    return out


def polygons(set_id):
    gj = json.loads((ROOT / 'data' / 'boundaries' / f'{set_id}.geojson').read_text())
    out = []
    for f in gj['features']:
        g = f.get('geometry') or {}
        parts = [g['coordinates']] if g.get('type') == 'Polygon' else g.get('coordinates') or []
        if not parts: continue
        xs = [p[0] for part in parts for p in part[0]]; ys = [p[1] for part in parts for p in part[0]]
        out.append({'props': f['properties'], 'parts': parts, 'box': (min(xs), min(ys), max(xs), max(ys))})
    return out


def lot_parts(lot):
    """'3596012' → ('3596', '012'); '4207014B' → ('4207', '014B'); '0001A001' → ('0001A', '001')."""
    m = re.match(r'^(\d{4}[A-Z]?)(\d{3}[A-Z]?)$', lot)
    return (m.group(1), m.group(2)) if m else (lot, '')


def main():
    segs, streets_as_of = load_streets()
    log(f'{len(segs):,} street blocks')
    grid = Grid(100)
    for s in segs: grid.add(s, bbox(s['m']))
    tiles = tile_index()

    # ---- parcels: each lot's corners (every tile piece), then the blocks they're near ----
    log('parcels')
    lots = {}
    for x, y, data in pmtiles(ROOT / 'data' / 'Land_Use_with_Active_Parcel_Information.pmtiles', 15):
        for p, rings, ext in mvt(data, 'parcels'):
            lot = p.get('mapblklot')
            if not lot: continue
            pts = [tile_lonlat(15, x, y, px, py, ext) for r in rings for px, py in r]
            pts = [(lo * KX, la * KY) for lo, la in pts]
            L = lots.get(lot)
            if not L:
                lots[lot] = L = {'use': p.get('landuse') or '', 'zone': p.get('parcelsactiveandretired_zoning_district') or '',
                                 'code': p.get('parcelsactiveandretired_zoning_code') or '', 'units': 0, 'street': street_key(p.get('street')), 'pts': []}
            L['units'] = max(L['units'], int(float(p.get('resunits') or 0)))
            L['pts'] += pts
    log(f'  {len(lots):,} lots')
    on_seg = defaultdict(list)
    for lot, L in lots.items():
        box = bbox(L['pts'], ADDR_M)
        for s in grid.near(box):
            lim = ADDR_M if L['street'] == s['key'] else NEAR_M
            sb = bbox(s['mid'], lim)
            if box[2] - ADDR_M < sb[0] or box[0] + ADDR_M > sb[2] or box[3] - ADDR_M < sb[1] or box[1] + ADDR_M > sb[3]: continue
            mid = s['mid']
            if any(seg_dist(px, py, mid[k - 1], mid[k]) <= lim for px, py in L['pts'] for k in range(1, len(mid))):
                on_seg[s['cnn']].append(lot)
        L['pts'] = None

    # ---- trees: the block's CNN, within 40 m ----
    log('trees')
    tm = tiles.get('street_trees')
    trees = points(ROOT / 'data' / 'tiles' / tm['file'], tm['layer'], tm.get('detailzoom', 15), lambda p: p.get('treeid') or json.dumps(p, sort_keys=True)) if tm else []
    by_cnn = {s['cnn']: s for s in segs}
    tree_at = defaultdict(list)
    for p, x, y in trees:
        try: c = int(float(p.get('cnn') or 0))
        except ValueError: continue
        s = by_cnn.get(c)
        if s and line_dist(x, y, s['m']) <= TREE_M: tree_at[c].append(p.get('common') or p.get('species') or p.get('genus') or '?')
    log(f'  {len(trees):,} trees, {sum(map(len, tree_at.values())):,} on blocks')

    # ---- businesses: on the block's street, inside its address ranges, within 60 m ----
    log('businesses')
    bm = tiles.get('businesses')
    biz = points(ROOT / 'data' / 'tiles' / bm['file'], bm['layer'], bm.get('detailzoom', 15), lambda p: json.dumps(p, sort_keys=True)) if bm else []
    biz_at = defaultdict(lambda: {'shown': 0, 'addrs': set(), 'hidden': defaultdict(int)})
    for p, x, y in biz:
        items = p.get('items')
        if isinstance(items, str):
            try: items = json.loads(items)
            except ValueError: items = []
        items = items or []
        for it in items:
            a = it.get('address') or p.get('address') or ''
            m = re.match(r'^(\d+)[A-Za-z]?(?:-\d+)?\s+(.+)$', a)
            if not m: continue
            key, n = street_key(re.sub(r'\s*(#|Ste|Unit|Fl|Apt)\b.*$', '', m.group(2), flags=re.I)), int(m.group(1))
            for s in grid.near((x - BIZ_M, y - BIZ_M, x + BIZ_M, y + BIZ_M)):
                if s['key'] != key or (s['ranges'] and not any(lo <= n <= hi for lo, hi in s['ranges'])): continue
                if line_dist(x, y, s['m']) > BIZ_M: continue
                b = biz_at[s['cnn']]
                if it.get('kind'): b['hidden'][it['kind']] += 1
                else: b['shown'] += 1; b['addrs'].add(a)
    log(f'  {len(biz):,} locations, on {len(biz_at):,} blocks')

    # ---- census blocks: 12 m to each side at 25/50/75% along ----
    log('census')
    cb = polygons('census_blocks')
    cgrid = Grid(0.002)
    for i, p in enumerate(cb): p['i'] = i; cgrid.add(p, p['box'])
    perim = lambda p: sum(sum(math.hypot((r[k][0] - r[k - 1][0]) * KX, (r[k][1] - r[k - 1][1]) * KY) for k in range(1, len(r))) for r in (part[0] for part in p['parts']))

    def offsets(coords, fs, side_m, center):
        out = []
        for f in fs:
            x, y = along(coords, f); x2, y2 = along(coords, min(1, f + 0.02))
            dx, dy = (x2 - x) * KX, (y2 - y) * KY; d = math.hypot(dx, dy) or 1; dx /= d; dy /= d
            if center: out.append((x, y))
            out += [(x - dy * side_m / KX, y + dx * side_m / KY), (x + dy * side_m / KX, y - dx * side_m / KY)]
        return out

    def hits(polys, g, pt):
        x, y = pt
        return [p for p in g.near((x, y, x, y)) if p['box'][0] <= x <= p['box'][2] and p['box'][1] <= y <= p['box'][3] and in_poly(x, y, p['parts'])]

    # ---- districts ----
    log('districts')
    area_sets = []
    for k, set_id, keep in AREA_SETS:
        try: polys = polygons(set_id)
        except FileNotFoundError: log(f'  no {set_id}, skipped'); continue
        g = Grid(0.01)
        for i, p in enumerate(polys): p['i'] = i; g.add(p, p['box'])
        area_sets.append((k, set_id, keep, polys, g))

    strings, sidx = [], {}

    def S(v):
        v = '' if v is None else str(v)
        if v not in sidx: sidx[v] = len(strings); strings.append(v)
        return sidx[v]

    def counted(values):
        c = defaultdict(int)
        for v in values: c[v] += 1
        return [x for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) for x in (S(k), n)]

    rows = []
    for s in segs:
        row = [s['cnn']]
        mine = sorted(set(on_seg.get(s['cnn'], ())))
        by_block = defaultdict(list)
        for lot in mine: b, l = lot_parts(lot); by_block[b].append(l)
        zones = defaultdict(lambda: [None, 0])
        for lot in mine:
            L = lots[lot]
            if L['zone']: zones[L['zone']][0] = L['code']; zones[L['zone']][1] += 1
        row += [len(mine), sum(lots[l]['units'] for l in mine), counted(lots[l]['use'] for l in mine),
                [x for name, (code, n) in sorted(zones.items(), key=lambda kv: -kv[1][1]) for x in (S(code), S(name), n)],
                '|'.join(b + ' ' + ' '.join(ls) for b, ls in sorted(by_block.items()))]
        t = tree_at.get(s['cnn'], [])
        row += [len(t), counted(t)]
        b = biz_at.get(s['cnn'])
        row += [b['shown'], len(b['addrs']), counted(k for k, n in b['hidden'].items() for _ in range(n))] if b else [0, 0, []]
        seg_len = sum(math.hypot(s['m'][k][0] - s['m'][k - 1][0], s['m'][k][1] - s['m'][k - 1][1]) for k in range(1, len(s['m'])))
        found = {}
        for pt in offsets(s['coords'], (0.25, 0.5, 0.75), SIDE_M, False):
            for p in hits(cb, cgrid, pt): found[p['i']] = p
        people = homes = 0; parts = []
        for p in found.values():
            if 'perim' not in p: p['perim'] = perim(p)
            share = min(1, seg_len / (p['perim'] or float('inf')))
            people += (float(p['props'].get('pop20') or 0)) * share; homes += float(p['props'].get('housing20') or 0) * share
            parts.append(str(p['props'].get('geoid20') or ''))
        row += [round(people, 1), round(homes, 1), parts]
        pts = offsets(s['coords'], (0.25, 0.5, 0.75), SIDE_M, True)
        names = []
        for k, set_id, keep, polys, g in area_sets:
            n = defaultdict(int)
            for pt in pts:
                for p in hits(polys, g, pt): n[p['i']] += 1
            names.append('.'.join(str(i) for i, _ in sorted(n.items(), key=lambda kv: -kv[1])))
        row.append('|'.join(names))
        rows.append(row)

    fields = ['cnn', 'lots', 'homes', 'uses', 'zones', 'lot_ids', 'trees', 'tree_kinds', 'biz', 'biz_addrs', 'biz_hidden',
              'people', 'census_homes', 'census_blocks', 'areas']
    # the lot ids and census blocks go in their own file, in the same order
    li, ci = fields.index('lot_ids'), fields.index('census_blocks')
    lot_rows = [[r[0], r[li], r[ci]] for r in rows]
    rows = [[v for k, v in enumerate(r) if k not in (li, ci)] for r in rows]
    fields = [f for f in fields if f not in ('lot_ids', 'census_blocks')]
    sources = {
        'streets': {'file': 'data/streets.json', 'as_of': streets_as_of},
        'parcels': {'file': 'data/Land_Use_with_Active_Parcel_Information.pmtiles', 'year': '2023'},
        'trees': {'file': f"data/tiles/{tm['file']}", 'as_of': tm.get('retrieved')} if tm else None,
        'businesses': {'file': f"data/tiles/{bm['file']}", 'as_of': bm.get('retrieved')} if bm else None,
        'census': {'file': 'data/boundaries/census_blocks.geojson', 'year': '2020'},
    }
    out = {
        '_doc': 'Facts per street block, built by scripts/build_facts.py. One row per CNN in `rows`, columns as `fields`. '
                'Text is an index into `strings`. uses / tree_kinds / biz_hidden: [text, count, ...]. zones: [code, name, lots, ...]. '
                'areas: one entry per set in `area_sets`, '
                'joined by "|"; each is the indexes of that set\'s areas (in `area_sets[k].areas`) joined by ".", most-covered first.',
        'built': date.today().isoformat(), 'sf_blocks': (ROOT / 'VERSION').read_text().strip(), 'sources': sources,
        'rules': {'lots_m': NEAR_M, 'lots_same_street_m': ADDR_M, 'trees_m': TREE_M, 'businesses_m': BIZ_M, 'side_m': SIDE_M},
        'area_sets': [{'k': k, 'set': set_id, 'areas': [{f: p['props'].get(f) for f in keep} for p in polys]} for k, set_id, keep, polys, g in area_sets],
        'fields': fields, 'strings': strings, 'rows': rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
    OUT.write_text(text)
    lots_out = {'_doc': 'Each street block\'s lots and census blocks, built by scripts/build_facts.py with streets.json. '
                        'lot_ids: "<assessor block> <lot> <lot>|<block> ..." (lot id = block + lot). census_blocks: geoid20s.',
                'built': out['built'], 'sf_blocks': out['sf_blocks'], 'fields': ['cnn', 'lot_ids', 'census_blocks'], 'rows': lot_rows}
    lt = json.dumps(lots_out, separators=(',', ':'))
    (OUT.parent / 'lots.json').write_text(lt)
    log(f'wrote data/facts/lots.json: {len(lt) / 1e6:.2f} MB ({len(gzip.compress(lt.encode())) / 1e6:.2f} MB gzipped)')
    log(f'wrote {OUT.relative_to(ROOT)}: {len(rows):,} blocks, {len(text) / 1e6:.2f} MB ({len(gzip.compress(text.encode())) / 1e6:.2f} MB gzipped)')


if __name__ == '__main__':
    main()
