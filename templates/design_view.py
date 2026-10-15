#!/usr/bin/env python3
"""A live 3D view of the printed parts while they are being designed.

Serves a browser page that draws every STL in PARTS in the design frame (z up,
millimetres), reloads each one the moment its file changes, and, when the
project has a build script and a pose file, turns sliders into a pose that
SAVE writes back and rebuilds. Picking and marks are the partview kit's: a
click reads a point in the design frame and in the part's own frame, a double
click selects the face under it, the spots SETTINGS.marks names are pinned
on their parts and listed, and the screws SETTINGS.screws places are drawn in
their holes, named, and read out with a click in one; click a readout to copy it. EXPORT STEP runs
export_step.py: every part as a STEP solid, and the assembly.

    .venv/bin/python scripts/design_view.py      # http://localhost:<port>

Reads the parts, meshes/assembly.json, the marks and the screws; writes the pose file and
step/ only when asked. Needs the partview kit (pip install -e <this skill>/kit).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import SETTINGS  # noqa: E402
from partview import KitHandler, mtime  # noqa: E402

# part -> (STL, colour, the group it hangs on in the page). A group other than
# "root" is placed by the page from assembly.json (see applyAssembly).
PARTS = {
    "base": (SETTINGS.print / "base.stl", "#d97a3d", "root"),
    "arm": (SETTINGS.print / "arm.stl", "#5b8fd4", "root"),
}
ASSEMBLY = SETTINGS.meshes / "assembly.json"     # written by the build: transforms, slider bounds
BUILD = Path(__file__).resolve().parent / "build.py"
EXPORT = Path(__file__).resolve().parent / "export_step.py"   # the parts as STEP, for CAD
POSE = SETTINGS.pose_yaml                         # the numbers SAVE may rewrite
PYTHON = SETTINGS.python if SETTINGS.python.is_file() else Path(sys.executable)

# slider -> key in the pose file, its label and unit, and whether it is cut
# into a part ("cut": moving it is a preview until SAVE rebuilds) or set at
# assembly ("live": the page moves the parts itself)
SLIDERS = [
    {"key": "angle", "label": "angle", "unit": "°", "min": -90, "max": 90, "step": 5, "kind": "live"},
    {"key": "length", "label": "length", "unit": "mm", "min": 100, "max": 300, "step": 10, "kind": "cut"},
]


def save_pose(values: dict) -> None:
    """Rewrite just the numbers in the pose file, so its comments survive."""
    text = POSE.read_text()
    for s in SLIDERS:
        if s["key"] not in values:
            continue
        v = float(values[s["key"]])
        text, n = re.subn(rf"^(\s*{s['key']}:\s*)[-+0-9.eE]+", rf"\g<1>{v:g}", text, flags=re.M)
        if n != 1:
            raise ValueError(f"{POSE.name} has {n} lines for `{s['key']}`, expected one")
    POSE.write_text(text)


PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>__TITLE__ - design view</title>
<link rel="stylesheet" href="/kit/kit.css">
<style>
  body { margin:0; background:#16181c; color:#cfd2d8; font:13px/1.5 -apple-system, sans-serif; overflow:hidden; }
  #hud { position:fixed; top:10px; left:12px; z-index:2; user-select:none; max-width:min(720px, calc(100vw - 40px)); }
  #hud b { color:#fff; font-weight:600; }
  .mono { font-family:ui-monospace,monospace; user-select:text; cursor:copy; margin-top:2px; }
  #cam { color:#7a7f88; }
  #probe { color:#8fb4e8; }
  #stale { color:#e0b252; }
  #controls { position:fixed; bottom:14px; left:12px; right:12px; z-index:2; display:flex; flex-wrap:wrap;
              gap:10px 18px; align-items:center; user-select:none; }
  #controls label { display:flex; gap:8px; align-items:center; }
  input[type=range] { width:200px; }
  .val { font-family:ui-monospace,monospace; min-width:5ch; text-align:right; color:#fff; }
  button { background:#2a2d33; color:#cfd2d8; border:1px solid #3a3e45; border-radius:4px;
           padding:4px 10px; cursor:pointer; font:12px inherit; }
  button:hover { background:#34383f; }
  button#save { background:#2f5d3a; border-color:#3f7a4c; color:#fff; }
  button#save:disabled { background:#2a2d33; color:#6a6f78; border-color:#3a3e45; cursor:default; }
  #log { position:fixed; right:10px; top:10px; width:380px; max-height:calc(100vh - 120px); overflow:auto;
         z-index:3; font:11px/1.4 ui-monospace,monospace; color:#9aa0aa; white-space:pre-wrap;
         background:rgba(16,18,22,.6); border:1px solid #2a2d33; border-radius:5px; padding:6px 8px; }
  #log:empty { display:none; }
</style>
</head>
<body>
<div id="hud">
  <b>__TITLE__</b> &nbsp; design frame &nbsp;
  <span><span style="color:#e05252">x</span> &nbsp;<span style="color:#3ec46d">y</span> &nbsp;<span style="color:#5277e0">z</span> up</span>
  &mdash; drag to orbit, scroll to zoom, right-drag to pan, click to probe a point, double-click for its face
  <div id="cam" class="mono" title="click to copy"></div>
  <div id="probe" class="mono" title="click to copy"></div>
  <div id="stale"></div>
  <div id="marks" class="dv-marks"></div>
</div>
<div id="tags"></div>
<div id="log"></div>
<div id="controls">
  <span id="sliders" style="display:contents"></span>
  <button id="save" disabled title="write the pose file and rebuild the parts">save &amp; rebuild</button>
  <button id="revert" title="back to the pose that was built">revert</button>
  <button id="step" title="write step/<part>.step and step/assembly.step from the parts on disk">export STEP</button>
  <span style="flex-basis:100%; height:0"></span>
  <button data-v="iso">iso</button>
  <button data-v="front">front (+x)</button>
  <button data-v="left">left (+y)</button>
  <button data-v="top">top</button>
  <label><input id="edges" type="checkbox" checked> outlines</label>
  <label><input id="marksOn" type="checkbox" checked> marks</label>
  <label><input id="screwsOn" type="checkbox" checked> screws</label>
  <span id="show" style="display:contents"></span>
  <span id="stamp" style="color:#7a7f88; margin-left:auto;"></span>
</div>
<script type="importmap">
{ "imports": {
  "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
  "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
} }
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { picker, marks, screws, copyOnClick } from '/kit/kit.js';

const PARTS = __PARTS__;       // name -> {color, group}
const SLIDERS = __SLIDERS__;   // [{key, label, unit, min, max, step, kind}]
const STEP = __STEP__;         // export_step.py is there
const DEG = Math.PI / 180;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x16181c);
// The design frame is z-up and three.js orbits about +y, so the whole model
// rides in a root turned a quarter about x: design (x, y, z) -> world (x, z, -y).
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2;
scene.add(root);
const w2f = v => new THREE.Vector3(v.x, -v.z, v.y);     // world -> design
const f2w = v => new THREE.Vector3(v.x, v.z, -v.y);     // design -> world

const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 1, 6000);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(devicePixelRatio);
document.body.appendChild(renderer.domElement);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.12;

scene.add(new THREE.HemisphereLight(0xffffff, 0x30343a, 0.9));
for (const [x, y, z] of [[300, 500, 400], [-400, 300, -200], [0, -200, 300]]) {
  const l = new THREE.DirectionalLight(0xffffff, 0.7); l.position.set(x, y, z); scene.add(l);
}
for (const [dir, color] of [[[1,0,0], 0xe05252], [[0,1,0], 0x3ec46d], [[0,0,1], 0x5277e0]])
  root.add(new THREE.ArrowHelper(new THREE.Vector3(...dir), new THREE.Vector3(0,0,0), 40, color, 6, 3));
const grid = new THREE.GridHelper(1000, 20, 0x3a3e45, 0x262a30);
grid.rotation.x = Math.PI / 2;            // GridHelper lies in xz; the design's floor is xy
grid.position.z = -0.01;
root.add(grid);

// ---- parts: each mesh hangs on a group the assembly places -----------------
const groups = {root};
for (const p of Object.values(PARTS)) if (!groups[p.group]) {
  groups[p.group] = new THREE.Group(); groups[p.group].matrixAutoUpdate = false; root.add(groups[p.group]);
}
const parts = Object.fromEntries(Object.entries(PARTS).map(([n, p]) =>
  [n, {holder: groups[p.group], color: new THREE.Color(p.color), mesh: null}]));
const loader = new STLLoader();
const edgeMat = new LineMaterial({color: 0x0d0e11, linewidth: 2.0});
edgeMat.resolution.set(innerWidth, innerHeight);
let edgesOn = true;
function load(name) {
  const p = parts[name];
  if (!p) return;                          // a file the page does not draw
  loader.load(`/mesh/${name}?t=${Date.now()}`, geo => {
    geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color: p.color, roughness: 0.6, metalness: 0.05}));
    const eg = new THREE.EdgesGeometry(geo, 25);
    const edges = new LineSegments2(new LineSegmentsGeometry().setPositions(Array.from(eg.attributes.position.array)), edgeMat);
    eg.dispose();
    edges.visible = edgesOn;
    mesh.add(edges);
    mesh.userData = {name, edges};
    if (p.mesh) { p.holder.remove(p.mesh); p.mesh.geometry.dispose(); }
    p.mesh = mesh;
    mesh.visible = document.getElementById(`show-${name}`)?.checked ?? true;
    if (mesh.visible) p.holder.add(mesh);     // hidden parts are off the tree: the probe cannot hit them
    pins.draw();                              // the marks ride the mesh just replaced
    bolts.draw();                             // and so do the screws
  });
}
document.getElementById('edges').addEventListener('change', e => {
  edgesOn = e.target.checked;
  for (const p of Object.values(parts)) if (p.mesh) p.mesh.userData.edges.visible = edgesOn;
});
for (const name of Object.keys(parts)) {
  const label = document.createElement('label');
  const box = document.createElement('input');
  box.type = 'checkbox'; box.checked = true; box.id = `show-${name}`;
  box.addEventListener('change', () => {
    const p = parts[name]; if (!p.mesh) return;
    p.mesh.visible = box.checked;
    if (box.checked) p.holder.add(p.mesh); else p.holder.remove(p.mesh);
  });
  label.append(box, ` ${name}`);
  document.getElementById('show').append(label);
}
Object.keys(parts).forEach(load);
Object.assign(window, {__controls: controls, __camera: camera, __scene: scene, __THREE: THREE, __parts: parts});

// ---- the pose: sliders, the built pose, save & rebuild ---------------------
let A = null;                 // assembly.json as built
const sliders = {};
for (const s of SLIDERS) {
  const label = document.createElement('label');
  label.innerHTML = `${s.label} <input id="${s.key}" type="range" min="${s.min}" max="${s.max}" step="${s.step}">` +
    ` <span class="val" id="${s.key}-v"></span> ${s.unit}`;
  document.getElementById('sliders').append(label);
  sliders[s.key] = label.querySelector('input');
  sliders[s.key].addEventListener('input', applyLive);
}
const live = () => Object.fromEntries(SLIDERS.map(s => [s.key, +sliders[s.key].value]));
function applyAssembly(a) {
  A = a;
  // bounds first, then values: a range input clamps a value to the bounds it has
  for (const s of SLIDERS) {
    const b = a.sliders?.[s.key];
    if (b) Object.assign(sliders[s.key], {min: b.min, max: b.max, step: b.step});
    if (a.pose?.[s.key] !== undefined) sliders[s.key].value = a.pose[s.key];
  }
  for (const [g, m] of Object.entries(a.groups || {})) if (groups[g]) groups[g].matrix.set(...m.flat());
  applyLive();
}
function applyLive() {
  const v = live();
  for (const k of Object.keys(v)) document.getElementById(`${k}-v`).textContent = v[k];
  if (!A) return;
  // TODO(project): move the "live" parts from v here, e.g.
  //   groups.arm.matrix.makeRotationY(v.angle * DEG);
  const changed = SLIDERS.filter(s => v[s.key] !== A.pose?.[s.key]);
  document.getElementById('save').disabled = changed.length === 0;
  const cut = changed.filter(s => s.kind === 'cut').map(s => s.label);
  document.getElementById('stale').textContent = cut.length
    ? `preview - ${cut.join(', ')} ${cut.length > 1 ? 'are' : 'is'} cut into the parts; save to rebuild`
    : changed.length ? 'preview - set at assembly; save to record it'
    : SLIDERS.length ? 'built pose: ' + SLIDERS.map(s => `${s.label} ${v[s.key]}${s.unit}`).join(', ') : '';
}
document.getElementById('revert').onclick = () => A && applyAssembly(A);
const log = document.getElementById('log');
document.getElementById('save').onclick = async () => {
  const btn = document.getElementById('save');
  btn.disabled = true; btn.textContent = 'building…';
  log.textContent = '';
  try {
    const out = await (await fetch('/pose', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                            body: JSON.stringify(live())})).json();
    log.textContent = (out.ok ? '' : 'BUILD FAILED\n') + out.output;
  } catch (e) { log.textContent = `save failed: ${e}`; }
  btn.textContent = 'save & rebuild';
  applyLive();
};
async function loadAssembly() {
  // save stays off until the built pose is on the sliders, or there is no build yet to compare with
  try { applyAssembly(await (await fetch(`/assembly?t=${Date.now()}`)).json()); }
  catch (e) { document.getElementById('save').disabled = false; applyLive(); }
}
if (!SLIDERS.length) for (const id of ['save', 'revert']) document.getElementById(id).style.display = 'none';
if (!STEP) document.getElementById('step').style.display = 'none';
document.getElementById('step').onclick = async () => {
  const btn = document.getElementById('step');
  btn.disabled = true; btn.textContent = 'exporting…';
  try {
    const out = await (await fetch('/step', {method: 'POST'})).json();
    log.textContent = (out.ok ? '' : 'EXPORT FAILED\n') + out.output;
  } catch (e) { log.textContent = `export failed: ${e}`; }
  btn.disabled = false; btn.textContent = 'export STEP';
};

// live reload: poll the mtimes, reload just what changed
let mtimes = null;
setInterval(async () => {
  try {
    const now = await (await fetch('/mtimes')).json();
    if (mtimes) for (const k of Object.keys(now)) if (now[k] !== mtimes[k]) {
      if (k === 'assembly') loadAssembly(); else if (k === 'marks') pins.load();
      else if (k === 'screws') bolts.load(); else load(k);
      document.getElementById('stamp').textContent = `${k} reloaded ${new Date().toLocaleTimeString()}`;
    }
    mtimes = now;
  } catch (e) {}
}, 1000);

// ---- views ------------------------------------------------------------------
const CENTRE = new THREE.Vector3(0, 0, 50);            // design frame
const views = { iso: [400, -380, 320], front: [600, 0, 50], left: [0, 600, 50], top: [1, 0, 700] };
function setView(v) {
  camera.position.copy(f2w(new THREE.Vector3(...views[v])));
  controls.target.copy(f2w(CENTRE));
  controls.update();
}
document.querySelectorAll('button[data-v]').forEach(b => b.onclick = () => setView(b.dataset.v));
setView('iso');
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ---- readouts: the view line, the pick, the marks (the partview kit) -----
const fmt = v => `(${v.x.toFixed(1)}, ${v.y.toFixed(1)}, ${v.z.toFixed(1)})`;
const camLine = document.getElementById('cam');
copyOnClick(camLine);
const pick = picker(THREE, {renderer, camera, unit: 1, toFrame: w2f, readout: document.getElementById('probe'),
                            meshes: () => Object.values(parts).filter(p => p.mesh?.parent).map(p => p.mesh)});
const pins = marks(THREE, {camera, controls, unit: 1, meshes: () => Object.values(parts).map(p => p.mesh), find: mk => parts[mk.part]?.mesh,
                           list: document.getElementById('marks'), tags: document.getElementById('tags')});
document.getElementById('marksOn').addEventListener('change', e => pins.show(e.target.checked));
pins.load();
const bolts = screws(THREE, {camera, unit: 1, find: s => parts[s.part]?.mesh, tags: document.getElementById('tags')});
document.getElementById('screwsOn').addEventListener('change', e => bolts.show(e.target.checked));
bolts.load();

renderer.setAnimationLoop(() => {
  controls.update();
  camLine.textContent = `view ${fmt(w2f(camera.position))} -> ${fmt(w2f(controls.target))}`;
  pins.place();
  bolts.place();
  edgeMat.resolution.set(innerWidth, innerHeight);
  renderer.render(scene, camera);
});
loadAssembly();
</script>
</body>
</html>
"""


class Handler(KitHandler):
    marks = SETTINGS.marks
    screws = SETTINGS.screws

    def do_GET(self):
        path = self.path.split("?")[0]
        if self.kit(path):
            return
        if path == "/":
            # filled per request, so the page never lags the parts table
            page = (PAGE.replace("__TITLE__", SETTINGS.title)
                    .replace("__STEP__", "true" if EXPORT.is_file() else "false")
                    .replace("__PARTS__", json.dumps({n: {"color": c, "group": g} for n, (_, c, g) in PARTS.items()}))
                    .replace("__SLIDERS__", json.dumps(SLIDERS if POSE.is_file() and BUILD.is_file() else [])))
            self.send_body(page.encode(), "text/html; charset=utf-8")
        elif path == "/assembly":
            if not ASSEMBLY.is_file():
                self.send_error(404, "no assembly.json - run the build")
                return
            self.send_body(ASSEMBLY.read_bytes(), "application/json")
        elif path == "/mtimes":
            files = ({n: f for n, (f, _, _) in PARTS.items()}
                     | {"assembly": ASSEMBLY, "marks": SETTINGS.marks, "screws": SETTINGS.screws})
            body = json.dumps({k: mtime(p) for k, p in files.items()}).encode()
            self.send_body(body, "application/json")
        elif path.startswith("/mesh/"):
            part = PARTS.get(path[len("/mesh/"):])
            if part is None or not part[0].is_file():
                self.send_error(404)
                return
            self.send_body(part[0].read_bytes(), "model/stl")
        else:
            self.send_error(404)

    def _run(self, script: Path) -> tuple[str, bool]:
        run = subprocess.run([str(PYTHON), str(script)], capture_output=True, text=True, timeout=300)
        return run.stdout + run.stderr, run.returncode == 0

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/step":
            try:
                output, ok = self._run(EXPORT)
            except Exception as e:  # noqa: BLE001 - shown on the page
                output, ok = f"{type(e).__name__}: {e}", False
            self.send_body(json.dumps({"ok": ok, "output": output}).encode(), "application/json")
            return
        if path != "/pose":
            self.send_error(404)
            return
        values = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        before = POSE.read_text()
        try:
            save_pose(values)
            output, ok = self._run(BUILD)
        except Exception as e:  # noqa: BLE001 - shown on the page
            output, ok = f"{type(e).__name__}: {e}", False
        if not ok:
            # a pose the build refused is not the pose on record: put it back and rebuild the
            # parts on disk for it (the failed build may have written them before it failed)
            POSE.write_text(before)
            restore, _ = self._run(BUILD)
            output += "\n-- the pose on record restored --\n" + restore
        self.send_body(json.dumps({"ok": ok, "output": output}).encode(), "application/json")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", SETTINGS.port), Handler)
    print(f"design view: http://localhost:{SETTINGS.port}  (watching {len(PARTS)} parts)")
    server.serve_forever()


if __name__ == "__main__":
    main()
