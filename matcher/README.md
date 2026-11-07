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

It needs three values from a Google Cloud project, one set per site, in `google.json`:

| Value | What it is | Where it comes from |
|---|---|---|
| `clientId` | The OAuth client, for signing in | Google Auth Platform › Clients; ends in `.apps.googleusercontent.com` |
| `apiKey` | The key for Google's file picker | APIs & Services › Credentials; starts with `AIza` |
| `appId` | The project **number** (all digits), not the project ID | Cloud overview › Dashboard, or IAM & Admin › Settings. It's also the digits at the start of the client ID |

They're public, not secrets: they identify the app to Google, and Google only accepts them from the sites listed in the steps below.

### Setting it up

The console has two areas for this. Sign-in settings live in **Google Auth Platform**; turning on APIs and making the key live in **APIs & Services**. The quickest way to any page below is to type its name in the search bar at the top of the console.

1. **Pick or create a project.** Use the project menu at the top left (it may say "My First Project"). The name doesn't matter to Matcher.

2. **Turn on three APIs.** Search for each one, open it, and click **Enable**:
   - Google Picker API
   - Google Drive API
   - Google Sheets API

3. **Google Auth Platform** (search "Google Auth Platform"; the first visit asks you to **Get started**):
   - **Branding:** app name (for example "sf-blocks Matcher") and a support email. This is what people see on the Google sign-in window.
   - **Audience:** **External**. While the status is **Testing**, only the people listed under **Test users** can sign in, so add yourself. When it works, click **Publish app** so anyone can sign in. With only `drive.file`, Google doesn't review it (adding a logo under Branding does start a brand check, so leave the logo off).
   - **Data Access › Add or remove scopes:** find `.../auth/drive.file` (Google Drive API: "See, edit, create, and delete only the specific Google Drive files you use with this app"), tick it, and **Update**, then **Save**.
   - **Clients › Create client:** type **Web application**, any name. Under **Authorized JavaScript origins** add `https://burritojustice.github.io` (just the site, no path or trailing slash), plus `http://localhost:8000` if you test locally. Leave **Authorized redirect URIs** empty. **Create**, then copy the **Client ID**.

4. **API key.** Search "Credentials" and open **Credentials (APIs & Services)**; it isn't under Google Auth Platform. Click **+ Create credentials › API key**, then open the new key (or **Edit API key**) and set:
   - **Application restrictions:** **Websites**, with these three entries:
     - `https://burritojustice.github.io/*`
     - `https://docs.google.com/*` (the picker runs in a frame from docs.google.com; without it the picker says the key is invalid)
     - `http://localhost:8000/*` if you test locally
   - **API restrictions:** **Restrict key**, and pick **Google Picker API**.

   **Save** and copy the key. Restrictions can take a few minutes to take effect.

5. **Project number.** Open **Cloud overview › Dashboard** (or **IAM & Admin › Settings**) and copy **Project number**. It's all digits. The **Project ID** (letters, like `project-6899…`) is a different value and won't work.

6. **Put them in `google.json`** under the site and ship it as an sf-blocks release. The same values work for `http://localhost:8000` if you added it in steps 3 and 4:

```json
"https://burritojustice.github.io": { "clientId": "1234567890-abc….apps.googleusercontent.com", "apiKey": "AIza…", "appId": "1234567890" }
```

### If it doesn't work

| What you see | Usually means |
|---|---|
| No **Open from Google Drive** button | `google.json` has no complete entry for this site (all three values, and the site exactly as it appears in the address bar) |
| "Error 400: redirect_uri_mismatch" or "origin_mismatch" in the sign-in window | The site isn't in the client's **Authorized JavaScript origins** |
| "Access blocked: … has not completed the Google verification process" | The app is in **Testing** and you're not a test user; add yourself or **Publish app** |
| The picker opens but says the API key is invalid | The key's website list is missing the site or `https://docs.google.com/*`, or the Picker API isn't enabled |
| The picker shows files but opening one fails with 403 | The Drive or Sheets API isn't enabled, or `appId` is the project ID instead of the project number |

Another organization running its own copy makes its own project and adds its own site.

Next step, not built yet: writing the matched columns back to the Sheet, to a new tab. That needs the Sheets write permission for the picked file, which `drive.file` already covers.
