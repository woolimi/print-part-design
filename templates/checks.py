"""Checks a build runs before it calls its parts done.

Each check returns a list of faults; an empty list is a pass. The build adds
them up, prints each one and exits non-zero while any are left, so every
rebuild runs them again:

    faults = []
    faults += one_solid("body", body)
    faults += fits_bed("body", body, SETTINGS.bed)
    faults += apart("body", body, "lid", lid, SETTINGS.min_gap)
    faults += slides_in("servo", servo, [body], way=(0, 0, -1))
    faults += tool_reaches("lid screw", seat, (0, 0, -1), 3.8, 6, 1.5, [body, lid])
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


def turned(part: m.Manifold, pivot, axis, deg: float) -> m.Manifold:
    """`part` turned `deg` degrees about the line through `pivot` along `axis` (right hand)."""
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    a = np.radians(deg)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    r = np.eye(3) + np.sin(a) * kx + (1 - np.cos(a)) * kx @ kx
    p = np.asarray(pivot, float)
    return part.transform(np.column_stack([r, p - r @ p]))


def turns_in(name: str, moving: m.Manifold, placed: list[m.Manifold], pivot, axis,
             start: float, end: float, allow: float = TOUCH, step_deg: float = 2.0) -> list[str]:
    """`moving`, drawn in its place at 0 deg, turns about its joint from `start` to `end`
    degrees without meeting a part in `placed`.

    For a part that only goes in with a joint bent: turn the joint (0 -> bent), slide the
    part in at the bent angle (slides_in on `turned(...)`), then turn back (bent -> 0).
    """
    n = max(1, int(np.ceil(abs(end - start) / step_deg)))
    for i in range(1, n + 1):
        deg = start + (end - start) * i / n
        s = turned(moving, pivot, axis, deg)
        for p in placed:
            v = overlap(s, p)
            if v > allow:
                return [f"{name}: meets a part at {deg:.0f} deg turning {start:.0f} -> {end:.0f} ({v:.2f} mm3)"]
    return []


def tool_reaches(name: str, seat, tip_way, head_d: float, length: float, key_d: float,
                 placed: list[m.Manifold], reach: float = 60.0, lead: float = 5.0,
                 skin: float = 0.1) -> list[str]:
    """A screw whose head sits at `seat`, pointing along `tip_way`, can be driven once the
    parts in `placed` are in: a head-wide path for the screw's `length` plus `lead` (it goes
    in straight that far; before that it can come in tilted), then a hex key `key_d` across
    flats for `reach` mm, are both clear of them.

    Overlap thinner than `skin` along the screw is a membrane left in the model that the
    printer won't lay down (less than half a layer), so it is not counted.
    """
    out = -np.asarray(tip_way, float)
    out = out / np.linalg.norm(out)
    a = np.cross(out, (1, 0, 0) if abs(out[0]) < 0.9 else (0, 1, 0))
    a = a / np.linalg.norm(a)
    frame = np.column_stack([a, np.cross(out, a), out, np.asarray(seat, float) + out * 0.2])
    key_r = key_d / np.sqrt(3)                       # across corners of the hex
    path = (m.Manifold.cylinder(length + lead, head_d / 2, head_d / 2, 24)
            + m.Manifold.cylinder(reach, key_r, key_r, 12)).transform(frame)
    for p in placed:
        hit = path ^ p
        if hit.volume() <= TOUCH:
            continue
        x0, y0, z0, x1, y1, z1 = hit.bounding_box()
        if abs(np.dot((x1 - x0, y1 - y0, z1 - z0), out)) >= skin:
            return [f"{name}: the way in for the screw or its key is blocked ({hit.volume():.2f} mm3)"]
    return []


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
