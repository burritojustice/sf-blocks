// Matcher's background worker (a module worker, as Pyodide needs): runs sf-blocks' own Python matchers (scripts/match_blocks.py and
// scripts/match_polygons.py) in Pyodide, so the page and the command line give the same answers.
// Messages in:  {id, op: 'init', base, pyodide}   (pyodide: the Pyodide folder to load; matcher.js picks it) | {id, op: 'rows', rows, mode, start} | {id, op: 'polygons', features, nameField}
//               {id, op: 'manual', cnns, nodes, text} | {id, op: 'suggest', rows, columns}
// Messages out: {id, ok, result} | {id, error} | {op: 'status', text} while starting up.
let py, ready;

const say = text => postMessage({ op: 'status', text });

async function start(base, pyodide) {
    say('Loading Python…');
    const { loadPyodide } = await import(pyodide + 'pyodide.mjs');
    py = await loadPyodide({ indexURL: pyodide });
    say('Loading the street list…');
    const files = { 'match_blocks.py': 'scripts/match_blocks.py', 'match_polygons.py': 'scripts/match_polygons.py',
                    'streets.json': 'data/streets.json', 'VERSION': 'VERSION' };
    py.FS.mkdirTree('/sfb');
    await Promise.all(Object.entries(files).map(async ([name, path]) => {
        const r = await fetch(base + path, { cache: 'no-cache' });
        if (!r.ok) throw new Error(`couldn't load ${path} (${r.status})`);
        py.FS.writeFile('/sfb/' + name, new Uint8Array(await r.arrayBuffer()));
    }));
    say('Getting the street names ready…');
    py.runPython(`
import sys, json
sys.path.insert(0, '/sfb')
import match_blocks as mb, match_polygons as mp
ST = mb.Streets(*mb.load('/sfb/streets.json'))
POLY = None

def run_rows(rows_json, mode_json, start):
    rows, mode = json.loads(rows_json), json.loads(mode_json)
    describe = mb.describer(**mode)
    return json.dumps([outs for _, _, outs in mb.match_rows(ST, rows, describe, start)])

def run_polygons(features_json, name_field):
    global POLY
    if POLY is None:
        POLY = mp.load_streets('/sfb/streets.json')
    out = [dict(index=i, rows=rows, feature=feat) for i, rows, feat in
           mp.match_features(json.loads(features_json), *POLY, name_field=name_field)]
    return json.dumps(out)

def run_suggest(rows_json, columns_json):
    return json.dumps(mb.suggest_columns(ST, json.loads(rows_json), json.loads(columns_json)))

def run_manual(cnns_json, nodes_json, text):
    return json.dumps(mb.manual(ST, json.loads(cnns_json), json.loads(nodes_json), text))
`);
    return { version: py.FS.readFile('/sfb/VERSION', { encoding: 'utf8' }).trim(), python: py.version };
}

onmessage = async ({ data: m }) => {
    try {
        let result;
        if (m.op === 'init') result = await (ready ||= start(m.base, m.pyodide));
        else {
            await ready;
            if (m.op === 'rows')
                result = JSON.parse(py.globals.get('run_rows')(JSON.stringify(m.rows), JSON.stringify(m.mode), m.start));
            else if (m.op === 'polygons')
                result = JSON.parse(py.globals.get('run_polygons')(JSON.stringify(m.features), m.nameField || 'name'));
            else if (m.op === 'suggest')
                result = JSON.parse(py.globals.get('run_suggest')(JSON.stringify(m.rows), JSON.stringify(m.columns)));
            else if (m.op === 'manual')
                result = JSON.parse(py.globals.get('run_manual')(JSON.stringify(m.cnns || []), JSON.stringify(m.nodes || []), m.text || ''));
            else throw new Error('unknown op ' + m.op);
        }
        postMessage({ id: m.id, ok: true, result });
    } catch (e) {
        postMessage({ id: m.id, error: String(e && e.message || e) });
    }
};
