# Matcher

https://burritojustice.github.io/sf-blocks/matcher/

Match street names, intersections and polygons to San Francisco blocks (CNNs) in the browser. Drop in a CSV, Excel workbook or GeoJSON, paste a link or rows, check the results on a map, fix the ones that need it, and save a CSV, GeoJSON or Excel file.

It runs sf-blocks' own `scripts/match_blocks.py` and `scripts/match_polygons.py` with [Pyodide](https://pyodide.org), so its answers are the command line's answers. Files stay in the browser.

| File | What it does |
|---|---|
| `index.html` | The page: Load, What to match, Results, the map and the table |
| `matcher.js` | Reading files and links, guessing columns, sending rows to the worker in batches, the map, the table, fixing on the map, saving |
| `worker.js` | Loads Pyodide and the scripts, and runs `match_rows`, `match_features`, `manual` and `suggest_columns` |
| `google-drive.js` | Signing in to Google, Google's file picker, and reading a Google Sheet or a Drive file. Self-contained, so other pages can copy it |
| `google.json` | Google Drive settings for each site Matcher runs on |
| `matcher.css` | Styles |

Libraries, pinned: MapLibre GL 5.16.0, PapaParse 5.4.1, SheetJS 0.20.3 (from SheetJS's own CDN; the npm copy is out of date), Pyodide 314.0.7, with Pyodide 0.27.7 as the fallback for Safari 18, where 314 crashes while starting.

For testing without the CDN, `?pyodide=<url>/` loads Pyodide from another copy; a comma-separated list tries each in turn.

## Google Drive

**Open from Google Drive** uses Google's file picker. It asks only for the `drive.file` permission, which lets the page open the files the person picks and nothing else in their Drive. Google treats that as a non-sensitive permission, so the app doesn't need Google's security review. The sign-in lasts up to an hour, stays in that browser tab, and never goes through a server of ours.

It needs three values from a Google Cloud project, one set per site. They're public, not secrets: they identify the app to Google, and Google only accepts them from the sites listed. Setting it up once:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (for example "sf-blocks Matcher").
2. **APIs & Services › Library:** enable the **Google Picker API**, the **Google Sheets API** and the **Google Drive API**.
3. **APIs & Services › OAuth consent screen:**
   - user type **External**;
   - app name, support email and developer email;
   - under Scopes, add `.../auth/drive.file`.

   While it's in **Testing**, only the test users you add can sign in. **Publish app** opens it to everyone; drive.file alone needs no verification.
4. **Credentials › Create credentials › OAuth client ID:** type **Web application**. Under **Authorized JavaScript origins**, add `https://burritojustice.github.io`, plus `http://localhost:8000` if you test locally. Copy the **Client ID**.
5. **Credentials › Create credentials › API key:**
   - **Application restrictions:** Websites, with `https://burritojustice.github.io/*` and `http://localhost:8000/*`.
   - **API restrictions:** Google Picker API.

   Copy the key.
6. The **project number** (on the project's Dashboard, or IAM & Admin › Settings) is the **App ID**.
7. Put them in `google.json` under the site, and ship it as an sf-blocks release:

```json
"https://burritojustice.github.io": { "clientId": "1234…apps.googleusercontent.com", "apiKey": "AIza…", "appId": "1234567890" }
```

Another organization running its own copy makes its own project and adds its own site.

Next step, not built yet: writing the matched columns back to the Sheet, to a new tab. That needs the Sheets write permission for the picked file, which `drive.file` already covers.
