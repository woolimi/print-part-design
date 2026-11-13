"""What every browser design viewer shares.

A design viewer is a one-file Python server and a three.js page drawing the
parts a build writes. The scene - which parts, where they hang, the sliders that
move them - is each project's own. What is the same everywhere lives here:

- the server's common routes (``KitHandler``): the page kit under ``/kit/``, the
  marks file under ``/marks``, the screws file under ``/screws``, an empty favicon;
- the page kit (``static/kit.js``, ``static/kit.css``): a click pins a point on a
  part and reads it in the page's frame and the part's own; a double click
  selects the face under it, as the outlines bound it, and reads its area,
  normal and extent; marks a script or a person writes are pinned on their
  parts, numbered, listed, and a click on the list brings the camera to one;
  the screws a build places are drawn in their holes, named beside them, and a
  click on a hole says which screw goes in it.
"""
from .server import STATIC, KitHandler, mtime, read_list, read_marks, read_screws

__all__ = ["STATIC", "KitHandler", "mtime", "read_list", "read_marks", "read_screws"]
