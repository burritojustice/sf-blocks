// Google Drive for static pages: sign in, pick a file with Google's own picker, and read it.
// Written for Matcher; Joiner and Block Party can copy this file as is.
//
// It asks only for the drive.file permission: the page can open the files the person picks in the
// picker, and nothing else in their Drive. Google treats that as a low-risk permission. Nothing goes
// through a server of ours: the token stays in this page and expires within an hour.
//
//   await GoogleDrive.config('google.json')     // {<site origin>: {clientId, apiKey, appId}}; null if this site has none
//   const doc = await GoogleDrive.pick(mimeTypes) // null if the person closes the picker
//   const got = await GoogleDrive.read(doc)
//     a Google Sheet -> {kind: 'sheet', id, name, tabs: [{title, sheetId, values: [[...], ...]}]}
//     any other file -> {kind: 'file', id, name, file: File}
'use strict';
window.GoogleDrive = (() => {
    const GIS = 'https://accounts.google.com/gsi/client';
    const GAPI = 'https://apis.google.com/js/api.js';
    const SCOPE = 'https://www.googleapis.com/auth/drive.file';
    const SHEET = 'application/vnd.google-apps.spreadsheet';
    let cfg = null, token = null, expires = 0;

    const load = src => new Promise((resolve, reject) => {
        if (document.querySelector(`script[src="${src}"]`)) return resolve();
        const s = document.createElement('script');
        s.src = src; s.async = true;
        s.onload = resolve;
        s.onerror = () => reject(new Error(`couldn't reach ${new URL(src).host}`));
        document.head.appendChild(s);
    });

    async function config(url) {
        try { cfg = (await (await fetch(url, { cache: 'no-cache' })).json())[location.origin] || null; }
        catch { cfg = null; }
        if (cfg && !(cfg.clientId && cfg.apiKey && cfg.appId)) cfg = null;
        return cfg;
    }

    // A token for drive.file, from Google Identity Services. Google shows its own sign-in and consent popup.
    async function signIn() {
        if (token && Date.now() < expires - 60_000) return token;
        await load(GIS);
        return new Promise((resolve, reject) => {
            const client = google.accounts.oauth2.initTokenClient({
                client_id: cfg.clientId, scope: SCOPE,
                callback: r => {
                    if (r.error) return reject(new Error(r.error_description || r.error));
                    token = r.access_token; expires = Date.now() + (r.expires_in || 3600) * 1000;
                    resolve(token);
                },
                error_callback: e => reject(new Error(e.type === 'popup_closed' ? 'the Google sign-in window was closed'
                    : e.type === 'popup_failed_to_open' ? 'the browser blocked the Google sign-in window' : (e.message || e.type))),
            });
            client.requestAccessToken();
        });
    }

    async function pick(mimeTypes = []) {
        if (!cfg) throw new Error("Google Drive isn't set up for this site");
        const t = await signIn();
        await load(GAPI);
        await new Promise(r => gapi.load('picker', r));
        return new Promise(resolve => {
            const P = google.picker;
            const view = new P.DocsView(P.ViewId.DOCS).setIncludeFolders(true).setSelectFolderEnabled(false);
            if (mimeTypes.length) view.setMimeTypes(mimeTypes.join(','));
            new P.PickerBuilder().addView(view).setOAuthToken(t).setDeveloperKey(cfg.apiKey).setAppId(cfg.appId)
                .setTitle('Choose a file').setCallback(d => {
                    if (d.action === P.Action.PICKED) resolve(d.docs[0]);
                    else if (d.action === P.Action.CANCEL) resolve(null);
                }).build().setVisible(true);
        });
    }

    async function api(url) {
        const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        if (r.status === 401) { token = null; throw new Error('the Google sign-in expired; try again'); }
        if (!r.ok) throw new Error(`Google answered ${r.status}`);
        return r;
    }

    async function read(doc) {
        if (doc.mimeType === SHEET) {
            const base = `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(doc.id)}`;
            const meta = await (await api(`${base}?fields=properties.title,sheets.properties(title,sheetId)`)).json();
            const titles = meta.sheets.map(s => s.properties.title);
            const ranges = titles.map(t => 'ranges=' + encodeURIComponent(`'${t.replace(/'/g, "''")}'`)).join('&');
            const vals = await (await api(`${base}/values:batchGet?${ranges}&valueRenderOption=FORMATTED_VALUE`)).json();
            return { kind: 'sheet', id: doc.id, name: meta.properties.title,
                tabs: titles.map((title, i) => ({ title, sheetId: meta.sheets[i].properties.sheetId, values: vals.valueRanges?.[i]?.values || [] })) };
        }
        const r = await api(`https://www.googleapis.com/drive/v3/files/${encodeURIComponent(doc.id)}?alt=media`);
        return { kind: 'file', id: doc.id, name: doc.name, file: new File([await r.blob()], doc.name, { type: doc.mimeType || '' }) };
    }

    return { config, pick, read, signIn, get ready() { return !!cfg; } };
})();
