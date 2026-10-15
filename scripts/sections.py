#!/usr/bin/env python3
"""A part's sections across one axis, overlaid in one picture: where two
pieces of a part meet, a step shows as outlines that should coincide and do not.

    python sections.py PART.stl OUT.png --axis z --at -40,-20,-16,-15 [--scale 1000] [--box u0 u1 v0 v1]

The sections are drawn in the other two axes, in mm, coloured from the first
level to the last.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from print_flaws import read  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stl", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--axis", choices="xyz", default="z")
    ap.add_argument("--at", required=True, help="comma-separated levels, mm")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--box", type=float, nargs=4, metavar=("U0", "U1", "V0", "V1"))
    a = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    solid = read(a.stl, a.scale)
    # bring the axis to z: slice() cuts across z
    turn = {"z": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
            "x": [[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0]],      # (y, z, x)
            "y": [[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0]]}[a.axis]  # (z, x, y)
    names = {"z": "xy", "x": "yz", "y": "zx"}[a.axis]
    solid = solid.transform(turn)
    levels = [float(v) for v in a.at.split(",")]
    fig, ax = plt.subplots(figsize=(10, 8))
    for i, level in enumerate(levels):
        colour = plt.cm.viridis(i / max(1, len(levels) - 1))
        for k, poly in enumerate(solid.slice(level).to_polygons()):
            p = np.vstack([poly, poly[:1]])
            ax.plot(p[:, 0], p[:, 1], lw=0.9, color=colour, label=f"{a.axis} {level:g}" if k == 0 else None)
    if a.box:
        ax.set_xlim(a.box[0], a.box[1])
        ax.set_ylim(a.box[2], a.box[3])
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    ax.set_xlabel(names[0])
    ax.set_ylabel(names[1])
    fig.savefig(a.out, dpi=120, bbox_inches="tight")
    print(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
