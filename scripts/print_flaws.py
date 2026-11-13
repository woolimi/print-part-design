#!/usr/bin/env python3
"""Small flaws in a printed part's mesh: what the viewer shows as two outline
lines close together, specks of faces, loose pieces and sealed voids.

    python print_flaws.py PART.stl [--scale 1000] [--width 1.2] [--box x0 x1 y0 y1 z0 z1]
    python print_flaws.py PART.stl --against OLD.stl     # what a fix changed

Faces are grouped into regions across every edge where the surface bends less
than --sharp degrees, so a region is one face as the viewer outlines it. Reported:

  strip   a region narrower than --width (2 x area / sharp boundary length):
          a step's riser, a ledge, a sliver left by two cuts that nearly agree
  speck   a region smaller than --speck mm2 whatever its shape: a chip, a
          facet a boolean left standing
  piece   a loose solid besides the largest
  void    a sealed cavity inside the solid

Coordinates are printed in mm in the STL's own frame (times --scale), which is
what a viewer's "in its own frame" probe reads, so a line can be found by
clicking there. A curved face that is tessellated coarser than --sharp shows up
as many strips side by side along one direction: that is facets, not a flaw.

--against prints the volume each way between two versions and the largest
distance of the new surface from the old one: a shape-keeping fix moves
little volume and few millimetres.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import manifold3d as m
import numpy as np


def read(path: Path, scale: float) -> m.Manifold:
    data = path.read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        nums = [float(w) for line in data.decode().splitlines()
                if line.strip().startswith("vertex") for w in line.split()[1:4]]
        tris = np.array(nums).reshape(-1, 3, 3)
    else:
        count = struct.unpack("<I", data[80:84])[0]
        rows = np.frombuffer(data[84:84 + 50 * count],
                             dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        tris = rows["v"].astype(np.float64)
    verts = tris.reshape(-1, 3) * scale
    unique, index = np.unique(np.round(verts, 4), axis=0, return_inverse=True)
    solid = m.Manifold(m.Mesh(vert_properties=unique.astype(np.float32),
                              tri_verts=index.reshape(-1, 3).astype(np.uint32)))
    if solid.status() != m.Error.NoError:
        sys.exit(f"{path.name}: not a closed solid ({solid.status()})")
    return solid


class Regions:
    """The surface split into faces at its sharp edges."""

    def __init__(self, solid: m.Manifold, sharp: float):
        mesh = solid.to_mesh()
        p = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        t = np.asarray(mesh.tri_verts, dtype=np.int64)
        # the manifold's own seams (merge_from -> merge_to) welded, so edges pair up
        weld = np.arange(len(p))
        weld[np.asarray(mesh.merge_from_vert, dtype=np.int64)] = np.asarray(mesh.merge_to_vert, dtype=np.int64)
        t = weld[t]
        a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
        n = np.cross(b - a, c - a)
        self.area = np.linalg.norm(n, axis=1) / 2
        self.normal = n / np.maximum(2 * self.area[:, None], 1e-15)
        self.p, self.t = p, t

        # every edge with the two faces on it
        e = np.stack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=1).reshape(-1, 2)
        face = np.repeat(np.arange(len(t)), 3)
        key = np.sort(e, axis=1)
        order = np.lexsort((key[:, 1], key[:, 0]))
        key, face = key[order], face[order]
        same = np.all(key[:-1] == key[1:], axis=1)
        i = np.flatnonzero(same)
        self.edge_v = key[i]                       # (k, 2) vertex ids
        self.edge_f = np.stack([face[i], face[i + 1]], axis=1)
        cos = np.cos(np.radians(sharp))
        dot = np.einsum("ij,ij->i", self.normal[self.edge_f[:, 0]], self.normal[self.edge_f[:, 1]])
        tiny = (self.area[self.edge_f[:, 0]] < 1e-9) | (self.area[self.edge_f[:, 1]] < 1e-9)
        smooth = tiny | (dot >= cos)
        self.sharp = ~smooth

        parent = np.arange(len(t))

        def find(x):
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:
                parent[x], x = root, parent[x]
            return root

        for f0, f1 in self.edge_f[smooth]:
            r0, r1 = find(f0), find(f1)
            if r0 != r1:
                parent[r0] = r1
        self.region = np.array([find(f) for f in range(len(t))])

    def table(self):
        """(width, length, area, centre, lo, hi, normal) for every region."""
        length_of = np.linalg.norm(self.p[self.edge_v[:, 0]] - self.p[self.edge_v[:, 1]], axis=1)
        per = np.zeros(len(self.t))
        for (f0, f1), L in zip(self.edge_f[self.sharp], length_of[self.sharp]):
            per[self.region[f0]] += L
            per[self.region[f1]] += L
        out = []
        for r in np.unique(self.region):
            idx = np.flatnonzero(self.region == r)
            A = float(self.area[idx].sum())
            if A < 1e-6:
                continue
            pts = self.p[self.t[idx].reshape(-1)]
            lo, hi = pts.min(0), pts.max(0)
            nn = (self.normal[idx] * self.area[idx, None]).sum(0)
            nn /= max(np.linalg.norm(nn), 1e-12)
            centre = (self.p[self.t[idx]].mean(1) * self.area[idx, None]).sum(0) / A
            width = 2 * A / per[r] if per[r] > 0 else np.inf
            out.append((width, float(np.linalg.norm(hi - lo)), A, centre, lo, hi, nn))
        return out


def fmt(v):
    return "(" + ", ".join(f"{x:7.1f}" for x in v) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stl", type=Path)
    ap.add_argument("--scale", type=float, default=1.0, help="to mm: 1000 for a mesh in metres")
    ap.add_argument("--sharp", type=float, default=25.0, help="degrees a face bends at an outlined edge")
    ap.add_argument("--width", type=float, default=1.2, help="mm: narrower is a strip")
    ap.add_argument("--speck", type=float, default=0.5, help="mm2: smaller is a speck")
    ap.add_argument("--min-length", type=float, default=1.0, help="mm: shorter strips are left to --speck")
    ap.add_argument("--box", type=float, nargs=6, metavar=("X0", "X1", "Y0", "Y1", "Z0", "Z1"),
                    help="only what is centred inside this box, mm")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--against", type=Path, help="an earlier version, to measure what changed")
    ap.add_argument("--up", type=float, nargs=3, metavar=("X", "Y", "Z"),
                    help="the build direction in the STL's frame: also list the faces that hang over")
    ap.add_argument("--overhang", type=float, default=45.0,
                    help="degrees from vertical a face may lean down before it needs support")
    ap.add_argument("--bed", type=float, default=0.4,
                    help="mm: a patch no higher than this is the first layers' round, not an overhang")
    a = ap.parse_args()

    solid = read(a.stl, a.scale)
    lo, hi = np.array(solid.bounding_box()[:3]), np.array(solid.bounding_box()[3:])
    print(f"{a.stl.name}: {solid.volume():.1f} mm3, {solid.num_tri()} triangles, "
          f"box {fmt(lo)} .. {fmt(hi)}")

    if a.against:
        old = read(a.against, a.scale)
        added, removed = solid - old, old - solid
        print(f"  against {a.against.name}: +{added.volume():.2f} mm3 added, "
              f"-{removed.volume():.2f} mm3 removed, net {solid.volume() - old.volume():+.2f}")
        # each changed piece: where, its box, and how thick it is on average
        # (2 x volume / surface) - about how far the surface moved there. A
        # merge of the triangles shows as wide pieces a few microns thick.
        for sign, diff in (("+", added), ("-", removed)):
            for s in sorted(diff.decompose(), key=lambda s: -s.volume()):
                if s.volume() < 0.05:
                    continue
                b = np.array(s.bounding_box())
                print(f"  {sign}{s.volume():9.2f} mm3  {2 * s.volume() / s.surface_area():5.3f} thick  "
                      f"{fmt(b[:3])} .. {fmt(b[3:])}")

    pieces = sorted(solid.decompose(), key=lambda s: -abs(s.volume()))
    loose = [s for s in pieces[1:] if s.volume() > 0]
    voids = [s for s in pieces if s.volume() < 0]
    for s in loose:
        b = s.bounding_box()
        print(f"  piece  {s.volume():8.3f} mm3   {fmt(b[:3])} .. {fmt(b[3:])}")
    for s in voids:
        b = s.bounding_box()
        print(f"  void   {s.volume():8.3f} mm3   {fmt(b[:3])} .. {fmt(b[3:])}")

    rows = Regions(solid, a.sharp).table()
    if a.box:
        x0, x1, y0, y1, z0, z1 = a.box
        rows = [r for r in rows if x0 <= r[3][0] <= x1 and y0 <= r[3][1] <= y1 and z0 <= r[3][2] <= z1]
    strips = sorted((r for r in rows if r[0] < a.width and r[1] >= a.min_length), key=lambda r: -r[1])
    specks = sorted((r for r in rows if r[2] < a.speck and not (r[0] < a.width and r[1] >= a.min_length)),
                    key=lambda r: r[2])
    print(f"  {len(rows)} faces, {len(strips)} strips under {a.width} mm, {len(specks)} specks under {a.speck} mm2")
    for w, L, A, c, lo_, hi_, n in strips[:a.limit]:
        print(f"  strip  w {w:4.2f} len {L:5.1f}  at {fmt(c)}  x {lo_[0]:6.1f}..{hi_[0]:6.1f} "
              f"y {lo_[1]:6.1f}..{hi_[1]:6.1f} z {lo_[2]:6.1f}..{hi_[2]:6.1f}  n ({n[0]:+.2f},{n[1]:+.2f},{n[2]:+.2f})")
    for w, L, A, c, lo_, hi_, n in specks[:a.limit]:
        print(f"  speck  {A:5.3f} mm2  at {fmt(c)}  n ({n[0]:+.2f},{n[1]:+.2f},{n[2]:+.2f})")

    if a.up:
        for row in overhangs(solid, np.array(a.up, dtype=np.float64), a.overhang, a.bed)[:a.limit]:
            A, height, c, lo_, hi_, kind, size = row
            print(f"  over   {A:8.2f} mm2  {height:5.1f} up  {kind:10s} {size:5.1f} mm  at {fmt(c)}  "
                  f"x {lo_[0]:6.1f}..{hi_[0]:6.1f} y {lo_[1]:6.1f}..{hi_[1]:6.1f} z {lo_[2]:6.1f}..{hi_[2]:6.1f}")
    return 0


def overhangs(solid: m.Manifold, up: np.ndarray, angle: float, bed: float):
    """Patches of triangles turned down past `angle` from vertical, off the bed,
    each as (area, height above the bed, centre, lo, hi), smallest first: what
    the slicer supports, or what sags if it does not. A small one is the worst
    kind - a support's scar for a ledge nobody sees. A face at the angle itself
    (a teardrop's point) is not one, and neither is a patch that stays within
    `bed` of the bed."""
    up = up / np.linalg.norm(up)
    r = Regions(solid, 180.0)                 # every edge smooth: only the adjacency is used
    limit = -np.sin(np.radians(90.0 - angle)) - 0.01
    h = r.p @ up
    lowest = float(h.min())
    down = r.normal @ up
    tri_h = h[r.t].mean(axis=1)
    hang = (down < limit) & ~((down < -0.999) & (np.abs(tri_h - lowest) < 0.05)) & (r.area > 1e-9)
    parent = np.arange(len(r.t))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for f0, f1 in r.edge_f:
        if hang[f0] and hang[f1]:
            a_, b_ = find(f0), find(f1)
            if a_ != b_:
                parent[a_] = b_
    groups = {}
    for f in np.flatnonzero(hang):
        groups.setdefault(find(f), []).append(f)
    out = []
    # which triangle is across each edge, to read what holds a patch up
    across = {}
    for (f0, f1) in r.edge_f:
        across.setdefault(int(f0), []).append(int(f1))
        across.setdefault(int(f1), []).append(int(f0))
    flat = lambda v: v - (v @ up) * up
    for idx in groups.values():
        idx = np.array(idx)
        A = float(r.area[idx].sum())
        pts = r.p[r.t[idx].reshape(-1)]
        if float((pts @ up).max()) - lowest <= bed:
            continue
        c = (r.p[r.t[idx]].mean(1) * r.area[idx, None]).sum(0) / A
        kind = hold(r, idx, across, up, flat)
        out.append((A, float(c @ up) - lowest, c, pts.min(0), pts.max(0)) + kind)
    out.sort(key=lambda row: row[0])
    print(f"  {len(out)} patches hang over (more than {angle:g} deg from vertical), "
          f"{sum(row[0] for row in out):.0f} mm2; smallest first:")
    return out


def hold(r, idx, across, up, flat, reach=15.0):
    """What holds a patch up: ('bridge', span) when every part of it has a wall
    going down on two opposite sides within `reach` mm - a slicer bridges it -
    ('cantilever', length) when walls hold it on one side only, length being
    how far its furthest point stands from them, or ('island', 0) when nothing
    under its edges holds it."""
    inside = set(idx.tolist())
    anchors = []
    for f in idx:
        for o in across.get(int(f), []):
            if o in inside:
                continue
            # the triangle across the patch's edge: a wall that goes down from it
            n = r.normal[o]
            if abs(n @ up) > 0.7:
                continue
            shared = set(r.t[f].tolist()) & set(r.t[o].tolist())
            other = [v for v in r.t[o].tolist() if v not in shared]
            if not other or not shared:
                continue
            edge_h = np.mean([r.p[v] @ up for v in shared])
            if r.p[other[0]] @ up < edge_h - 1e-6:
                anchors.append(flat(np.mean([r.p[v] for v in shared], axis=0)))
    if not anchors:
        return ("island", 0.0)
    anchors = np.array(anchors)
    cents = np.array([flat(r.p[r.t[f]].mean(0)) for f in idx])
    worst_bridge, worst_reach, both = 0.0, 0.0, True
    for c in cents:
        d = anchors - c
        dist = np.linalg.norm(d, axis=1)
        near = int(np.argmin(dist))
        worst_reach = max(worst_reach, float(dist[near]))
        u = d[near] / max(dist[near], 1e-9)
        opposite = (d @ u < -0.5 * dist) & (dist <= reach)
        if dist[near] > 1e-6 and not opposite.any():
            both = False
        elif opposite.any():
            worst_bridge = max(worst_bridge, float(dist[near] + dist[opposite].min()))
    return ("bridge", worst_bridge) if both else ("cantilever", worst_reach)


if __name__ == "__main__":
    sys.exit(main())
