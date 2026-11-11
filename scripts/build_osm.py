#!/usr/bin/env python3
# sf-blocks 2026.11.11
"""OpenStreetMap ways in San Francisco, as pieces apps can pick: streets, alleys, paths, bike paths,
stairs, sidewalks and crosswalks, split where they meet, each with a lasting id and the CNN it runs
along (if any). Standard library only.

The "Add or refresh data" Action (Kind: OSM ways) downloads Geofabrik's Northern California extract,
clips it to San Francisco with osmium, keeps the highway=* ways, and runs:

    python3 scripts/build_osm.py sf-highways.osm --as-of 2026-11-10 --geojsonseq pieces.geojsonseq --report report.md

then tiles pieces.geojsonseq with tippecanoe into data/osm/ways.pmtiles.

Writes:
  data/osm/index.json     manifest: date of the OSM data, counts by kind, files, fields, attribution
  data/osm/gaps/<n>.json  the pieces that don't run along any city street (park and campus paths, bike paths,
                          stairs, sidewalks…), by id, split into 16 files by way id (n = way id % 16), so an app
                          can draw a picked piece from its id alone: {id: [kind, highway, name, tags, coords]}
                          with coords as whole numbers (lon/lat x 1e6, first point then differences)
  --geojsonseq FILE       every piece as one GeoJSON line, for tippecanoe (not committed)
  --report FILE           counts, CNN matches, sizes with and without sidewalks, and sample gap pieces

Ids: w<way>:n<first node>-n<last node>. A piece keeps its id across refreshes unless someone edits the nodes at
its ends. Data © OpenStreetMap contributors, under the Open Database License (ODbL); this derived layer is too.
"""
import argparse, bz2, gzip, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree.ElementTree import iterparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'osm'
KX, KY = 111320 * math.cos(math.radians(37.76)), 110540   # meters per degree around SF
SCALE = 1_000_000
MATCH_M, MATCH_DEG = 12, 30          # a piece runs along a city street when 2+ samples are this close and this parallel
ROADS = {'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link',
         'tertiary', 'tertiary_link', 'unclassified', 'residential', 'living_street', 'road', 'busway', 'service'}
KEEP_TAGS = ['name', 'ref', 'service', 'footway', 'cycleway', 'cycleway:left', 'cycleway:right', 'cycleway:both', 'bicycle', 'foot',
             'segregated', 'oneway', 'oneway:bicycle', 'surface', 'access', 'layer', 'bridge', 'tunnel', 'lit', 'incline', 'step_count']
SAMPLES = {   # places to list gap pieces from in the report: (name, west, south, east, north)
    'Golden Gate Park': (-122.5115, 37.7650, -122.4530, 37.7745),
    'SF State': (-122.4840, 37.7195, -122.4750, 37.7265),
    "O'Shaughnessy Blvd": (-122.4450, 37.7350, -122.4370, 37.7450),
    'The Presidio': (-122.4850, 37.7880, -122.4460, 37.8100),
}


def log(*a): print(*a, file=sys.stderr, flush=True)


def kind_of(t):
    hw = t.get('highway', '')
    if hw == 'footway' and t.get('footway') == 'sidewalk': return 'sidewalk'
    if t.get('footway') == 'crossing' or t.get('cycleway') == 'crossing' or t.get('path') == 'crossing': return 'crossing'
    if hw == 'cycleway' or (hw == 'path' and t.get('bicycle') in ('designated', 'yes')): return 'bike'
    if hw == 'steps': return 'steps'
    if hw in ('footway', 'pedestrian', 'path', 'track', 'bridleway', 'corridor'): return 'foot'
    if hw == 'service': return 'alley' if t.get('service') == 'alley' else 'service'
    if hw in ROADS: return 'road'
    return 'other'


def opener(p):
    p = str(p)
    return bz2.open(p, 'rb') if p.endswith('.bz2') else gzip.open(p, 'rb') if p.endswith('.gz') else open(p, 'rb')


def read_osm(path):
    """nodes {id: (lon, lat)} and ways [(id, [node ids], tags)] from an .osm XML file (osmium's output: nodes first)."""
    nodes, ways = {}, []
    cur = None
    for ev, el in iterparse(opener(path), events=('start', 'end')):
        tag = el.tag
        if ev == 'start':
            if tag == 'way': cur = (int(el.get('id')), [], {})
            continue
        if tag == 'node':
            nodes[int(el.get('id'))] = (float(el.get('lon')), float(el.get('lat'))); el.clear()
        elif tag == 'nd' and cur: cur[1].append(int(el.get('ref')))
        elif tag == 'tag' and cur: cur[2][el.get('k')] = el.get('v')
        elif tag == 'way':
            if cur and 'highway' in cur[2] and len(cur[1]) > 1: ways.append(cur)
            cur = None; el.clear()
        elif tag == 'relation': el.clear()
    return nodes, ways


def split(ways, nodes):
    """pieces split at every node two or more ways share (and where a way crosses itself)"""
    use = Counter()
    for _, nds, _ in ways:
        for i, n in enumerate(nds): use[n] += 1 if 0 < i < len(nds) - 1 else 2
    pieces = []
    for wid, nds, tags in ways:
        nds = [n for n in nds if n in nodes]
        start = 0
        for i in range(1, len(nds)):
            if i == len(nds) - 1 or use[nds[i]] > 1:
                seg = nds[start:i + 1]
                if len(seg) > 1: pieces.append((f'w{wid}:n{seg[0]}-n{seg[-1]}', wid, seg, tags))
                start = i
    return pieces


# ---------------------------------------------------------------- city streets, for matching
def load_streets(path):
    raw = json.loads(Path(path).read_text())
    S, F = raw['strings'], {f: i for i, f in enumerate(raw['seg_fields'])}
    segs = []
    for r in raw['segs']:
        if not r[F['flags']] & 1: continue
        g, pts, x, y = r[F['geom']], [], 0, 0
        for i in range(0, len(g), 2):
            x, y = (g[0], g[1]) if i == 0 else (x + g[i], y + g[i + 1])
            pts.append((x / 1e5 * KX, y / 1e5 * KY))
        segs.append((r[F['cnn']], S[r[F['streetname']]], pts))
    return segs


class Grid:
    """city street segments (pairs of points) in 50 m cells"""
    def __init__(self, segs, cell=50):
        self.cell, self.cells = cell, defaultdict(list)
        for cnn, name, pts in segs:
            for a, b in zip(pts, pts[1:]):
                for cx in range(int(min(a[0], b[0]) // cell) - 1, int(max(a[0], b[0]) // cell) + 2):
                    for cy in range(int(min(a[1], b[1]) // cell) - 1, int(max(a[1], b[1]) // cell) + 2):
                        self.cells[(cx, cy)].append((cnn, a, b))

    def nearest(self, x, y, heading):
        best = None
        for cnn, a, b in self.cells.get((int(x // self.cell), int(y // self.cell)), ()):
            vx, vy = b[0] - a[0], b[1] - a[1]; L2 = vx * vx + vy * vy or 1
            u = max(0, min(1, ((x - a[0]) * vx + (y - a[1]) * vy) / L2))
            d = math.hypot(x - a[0] - u * vx, y - a[1] - u * vy)
            if d > MATCH_M: continue
            h = math.degrees(math.atan2(vx, vy)) % 180
            dh = abs(h - heading) % 180; dh = min(dh, 180 - dh)
            if dh <= MATCH_DEG and (best is None or d < best[0]): best = (d, cnn)
        return best and best[1]


def along(pts, fracs):
    """points (and headings, 0–180°) at fractions of a line's length, in meters"""
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    total = sum(lens) or 1
    out = []
    for f in fracs:
        d, i = f * total, 0
        while i < len(lens) - 1 and d > lens[i]: d -= lens[i]; i += 1
        a, b = pts[i], pts[i + 1]; u = d / (lens[i] or 1)
        out.append((a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]), math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 180))
    return out, total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('osm', help='an .osm XML file (optionally .gz / .bz2) of the highway ways in San Francisco')
    ap.add_argument('--as-of', default='', help="the OSM data's date (YYYY-MM-DD)")
    ap.add_argument('--streets', default=str(ROOT / 'data' / 'streets.json'))
    ap.add_argument('--geojsonseq', help='write every piece here, one GeoJSON feature per line, for tippecanoe')
    ap.add_argument('--report', help='write a Markdown report here')
    args = ap.parse_args()

    log('reading', args.osm)
    nodes, ways = read_osm(args.osm)
    log(f'  {len(ways):,} ways, {len(nodes):,} nodes')
    pieces = split(ways, nodes)
    log(f'  {len(pieces):,} pieces')
    grid = Grid(load_streets(args.streets))

    by_kind, matched, meters, gap_n = Counter(), Counter(), Counter(), Counter()
    seq = open(args.geojsonseq, 'w') if args.geojsonseq else None
    seq_bytes = Counter()
    gaps = defaultdict(dict)
    samples = defaultdict(list)
    for pid, wid, nds, tags in pieces:
        k = kind_of(tags)
        ll = [nodes[n] for n in nds]
        pts = [(x * KX, y * KY) for x, y in ll]
        probes, length = along(pts, [i / 10 for i in range(1, 10)])
        cnns = []
        if k in ('road', 'alley', 'service'):
            hits = Counter(c for c in (grid.nearest(x, y, h) for x, y, h in probes) if c)
            cnns = [c for c, n in hits.most_common() if n >= 2]
        by_kind[k] += 1; meters[k] += length
        if cnns: matched[k] += 1
        keep = {t: tags[t] for t in KEEP_TAGS if t in tags}
        props = {'id': pid, 'kind': k, 'highway': tags.get('highway', ''), **keep, 'cnns': ';'.join(map(str, cnns))}
        if k in ('sidewalk', 'crossing'): feat_min = 15
        elif k in ('foot', 'steps', 'service'): feat_min = 14
        else: feat_min = 12
        line = json.dumps({'type': 'Feature', 'tippecanoe': {'minzoom': feat_min}, 'properties': props,
                           'geometry': {'type': 'LineString', 'coordinates': [[round(x, 7), round(y, 7)] for x, y in ll]}}, separators=(',', ':'))
        seq_bytes['all'] += len(line) + 1
        if k not in ('sidewalk', 'crossing'): seq_bytes['no_sidewalks'] += len(line) + 1
        if seq: seq.write(line + '\n')
        if not cnns:
            gap_n[k] += 1
            q = [(round(x * SCALE), round(y * SCALE)) for x, y in ll]
            coords = [q[0][0], q[0][1]] + [v for a, b in zip(q, q[1:]) for v in (b[0] - a[0], b[1] - a[1])]
            gaps[wid % 16][pid] = [k, tags.get('highway', ''), tags.get('name', ''), {t: v for t, v in keep.items() if t != 'name'}, coords]
            mx, my = sum(x for x, _ in ll) / len(ll), sum(y for _, y in ll) / len(ll)
            for place, (w, s, e, n) in SAMPLES.items():
                if w <= mx <= e and s <= my <= n and k not in ('sidewalk', 'crossing'): samples[place].append((k, tags.get('name', ''), pid, round(length)))
    if seq: seq.close()

    (OUT / 'gaps').mkdir(parents=True, exist_ok=True)
    gap_bytes = Counter()
    for n in range(16):
        txt = json.dumps(dict(sorted(gaps.get(n, {}).items())), separators=(',', ':'), ensure_ascii=False)
        (OUT / 'gaps' / f'{n}.json').write_text(txt)
        gap_bytes['all'] += len(txt)
        gap_bytes['no_sidewalks'] += len(json.dumps({p: v for p, v in gaps.get(n, {}).items() if v[0] not in ('sidewalk', 'crossing')}, separators=(',', ':'), ensure_ascii=False))
    index = {
        '_doc': 'OpenStreetMap ways in San Francisco as pieces, split where they meet. Built by scripts/build_osm.py. '
                'ways.pmtiles (layer "ways") has every piece; gaps/<way id % 16>.json has the pieces that run along no city street. '
                'Data © OpenStreetMap contributors, ODbL.',
        'as_of': args.as_of, 'source': 'Geofabrik north-america/us/california/norcal-latest.osm.pbf, clipped to San Francisco',
        'attribution': '© OpenStreetMap contributors', 'license': 'ODbL-1.0',
        'pieces': len(pieces), 'ways': len(ways), 'kinds': dict(by_kind.most_common()), 'matched': dict(matched), 'gaps': dict(gap_n.most_common()),
        'tiles': 'ways.pmtiles', 'tile_layer': 'ways', 'gap_files': 'gaps/', 'gap_fields': ['kind', 'highway', 'name', 'tags', 'coords'], 'coord_scale': SCALE,
        'id': 'w<way id>:n<first node>-n<last node>',
    }
    (OUT / 'index.json').write_text(json.dumps(index, indent=1))

    if args.report:
        mb = lambda b: f'{b / 1e6:.1f} MB'
        L = [f'OSM data of {args.as_of or "unknown date"}: {len(ways):,} ways split into **{len(pieces):,} pieces**.', '',
             '| Kind | Pieces | km | Run along a city street | Gaps (no city street) |', '| --- | ---: | ---: | ---: | ---: |']
        for k, n in by_kind.most_common():
            L.append(f'| {k} | {n:,} | {meters[k] / 1000:,.0f} | {matched[k]:,} | {gap_n[k]:,} |')
        L += ['', '**Sizes**', '',
              f'- Every piece as GeoJSON (what tippecanoe reads): {mb(seq_bytes["all"])}; without sidewalks and crosswalks {mb(seq_bytes["no_sidewalks"])}.',
              f'- Gap pieces (`data/osm/gaps/`, what an app loads to draw a picked piece): {mb(gap_bytes["all"])}; without sidewalks and crosswalks {mb(gap_bytes["no_sidewalks"])}.',
              '', '**Gap pieces, by place** (sidewalks and crosswalks left out of these lists)', '']
        for place in SAMPLES:
            got = samples.get(place, [])
            names = Counter(nm for _, nm, _, _ in got if nm)
            L.append(f'- **{place}:** {len(got):,} pieces ({", ".join(f"{k} {n}" for k, n in Counter(k for k, *_ in got).most_common())})'
                     + (f'; named: {", ".join(n for n, _ in names.most_common(8))}' if names else ''))
        Path(args.report).write_text('\n'.join(L) + '\n')
    log('done')


if __name__ == '__main__':
    main()
