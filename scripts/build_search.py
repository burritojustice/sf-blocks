#!/usr/bin/env python3
# sf-blocks 2026.11.10
"""Build the search index apps load for "Address / Places" search into data/search/.

    python3 scripts/build_search.py                  download from DataSF and build everything
    python3 scripts/build_search.py --cache DIR      keep the downloads in DIR (re-used if there)

Writes:
  data/search/index.json        the manifest: counts, files, the data's dates, and the street → shard map
  data/search/businesses.json   open business locations in the city: name, owner (when it's not the name),
                                address, self-reported NAICS code, kind (from data/tiles/business_kinds.json:
                                not a storefront), and the point
  data/search/addresses/<k>.json  every address (Enterprise Addressing System), one file per first character
                                of the street name: {street: [[number, suffix, x, y, lot, cnn], ...]}
  data/search/landmarks.json    named places from the same address list (City Hall, ...)
  data/search/naics.json        NAICS 2022 code → title (2 to 6 digits), from data/uploads/naics_2022_codes.xlsx

Points are whole numbers: x = (lon - x0) * 100000 and y = (lat - y0) * 100000, with x0 / y0 from index.json
(about a meter). Lots are block + lot as one string ("3596012"). Standard library only.
"""
import argparse, csv, io, json, re, sys, time, urllib.parse, urllib.request, zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'search'
PORTAL = 'https://data.sf.gov'
PAGE = 50000
SCALE = 100000
BUSINESSES = {
    'dataset': 'g8m3-pdis',
    'select': 'dba_name,ownership_name,full_business_address,self_reported_naics_code,location',
    'where': "location_end_date IS NULL AND dba_end_date IS NULL AND location IS NOT NULL",
}
ADDRESSES = {
    'dataset': '3mea-di5p',
    'select': 'address_number,address_number_suffix,street_name,street_type,cnn,parcel_number,longitude,latitude,complete_landmark_name',
    'where': 'longitude IS NOT NULL',
}
csv.field_size_limit(1 << 30)


def log(*a): print(*a, file=sys.stderr, flush=True)


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'sf-blocks build_search.py'})
            with urllib.request.urlopen(req, timeout=300) as r: return r.read()
        except Exception as e:
            if i == tries - 1: raise
            log(f'  retry ({e})'); time.sleep(5 * (i + 1))


def fetch(ds, cache):
    """All rows of a DataSF dataset as dicts (CSV, in pages), kept in the cache folder if one is given."""
    path = cache / f"{ds['dataset']}.csv" if cache else None
    if path and path.exists():
        log(f'  using {path}')
        return list(csv.DictReader(path.open(newline='', encoding='utf-8')))
    rows, off = [], 0
    q = '&$select=' + urllib.parse.quote(ds['select']) + '&$where=' + urllib.parse.quote(ds['where'])
    while True:
        url = f"{PORTAL}/resource/{ds['dataset']}.csv?$limit={PAGE}&$offset={off}&$order=:id{q}"
        page = list(csv.DictReader(io.StringIO(get(url).decode('utf-8'))))
        rows += page; off += PAGE
        log(f"  {ds['dataset']}: {len(rows):,} rows")
        if len(page) < PAGE: break
    if path:
        cache.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else []); w.writeheader(); w.writerows(rows)
    return rows


def as_of(ds):
    try: return date.fromtimestamp(json.loads(get(f"{PORTAL}/api/views/{ds['dataset']}.json"))['rowsUpdatedAt']).isoformat()
    except Exception: return None


def point_wkt(v):
    m = re.match(r'\s*POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)', v or '', re.I)
    return (float(m.group(1)), float(m.group(2))) if m else None


def naics_titles(xlsx):
    """NAICS 2022 '2-6 digit' workbook → {code: title}. Sector ranges like 31-33 become 31, 32 and 33."""
    z = zipfile.ZipFile(xlsx)
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    strings = [''.join(t.text or '' for t in si.iter(f"{{{ns['s']}}}t")) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', ns)]
    sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    out = {}
    for row in sheet.iter(f"{{{ns['s']}}}row"):
        vals = {}
        for c in row.findall('s:c', ns):
            v = c.find('s:v', ns)
            if v is None: continue
            col = re.match(r'[A-Z]+', c.get('r')).group(0)
            vals[col] = strings[int(v.text)] if c.get('t') == 's' else v.text
        code, title = (vals.get('B') or '').strip(), (vals.get('C') or '').strip()
        if not title or not re.match(r'^\d{2}(-\d{2})?\d*$', code.replace('.0', '')): continue
        code = code.replace('.0', '')
        title = re.sub(r'T$', '', title).strip()   # the workbook marks some titles with a trailing T
        if '-' in code:
            a, b = code.split('-')
            for n in range(int(a), int(b) + 1): out[str(n)] = title
        else: out[code] = title
    return dict(sorted(out.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cache', type=Path, help='folder to keep the downloads in (re-used if there)')
    args = ap.parse_args()
    region = json.loads((ROOT / 'region.json').read_text())
    x0, y0, x1, y1 = region['bbox']
    inside = lambda x, y: x0 <= x <= x1 and y0 <= y <= y1
    xy = lambda x, y: [round((x - x0) * SCALE), round((y - y0) * SCALE)]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'addresses').mkdir(exist_ok=True)

    # NAICS titles
    naics = naics_titles(ROOT / 'data' / 'uploads' / 'naics_2022_codes.xlsx')
    (OUT / 'naics.json').write_text(json.dumps(naics, separators=(',', ':'), ensure_ascii=False))
    log(f'naics: {len(naics):,} codes')

    # businesses
    log('businesses')
    kinds = json.loads((ROOT / 'data' / 'tiles' / 'business_kinds.json').read_text())
    named, keep, rule = kinds.get('owners', {}), set(kinds.get('storefronts', [])), kinds.get('rule') or {}
    by_naics = sorted((kinds.get('naics') or {}).items(), key=lambda kv: -len(kv[0]))
    raw = fetch(BUSINESSES, args.cache)
    recs = []
    for r in raw:
        p = point_wkt(r.get('location'))
        if not p or not inside(*p): continue
        dba = (r.get('dba_name') or '').strip(); owner = (r.get('ownership_name') or '').strip()
        if re.match(r'^(N/A|Same As Ownership)$', dba, re.I): dba = ''
        recs.append({'name': dba or owner, 'owner': owner if owner and owner != dba else '', 'owner_raw': owner,
                     'address': (r.get('full_business_address') or '').strip(), 'naics': re.sub(r'\D', '', r.get('self_reported_naics_code') or ''), 'p': p})
    addrs = defaultdict(set)
    for b in recs: addrs[b['owner_raw']].add(b['address'])
    def kind(b):
        o, n = b['owner_raw'], b['naics']
        if o in keep: return ''
        return named.get(o) or next((k for pre, k in by_naics if n.startswith(pre)), None) \
            or (rule.get('kind') if o and len(addrs[o]) >= rule.get('min_addresses', 1e9) else '') or ''
    rows = sorted(([b['name'], b['owner'] if b['owner'] != b['name'] else '', b['address'], b['naics'], kind(b), *xy(*b['p'])] for b in recs if b['name']),
                  key=lambda r: (r[4] != '', r[0].lower()))
    (OUT / 'businesses.json').write_text(json.dumps({'fields': ['name', 'owner', 'address', 'naics', 'kind', 'x', 'y'], 'rows': rows}, separators=(',', ':'), ensure_ascii=False))
    log(f'  {len(rows):,} in the city')

    # addresses, by street, sharded on the street name's first character
    log('addresses')
    shards, landmarks, n_addr = defaultdict(lambda: defaultdict(list)), [], 0
    for r in fetch(ADDRESSES, args.cache):
        try: x, y = float(r['longitude']), float(r['latitude'])
        except (TypeError, ValueError): continue
        if not inside(x, y): continue
        street = ' '.join(v for v in ((r.get('street_name') or '').strip(), (r.get('street_type') or '').strip()) if v).upper()
        if not street: continue
        num = int(r['address_number']) if (r.get('address_number') or '').isdigit() else 0
        row = [num, (r.get('address_number_suffix') or '').strip(), *xy(x, y), (r.get('parcel_number') or '').strip(), int(r['cnn']) if (r.get('cnn') or '').isdigit() else 0]
        key = street[0].lower() if street[0].isalnum() else '_'
        shards[key][street].append(row); n_addr += 1
        lm = (r.get('complete_landmark_name') or '').strip()
        if lm: landmarks.append([lm, f"{num}{row[1]} {street}".strip(), *xy(x, y), row[4], row[5]])
    streets, files = {}, {}
    for key, by_street in sorted(shards.items()):
        data = {s: sorted(v) for s, v in sorted(by_street.items())}
        (OUT / 'addresses' / f'{key}.json').write_text(json.dumps(data, separators=(',', ':')))
        files[key] = sum(len(v) for v in data.values())
        for s in data: streets[s] = key
    landmarks.sort(key=lambda r: r[0].lower())
    (OUT / 'landmarks.json').write_text(json.dumps({'fields': ['name', 'address', 'x', 'y', 'lot', 'cnn'], 'rows': landmarks}, separators=(',', ':'), ensure_ascii=False))
    log(f'  {n_addr:,} addresses on {len(streets):,} streets; {len(landmarks):,} landmarks')

    index = {
        '_doc': 'Search index for Address / Places search. Built by scripts/build_search.py. Points are integers: lon = x0 + x / scale, lat = y0 + y / scale.',
        'built': date.today().isoformat(), 'x0': x0, 'y0': y0, 'scale': SCALE,
        'businesses': {'file': 'businesses.json', 'n': len(rows), 'dataset': BUSINESSES['dataset'], 'as_of': as_of(BUSINESSES),
                       'kinds': kinds.get('kinds', {})},
        'addresses': {'dir': 'addresses/', 'n': n_addr, 'files': files, 'dataset': ADDRESSES['dataset'], 'as_of': as_of(ADDRESSES),
                      'fields': ['number', 'suffix', 'x', 'y', 'lot', 'cnn']},
        'streets': streets,
        'landmarks': {'file': 'landmarks.json', 'n': len(landmarks)},
        'naics': {'file': 'naics.json', 'n': len(naics), 'source': 'data/uploads/naics_2022_codes.xlsx (census.gov, 2022 NAICS 2-6 digit codes)'},
    }
    (OUT / 'index.json').write_text(json.dumps(index, indent=1, ensure_ascii=False))
    log('done')


if __name__ == '__main__':
    main()
