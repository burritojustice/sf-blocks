#!/usr/bin/env python3
# sf-blocks 2026.10.28: master copy.
"""Add a boundary set to sf-blocks, or refresh one, in one step. This is what the "Add or refresh a boundary
set" GitHub Action runs, so nobody needs a command line; it works the same from one.

    python3 scripts/add_boundary_set.py --id historic_districts --source 63x5-g3m4
    python3 scripts/add_boundary_set.py --id historic_districts --source data/uploads/Historic_Districts_20261028.geojson
    python3 scripts/add_boundary_set.py --id historic_districts            # refresh from its DataSF dataset

--source is a DataSF dataset id (63x5-g3m4), a link to a DataSF dataset page, or a GeoJSON file already in
data/uploads/ (an export someone uploaded). It then:

  1. downloads the dataset as GeoJSON into data/uploads/<Title>_<YYYYMMDD>.geojson (kept as published);
  2. picks the field that names each area, unless --name says (name-like, readable, mostly filled in, not
     an id); names shared by several pieces make one area each (mergeByKey);
  3. adds or updates the set in data/boundaries/sources.json (fields to keep, label, Joiner tab);
  4. builds data/boundaries/<id>.geojson and index.json with get_layers.py;
  5. bumps VERSION and adds a CHANGELOG entry;
  6. with --summary, writes a Markdown report (fields, the chosen name, counts, warnings, preview links)
     for the pull request.

Standard library only.
"""
import argparse, json, re, sys, urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import get_layers  # noqa: E402

OUT_DIR = ROOT / 'data' / 'boundaries'
SOURCES = OUT_DIR / 'sources.json'
INDEX = OUT_DIR / 'index.json'
UPLOADS = ROOT / 'data' / 'uploads'
REPO = 'burritojustice/sf-blocks'
APPS = {'Joiner': 'https://burritojustice.github.io/joiner/', 'Block Party': 'https://burritojustice.github.io/block-party/'}
DATASET = re.compile(r'(?<![a-z0-9])([a-z0-9]{4}-[a-z0-9]{4})(?![a-z0-9])')
ID_LIKE = re.compile(r'^(fid|objectid|object_id|id|ogc_fid|gid|globalid|shape_?(area|len|length|leng)|cartodb_id)$|_id$|^id_', re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'sf-blocks'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode('utf-8'))


def text_values(feats, k):
    vals = [(f.get('properties') or {}).get(k) for f in feats]
    return [str(v).strip() for v in vals if v is not None and not isinstance(v, (dict, list)) and str(v).strip() != '']


def name_score(feats, k):
    """how likely a field names each area; the same rules as Joiner's guess for uploaded polygons"""
    filled = text_values(feats, k)
    if not filled or len(filled) < len(feats) * 0.5:
        return None
    distinct = len(set(filled))
    if distinct < 2 and len(feats) > 1:
        return None
    s = distinct / len(feats) + sum(1 for v in filled if re.search('[a-z]', v, re.I)) / len(filled)
    if re.search('name|label|title', k, re.I):
        s += 2
    elif re.search('nhood|neighbo|district|dist$|county|zip|zcta|geoid|tract', k, re.I):
        s += 1
    if ID_LIKE.search(k):
        s -= 3
    if all(re.fullmatch(r'-?[\d.]+', v) for v in filled) and not re.search('zip|zcta|geoid|tract|district|dist$', k, re.I):
        s -= 1.5
    return s


def field_table(feats, fields):
    rows = ['| Field | Filled | Different values | Examples |', '| --- | --- | --- | --- |']
    for k in fields:
        vals = text_values(feats, k)
        ex = ', '.join(sorted(set(vals), key=vals.index)[:3])
        ex = (ex[:70] + '…') if len(ex) > 70 else ex
        rows.append(f'| `{k}` | {len(vals)} of {len(feats)} | {len(set(vals))} | {ex.replace("|", "/")} |')
    return '\n'.join(rows)


def bump_version(note):
    today = date.today().strftime('%Y.%m.%d')
    old = (ROOT / 'VERSION').read_text().strip()
    if old == today or old.startswith(today + '.'):
        n = int(old.split('.')[3]) + 1 if old.count('.') == 3 else 2
        new = f'{today}.{n}'
    else:
        new = today
    (ROOT / 'VERSION').write_text(new + '\n')
    log = ROOT / 'CHANGELOG.md'
    s = log.read_text()
    i = s.index('\n## ') + 1
    log.write_text(s[:i] + f'## {new}\n{note}\n\n' + s[i:])
    return new


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--id', required=True, help='set id: lowercase words joined by _, e.g. historic_districts')
    ap.add_argument('--source', default='', help='DataSF dataset id or page link, or a file in data/uploads/; blank refreshes the set from its dataset')
    ap.add_argument('--name', default='', help='field that names each area (what rows match); blank: guess')
    ap.add_argument('--label', default='', help="title in the apps; blank: the dataset's name")
    ap.add_argument('--tab', default='', help='Joiner tab (Other, Neighborhood, District, ZIP); blank: Other, or what the set has')
    ap.add_argument('--keep', default='', help='other fields to keep, comma separated; blank: readable text fields')
    ap.add_argument('--summary', default='', help='write a Markdown report here')
    ap.add_argument('--branch', default='', help='branch the result is pushed to, for preview links')
    ap.add_argument('--no-version', action='store_true', help="don't bump VERSION or CHANGELOG")
    a = ap.parse_args(argv)

    if not re.fullmatch(r'[a-z][a-z0-9_]{2,40}', a.id):
        sys.exit(f'--id "{a.id}": use lowercase letters, numbers and _, like historic_districts')
    before_sources = SOURCES.read_text(encoding='utf-8')
    before_index = INDEX.read_text(encoding='utf-8')
    before_set = (OUT_DIR / f'{a.id}.geojson').read_text(encoding='utf-8') if (OUT_DIR / f'{a.id}.geojson').exists() else None
    downloaded = False
    cfg = json.loads(before_sources)
    existing = next((l for l in cfg['layers'] if l['id'] == a.id), None)
    portal = cfg['portal']
    notes, title, dataset, page = [], None, None, None

    # 1. the data: a file in data/uploads/, or a DataSF download saved there
    src = a.source.strip()
    if src and not DATASET.search(src.lower()) or src.endswith(('.geojson', '.json')):
        path = (ROOT / src).resolve() if not Path(src).is_absolute() else Path(src)
        if not path.exists():
            sys.exit(f'{src}: no such file (upload it to data/uploads/ first)')
        upload = path
        title = re.sub(r'[_-]?\d{8}$', '', path.stem).replace('_', ' ').strip()
        dataset = (existing or {}).get('dataset')
    else:
        m = DATASET.search(src.lower()) if src else None
        dataset = m.group(1) if m else (existing or {}).get('dataset')
        if not dataset:
            sys.exit(f'{a.id} is new: give --source (a DataSF dataset id or page link, or a file in data/uploads/)')
        try:
            meta = fetch(f'{portal}/api/views/{dataset}.json')
            title = meta.get('name')
        except Exception as e:   # the page title is only for names; the download is what matters
            print(f'  ! could not read the dataset description ({e})')
        print(f'downloading {dataset} ({title or "?"})')
        gj = fetch(f'{portal}/resource/{dataset}.geojson?$limit={get_layers.SODA_LIMIT}')
        stem = re.sub(r'[^A-Za-z0-9]+', '_', title or a.id).strip('_')
        upload = UPLOADS / f'{stem}_{date.today():%Y%m%d}.geojson'
        UPLOADS.mkdir(parents=True, exist_ok=True)
        downloaded = not upload.exists()
        upload.write_text(json.dumps(gj, ensure_ascii=False) + '\n', encoding='utf-8')
        page = f'{portal}/d/{dataset}'
    gj = json.loads(upload.read_text(encoding='utf-8'))
    feats = [f for f in gj.get('features', []) if (f.get('geometry') or {}).get('type') in ('Polygon', 'MultiPolygon')]
    if not feats:
        sys.exit(f'{upload.name} has no polygons')
    skipped = len(gj.get('features', [])) - len(feats)
    if skipped:
        notes.append(f'{skipped} features without polygons were left out.')
    fields = [k for k in dict.fromkeys(k for f in feats for k in (f.get('properties') or {})) if not k.startswith((':', '@'))]

    # 2. the field that names each area
    scores = {k: s for k in fields if (s := name_score(feats, k)) is not None}
    name = a.name.strip() or ((existing or {}).get('name') if existing and (existing or {}).get('name') in fields else None) \
        or (max(scores, key=scores.get) if scores else None)
    if not name or name not in fields:
        sys.exit(f'no field names the areas{f" (--name {a.name} isn’t one)" if a.name else ""}; fields: {", ".join(fields)}')
    names = text_values(feats, name)
    dupes = len(names) - len(set(names))
    blanks = len(feats) - len(names)

    # 3. sources.json
    if a.keep.strip():
        keep = [name] + [k.strip() for k in a.keep.split(',') if k.strip() and k.strip() != name]
    elif existing:
        keep = [k for k in existing['keep'] if k in fields] or [name]
    else:
        def readable(k):
            v = text_values(feats, k)
            return (k != name and not ID_LIKE.search(k) and len(v) >= len(feats) * 0.5 and len(set(v)) > 1
                    and sum(map(len, v)) / len(v) <= 80)
        keep = [name] + [k for k in fields if readable(k)][:6]
    missing = [k for k in keep if k not in fields]
    if missing:
        sys.exit(f'not in the data: {", ".join(missing)}; fields: {", ".join(fields)}')
    entry = dict(existing or {})
    entry.update(id=a.id, label=a.label.strip() or entry.get('label') or title or a.id.replace('_', ' ').title(),
                 tab=a.tab.strip() or entry.get('tab') or 'Other', key=name, name=name, keep=keep)
    if dataset:
        entry['dataset'] = dataset
    if page or not entry.get('page'):
        entry['page'] = page or entry.get('page') or ''
    if dupes:
        entry['mergeByKey'] = True
    entry.setdefault('match', {'caseInsensitive': True, 'collapseSpace': True})
    entry.pop('expectCount', None) if existing and existing.get('expectCount') not in (None, len(set(names))) else None
    order = ['id', 'label', 'short', 'tab', 'default', 'dataset', 'localFiles', 'dissolve', 'page', 'key', 'name', 'nameTemplate',
             'labelTemplate', 'labelExtras', 'keep', 'mergeByKey', 'regional', 'expectCount', 'match']
    entry = {k: entry[k] for k in order + [k for k in entry if k not in order] if k in entry}
    if existing:
        cfg['layers'][cfg['layers'].index(existing)] = entry
    else:
        cfg['layers'].append(entry)
    SOURCES.write_text(get_layers.stringify(cfg, indent=2) + '\n', encoding='utf-8')

    # 4. build
    rel = upload.relative_to(ROOT) if upload.is_relative_to(ROOT) else upload
    out = ROOT / 'data' / 'boundaries' / f'{a.id}.geojson'
    status = get_layers.main([a.id, '--file', f'{a.id}={upload}'])
    if status:
        sys.exit(f'get_layers.py failed for {a.id}')
    # a refresh that changed nothing leaves the repo as it was (no new upload, version or pull request)
    if existing and before_set == out.read_text(encoding='utf-8') and before_sources == SOURCES.read_text(encoding='utf-8'):
        INDEX.write_text(before_index, encoding='utf-8')
        if downloaded:
            upload.unlink()
        print(f'{a.id}: no change')
        if a.summary:
            Path(a.summary).write_text(f'**`{a.id}`: no change** since the last build.\n', encoding='utf-8')
        return 0
    built = json.loads(out.read_text(encoding='utf-8'))
    n = len(built['features'])

    # 5. version
    verb = 'Refreshed' if existing else 'Added'
    version = None
    if not a.no_version:
        version = bump_version(f'- {verb} boundary set `{a.id}` ({entry["label"]}): {n} areas named by `{name}`, from '
                               + (f'DataSF [{dataset}]({entry["page"]})' if dataset and not a.source.endswith(('.geojson', '.json')) else f'`{rel}`')
                               + f'. Raw copy: `{rel}`.')

    # 6. report
    if a.summary:
        b = a.branch or 'main'
        live = f'https://raw.githubusercontent.com/{REPO}/{b}/'
        others = sorted(scores, key=scores.get, reverse=True)
        lines = [
            f'**{verb} `{a.id}`: {entry["label"]}**' + (f' (sf-blocks {version})' if version else ''),
            '',
            f'- Source: ' + (f'DataSF [{dataset}]({entry["page"]})' if dataset else f'`{rel}`') + f'; raw copy in `{rel}`',
            f'- **{n} areas**, named by **`{name}`**' + (f' (other candidates: {", ".join(f"`{k}`" for k in others[1:4])})' if len(others) > 1 else ''),
            f'- Joiner tab: {entry["tab"]}; fields kept: ' + ', '.join(f'`{k}`' for k in keep),
        ]
        if dupes:
            lines.append(f'- {dupes} pieces share a name with another piece, so they were joined into one area each.')
        if blanks:
            lines.append(f'- {blanks} pieces have no `{name}` and were left out.')
        lines += [f'- {x}' for x in notes]
        lines += ['', '**Check it before merging** (these read this branch):', '']
        lines += [f'- [{app}]({url}?sfblocks={live}#layer={a.id})' + (': Other menu' if app == 'Joiner' and entry['tab'] == 'Other' else '')
                  for app, url in APPS.items() if app == 'Joiner']
        lines += ['- The names in the area list look right (not ids or codes); if not, run the Action again with **Name field** set to another field below.',
                  '', '<details><summary>All fields</summary>', '', field_table(feats, fields), '', '</details>', '',
                  'After merging, Joiner shows the set from sf-blocks right away. To show it in Block Party (map layer and card row), '
                  f"add `{{ k: '…', set: '{a.id}', color: '#…' }}` to `AREA_LAYERS` in Block Party's `index.html`."]
        Path(a.summary).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{verb.lower()} {a.id}: {n} areas named by {name}' + (f'; sf-blocks {version}' if version else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
