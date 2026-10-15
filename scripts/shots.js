// Playwright browser_run_code_unsafe body: screenshots of one part from given
// points and directions, aimed in the part's own STL coordinates (mm) - the
// same numbers print_flaws.py prints and the viewer's probe reads "in its own
// frame". Fill PART, DIR and SHOTS, paste as the `code` argument.
//
// Works with a viewer that exposes window.__camera, __controls, __THREE and
// either __parts ({name: {mesh}}, the template viewer) or __visuals
// ([mesh] with userData.file, follower_view.py).
async (page) => {
  const PART = 'base_right.stl';            // file name, or a __parts key
  const DIR = '/tmp/shots/';                // a scratch directory, not the repo
  const SCALE = 1000;                       // STL units per mm: 1000 for metres
  // [name, point in the STL frame (mm), view direction in the STL frame, distance (m in the scene)]
  const SHOTS = [
    ['iso', null, [1, -0.8, 0.7], 0.22],    // null point: the part's centre
    ['join', [0, 70, -15], [0.2, -0.3, 1], 0.07],
  ];
  await page.evaluate(([PART, SCALE]) => {
    const T = window.__THREE;
    const meshes = window.__visuals
      ?? Object.entries(window.__parts).map(([n, p]) => Object.assign(p.mesh, {userData: {...p.mesh.userData, file: n}}));
    const mine = meshes.find(m => m.userData.file === PART);
    for (const m of meshes) m.visible = (m === mine);      // only this part
    window.__aim = (mm, d, dist) => {
      mine.updateWorldMatrix(true, false);
      let c;
      if (mm) c = mine.localToWorld(new T.Vector3(mm[0] / SCALE, mm[1] / SCALE, mm[2] / SCALE));
      else c = new T.Box3().setFromObject(mine).getCenter(new T.Vector3());
      const q = new T.Quaternion();
      mine.getWorldQuaternion(q);
      const dir = new T.Vector3(...d).normalize().applyQuaternion(q);
      window.__camera.position.copy(c.clone().add(dir.multiplyScalar(dist)));
      window.__camera.up.set(0, 1, 0);
      window.__controls.target.copy(c);
      window.__controls.update();
    };
  }, [PART, SCALE]);
  for (const [name, p, d, r] of SHOTS) {
    await page.evaluate(([p, d, r]) => window.__aim(p, d, r), [p, d, r]);
    await page.waitForTimeout(400);
    await page.screenshot({ path: DIR + name + '.png' });
  }
  return 'ok';
}
