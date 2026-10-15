# partview

What every browser design viewer shares. A design viewer is a one-file Python
server and a three.js page that draws the parts a build writes (manifold3d →
STL) and reloads them as they change. The scene - which parts, where they hang,
the sliders that move them - belongs to each project. This package holds the
rest, so a fix or a feature lands in every viewer at once.

| Where | What |
|---|---|
| `partview.KitHandler` | the server's common routes: `/kit/kit.js`, `/kit/kit.css`, `/marks`, `/screws`, an empty favicon |
| `partview.mtime`, `partview.read_marks`, `partview.read_screws` | a file's mtime for the page's reload check; the marks file's list; the screws file's list |
| `static/kit.js` `picker` | click: pin a point, read it in the page's frame and the part's own STL frame, and, in a hole the screws file names, which screw goes in it. Double click: select the face under the pointer - a flat face up to where the surface turns, or a whole hole or round - and read its area, normal, plane and extent |
| `static/kit.js` `marks` | the spots the marks file names, pinned on their parts through whatever is in front, numbered, listed; a click on the list brings the camera to one |
| `static/kit.js` `screws` | the screws the build places, drawn in their holes through whatever is in front, each named beside it |
| `static/kit.js` `copyOnClick` | a readout line that copies itself |

## Install

Into the environment the viewer runs in, from the skill's `kit/` directory:

    pip install -e ~/.claude/skills/print-part-design/kit                                 # a pip environment
    uv pip install --python .venv/bin/python -e ~/.claude/skills/print-part-design/kit   # a uv one

Editable, so a change here reaches every viewer the next time it starts.

## Use

Server:

```python
from partview import KitHandler, mtime

class Handler(KitHandler):
    marks = SETTINGS.marks          # the project's marks file
    screws = SETTINGS.screws        # the screws file the build writes

    def do_GET(self):
        path = self.path.split("?")[0]
        if self.kit(path):
            return
        ...                         # the viewer's own routes; self.send_body(...)
```

Add `"marks": mtime(SETTINGS.marks)` and `"screws": mtime(SETTINGS.screws)` to the
mtimes the page polls.

Page:

```html
<link rel="stylesheet" href="/kit/kit.css">
<div id="tags"></div>                                   <!-- the marks' numbers -->
<div id="marks" class="dv-marks"></div>                 <!-- the marks' list -->
<div id="probe" class="mono"></div>                     <!-- the pick's readout -->
<script type="module">
import { picker, marks, screws, copyOnClick } from '/kit/kit.js';
const pick = picker(THREE, {renderer, camera, meshes: () => [...], unit: 1,
                            name: m => m.userData.name, toFrame: p => w2f(p), readout: probeEl});
const pins = marks(THREE, {camera, controls, unit: 1, list: marksEl, tags: tagsEl,
                           find: mk => meshByName[mk.part]});
pins.load();                       // and again when the mtimes say the marks changed
const bolts = screws(THREE, {camera, unit: 1, tags: tagsEl, find: s => meshByName[s.part]});
bolts.load();                      // and again when the mtimes say the screws changed
// every frame: pins.place(); bolts.place();  after the parts reload: pins.draw(); bolts.draw();
</script>
```

`unit` is the scene's units per millimetre: 1 for a page drawn in millimetres,
0.001 for one in metres. A part's own frame is its mesh's local frame.

## Marks file

A JSON list, written by hand or by a script:

```json
[{"part": "body", "at": [24.0, 49.2, 19.3], "box": [[20, 43, 14], [25.3, 55.6, 24.6]],
  "label": "the lead clip", "note": "turned a quarter", "view": 70}]
```

`at` and `box` are in the part's own STL frame, in millimetres; `view` is how far
off the camera stands when brought to the mark, in millimetres. What `part`
names is the viewer's own: a part's name in its table, or its file name.

Two directions, both in the part's frame, are optional. `from` is the side the
camera looks from when brought to the mark. `faces` paints the part's faces
inside `box` that turn within 45 degrees of it, drawn through everything in
front: the faces a mark is about are often inside a pocket or under a lip. For
an overhang, both are the part's print-down direction.

## Screws file

A JSON list the build writes - where each screw sits, as it cuts the holes:

```json
[{"part": "cap", "at": [15.0, 32.7, -24.25], "axis": [0, -1, 0], "d": 5, "len": 10,
  "head": [9.5, 2.75], "spec": "M5 x 10 button head", "into": "an M5 T-nut", "label": "M5x10"}]
```

All in the part's own STL frame, in millimetres: `at` is where the head bears,
`axis` the way the screw goes in, `d` its size across the thread, `len` the
thread's length from `at`, `head` the head's `[diameter, height]` behind `at`
(left out for a set screw). `spec` names the screw, `into` what it threads into,
`label` the short name drawn beside it. A click anywhere in a screw's hole - its
thread or its head's recess, in any part the hole runs through - adds
`screw: <spec> into <into>` to the probe's line; the picker asks for the file on
each click, so a viewer whose server has none just says nothing.
