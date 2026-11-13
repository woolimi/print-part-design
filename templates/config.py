"""Where this project reads from and writes to."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    """The single source of truth for every path and port these scripts use."""

    #: the page's title
    title: str = "project"
    #: the pose the view writes and the build reads
    pose_yaml: Path = REPO / "config" / "pose.yaml"
    #: printed parts, millimetres, one STL each
    print: Path = REPO / "print"
    #: what the view draws beside the prints, and assembly.json
    meshes: Path = REPO / "meshes"
    #: the project's venv the build runs in (the page may have been started from any python)
    python: Path = REPO / ".venv" / "bin" / "python"
    #: the design view's port: one free port per viewer running on the machine
    port: int = 8790
    #: spots the view pins for whoever looks (partview marks); not committed
    marks: Path = REPO / "marks.json"
    #: what goes into each hole, as the build places the screws (partview screws)
    screws: Path = REPO / "meshes" / "screws.json"


SETTINGS = Settings()
