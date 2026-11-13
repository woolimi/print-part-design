"""The server side every viewer shares: the kit's files, the marks, the screws, the favicon."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def mtime(path: Path | None) -> float:
    """A file's modification time, 0 while it is not there."""
    return path.stat().st_mtime if path is not None and path.is_file() else 0.0


def read_list(path: Path | None) -> list:
    """A JSON file's list: none while there is no file, or it does not parse."""
    if path is None:
        return []
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return found if isinstance(found, list) else []


def read_marks(path: Path | None) -> list:
    """The marks file's list: none while there is no file, or it does not parse.

    Each mark is ``{"part", "at", "box"?, "label"?, "note"?, "view"?, "from"?, "faces"?}`` -
    a point (and a box about it) in that part's own STL frame, in millimetres;
    how far off to stand when the camera is brought to it, also in millimetres;
    the direction to look from, in the part's frame; and a direction, also in
    the part's frame, whose faces inside the box are painted through the rest.
    What a ``part`` names is the viewer's own: a part's name in its table, or
    its file name.
    """
    return read_list(path)


def read_screws(path: Path | None) -> list:
    """The screws file's list: what goes into each hole, as the build placed it.

    Each screw is ``{"part", "at", "axis", "d", "len", "spec", "head"?, "into"?,
    "note"?, "label"?}`` in that part's own STL frame, in millimetres: ``at``
    where the head bears, ``axis`` the way the screw goes in, ``d`` its size
    across the thread, ``len`` the thread's length from ``at``, ``head`` the
    head's ``[diameter, height]`` behind ``at`` (none for a set screw). ``spec``
    names the screw, ``into`` what it threads into, ``label`` the short name
    drawn beside it (``spec`` if none).
    """
    return read_list(path)


class KitHandler(BaseHTTPRequestHandler):
    """A viewer's handler: its own routes, after the ones every viewer serves.

        class Handler(KitHandler):
            marks = SETTINGS.marks
            screws = SETTINGS.screws
            def do_GET(self):
                path = self.path.split("?")[0]
                if self.kit(path):
                    return
                ...
    """

    marks: Path | None = None
    screws: Path | None = None

    def log_message(self, *args):  # quiet
        pass

    def send_body(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def kit(self, path: str) -> bool:
        """Serve one of the routes every viewer has; False if `path` is not one."""
        if path.startswith("/kit/"):
            name = path[len("/kit/"):]
            file = STATIC / name
            if "/" in name or not file.is_file():
                self.send_error(404)
            else:
                self.send_body(file.read_bytes(), TYPES.get(file.suffix, "application/octet-stream"))
        elif path == "/marks":
            self.send_body(json.dumps(read_marks(self.marks)).encode(), "application/json")
        elif path == "/screws":
            self.send_body(json.dumps(read_screws(self.screws)).encode(), "application/json")
        elif path == "/favicon.ico":
            self.send_body(b"", "image/x-icon", 204)
        else:
            return False
        return True
