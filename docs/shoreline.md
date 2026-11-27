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

| Survey | Register | NOAA record | Sheets | Covers |
| --- | --- | --- | --- | --- |
| 1850–52 | CA37A02 | [InPort 62009](https://www.fisheries.noaa.gov/inport/item/62009) | seven: T-00352 (the bay shore), T-00314, T-00321, T-00334-1, T-00334-2, T-00361, T-00382 | the whole city shore and Marin |
| 1853 | CA37B07 | [InPort 62017](https://www.fisheries.noaa.gov/inport/item/62017) | one, T-00398 | the northeast waterfront, North Beach to Mission Creek |
| 1857 | CA37B08 | [InPort 62018](https://www.fisheries.noaa.gov/inport/item/62018) | one, T-00687 | North Beach and the Presidio to Islais Creek |

**What NOAA's records say** about how the lines were made (the same for all three):
- They are a vector conversion of the Coast Survey's shoreline manuscripts (the T-sheets). Contractors traced georeferenced scans in ArcScan and edge-matched the sheets of each project, under NOAA's Environmental Data Rescue Program. The tracing is dated 2004 (July, August and September for the three).
- Each survey is a planetable survey: 1850–1852 for CA37A02, 1853 and 1857 for the others.
- Coordinates are NAD83. NOAA says the overall horizontal accuracy "has not been determined"; the records point to project reports and a 1991 *Journal of Coastal Research* article on shoreline error.
- Each set is clipped to its project's neatline, open lines were snapped together, and a "Shoreline/Alongshore Feature Boundary" line was added to close double-lined features such as wharves. The rectangle around each set is for data management, and doesn't mean the whole rectangle was surveyed.
- Attributes use NGS's C-COAST scheme (described in [InPort 60809](https://www.fisheries.noaa.gov/inport/item/60809)). Downloads are at [ngs.noaa.gov/NSDE](https://www.ngs.noaa.gov/NSDE/).
- The CA37A02 record's title calls it Santa Catalina Island, but its extent and data are San Francisco: a slip in the record.

So the lines carry two kinds of error: the 1850s surveyors' own, and how each scan was placed when it was traced in 2004. The 60 m error in T-00352 is the second kind.

Every feature is kept except the sheets' own bounding boxes ("User Added Line" with class Cartographic). That includes wharves, marsh edges, piers and creeks.

**The Coast Survey's printed charts** at 1:10,000, in the [David Rumsey Map Collection](https://www.davidrumsey.com/). These are the published maps compiled from the T-sheets, with the streets, buildings and place names the T-sheets leave out:

- 1853: *City of San Francisco and its Vicinity*, [RUMSEY~8~1~2210~180022](https://www.davidrumsey.com/luna/servlet/detail/RUMSEY~8~1~2210~180022). Rumsey's note says the survey was finished in April 1852, and the city plan came from Eddy's official map. Its IIIF image (6,880 × 9,914 px) is at `https://www.davidrumsey.com/luna/servlet/iiif/RUMSEY~8~1~2210~180022`. A colored copy is on [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:1853_U.S.C.S._Map_of_San_Francisco,_California_%5E_Vicinity_-_Geographicus_-_SanFrancisco3-uscs-1853.jpg).
- 1857: *City of San Francisco and its Vicinity*, first edition, [RUMSEY~8~1~239938~5512085](https://davidrumsey.com/luna/servlet/detail/RUMSEY~8~1~239938~5512085).
- There is no separate 1850 chart. The 1850–52 work went into several issues of the chart as the city grew, which is why the same survey shows different coastlines.

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

### Bending a sheet onto the 1853 chart

**What is aligned to what:** today's street intersections fix the 1853 chart (below), and each digitized sheet is then tied to the chart directly, never one sheet to another. That way one sheet's error never carries into the next.

The 60 m move fixed T-00352 along the bay front, but not inland: on the same sheet, the Mission Creek marsh and North Beach still sat 25–60 m north of the chart. So after the move, the build bends the sheet:

- **Tie points** are in `data/georef/shoreline_ties.csv`: a spot on the moved 1850–52 line (`lon`, `lat`) and the same feature on the chart (`to_lon`, `to_lat`), with a note. John picked them in the tie picker, an artifact page that shows the chart under NOAA's lines: 167 so far, 166 on T-00352 and one on T-00314 (Fort Mason, as far west as the 1853 chart goes). Ties picked on the bent line are stored as the matching point on the moved line, since the two match vertex for vertex.
- **The bend** (`bend_sheets()`) fits a thin-plate spline to a sheet's ties, if it has at least 10 (`BEND_MIN_TIES`), and moves every point of the sheet by it.
  - `BEND_SMOOTH` lets it miss a tie that disagrees with its neighbors, rather than kink.
  - Farther than 300 m from every tie (`BEND_REACH_M`), it holds the value it has at that distance instead of extrapolating. That covers Islais Creek and Hunters Point, south of Pt. San Quentin, which the 1853 chart doesn't reach; they wait for the 1857 chart.
  - Within 150 m of a seam with an unbent sheet (`BEND_EASE_M`), it eases to nothing.
- **How well it fits:** the bent line passes within 2.7 m of its ties (median), 15 m at most. Holding each tie out in turn and predicting it from the others gives 5 m (median). The ties that disagree most with their neighbors are on the south edge of Mission Creek, where the marsh and water lines are smooth and close together and good ties are hard to find, and Van Ness, at the edge of the ties beside the seam.
- **Before the bend,** the ties were 29 m off (median): mostly south, and about 20 m west along the waterfront.

T-00314 (the north shore, Fort Mason west) has a single tie, so it isn't bent yet.

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

- `control_points.csv`: 149 street intersections, each with its pixel on Rumsey's scan (`px_x`, `px_y`, full size) and its place today (`lon`, `lat`, from `data/streets.json`).
- `names.csv`: the names read off the chart (`name`, `as_printed`, `kind`, pixel position, `note`). The build places them with an affine fit to the control points.
- `annotation.json`: the same control points as an [Allmaps](https://allmaps.org) georeference annotation, pointing at Rumsey's IIIF image.

**How the control points were found** (scratch scripts, not committed):

1. Start from the georeference Allmaps already had for this scan: four points, at annotations.allmaps.org.
2. For each of about 1,000 intersections in the 1853 city, draw today's streets around it (centerlines from `streets.json`, widened to their real widths: 21 m downtown, 25 m south of Market, 36.6 m for Market) into the scan's pixels.
3. Slide that drawing to where it best matches the chart's street edges, and keep the shift.
4. Fit an affine transformation with RANSAC, then keep the intersections within 10 px. That leaves 146, with **3.3 m RMS**.
5. The 146 all lie north of Townsend. Three more were added by hand from the Mission: 16th Street at Guerrero, Mission and Folsom. Before they were added, the fit was 15–20 m off there.

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
