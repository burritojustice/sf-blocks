# Historic shoreline and water

How the 1850s shoreline layers are made: where the lines come from, what we change, how the water areas are built, and how we check the alignment. The build is `scripts/build_layers.py` (`build_shoreline`, `shoreline_water`, `build_chart_1853`).

## Layers

| Layer | File | What it is |
| --- | --- | --- |
| Shoreline 1850–1857 | `data/layers/shoreline.geojson` | The surveyed lines, one feature per line, with `survey` (1850–52, 1853, 1857), `register`, `sheet`, `kind` and `class` |
| Water in the 1850s | `data/layers/shoreline_water.geojson` | One water area per survey, built from those lines. Apps fill it in the basemap's water color (`draw: water`), so land that was water then shows as water |
| Names on the 1853 chart | `data/layers/chart_1853.geojson` | Points for the wharves, points and rocks named on the Coast Survey's 1853 chart, with `name`, `as_printed` and `kind` |

## Sources

**NOAA shoreline surveys (T-sheets).** The lines are the U.S. Coast Survey's topographic sheets, digitized by NOAA ([shoreline.noaa.gov/t-sheets](https://shoreline.noaa.gov/t-sheets.html)) and exported through Selecter, one GeoJSON per survey in `data/uploads/shoreline/`. These downloads stay as published.

| Survey | Register | Sheets | Covers |
| --- | --- | --- | --- |
| 1850–52 | CA37A02 | seven, T-00314, T-00352 and others | the whole city shore and Marin |
| 1853 | CA37B07 | one | the northeast waterfront, North Beach to Mission Creek |
| 1857 | CA37B08 | one | North Beach and the Presidio to Islais Creek |

Every feature is kept except the sheets' own bounding boxes ("User Added Line" with class Cartographic). That includes wharves, marsh edges, piers and creeks.

**The Coast Survey's printed charts** at 1:10,000, in the [David Rumsey Map Collection](https://www.davidrumsey.com/). These are the published maps compiled from the T-sheets, with the streets, buildings and place names the T-sheets leave out:

- 1853: *City of San Francisco and its Vicinity*, [RUMSEY~8~1~2210~180022](https://www.davidrumsey.com/luna/servlet/detail/RUMSEY~8~1~2210~180022). Rumsey's note says the survey was finished in April 1852, and the city plan came from Eddy's official map. Its IIIF image (6,880 × 9,914 px) is at `https://www.davidrumsey.com/luna/servlet/iiif/RUMSEY~8~1~2210~180022`. A colored copy is on [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:1853_U.S.C.S._Map_of_San_Francisco,_California_%5E_Vicinity_-_Geographicus_-_SanFrancisco3-uscs-1853.jpg).
- 1857: *City of San Francisco and its Vicinity*, first edition, [RUMSEY~8~1~239938~5512085](https://davidrumsey.com/luna/servlet/detail/RUMSEY~8~1~239938~5512085).
- 1850: also in the collection; its link still needs adding here.

Rumsey's images are © Cartography Associates, shared under a Creative Commons non-commercial license. Credit "David Rumsey Map Collection" wherever they show.

## What we change

### Moving a sheet that was digitized out of place

The 1850–52 bay sheet, **T-00352** (North Beach to Hunters Point), sat about 60 m south of where the 1853 and 1857 surveys put the same piers, the beach south of them and Rincon Point. Every other sheet lined up. It's a digitizing error, not a survey one, so the build moves the whole sheet:

- `SHORE_SHIFT` in `build_layers.py` holds meters east and north for each sheet: T-00352 moves **6 m east and 60 m north**.
- Within 400 m (`SHIFT_EASE_M`) of where the moved sheet meets an unmoved one (at North Beach, against T-00314), the move eases to nothing, so the shore stays joined. That short stretch is a small bend, not a straight move.

**How it was measured:** we tried shifts on a grid and kept the one that puts the most 1850–52 points within 6 m of another survey's line.
- Against 1853, Rincon Point gave 6 m east and 64 m north, with 88% of points matching (19% before the move). The piers gave 59 m north.
- Against 1857, Potrero and Islais gave about 60 m north.

**Checked against the streets:** the 1853 printed chart, fitted to today's street intersections (below), puts its wharves and its Rincon Point shore within about 5–15 m of both the 1853 line and the moved 1850–52 line.

Bending a survey to fix the 1850s surveyors' own errors is a separate step, still to come; see the issue on using the intersections.

### Closing the lines into water areas

A water area is the shore closed into a ring, with the land left out:

- **1850–52** reaches all the way round, so its shore is closed offshore along a frame (`WATER_FRAME`) that runs well out into the bay and the ocean.
- **1853 and 1857** cover only part of the waterfront, so `_partial_water()` closes each one with a box to the north and east (`PART_NE`):
  - It chains the lines end to end, bridging gaps of up to 150 m (`PART_BRIDGE_M`).
  - Piers and wharves that touch the shore within 8 m (`PART_SPLICE_M`) are spliced in, so they show as land.
  - The ring is checked so it never crosses itself (`_crossings`).
  - Closed loops out in the water become holes (islands, piers standing on their own); loops on land become ponds.
  - A few short stubs that touch nothing stay as lines.
- The only real gap is at Mission Creek on the 1853 sheet, about 100 m, where the sheet is cut off.

## The 1853 chart: georeference and names

`data/georef/uscs-1853/` holds:

- `control_points.csv`: 146 street intersections, each with its pixel on Rumsey's scan (`px_x`, `px_y`, full size) and its place today (`lon`, `lat`, from `data/streets.json`).
- `names.csv`: the names read off the chart (`name`, `as_printed`, `kind`, pixel position, `note`). The build places them with an affine fit to the control points.
- `annotation.json`: the same control points as an [Allmaps](https://allmaps.org) georeference annotation, pointing at Rumsey's IIIF image.

**How the control points were found** (scratch scripts, not committed):

1. Start from the georeference Allmaps already had for this scan: four points, at annotations.allmaps.org.
2. For each of about 1,000 intersections in the 1853 city, draw today's streets around it (centerlines from `streets.json`, widened to their real widths: 21 m downtown, 25 m south of Market, 36.6 m for Market) into the scan's pixels.
3. Slide that drawing to where it best matches the chart's street edges, and keep the shift.
4. Fit an affine transformation with RANSAC, then keep the intersections within 10 px. That leaves 146, with **3.3 m RMS**.

A second- or third-order fit isn't any better: the chart's city plan lines up with today's streets to about 3 m without any bending.

**Tiles:** Allmaps can warp the scan into map tiles straight from Rumsey's IIIF server, so nothing has to be hosted here:

```
https://allmaps.xyz/{z}/{x}/{y}.png?url=https://burritojustice.github.io/sf-blocks/data/georef/uscs-1853/annotation.json
```

That works as a raster source in MapLibre. Apps can use it as an overlay, credited "David Rumsey Map Collection".

## Using intersections to check alignment

Street intersections are the best way to check these layers, because the city grid laid out in the late 1840s is mostly still there:

- **The printed charts** show the streets, so they can be fitted to today's intersections, as with the 1853 chart above. Once fitted, a chart shows directly where each digitized shoreline should be.
- **The T-sheet scans** (NOAA's images of the original sheets, not the digitized lines) show some streets and buildings too. Digitizing a few corners from each sheet would measure each sheet's own error, and that is what a rubber-sheet correction needs.
- Do the 1850 and 1857 charts the same way: read their IIIF images, fit them to intersections, and compare. The steps are in the issue.
