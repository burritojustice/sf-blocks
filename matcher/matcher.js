// Matcher: load a CSV, Excel sheet, GeoJSON or link; match it to San Francisco blocks with sf-blocks'
// own Python scripts (run in a worker with Pyodide); show and fix results on a map and in a table; save
// the enhanced file. Nothing leaves the browser except requests for the map and the libraries.
'use strict';
const MATCHER_VERSION = '9';
const BASE = new URL('../', location.href).href;          // the sf-blocks site root
const STYLE = key => `https://api.protomaps.com/styles/v5/white/en.json?key=${key}`;
const DEFAULT_KEY = '071e272e8d5e13b7';                   // burritojustice.github.io (localhost accepts any key)
const BATCH = 100;                                         // rows per trip to the worker
const SHOW = 500;                                          // table rows drawn at once
const OUT_FIELDS = ['source_row', 'part', 'parts', 'matched_text', 'type', 'cnn', 'nearby_cnns', 'street', 'from_street',
    'to_street', 'address_low', 'address_high', 'address_ranges', 'supervisor_district', 'nhood', 'wkt',
    'confidence', 'method', 'notes'];
const POLY_FIELDS = ['polygon_index', 'polygon_name', 'polygon_id', 'shape', 'width_m', 'type', 'cnn', 'street',
    'from_street', 'to_street', 'layer', 'inside_pct', 'near_m', 'status', 'note', 'wkt'];
const CONF = ['high', 'medium', 'low', 'none', 'manual', 'polygon'];
const COLORS = { high: '#22814f', medium: '#c48a00', low: '#d4572a', none: '#8a93a3', manual: '#7a4bd1', polygon: '#5b6475' };
const EXCLUDED_LAYERS = new Set(['FREEWAYS', 'PAPER', 'PAPER_FWYS', 'PAPER_WATER', 'PSEUDO', 'PRIVATE_PARKING']);

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n.toLocaleString('en-US');

// ------------------------------------------------------------------ state
const S = {
    kind: null,          // 'rows' or 'polygons'
    name: '', ext: '',   // file name without extension, and its type
    headers: [], rows: [], features: [], workbook: null,
    drive: null,         // the Google Drive file this came from: {id, name, kind, tabs?}
    showCols: true,      // show the person's other columns in the table
    results: [],         // rows: {key, src, out, fixed}; polygons: {key, index, name, feature, rows, fixed, only}
    polys: [],           // polygons loaded, before matching: {index (in the file), feature, removed, only}
    prepSel: new Set(),  // polygons selected in that list (file indexes)
    filter: 'all', query: '', selected: null,
    pick: null,          // {key, cnns: Set, nodes: Set}
    streets: null,       // {segs: Map cnn -> {street, f, t, coords}, nodes: Map cnn -> {streets, xy}}
    version: '',
};

// ------------------------------------------------------------------ worker
// Pyodide 314 (Python 3.14) crashes while starting on Safari 18 ("Out of bounds memory access" in
// _PyRun_SimpleString); Safari 26 is fine. When a version fails to start, Matcher starts a fresh worker
// with the next one. Pyodide 0.27 (Python 3.12) works on Safari 18, and the scripts give the same
// answers on 3.12.
const PYODIDE_VERSIONS = ['https://cdn.jsdelivr.net/npm/pyodide@314.0.7/', 'https://cdn.jsdelivr.net/npm/pyodide@0.27.7/'];
// ?pyodide=<url>[,<url>…] loads Python from other copies, in that order (for tests without the CDN).
const params = new URLSearchParams(location.search);
const PYODIDE_OVERRIDE = params.get('pyodide');
const PYODIDE_URLS = PYODIDE_OVERRIDE ? PYODIDE_OVERRIDE.split(',').map(u => new URL(u, location.href).href) : PYODIDE_VERSIONS;
let worker, nextId = 1;
const waiting = new Map();
function newWorker() {
    worker?.terminate();
    for (const w of waiting.values()) w.reject(new Error('Python stopped'));
    waiting.clear();
    worker = new Worker('worker.js', { type: 'module' });
    worker.onmessage = ({ data: m }) => {
        if (m.op === 'status') { $('engine').textContent = m.text; return; }
        const w = waiting.get(m.id); waiting.delete(m.id);
        if (!w) return;
        m.error ? w.reject(new Error(m.error)) : w.resolve(m.result);
    };
    // a worker that crashes outright (rather than reporting an error) fails whatever was waiting on it
    worker.onerror = e => { for (const w of waiting.values()) w.reject(new Error(e.message || 'Python stopped')); waiting.clear(); };
}
const ask = (op, data = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    waiting.set(id, { resolve, reject });
    worker.postMessage({ id, op, ...data });
});
async function startEngine() {
    let last;
    for (const [i, url] of PYODIDE_URLS.entries()) {
        newWorker();
        try {
            const info = await ask('init', { base: BASE, pyodide: url });
            if (i) console.info(`[matcher] started with ${url} after: ${last.message}`);
            return info;
        } catch (e) {
            last = e;
            // expected on Safari 18 with Pyodide 314; the next version usually starts
            (i + 1 < PYODIDE_URLS.length ? console.info : console.warn)(`[matcher] Pyodide ${url.match(/pyodide@([\d.]+)/)?.[1] || url} couldn't start here (${e.message})${i + 1 < PYODIDE_URLS.length ? '; trying the next version' : ''}.`);
            if (i + 1 < PYODIDE_URLS.length) $('engine').textContent = 'Trying another Python…';
        }
    }
    throw last;
}
const engine = startEngine().then(info => {
    S.version = info.version;
    $('engine').textContent = `sf-blocks ${info.version} · ready`;
    $('engine').classList.add('ready');
    $('logo').title = `Matcher ${MATCHER_VERSION} · sf-blocks ${info.version} · Pyodide ${info.python}`;
    return info;
}).catch(e => {
    $('engine').textContent = "Python didn't start";
    $('engine').classList.add('bad');
    $('engine').title = e.message;
    toast(`Matching can't start in this browser (${e.message}). Updating the browser, or trying Chrome or Firefox, should fix it.`, null, 12000);
    throw e;
});

// ------------------------------------------------------------------ toast
let toastTimer;
function toast(text, frac = null, hideAfter = 0) {
    clearTimeout(toastTimer);
    $('toast').hidden = false;
    $('toast-text').textContent = text;
    $('toast').classList.toggle('nobar', frac == null);
    if (frac != null) $('toast-bar').style.width = `${Math.round(frac * 100)}%`;
    if (hideAfter) toastTimer = setTimeout(() => { $('toast').hidden = true; }, hideAfter);
}
const done = (text, ms = 3500) => toast(text, null, ms);

// ------------------------------------------------------------------ map
let map, popup, hoverSeg = null, HOME = [[-122.5149, 37.7081], [-122.357, 37.8324]];
const empty = () => ({ type: 'FeatureCollection', features: [] });

async function startMap() {
    let region = {};
    try { region = await (await fetch(BASE + 'region.json')).json(); } catch (e) { console.warn('[region]', e); }
    const keys = region.basemap?.keys || {};
    const key = keys[location.origin] || DEFAULT_KEY;
    const bbox = region.bbox || [-122.5149, 37.7081, -122.357, 37.8324];
    HOME = [[bbox[0], bbox[1]], [bbox[2], bbox[3]]];
    map = new maplibregl.Map({ container: 'map', style: STYLE(key), bounds: [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        fitBoundsOptions: { padding: 20 }, attributionControl: { compact: true }, hash: false });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.addControl({ onAdd() {
        const el = document.createElement('div');
        el.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-switch';
        el.innerHTML = '<button type="button" data-b="map" aria-pressed="true">Map</button><button type="button" data-b="sat" aria-pressed="false">Satellite</button>';
        el.onclick = e => { const b = e.target.closest('[data-b]'); if (b) setBasemap(b.dataset.b === 'sat'); };
        return el;
    }, onRemove() {} }, 'top-right');
    popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on('load', () => {
        fixCreeks();
        const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
        map.addSource('streets', { type: 'geojson', data: empty(), promoteId: 'cnn' });
        map.addSource('nodes', { type: 'geojson', data: empty(), promoteId: 'cnn' });
        map.addSource('polys', { type: 'geojson', data: empty() });
        map.addSource('results', { type: 'geojson', data: empty() });
        map.addSource('picked', { type: 'geojson', data: empty() });
        // Satellite: Esri World Imagery, drawn under the basemap's labels and above everything else of it
        map.addSource('satellite', { type: 'raster', tileSize: 256, maxzoom: 19,
            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
            attribution: 'Imagery © <a href="https://www.esri.com">Esri</a>, Maxar, Earthstar Geographics' });
        map.addLayer({ id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } }, before);
        map.addLayer({ id: 'polys-fill', type: 'fill', source: 'polys', paint: { 'fill-color': ['case', ['get', 'only'], '#5b6475', '#2f5fd0'], 'fill-opacity': ['case', ['get', 'sel'], 0.22, 0.06] } }, before);
        map.addLayer({ id: 'polys-line', type: 'line', source: 'polys', paint: { 'line-color': ['case', ['get', 'only'], '#5b6475', '#2f5fd0'], 'line-width': ['case', ['get', 'sel'], 3, 1.2], 'line-opacity': 0.85 } }, before);
        // Lines go under the basemap's labels so street names stay readable, above all while fixing a row.
        map.addLayer({ id: 'streets-pick', type: 'line', source: 'streets', layout: { visibility: 'none', 'line-cap': 'round' },
            paint: { 'line-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#7a4bd1', '#9aa3b5'],
                     'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2, 17, 7], 'line-opacity': 0.55 } }, before);
        map.addLayer({ id: 'results-line', type: 'line', source: 'results', filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 11, ['case', ['get', 'sel'], 5, 3], 17, ['case', ['get', 'sel'], 12, 8]],
                     'line-opacity': ['case', ['get', 'sel'], 1, 0.85] } }, before);
        map.addLayer({ id: 'results-pt', type: 'circle', source: 'results', filter: ['==', ['geometry-type'], 'Point'],
            paint: { 'circle-color': ['get', 'color'], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['*', ['get', 'r'], ['case', ['get', 'sel'], 7, 5]], 17, ['*', ['get', 'r'], ['case', ['get', 'sel'], 13, 9]]],
                     'circle-stroke-color': '#fff', 'circle-stroke-width': ['*', ['get', 'r'], 1.5] } });
        map.addLayer({ id: 'nodes-pick', type: 'circle', source: 'nodes', minzoom: 14.5, layout: { visibility: 'none' },
            paint: { 'circle-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#7a4bd1', '#ffffff'],
                     'circle-stroke-color': '#7a4bd1', 'circle-stroke-width': 1.5, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 15, 4, 18, 8] } });
        map.addLayer({ id: 'picked-line', type: 'line', source: 'picked', filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round' }, paint: { 'line-color': '#7a4bd1', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 5, 17, 12], 'line-opacity': 0.8 } }, before);
        map.addLayer({ id: 'picked-pt', type: 'circle', source: 'picked', filter: ['==', ['geometry-type'], 'Point'],
            paint: { 'circle-color': '#7a4bd1', 'circle-radius': 9, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
        hookMap();
        let sat = false;
        try { sat = localStorage.getItem('matcher.basemap') === 'satellite'; } catch { }
        setBasemap(sat);
        loadStreets();
    });
}

function setBasemap(sat) {
    if (map.getLayer('satellite')) map.setLayoutProperty('satellite', 'visibility', sat ? 'visible' : 'none');
    document.querySelectorAll('.basemap-switch button').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.b === 'sat') === sat)));
    try { localStorage.setItem('matcher.basemap', sat ? 'satellite' : 'map'); } catch { }
}

// Creek fix (same as Block Party, Selecter and Joiner): Protomaps tags many Bay Area creeks as rivers,
// including culverted ones underground. Hide streams, and rivers or labels named "Creek" or "Arroyo".
function fixCreeks() {
    try {
        if (map.getLayer('water_stream')) map.setLayoutProperty('water_stream', 'visibility', 'none');
        if (map.getLayer('water_river')) map.setFilter('water_river', ['all',
            ['!', ['in', 'Creek', ['get', 'name']]], ['!', ['in', 'Arroyo', ['get', 'name']]]]);
        if (map.getLayer('water_waterway_label')) map.setFilter('water_waterway_label', ['all',
            ['!=', ['get', 'kind'], 'stream'], ['!', ['in', 'Creek', ['get', 'name']]], ['!', ['in', 'Arroyo', ['get', 'name']]]]);
    } catch (e) { console.warn('[creek filter]', e); }
}

// The city's blocks and intersections, for drawing a fix (same file the Python matcher reads).
async function loadStreets() {
    try {
        const raw = await (await fetch(BASE + 'data/streets.json')).json();
        const Sx = raw.strings, F = Object.fromEntries(raw.seg_fields.map((f, i) => [f, i]));
        const NF = Object.fromEntries(raw.node_fields.map((f, i) => [f, i]));
        const segs = new Map(), nodes = new Map(), feats = [], nfeats = [], used = new Set();
        for (const r of raw.segs) {
            if (!(r[F.flags] & 1) || EXCLUDED_LAYERS.has(Sx[r[F.layer]])) continue;
            const g = r[F.geom], coords = [];
            let x = 0, y = 0;
            for (let i = 0; i < g.length; i += 2) {
                if (i === 0) { x = g[0]; y = g[1]; } else { x += g[i]; y += g[i + 1]; }
                coords.push([x / 1e5, y / 1e5]);
            }
            const s = { cnn: r[F.cnn], street: Sx[r[F.streetname]], f: Sx[r[F.f_st]], t: Sx[r[F.t_st]], coords };
            segs.set(s.cnn, s);
            used.add(r[F.f_node_cnn]); used.add(r[F.t_node_cnn]);
            feats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: { cnn: s.cnn, street: s.street, f: s.f, t: s.t } });
        }
        for (const n of raw.nodes) {
            const cnn = n[NF.cnn];
            if (!used.has(cnn)) continue;
            const streets = n[NF.streets].map(i => Sx[i]), xy = [n[NF.x] / 1e5, n[NF.y] / 1e5];
            nodes.set(cnn, { streets, xy });
            nfeats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: xy }, properties: { cnn, streets: streets.join(' & ') } });
        }
        S.streets = { segs, nodes };
        map.getSource('streets').setData({ type: 'FeatureCollection', features: feats });
        map.getSource('nodes').setData({ type: 'FeatureCollection', features: nfeats });
    } catch (e) {
        console.warn('[streets]', e);
    }
}

function hookMap() {
    const hoverable = ['results-line', 'results-pt', 'polys-fill'];
    map.on('mousemove', e => {
        if (S.pick) return pickHover(e);
        const f = map.queryRenderedFeatures(e.point, { layers: hoverable })[0];
        map.getCanvas().style.cursor = f ? 'pointer' : '';
        if (!f) return popup.remove();
        const r = S.results.find(x => x.key === f.properties.key);
        if (!r && S.kind === 'polygons') {
            const p = S.polys.find(x => `p${x.index}` === f.properties.key);
            if (!p) return popup.remove();
            return popup.setLngLat(e.lngLat).setHTML(`<div class="pop-title">${esc(polyName(p) || `Polygon ${p.index + 1}`)}</div>
                <div class="pop-sub">${fmtArea(areaM2(p.feature.geometry))} · click to ${S.prepSel.has(p.index) ? 'unselect' : 'select'}</div>`).addTo(map);
        }
        if (!r) return popup.remove();
        popup.setLngLat(e.lngLat).setHTML(popupHtml(r)).addTo(map);
    });
    map.on('mouseout', () => popup.remove());
    map.on('click', e => {
        if (S.pick) return pickClick(e);
        const f = map.queryRenderedFeatures(e.point, { layers: hoverable })[0];
        if (f && S.kind === 'polygons' && !S.results.length) return togglePrep(Number(f.properties.key.slice(1)));
        if (f) select(f.properties.key, { fly: false, scroll: true });
    });
}

function popupHtml(r) {
    if (S.kind === 'polygons') {
        const p = r.feature.properties;
        return `<div class="pop-title">${esc(r.name || `Polygon ${r.index + 1}`)}</div>
            <div class="pop-sub">${esc(p.cnn_shape)} · ${p.block_cnns.length} blocks, ${p.partial_cnns.length} partly inside, ${p.intersection_cnns.length} intersections</div>`;
    }
    const o = r.out;
    const where = o.type === 'intersection' ? `${o.street} & ${o.from_street}` : [o.street, o.from_street && o.to_street ? `${o.from_street} to ${o.to_street}` : ''].filter(Boolean).join(', ');
    return `<div class="pop-title">${esc(describe(S.rows[r.src]))}</div>
        <div class="pop-sub">${esc(where || 'no match')} · ${esc(label(r))}</div>`;
}

// ------------------------------------------------------------------ WKT
function parseWkt(w) {
    if (!w) return null;
    const nums = s => s.trim().split(/\s*,\s*/).map(p => p.split(/\s+/).map(Number));
    let m;
    if ((m = /^POINT\s*\(([^)]*)\)/i.exec(w))) return { type: 'Point', coordinates: nums(m[1])[0] };
    if ((m = /^MULTIPOINT\s*\((.*)\)\s*$/i.exec(w))) return { type: 'MultiPoint', coordinates: m[1].split(/\)\s*,\s*\(/).map(s => nums(s.replace(/[()]/g, ''))[0]) };
    if ((m = /^LINESTRING\s*\(([^)]*)\)/i.exec(w))) return { type: 'LineString', coordinates: nums(m[1]) };
    if ((m = /^MULTILINESTRING\s*\((.*)\)\s*$/i.exec(w))) return { type: 'MultiLineString', coordinates: m[1].split(/\)\s*,\s*\(/).map(s => nums(s.replace(/[()]/g, ''))) };
    return null;
}
// MapLibre filters on geometry-type see Multi* as their single type, but splitting keeps hover simple.
function* parts(g) {
    if (!g) return;
    if (g.type === 'MultiPoint') for (const c of g.coordinates) yield { type: 'Point', coordinates: c };
    else if (g.type === 'MultiLineString') for (const c of g.coordinates) yield { type: 'LineString', coordinates: c };
    else yield g;
}
function extend(b, g) {
    const walk = c => typeof c[0] === 'number' ? b.extend(c) : c.forEach(walk);
    if (g) walk(g.coordinates);
    return b;
}

// ------------------------------------------------------------------ loading
const drop = $('drop');
['dragenter', 'dragover'].forEach(t => document.addEventListener(t, e => { e.preventDefault(); document.body.classList.add('dragging'); }));
['dragleave', 'drop'].forEach(t => document.addEventListener(t, e => { if (t === 'drop' || !e.relatedTarget) document.body.classList.remove('dragging'); }));
document.addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f) loadFile(f); });
$('file').addEventListener('change', e => { const f = e.target.files[0]; if (f) loadFile(f); e.target.value = ''; });
$('link-form').addEventListener('submit', e => { e.preventDefault(); const u = $('link').value.trim(); if (u) loadLink(u); });
$('paste-go').addEventListener('click', () => loadPasted($('paste').value));

const stem = name => name.replace(/\.[^.]+$/, '');

async function loadFile(file, drive = null) {
    S.drive = drive;
    const ext = (file.name.match(/\.([^.]+)$/)?.[1] || '').toLowerCase();
    toast(`Reading ${file.name}…`);
    try {
        if (ext === 'xlsx' || ext === 'xls' || ext === 'xlsm' || ext === 'ods') {
            const wb = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true });
            useWorkbook(wb, stem(file.name), ext);
        } else {
            const text = await file.text();
            if (ext === 'geojson' || ext === 'json' || /^\s*[{[]/.test(text)) useJson(JSON.parse(text), stem(file.name), ext);
            else useCsv(text, stem(file.name), ext);
        }
    } catch (e) {
        done(`Couldn't read ${file.name}: ${e.message}`, 8000);
    }
}

// Google Drive: Google's picker, then a Google Sheet (every tab) or a file in Drive. google-drive.js does
// the signing in and reading; the settings for each site are in google.json.
const DRIVE_TYPES = ['application/vnd.google-apps.spreadsheet', 'text/csv', 'text/tab-separated-values', 'text/plain',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel',
    'application/geo+json', 'application/json', 'application/vnd.geo+json'];
$('drive').addEventListener('click', async () => {
    try {
        if (!GoogleDrive.ready && !(await GoogleDrive.config('google.json')))
            return done("Google Drive isn't set up for this site yet. The steps are in matcher/README.md.", 8000);
        toast('Opening Google Drive…');
        const doc = await GoogleDrive.pick(DRIVE_TYPES);
        if (!doc) return done('No file picked.', 2500);
        toast(`Reading ${doc.name} from Google Drive…`);
        const got = await GoogleDrive.read(doc);
        const drive = { id: got.id, name: got.name, kind: got.kind };
        if (got.kind === 'file') return loadFile(got.file, drive);
        // a Google Sheet: each tab becomes a sheet, so the Sheet menu and column guessing work as for Excel
        const wb = XLSX.utils.book_new(), used = new Set(), tabOf = {};
        for (const t of got.tabs) {
            let n = t.title.replace(/[\\/?*[\]:]/g, ' ').slice(0, 31) || 'Sheet', k = 2;
            while (used.has(n.toLowerCase())) n = `${n.slice(0, 28)} ${k++}`;
            used.add(n.toLowerCase());
            tabOf[n] = { title: t.title, sheetId: t.sheetId };
            XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(t.values.length ? t.values : [['']]), n);
        }
        S.drive = { ...drive, tabs: got.tabs.map(t => ({ title: t.title, sheetId: t.sheetId })), tabOf };
        useWorkbook(wb, got.name, 'gsheet');
    } catch (e) {
        done(`Google Drive: ${e.message}.`, 8000);
    }
});

// Google Sheets and DataSF links become their CSV exports; anything else is fetched as is.
function linkUrl(u) {
    let m;
    if ((m = /docs\.google\.com\/spreadsheets\/d\/([\w-]+)/.exec(u))) {
        const gid = /[#&?]gid=(\d+)/.exec(u)?.[1];
        return { url: `https://docs.google.com/spreadsheets/d/${m[1]}/export?format=csv${gid ? `&gid=${gid}` : ''}`, name: 'google-sheet' };
    }
    if ((m = /^https?:\/\/([\w.-]+)\/(?:.*\/)?([a-z0-9]{4}-[a-z0-9]{4})(?:\/|\.(json|csv|geojson)|\?|$)/i.exec(u)) && /data\.|socrata|opendata/i.test(m[1])) {
        const kind = m[3] === 'geojson' ? 'geojson' : 'csv';
        return { url: `https://${m[1]}/resource/${m[2]}.${kind}?$limit=100000`, name: `${m[1].split('.')[0].replace(/^data$/, 'datasf')}-${m[2]}` };
    }
    return { url: u, name: decodeURIComponent(new URL(u).pathname.split('/').pop() || 'link') };
}

async function loadLink(u) {
    S.drive = null;
    let target;
    try { target = linkUrl(u); } catch { return done("That doesn't look like a link.", 5000); }
    toast(`Loading ${target.name}…`);
    try {
        const r = await fetch(target.url);
        if (!r.ok) throw new Error(`the site answered ${r.status}${r.status === 401 || r.status === 403 ? ' (is it shared publicly?)' : ''}`);
        const type = r.headers.get('content-type') || '';
        const ext = (target.url.match(/\.(\w+)(?:\?|$)/)?.[1] || '').toLowerCase();
        if (/sheet|excel|officedocument/.test(type) || ['xlsx', 'xls'].includes(ext)) {
            useWorkbook(XLSX.read(await r.arrayBuffer(), { type: 'array', cellDates: true }), stem(target.name), 'xlsx');
            return;
        }
        const text = await r.text();
        if (/json/.test(type) || /^\s*[{[]/.test(text)) useJson(JSON.parse(text), stem(target.name), 'geojson');
        else useCsv(text, stem(target.name), 'csv');
    } catch (e) {
        done(`Couldn't load that link: ${e.message === 'Failed to fetch' ? "the site doesn't allow loading from other pages" : e.message}.`, 9000);
    }
}

function loadPasted(text) {
    S.drive = null;
    text = text.trim();
    if (!text) return;
    const first = text.split('\n')[0];
    if (/\t|,/.test(first) && text.includes('\n') && !/\b(between|and|&)\b/i.test(first.split(/[\t,]/)[0])) useCsv(text, 'pasted', 'csv');
    else useRows(['location'], text.split('\n').map(l => l.trim()).filter(Boolean).map(l => ({ location: l })), 'pasted', 'csv');
}

function useCsv(text, name, ext) {
    const p = Papa.parse(text.replace(/^﻿/, ''), { header: true, skipEmptyLines: 'greedy', transformHeader: h => h.trim() });
    if (!p.meta.fields?.length) throw new Error('no header row');
    useRows(p.meta.fields, p.data, name, ext);
}

function useWorkbook(wb, name, ext) {
    S.workbook = wb;
    const names = wb.SheetNames;
    $('sheet').innerHTML = names.map(n => `<option>${esc(n)}</option>`).join('');
    $('sheet-field').hidden = names.length < 2;
    $('sheet').onchange = () => useSheet($('sheet').value, name, ext);
    // start on the sheet with the most rows (a workbook often opens on a notes or summary sheet)
    const size = n => { const r = wb.Sheets[n]['!ref']; return r ? XLSX.utils.decode_range(r).e.r : -1; };
    const first = names.reduce((a, b) => size(b) > size(a) ? b : a, names[0]);
    $('sheet').value = first;
    useSheet(first, name, ext);
}

function useSheet(sheet, name, ext) {
    const ws = S.workbook.Sheets[sheet];
    // blank rows are kept here so row numbers match the sheet's (Save to Google Sheet needs them)
    const grid = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false, blankrows: true });
    const top = headerRow(grid);
    if (top < 0) throw new Error(`sheet "${sheet}" is empty`);
    const headers = dedupe(grid[top].map((h, i) => String(h).trim() || `column ${i + 1}`));
    const rows = grid.slice(top + 1).filter(r => r.some(c => String(c).trim())).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i] == null ? '' : String(r[i])])));
    const keep = S.workbook;
    useRows(headers, rows, name, ext);
    S.workbook = keep;
    S.sheet = { name: sheet, headerRow: top + (ws['!ref'] ? XLSX.utils.decode_range(ws['!ref']).s.r : 0) };
    $('sheet-field').hidden = keep.SheetNames.length < 2;
}
// The header is the first row about as wide as the table, so a title or note in the top rows
// ("Traffic intersections, 2026") isn't taken for the header.
function headerRow(grid) {
    const filled = r => r.filter(c => String(c).trim()).length;
    const widest = Math.max(0, ...grid.slice(0, 30).map(filled));
    if (!widest) return -1;
    return grid.findIndex(r => filled(r) >= Math.max(1, Math.ceil(widest * 0.6)));
}
const dedupe = hs => { const seen = {}; return hs.map(h => (seen[h] = (seen[h] || 0) + 1) > 1 ? `${h} ${seen[h]}` : h); };

function useJson(j, name, ext) {
    const feats = j.type === 'FeatureCollection' ? j.features : j.type === 'Feature' ? [j] : null;
    if (feats) {
        const polys = feats.filter(f => /Polygon$/.test(f.geometry?.type || ''));
        if (polys.length) return usePolygons(feats, name, ext);
        const headers = [...new Set(feats.flatMap(f => Object.keys(f.properties || {})))];
        return useRows(headers, feats.map(f => Object.fromEntries(headers.map(h => [h, f.properties?.[h] ?? '']))), name, ext);
    }
    if (Array.isArray(j) && j.length && typeof j[0] === 'object') {
        const headers = [...new Set(j.flatMap(o => Object.keys(o)))].filter(h => !h.startsWith(':@'));
        return useRows(headers, j.map(o => Object.fromEntries(headers.map(h => [h, typeof o[h] === 'object' && o[h] ? JSON.stringify(o[h]) : (o[h] ?? '')]))), name, ext);
    }
    throw new Error('no rows or polygons in this JSON');
}

function reset() {
    S.results = []; S.selected = null; S.filter = 'all'; S.query = ''; $('search').value = '';
    $('sheet-field').hidden = true;
    S.polys = []; S.prepSel = new Set(); $('poly-back').hidden = true;
    endPick(); $('card-results').hidden = true; $('drawer').hidden = true;
    if (map?.getSource('results')) { map.getSource('results').setData(empty()); map.getSource('polys').setData(empty()); }
}

// After a file loads, the Load card shrinks to one line (the file, Load another, Start over).
function loaded(name) {
    $('loaded-name').textContent = name;
    $('loaded-file').hidden = false;
    $('load-inputs').hidden = true;
}
$('load-another').addEventListener('click', () => { $('load-inputs').hidden = false; reveal($('card-load')); });
$('start-over').addEventListener('click', startOver);
function startOver() {
    reset();
    Object.assign(S, { kind: null, name: '', ext: '', headers: [], rows: [], features: [], workbook: null, drive: null });
    ['card-match', 'card-results', 'drawer', 'loaded-file'].forEach(id => { $(id).hidden = true; });
    $('load-inputs').hidden = false;
    $('link').value = ''; $('paste').value = '';
    if (map?.getSource('polys')) {
        ['results', 'polys', 'picked'].forEach(id => map.getSource(id).setData(empty()));
        map.fitBounds(HOME, { padding: 20, duration: 500 });
    }
    $('toast').hidden = true;
    document.querySelector('.side').scrollTop = 0;
}
// Scroll the sidebar so a card that just changed is in view down to its last button.
function reveal(el) {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    requestAnimationFrame(() => el.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' }));
}

function useRows(headers, rows, name, ext) {
    reset();
    Object.assign(S, { kind: 'rows', headers, rows: rows.map(r => Object.fromEntries(headers.map(h => [h, r[h] == null ? '' : String(r[h])]))), features: [], name, ext });
    if (!['xlsx', 'xls', 'xlsm', 'ods', 'gsheet'].includes(ext)) S.workbook = null;
    $('text-opts').hidden = false; $('poly-opts').hidden = true;
    $('loaded').innerHTML = `${esc(name)} <span>· ${fmt(rows.length)} rows, ${headers.length} columns</span>`;
    S.colInfo = columnInfo(headers, S.rows);
    const opts = ['', ...headers].map(h => `<option value="${esc(h)}">${esc(h || '(none)')}</option>`).join('');
    for (const id of ['col-text', 'col-street', 'col-cross', 'col-cross2']) $(id).innerHTML = opts;
    const g = guessColumns(headers, S.rows);
    $('col-text').value = g.text || headers[0];
    $('col-street').value = g.street || ''; $('col-cross').value = g.cross || ''; $('col-cross2').value = g.cross2 || '';
    document.querySelector(`input[name=mode][value=${g.street && g.cross ? 'columns' : 'column'}]`).checked = true;
    S.picked = false;
    $('suggest').textContent = 'Looking through the columns…';
    showMode();
    $('card-match').hidden = false;
    loaded(`${name}${S.drive ? ' (Google Drive)' : ''}`);
    reveal($('card-match'));
    done(`Loaded ${fmt(rows.length)} rows from ${name}. Check the columns, then Match.`);
    suggest(S.rows);
}

// Ask the matcher which columns hold street names or locations (match_blocks.suggest_columns), then
// label each column with what's in it and switch to the suggestion unless the columns were already picked.
async function suggest(rows) {
    try {
        await engine;
        const g = await ask('suggest', { rows: rows.slice(0, 80), columns: S.headers });
        if (rows !== S.rows) return;                       // another file was loaded meanwhile
        const pct = x => `${Math.round(x * 100)}%`;
        const note = h => { const r = g.report[h]; if (!r?.filled) return '';
            return r.street >= 0.3 ? ` · street names ${pct(r.street)}` : r.place >= 0.2 ? ` · locations ${pct(r.place)}` : r.pair >= 0.3 ? ` · two streets ${pct(r.pair)}` : ''; };
        for (const h of S.headers) if (S.colInfo[h]) S.colInfo[h].note = note(h).replace(/^ · /, '');
        for (const id of ['col-text', 'col-street', 'col-cross', 'col-cross2'])
            for (const o of $(id).options) if (o.value) o.textContent = o.value + note(o.value);
        refreshPickers();
        if (!S.picked) {
            if (g.mode === 'columns') {
                $('col-street').value = g.street; $('col-cross').value = g.cross; $('col-cross2').value = g.cross2 || '';
            }
            if (g.column) $('col-text').value = g.column;
            document.querySelector(`input[name=mode][value=${g.mode}]`).checked = true;
            showMode();
        }
        const parts = [];
        if (g.mode === 'columns') parts.push(`street names in ${q(g.street)} and ${q(g.cross)}${g.cross2 ? ` and ${q(g.cross2)}` : ''}`);
        if (g.column) parts.push(`locations in ${q(g.column)}`);
        $('suggest').textContent = parts.length ? `Looks like ${parts.join('; ')}.` : "None of the columns look like street names or locations. Pick the one to match.";
    } catch (e) {
        $('suggest').textContent = '';
        console.warn('[suggest]', e);
    }
}
const q = s => `“${s}”`;

function usePolygons(feats, name, ext) {
    reset();
    const headers = [...new Set(feats.flatMap(f => Object.keys(f.properties || {})))];
    Object.assign(S, { kind: 'polygons', headers, rows: [], features: feats, name, ext, workbook: null });
    S.polys = feats.map((feature, index) => ({ index, feature, removed: false, only: false })).filter(p => /Polygon$/.test(p.feature.geometry?.type || ''));
    const n = S.polys.length;
    $('text-opts').hidden = true; $('poly-opts').hidden = false;
    $('loaded').innerHTML = `${esc(name)} <span>· ${fmt(n)} polygons${feats.length > n ? `, ${fmt(feats.length - n)} other features skipped` : ''}</span>`;
    S.colInfo = columnInfo(headers, feats.map(f => f.properties || {}));
    $('col-name').innerHTML = ['', ...headers].map(h => `<option value="${esc(h)}">${esc(h || '(numbered)')}</option>`).join('');
    $('col-name').value = headers.find(h => /^(name|title|label)$/i.test(h)) || headers.find(h => /name|title/i.test(h)) || '';
    refreshPickers();
    $('card-match').hidden = false;
    loaded(`${name}${S.drive ? ' (Google Drive)' : ''}`);
    reveal($('card-match'));
    const polys = polyCollection();
    map?.getSource('polys')?.setData(polys);
    const b = new maplibregl.LngLatBounds();
    polys.features.forEach(f => extend(b, f.geometry));
    if (!b.isEmpty()) map.fitBounds(b, { padding: 40, maxZoom: 16 });
    showPrep();
    done(`Loaded ${fmt(n)} polygons from ${name}. Delete any you don't need, then Match.`);
}

// ------------------------------------------------------------------ polygons before matching
const polyName = p => { const f = $('col-name').value; return f ? String(p.feature.properties?.[f] ?? '') : ''; };
$('col-name').addEventListener('change', () => { if (!S.results.length) showPrep(); });

// Rough area in square meters (equirectangular; fine for a city).
function areaM2(g) {
    const ring = r => { let a = 0; const k = Math.cos(r[0][1] * Math.PI / 180) * 111320 * 110540;
        for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] - r[i][0]) * (r[j][1] + r[i][1]); return Math.abs(a / 2) * k; };
    const poly = p => ring(p[0]) - p.slice(1).reduce((t, h) => t + ring(h), 0);
    return g.type === 'Polygon' ? poly(g.coordinates) : g.coordinates.reduce((t, p) => t + poly(p), 0);
}
const fmtArea = m2 => m2 >= 10000 ? `${(m2 / 10000).toFixed(m2 >= 1e5 ? 0 : 1)} ha` : `${fmt(Math.round(m2))} m²`;

function showPrep() {
    $('drawer').hidden = false;
    $('card-results').hidden = true;
    const live = S.polys.filter(p => !p.removed), gone = S.polys.length - live.length;
    const sel = [...S.prepSel].filter(i => live.some(p => p.index === i));
    S.prepSel = new Set(sel);
    $('chips').innerHTML = `<div class="prep-actions">
        <span class="count">${fmt(live.length)} polygons${sel.length ? `, ${fmt(sel.length)} selected` : ''}</span>
        <button type="button" class="btn small" data-prep="all">Select all</button>
        <button type="button" class="btn small" data-prep="none"${sel.length ? '' : ' disabled'}>Clear</button>
        <button type="button" class="btn small" data-prep="delete"${sel.length ? '' : ' disabled'}>Delete selected</button>
        <button type="button" class="btn small" data-prep="only"${sel.length ? '' : ' disabled'}>Keep as polygons</button>
        <button type="button" class="btn small" data-prep="match"${sel.length ? '' : ' disabled'}>Match these</button>
        ${gone ? `<button type="button" class="btn ghost small" data-prep="restore">Bring back ${fmt(gone)} deleted</button>` : ''}</div>`;
    const q = S.query;
    const rows = live.filter(p => !q || polyName(p).toLowerCase().includes(q));
    $('table').innerHTML = `<thead><tr><th></th><th>#</th><th>Polygon</th><th>Area</th><th>Will be</th></tr></thead><tbody>${rows.slice(0, SHOW).map(p => `
        <tr data-k="p${p.index}" class="${S.prepSel.has(p.index) ? 'sel' : ''}${p.only ? ' only' : ''}">
        <td class="check"><input type="checkbox" data-pick="${p.index}"${S.prepSel.has(p.index) ? ' checked' : ''} aria-label="Select polygon ${p.index + 1}"></td>
        <td class="num">${p.index + 1}</td><td class="desc">${esc(polyName(p) || `Polygon ${p.index + 1}`)}</td>
        <td class="num">${fmtArea(areaM2(p.feature.geometry))}</td>
        <td>${p.only ? 'kept as a polygon' : 'matched to blocks'}</td></tr>`).join('')}
        ${rows.length > SHOW ? `<tr class="more"><td colspan="5">Showing ${fmt(SHOW)} of ${fmt(rows.length)}. Search to find others.</td></tr>` : ''}
        ${!rows.length ? `<tr class="more"><td colspan="5">${live.length ? 'No polygons match the search.' : 'All the polygons are deleted.'}</td></tr>` : ''}</tbody>`;
    $('go').disabled = !live.length;
    $('go').textContent = live.length && live.every(p => p.only) ? 'Continue' : 'Match';
    map?.getSource('polys')?.setData(polyCollection());
}

$('chips').addEventListener('click', e => {
    const b = e.target.closest('[data-prep]');
    if (!b) return;
    const act = b.dataset.prep, live = S.polys.filter(p => !p.removed);
    if (act === 'all') live.forEach(p => S.prepSel.add(p.index));
    if (act === 'none') S.prepSel.clear();
    if (act === 'delete') { const n = S.prepSel.size; live.forEach(p => { if (S.prepSel.has(p.index)) p.removed = true; }); S.prepSel.clear(); done(`Deleted ${fmt(n)} ${n === 1 ? 'polygon' : 'polygons'}. They won't be matched or saved.`); }
    if (act === 'only' || act === 'match') { live.forEach(p => { if (S.prepSel.has(p.index)) p.only = act === 'only'; }); S.prepSel.clear(); }
    if (act === 'restore') S.polys.forEach(p => { p.removed = false; });
    showPrep();
});
function togglePrep(i) { S.prepSel.has(i) ? S.prepSel.delete(i) : S.prepSel.add(i); showPrep(); }
$('poly-back').addEventListener('click', () => { S.results = []; S.selected = null; S.filter = 'all'; endPick(); map.getSource('results').setData(empty()); showPrep(); });

// Which columns hold the location? Header names first, then what's in the cells.
function guessColumns(headers, rows) {
    const find = re => headers.find(h => re.test(h.trim()));
    const street = find(/^(street|street ?name|on ?street|main ?street|streetname)$/i);
    const cross = find(/^(cross|cross ?street|cross ?st|at ?street|intersecting ?street|from ?street|cross ?street ?1)$/i);
    const cross2 = find(/^(cross ?2|cross ?street ?2|second ?cross ?street|to ?street)$/i);
    const named = find(/^(location|address|block|where|intersection|site|place)$/i) || find(/location|address|block|intersection|where/i);
    let text = named;
    if (!text) {
        const sample = rows.slice(0, 200), score = h => sample.reduce((n, r) => n +
            (/\b(between|and|&|st|street|ave|avenue|blvd|block|corner)\b|\d+\s+[a-z]/i.test(r[h] || '') ? 1 : 0), 0);
        text = headers.map(h => [h, score(h)]).sort((a, b) => b[1] - a[1])[0]?.[0];
    }
    return { text, street, cross: street ? cross : null, cross2: street && cross ? cross2 : null };
}

document.querySelectorAll('input[name=mode]').forEach(r => r.addEventListener('change', () => { S.picked = true; showMode(); }));
['col-text', 'col-street', 'col-cross', 'col-cross2'].forEach(id => $(id).addEventListener('change', () => { S.picked = true; showMode(); }));
const mode = () => document.querySelector('input[name=mode]:checked').value;

function showMode() {
    refreshPickers();
    const m = mode();
    document.querySelectorAll('[data-mode]').forEach(el => { el.style.opacity = el.dataset.mode === m ? 1 : 0.45; });
    const ex = S.rows.slice(0, 3).map(describe).filter(Boolean);
    $('example').textContent = ex.length ? ex.map(e => `“${e}”`).join('  ') : '';
}

// ------------------------------------------------------------------ column menus
// Each column menu is a button and a list in place of the <select>, so every column can show its
// position, what the matcher thinks is in it, and a few sample values in smaller type. The hidden
// <select> keeps the value, so the rest of the page reads and sets it as before.
function columnInfo(headers, rows) {
    const info = {};
    headers.forEach((h, i) => {
        const seen = new Set();
        for (const r of rows) {
            const v = String(r[h] ?? '').trim();
            if (v && !seen.has(v)) seen.add(v.length > 40 ? v.slice(0, 39) + '…' : v);
            if (seen.size >= 4) break;
        }
        info[h] = { n: i + 1, samples: [...seen], note: '' };
    });
    return info;
}
const PICKERS = ['col-text', 'col-street', 'col-cross', 'col-cross2', 'col-name'];
let openPicker = null;
function optionHtml(o) {
    const c = S.colInfo?.[o.value];
    if (!o.value || !c) return `<span class="cp-name">${esc(o.textContent)}</span>`;
    return `<span class="cp-name"><span class="cp-num">${c.n}</span>${esc(o.value)}${c.note ? ` <span class="cp-note">${esc(c.note)}</span>` : ''}</span>`
        + `<span class="cp-samples">${c.samples.length ? c.samples.map(esc).join(' · ') : 'empty'}</span>`;
}
function makePicker(sel) {
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'cpick'; btn.id = `${sel.id}-pick`;
    btn.setAttribute('aria-haspopup', 'listbox'); btn.setAttribute('aria-expanded', 'false');
    sel.before(btn); sel.hidden = true; sel.tabIndex = -1;
    btn.addEventListener('click', () => openPicker?.sel === sel ? closePicker() : showList(sel, btn));
    btn.addEventListener('keydown', e => { if (['ArrowDown', 'ArrowUp'].includes(e.key)) { e.preventDefault(); showList(sel, btn); } });
}
function refreshPickers() {
    for (const id of PICKERS) {
        const sel = $(id), btn = $(`${id}-pick`);
        if (!btn) continue;
        const o = sel.options[sel.selectedIndex];
        btn.innerHTML = o ? optionHtml(o) : '';
        btn.title = o?.value || '';
    }
}
function showList(sel, btn) {
    closePicker();
    const ul = document.createElement('ul');
    ul.className = 'cpick-list'; ul.setAttribute('role', 'listbox'); ul.tabIndex = -1;
    ul.setAttribute('aria-label', btn.closest('label')?.firstChild?.textContent.trim() || 'Column');
    [...sel.options].forEach((o, i) => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option'); li.id = `${sel.id}-opt-${i}`; li.dataset.i = i;
        li.setAttribute('aria-selected', String(i === sel.selectedIndex));
        li.innerHTML = optionHtml(o);
        ul.appendChild(li);
    });
    document.body.appendChild(ul);
    const r = btn.getBoundingClientRect(), below = innerHeight - r.bottom - 8;
    // wider than the button, so the sample values fit
    const w = Math.min(Math.max(r.width, 440), innerWidth - 16);
    ul.style.left = `${Math.max(8, Math.min(r.left, innerWidth - w - 8))}px`; ul.style.width = `${w}px`;
    if (below >= 200 || below >= r.top) { ul.style.top = `${r.bottom + 2}px`; ul.style.maxHeight = `${Math.min(320, below)}px`; }
    else { ul.style.bottom = `${innerHeight - r.top + 2}px`; ul.style.maxHeight = `${Math.min(320, r.top - 8)}px`; }
    openPicker = { sel, btn, ul, active: Math.max(0, sel.selectedIndex) };
    btn.setAttribute('aria-expanded', 'true');
    setActive(openPicker.active);
    ul.focus();
    ul.addEventListener('click', e => { const li = e.target.closest('li'); if (li) choose(+li.dataset.i); });
    ul.addEventListener('mousemove', e => { const li = e.target.closest('li'); if (li) setActive(+li.dataset.i, false); });
    ul.addEventListener('keydown', e => {
        const n = sel.options.length, a = openPicker.active;
        if (e.key === 'ArrowDown') setActive(Math.min(n - 1, a + 1));
        else if (e.key === 'ArrowUp') setActive(Math.max(0, a - 1));
        else if (e.key === 'Home') setActive(0);
        else if (e.key === 'End') setActive(n - 1);
        else if (e.key === 'Enter' || e.key === ' ') choose(a);
        else if (e.key === 'Escape' || e.key === 'Tab') { closePicker(); if (e.key === 'Escape') btn.focus(); return; }
        else if (e.key.length === 1) {               // type to jump to a column
            const k = e.key.toLowerCase(), opts = [...sel.options];
            const j = opts.findIndex((o, i) => i > a && o.value.toLowerCase().startsWith(k));
            const at = j >= 0 ? j : opts.findIndex(o => o.value.toLowerCase().startsWith(k));
            if (at >= 0) setActive(at);
            return;
        } else return;
        e.preventDefault();
    });
}
function setActive(i, scroll = true) {
    const { ul } = openPicker;
    ul.querySelector('.active')?.classList.remove('active');
    const li = ul.children[i];
    if (!li) return;
    li.classList.add('active'); ul.setAttribute('aria-activedescendant', li.id);
    openPicker.active = i;
    if (scroll) li.scrollIntoView({ block: 'nearest' });
}
function choose(i) {
    const { sel, btn } = openPicker;
    closePicker();
    btn.focus();
    if (sel.selectedIndex === i) return;
    sel.selectedIndex = i;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    refreshPickers();
}
function closePicker() {
    if (!openPicker) return;
    openPicker.ul.remove(); openPicker.btn.setAttribute('aria-expanded', 'false');
    openPicker = null;
}
document.addEventListener('pointerdown', e => { if (openPicker && !openPicker.ul.contains(e.target) && !openPicker.btn.contains(e.target)) closePicker(); });
document.querySelector('.side').addEventListener('scroll', closePicker);
addEventListener('resize', closePicker);
PICKERS.forEach(id => makePicker($(id)));

// What the matcher reads for a row: the same rule as match_blocks.py's describer()/from_columns().
function describe(row) {
    if (!row) return '';
    if (mode() === 'column') return String(row[$('col-text').value] ?? '');
    const st = String(row[$('col-street').value] ?? '').trim(), c2col = $('col-cross2').value;
    const cross = String(row[$('col-cross').value] ?? '').trim(), cross2 = c2col ? String(row[c2col] ?? '').trim() : '';
    if (!st) return cross;
    const crosses = (cross2 ? [cross, cross2] : cross.split(/\s*(?:&|\/|,|\band\b|\bto\b)\s*/i)).filter(c => c.trim());
    if (crosses.length >= 2) return `${st} between ${crosses[0]} and ${crosses[1]}`;
    return crosses.length ? `${st} & ${crosses[0]}` : st;
}

// ------------------------------------------------------------------ matching
$('go').addEventListener('click', () => S.kind === 'polygons' ? matchPolygons() : matchRows());

async function matchRows() {
    const m = mode() === 'column' ? { column: $('col-text').value }
        : { street: $('col-street').value, cross: $('col-cross').value, cross2: $('col-cross2').value || null };
    if (m.street === '' || m.cross === '') return done('Pick both the street and cross street columns.', 5000);
    $('go').disabled = true;
    try {
        if (!S.version) toast('Starting Python… (only the first time)');
        await engine;
        S.results = []; S.selected = null;
        const n = S.rows.length, t0 = performance.now();
        for (let i = 0; i < n; i += BATCH) {
            toast(`Matching ${fmt(Math.min(i + BATCH, n))} of ${fmt(n)} rows…`, i / n);
            const outs = await ask('rows', { rows: S.rows.slice(i, i + BATCH), mode: m, start: i + 1 });
            outs.forEach((list, j) => list.forEach(out => S.results.push({ key: `r${i + j}-${out.part}`, src: i + j, out, fixed: false })));
            if (i === 0 || (i / BATCH) % 5 === 4) showResults(false);
        }
        showResults(true);
        reveal($('card-results'));
        const c = counts();
        const secs = (performance.now() - t0) / 1000;
        done(`Matched ${fmt(n)} rows in ${secs < 1 ? 'under a second' : `${secs.toFixed(1)} s`}: ${fmt(c.high)} high, ${fmt(c.medium)} medium, ${fmt(c.low)} low, ${fmt(c.none)} no match.`, 6000);
    } catch (e) {
        done(`Matching stopped: ${e.message}`, 9000);
    } finally { $('go').disabled = false; }
}

async function matchPolygons() {
    $('go').disabled = true;
    try {
        if (!S.version) toast('Starting Python… (only the first time)');
        await engine;
        S.results = []; S.selected = null; S.filter = 'all';
        const live = S.polys.filter(p => !p.removed), todo = live.filter(p => !p.only), n = todo.length, step = 10;
        const intersections = document.querySelector('input[name=ix]:checked').value === 'yes';
        const nameField = $('col-name').value;
        for (const p of live.filter(p => p.only)) S.results.push(polygonOnly(p));
        for (let i = 0; i < n; i += step) {
            toast(`Matching polygon ${fmt(Math.min(i + step, n))} of ${fmt(n)}…`, i / n);
            const batch = todo.slice(i, i + step);
            const res = await ask('polygons', { features: batch.map(p => p.feature), nameField: nameField || '__none__', intersections });
            for (const r of res) {
                const p = batch[r.index];
                r.rows.forEach(x => { x.polygon_index = p.index; });
                S.results.push({ key: `p${p.index}`, index: p.index, name: polyName(p), feature: r.feature, rows: r.rows, fixed: false, only: false });
            }
            S.results.sort((a, b) => a.index - b.index);
            showResults(false);
        }
        S.results.sort((a, b) => a.index - b.index);
        showResults(true);
        reveal($('card-results'));
        const kept = live.length - n;
        done(`Matched ${fmt(n)} ${n === 1 ? 'polygon' : 'polygons'}${kept ? `; ${fmt(kept)} kept as plain polygons` : ''}.`);
    } catch (e) {
        done(`Matching stopped: ${e.message}`, 9000);
    } finally { $('go').disabled = false; }
}

// ------------------------------------------------------------------ results: tally, chips, table, map
const POLY_STATE = { blocks: 'high', 'intersections only': 'medium', 'nearest only': 'low', 'nothing inside': 'none', 'polygon only': 'polygon' };
const label = r => r.only ? 'polygon only' : r.fixed ? 'fixed' : S.kind === 'polygons' ? polyState(r) : r.out.confidence;
const confOf = r => r.only ? 'polygon' : r.fixed ? 'manual' : S.kind === 'polygons' ? POLY_STATE[polyState(r)] : r.out.confidence;
function polyState(r) {
    if (r.only) return 'polygon only';
    const p = r.feature.properties;
    if (p.block_cnns.length || p.partial_cnns.length) return 'blocks';
    if (p.intersection_cnns.length) return 'intersections only';
    return p.nearest_cnn ? 'nearest only' : 'nothing inside';
}
function counts() {
    const c = Object.fromEntries(CONF.map(k => [k, 0]));
    for (const r of S.results) c[confOf(r)]++;
    return c;
}
const TEXT_NAMES = { high: 'High', medium: 'Medium', low: 'Low', none: 'No match', manual: 'Fixed', polygon: 'Polygon only' };
const POLY_NAMES = { high: 'Blocks', medium: 'Intersections only', low: 'Nearest block only', none: 'Nothing inside', manual: 'Fixed', polygon: 'Polygon only' };
const shown = (k, c) => !['manual', 'polygon'].includes(k) || c[k] > 0;
let NAMES = TEXT_NAMES;

function showResults(final) {
    NAMES = S.kind === 'polygons' ? POLY_NAMES : TEXT_NAMES;
    $('card-results').hidden = false;
    $('drawer').hidden = false;
    const c = counts(), total = S.results.length || 1;
    $('poly-back').hidden = S.kind !== 'polygons';
    $('tally').innerHTML = CONF.filter(k => shown(k, c)).map(k => `
        <div class="tally-row${S.kind === 'polygons' ? ' wide' : ''}" data-f="${k}"><span class="tally-label">${NAMES[k]}</span>
        <span class="tally-bar"><i style="width:${(c[k] / total * 100).toFixed(1)}%;background:${COLORS[k]}"></i></span>
        <span class="tally-n">${fmt(c[k])}</span></div>`).join('');
    $('tally').querySelectorAll('.tally-row').forEach(el => el.onclick = () => setFilter(el.dataset.f));
    const look = c.medium + c.low + c.none;
    $('results-hint').textContent = S.kind === 'polygons'
        ? 'Click a polygon in the table, then Fix to add or remove blocks, or to keep it as a plain polygon.'
        : look ? `${fmt(look)} ${look === 1 ? 'location needs' : 'locations need'} a look. They're at the top of the table; Fix lets you pick the right block on the map.`
            : 'Everything matched with high confidence.';
    drawChips(c);
    drawTable();
    drawMap(final);
    findSpelling();
    $('save-gsheet').hidden = S.drive?.kind !== 'sheet' || S.kind !== 'rows';
}

function drawChips(c) {
    const list = [['all', 'All', S.results.length], ['look', 'Needs a look', c.medium + c.low + c.none], ...CONF.filter(k => shown(k, c)).map(k => [k, NAMES[k], c[k]])];
    $('chips').innerHTML = list.map(([k, n, v]) => `<button type="button" class="chip${S.filter === k ? ' on' : ''}" data-f="${k}">${n}<b>${fmt(v)}</b></button>`).join('');
    $('chips').querySelectorAll('.chip').forEach(el => el.onclick = () => setFilter(el.dataset.f));
}
function setFilter(f) { S.filter = f; drawChips(counts()); drawTable(); }
try { S.showCols = localStorage.getItem('matcher.cols') !== 'off'; } catch { }
$('show-cols').checked = S.showCols;
$('show-cols').addEventListener('change', e => { S.showCols = e.target.checked; try { localStorage.setItem('matcher.cols', S.showCols ? 'on' : 'off'); } catch { } drawTable(); });
$('search').addEventListener('input', e => { S.query = e.target.value.trim().toLowerCase(); S.kind === 'polygons' && !S.results.length ? showPrep() : drawTable(); });
$('drawer-toggle').addEventListener('click', () => {
    const c = $('drawer').classList.toggle('collapsed');
    $('drawer-toggle').textContent = c ? 'Show table' : 'Hide table';
    $('drawer-toggle').setAttribute('aria-expanded', String(!c));
    setTimeout(() => map.resize(), 0);
});

const ORDER = { none: 0, low: 1, medium: 2, manual: 3, high: 4, polygon: 5 };
function visible() {
    const q = S.query;
    let list = S.results.filter(r => {
        const c = confOf(r);
        if (S.filter === 'look' && !['medium', 'low', 'none'].includes(c)) return false;
        if (CONF.includes(S.filter) && c !== S.filter) return false;
        if (!q) return true;
        const hay = S.kind === 'polygons' ? `${r.name} ${r.rows.map(x => x.street).join(' ')}` : `${describe(S.rows[r.src])} ${Object.values(r.out).join(' ')}`;
        return hay.toLowerCase().includes(q);
    });
    if (S.kind === 'rows') list = list.slice().sort((a, b) => ORDER[confOf(a)] - ORDER[confOf(b)] || a.src - b.src || a.out.part - b.out.part);
    return list;
}

// The person's other columns, after Matcher's own, so there's more to go on when a match is unsure.
// The columns already shown as the description are left out. "Your columns" in the table bar hides them.
function extraCols() {
    if (!S.showCols) return [];
    if (S.kind === 'polygons') return S.headers.filter(h => h !== $('col-name').value);
    const used = mode() === 'column' ? [$('col-text').value] : [$('col-street').value, $('col-cross').value, $('col-cross2').value];
    return S.headers.filter(h => !used.includes(h));
}
const extraHead = () => extraCols().map(h => `<th class="theirs">${esc(h)}</th>`).join('');
const extraCells = row => extraCols().map(h => { const v = row?.[h] ?? ''; const t = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return `<td class="theirs" title="${esc(t)}">${esc(t.length > 80 ? t.slice(0, 79) + '…' : t)}</td>`; }).join('');

function drawTable() {
    const list = visible(), shown = list.slice(0, SHOW);
    let head, body;
    if (S.kind === 'polygons') {
        head = `<tr><th></th><th>#</th><th>Polygon</th><th>Shape</th><th>Blocks</th><th>Partly inside</th><th>Intersections</th><th>Nearest</th><th></th>${extraHead()}</tr>`;
        body = shown.map(r => {
            const p = r.feature.properties;
            return `<tr data-k="${r.key}"${S.selected === r.key ? ' class="sel"' : ''}>
                <td><span class="conf ${confOf(r)}">${esc(label(r))}</span></td><td class="num">${r.index + 1}</td>
                <td class="desc">${esc(r.name || `Polygon ${r.index + 1}`)}</td><td>${r.only ? 'not matched' : `${esc(p.cnn_shape)}, ${p.cnn_width_m} m`}</td>
                <td class="num">${p.block_cnns.length}</td><td class="num">${p.partial_cnns.length}</td><td class="num">${p.intersection_cnns.length}</td>
                <td class="mono">${esc(p.nearest_cnn ?? '')}</td><td><button type="button" class="btn small" data-fix="${r.key}">Fix</button></td>${extraCells(S.features[r.index]?.properties)}</tr>
                ${S.selected === r.key && !r.only && !S.pick ? partsRows(r) : ''}`;
        }).join('');
    } else {
        head = `<tr><th></th><th>Row</th><th>Description</th><th>Matched as</th><th>Type</th><th>CNN</th><th>Notes</th><th></th>${extraHead()}</tr>`;
        body = shown.map(r => {
            const o = r.out;
            const as = o.type === 'intersection' ? `${o.street} & ${o.from_street}` : o.street ? `${o.street}${o.from_street ? `, ${o.from_street} to ${o.to_street}` : ''}` : '';
            return `<tr data-k="${r.key}"${S.selected === r.key ? ' class="sel"' : ''}>
                <td><span class="conf ${confOf(r)}">${esc(label(r))}</span></td><td class="num">${o.source_row}${o.parts > 1 ? `.${o.part}` : ''}</td>
                <td class="desc">${esc(describe(S.rows[r.src]))}</td><td>${esc(as)}</td><td>${esc(o.type)}</td>
                <td class="mono">${esc(o.cnn.split(';').join(', '))}</td><td class="notes">${esc(o.notes)}</td>
                <td><button type="button" class="btn small" data-fix="${r.key}">Fix</button></td>${extraCells(S.rows[r.src])}</tr>`;
        }).join('');
    }
    const span = 9 + extraCols().length;
    const more = list.length > SHOW ? `<tr class="more"><td colspan="${span}">Showing ${fmt(SHOW)} of ${fmt(list.length)}. Search or pick a filter to see the others.</td></tr>` : '';
    const none = !list.length ? `<tr class="more"><td colspan="${span}">${S.results.length ? 'No rows match this filter.' : 'Matching…'}</td></tr>` : '';
    $('table').innerHTML = `<thead>${head}</thead><tbody>${body}${more}${none}</tbody>`;
}

$('table').addEventListener('click', e => {
    const box = e.target.closest('[data-pick]');
    if (box) { e.stopPropagation(); return togglePrep(Number(box.dataset.pick)); }
    if (S.kind === 'polygons' && !S.results.length) {
        const tr = e.target.closest('tr[data-k]');
        if (tr) flyToPoly(Number(tr.dataset.k.slice(1)));
        return;
    }
    const del = e.target.closest('[data-del]');
    if (del) {
        const r = S.results.find(x => x.key === S.selected);
        if (del.dataset.del === 'ix') r.rows = r.rows.filter(x => x.type !== 'intersection');
        else r.rows.splice(Number(del.dataset.del), 1);
        S.hiPart = null;
        syncPolygon(r); showResults(false); highlightPart(null);
        return;
    }
    const part = e.target.closest('tr[data-part]');
    if (part) {
        const r = S.results.find(x => x.key === S.selected), i = Number(part.dataset.part);
        S.hiPart = S.hiPart === i ? null : i;
        drawTable(); highlightPart(S.hiPart == null ? null : r.rows[i]);
        return;
    }
    const fix = e.target.closest('[data-fix]');
    if (fix) { e.stopPropagation(); return startPick(fix.dataset.fix); }
    const tr = e.target.closest('tr[data-k]');
    if (tr) select(tr.dataset.k, { fly: true });
});

function geomOf(r) {
    if (S.kind === 'polygons') return r.feature.geometry;
    return parseWkt(r.out.wkt);
}

function drawMap(fit) {
    if (!map?.getSource('results')) return;
    const feats = [];
    for (const r of S.results) {
        const conf = confOf(r), sel = r.key === S.selected;
        if (S.kind === 'polygons') {
            for (const x of r.rows) {
                if (x.type !== 'block' && x.type !== 'intersection') continue;
                const g = parseWkt(x.wkt);
                const c = x.status === 'manual' ? COLORS.manual : x.status === 'partial' ? COLORS.medium : x.status === 'nearest' ? COLORS.low : COLORS.high;
                for (const p of parts(g)) feats.push({ type: 'Feature', geometry: p, properties: { key: r.key, color: c, sel, r: 0.45 } });
            }
        } else {
            for (const p of parts(parseWkt(r.out.wkt))) feats.push({ type: 'Feature', geometry: p, properties: { key: r.key, color: COLORS[conf], sel, r: 1 } });
        }
    }
    map.getSource('results').setData({ type: 'FeatureCollection', features: feats });
    if (S.kind === 'polygons') map.getSource('polys').setData(polyCollection());
    if (fit) {
        const b = new maplibregl.LngLatBounds();
        S.results.forEach(r => extend(b, geomOf(r)));
        if (!b.isEmpty()) map.fitBounds(b, { padding: 50, maxZoom: 16, duration: 600 });
    }
}

// The polygons on the map: the matched ones, or before Match, the ones loaded from the file.
function polyCollection() {
    const list = S.results.length ? S.results.map(r => ({ key: r.key, geometry: r.feature.geometry, only: !!r.only, sel: r.key === S.selected }))
        : S.polys.filter(p => !p.removed).map(p => ({ key: `p${p.index}`, geometry: p.feature.geometry, only: p.only, sel: S.prepSel.has(p.index) || S.selected === `p${p.index}` }));
    return { type: 'FeatureCollection', features: list.map(x => ({ type: 'Feature', geometry: x.geometry, properties: { key: x.key, sel: x.sel, only: x.only } })) };
}
function flyToPoly(i) {
    const p = S.polys.find(x => x.index === i);
    if (!p) return;
    S.selected = `p${i}`;
    map.getSource('polys').setData(polyCollection());
    const b = extend(new maplibregl.LngLatBounds(), p.feature.geometry);
    if (!b.isEmpty()) map.fitBounds(b, { padding: 80, maxZoom: 17, duration: 500 });
}

// A polygon kept as is: saved with its properties and no blocks, so it can still be joined by shape later.
function polygonOnly(p) {
    const props = p.feature.properties || {};
    return { key: `p${p.index}`, index: p.index, name: polyName(p), only: true, fixed: false,
        feature: { type: 'Feature', geometry: p.feature.geometry, properties: { ...props, cnn_shape: 'polygon only', cnn_width_m: null,
            block_cnns: [], partial_cnns: [], nearest_cnn: null, intersection_cnns: [] } },
        rows: [{ polygon_index: p.index, polygon_name: polyName(p), polygon_id: props['felt:id'] || props.id || '', shape: 'polygon only', width_m: '',
            type: '', cnn: '', street: '', from_street: '', to_street: '', layer: '', inside_pct: '', near_m: '', status: 'polygon only',
            note: 'kept as a polygon; not matched', wkt: '' }] };
}

// Show one block or intersection of a polygon in the highlight color, and bring it into view.
function highlightPart(x) {
    const g = x && parseWkt(x.wkt);
    map.getSource('picked').setData(g ? { type: 'FeatureCollection', features: [...parts(g)].map(p => ({ type: 'Feature', geometry: p, properties: {} })) } : empty());
    if (g) { const b = extend(new maplibregl.LngLatBounds(), g); if (!b.isEmpty() && !map.getBounds().contains(b.getCenter())) map.easeTo({ center: b.getCenter(), duration: 400 }); }
}

function select(key, { fly = false, scroll = false } = {}) {
    if (S.hiPart != null || key !== S.selected) { S.hiPart = null; highlightPart(null); }
    S.selected = S.selected === key && !fly ? null : key;
    drawTable(); drawMap(false);
    const r = S.results.find(x => x.key === key);
    if (fly && r) {
        const b = extend(new maplibregl.LngLatBounds(), geomOf(r));
        if (!b.isEmpty()) map.fitBounds(b, { padding: 80, maxZoom: 17, duration: 500 });
    }
    if (scroll) $('table').querySelector(`tr[data-k="${key}"]`)?.scrollIntoView({ block: 'nearest' });
}

// ------------------------------------------------------------------ fixing: pick on the map
function startPick(key) {
    const r = S.results.find(x => x.key === key);
    if (!r || !S.streets) return done('The street list is still loading; try again in a moment.', 4000);
    S.selected = key;
    if (S.kind === 'polygons') {
        const blocks = r.rows.filter(x => x.type === 'block').map(x => Number(x.cnn));
        const nodes = r.rows.filter(x => x.type === 'intersection').map(x => Number(x.cnn));
        S.pick = { key, cnns: new Set(blocks), nodes: new Set(nodes) };
        $('pick-title').textContent = `Fixing ${r.name || `polygon ${r.index + 1}`}`;
        $('pick-help').textContent = 'Click blocks, or zoom in and click intersections, to add them to this polygon or take them out.';
        $('pick-change').textContent = '';
        $('pick-use').textContent = 'Done';
        $('pick-none').textContent = r.only ? 'Keep as a polygon' : 'Just a polygon';
        $('pick-none').hidden = false;
    } else {
        const o = r.out, cnns = o.cnn ? o.cnn.split(';').map(Number) : [];
        S.pick = { key, cnns: new Set(o.type === 'block' ? cnns : []), nodes: new Set(o.type === 'intersection' ? cnns : []) };
        $('pick-title').textContent = `Row ${o.source_row}: ${describe(S.rows[r.src]) || '(empty)'}`;
        $('pick-help').textContent = 'Click the right block (shift-click for more than one) or zoom in and click an intersection.';
        $('pick-change').textContent = '';
        $('pick-use').textContent = 'Use selection';
        $('pick-none').textContent = 'No match';
        $('pick-none').hidden = false;
    }
    $('pickbar').hidden = false;
    map.setLayoutProperty('streets-pick', 'visibility', 'visible');
    map.setLayoutProperty('nodes-pick', 'visibility', 'visible');
    map.setPaintProperty('results-line', 'line-opacity', ['case', ['get', 'sel'], 0.35, 0.25]);
    map.setPaintProperty('results-pt', 'circle-opacity', 0.35);
    drawPicked(); drawTable(); drawMap(false);
    const b = extend(new maplibregl.LngLatBounds(), geomOf(r));
    if (!b.isEmpty()) map.fitBounds(b, { padding: 120, maxZoom: 17, duration: 500 });
    else toast('Find the location on the map, then click it.', null, 4000);
}

function endPick() {
    S.pick = null;
    $('pickbar').hidden = true;
    if (map?.getLayer('streets-pick')) {
        map.setLayoutProperty('streets-pick', 'visibility', 'none');
        map.setLayoutProperty('nodes-pick', 'visibility', 'none');
        map.setPaintProperty('results-line', 'line-opacity', ['case', ['get', 'sel'], 1, 0.85]);
        map.setPaintProperty('results-pt', 'circle-opacity', 1);
        map.getSource('picked').setData(empty());
        setHover(null);
    }
}

function setHover(f) {
    if (hoverSeg) map.setFeatureState(hoverSeg, { hover: false });
    hoverSeg = f ? { source: f.source, id: f.id } : null;
    if (hoverSeg) map.setFeatureState(hoverSeg, { hover: true });
}
const pickAt = point => {
    const box = [[point.x - 6, point.y - 6], [point.x + 6, point.y + 6]];
    return map.queryRenderedFeatures(box, { layers: ['nodes-pick'] })[0] || map.queryRenderedFeatures(box, { layers: ['streets-pick'] })[0];
};
function pickHover(e) {
    const f = pickAt(e.point);
    setHover(f);
    map.getCanvas().style.cursor = f ? 'pointer' : '';
    if (!f) return popup.remove();
    const p = f.properties;
    popup.setLngLat(e.lngLat).setHTML(f.source === 'nodes'
        ? `<div class="pop-title">${esc(p.streets)}</div><div class="pop-sub">intersection ${p.cnn}</div>`
        : `<div class="pop-title">${esc(p.street)}</div><div class="pop-sub">${esc(p.f)} to ${esc(p.t)} · block ${p.cnn}</div>`).addTo(map);
}
function pickClick(e) {
    const f = pickAt(e.point);
    if (!f) return;
    const P = S.pick, cnn = Number(f.properties.cnn), multi = e.originalEvent.shiftKey || S.kind === 'polygons';
    if (S.kind === 'polygons') {          // polygons: blocks and intersections toggle independently
        const set = f.source === 'nodes' ? P.nodes : P.cnns;
        set.has(cnn) ? set.delete(cnn) : set.add(cnn);
        return drawPicked();
    }
    if (f.source === 'nodes') {
        P.cnns.clear();
        if (!multi) P.nodes.clear();
        P.nodes.has(cnn) ? P.nodes.delete(cnn) : P.nodes.add(cnn);
    } else {
        P.nodes.clear();
        if (!multi) { const had = P.cnns.has(cnn) && P.cnns.size === 1; P.cnns.clear(); if (had) return drawPicked(); }
        P.cnns.has(cnn) ? P.cnns.delete(cnn) : P.cnns.add(cnn);
    }
    drawPicked();
}
function drawPicked() {
    const P = S.pick, feats = [];
    for (const c of P.cnns) { const s = S.streets.segs.get(c); if (s) feats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: s.coords }, properties: {} }); }
    for (const c of P.nodes) { const n = S.streets.nodes.get(c); if (n) feats.push({ type: 'Feature', geometry: { type: 'Point', coordinates: n.xy }, properties: {} }); }
    map.getSource('picked').setData({ type: 'FeatureCollection', features: feats });
    const n = P.cnns.size + P.nodes.size;
    $('pick-use').disabled = S.kind !== 'polygons' && !n;
    if (S.kind !== 'polygons') $('pick-change').textContent = n ? `Change to ${pickedText(P)}` : '';
}
// "CNN 22091000, Cayuga Ave and Mount Vernon Ave" / "CNN 9087000, Mission St from 1st St to Fremont St"
const nice = name => String(name || '').toLowerCase().replace(/\b0+(\d)/g, '$1').replace(/\b([a-z])/g, c => c.toUpperCase()).replace(/\b(\d+)(St|Nd|Rd|Th)\b/g, (m, d, x) => d + x.toLowerCase());
function pickedText(P) {
    const parts = [];
    for (const c of P.nodes) { const x = S.streets.nodes.get(c); parts.push(`CNN ${c}, ${x ? x.streets.map(nice).join(' and ') : 'intersection'}`); }
    for (const c of P.cnns) { const x = S.streets.segs.get(c); parts.push(`CNN ${c}, ${x ? `${nice(x.street)} from ${nice(x.f)} to ${nice(x.t)}` : 'block'}`); }
    return parts.length > 3 ? `${parts.length} blocks: ${parts.slice(0, 3).join('; ')}; …` : parts.join('; ');
}
$('pick-cancel').addEventListener('click', () => { endPick(); drawMap(false); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.pick) { endPick(); drawMap(false); } });

$('pick-use').addEventListener('click', async () => {
    const P = S.pick, r = S.results.find(x => x.key === P.key);
    if (S.kind === 'polygons') applyPolygonFix(r, P);
    else {
        try {
            const fields = await ask('manual', { cnns: [...P.cnns], nodes: [...P.nodes], text: describe(S.rows[r.src]) });
            r.out = { ...r.out, ...fields, matched_text: r.out.matched_text || fields.matched_text };
            r.fixed = true;
        } catch (e) { return done(`Couldn't use that: ${e.message}`, 6000); }
    }
    endPick();
    showResults(false);
    done(S.kind === 'polygons' ? 'Polygon updated.' : `Row ${r.out.source_row} fixed.`);
});
$('pick-none').addEventListener('click', () => {
    const r = S.results.find(x => x.key === S.pick.key);
    if (S.kind === 'polygons') {
        const p = S.polys.find(x => x.index === r.index);
        Object.assign(r, polygonOnly(p));
        p.only = true;
        endPick(); showResults(false);
        return done(`${r.name || `Polygon ${r.index + 1}`} kept as a plain polygon.`);
    }
    Object.assign(r.out, { type: '', cnn: '', nearby_cnns: '', street: '', from_street: '', to_street: '', address_low: '', address_high: '',
        address_ranges: '', supervisor_district: '', nhood: '', wkt: '', confidence: 'none', method: 'manual', notes: 'marked as no match' });
    r.fixed = true;
    endPick(); showResults(false);
    done(`Row ${r.out.source_row} marked as no match.`);
});

// Polygons: blocks picked by hand are added with status "manual"; blocks taken out are dropped.
function applyPolygonFix(r, P) {
    if (r.only) {          // matching a polygon that was kept as is
        r.only = false; r.rows = [];
        Object.assign(r.feature.properties, { cnn_shape: 'manual', cnn_width_m: null });
        const p = S.polys.find(x => x.index === r.index); if (p) p.only = false;
    }
    const had = t => new Set(r.rows.filter(x => x.type === t).map(x => Number(x.cnn)));
    const beforeB = had('block'), beforeN = had('intersection');
    const base = { polygon_index: r.index, polygon_name: r.name, polygon_id: r.rows[0]?.polygon_id ?? (r.feature.properties.id || ''),
        shape: r.feature.properties.cnn_shape, width_m: r.feature.properties.cnn_width_m };
    r.rows = r.rows.filter(x => (x.type === 'block' ? P.cnns : P.nodes).has(Number(x.cnn)));
    for (const c of P.cnns) {
        if (beforeB.has(c)) continue;
        const s = S.streets.segs.get(c);
        r.rows.push({ ...base, type: 'block', cnn: c, street: s.street, from_street: s.f, to_street: s.t, layer: '', inside_pct: '', near_m: '',
            status: 'manual', note: 'picked on the map', wkt: `LINESTRING (${s.coords.map(([x, y]) => `${x.toFixed(6)} ${y.toFixed(6)}`).join(', ')})` });
    }
    for (const c of P.nodes) {
        if (beforeN.has(c)) continue;
        const n = S.streets.nodes.get(c);
        r.rows.push({ ...base, type: 'intersection', cnn: c, street: n.streets[0] || '', from_street: n.streets.slice(1).join(' & '), to_street: '', layer: '',
            inside_pct: '', near_m: '', status: 'manual', note: 'picked on the map', wkt: `POINT (${n.xy[0].toFixed(6)} ${n.xy[1].toFixed(6)})` });
    }
    syncPolygon(r);
}

// After blocks or intersections change by hand: keep the rows in the script's order and the feature's lists in step.
function syncPolygon(r) {
    r.rows.sort((a, b) => (a.type !== 'block') - (b.type !== 'block') || String(a.street).localeCompare(b.street) || a.cnn - b.cnn);
    const p = r.feature.properties, blocks = r.rows.filter(x => x.type === 'block');
    p.block_cnns = blocks.filter(x => x.status === 'full' || x.status === 'manual').map(x => Number(x.cnn));
    p.partial_cnns = blocks.filter(x => x.status === 'partial').map(x => Number(x.cnn));
    p.nearest_cnn = blocks.find(x => x.status === 'nearest')?.cnn ?? null;
    p.intersection_cnns = r.rows.filter(x => x.type === 'intersection').map(x => Number(x.cnn));
    r.fixed = true;
}

// The selected polygon's blocks and intersections, listed under its row, each with Remove.
function partsRows(r) {
    const nb = r.rows.filter(x => x.type === 'block').length, ni = r.rows.filter(x => x.type === 'intersection').length;
    const list = r.rows.map((x, i) => !x.type ? '' : `<tr data-part="${i}"${S.hiPart === i ? ' class="hi"' : ''}>
        <td>${x.type}</td><td>${esc(x.street)}</td><td>${esc(x.type === 'block' ? `${x.from_street} to ${x.to_street}` : x.from_street)}</td>
        <td class="mono">${x.cnn}</td><td>${esc(x.status)}${x.inside_pct !== '' && x.inside_pct != null && x.type === 'block' ? `, ${x.inside_pct}% inside` : ''}</td>
        <td class="x"><button type="button" class="btn small" data-del="${i}">Remove</button></td></tr>`).join('');
    return `<tr class="detail"><td colspan="9"><div class="parts-head">${fmt(nb)} ${nb === 1 ? 'block' : 'blocks'}, ${fmt(ni)} ${ni === 1 ? 'intersection' : 'intersections'}
        ${ni ? `<button type="button" class="btn small" data-del="ix">Remove all intersections</button>` : ''}</div>
        ${r.rows.some(x => x.type) ? `<table class="parts"><tbody>${list}</tbody></table>` : ''}</td></tr>`;
}

// ------------------------------------------------------------------ saving
function download(name, blob) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
// The same rows match_blocks.py / match_polygons.py would write, in the input's order, with fixes applied
// (and spelling fixed in the person's own columns, if they asked for that).
function outputRows() {
    if (S.kind === 'polygons') return { fields: POLY_FIELDS, rows: S.results.flatMap(r => r.rows) };
    const fields = [...S.headers, ...OUT_FIELDS.filter(f => !S.headers.includes(f))];
    const rows = S.results.slice().sort((a, b) => a.src - b.src || a.out.part - b.out.part).map(r => ({ ...spelled(r.src), ...r.out }));
    return { fields, rows };
}

// ------------------------------------------------------------------ spelling
// When the matcher read a misspelled street ('read "mision" as "mission"'), offer to fix the spelling in
// the person's own column too: "Mision between 1st and Fremont" becomes "Mission between 1st and Fremont".
const SUFFIX_WORDS = new Set(['ST', 'AVE', 'BLVD', 'TER', 'CT', 'WAY', 'PL', 'DR', 'ALY', 'LN', 'RD', 'CIR', 'PLZ', 'HWY', 'ROW', 'WALK', 'LOOP']);
const SUFFIX_TYPED = /^(st|str|street|ave?|avenue|blvd|boulevard|ter|terrace|ct|court|way|wy|pl|place|dr|drive|aly|alley|ln|lane|rd|road|cir|circle|plz|plaza|hwy|highway|row|walk|loop)\.?$/i;
const baseOf = name => { const w = String(name).split(' '); return w.length > 1 && SUFFIX_WORDS.has(w[w.length - 1]) ? w.slice(0, -1).join(' ') : name; };
const flat = k => String(k).toLowerCase().replace(/\b0+(\d)/g, '$1').replace(/[^a-z0-9]/g, '');
const spellRe = wrong => new RegExp(`(?<![A-Za-z0-9])${wrong.match(/[a-z0-9]+/gi).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join("[\\s.'’-]*")}(?![A-Za-z0-9])`, 'i');
function findSpelling() {
    S.spell = [];
    if (S.kind !== 'rows') return;
    const cols = mode() === 'column' ? [$('col-text').value] : [$('col-street').value, $('col-cross').value, $('col-cross2').value].filter(Boolean);
    const seen = new Set();
    for (const r of S.results) {
        if (r.fixed) continue;
        const o = r.out;
        for (const m of String(o.notes || '').matchAll(/read (?:cross street )?"([^"]+)" as "([^"]+)"/g)) {
            const [, wrong, key] = m;
            if (!/[a-z]/i.test(wrong)) continue;
            const name = [o.street, o.from_street, o.to_street].find(n => n && (flat(baseOf(n)) === flat(key) || flat(n) === flat(key)));
            if (!name) continue;
            const to = nice(SUFFIX_TYPED.test(wrong.trim().split(/\s+/).pop()) ? name : baseOf(name));
            const re = spellRe(wrong);
            for (const c of cols) {
                const cell = String(S.rows[r.src][c] ?? ''), hit = cell.match(re);
                if (!hit || hit[0].toLowerCase() === to.toLowerCase() || seen.has(`${r.src}|${c}|${hit[0]}`)) continue;
                seen.add(`${r.src}|${c}|${hit[0]}`);
                S.spell.push({ src: r.src, col: c, from: hit[0], to, re });
            }
        }
    }
    const n = new Set(S.spell.map(x => x.src)).size;
    $('spell').hidden = !n;
    if (!n) return;
    $('spell-text').textContent = `Also fix the spelling in your ${S.spell.length > 1 && new Set(S.spell.map(x => x.col)).size > 1 ? 'columns' : `“${S.spell[0].col}” column`} (${fmt(n)} row${n === 1 ? '' : 's'}) when saving`;
    const pairs = {};
    for (const x of S.spell) { const k = `${x.from} → ${x.to}`; pairs[k] = (pairs[k] || 0) + 1; }
    $('spell-list').innerHTML = Object.entries(pairs).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<li>${esc(k)}${v > 1 ? ` <span>× ${v}</span>` : ''}</li>`).join('');
}
// A row with its spelling fixed, if the person asked for it.
function spelled(src) {
    const row = S.rows[src];
    if (!$('spell-on').checked || !S.spell?.length) return row;
    let out = row;
    for (const x of S.spell) if (x.src === src) { if (out === row) out = { ...row }; out[x.col] = String(out[x.col]).replace(x.re, x.to); }
    return out;
}
const spellChanges = () => $('spell-on').checked ? S.spell : [];
const suffix = () => S.kind === 'polygons' ? '_cnns' : '_matched';

$('save-csv').addEventListener('click', () => {
    const { fields, rows } = outputRows();
    download(`${S.name}${suffix()}.csv`, new Blob(['﻿' + Papa.unparse({ fields, data: rows.map(r => fields.map(f => r[f] ?? '')) })], { type: 'text/csv' }));
});
function resultsGeoJSON() {
    if (S.kind === 'polygons') return { type: 'FeatureCollection', features: S.results.map(r => r.feature) };
    const { rows } = outputRows();
    return { type: 'FeatureCollection', features: rows.map(r => { const { wkt, ...props } = r; return { type: 'Feature', geometry: parseWkt(wkt), properties: props }; }) };
}
$('save-geojson').addEventListener('click', () => {
    download(`${S.name}${suffix()}.geojson`, new Blob([JSON.stringify(resultsGeoJSON())], { type: 'application/geo+json' }));
});

// ------------------------------------------------------------------ save to Google Sheet
// The default writes a new tab: the person's columns and Matcher's, one row per location, the same rows
// as Save CSV. The other choice adds Matcher's columns to the right of the original tab, one row per row
// (several locations joined with ";"). Before that, Matcher reads the tab again and stops if its rows
// don't line up with what was loaded, so results can't land on the wrong rows.
const gsTab = () => S.drive?.tabOf?.[S.sheet?.name] || null;
const quoteTab = t => `'${t.replace(/'/g, "''")}'`;
const colLetter = n => { let s = ''; for (n++; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
const GS_COLS = [['cnn', 'Matcher: CNN'], ['type', 'Matcher: type'], ['street', 'Matcher: street'], ['from_street', 'Matcher: from'],
    ['to_street', 'Matcher: to'], ['confidence', 'Matcher: confidence'], ['notes', 'Matcher: notes']];
$('save-gsheet').addEventListener('click', () => {
    const t = gsTab();
    if (!t) return done("Couldn't tell which tab of the Sheet this came from. Load it again with Open from Google Drive.", 7000);
    $('gs-tabname').textContent = `“${(t.title + ' matched').slice(0, 100)}”`;
    $('gs-src').textContent = t.title;
    $('gs-msg').textContent = ''; $('gs-go').textContent = 'Save'; delete $('gs-go').dataset.replace;
    $('gsheet-panel').hidden = false;
    showGsWarn();
    reveal($('gsheet-panel'));
});
const showGsWarn = () => { $('gs-warn').hidden = document.querySelector('input[name=gs]:checked').value !== 'cols'; };
document.querySelectorAll('input[name=gs]').forEach(i => i.addEventListener('change', () => { showGsWarn(); $('gs-go').textContent = 'Save'; delete $('gs-go').dataset.replace; $('gs-msg').textContent = ''; }));
$('gs-cancel').addEventListener('click', () => { $('gsheet-panel').hidden = true; });
$('gs-go').addEventListener('click', async () => {
    const how = document.querySelector('input[name=gs]:checked').value, t = gsTab(), id = S.drive.id;
    const btn = $('gs-go');
    btn.disabled = true;
    try {
        await GoogleDrive.signIn();                    // first, while the click still counts, in case Google asks again
        if (how === 'tab') await saveNewTab(id, t, btn);
        else await saveColumns(id, t);
    } catch (e) {
        $('gs-msg').textContent = `Couldn't save: ${e.message}.`;
        done(`Couldn't save to the Google Sheet: ${e.message}.`, 9000);
    } finally { btn.disabled = false; }
});
async function writeRows(id, tab, values, startRow = 1, startCol = 0) {
    const CH = 2000;
    for (let i = 0; i < values.length; i += CH) {
        toast(`Saving to Google Sheets…`, Math.min(1, i / values.length));
        await GoogleDrive.putValues(id, `${quoteTab(tab)}!${colLetter(startCol)}${startRow + i}`, values.slice(i, i + CH));
    }
}
async function saveNewTab(id, t, btn) {
    const { fields, rows } = outputRows();
    const values = [fields, ...rows.map(r => fields.map(f => String(r[f] ?? '')))];
    let title = (t.title + ' matched').slice(0, 100);
    const tabs = await GoogleDrive.sheetTabs(id);
    const have = tabs.find(x => x.title === title);
    if (have && btn.dataset.replace !== title) {
        btn.dataset.replace = title; btn.textContent = `Replace “${title}”`;
        $('gs-msg').innerHTML = `This Sheet already has a tab called “${esc(title)}”. Replace it, or <button type="button" class="linkish" id="gs-new">save as a new tab</button>.`;
        $('gs-new').onclick = () => { btn.dataset.replace = 'new'; btn.click(); };
        return;
    }
    let sheetId;
    if (have && btn.dataset.replace === title) {
        sheetId = have.sheetId;
        await GoogleDrive.clearValues(id, quoteTab(title));
        await GoogleDrive.resizeTab(id, sheetId, Math.max(values.length, have.rows || 0), Math.max(fields.length, have.cols || 0));
    } else {
        if (have) { let k = 2; while (tabs.some(x => x.title === `${title} ${k}`)) k++; title = `${title} ${k}`.slice(0, 100); }
        sheetId = await GoogleDrive.addTab(id, title, values.length + 10, fields.length);
    }
    await writeRows(id, title, values);
    finishSave(id, sheetId, have && btn.dataset.replace === title ? `Replaced the tab “${title}” with ${fmt(rows.length)} rows.` : `Saved ${fmt(rows.length)} rows to the new tab “${title}”.`);
}
async function saveColumns(id, t) {
    // read the tab again and check its rows still line up with the rows Matcher loaded
    toast('Checking the Sheet before changing it…');
    const now = await GoogleDrive.getValues(id, quoteTab(t.title));
    const top = S.sheet.headerRow, head = (now[top] || []).map(h => String(h).trim());
    const used = mode() === 'column' ? [$('col-text').value] : [$('col-street').value, $('col-cross').value, $('col-cross2').value].filter(Boolean);
    const at = used.map(c => S.headers.indexOf(c));
    const body = now.slice(top + 1).filter(r => r.some(c => String(c).trim()));
    const problem = at.some(i => i < 0 || (head[i] || `column ${i + 1}`) !== S.headers[i]) ? 'its header row has changed'
        : body.length !== S.rows.length ? `it has ${fmt(body.length)} rows now and Matcher loaded ${fmt(S.rows.length)}`
        : (() => { const i = S.rows.findIndex((r, k) => at.some(j => String(body[k][j] ?? '') !== String(r[S.headers[j]] ?? ''))); return i >= 0 ? `row ${i + 1} is different from what Matcher loaded` : ''; })();
    if (problem) {
        $('gs-msg').textContent = `Nothing was changed: ${problem}. Load the Sheet again and match it, or save to a new tab.`;
        return done(`Didn't change the Sheet: ${problem}.`, 9000);
    }
    // one row per row: several locations from one row are joined with ";"
    const per = new Map();
    for (const r of S.results) { const a = per.get(r.src) || []; a.push(r.out); per.set(r.src, a); }
    const join = (outs, f) => [...new Set(outs.map(o => String(o[f] ?? '')).filter(Boolean))].join('; ');
    // reuse Matcher's columns from an earlier save; otherwise start after the last column used
    let start = head.indexOf(GS_COLS[0][1]);
    if (start < 0) start = Math.max(head.length, ...now.map(r => r.length));
    const spell = spellChanges(), fixCols = [...new Set(spell.map(x => x.col))];
    // the data rows as they sit in the tab (blank rows in between are kept as they are)
    const lines = [];
    let k = 0;
    for (let i = top + 1; i < now.length && k < S.rows.length; i++) {
        if (!now[i].some(c => String(c).trim())) continue;
        lines.push({ line: i + 1, src: k++ });
    }
    const values = [];
    const firstLine = top + 2, lastLine = lines.length ? lines[lines.length - 1].line : firstLine - 1;
    for (let line = firstLine; line <= lastLine; line++) values.push(GS_COLS.map(() => ''));
    for (const { line, src } of lines) { const outs = per.get(src) || []; values[line - firstLine] = GS_COLS.map(([f]) => join(outs, f)); }
    await GoogleDrive.resizeTab(id, t.sheetId, Math.max(lastLine, now.length, 1000), Math.max(start + GS_COLS.length, head.length));
    await writeRows(id, t.title, [GS_COLS.map(c => c[1])], top + 1, start);
    await writeRows(id, t.title, values, firstLine, start);
    // spelling, cell by cell, in the person's own columns
    for (const c of fixCols) {
        const j = S.headers.indexOf(c);
        const colVals = lines.map(({ src }) => [String(spelled(src)[c] ?? '')]);
        if (lines.length) {
            // write the whole column back only from its first to last data line, keeping blank lines blank
            const vals = [];
            for (let line = firstLine; line <= lastLine; line++) vals.push([String(now[line - 1]?.[j] ?? '')]);
            lines.forEach(({ line }, n) => { vals[line - firstLine] = colVals[n]; });
            await writeRows(id, t.title, vals, firstLine, j);
        }
    }
    // the Sheet now has the fixed spellings, so the rows Matcher holds do too (and a later save still lines up)
    if (spell.length) { for (const x of spell) S.rows[x.src] = spelled(x.src); findSpelling(); drawTable(); }
    finishSave(id, t.sheetId, `Added Matcher's columns to “${t.title}”${spell.length ? `, and fixed ${fmt(spell.length)} spelling${spell.length === 1 ? '' : 's'}` : ''}.`);
}
function finishSave(id, sheetId, msg) {
    const url = `https://docs.google.com/spreadsheets/d/${encodeURIComponent(id)}/edit#gid=${sheetId}`;
    $('gs-msg').innerHTML = `${esc(msg)} <a href="${url}" target="_blank" rel="noopener">Open it in Google Sheets</a>`;
    $('gs-go').textContent = 'Save'; delete $('gs-go').dataset.replace;
    done(msg, 6000);
}

// ------------------------------------------------------------------ open in Joiner / Block Party
// Both apps live on the same site as Matcher, so Matcher can hand Joiner the results directly: it opens
// Joiner, waits for it to start, and gives it the GeoJSON as a file, as if it had been dropped there.
// Block Party takes a list of blocks in its link (#cnn=…). ?joiner= and ?blockparty= point at other copies.
const APPS = {
    joiner: params.get('joiner') || 'https://burritojustice.github.io/joiner/',
    blockParty: params.get('blockparty') || 'https://burritojustice.github.io/block-party/',
};
const sameSite = u => { try { return new URL(u, location.href).origin === location.origin; } catch { return false; } };
$('open-joiner').addEventListener('click', () => {
    const name = `${S.name}${suffix()}.geojson`, json = JSON.stringify(resultsGeoJSON());
    const w = window.open(APPS.joiner, '_blank');
    if (!w) return done('The browser blocked the new tab. Allow pop-ups for this page, then try again.', 8000);
    if (!sameSite(APPS.joiner)) {
        download(name, new Blob([json], { type: 'application/geo+json' }));
        return done(`Saved ${name}. Drop it on Joiner to map it.`, 8000);
    }
    toast('Opening Joiner…');
    const start = Date.now();
    const tick = setInterval(() => {
        if (w.closed || Date.now() - start > 45000) {
            clearInterval(tick);
            if (!w.closed) { download(name, new Blob([json], { type: 'application/geo+json' })); done(`Joiner took too long to start. Saved ${name}; drop it on Joiner.`, 9000); }
            else done('Joiner was closed.', 3000);
            return;
        }
        let J;
        try { J = w.Joiner; } catch { return; }
        if (!J?.loadFile || !J.state?.layerId || !J.map?.isStyleLoaded?.()) return;
        clearInterval(tick);
        J.loadFile(new w.File([json], name, { type: 'application/geo+json' }));
        done(`Opened ${fmt(resultsGeoJSON().features.length)} features in Joiner.`, 4000);
    }, 250);
});
// Every matched block and intersection; Block Party takes both kinds of CNN.
function matchedCnns() {
    const cnns = new Set();
    for (const r of outputRows().rows)
        if (r.type === 'block' || r.type === 'intersection') for (const c of String(r.cnn ?? '').split(/[;,\s]+/)) if (/^\d+$/.test(c)) cnns.add(c);
    return [...cnns];
}
$('open-blockparty').addEventListener('click', () => {
    const cnns = matchedCnns();
    if (!cnns.length) return done('Nothing matched yet to show in Block Party.', 5000);
    window.open(`${APPS.blockParty}#cnn=${cnns.join(',')}`, '_blank');
    done(`Opened ${fmt(cnns.length)} location${cnns.length === 1 ? '' : 's'} in Block Party.`, 5000);
});
$('save-xlsx').addEventListener('click', () => {
    const { fields, rows } = outputRows();
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows.map(r => Object.fromEntries(fields.map(f => [f, r[f] ?? '']))), { header: fields }), 'matched');
    XLSX.writeFile(wb, `${S.name}${suffix()}.xlsx`);
});

// ------------------------------------------------------------------ test hook
window.Matcher = { state: S, engine, get map() { return map; }, version: MATCHER_VERSION, outputRows, describe };

startMap();
