"""Checks a build runs before it calls its parts done.

Each check returns a list of faults; an empty list is a pass. The build adds
them up, prints each one and exits non-zero while any are left, so every
rebuild runs them again:

    faults = []
    faults += one_solid("body", body)
    faults += fits_bed("body", body, SETTINGS.bed)
    faults += apart("body", body, "lid", lid, SETTINGS.min_gap)
    faults += slides_in("servo", servo, [body], way=(0, 0, -1))
    faults += no_worse("servo in body", overlap(servo, body), SETTINGS.reference["servo in body"])
    for f in faults:
        print("FAIL", f)
    sys.exit(1 if faults else 0)

Parts are manifold3d Manifolds placed as assembled, in millimetres; volumes
are in cubic millimetres.
"""
from __future__ import annotations

import manifold3d as m
import numpy as np

#: mm3: an overlap below this is boolean noise, not contact
TOUCH = 0.01
#: mm between the positions a slide is checked at
STEP = 0.5
#: mm: a gap this much under the minimum is float noise
EPS = 1e-6


def overlap(a: m.Manifold, b: m.Manifold) -> float:
    """How much of a and b is the same space, mm3."""
    return (a ^ b).volume()


def one_solid(name: str, part: m.Manifold) -> list[str]:
    """The part is one closed, valid solid: no loose pieces, no open edges."""
    if part.status() != m.Error.NoError:
        return [f"{name}: not a valid solid ({part.status()})"]
    if part.is_empty():
        return [f"{name}: empty"]
    pieces = len(part.decompose())
    return [] if pieces == 1 else [f"{name}: {pieces} separate pieces, expected one"]


def fits_bed(name: str, part: m.Manifold, bed: tuple[float, float, float]) -> list[str]:
    """The part, lying as drawn, fits the printer's build volume."""
    x0, y0, z0, x1, y1, z1 = part.bounding_box()
    size = (x1 - x0, y1 - y0, z1 - z0)
    if all(s <= b for s, b in zip(size, bed)):
        return []
    return [f"{name}: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm exceeds the bed {bed}"]


def apart(a_name: str, a: m.Manifold, b_name: str, b: m.Manifold, min_gap: float) -> list[str]:
    """Assembled, a and b do not overlap and come no closer than min_gap."""
    v = overlap(a, b)
    if v > TOUCH:
        return [f"{a_name}-{b_name}: overlap {v:.3f} mm3 assembled"]
    gap = a.min_gap(b, min_gap + 1.0)
    if gap < min_gap - EPS:
        return [f"{a_name}-{b_name}: {gap:.2f} mm apart, under {min_gap} mm"]
    return []


def slides_in(name: str, moving: m.Manifold, placed: list[m.Manifold], way,
              allow: float = TOUCH, step: float = STEP) -> list[str]:
    """`moving`, drawn in its place, goes in along `way` from clear of every part in
    `placed` without meeting one of them on the way.

    It is backed off against `way` until it is clear of them all, then brought in
    a step at a time; at each step its overlap with each placed part must stay
    under `allow` - the overlap it is allowed in its place, when the reference
    part already overlaps there (see no_worse).
    """
    way = np.asarray(way, float)
    way = way / np.linalg.norm(way)

    def along(part: m.Manifold) -> np.ndarray:
        verts = np.asarray(part.to_mesh().vert_properties)[:, :3]
        return verts @ way

    travel = max(along(p).max() for p in placed) - along(moving).min() + step
    hits = []
    for k in range(1, int(np.ceil(travel / step)) + 1):
        d = k * step
        back = moving.translate(tuple(-way * d))
        if any(overlap(back, p) > allow for p in placed):
            hits.append(d)
    if not hits:
        return []
    return [f"{name}: meets a part {hits[0]:.1f}-{hits[-1]:.1f} mm before its place, "
            f"going in along {tuple(round(float(c), 3) for c in way)}"]


def no_worse(what: str, value: float, baseline: float, slack: float = TOUCH) -> list[str]:
    """`value` is no larger than the same measure on the reference build - the
    upstream original or the last build that went together for real."""
    if value <= baseline + slack:
        return []
    return [f"{what}: {value:.2f} mm3, {baseline:.2f} mm3 in the reference"]


def sides(housing: m.Manifold, seat_normal, seat_offset: float, lift: float = 0.05) -> m.Manifold:
    """The housing without what lies under the plane a part is seated on, so that
    `apart(part, sides(...))` measures the room round the part's sides, not the
    face it sits on. The plane is `seat_normal . p = seat_offset`, the normal
    pointing away from the seat into the pocket."""
    n = np.asarray(seat_normal, float)
    n = n / np.linalg.norm(n)
    return housing.trim_by_plane(tuple(n), seat_offset + lift)
