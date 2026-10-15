# print-part-design

A Claude Code skill for repositories that design 3D-printed parts in code (manifold3d or build123d → STL). One build
script writes the parts and checks them; a browser viewer draws them the moment they change; a set of tools finds and
fixes the small flaws boolean joins leave before the parts go to the printer.

The skill's documents (`SKILL.md`, `references/`) are written in Korean. Technical terms are left in English. The
Python and JavaScript and their comments are in English.

## What it does

- **Design viewer.** A one-file Python server and a three.js page (`templates/design_view.py`). Parts in the design
  frame (z up, millimetres), reloaded as their files change; outlines, per-part show/hide, view buttons; sliders that
  move a live pose or preview a cut, then save it to the pose file and rebuild; STEP export of every part and the
  assembly.
- **partview kit.** What every viewer shares lives in `kit/` (the `partview` package), so a fix lands in every viewer
  at once: a click pins a point and reads it in the design frame and the part's own; a double click selects a whole
  face, hole or round and reads its area, normal and extent; a marks file pins numbered spots on the parts and
  brings the camera to one; a screws file the build writes draws each screw in its hole and names it.
- **Design checks.** `templates/checks.py` holds the checks a build runs before it calls its parts done: one valid
  solid, fits the bed, parts apart by a minimum gap, room round a motor's sides, a part sliding in along its
  assembly direction without meeting what is already placed, and overlaps judged against a reference build that
  went together for real rather than against zero.
- **Print tidy.** `scripts/print_flaws.py` lists zero-width strips, specks, loose pieces, voids and overhangs (with
  bridge / cantilever / island) in the part's own frame, and diffs two builds piece by piece; `sections.py` overlays
  cross-sections; `shots.js` aims a Playwright capture at a point in a part's frame. `references/print-tidy.md` is
  the procedure: keep the shape, fix each flaw where the build makes it, verify by numbers and by eye.

## Install

```bash
git clone https://github.com/woolimi/print-part-design ~/.claude/skills/print-part-design
pip install -e ~/.claude/skills/print-part-design/kit        # into the environment the viewer runs in
```

Requirements: Python 3.10+ with `manifold3d` and `numpy` (the build and the checks), `cadquery-ocp` for STEP export,
`matplotlib` for `sections.py`. The page loads three.js from a CDN.

## Use

Ask Claude Code for a viewer ("set up a design viewer for this repo", "설계 뷰어 만들어줘"), for a fit check ("does
the servo go in?", "서보 들어가는지 봐줘"), or for a print tidy ("tidy these parts for printing", "출력 잘 되게
다듬어줘"). To set up a viewer by hand:

1. Copy `templates/design_view.py`, `config.py`, `export_step.py` and `checks.py` into your repo's `scripts/`.
2. Fill `PARTS` in `design_view.py`: `name: (STL path, colour, group)`.
3. Have your build write `meshes/assembly.json` (`references/viewer.md` §2) and run the checks:

```python
import sys
from checks import apart, fits_bed, one_solid, slides_in

faults = one_solid("body", body) + fits_bed("body", body, (256, 256, 256))
faults += apart("lid", lid, "body", body, 0.3)
faults += slides_in("servo", servo, [body], way=(0, 0, -1))
for f in faults:
    print("FAIL", f)
sys.exit(1 if faults else 0)
```

4. Run `python scripts/design_view.py` and open `http://localhost:<port>/`.

```bash
python ~/.claude/skills/print-part-design/scripts/print_flaws.py print/body.stl --up 0 0 1
```

For Bambu Studio projects (`.3mf`) of the parts, see [bambu-3mf](https://github.com/woolimi/bambu-3mf).

## License

MIT
