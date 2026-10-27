# Reference

Public lists that go with the map data but aren't maps: who to contact in each area, as the city or the organization publishes it. Plain files, so anyone can read and update them without an Airtable account.

| Folder | What | Goes with |
|---|---|---|
| `neighborhood-groups/` | SF Planning's neighborhood group notification list, as published, plus `neighborhood_groups.json` built from it | `planning_neighborhoods` |
| `cultural-districts/` | Contacts for the 10 Cultural Districts (`contacts.csv`, to fill in) | `cultural_districts` |

## What belongs here

- **Public contact information only:** what a city department or the organization itself publishes.
- **Not** private contacts: personal emails or phones, donors, volunteers, anything from Airtable or a sign-up form.
- A list downloaded whole keeps its publish or download date in the file name (`…_20260925.csv`) and isn't edited by hand.
- A list built by hand has `source_url` and `checked` (`YYYY-MM-DD`) on every row.
- The first column is the boundary set's key, spelled as in `data/boundaries/<set>.geojson`, so the list joins to the map.
