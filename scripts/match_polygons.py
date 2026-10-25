#!/usr/bin/env python3
# sf-blocks 2026.10.22: master copy.
"""
Find the street blocks (segment CNNs) and intersections (node CNNs) inside polygons.

    python3 scripts/match_polygons.py projects.geojson                 # writes projects_cnns.csv + projects_cnns.geojson
    python3 scripts/match_polygons.py projects.geojson --name-field name --out-dir out/

Standard library only. Reads data/streets.json.

Each polygon is sorted into one of two shapes, because people draw them for two different reasons:

  thin   A strip drawn around a street: narrower than --thin-m (35 m), or at least 4 times as long
         as it is wide and narrower than --max-strip-m (60 m), like a long corridor drawn wide enough
         to take in the sidewalks. Width is estimated as 2 x area / perimeter and length as
         perimeter / 2 - width, both exact for a rectangle. Blocks count when they run along the
         strip (within 30 degrees of its long axis, or, for a strip that curves, with a stretch inside
         more than 2.2 times the strip's width, which a cross street can't have), and either half the block is inside or the
         inside stretch covers half the strip's length (a plaza drawn on part of a long block).
         "full" at 90% or more of the block inside, otherwise "partial". Cross streets that only cut
         across the strip are left out; the intersections already cover those corners.

  area   Anything else: a park, a district, a freeway right-of-way. Blocks count in any direction:
         "full" when at least 90% of the block is inside, "partial" when at least --min-partial
         (10%) is.

A thin strip with no blocks inside is often a median or a planting strip between the two sides of a
divided street, with both centerlines just outside it; it's matched again counting 10 m around the
outline, and those rows say so in "note".

A polygon with nothing inside (a parcel, a set of stairs, a plaza off the street grid) lists the
nearest block within --near-m (40 m) instead, with status "nearest" and the distance in inside_pct's
place (near_m).

Intersections count when their point is inside the polygon (or within 3 m of its edge). Intersections
where only one block meets (dead ends, the ends of paper streets) are listed too, marked kind=end.

Output, one row per polygon and CNN:
  polygon_index, polygon_name, polygon_id, shape, width_m, type (block / intersection), cnn, street,
  from_street, to_street, layer, inside_pct, status (full / partial / inside), wkt
plus a GeoJSON copy of the input polygons with cnn lists added (block_cnns, partial_cnns,
intersection_cnns), ready to load into a map.

Felt exports carry text labels as polygons ("felt:type": "Text"); those are skipped.
"""
import argparse, csv, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KX, KY = 111320 * math.cos(math.radians(37.76)), 110540        # degrees -> meters near SF
STEP_M = 2.0           # sampling step along a block when measuring how much of it is inside
EDGE_M = 3.0           # an intersection this close to the polygon's edge counts as inside
AXIS_DEG = 30          # thin polygons: blocks must run within this angle of the long axis
MEDIAN_M = 10          # thin polygons with no blocks inside: retry counting this far around the outline


# ---------------------------------------------------------------- streets.json
def load_streets(path):
    raw = json.load(open(path, encoding="utf-8"))
    S, F = raw["strings"], {f: i for i, f in enumerate(raw["seg_fields"])}
    NF = {f: i for i, f in enumerate(raw["node_fields"])}
    segs = []
    for r in raw["segs"]:
        if not r[F["flags"]] & 1:          # retired
            continue
        g, pts, x, y = r[F["geom"]], [], 0, 0
        for i in range(0, len(g), 2):
            if i == 0: x, y = g[0], g[1]
            else: x, y = x + g[i], y + g[i + 1]
            pts.append((x / 1e5 * KX, y / 1e5 * KY))
        segs.append(dict(cnn=r[F["cnn"]], street=S[r[F["streetname"]]], f=S[r[F["f_st"]]], t=S[r[F["t_st"]]],
                         layer=S[r[F["layer"]]], fn=r[F["f_node_cnn"]], tn=r[F["t_node_cnn"]], pts=pts))
    degree = {}
    for s in segs:
        for n in (s["fn"], s["tn"]):
            degree[n] = degree.get(n, 0) + 1
    nodes = [dict(cnn=n[NF["cnn"]], x=n[NF["x"]] / 1e5 * KX, y=n[NF["y"]] / 1e5 * KY,
                  streets=sorted({S[i] for i in n[NF["streets"]]}), degree=degree.get(n[NF["cnn"]], 0))
             for n in raw["nodes"] if degree.get(n[NF["cnn"]])]
    return segs, nodes


# ---------------------------------------------------------------- geometry (meters)
def to_m(ring):
    return [(c[0] * KX, c[1] * KY) for c in ring]


def in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        (xi, yi), (xj, yj) = ring[i], ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def seg_dist(x, y, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy or 1
    u = max(0, min(1, ((x - a[0]) * vx + (y - a[1]) * vy) / L2))
    return math.hypot(a[0] + u * vx - x, a[1] + u * vy - y)


class Poly:
    def __init__(self, geom):
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        self.parts = [[to_m(r) for r in p] for p in polys]
        xs = [x for p in self.parts for x, _ in p[0]]
        ys = [y for p in self.parts for _, y in p[0]]
        self.box = (min(xs), min(ys), max(xs), max(ys))
        area = perim = 0
        for p in self.parts:
            for k, r in enumerate(p):
                a = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1])) / 2
                area += abs(a) * (1 if k == 0 else -1)
                perim += sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))
        self.area, self.perim = area, perim
        self.width = 2 * area / perim if perim else 0
        self.length = max(perim / 2 - self.width, self.width)
        # long axis: principal direction of the outline's vertices
        pts = [pt for p in self.parts for pt in p[0]]
        mx, my = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
        sxx = sum((x - mx) ** 2 for x, _ in pts); syy = sum((y - my) ** 2 for _, y in pts)
        sxy = sum((x - mx) * (y - my) for x, y in pts)
        self.axis = 0.5 * math.atan2(2 * sxy, sxx - syy)

    def contains(self, x, y, edge=0.0):
        x0, y0, x1, y1 = self.box
        if x < x0 - edge or x > x1 + edge or y < y0 - edge or y > y1 + edge:
            return False
        for p in self.parts:
            if in_ring(x, y, p[0]) and not any(in_ring(x, y, h) for h in p[1:]):
                return True
        if edge:
            for p in self.parts:
                for r in p:
                    for a, b in zip(r, r[1:] + r[:1]):
                        if seg_dist(x, y, a, b) <= edge:
                            return True
        return False

    def overlaps_box(self, pts):
        x0, y0, x1, y1 = self.box
        return not (max(x for x, _ in pts) < x0 or min(x for x, _ in pts) > x1 or
                    max(y for _, y in pts) < y0 or min(y for _, y in pts) > y1)


def inside_fraction(poly, pts, edge=0.0):
    """share of a line's length inside the polygon (or within `edge` m of it), by sampling every STEP_M"""
    total = inside = 0.0
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / STEP_M))
        for i in range(n):
            u = (i + 0.5) / n
            if poly.contains(a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]), edge):
                inside += L / n
        total += L
    return inside / total if total else 0.0, total


def bearing_diff(pts, axis):
    """angle in degrees between a block's overall direction and an axis (0-90)"""
    dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
    d = abs(math.degrees(math.atan2(dy, dx) - axis)) % 180
    return min(d, 180 - d)


# ---------------------------------------------------------------- matching
def line_dist(poly, pts):
    """shortest distance between a line and the polygon's outline (0 if they cross or touch)"""
    best = math.inf
    for p in poly.parts:
        for r in p:
            for a, b in zip(r, r[1:] + r[:1]):
                for q in pts:
                    best = min(best, seg_dist(q[0], q[1], a, b))
                for c, d in zip(pts, pts[1:]):
                    best = min(best, seg_dist(a[0], a[1], c, d))
    return best


def match(poly, segs, nodes, a, edge=0.0):
    strip = poly.width < a.thin_m or (poly.length >= 4 * poly.width and poly.width < a.max_strip_m)
    shape = "thin" if strip else "area"
    rows = []
    for s in segs:
        if not poly.overlaps_box(s["pts"]) and not (edge and poly.overlaps_box([(x + d, y + d) for x, y in s["pts"] for d in (-edge, edge)])):
            continue
        frac, length = inside_fraction(poly, s["pts"], edge)
        if frac <= 0:
            continue
        if shape == "thin":
            # along the strip: same direction as its long axis, or (for a strip that curves) a stretch
            # inside much longer than the strip is wide, which a street cutting across can't have
            along = bearing_diff(s["pts"], poly.axis) <= AXIS_DEG or frac * length >= 2.2 * (poly.width + 2 * edge) or frac >= 0.9
            if not along or (frac < 0.5 and frac * length < 0.5 * poly.length):
                continue
        elif frac < a.min_partial:
            continue
        rows.append(dict(type="block", cnn=s["cnn"], street=s["street"], from_street=s["f"], to_street=s["t"],
                         layer=s["layer"], inside_pct=round(frac * 100), status="full" if frac >= 0.9 else "partial",
                         note=f"within {edge:g} m of the outline" if edge else "", wkt=line_wkt(s["pts"])))
    for n in nodes:
        if poly.contains(n["x"], n["y"], EDGE_M):
            rows.append(dict(type="intersection", cnn=n["cnn"], street=n["streets"][0] if n["streets"] else "",
                             from_street=" & ".join(n["streets"][1:]), to_street="", layer="",
                             inside_pct=100, status="inside" if n["degree"] > 1 else "end",
                             wkt=f"POINT ({n['x'] / KX:.6f} {n['y'] / KY:.6f})"))
    # A thin strip with no blocks may be a median or a sidewalk strip between the two sides of a
    # divided street, whose centerlines run just outside it: try again counting MEDIAN_M around it.
    if shape == "thin" and not edge and not any(r["type"] == "block" for r in rows):
        retry = match(poly, segs, nodes, a, MEDIAN_M)[1]
        if any(r["type"] == "block" and r["status"] != "nearest" for r in retry):
            return shape, retry
    if not rows:          # nothing inside: the nearest block, if it's close
        best = None
        for s in segs:
            x0, y0, x1, y1 = poly.box
            if max(x for x, _ in s["pts"]) < x0 - a.near_m or min(x for x, _ in s["pts"]) > x1 + a.near_m or \
               max(y for _, y in s["pts"]) < y0 - a.near_m or min(y for _, y in s["pts"]) > y1 + a.near_m:
                continue
            d = line_dist(poly, s["pts"])
            if d <= a.near_m and (best is None or d < best[0]):
                best = (d, s)
        if best:
            d, s = best
            rows.append(dict(type="block", cnn=s["cnn"], street=s["street"], from_street=s["f"], to_street=s["t"],
                             layer=s["layer"], inside_pct=0, near_m=round(d), status="nearest", wkt=line_wkt(s["pts"])))
    rows.sort(key=lambda r: (r["type"] != "block", r["street"], r["cnn"]))
    return shape, rows


def line_wkt(pts):
    return "LINESTRING (" + ", ".join(f"{x / KX:.6f} {y / KY:.6f}" for x, y in pts) + ")"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("geojson")
    ap.add_argument("--streets", default=os.path.join(ROOT, "data", "streets.json"))
    ap.add_argument("--name-field", default="name")
    ap.add_argument("--thin-m", type=float, default=35, help="polygons narrower than this are street strips (default 35 m)")
    ap.add_argument("--max-strip-m", type=float, default=60, help="long strips up to this wide still count as thin (default 60 m)")
    ap.add_argument("--near-m", type=float, default=40, help="polygons with nothing inside: nearest block within this (default 40 m)")
    ap.add_argument("--min-partial", type=float, default=0.1, help="area polygons: smallest share of a block to list (default 0.1)")
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args()

    segs, nodes = load_streets(a.streets)
    data = json.load(open(a.geojson, encoding="utf-8"))
    base = os.path.splitext(os.path.basename(a.geojson))[0]
    out_dir = a.out_dir or os.path.dirname(os.path.abspath(a.geojson))
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, base + "_cnns.csv")
    gj_path = os.path.join(out_dir, base + "_cnns.geojson")

    cols = ["polygon_index", "polygon_name", "polygon_id", "shape", "width_m", "type", "cnn", "street",
            "from_street", "to_street", "layer", "inside_pct", "near_m", "status", "note", "wkt"]
    out_feats, n_rows, summary = [], 0, []
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, f in enumerate(data["features"]):
            g, p = f.get("geometry"), f.get("properties") or {}
            if not g or g["type"] not in ("Polygon", "MultiPolygon") or p.get("felt:type") == "Text":
                continue
            poly = Poly(g)
            shape, rows = match(poly, segs, nodes, a)
            name, pid = p.get(a.name_field, ""), p.get("felt:id") or p.get("id") or ""
            for r in rows:
                w.writerow(dict(polygon_index=i, polygon_name=name, polygon_id=pid, shape=shape,
                                width_m=round(poly.width), **r))
            n_rows += len(rows)
            blocks = [r for r in rows if r["type"] == "block"]
            props = dict(p, cnn_shape=shape, cnn_width_m=round(poly.width),
                         block_cnns=[r["cnn"] for r in blocks if r["status"] == "full"],
                         partial_cnns=[r["cnn"] for r in blocks if r["status"] == "partial"],
                         nearest_cnn=next((r["cnn"] for r in blocks if r["status"] == "nearest"), None),
                         intersection_cnns=[r["cnn"] for r in rows if r["type"] == "intersection"])
            out_feats.append(dict(type="Feature", geometry=g, properties=props))
            summary.append((name, shape, round(poly.width), len(props["block_cnns"]), len(props["partial_cnns"]),
                            len(props["intersection_cnns"]), props["nearest_cnn"]))
    json.dump(dict(type="FeatureCollection", features=out_feats), open(gj_path, "w", encoding="utf-8"))
    for s in summary:
        print(f"{s[0][:44]:44}  {s[1]:5} {s[2]:4} m  blocks {s[3]:3}  partial {s[4]:3}  intersections {s[5]:3}"
              + (f"  nearest {s[6]}" if s[6] else ""))
    print(f"\n{len(out_feats)} polygons, {n_rows} rows -> {csv_path}\n{'':>17}-> {gj_path}")


if __name__ == "__main__":
    main()
