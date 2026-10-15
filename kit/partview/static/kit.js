// partview kit: what every design viewer's page shares.
//
//   <link rel="stylesheet" href="/kit/kit.css">
//   import { picker, marks, screws, copyOnClick } from '/kit/kit.js';
//
// Each call takes the page's THREE, so the kit draws with the page's own copy
// of three.js. `unit` is how many of the scene's units make a millimetre - 1
// for a page drawn in millimetres, 0.001 for one drawn in metres - and a part's
// own frame is its mesh's local frame, the frame its STL was written in.

// Where EdgesGeometry draws an outline: a face, as the page shows it, ends at
// an edge it bends across by more than this.
const SHARP = 25;

// A line of text that copies itself on a click, flashing green.
export function copyOnClick(el) {
  el.addEventListener('click', async () => {
    if (!el.textContent) return;
    try { await navigator.clipboard.writeText(el.textContent); } catch (e) { return; }
    const keep = el.style.color;
    el.style.color = '#3ec46d';
    setTimeout(() => { el.style.color = keep; }, 350);
  });
}

// Whether an object is drawn: in the scene, and it and everything it hangs
// on visible. A part taken off the tree, or hidden with its group, is not
// picked and its marks' numbers are not shown.
function drawn(o) {
  for (; o; o = o.parent) {
    if (!o.visible) return false;
    if (o.isScene) return true;
  }
  return false;
}

// ---- faces ------------------------------------------------------------------
// A geometry's triangles welded at their corners and paired across their
// edges, and gathered into flat pieces - triangles joined across edges they
// bend over by less than half a degree - once per geometry: what a face is
// read from.
function adjacency(THREE, geo) {
  if (geo.userData.dvAdjacency) return geo.userData.dvAdjacency;
  const pos = geo.attributes.position.array;
  const n = pos.length / 9;
  geo.computeBoundingBox();
  const q = geo.boundingBox.getSize(new THREE.Vector3()).length() * 1e-7 || 1e-12;
  const ids = new Map();
  const corner = new Int32Array(n * 3);
  for (let i = 0; i < n * 3; i++) {
    const key = `${Math.round(pos[3 * i] / q)},${Math.round(pos[3 * i + 1] / q)},${Math.round(pos[3 * i + 2] / q)}`;
    let id = ids.get(key);
    if (id === undefined) { id = ids.size; ids.set(key, id); }
    corner[i] = id;
  }
  const normal = new Float32Array(n * 3), area = new Float32Array(n), longest = new Float32Array(n);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let t = 0; t < n; t++) {
    a.fromArray(pos, 9 * t); b.fromArray(pos, 9 * t + 3); c.fromArray(pos, 9 * t + 6);
    longest[t] = Math.max(a.distanceTo(b), b.distanceTo(c), c.distanceTo(a));
    const cross = b.sub(a).cross(c.sub(a));
    const len = cross.length();
    area[t] = len / 2;
    if (len > 0) cross.divideScalar(len);
    cross.toArray(normal, 3 * t);
  }
  const edge = (u, v) => (u < v ? u * 2097152 + v : v * 2097152 + u);
  const across = new Map();
  for (let t = 0; t < n; t++) for (let k = 0; k < 3; k++) {
    const e = edge(corner[3 * t + k], corner[3 * t + (k + 1) % 3]);
    const list = across.get(e);
    if (list) list.push(t); else across.set(e, [t]);
  }
  const dot = (t, o) => normal[3 * t] * normal[3 * o] + normal[3 * t + 1] * normal[3 * o + 1] + normal[3 * t + 2] * normal[3 * o + 2];
  // flat pieces: union-find over the edges that hardly bend
  const parent = new Int32Array(n).map((_, i) => i);
  const find = i => { while (parent[i] !== i) { parent[i] = parent[parent[i]]; i = parent[i]; } return i; };
  const level = Math.cos(0.5 * Math.PI / 180);
  for (const list of across.values()) if (list.length === 2) {
    const [t, o] = list;
    if (dot(t, o) >= level || area[t] === 0 || area[o] === 0) parent[find(t)] = find(o);
  }
  const piece = new Int32Array(n), pieceArea = new Map(), pieceLong = new Map();
  for (let t = 0; t < n; t++) {
    const r = find(t);
    piece[t] = r;
    pieceArea.set(r, (pieceArea.get(r) || 0) + area[t]);
    pieceLong.set(r, Math.max(pieceLong.get(r) || 0, longest[t]));
  }
  // a piece's width: its area over its longest edge - a facet of a curve is a thin strip
  const width = new Map([...pieceArea].map(([r, A]) => [r, A / (pieceLong.get(r) || 1)]));
  geo.userData.dvAdjacency = {corner, normal, area, across, edge, dot, piece, width};
  return geo.userData.dvAdjacency;
}

// The triangles of the face `start` lies on. On a flat face, the flat piece it
// belongs to: the plane up to wherever the surface turns. On a curved one -
// a hole, a round - the facets it is drawn with: thin flat strips, joined
// across edges that bend by less than SHARP, so the curve is taken whole and
// stops at the flat faces it runs into.
function faceOf(THREE, geo, start, unit) {
  const {corner, area, across, edge, dot, piece, width} = adjacency(THREE, geo);
  const strip = t => width.get(piece[t]) < 1.0 * unit;
  const cos = Math.cos(SHARP * Math.PI / 180);
  const curved = strip(start);
  const joins = curved ? (t, o) => strip(o) && (dot(t, o) >= cos || area[o] === 0)
                       : (t, o) => piece[o] === piece[start];
  const seen = new Uint8Array(area.length);
  const out = [], stack = [start];
  seen[start] = 1;
  while (stack.length) {
    const t = stack.pop();
    out.push(t);
    for (let k = 0; k < 3; k++) {
      for (const o of across.get(edge(corner[3 * t + k], corner[3 * t + (k + 1) % 3])) || []) {
        if (!seen[o] && joins(t, o)) { seen[o] = 1; stack.push(o); }
      }
    }
  }
  return out;
}

// A face's area, mean normal, whether it is flat, its plane and its extent.
function describe(THREE, geo, tris, unit) {
  const pos = geo.attributes.position.array;
  const {normal, area} = adjacency(THREE, geo);   // area-weighted, in the part's frame
  const n = new THREE.Vector3(), centre = new THREE.Vector3(), p = new THREE.Vector3();
  const lo = new THREE.Vector3(Infinity, Infinity, Infinity), hi = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  let total = 0;
  for (const t of tris) {
    total += area[t];
    n.x += normal[3 * t] * area[t]; n.y += normal[3 * t + 1] * area[t]; n.z += normal[3 * t + 2] * area[t];
    for (let k = 0; k < 3; k++) {
      p.fromArray(pos, 9 * t + 3 * k);
      centre.addScaledVector(p, area[t] / 3);
      lo.min(p); hi.max(p);
    }
  }
  n.normalize();
  centre.divideScalar(total || 1);
  let off = 0;
  for (const t of tris) for (let k = 0; k < 3; k++) off = Math.max(off, Math.abs(p.fromArray(pos, 9 * t + 3 * k).sub(centre).dot(n)));
  return {area: total, normal: n, flat: off < 0.01 * unit, plane: n.dot(centre), lo, hi};
}

// ---- screws -----------------------------------------------------------------
// The screws file (see partview.read_screws), each screw in its part's own
// frame. The screw a point is in: on its thread's cylinder or in its head's
// recess, the walls of the hole included, and of two, the one whose axis is
// nearer. `local(screw)` is the point in that screw's part frame, millimetres.
const SCREW_REACH = 1.5;                 // mm past a hole's wall still read as that hole
function screwAt(screws, local) {
  let best = null, nearest = Infinity;
  for (const s of screws) {
    if (!Array.isArray(s.at) || !Array.isArray(s.axis)) continue;
    const p = local(s);
    if (!p) continue;
    const u = s.axis.map(v => v / Math.hypot(...s.axis));
    const d = [p[0] - s.at[0], p[1] - s.at[1], p[2] - s.at[2]];
    const t = d[0] * u[0] + d[1] * u[1] + d[2] * u[2];
    const r = Math.hypot(d[0] - t * u[0], d[1] - t * u[1], d[2] - t * u[2]);
    const [hd, hh] = Array.isArray(s.head) ? s.head : [0, 0];
    const inThread = t >= -0.5 && t <= (s.len ?? 0) + 1 && r <= (s.d ?? 0) / 2 + SCREW_REACH;
    const inHead = hh > 0 && t >= -hh - 1 && t <= 0.5 && r <= hd / 2 + SCREW_REACH;
    if ((inThread || inHead) && r < nearest) { best = s; nearest = r; }
  }
  return best;
}
const sayScrew = s => `${s.spec ?? 'screw'}${s.into ? ` into ${s.into}` : ''}${s.note ? ` (${s.note})` : ''}`;

// ---- picking ----------------------------------------------------------------
// A click pins a point on a part; a double click selects the face under the
// pointer, the face the outlines bound, and tints it. Either reads out in
// `readout`, in the page's frame (`toFrame`, scene units) and in the part's
// own, and the line copies on a click. A press that moves more than a few
// pixels is the camera's, not a pick. A point in a hole the screws file names
// says which screw goes there, whichever part the hole runs through.
//
//   const pick = picker(THREE, {renderer, camera, meshes: () => [...], unit,
//                               name: mesh => 'body', toFrame: p => w2f(p), readout: el});
//   pick.clear();
export function picker(THREE, {renderer, camera, meshes, unit = 1, name = m => m.userData.name ?? '',
                               toFrame = p => p, readout, screwsUrl = '/screws'}) {
  const ray = new THREE.Raycaster();
  const dot = new THREE.Mesh(new THREE.SphereGeometry(1.2 * unit, 16, 12), new THREE.MeshBasicMaterial({color: 0xf2e14c}));
  const tint = new THREE.MeshBasicMaterial({color: 0x3ec4ff, transparent: true, opacity: 0.55, side: THREE.DoubleSide,
                                            polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2});
  let face = null;
  const mm = v => `(${(v.x / unit).toFixed(1)}, ${(v.y / unit).toFixed(1)}, ${(v.z / unit).toFixed(1)})`;
  const dir = v => `(${v.x.toFixed(2)}, ${v.y.toFixed(2)}, ${v.z.toFixed(2)})`;

  function hitAt(e) {
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                                        -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    return ray.intersectObjects(meshes().filter(drawn), false)[0];
  }
  function dropFace() {
    if (!face) return;
    face.removeFromParent();
    face.geometry.dispose();
    face = null;
  }
  function clear() {
    dot.removeFromParent();
    dropFace();
    readout.textContent = '';
  }
  function point(hit) {
    dropFace();
    // the dot rides the part, so it stays on the spot when the part moves
    const local = hit.object.worldToLocal(hit.point.clone());
    dot.position.copy(local);
    hit.object.add(dot);
    const said = readout.textContent =
      `probe ${name(hit.object)} ${mm(toFrame(hit.point.clone()))} mm | in its own frame ${mm(local)}`;
    whichScrew(hit.point.clone()).then(s => {
      if (s && readout.textContent === said) readout.textContent = `${said} | screw: ${sayScrew(s)}`;
    });
  }
  // asked on each pick, so it is the build's latest; a viewer without the file says nothing
  async function whichScrew(world) {
    let list;
    try { list = await (await fetch(`${screwsUrl}?t=${Date.now()}`)).json(); } catch (e) { return null; }
    if (!Array.isArray(list) || !list.length) return null;
    const byName = new Map(meshes().filter(drawn).map(m => [name(m), m]));
    return screwAt(list, s => {
      const m = byName.get(s.part);
      if (!m) return null;
      const q = m.worldToLocal(world.clone()).divideScalar(unit);
      return [q.x, q.y, q.z];
    });
  }
  function select(hit) {
    dot.removeFromParent();
    dropFace();
    const geo = hit.object.geometry;
    if (geo.index) { readout.textContent = 'face: this part is drawn indexed; the kit reads STL triangles'; return; }
    const tris = faceOf(THREE, geo, hit.faceIndex, unit);
    const pos = geo.attributes.position.array;
    const out = new Float32Array(tris.length * 9);
    tris.forEach((t, i) => out.set(pos.subarray(9 * t, 9 * t + 9), 9 * i));
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(out, 3));
    face = new THREE.Mesh(g, tint);
    face.renderOrder = 4;
    hit.object.add(face);
    const f = describe(THREE, geo, tris, unit);
    readout.textContent = `face ${name(hit.object)} ${(f.area / unit / unit).toFixed(1)} mm2, ` +
      (f.flat ? `flat, normal ${dir(f.normal)}, n.p ${(f.plane / unit).toFixed(2)} mm` : `curved, mean normal ${dir(f.normal)}`) +
      ` | box ${mm(f.lo)} .. ${mm(f.hi)} in its own frame`;
  }

  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = e.button === 0 ? [e.clientX, e.clientY] : null; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down) return;
    const moved = Math.hypot(e.clientX - down[0], e.clientY - down[1]);
    down = null;
    if (moved > 5) return;
    const hit = hitAt(e);
    if (hit) point(hit); else clear();
  });
  renderer.domElement.addEventListener('dblclick', e => {
    const hit = hitAt(e);
    if (hit) select(hit);
  });
  copyOnClick(readout);
  return {clear};
}

// ---- marks ------------------------------------------------------------------
// Spots the marks file names for whoever looks (see partview.read_marks):
// each pinned on its part, drawn through whatever stands in front of it, its
// number floating over it, and listed in `list` - a click there brings the
// camera to it from the side it looks from now and, given the page's
// `meshes`, fades every other part so the one marked stands out; Escape, or
// a click on the list's head, brings them back. A mark with `faces` (a
// direction in its part's frame) also has the part's faces inside its box
// that turn within 45 degrees of that direction painted, through whatever
// stands in front of them - the faces a mark is about are often inside a
// pocket or under a lip. `find(mark)` is the page's:
// the mesh a mark's `part` names, or nothing. Call place() every frame and
// draw() whenever the parts are reloaded.
//
//   const pins = marks(THREE, {camera, controls, find, unit, list, tags, meshes: () => [...]});
//   pins.load();
export function marks(THREE, {camera, controls, find, unit = 1, list, tags, url = '/marks', meshes = null}) {
  const PINK = 0xff5fd2;
  const dotMat = new THREE.MeshBasicMaterial({color: PINK, depthTest: false, transparent: true});
  const lineMat = new THREE.LineBasicMaterial({color: PINK, depthTest: false, transparent: true});
  const faceMat = new THREE.MeshBasicMaterial({color: PINK, depthTest: false, transparent: true,
                                               opacity: 0.55, side: THREE.DoubleSide});
  let data = [], pinned = [], shown = true;
  const at = v => new THREE.Vector3(v[0], v[1], v[2]).multiplyScalar(unit);

  async function load() {
    try { data = await (await fetch(`${url}?t=${Date.now()}`)).json(); } catch (e) { data = []; }
    draw();
  }
  function draw() {
    unfocus();
    // the geometry is each mark's own, the materials shared
    for (const o of pinned) if (o) { o.group.traverse(c => c.geometry?.dispose()); o.group.removeFromParent(); }
    pinned = [];
    tags.innerHTML = '';
    // a marks file is the project's, and may name parts another viewer draws:
    // those are counted, not listed
    const here = data.map(mk => (Array.isArray(mk.at) ? find(mk) : null));
    const away = here.filter(m => !m).length;
    list.innerHTML = here.some(m => m) ? '<div class="dv-head" title="show every part again (Esc)">marks</div>' : '';
    list.querySelector('.dv-head')?.addEventListener('click', unfocus);
    data.forEach((mk, i) => {
      const mesh = here[i];
      if (!mesh) return;
      const line = document.createElement('div');
      line.innerHTML = `<b>${i + 1}</b>${mk.label ?? ''} <span class="note">${mk.note ?? ''}</span>`;
      list.append(line);
      const group = new THREE.Group();
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.9 * unit, 16, 12), dotMat);
      dot.position.copy(at(mk.at));
      dot.renderOrder = 10;
      group.add(dot);
      if (Array.isArray(mk.box)) {
        const [a, b] = mk.box.map(at);
        const size = b.clone().sub(a);
        const box = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z)), lineMat);
        box.position.copy(a.clone().add(b).multiplyScalar(0.5));
        box.renderOrder = 10;
        group.add(box);
        if (Array.isArray(mk.faces)) {
          const painted = facesIn(mesh.geometry, a, b, new THREE.Vector3(...mk.faces).normalize());
          if (painted) { painted.renderOrder = 9; group.add(painted); }
        }
      }
      group.visible = shown;
      mesh.add(group);
      const tag = document.createElement('div');
      tag.className = 'dv-tag';
      tag.textContent = i + 1;
      tags.append(tag);
      pinned[i] = {group, dot, tag, mk, line};
      line.onclick = () => go(i);
    });
    if (away && here.some(m => m)) list.insertAdjacentHTML('beforeend', `<div class="away">+${away} for parts not in this view</div>`);
  }
  // the triangles of `geo` with every corner in the box a..b (a hair over) whose
  // normal is within 45 degrees of `dir`, as one mesh in the part's frame
  function facesIn(geo, a, b, dir) {
    const pos = geo.attributes.position.array, index = geo.index?.array;
    const count = index ? index.length / 3 : pos.length / 9;
    const lo = a.clone().min(b), hi = a.clone().max(b), pad = 0.05 * unit;
    lo.subScalar(pad); hi.addScalar(pad);
    const v = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
    const e1 = new THREE.Vector3(), e2 = new THREE.Vector3(), out = [];
    for (let t = 0; t < count; t++) {
      for (let k = 0; k < 3; k++) v[k].fromArray(pos, 3 * (index ? index[3 * t + k] : 3 * t + k));
      if (!v.every(p => p.x >= lo.x && p.y >= lo.y && p.z >= lo.z && p.x <= hi.x && p.y <= hi.y && p.z <= hi.z)) continue;
      e1.subVectors(v[1], v[0]); e2.subVectors(v[2], v[0]);
      const n = e1.cross(e2);
      if (n.lengthSq() === 0 || n.normalize().dot(dir) < Math.SQRT1_2) continue;
      for (const p of v) out.push(p.x, p.y, p.z);
    }
    if (!out.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(out, 3));
    return new THREE.Mesh(g, faceMat);
  }
  // fading: each faded material's own settings, to put back
  const faded = new Map();
  function unfocus() {
    for (const [mat, keep] of faded) Object.assign(mat, keep);
    faded.clear();
    for (const o of pinned) if (o) o.line?.classList.remove('on');
  }
  function focus(mesh) {
    unfocus();
    if (!meshes) return;
    for (const m of meshes()) {
      if (!m || m === mesh || faded.has(m.material)) continue;
      faded.set(m.material, {transparent: m.material.transparent, opacity: m.material.opacity, depthWrite: m.material.depthWrite});
      Object.assign(m.material, {transparent: true, opacity: 0.12, depthWrite: false});
    }
  }
  addEventListener('keydown', e => { if (e.key === 'Escape') unfocus(); });
  function go(i) {
    const o = pinned[i];
    if (!o) return;
    focus(o.group.parent);
    o.line.classList.add('on');
    const spot = o.dot.getWorldPosition(new THREE.Vector3());
    // from the side the mark says to look from (in its part's frame), or else
    // from the side the camera looks from now - then the nearest direction to
    // that with a clear line from the mark out of its part, so the camera does
    // not stand inside it
    let want = camera.position.clone().sub(controls.target).normalize();
    if (Array.isArray(o.mk.from)) {
      const q = o.group.getWorldQuaternion(new THREE.Quaternion());
      want = new THREE.Vector3(...o.mk.from).normalize().applyQuaternion(q);
    }
    const dist = (o.mk.view ?? 90) * unit;
    const solids = [o.group.parent];               // the rest are faded: seen through
    const ray = new THREE.Raycaster();
    const clear = d => {
      ray.set(spot.clone().addScaledVector(d, 0.3 * unit), d);
      ray.far = dist;
      return ray.intersectObjects(solids, false).length === 0;
    };
    const tries = [];
    for (let i = 0; i < 64; i++) {                 // a Fibonacci sphere of directions
      const y = 1 - (i + 0.5) / 32, r = Math.sqrt(1 - y * y), a = i * 2.39996;
      tries.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    tries.sort((a, b) => b.dot(want) - a.dot(want));
    let back = [want, ...tries].find(clear) ?? want;
    // straight down or up the camera's up is no view: lean off it a little
    if (Math.abs(back.dot(camera.up)) > 0.95) back = back.clone().addScaledVector(new THREE.Vector3(1, 0, 0.6), 0.35).normalize();
    camera.position.copy(spot).addScaledVector(back, dist);
    controls.target.copy(spot);
    controls.update();
  }
  function show(on) {
    shown = on;
    for (const o of pinned) if (o) o.group.visible = on;
  }
  const p = new THREE.Vector3(), w = new THREE.Vector3();
  function place() {
    const W = innerWidth, H = innerHeight;
    for (const o of pinned) {
      if (!o) continue;
      // the dot keeps its size on the screen, however near the camera comes
      o.dot.getWorldPosition(w);
      o.dot.scale.setScalar(camera.position.distanceTo(w) * 0.006 / (0.9 * unit));
      p.copy(w).project(camera);
      const on = drawn(o.dot) && p.z < 1 && Math.abs(p.x) < 1 && Math.abs(p.y) < 1;
      o.tag.style.display = on ? '' : 'none';
      if (on) { o.tag.style.left = `${(p.x + 1) / 2 * W}px`; o.tag.style.top = `${(1 - p.y) / 2 * H}px`; }
    }
  }
  return {load, draw, go, show, place, unfocus};
}

// ---- screws -----------------------------------------------------------------
// The screws the build places (see partview.read_screws), drawn in their
// holes through whatever is in front - the thread and, behind where it bears,
// the head - with their names beside them in `tags`. `find(screw)` is the
// page's: the mesh a screw's `part` names, or nothing. Call place() every
// frame and draw() whenever the parts are reloaded.
//
//   const bolts = screws(THREE, {camera, find, unit, tags});
//   bolts.load();                    // and again when the mtimes say the screws changed
export function screws(THREE, {camera, find, unit = 1, tags, url = '/screws'}) {
  const mat = new THREE.MeshBasicMaterial({color: 0x9fb7d6, transparent: true, opacity: 0.55, depthTest: false});
  let data = [], drawnOnes = [], shown = true;
  const v = a => new THREE.Vector3(a[0], a[1], a[2]);

  async function load() {
    try { data = await (await fetch(`${url}?t=${Date.now()}`)).json(); } catch (e) { data = []; }
    if (!Array.isArray(data)) data = [];
    draw();
  }
  function rod(r, length, from, u) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, length, 20), mat);
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), u);
    m.position.copy(from).addScaledVector(u, length / 2);
    m.renderOrder = 9;
    return m;
  }
  function draw() {
    for (const o of drawnOnes) { o.group.removeFromParent(); o.tag.remove(); }
    drawnOnes = [];
    for (const s of data) {
      const mesh = find(s);
      if (!mesh || !Array.isArray(s.at) || !Array.isArray(s.axis)) continue;
      const at = v(s.at).multiplyScalar(unit), u = v(s.axis).normalize();
      const group = new THREE.Group();
      group.add(rod((s.d ?? 3) / 2 * unit, (s.len ?? 5) * unit, at, u));
      const [hd, hh] = Array.isArray(s.head) ? s.head : [0, 0];
      if (hh > 0) group.add(rod(hd / 2 * unit, hh * unit, at.clone().addScaledVector(u, -hh * unit), u));
      const anchor = new THREE.Object3D();
      anchor.position.copy(at).addScaledVector(u, -hh * unit);
      group.add(anchor);
      group.visible = shown;
      mesh.add(group);
      const tag = document.createElement('div');
      tag.className = 'dv-screw';
      tag.textContent = s.label ?? s.spec ?? 'screw';
      tag.title = sayScrew(s);
      tags.append(tag);
      drawnOnes.push({group, anchor, tag});
    }
  }
  function show(on) {
    shown = on;
    for (const o of drawnOnes) o.group.visible = on;
  }
  const p = new THREE.Vector3();
  function place() {
    const W = innerWidth, H = innerHeight;
    for (const o of drawnOnes) {
      o.anchor.getWorldPosition(p).project(camera);
      const on = shown && drawn(o.anchor) && p.z < 1 && Math.abs(p.x) < 1 && Math.abs(p.y) < 1;
      o.tag.style.display = on ? '' : 'none';
      if (on) { o.tag.style.left = `${(p.x + 1) / 2 * W}px`; o.tag.style.top = `${(1 - p.y) / 2 * H}px`; }
    }
  }
  return {load, draw, show, place};
}
