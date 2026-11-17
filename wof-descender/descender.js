// Descender: the descendants of any Who's On First place, with their shapes, on a map; save them as
// GeoJSON or CSV with WKT. The browser twin of descender.py: for the same place and filters it writes
// the same bytes, so change FIELDS, status(), the sort and the writers in both.
'use strict';
const DESCENDER_VERSION = '2026.11.17';
const SPELUNKER = 'https://spelunker.whosonfirst.org';
const DATA = 'https://data.whosonfirst.org';
const GITHUB_RAW = 'https://raw.githubusercontent.com/whosonfirst-data';
const BASE = new URL('../', location.href).href;          // the sf-blocks site root
const STYLE = key => `https://api.protomaps.com/styles/v5/white/en.json?key=${key}`;
const DEFAULT_KEY = '071e272e8d5e13b7';                   // burritojustice.github.io (localhost accepts any key)
const FILTERS = ['country', 'iscurrent', 'isdeprecated'];
const PLACETYPES = ['planet', 'continent', 'ocean', 'empire', 'country', 'dependency', 'disputed', 'marinearea',
    'macroregion', 'region', 'macrocounty', 'county', 'localadmin', 'metroarea', 'locality',
    'borough', 'macrohood', 'neighbourhood', 'microhood', 'campus', 'building', 'address',
    'venue', 'postalregion', 'postalcode', 'intersection', 'enclosure', 'installation',
    'arcade', 'concourse', 'wing'];
const COLORS = ['#2f5fd0', '#d4572a', '#22814f', '#7a4bd1', '#c48a00', '#0f8b8d', '#b5446e', '#5b6475'];
const PAGE_WORKERS = 4, RECORD_WORKERS = 8, SHOW = 300;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => Number(n).toLocaleString('en-US');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const S = {
    spelunker: null,     // where descendant lists are read from: a proxy, the local server, or the Spelunker
    id: null, me: null,  // the place: its id and its short record (spr)
    pts: [],             // placetypes picked, in the order picked
    filters: { isdeprecated: '0' },
    facets: {},
    records: [], rows: [], cols: [], missing: [], name: '',
    selected: null, query: '',
};

// ------------------------------------------------------------------ fetching
async function get(url, json = false, tries = 4) {
    for (let i = 1; ; i++) {
        let res;
        try { res = await fetch(url); }
        catch (e) { if (i >= tries) throw e; await sleep(1000 * 2 ** i); continue; }
        if (res.ok) return json ? res.json() : res.text();
        if (res.status === 404) return null;
        if (i >= tries || ![429, 500, 502, 503, 504].includes(res.status)) throw new Error(`HTTP ${res.status} ${url}`);
        await sleep(1000 * 2 ** i);
    }
}
const wofPath = id => String(id).match(/.{1,3}/g).join('/') + `/${id}.geojson`;

function parseTarget(text) {
    text = text.trim();
    if (/^\d+$/.test(text)) return { id: Number(text), filters: null };
    let u;
    try { u = new URL(text); } catch { return null; }
    const m = u.pathname.match(/\/id\/(\d+)/) || u.pathname.match(/\/(\d+)\.geojson$/);
    if (!m) return null;
    const filters = {};
    for (const k of ['placetype', ...FILTERS]) { const v = u.searchParams.get(k); if (v) filters[k] = v; }
    return { id: Number(m[1]), filters: /\/descendants/.test(u.pathname) ? filters : null };
}

function descendantsUrl(id, query, facets = false) {
    const q = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''));
    // Python's urlencode and URLSearchParams agree for these values (letters, digits, -).
    return `${S.spelunker}/id/${id}/descendants${facets ? '/facets' : ''}` + (q.toString() ? `?${q}` : '');
}

function parsePage(text) {
    const doc = new DOMParser().parseFromString(text, 'text/html');
    const rows = [...doc.querySelectorAll('li.spr-place[data-id]')].map(li => {
        const repo = [...li.querySelectorAll('div')].map(d => d.textContent.match(/^\s*Repo\s+(\S+?)\//)).find(Boolean);
        return [Number(li.dataset.id), (li.querySelector('.wof-place-name')?.textContent || '').trim(), repo ? repo[1] : ''];
    });
    const counts = doc.querySelector('.pagination-counts')?.textContent || '';
    const total = counts.match(/There (?:are|is) ([\d,]+) place/);
    const pages = counts.match(/page [\d,]+ of ([\d,]+)/);
    return {
        total: total ? Number(total[1].replace(/,/g, '')) : rows.length,
        pages: pages ? Number(pages[1].replace(/,/g, '')) : (rows.length ? 1 : 0),
        rows,
    };
}

async function pool(items, n, fn) {
    const out = new Array(items.length);
    let next = 0;
    await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
        while (next < items.length) { const i = next++; out[i] = await fn(items[i], i); }
    }));
    return out;
}

async function walk(id, placetype, filters, onPage) {
    const query = { placetype, ...filters };
    const first = await get(descendantsUrl(id, query));
    if (first == null) throw new Error(`The Spelunker has no place ${id}`);
    const { total, pages, rows } = parsePage(first);
    onPage(1, pages, total);
    let done = 1;
    const more = await pool(Array.from({ length: Math.max(0, pages - 1) }, (_, i) => i + 2), PAGE_WORKERS, async n => {
        const r = parsePage((await get(descendantsUrl(id, { ...query, page: n }))) || '').rows;
        onPage(++done, pages, total);
        return r;
    });
    const seen = new Set(), out = [];
    for (const r of rows.concat(...more)) if (!seen.has(r[0]) && r[0] !== id) { seen.add(r[0]); out.push(r); }
    return { total, rows: out };
}

async function facetCounts(id, filters, facet) {
    const q = { ...Object.fromEntries(Object.entries(filters).filter(([k]) => k !== facet)), facet };
    const res = await get(descendantsUrl(id, q, true), true) || [];
    const out = {};
    for (const x of res) for (const r of x.results || []) out[r.key] = r.count;
    return out;
}

const spr = id => get(`${S.spelunker || SPELUNKER}/id/${id}/spr`, true);   // short records: name, placetype, bbox

async function record(id, repo) {
    let text = null;
    try { text = await get(`${DATA}/${wofPath(id)}`); } catch { }
    if (text == null && repo) text = await get(`${GITHUB_RAW}/${repo}/master/data/${wofPath(id)}`);
    return text == null ? null : JSON.parse(text);
}

// Which address answers for the Spelunker's lists: ?spelunker=, descender.py --serve's /spelunker,
// descender.json's proxy, then the Spelunker itself (which other sites can't read today).
async function findSpelunker() {
    const params = new URLSearchParams(location.search);
    let cfg = {};
    try { cfg = await (await fetch('descender.json', { cache: 'no-cache' })).json(); } catch { }
    const local = `${location.origin}/spelunker`;
    const tries = [params.get('spelunker'), local, cfg.proxy, SPELUNKER].filter(Boolean).map(s => s.replace(/\/+$/, ''));
    for (const base of tries) {
        try {
            if (base === local) {
                const r = await fetch(local + '/');
                if (!r.ok || !(await r.json()).descender) continue;
            }
            const r = await fetch(`${base}/id/85922583/descendants/facets?facet=isdeprecated`);
            if (r.ok) { await r.json(); return base; }
        } catch { }
    }
    return null;
}

// ------------------------------------------------------------------ fields (match descender.py)
const isSet = v => v !== undefined && v !== null && v !== '' && v !== 'uuuu' && v !== -1 && !(Array.isArray(v) && !v.length);
function status(p) {
    if (isSet(p['edtf:deprecated'])) return 'deprecated';
    if (isSet(p['wof:superseded_by'])) return 'superseded';
    if (isSet(p['edtf:cessation'])) return 'ceased';
    if (p['mz:is_current'] === 1) return 'current';
    if (p['mz:is_current'] === 0) return 'not current';
    return 'unverified';
}
const edtf = v => (v == null || v === '' || v === 'uuuu') ? '' : String(v);
const ymd = ts => ts ? new Date(Number(ts) * 1000).toISOString().slice(0, 10) : '';
const posInt = v => Number.isInteger(v) && v > 0;
function hierarchy(p, ancestor) {
    const hs = p['wof:hierarchy'] || [];
    return hs.find(h => Object.values(h).includes(ancestor)) || hs[0] || {};
}
const BASE_FIELDS = ['wof_id', 'name', 'placetype', 'status', 'is_current', 'country', 'parent_id', 'parent'];
const TAIL_FIELDS = ['inception', 'cessation', 'deprecated', 'superseded_by', 'lastmodified', 'src_geom',
    'lbl_latitude', 'lbl_longitude', 'area_m2', 'repo', 'spelunker', 'geojson'];

function between(records, ancestorPt, ancestor) {
    const start = PLACETYPES.indexOf(ancestorPt);
    const pts = new Set();
    for (const r of records) {
        const p = r.properties;
        const own = PLACETYPES.indexOf(p['wof:placetype']);
        const end = own < 0 ? PLACETYPES.length : own;
        for (const [k, v] of Object.entries(hierarchy(p, ancestor))) {
            const pt = k.slice(0, -3), i = PLACETYPES.indexOf(pt);
            if (i >= 0 && start < i && i < end && posInt(v)) pts.add(pt);
        }
    }
    return PLACETYPES.filter(pt => pts.has(pt));
}
const fieldsFor = levels => [...BASE_FIELDS, ...levels.flatMap(pt => [`${pt}_id`, pt]), ...TAIL_FIELDS];

function rowOf(r, ancestor, levels, names) {
    const p = r.properties, id = p['wof:id'], h = hierarchy(p, ancestor);
    const parent = posInt(p['wof:parent_id']) ? p['wof:parent_id'] : null;
    const area = p['geom:area_square_m'];
    const out = {
        wof_id: id, name: p['wof:name'] ?? '', placetype: p['wof:placetype'] ?? '',
        status: status(p), is_current: p['mz:is_current'] ?? null,
        country: p['wof:country'] || p['iso:country'] || '',
        parent_id: parent, parent: parent ? (names.get(parent) ?? '') : '',
    };
    for (const pt of levels) {
        let v = h[`${pt}_id`];
        v = posInt(v) && v !== id ? v : null;
        out[`${pt}_id`] = v;
        out[pt] = v ? (names.get(v) ?? '') : '';
    }
    const sup = p['wof:superseded_by'] ?? [];
    Object.assign(out, {
        inception: edtf(p['edtf:inception']), cessation: edtf(p['edtf:cessation']), deprecated: edtf(p['edtf:deprecated']),
        superseded_by: Array.isArray(sup) ? sup.join(';') : String(sup),
        lastmodified: ymd(p['wof:lastmodified']),
        src_geom: p['src:geom'] || '',
        lbl_latitude: ('lbl:latitude' in p ? p['lbl:latitude'] : p['geom:latitude']) ?? null,
        lbl_longitude: ('lbl:longitude' in p ? p['lbl:longitude'] : p['geom:longitude']) ?? null,
        area_m2: typeof area === 'number' && area ? Math.floor(area + 0.5) : null,
        repo: p['wof:repo'] || '',
        spelunker: `${SPELUNKER}/id/${id}/`,
        geojson: `${DATA}/${wofPath(id)}`,
    });
    return out;
}

function sortRecords(records, order) {
    const key = r => {
        const p = r.properties, i = order.indexOf(p['wof:placetype'] ?? '');
        return [i < 0 ? order.length : i, String(p['wof:name'] ?? '').toLowerCase(), p['wof:id']];
    };
    const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
    return records.map(r => [key(r), r]).sort(([a], [b]) => cmp(a[0], b[0]) || cmp(a[1], b[1]) || cmp(a[2], b[2])).map(x => x[1]);
}

// ------------------------------------------------------------------ writers (match descender.py)
const featureOf = (rec, props, all) => ({ type: 'Feature', id: props.wof_id, properties: all ? { ...rec.properties } : props, geometry: rec.geometry ?? null });
const geojsonText = (name, feats) => `{"type":"FeatureCollection","name":${JSON.stringify(name)},"features":[\n${feats.map(f => JSON.stringify(f)).join(',\n')}\n]}\n`;
function wkt(g) {
    if (!g) return '';
    const c = g.coordinates, pt = p => p.map(x => JSON.stringify(x)).join(' ');
    const ring = r => '(' + r.map(pt).join(', ') + ')', poly = rs => '(' + rs.map(ring).join(', ') + ')';
    switch (g.type) {
        case 'Point': return `POINT (${pt(c)})`;
        case 'MultiPoint': return 'MULTIPOINT (' + c.map(p => `(${pt(p)})`).join(', ') + ')';
        case 'LineString': return 'LINESTRING ' + ring(c);
        case 'MultiLineString': return 'MULTILINESTRING ' + poly(c);
        case 'Polygon': return 'POLYGON ' + poly(c);
        case 'MultiPolygon': return 'MULTIPOLYGON (' + c.map(poly).join(', ') + ')';
        case 'GeometryCollection': return 'GEOMETRYCOLLECTION (' + (g.geometries || []).map(wkt).join(', ') + ')';
        default: return '';
    }
}
function cell(v) {
    if (v == null) return '';
    const s = typeof v === 'number' ? JSON.stringify(v) : String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
const csvText = (cols, rows, geoms) => [[...cols, 'wkt'].join(','),
    ...rows.map((r, i) => [...cols.map(c => cell(r[c])), cell(wkt(geoms[i]))].join(','))].join('\n') + '\n';

// ------------------------------------------------------------------ descend
async function descend() {
    const id = S.id, pts = [...S.pts], filters = { ...S.filters };
    for (const k of Object.keys(filters)) if (filters[k] === '' || filters[k] == null) delete filters[k];
    $('go').disabled = true;
    try {
        const listed = [];
        for (const pt of pts) {
            const { rows } = await walk(id, pt, filters, (n, of, total) => toast(`Listing ${pt}: page ${fmt(n)} of ${fmt(of)} (${fmt(total)} places)`, of ? n / of : 1));
            listed.push(...rows);
        }
        if (listed.length > 3000 && !confirm(`That's ${fmt(listed.length)} places to download, one at a time. Go ahead?`)) { done('Stopped.'); return; }
        const recs = new Map(), missing = [];
        let n = 0;
        await pool(listed, RECORD_WORKERS, async ([i, name, repo]) => {
            let r = null;
            try { r = await record(i, repo); } catch (e) { console.warn(i, e); }
            if (r?.properties?.['wof:id'] === i) recs.set(i, r); else missing.push([i, name]);
            if (++n % 10 === 0 || n === listed.length) toast(`Downloading ${fmt(n)} of ${fmt(listed.length)}`, n / listed.length);
        });
        const records = sortRecords([...recs.values()], pts);
        const levels = between(records, S.me['wof:placetype'], id);
        const names = new Map([[id, S.me['wof:name'] ?? '']]);
        for (const r of records) names.set(r.properties['wof:id'], r.properties['wof:name'] ?? '');
        const need = new Set();
        for (const r of records) {
            const p = r.properties, h = hierarchy(p, id);
            for (const x of [p['wof:parent_id'], ...levels.map(pt => h[`${pt}_id`])]) if (posInt(x) && !names.has(x)) need.add(x);
        }
        if (need.size) {
            toast(`Looking up ${fmt(need.size)} names…`);
            await pool([...need], RECORD_WORKERS, async x => { let s = null; try { s = await spr(x); } catch { } names.set(x, s?.['wof:name'] ?? ''); });
        }
        S.records = records;
        S.rows = records.map(r => rowOf(r, id, levels, names));
        S.cols = fieldsFor(levels);
        S.missing = missing.sort((a, b) => a[0] - b[0]);
        S.name = `${id}-${pts.join('-')}`;
        S.selected = null;
        showResults();
        done(`${fmt(S.rows.length)} places`);
    } catch (e) {
        console.error(e);
        done(`Something went wrong: ${e.message}`, 8000);
    } finally { updateGo(); }
}

// ------------------------------------------------------------------ the place and its filters
async function lookUp(text, keepFilters = false) {
    const t = parseTarget(text);
    if (!t) { done("That isn't a Who's On First id or Spelunker link."); return; }
    if (!S.spelunker) { S.id = t.id; if (t.filters?.placetype) S.pts = [t.filters.placetype]; showBlocked(); return; }
    toast('Looking it up…');
    let me = null;
    try { me = await spr(t.id); } catch (e) { console.warn(e); }
    if (!me) { done(`The Spelunker doesn't know ${t.id}.`); return; }
    S.id = t.id; S.me = me;
    $('place').value = String(t.id);
    if (t.filters) {
        S.pts = t.filters.placetype ? [t.filters.placetype] : [];
        S.filters = Object.fromEntries(FILTERS.map(k => [k, t.filters[k] ?? '']));
    } else if (!keepFilters) {
        S.pts = []; S.filters = { isdeprecated: '0' };
    }
    $('place-info').hidden = false;
    $('place-info').innerHTML = `<strong>${esc(me['wof:name'])}</strong><span>${esc(me['wof:placetype'])} · ${esc(me['wof:country'] || '')} · ${t.id} · <a href="${SPELUNKER}/id/${t.id}/descendants" target="_blank" rel="noopener">Spelunker</a></span>`;
    if (me['mz:min_longitude'] != null) map?.fitBounds([[me['mz:min_longitude'], me['mz:min_latitude']], [me['mz:max_longitude'], me['mz:max_latitude']]], { padding: 30, duration: 600 });
    $('toast').hidden = true;
    $('card-filters').hidden = false;
    await refreshFacets();
    syncUrl();
}

let facetTimer, facetSeq = 0;
function refreshFacetsSoon() { clearTimeout(facetTimer); facetTimer = setTimeout(refreshFacets, 150); }
async function refreshFacets() {
    const seq = ++facetSeq, id = S.id;
    const filters = Object.fromEntries(Object.entries(S.filters).filter(([, v]) => v !== '' && v != null));
    const one = S.pts.length === 1 ? { placetype: S.pts[0] } : {};
    try {
        const [pt, country, iscurrent, isdeprecated] = await Promise.all([
            facetCounts(id, filters, 'placetype'),
            facetCounts(id, { ...filters, ...one }, 'country'),
            facetCounts(id, { ...filters, ...one }, 'iscurrent'),
            facetCounts(id, { ...filters, ...one }, 'isdeprecated'),
        ]);
        if (seq !== facetSeq) return;
        S.facets = { placetype: pt, country, iscurrent, isdeprecated };
    } catch (e) { console.warn('[facets]', e); }
    drawFilters();
}

function drawFilters() {
    const f = S.facets;
    const pts = Object.keys(f.placetype || {});
    for (const p of S.pts) if (!pts.includes(p)) pts.push(p);
    pts.sort((a, b) => (PLACETYPES.indexOf(a) + 1 || 99) - (PLACETYPES.indexOf(b) + 1 || 99) || a.localeCompare(b));
    $('pts').innerHTML = pts.length ? pts.map(p => {
        const i = S.pts.indexOf(p);
        return `<label class="pt"><input type="checkbox" value="${esc(p)}" ${i >= 0 ? 'checked' : ''}><span>${i >= 0 ? `<i style="background:${COLORS[i % COLORS.length]}"></i>` : ''}${esc(p)}</span><span class="n">${fmt(f.placetype?.[p] ?? 0)}</span></label>`;
    }).join('') : '<p class="hint">No descendants with these filters.</p>';
    const sel = (el, opts, v) => { el.innerHTML = opts.map(([val, label]) => `<option value="${esc(val)}" ${String(v ?? '') === val ? 'selected' : ''}>${esc(label)}</option>`).join(''); };
    const n = (k, v) => f[k]?.[v] != null ? ` (${fmt(f[k][v])})` : '';
    const countries = Object.keys(f.country || {}).filter(Boolean).sort();
    if (S.filters.country && !countries.includes(S.filters.country)) countries.push(S.filters.country);
    sel($('f-country'), [['', 'Any'], ...countries.map(c => [c, c + n('country', c)])], S.filters.country);
    sel($('f-iscurrent'), [['', 'Any'], ['1', 'Current' + n('iscurrent', '1')], ['0', 'Not current' + n('iscurrent', '0')], ['-1', 'Unknown' + n('iscurrent', '-1')]], S.filters.iscurrent);
    sel($('f-isdeprecated'), [['0', 'Leave them out' + n('isdeprecated', '0')], ['', 'Include them'], ['1', 'Only deprecated' + n('isdeprecated', '1')]], S.filters.isdeprecated);
    updateGo();
}

function updateGo() {
    const n = S.pts.reduce((s, p) => s + (S.facets.placetype?.[p] ?? 0), 0);
    const exact = S.pts.length === 1 && S.facets.isdeprecated;
    $('go').disabled = !S.pts.length;
    $('go').textContent = S.pts.length ? `Get ${S.pts.join(' + ')}` : 'Pick a placetype';
    $('go-hint').textContent = S.pts.length && !exact ? `About ${fmt(n)} places before the country and status filters.` : '';
    $('cli').textContent = cli();
}

function cli() {
    const f = S.filters, parts = ['python3 wof-descender/descender.py', String(S.id ?? '<id>')];
    if (S.pts.length) parts.push('-p', S.pts.join(','));
    for (const k of FILTERS) if (f[k] !== '' && f[k] != null) parts.push(`--${k}`, f[k]);
    if ($('all-props').checked) parts.push('--all-properties');
    return parts.join(' ');
}

function syncUrl() {
    const q = new URLSearchParams();
    if (S.id) q.set('id', S.id);
    if (S.pts.length) q.set('placetype', S.pts.join(','));
    for (const k of FILTERS) {
        const v = S.filters[k] ?? '';
        if (k === 'isdeprecated') { if (v !== '0') q.set(k, v === '' ? 'any' : v); }
        else if (v !== '') q.set(k, v);
    }
    const sp = new URLSearchParams(location.search).get('spelunker');
    if (sp) q.set('spelunker', sp);
    history.replaceState(null, '', `${location.pathname}${q.toString() ? '?' + q : ''}`);
}

function showBlocked() {
    $('card-blocked').hidden = false;
    $('card-filters').hidden = true;
    $('cli-blocked').textContent = `python3 wof-descender/descender.py ${S.id ?? 85922583} -p ${S.pts.join(',') || 'neighbourhood'}`;
}

// ------------------------------------------------------------------ results
const colorOf = pt => COLORS[Math.max(0, S.pts.indexOf(pt)) % COLORS.length];

function showResults() {
    $('card-results').hidden = false;
    const tally = {};
    for (const r of S.rows) { const k = `${r.placetype}\u0000${r.status}`; tally[k] = (tally[k] || 0) + 1; }
    $('tally').innerHTML = Object.entries(tally).sort().map(([k, n]) => {
        const [pt, st] = k.split('\u0000');
        return `<div class="tally-row"><span><i style="background:${colorOf(pt)}"></i>${esc(pt)}, ${esc(st)}</span><span>${fmt(n)}</span></div>`;
    }).join('') || '<p class="hint">Nothing found.</p>';
    $('missing').hidden = !S.missing.length;
    $('missing').textContent = S.missing.length ? `${S.missing.length} couldn't be downloaded: ${S.missing.slice(0, 8).map(([i, n]) => `${n || i} (${i})`).join(', ')}${S.missing.length > 8 ? '…' : ''}` : '';
    drawList();
    drawMap(true);
}

function drawList() {
    const q = S.query.trim().toLowerCase();
    const items = S.rows.map((r, i) => [r, i]).filter(([r]) => !q || r.name.toLowerCase().includes(q) || String(r.wof_id).includes(q));
    $('list').innerHTML = items.slice(0, SHOW).map(([r, i]) => {
        const extra = [r.placetype, r.status, r.parent].filter(Boolean).join(' · ');
        return `<li data-i="${i}" class="${S.selected === i ? 'sel' : ''}">${esc(r.name || r.wof_id)}<span>${esc(extra)} · ${r.wof_id}</span></li>`;
    }).join('') + (items.length > SHOW ? `<li class="more">${fmt(items.length - SHOW)} more; search to narrow</li>` : '');
}

function select(i, fly = true) {
    S.selected = i;
    drawList();
    $('list').querySelector('li.sel')?.scrollIntoView({ block: 'nearest' });
    drawMap(false);
    const rec = S.records[i];
    if (fly && rec?.geometry) {
        const b = extend(new maplibregl.LngLatBounds(), rec.geometry);
        if (!b.isEmpty()) map.fitBounds(b, { padding: 60, maxZoom: 16, duration: 500 });
    }
}

function extend(b, g) {
    const walkC = c => typeof c[0] === 'number' ? b.extend(c) : c.forEach(walkC);
    if (g.type === 'GeometryCollection') g.geometries.forEach(x => extend(b, x)); else if (g.coordinates) walkC(g.coordinates);
    return b;
}

function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ------------------------------------------------------------------ map
let map, popup;
const empty = () => ({ type: 'FeatureCollection', features: [] });

async function startMap() {
    let region = {};
    try { region = await (await fetch(BASE + 'region.json')).json(); } catch (e) { console.warn('[region]', e); }
    const key = region.basemap?.keys?.[location.origin] || DEFAULT_KEY;
    map = new maplibregl.Map({ container: 'map', style: STYLE(key), center: [-40, 30], zoom: 1.6, attributionControl: { compact: true } });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.addControl({ onAdd() {
        const el = document.createElement('div');
        el.className = 'maplibregl-ctrl maplibregl-ctrl-group basemap-switch';
        el.innerHTML = '<button type="button" data-b="map" aria-pressed="true">Map</button><button type="button" data-b="sat" aria-pressed="false">Satellite</button>';
        el.onclick = e => { const b = e.target.closest('[data-b]'); if (b) setBasemap(b.dataset.b === 'sat'); };
        return el;
    }, onRemove() {} }, 'top-right');
    popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    map.on('load', () => { addLayers(); if (S.records.length) drawMap(true); });
}

// The map's own layers, once the basemap has loaded. Everything else works without the map.
function addLayers() {
    fixCreeks();
    const before = map.getStyle().layers.find(l => l.type === 'symbol')?.id;
    map.addSource('places', { type: 'geojson', data: empty(), promoteId: 'i' });
    map.addSource('labels', { type: 'geojson', data: empty() });
    map.addSource('satellite', { type: 'raster', tileSize: 256, maxzoom: 19,
        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
        attribution: 'Imagery © <a href="https://www.esri.com">Esri</a>, Maxar, Earthstar Geographics' });
    map.addLayer({ id: 'satellite', type: 'raster', source: 'satellite', layout: { visibility: 'none' } }, before);
    const hover = ['boolean', ['feature-state', 'hover'], false];
    map.addLayer({ id: 'places-fill', type: 'fill', source: 'places', filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': ['case', ['get', 'sel'], 0.3, hover, 0.2, ['get', 'current'], 0.08, 0.03] } }, before);
    map.addLayer({ id: 'places-line', type: 'line', source: 'places', filter: ['!=', ['geometry-type'], 'Point'],
        paint: { 'line-color': ['get', 'color'], 'line-width': ['case', ['get', 'sel'], 3, hover, 2.2, 1.2], 'line-opacity': ['case', ['get', 'current'], 0.9, 0.45] } }, before);
    map.addLayer({ id: 'places-pt', type: 'circle', source: 'places', filter: ['==', ['geometry-type'], 'Point'],
        paint: { 'circle-color': ['get', 'color'], 'circle-radius': ['case', ['get', 'sel'], 7, 5], 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
    map.addLayer({ id: 'labels', type: 'symbol', source: 'labels', minzoom: 3,
        layout: { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Medium'], 'text-size': 12, 'text-max-width': 8, 'text-padding': 4 },
        paint: { 'text-color': '#1d2433', 'text-halo-color': '#fff', 'text-halo-width': 1.6 } });
    let hovered = null;
    const layers = ['places-fill', 'places-line', 'places-pt'];
    map.on('mousemove', e => {
        const f = map.queryRenderedFeatures(e.point, { layers })[0];
        if (hovered !== null && hovered !== f?.id) map.setFeatureState({ source: 'places', id: hovered }, { hover: false });
        if (!f) { hovered = null; popup.remove(); map.getCanvas().style.cursor = ''; return; }
        hovered = f.id;
        map.setFeatureState({ source: 'places', id: hovered }, { hover: true });
        map.getCanvas().style.cursor = 'pointer';
        const r = S.rows[f.id];
        popup.setLngLat(e.lngLat).setHTML(`<div class="pop-title">${esc(r.name)}</div><div class="pop-sub">${esc(r.placetype)} · ${esc(r.status)}${r.parent ? ' · in ' + esc(r.parent) : ''}<br>${r.wof_id}</div>`).addTo(map);
    });
    map.on('mouseout', () => popup.remove());
    map.on('click', e => {
        const f = map.queryRenderedFeatures(e.point, { layers })[0];
        if (f) select(f.id, false);
    });
    map.on('dblclick', e => {
        const f = map.queryRenderedFeatures(e.point, { layers })[0];
        if (f) { e.preventDefault(); window.open(S.rows[f.id].spelunker, '_blank', 'noopener'); }
    });
    let sat = false;
    try { sat = localStorage.getItem('descender.basemap') === 'satellite'; } catch { }
    setBasemap(sat);
}

function setBasemap(sat) {
    if (map.getLayer('satellite')) map.setLayoutProperty('satellite', 'visibility', sat ? 'visible' : 'none');
    document.querySelectorAll('.basemap-switch button').forEach(b => b.setAttribute('aria-pressed', String((b.dataset.b === 'sat') === sat)));
    try { localStorage.setItem('descender.basemap', sat ? 'satellite' : 'map'); } catch { }
}

// Creek fix (same as Block Party, Selecter, Joiner and Matcher): Protomaps tags many Bay Area creeks as
// rivers, including culverted ones underground. Hide streams, and rivers or labels named "Creek" or "Arroyo".
function fixCreeks() {
    try {
        if (map.getLayer('water_stream')) map.setLayoutProperty('water_stream', 'visibility', 'none');
        if (map.getLayer('water_river')) map.setFilter('water_river', ['all',
            ['!', ['in', 'Creek', ['get', 'name']]], ['!', ['in', 'Arroyo', ['get', 'name']]]]);
        if (map.getLayer('water_waterway_label')) map.setFilter('water_waterway_label', ['all',
            ['!=', ['get', 'kind'], 'stream'], ['!', ['in', 'Creek', ['get', 'name']]], ['!', ['in', 'Arroyo', ['get', 'name']]]]);
    } catch (e) { console.warn('[creek filter]', e); }
}

function drawMap(fit) {
    if (!map?.getSource('places')) return;
    const feats = [], labels = [];
    S.records.forEach((rec, i) => {
        const r = S.rows[i];
        if (!rec.geometry) return;
        const props = { i, name: r.name, color: colorOf(r.placetype), current: r.status === 'current' || r.status === 'unverified', sel: S.selected === i };
        // MultiPolygons split so the fill filter sees them as polygons (MapLibre does that anyway); keep one id.
        feats.push({ type: 'Feature', id: i, properties: props, geometry: rec.geometry });
        if (r.lbl_longitude != null && r.lbl_latitude != null && rec.geometry.type !== 'Point')
            labels.push({ type: 'Feature', properties: { name: r.name }, geometry: { type: 'Point', coordinates: [r.lbl_longitude, r.lbl_latitude] } });
    });
    map.getSource('places').setData({ type: 'FeatureCollection', features: feats });
    map.getSource('labels').setData({ type: 'FeatureCollection', features: labels });
    if (fit && feats.length) {
        const b = new maplibregl.LngLatBounds();
        feats.forEach(f => extend(b, f.geometry));
        if (!b.isEmpty()) map.fitBounds(b, { padding: 30, maxZoom: 15, duration: 600 });
    }
}

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

// ------------------------------------------------------------------ wiring
$('place-form').onsubmit = e => { e.preventDefault(); if ($('place').value.trim()) lookUp($('place').value); };
document.querySelectorAll('[data-eg]').forEach(b => b.onclick = () => { $('place').value = b.dataset.eg; lookUp(b.dataset.eg); });
$('pts').onchange = e => {
    const v = e.target.value;
    if (e.target.checked) { if (!S.pts.includes(v)) S.pts.push(v); } else S.pts = S.pts.filter(p => p !== v);
    drawFilters(); refreshFacetsSoon(); syncUrl();
};
for (const k of FILTERS) $(`f-${k}`).onchange = e => { S.filters[k] = e.target.value; refreshFacetsSoon(); syncUrl(); updateGo(); };
$('all-props').onchange = updateGo;
$('go').onclick = descend;
$('search').oninput = e => { S.query = e.target.value; drawList(); };
$('list').onclick = e => { const li = e.target.closest('li[data-i]'); if (li) select(Number(li.dataset.i)); };
$('save-geojson').onclick = () => {
    const all = $('all-props').checked;
    download(`${S.name}.geojson`, geojsonText(S.name, S.records.map((r, i) => featureOf(r, S.rows[i], all))), 'application/geo+json');
};
$('save-csv').onclick = () => download(`${S.name}.csv`, csvText(S.cols, S.rows, S.records.map(r => r.geometry ?? null)), 'text/csv');
$('copy-cli').onclick = async () => { try { await navigator.clipboard.writeText(cli()); done('Copied.', 1500); } catch { done("Couldn't copy; select the text instead."); } };

(async () => {
    startMap().catch(e => console.warn('[map]', e));
    S.spelunker = await findSpelunker();
    const pill = $('source');
    if (!S.spelunker) { pill.textContent = "Spelunker can't be read here"; pill.className = 'pill bad'; }
    else {
        pill.className = 'pill ready';
        pill.textContent = S.spelunker === SPELUNKER ? 'Spelunker' : S.spelunker.endsWith('/spelunker') && S.spelunker.startsWith(location.origin) ? 'Spelunker, through descender.py' : 'Spelunker, through a proxy';
    }
    const q = new URLSearchParams(location.search);
    const start = q.get('url') || q.get('id');
    if (!start) { if (!S.spelunker) showBlocked(); return; }
    const t = parseTarget(start);
    if (t && !t.filters && q.get('id')) {
        S.pts = (q.get('placetype') || '').split(',').filter(Boolean);
        S.filters = { country: q.get('country') || '', iscurrent: q.get('iscurrent') || '',
            isdeprecated: q.has('isdeprecated') ? (q.get('isdeprecated') === 'any' ? '' : q.get('isdeprecated')) : '0' };
    }
    await lookUp(start, true);
    if (S.spelunker && S.id && S.pts.length && q.get('go') !== '0') descend();
})();
