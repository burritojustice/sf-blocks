// Descender proxy: lets the Descender page read the Spelunker's descendant lists, which the Spelunker
// doesn't let other sites read. A Cloudflare Worker (the free plan is plenty). It only passes on
// GET requests for /id/<id>/descendants, /id/<id>/descendants/facets and /id/<id>/spr, and caches
// answers for a day. See README.md in this folder.
const SPELUNKER = 'https://spelunker.whosonfirst.org';
const ALLOWED = /^\/id\/\d+(\/descendants(\/facets)?|\/spr)?\/?$/;
const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, OPTIONS' };

export default {
    async fetch(request) {
        if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });
        const url = new URL(request.url);
        if (request.method !== 'GET' || !ALLOWED.test(url.pathname)) return new Response('not found', { status: 404, headers: CORS });
        const upstream = await fetch(SPELUNKER + url.pathname + url.search, {
            headers: { 'User-Agent': 'sf-blocks wof-descender proxy (+https://github.com/burritojustice/sf-blocks)' },
            cf: { cacheTtl: 86400, cacheEverything: true },
        });
        const headers = new Headers(CORS);
        headers.set('Content-Type', upstream.headers.get('Content-Type') || 'text/html');
        headers.set('Cache-Control', 'public, max-age=3600');
        return new Response(upstream.body, { status: upstream.status, headers });
    },
};
