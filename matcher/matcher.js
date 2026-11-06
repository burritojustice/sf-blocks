// Matcher: load a CSV, Excel sheet, GeoJSON or link; match it to San Francisco blocks with sf-blocks'
// own Python scripts (run in a worker with Pyodide); show and fix results on a map and in a table; save
// the enhanced file. Nothing leaves the browser except requests for the map and the libraries.
'use strict';
const MATCHER_VERSION = '2';
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
const CONF = ['high', 'medium', 'low', 'none', 'manual'];
const COLORS = { high: '#22814f', medium: '#c48a00', low: '#d4572a', none: '#8a93a3', manual: '#7a4bd1' };
const EXCLUDED_LAYERS = new Set(['FREEWAYS', 'PAPER', 'PAPER_FWYS', 'PAPER_WATER', 'PSEUDO', 'PRIVATE_PARKING']);

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => n.toLocaleString('en-US');

// ------------------------------------------------------------------ state
const S = {
    kind: null,          // 'rows' or 'polygons'
    name: '', ext: '',   // file name without extension, and its type
    headers: [], rows: [], features: [], workbook: null,
    results: [],         // rows: {key, src, out, fixed}; polygons: {key, index, name, feature, rows, fixed}
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
const PYODIDE_OVERRIDE = new URLSearchParams(location.search).get('pyodide');
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
            console.warn(`[matcher] Python from ${url} didn't start: ${e.message}`);
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
let map, popup, hoverSeg = null;
const empty = () => ({ type: 'FeatureCollection', features: [] });

async function startMap() {
    let region = {};
    try { region = await (await fetch(BASE + 'region.json')).json(); } catch (e) { console.warn('[region]', e); }
    const keys = region.basemap?.keys || {};
    const key = keys[location.origin] || DEFAULT_KEY;
    const bbox = region.bbox || [-122.5149, 37.7081, -122.357, 37.8324];
    map = new maplibregl.Map({ container: 'map', style: STYLE(key), bounds: [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        fitBoundsOptions: { padding: 20 }, attributionControl: { compact: true }, hash: false });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on('load', () => {
        fixCreeks();
        const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
        map.addSource('streets', { type: 'geojson', data: empty(), promoteId: 'cnn' });
        map.addSource('nodes', { type: 'geojson', data: empty(), promoteId: 'cnn' });
        map.addSource('polys', { type: 'geojson', data: empty() });
        map.addSource('results', { type: 'geojson', data: empty() });
        map.addSource('picked', { type: 'geojson', data: empty() });
        map.addLayer({ id: 'polys-fill', type: 'fill', source: 'polys', paint: { 'fill-color': '#2f5fd0', 'fill-opacity': ['case', ['get', 'sel'], 0.16, 0.06] } }, before);
        map.addLayer({ id: 'polys-line', type: 'line', source: 'polys', paint: { 'line-color': '#2f5fd0', 'line-width': ['case', ['get', 'sel'], 2.5, 1.2], 'line-opacity': 0.8 } }, before);
        map.addLayer({ id: 'streets-pick', type: 'line', source: 'streets', layout: { visibility: 'none', 'line-cap': 'round' },
            paint: { 'line-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#7a4bd1', '#9aa3b5'],
                     'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2, 17, 7], 'line-opacity': 0.55 } });
        map.addLayer({ id: 'results-line', type: 'line', source: 'results', filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 11, ['case', ['get', 'sel'], 5, 3], 17, ['case', ['get', 'sel'], 12, 8]],
                     'line-opacity': ['case', ['get', 'sel'], 1, 0.85] } });
        map.addLayer({ id: 'results-pt', type: 'circle', source: 'results', filter: ['==', ['geometry-type'], 'Point'],
            paint: { 'circle-color': ['get', 'color'], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, ['*', ['get', 'r'], ['case', ['get', 'sel'], 7, 5]], 17, ['*', ['get', 'r'], ['case', ['get', 'sel'], 13, 9]]],
                     'circle-stroke-color': '#fff', 'circle-stroke-width': ['*', ['get', 'r'], 1.5] } });
        map.addLayer({ id: 'nodes-pick', type: 'circle', source: 'nodes', minzoom: 14.5, layout: { visibility: 'none' },
            paint: { 'circle-color': ['case', ['boolean', ['feature-state', 'hover'], false], '#7a4bd1', '#ffffff'],
                     'circle-stroke-color': '#7a4bd1', 'circle-stroke-width': 1.5, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 15, 4, 18, 8] } });
        map.addLayer({ id: 'picked-line', type: 'line', source: 'picked', filter: ['==', ['geometry-type'], 'LineString'],
            layout: { 'line-cap': 'round' }, paint: { 'line-color': '#7a4bd1', 'line-width': ['interpolate', ['linear'], ['zoom'], 13, 5, 17, 12] } });
        map.addLayer({ id: 'picked-pt', type: 'circle', source: 'picked', filter: ['==', ['geometry-type'], 'Point'],
            paint: { 'circle-color': '#7a4bd1', 'circle-radius': 9, 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
        hookMap();
        loadStreets();
    });
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
        if (!r) return popup.remove();
        popup.setLngLat(e.lngLat).setHTML(popupHtml(r)).addTo(map);
    });
    map.on('mouseout', () => popup.remove());
    map.on('click', e => {
        if (S.pick) return pickClick(e);
        const f = map.queryRenderedFeatures(e.point, { layers: hoverable })[0];
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

async function loadFile(file) {
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
    const grid = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '', raw: false, blankrows: false });
    const top = grid.findIndex(r => r.filter(c => String(c).trim()).length >= 1);
    if (top < 0) throw new Error(`sheet "${sheet}" is empty`);
    const headers = dedupe(grid[top].map((h, i) => String(h).trim() || `column ${i + 1}`));
    const rows = grid.slice(top + 1).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i] == null ? '' : String(r[i])])));
    const keep = S.workbook;
    useRows(headers, rows, name, ext);
    S.workbook = keep;
    $('sheet-field').hidden = keep.SheetNames.length < 2;
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
    endPick(); $('card-results').hidden = true; $('drawer').hidden = true;
    if (map?.getSource('results')) { map.getSource('results').setData(empty()); map.getSource('polys').setData(empty()); }
}

function useRows(headers, rows, name, ext) {
    reset();
    Object.assign(S, { kind: 'rows', headers, rows: rows.map(r => Object.fromEntries(headers.map(h => [h, r[h] == null ? '' : String(r[h])]))), features: [], name, ext });
    if (!['xlsx', 'xls', 'xlsm', 'ods'].includes(ext)) S.workbook = null;
    $('text-opts').hidden = false; $('poly-opts').hidden = true;
    $('loaded').innerHTML = `${esc(name)} <span>· ${fmt(rows.length)} rows, ${headers.length} columns</span>`;
    const opts = ['', ...headers].map(h => `<option value="${esc(h)}">${esc(h || '(none)')}</option>`).join('');
    for (const id of ['col-text', 'col-street', 'col-cross', 'col-cross2']) $(id).innerHTML = opts;
    const g = guessColumns(headers, S.rows);
    $('col-text').value = g.text || headers[0];
    $('col-street').value = g.street || ''; $('col-cross').value = g.cross || ''; $('col-cross2').value = g.cross2 || '';
    document.querySelector(`input[name=mode][value=${g.street && g.cross ? 'columns' : 'column'}]`).checked = true;
    showMode();
    $('card-match').hidden = false;
    done(`Loaded ${fmt(rows.length)} rows from ${name}. Check the columns, then Match.`);
}

function usePolygons(feats, name, ext) {
    reset();
    const headers = [...new Set(feats.flatMap(f => Object.keys(f.properties || {})))];
    Object.assign(S, { kind: 'polygons', headers, rows: [], features: feats, name, ext, workbook: null });
    const n = feats.filter(f => /Polygon$/.test(f.geometry?.type || '')).length;
    $('text-opts').hidden = true; $('poly-opts').hidden = false;
    $('loaded').innerHTML = `${esc(name)} <span>· ${fmt(n)} polygons${feats.length > n ? `, ${fmt(feats.length - n)} other features skipped` : ''}</span>`;
    $('col-name').innerHTML = ['', ...headers].map(h => `<option value="${esc(h)}">${esc(h || '(numbered)')}</option>`).join('');
    $('col-name').value = headers.find(h => /^(name|title|label)$/i.test(h)) || headers.find(h => /name|title/i.test(h)) || '';
    $('card-match').hidden = false;
    const polys = { type: 'FeatureCollection', features: feats.filter(f => /Polygon$/.test(f.geometry?.type || '')).map((f, i) => ({ ...f, properties: { key: `p${feats.indexOf(f)}`, sel: false } })) };
    map?.getSource('polys')?.setData(polys);
    const b = new maplibregl.LngLatBounds();
    polys.features.forEach(f => extend(b, f.geometry));
    if (!b.isEmpty()) map.fitBounds(b, { padding: 40, maxZoom: 16 });
    done(`Loaded ${fmt(n)} polygons from ${name}. Press Match.`);
}

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

document.querySelectorAll('input[name=mode]').forEach(r => r.addEventListener('change', showMode));
['col-text', 'col-street', 'col-cross', 'col-cross2'].forEach(id => $(id).addEventListener('change', showMode));
const mode = () => document.querySelector('input[name=mode]:checked').value;

function showMode() {
    const m = mode();
    document.querySelectorAll('[data-mode]').forEach(el => { el.style.opacity = el.dataset.mode === m ? 1 : 0.45; });
    const ex = S.rows.slice(0, 3).map(describe).filter(Boolean);
    $('example').textContent = ex.length ? ex.map(e => `“${e}”`).join('  ') : '';
}

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
        S.results = []; S.selected = null;
        const all = S.features, n = all.length, nameField = $('col-name').value, step = 10;
        for (let i = 0; i < n; i += step) {
            toast(`Matching polygon ${fmt(Math.min(i + step, n))} of ${fmt(n)}…`, i / n);
            const res = await ask('polygons', { features: all.slice(i, i + step), nameField: nameField || '__none__' });
            for (const r of res) {
                const index = i + r.index;
                r.rows.forEach(x => { x.polygon_index = index; });
                const name = nameField ? String(all[index].properties?.[nameField] ?? '') : '';
                S.results.push({ key: `p${index}`, index, name, feature: r.feature, rows: r.rows, fixed: false });
            }
            showResults(false);
        }
        showResults(true);
        done(`Matched ${fmt(S.results.length)} polygons.`);
    } catch (e) {
        done(`Matching stopped: ${e.message}`, 9000);
    } finally { $('go').disabled = false; }
}

// ------------------------------------------------------------------ results: tally, chips, table, map
const POLY_STATE = { blocks: 'high', 'intersections only': 'medium', 'nearest only': 'low', 'nothing inside': 'none' };
const label = r => r.fixed ? 'fixed' : S.kind === 'polygons' ? polyState(r) : r.out.confidence;
const confOf = r => r.fixed ? 'manual' : S.kind === 'polygons' ? POLY_STATE[polyState(r)] : r.out.confidence;
function polyState(r) {
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
const TEXT_NAMES = { high: 'High', medium: 'Medium', low: 'Low', none: 'No match', manual: 'Fixed' };
const POLY_NAMES = { high: 'Blocks', medium: 'Intersections only', low: 'Nearest block only', none: 'Nothing inside', manual: 'Fixed' };
let NAMES = TEXT_NAMES;

function showResults(final) {
    NAMES = S.kind === 'polygons' ? POLY_NAMES : TEXT_NAMES;
    $('card-results').hidden = false;
    $('drawer').hidden = false;
    const c = counts(), total = S.results.length || 1;
    $('tally').innerHTML = CONF.filter(k => k !== 'manual' || c.manual).map(k => `
        <div class="tally-row${S.kind === 'polygons' ? ' wide' : ''}" data-f="${k}"><span class="tally-label">${NAMES[k]}</span>
        <span class="tally-bar"><i style="width:${(c[k] / total * 100).toFixed(1)}%;background:${COLORS[k]}"></i></span>
        <span class="tally-n">${fmt(c[k])}</span></div>`).join('');
    $('tally').querySelectorAll('.tally-row').forEach(el => el.onclick = () => setFilter(el.dataset.f));
    const look = c.medium + c.low + c.none;
    $('results-hint').textContent = S.kind === 'polygons'
        ? 'Click a polygon in the table, then Fix to add or remove blocks.'
        : look ? `${fmt(look)} ${look === 1 ? 'location needs' : 'locations need'} a look. They're at the top of the table; Fix lets you pick the right block on the map.`
            : 'Everything matched with high confidence.';
    drawChips(c);
    drawTable();
    drawMap(final);
}

function drawChips(c) {
    const list = [['all', 'All', S.results.length], ['look', 'Needs a look', c.medium + c.low + c.none], ...CONF.filter(k => k !== 'manual' || c.manual).map(k => [k, NAMES[k], c[k]])];
    $('chips').innerHTML = list.map(([k, n, v]) => `<button type="button" class="chip${S.filter === k ? ' on' : ''}" data-f="${k}">${n}<b>${fmt(v)}</b></button>`).join('');
    $('chips').querySelectorAll('.chip').forEach(el => el.onclick = () => setFilter(el.dataset.f));
}
function setFilter(f) { S.filter = f; drawChips(counts()); drawTable(); }
$('search').addEventListener('input', e => { S.query = e.target.value.trim().toLowerCase(); drawTable(); });
$('drawer-toggle').addEventListener('click', () => {
    const c = $('drawer').classList.toggle('collapsed');
    $('drawer-toggle').textContent = c ? 'Show table' : 'Hide table';
    $('drawer-toggle').setAttribute('aria-expanded', String(!c));
    setTimeout(() => map.resize(), 0);
});

const ORDER = { none: 0, low: 1, medium: 2, manual: 3, high: 4 };
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

function drawTable() {
    const list = visible(), shown = list.slice(0, SHOW);
    let head, body;
    if (S.kind === 'polygons') {
        head = '<tr><th></th><th>#</th><th>Polygon</th><th>Shape</th><th>Blocks</th><th>Partly inside</th><th>Intersections</th><th>Nearest</th><th></th></tr>';
        body = shown.map(r => {
            const p = r.feature.properties;
            return `<tr data-k="${r.key}"${S.selected === r.key ? ' class="sel"' : ''}>
                <td><span class="conf ${confOf(r)}">${esc(label(r))}</span></td><td class="num">${r.index + 1}</td>
                <td class="desc">${esc(r.name || `Polygon ${r.index + 1}`)}</td><td>${esc(p.cnn_shape)}, ${p.cnn_width_m} m</td>
                <td class="num">${p.block_cnns.length}</td><td class="num">${p.partial_cnns.length}</td><td class="num">${p.intersection_cnns.length}</td>
                <td class="mono">${esc(p.nearest_cnn ?? '')}</td><td><button type="button" class="btn small" data-fix="${r.key}">Fix</button></td></tr>`;
        }).join('');
    } else {
        head = '<tr><th></th><th>Row</th><th>Description</th><th>Matched as</th><th>Type</th><th>CNN</th><th>Notes</th><th></th></tr>';
        body = shown.map(r => {
            const o = r.out;
            const as = o.type === 'intersection' ? `${o.street} & ${o.from_street}` : o.street ? `${o.street}${o.from_street ? `, ${o.from_street} to ${o.to_street}` : ''}` : '';
            return `<tr data-k="${r.key}"${S.selected === r.key ? ' class="sel"' : ''}>
                <td><span class="conf ${confOf(r)}">${esc(label(r))}</span></td><td class="num">${o.source_row}${o.parts > 1 ? `.${o.part}` : ''}</td>
                <td class="desc">${esc(describe(S.rows[r.src]))}</td><td>${esc(as)}</td><td>${esc(o.type)}</td>
                <td class="mono">${esc(o.cnn.split(';').join(', '))}</td><td class="notes">${esc(o.notes)}</td>
                <td><button type="button" class="btn small" data-fix="${r.key}">Fix</button></td></tr>`;
        }).join('');
    }
    const more = list.length > SHOW ? `<tr class="more"><td colspan="9">Showing ${fmt(SHOW)} of ${fmt(list.length)}. Search or pick a filter to see the others.</td></tr>` : '';
    const none = !list.length ? `<tr class="more"><td colspan="9">${S.results.length ? 'No rows match this filter.' : 'Matching…'}</td></tr>` : '';
    $('table').innerHTML = `<thead>${head}</thead><tbody>${body}${more}${none}</tbody>`;
}

$('table').addEventListener('click', e => {
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
    if (S.kind === 'polygons') {
        map.getSource('polys').setData({ type: 'FeatureCollection', features: S.results.map(r => ({ type: 'Feature', geometry: r.feature.geometry, properties: { key: r.key, sel: r.key === S.selected } })) });
    }
    if (fit) {
        const b = new maplibregl.LngLatBounds();
        S.results.forEach(r => extend(b, geomOf(r)));
        if (!b.isEmpty()) map.fitBounds(b, { padding: 50, maxZoom: 16, duration: 600 });
    }
}

function select(key, { fly = false, scroll = false } = {}) {
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
        S.pick = { key, cnns: new Set(blocks), nodes: new Set() };
        $('pick-title').textContent = `Fixing ${r.name || `polygon ${r.index + 1}`}`;
        $('pick-help').textContent = 'Click blocks to add them to this polygon or take them out.';
        $('pick-use').textContent = 'Done';
        $('pick-none').hidden = true;
    } else {
        const o = r.out, cnns = o.cnn ? o.cnn.split(';').map(Number) : [];
        S.pick = { key, cnns: new Set(o.type === 'block' ? cnns : []), nodes: new Set(o.type === 'intersection' ? cnns : []) };
        $('pick-title').textContent = `Row ${o.source_row}: ${describe(S.rows[r.src]) || '(empty)'}`;
        $('pick-help').textContent = 'Click the right block (shift-click for more than one) or zoom in and click an intersection.';
        $('pick-use').textContent = 'Use selection';
        $('pick-none').hidden = false;
    }
    $('pickbar').hidden = false;
    map.setLayoutProperty('streets-pick', 'visibility', 'visible');
    map.setLayoutProperty('nodes-pick', 'visibility', 'visible');
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
    if (f.source === 'nodes') {
        if (S.kind === 'polygons') return;
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
    Object.assign(r.out, { type: '', cnn: '', nearby_cnns: '', street: '', from_street: '', to_street: '', address_low: '', address_high: '',
        address_ranges: '', supervisor_district: '', nhood: '', wkt: '', confidence: 'none', method: 'manual', notes: 'marked as no match' });
    r.fixed = true;
    endPick(); showResults(false);
    done(`Row ${r.out.source_row} marked as no match.`);
});

// Polygons: blocks picked by hand are added with status "manual"; blocks taken out are dropped.
function applyPolygonFix(r, P) {
    const before = new Set(r.rows.filter(x => x.type === 'block').map(x => Number(x.cnn)));
    const base = { polygon_index: r.index, polygon_name: r.name, polygon_id: r.rows[0]?.polygon_id ?? (r.feature.properties.id || ''),
        shape: r.feature.properties.cnn_shape, width_m: r.feature.properties.cnn_width_m };
    r.rows = r.rows.filter(x => x.type !== 'block' || P.cnns.has(Number(x.cnn)));
    for (const c of P.cnns) {
        if (before.has(c)) continue;
        const s = S.streets.segs.get(c);
        r.rows.push({ ...base, type: 'block', cnn: c, street: s.street, from_street: s.f, to_street: s.t, layer: '', inside_pct: '', near_m: '',
            status: 'manual', note: 'picked on the map', wkt: `LINESTRING (${s.coords.map(([x, y]) => `${x.toFixed(6)} ${y.toFixed(6)}`).join(', ')})` });
    }
    r.rows.sort((a, b) => (a.type !== 'block') - (b.type !== 'block') || String(a.street).localeCompare(b.street) || a.cnn - b.cnn);
    const p = r.feature.properties, blocks = r.rows.filter(x => x.type === 'block');
    p.block_cnns = blocks.filter(x => x.status === 'full' || x.status === 'manual').map(x => Number(x.cnn));
    p.partial_cnns = blocks.filter(x => x.status === 'partial').map(x => Number(x.cnn));
    p.nearest_cnn = blocks.find(x => x.status === 'nearest')?.cnn ?? null;
    r.fixed = true;
}

// ------------------------------------------------------------------ saving
function download(name, blob) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
// The same rows match_blocks.py / match_polygons.py would write, in the input's order, with fixes applied.
function outputRows() {
    if (S.kind === 'polygons') return { fields: POLY_FIELDS, rows: S.results.flatMap(r => r.rows) };
    const fields = [...S.headers, ...OUT_FIELDS.filter(f => !S.headers.includes(f))];
    const rows = S.results.slice().sort((a, b) => a.src - b.src || a.out.part - b.out.part).map(r => ({ ...S.rows[r.src], ...r.out }));
    return { fields, rows };
}
const suffix = () => S.kind === 'polygons' ? '_cnns' : '_matched';

$('save-csv').addEventListener('click', () => {
    const { fields, rows } = outputRows();
    download(`${S.name}${suffix()}.csv`, new Blob(['﻿' + Papa.unparse({ fields, data: rows.map(r => fields.map(f => r[f] ?? '')) })], { type: 'text/csv' }));
});
$('save-geojson').addEventListener('click', () => {
    let fc;
    if (S.kind === 'polygons') fc = { type: 'FeatureCollection', features: S.results.map(r => r.feature) };
    else {
        const { rows } = outputRows();
        fc = { type: 'FeatureCollection', features: rows.map(r => { const { wkt, ...props } = r; return { type: 'Feature', geometry: parseWkt(wkt), properties: props }; }) };
    }
    download(`${S.name}${suffix()}.geojson`, new Blob([JSON.stringify(fc)], { type: 'application/geo+json' }));
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
