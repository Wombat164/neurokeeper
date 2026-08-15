"""Generate the neurokeeper mark: a solid tile with ONE unioned knockout.

Why a union rather than stacked subpaths: overlapping holes cancel under both fill rules
(evenodd toggles, nonzero sums to a non-zero winding), so drawing edge-quads over node-circles
re-fills notches inside every node. Unioning the geometry first gives a single closed outline,
which punches cleanly as one hole.

Emits: tile outer ring + union exterior, one path, fill-rule="evenodd".
"""
import sys

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

NODES = [(17.5, 28.5), (28.5, 42.5), (47.0, 20.0)]   # the check: left arm, vertex, right arm
NODE_R = 5.0
EDGE_W = 1.95                                         # half-width of the connecting edge
Q = 16                                                # arc segments per quarter circle


def fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ring_to_path(coords):
    pts = list(coords)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    d = [f"M{fmt(pts[0][0])} {fmt(pts[0][1])}"]
    for x, y in pts[1:]:
        d.append(f"L{fmt(x)} {fmt(y)}")
    d.append("Z")
    return "".join(d)


def main():
    edges = LineString(NODES).buffer(EDGE_W, cap_style=2, join_style=1, quad_segs=Q)
    nodes = [Point(p).buffer(NODE_R, quad_segs=Q) for p in NODES]
    glyph = unary_union([edges] + nodes)

    if glyph.geom_type != "Polygon":
        sys.exit(f"expected a single polygon, got {glyph.geom_type}: shapes are not all touching")
    if list(glyph.interiors):
        sys.exit("union has interior rings; the check should not enclose an area")

    minx, miny, maxx, maxy = glyph.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    print(f"  glyph bounds {fmt(minx)},{fmt(miny)} .. {fmt(maxx)},{fmt(maxy)}")
    print(f"  centre {fmt(cx)},{fmt(cy)}  (tile centre 32,32)")
    print(f"  outline points: {len(glyph.exterior.coords)}")

    tile = ("M14 0H50A14 14 0 0 1 64 14V50A14 14 0 0 1 50 64H14"
            "A14 14 0 0 1 0 50V14A14 14 0 0 1 14 0Z")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" '
        'aria-label="neurokeeper">\n'
        "  <title>neurokeeper</title>\n"
        '  <path fill="{fill}" fill-rule="evenodd" d="' + tile + ring_to_path(glyph.exterior.coords)
        + '"/>\n</svg>\n'
    )
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        fh.write(svg.replace("{fill}", sys.argv[2] if len(sys.argv) > 2 else "#10B981"))
    print(f"  wrote {sys.argv[1]}")


if __name__ == "__main__":
    main()
