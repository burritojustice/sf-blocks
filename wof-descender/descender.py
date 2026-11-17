#!/usr/bin/env python3
# sf-blocks 2026.11.17: wof-descender/descender.py, master copy.
"""Descender: the descendants of any Who's On First place, with their geometries.

Give it a WOF id or a Spelunker URL, pick the placetype(s) and the same filters the
Spelunker's descendants page has, and it writes a GeoJSON FeatureCollection and a CSV with
WKT. Neighbourhoods in San Francisco, counties in Arizona, boroughs in London:

    python3 descender.py 85922583 --placetype neighbourhood --isdeprecated 0
    python3 descender.py "https://spelunker.whosonfirst.org/id/85922583/descendants?isdeprecated=0&placetype=neighbourhood"
    python3 descender.py 85688719 --placetype county --iscurrent 1 -o arizona_counties
    python3 descender.py 101750367 --placetype borough,macrohood --iscurrent 1
    python3 descender.py 101750367 --facets          # what's there: counts by placetype, country, status
    python3 descender.py --serve                     # the web page, on this computer (see README.md)

How it works
  1. The Spelunker's descendants page (spelunker.whosonfirst.org/id/<id>/descendants) lists
     places 10 at a time, one placetype per request. Descender reads every page for each
     placetype asked for, with the filters: placetype, country, iscurrent (1, 0, -1) and
     isdeprecated (0, 1).
  2. Each record comes from data.whosonfirst.org (or the GitHub repo the list names, if that
     fails), and the names of the places in between (a London neighbourhood's borough, an
     SF neighbourhood's macrohood) from the Spelunker's short records.
  3. Outputs, named <id>-<placetype>.geojson / .csv unless -o says otherwise:
     - GeoJSON: one Feature per place, the fields below plus its geometry.
     - CSV: the same fields, with the geometry as WKT in the last column.

The web page (index.html, descender.js) does the same in the browser and writes the same
bytes for the same input: change FIELDS, status(), the sort and the writers together.

Standard library only (Python 3.9+).
"""
import argparse
import concurrent.futures as cf
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '2026.11.17'
SPELUNKER = 'https://spelunker.whosonfirst.org'
DATA = 'https://data.whosonfirst.org'
GITHUB_RAW = 'https://raw.githubusercontent.com/whosonfirst-data'
FILTERS = ['country', 'iscurrent', 'isdeprecated']     # besides placetype; the Spelunker's facets
UA = f'sf-blocks wof-descender/{VERSION} (+https://github.com/burritojustice/sf-blocks)'

# WOF placetypes, broadest first: the order of the <placetype>_id / <placetype> columns.
PLACETYPES = ['planet', 'continent', 'ocean', 'empire', 'country', 'dependency', 'disputed', 'marinearea',
              'macroregion', 'region', 'macrocounty', 'county', 'localadmin', 'metroarea', 'locality',
              'borough', 'macrohood', 'neighbourhood', 'microhood', 'campus', 'building', 'address',
              'venue', 'postalregion', 'postalcode', 'intersection', 'enclosure', 'installation',
              'arcade', 'concourse', 'wing']


# ------------------------------------------------------------------ fetching
def get(url, tries=4, as_json=False):
    """GET with retries for 429 and 5xx; None for a 404."""
    for i in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode('utf-8')
                return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries or e.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries:
                raise
        time.sleep(2 ** i)


def wof_path(wid):
    s = str(wid)
    return '/'.join(s[i:i + 3] for i in range(0, len(s), 3)) + f'/{s}.geojson'


def parse_target(text):
    """A WOF id, a Spelunker URL (/id/<id> or /id/<id>/descendants?...) or a data.whosonfirst.org URL
    → (id, {filter: value}) with the URL's query as filters."""
    text = text.strip()
    if re.fullmatch(r'\d+', text):
        return int(text), {}
    u = urllib.parse.urlparse(text)
    m = re.search(r'/id/(\d+)', u.path) or re.search(r'/(\d+)\.geojson$', u.path)
    if not m:
        raise SystemExit(f"Couldn't find a Who's On First id in {text!r}")
    q = urllib.parse.parse_qs(u.query)
    filters = {k: v[0] for k, v in q.items() if k in ['placetype'] + FILTERS and v and v[0] != ''}
    return int(m.group(1)), filters


def descendants_url(wid, query, base=SPELUNKER, facets=False):
    q = urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, '')})
    return f'{base}/id/{wid}/descendants{"/facets" if facets else ""}' + (f'?{q}' if q else '')


LI = re.compile(r'<li class="spr-place" data-id="(\d+)"(.*?)</li>', re.S)
NAME = re.compile(r'class="wof-place-name[^"]*">(.*?)</a>', re.S)
REPO = re.compile(r'Repo <span class="hey-look">([^<]+)</span>')
COUNT = re.compile(r'There (?:are|is) <span class="hey-look">([\d,]+)</span> place')
PAGES = re.compile(r'page [\d,]+</span> of <span class="hey-look">([\d,]+)</span>')


def parse_page(text):
    """One descendants page → (total, pages, [(id, name, repo)])."""
    rows = []
    for wid, body in LI.findall(text):
        name = NAME.search(body)
        repo = REPO.search(body)
        rows.append((int(wid), html.unescape(name.group(1)).strip() if name else '', repo.group(1) if repo else ''))
    total = COUNT.search(text)
    pages = PAGES.search(text)
    total = int(total.group(1).replace(',', '')) if total else len(rows)
    pages = int(pages.group(1).replace(',', '')) if pages else (1 if rows else 0)
    return total, pages, rows


def walk(wid, placetype, filters, workers=4, log=print):
    """Every place on the descendants pages for one placetype → [(id, name, repo)] in page order."""
    query = {'placetype': placetype, **filters}
    first = get(descendants_url(wid, query))
    if first is None:
        raise SystemExit(f'The Spelunker has no place {wid}')
    total, pages, rows = parse_page(first)
    log(f'  {placetype}: {total:,} places on {pages:,} page{"s" * (pages != 1)}')
    if pages > 1:
        def page(n):
            return parse_page(get(descendants_url(wid, {**query, 'page': n})) or '')[2]
        with cf.ThreadPoolExecutor(workers) as ex:
            for more in ex.map(page, range(2, pages + 1)):
                rows += more
    seen, out = set(), []
    for r in rows:
        if r[0] not in seen and r[0] != wid:
            seen.add(r[0])
            out.append(r)
    if len(out) != total:
        log(f'  {placetype}: the pages listed {len(out):,} of {total:,}')
    return out


def facets(wid, filters):
    """Counts by placetype, country, iscurrent and isdeprecated, for the filters given."""
    out = {}
    for f in ['placetype'] + FILTERS:
        res = get(descendants_url(wid, {**{k: v for k, v in filters.items() if k != f}, 'facet': f}, facets=True),
                  as_json=True) or []
        out[f] = {r['key']: r['count'] for x in res for r in x.get('results', [])}
    return out


def place_spr(wid):
    """The Spelunker's short record for one place (name, placetype, parent…), or None."""
    return get(f'{SPELUNKER}/id/{wid}/spr', as_json=True)


def record(wid, repo, cache=None):
    """The full WOF record: data.whosonfirst.org, then the GitHub repo the Spelunker named."""
    if cache:
        p = os.path.join(cache, f'{wid}.geojson')
        if os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    text = None
    try:
        text = get(f'{DATA}/{wof_path(wid)}')
    except Exception:
        pass
    if text is None and repo:
        text = get(f'{GITHUB_RAW}/{repo}/master/data/{wof_path(wid)}')
    if text is None:
        return None
    if cache:
        with open(os.path.join(cache, f'{wid}.geojson'), 'w', encoding='utf-8') as f:
            f.write(text)
    return json.loads(text)


# ------------------------------------------------------------------ fields
def is_set(v):
    return v is not None and v != '' and v != 'uuuu' and v != [] and v != -1


def status(p):
    if is_set(p.get('edtf:deprecated')):
        return 'deprecated'
    if is_set(p.get('wof:superseded_by')):
        return 'superseded'
    if is_set(p.get('edtf:cessation')):
        return 'ceased'
    c = p.get('mz:is_current')
    if c == 1:
        return 'current'
    if c == 0:
        return 'not current'
    return 'unverified'          # mz:is_current -1 or missing: never reviewed


def edtf(v):
    return '' if v in (None, '', 'uuuu') else str(v)


def ymd(ts):
    if not ts:
        return ''
    return time.strftime('%Y-%m-%d', time.gmtime(int(ts)))


def hierarchy(p, ancestor):
    """The record's hierarchy: the one through the place asked about, else the first."""
    hs = p.get('wof:hierarchy') or []
    for h in hs:
        if ancestor in h.values():
            return h
    return hs[0] if hs else {}


BASE_FIELDS = ['wof_id', 'name', 'placetype', 'status', 'is_current', 'country', 'parent_id', 'parent']
TAIL_FIELDS = ['inception', 'cessation', 'deprecated', 'superseded_by', 'lastmodified', 'src_geom',
               'lbl_latitude', 'lbl_longitude', 'area_m2', 'repo', 'spelunker', 'geojson']


def between(records, ancestor_pt, ancestor):
    """Placetypes whose ids sit in the hierarchies between the place asked about and the records."""
    start = PLACETYPES.index(ancestor_pt) if ancestor_pt in PLACETYPES else -1
    pts = set()
    for r in records:
        p = r['properties']
        own = p.get('wof:placetype')
        end = PLACETYPES.index(own) if own in PLACETYPES else len(PLACETYPES)
        for k, v in hierarchy(p, ancestor).items():
            pt = k[:-3]
            if pt in PLACETYPES and start < PLACETYPES.index(pt) < end and isinstance(v, int) and v > 0:
                pts.add(pt)
    return [pt for pt in PLACETYPES if pt in pts]


def fields(levels):
    return BASE_FIELDS + [f for pt in levels for f in (f'{pt}_id', pt)] + TAIL_FIELDS


def row(r, ancestor, levels, names):
    p = r['properties']
    wid = p['wof:id']
    h = hierarchy(p, ancestor)
    parent = p.get('wof:parent_id')
    parent = parent if isinstance(parent, int) and parent > 0 else None
    area = p.get('geom:area_square_m')
    out = {
        'wof_id': wid, 'name': p.get('wof:name', ''), 'placetype': p.get('wof:placetype', ''),
        'status': status(p), 'is_current': p.get('mz:is_current'),
        'country': p.get('wof:country') or p.get('iso:country') or '',
        'parent_id': parent, 'parent': names.get(parent, '') if parent else '',
    }
    for pt in levels:
        v = h.get(f'{pt}_id')
        v = v if isinstance(v, int) and v > 0 and v != wid else None
        out[f'{pt}_id'] = v
        out[pt] = names.get(v, '') if v else ''
    sup = p.get('wof:superseded_by') or []
    out.update({
        'inception': edtf(p.get('edtf:inception')), 'cessation': edtf(p.get('edtf:cessation')),
        'deprecated': edtf(p.get('edtf:deprecated')),
        'superseded_by': ';'.join(str(x) for x in sup) if isinstance(sup, list) else str(sup),
        'lastmodified': ymd(p.get('wof:lastmodified')),
        'src_geom': p.get('src:geom') or '',
        'lbl_latitude': p.get('lbl:latitude', p.get('geom:latitude')),
        'lbl_longitude': p.get('lbl:longitude', p.get('geom:longitude')),
        'area_m2': math.floor(area + 0.5) if isinstance(area, (int, float)) and area else None,
        'repo': p.get('wof:repo') or '',
        'spelunker': f'{SPELUNKER}/id/{wid}/',
        'geojson': f'{DATA}/{wof_path(wid)}',
    })
    return out


def sort_key(order):
    def key(r):
        p = r['properties']
        pt = p.get('wof:placetype', '')
        return (order.index(pt) if pt in order else len(order), str(p.get('wof:name', '')).lower(), p['wof:id'])
    return key


# ------------------------------------------------------------------ writers (match descender.js)
def js_num(x):
    """A number the way JavaScript's JSON.stringify writes it (copied from scripts/get_layers.py)."""
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
    if -7 <= exp < 21:
        sign = '-' if mant.startswith('-') else ''
        digits = mant.lstrip('-').replace('.', '')
        point = 1 + exp
        if point <= 0:
            s = '0.' + '0' * -point + digits
        elif point >= len(digits):
            s = digits + '0' * (point - len(digits))
        else:
            s = digits[:point] + '.' + digits[point:]
        return sign + s
    mant = mant.rstrip('0').rstrip('.') if '.' in mant else mant
    return f'{mant}e{"+" if exp > 0 else "-"}{abs(exp)}'


def stringify(v):
    """Compact JSON the way JSON.stringify writes it."""
    if v is None:
        return 'null'
    if isinstance(v, (bool, int, float)):
        return js_num(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return '[' + ','.join(stringify(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{' + ','.join(json.dumps(str(k), ensure_ascii=False) + ':' + stringify(x) for k, x in v.items()) + '}'
    raise TypeError(type(v))


def feature(rec, props, all_properties=False):
    p = dict(rec['properties']) if all_properties else props
    return {'type': 'Feature', 'id': props['wof_id'], 'properties': p, 'geometry': rec.get('geometry')}


def geojson_text(name, feats):
    return ('{"type":"FeatureCollection","name":' + stringify(name) + ',"features":[\n'
            + ',\n'.join(stringify(f) for f in feats) + '\n]}\n')


def wkt(g):
    if not g:
        return ''
    t, c = g.get('type'), g.get('coordinates')
    pt = lambda p: ' '.join(js_num(x) for x in p)
    ring = lambda r: '(' + ', '.join(pt(p) for p in r) + ')'
    poly = lambda rs: '(' + ', '.join(ring(r) for r in rs) + ')'
    if t == 'Point':
        return f'POINT ({pt(c)})'
    if t == 'MultiPoint':
        return 'MULTIPOINT (' + ', '.join(f'({pt(p)})' for p in c) + ')'
    if t == 'LineString':
        return 'LINESTRING ' + ring(c)
    if t == 'MultiLineString':
        return 'MULTILINESTRING ' + poly(c)
    if t == 'Polygon':
        return 'POLYGON ' + poly(c)
    if t == 'MultiPolygon':
        return 'MULTIPOLYGON (' + ', '.join(poly(p) for p in c) + ')'
    if t == 'GeometryCollection':
        return 'GEOMETRYCOLLECTION (' + ', '.join(wkt(x) for x in g.get('geometries', [])) + ')'
    return ''


def cell(v):
    if v is None:
        return ''
    s = js_num(v) if isinstance(v, (int, float)) else str(v)
    return '"' + s.replace('"', '""') + '"' if re.search(r'[",\r\n]', s) else s


def csv_text(cols, rows, geoms):
    lines = [','.join(cols + ['wkt'])]
    for r, g in zip(rows, geoms):
        lines.append(','.join([cell(r.get(c)) for c in cols] + [cell(wkt(g))]))
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------ main
def descend(wid, placetypes, filters, workers=4, cache=None, log=print):
    """→ (place spr, records in order, rows, field names, missing [(id, name)])."""
    me = place_spr(wid)
    if not me:
        raise SystemExit(f"The Spelunker doesn't know place {wid}")
    log(f"{me.get('wof:name')} ({me.get('wof:placetype')} {wid}): descendants, {filters or 'no filters'}")
    listed = []
    for pt in placetypes:
        listed += walk(wid, pt, filters, workers, log)
    log(f'downloading {len(listed):,} records…')
    if cache:
        os.makedirs(cache, exist_ok=True)
    recs, missing, done = {}, [], 0
    with cf.ThreadPoolExecutor(workers * 2) as ex:
        futs = {ex.submit(record, i, repo, cache): (i, name) for i, name, repo in listed}
        for f in cf.as_completed(futs):
            i, name = futs[f]
            try:
                r = f.result()
            except Exception as e:
                r = None
                log(f'  {i} {name}: {e}')
            if r and r.get('properties', {}).get('wof:id') == i:
                recs[i] = r
            else:
                missing.append((i, name))
            done += 1
            if done % 50 == 0:
                log(f'  {done:,}/{len(listed):,}')
    records = sorted(recs.values(), key=sort_key(placetypes))
    levels = between(records, me.get('wof:placetype'), wid)
    names = {wid: me.get('wof:name', '')}
    names.update({r['properties']['wof:id']: r['properties'].get('wof:name', '') for r in records})
    need = set()
    for r in records:
        p = r['properties']
        h = hierarchy(p, wid)
        ids = [p.get('wof:parent_id')] + [h.get(f'{pt}_id') for pt in levels]
        need |= {x for x in ids if isinstance(x, int) and x > 0 and x not in names}
    if need:
        log(f'looking up {len(need):,} names of the places in between…')
        with cf.ThreadPoolExecutor(workers * 2) as ex:
            for i, s in zip(need, ex.map(lambda x: _try(place_spr, x), need)):
                names[i] = (s or {}).get('wof:name', '')
    rows = [row(r, wid, levels, names) for r in records]
    return me, records, rows, fields(levels), sorted(missing)


def _try(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def summary(rows, missing):
    tally = {}
    for r in rows:
        k = f"{r['placetype']} {r['status']}"
        tally[k] = tally.get(k, 0) + 1
    out = ', '.join(f'{k} {n:,}' for k, n in sorted(tally.items()))
    if missing:
        out += f'; {len(missing)} not downloaded: ' + ', '.join(f'{i} {n}' for i, n in missing[:10])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog='\n\n'.join(__doc__.split('\n\n')[1:3]))
    ap.add_argument('target', nargs='?', help="a WOF id, or a Spelunker URL (its placetype and filters are used)")
    ap.add_argument('--placetype', '-p', action='append',
                    help='placetype(s) of the descendants: neighbourhood, county, borough… (repeat or comma-separate)')
    ap.add_argument('--country', help='two-letter country code')
    ap.add_argument('--iscurrent', choices=['1', '0', '-1'], help='1 current, 0 not current, -1 unknown')
    ap.add_argument('--isdeprecated', choices=['0', '1'], help='0 leaves out deprecated places, 1 only those')
    ap.add_argument('--facets', action='store_true', help='list counts by placetype, country and status, then stop')
    ap.add_argument('--ids-only', action='store_true', help='list the ids and names, without downloading')
    ap.add_argument('-o', '--out', help='output name, without extension (default <id>-<placetype>)')
    ap.add_argument('--no-csv', action='store_true', help="don't write the CSV")
    ap.add_argument('--all-properties', action='store_true', help='GeoJSON keeps every WOF property, not just the fields')
    ap.add_argument('--cache', help='folder to keep downloaded records in, for reruns')
    ap.add_argument('--workers', type=int, default=4, help='requests at once (default 4)')
    ap.add_argument('--serve', nargs='?', const=8765, type=int, metavar='PORT',
                    help='run the web page on this computer (default port 8765)')
    a = ap.parse_args()

    if a.serve:
        return serve(a.serve)
    if not a.target:
        ap.error('give a WOF id or Spelunker URL (or --serve)')
    wid, filters = parse_target(a.target)
    for k in FILTERS:
        if getattr(a, k) is not None:
            filters[k] = getattr(a, k)
    pts = [x.strip() for v in (a.placetype or []) for x in v.split(',') if x.strip()]
    pts = pts or [x for x in filters.pop('placetype', '').split(',') if x]
    filters.pop('placetype', None)
    unknown = [x for x in pts if x not in PLACETYPES]
    if unknown:
        print(f"warning: {', '.join(unknown)} isn't a WOF placetype I know", file=sys.stderr)

    if a.facets or not pts:
        me = place_spr(wid) or {}
        print(f"{me.get('wof:name', '?')} ({me.get('wof:placetype', '?')} {wid}), descendants"
              + (f' with {filters}' if filters else '') + ':')
        for f, counts in facets(wid, filters).items():
            print(f'  {f}: ' + ', '.join(f'{k or "(none)"} {n:,}' for k, n in sorted(counts.items(), key=lambda kv: -kv[1])))
        if not pts and not a.facets:
            print('\nPick one or more with --placetype.')
        return

    log = lambda s: print(s, file=sys.stderr)
    if a.ids_only:
        for pt in pts:
            for i, name, repo in walk(wid, pt, filters, a.workers, log):
                print(f'{i}\t{pt}\t{name}\t{repo}')
        return

    me, records, rows, cols, missing = descend(wid, pts, filters, a.workers, a.cache, log)
    out = a.out or f"{wid}-{'-'.join(pts)}"
    name = os.path.basename(out)
    feats = [feature(r, row_, a.all_properties) for r, row_ in zip(records, rows)]
    with open(out + '.geojson', 'w', encoding='utf-8', newline='') as f:
        f.write(geojson_text(name, feats))
    written = [out + '.geojson']
    if not a.no_csv:
        with open(out + '.csv', 'w', encoding='utf-8', newline='') as f:
            f.write(csv_text(cols, rows, [r.get('geometry') for r in records]))
        written.append(out + '.csv')
    log(f"{len(rows):,} places: {summary(rows, missing)}")
    log('wrote ' + ' and '.join(written))


# ------------------------------------------------------------------ the web page, locally
def serve(port):
    """Serve the sf-blocks folder, with /spelunker/… passed on to the Spelunker (which doesn't
    let other sites read its pages), so the web page works on this computer."""
    import http.server
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    allowed = re.compile(r'^/id/\d+(/descendants(/facets)?|/spr)?/?$')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=root, **kw)

        def do_GET(self):
            if not self.path.startswith('/spelunker'):
                return super().do_GET()
            u = urllib.parse.urlparse(self.path[len('/spelunker'):] or '/')
            if u.path in ('', '/'):
                return self._send(200, b'{"descender":"' + VERSION.encode() + b'"}', 'application/json')
            if not allowed.match(u.path):
                return self._send(404, b'not found', 'text/plain')
            try:
                req = urllib.request.Request(SPELUNKER + u.path + (f'?{u.query}' if u.query else ''),
                                             headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    self._send(r.status, r.read(), r.headers.get('Content-Type', 'text/html'))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), e.headers.get('Content-Type', 'text/plain'))
            except Exception as e:
                self._send(502, str(e).encode(), 'text/plain')

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Descender: http://localhost:{port}/wof-descender/  (Ctrl-C to stop)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
