#!/usr/bin/env python3
"""The printed parts as STEP, for CAD.

Each part's STL becomes a solid: its triangles are sewn shut, then triangles
lying in one plane are merged back into one face, so a box comes out as six
faces and only curved surfaces stay faceted. Writes one STEP per part and an
assembly STEP with every part named and placed as assembly.json places it,
each in the colour the view draws it.

    .venv/bin/python scripts/export_step.py      # step/<part>.step, step/assembly.step

Needs cadquery-ocp (`pip install cadquery-ocp`).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import SETTINGS  # noqa: E402
from design_view import ASSEMBLY, PARTS  # noqa: E402

OUT = SETTINGS.print.parent / "step"
SEW_TOL = 1e-3          # mm: vertices closer than this are one vertex


def read_stl(path: Path) -> np.ndarray:
    """Binary or ASCII STL -> (n, 3, 3) float array of triangles."""
    data = path.read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        v = [list(map(float, line.split()[1:4])) for line in data.decode(errors="ignore").splitlines()
             if line.strip().startswith("vertex")]
        return np.array(v, float).reshape(-1, 3, 3)
    n = int.from_bytes(data[80:84], "little")
    rec = np.frombuffer(data, dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]), count=n, offset=84)
    return rec["v"].astype(float).reshape(-1, 3, 3)


def solid_from_triangles(tris: np.ndarray):
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon,
                                    BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing)
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.gp import gp_Pnt
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    sew = BRepBuilderAPI_Sewing(SEW_TOL)
    for a, b, c in tris:
        if np.linalg.norm(np.cross(b - a, c - a)) < 1e-12:
            continue                                   # a degenerate sliver
        poly = BRepBuilderAPI_MakePolygon(gp_Pnt(*a), gp_Pnt(*b), gp_Pnt(*c), True)
        sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    made = BRepBuilderAPI_MakeSolid()
    while ex.More():
        made.Add(TopoDS.Shell_s(ex.Current()))
        ex.Next()
    # booleans leave slivers a hair wide; sewn at SEW_TOL they can fold, and
    # the fixer mends that
    fix = ShapeFix_Solid(made.Solid())
    fix.Perform()
    solid = fix.Solid()
    unify = ShapeUpgrade_UnifySameDomain(solid, True, True, False)
    unify.Build()
    if BRepCheck_Analyzer(unify.Shape()).IsValid():
        return unify.Shape()
    # merging planes broke something: keep the sewn triangles, every face exact
    return solid


def placement(m) -> "gp_Trsf":
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    m = np.asarray(m, float)
    t.SetValues(*m[0], *m[1], *m[2])
    return t


@contextlib.contextmanager
def quiet():
    """OCCT prints its transfer statistics straight to fd 1."""
    sys.stdout.flush()
    keep, null = os.dup(1), os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    try:
        yield
    finally:
        os.dup2(keep, 1)
        os.close(keep)
        os.close(null)


def colour(hex_rgb: str):
    """'#rrggbb' as the view's page takes it -> an OCCT colour."""
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    r, g, b = (int(hex_rgb[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return Quantity_Color(r, g, b, Quantity_TOC_sRGB)


def new_doc():
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    return TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))


def add_part(doc, shape, name: str, hex_rgb: str):
    """The shape into the document, named and coloured; returns its label."""
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.XCAFDoc import XCAFDoc_ColorGen, XCAFDoc_DocumentTool
    label = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()).AddShape(shape, False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    XCAFDoc_DocumentTool.ColorTool_s(doc.Main()).SetColor(label, colour(hex_rgb), XCAFDoc_ColorGen)
    return label


def write_step(doc, path: Path) -> None:
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer()
    with quiet():
        w.Transfer(doc, STEPControl_AsIs)
    with quiet():
        done = w.Write(str(path))
    if done != IFSelect_RetDone:
        raise SystemExit(f"could not write {path}")


def main() -> None:
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    OUT.mkdir(exist_ok=True)
    groups = json.loads(ASSEMBLY.read_text()).get("groups", {}) if ASSEMBLY.is_file() else {}
    doc = new_doc()
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    top = tool.NewShape()
    TDataStd_Name.Set_s(top, TCollection_ExtendedString(SETTINGS.title))
    for name, (stl, hex_rgb, group) in PARTS.items():
        if not stl.is_file():
            print(f"  {name}: no {stl.name}, skipped")
            continue
        tris = read_stl(stl)
        shape = solid_from_triangles(tris)
        one = new_doc()
        add_part(one, shape, name, hex_rgb)
        write_step(one, OUT / f"{name}.step")
        label = add_part(doc, shape, name, hex_rgb)
        loc = TopLoc_Location(placement(groups[group])) if group in groups else TopLoc_Location()
        comp = tool.AddComponent(top, label, loc)
        TDataStd_Name.Set_s(comp, TCollection_ExtendedString(name))
        print(f"  {name}: {len(tris)} triangles -> step/{name}.step", flush=True)
    tool.UpdateAssemblies()
    write_step(doc, OUT / "assembly.step")
    print(f"  assembly: {len(PARTS)} parts, placed as assembly.json has them -> step/assembly.step")


if __name__ == "__main__":
    main()
