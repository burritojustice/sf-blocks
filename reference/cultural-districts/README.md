# Cultural Districts contacts

Contacts for San Francisco's 10 Cultural Districts, one row per district, keyed by `district_name`. Goes with the `cultural_districts` boundary set (`data/boundaries/cultural_districts.geojson`); in Joiner it's Other › Cultural Districts.

## Sources

- Boundaries: DataSF [Cultural Districts](https://data.sf.gov/Culture-and-Recreation/Cultural-Districts/5xmc-5bjj) (`5xmc-5bjj`), exported 2026-10-25 (the export is in `data/uploads/`).
- The program: [SF.gov — San Francisco Cultural Districts Program](https://www.sf.gov/san-francisco-cultural-districts-program) (run by MOHCD) and [SF Planning — Cultural Heritage](https://sfplanning.org/cultural-heritage). Each district's page on SF.gov names its lead organization and links its website.

## Columns (`contacts.csv`)

| Column | What to put in it |
|---|---|
| `district_name` | The district, exactly as in the boundary file. Already filled in; don't change it |
| `organization` | The district's lead or partner organization, as the city lists it |
| `role` | What the organization does for the district, e.g. "lead organization", "fiscal sponsor" |
| `website` | The district's or organization's public website |
| `public_email` | A general email the organization publishes (info@…). Not a person's own address unless the organization lists it as the public contact |
| `public_phone` | A published office phone |
| `source_url` | The page where you found this row's information |
| `checked` | The date you checked it, `YYYY-MM-DD` |
| `notes` | Anything else, e.g. "also covers Tenderloin events" |

One row per district. If a district has two organizations, add a second row with the same `district_name`.

## Adding or updating contacts

1. Open the district's page from the SF.gov Cultural Districts page (or the organization's own site).
2. Fill in the row in `contacts.csv` in a spreadsheet app or text editor. Save it as CSV (UTF-8), keeping the header row and column order.
3. Put the page you used in `source_url` and today's date in `checked`.
4. Check it in Joiner: choose **Other › Cultural Districts**, then **Load data** and pick `contacts.csv`. All 10 districts should be matched (rows match by `district_name`). Other spellings people use go in `data/aliases.json`..
5. Commit with a message like "Cultural Districts contacts: add Japantown". On GitHub you can edit the file in the browser (the pencil icon) and commit from there.

## When the districts change

When the Board of Supervisors designates a new district or redraws one:

1. Export the new GeoJSON from DataSF (Export › GeoJSON).
2. Save it in `data/uploads/` with its date in the name and rebuild the set (for now with Joiner's `node scripts/get_layers.mjs --file cultural_districts=<path>`, then copy it here). Update `expectCount` and the label in `data/boundaries/sources.json` if the number changed.
3. Add a row to `contacts.csv` for the new district, and update the export date above.
