// Simple solids that aren't turned along the gun's axis: boxes, and profiles
// for spheres and tori (revolve them with lathe() and rotate into place).

/** Axis-aligned box centred on the origin, with flat-shaded faces. */
export function box(sx, sy, sz) {
  const hx = sx / 2, hy = sy / 2, hz = sz / 2;
  // Each face: normal, then its four corners counter-clockwise seen from outside.
  const faces = [
    [[1, 0, 0], [[hx, -hy, -hz], [hx, hy, -hz], [hx, hy, hz], [hx, -hy, hz]]],
    [[-1, 0, 0], [[-hx, -hy, hz], [-hx, hy, hz], [-hx, hy, -hz], [-hx, -hy, -hz]]],
    [[0, 1, 0], [[-hx, hy, -hz], [-hx, hy, hz], [hx, hy, hz], [hx, hy, -hz]]],
    [[0, -1, 0], [[-hx, -hy, hz], [-hx, -hy, -hz], [hx, -hy, -hz], [hx, -hy, hz]]],
    [[0, 0, 1], [[-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz]]],
    [[0, 0, -1], [[hx, -hy, -hz], [-hx, -hy, -hz], [-hx, hy, -hz], [hx, hy, -hz]]],
  ];
  const positions = [], normals = [], indices = [];
  faces.forEach(([n, corners], f) => {
    for (const c of corners) { positions.push(...c); normals.push(...n); }
    const b = f * 4;
    indices.push(b, b + 1, b + 2, b, b + 2, b + 3);
  });
  return { positions: new Float32Array(positions), normals: new Float32Array(normals), indices: new Uint32Array(indices) };
}

/** Convex polygon [[x, y], ...] in the xy-plane, extruded to a slab of width sz centred on z = 0. */
export function prism(points, sz) {
  let area = 0;
  points.forEach(([x, y], i) => {
    const [x2, y2] = points[(i + 1) % points.length];
    area += x * y2 - x2 * y;
  });
  const pts = area < 0 ? [...points].reverse() : points;  // counter-clockwise
  const hz = sz / 2;
  const positions = [], normals = [], indices = [];
  const face = (corners, n) => {
    const b = positions.length / 3;
    for (const c of corners) { positions.push(...c); normals.push(...n); }
    for (let k = 1; k < corners.length - 1; k++) indices.push(b, b + k, b + k + 1);
  };
  face(pts.map(([x, y]) => [x, y, hz]), [0, 0, 1]);
  face([...pts].reverse().map(([x, y]) => [x, y, -hz]), [0, 0, -1]);
  pts.forEach(([x, y], i) => {
    const [x2, y2] = pts[(i + 1) % pts.length];
    const len = Math.hypot(x2 - x, y2 - y) || 1;
    face([[x, y, -hz], [x2, y2, -hz], [x2, y2, hz], [x, y, hz]], [(y2 - y) / len, -(x2 - x) / len, 0]);
  });
  return { positions: new Float32Array(positions), normals: new Float32Array(normals), indices: new Uint32Array(indices) };
}

/** Sphere of radius r centred at x = cx, as a lathe profile. */
export function sphereProfile(r, cx = 0, n = 24) {
  const pts = [];
  for (let k = 0; k <= n; k++) {
    const a = -Math.PI / 2 + (k / n) * Math.PI;
    pts.push([r * Math.cos(a), cx + r * Math.sin(a)]);
  }
  return [pts];
}

/** Ring of tube radius r whose centre line has radius R about the lathe axis (x). */
export function torusProfile(R, r, n = 24) {
  const pts = [];
  for (let k = 0; k <= n; k++) {
    // Counter-clockwise in (r, x), so the outward normal (dx, -dr) points away from the tube's centre line.
    const a = (k / n) * 2 * Math.PI;
    pts.push([R + r * Math.cos(a), r * Math.sin(a)]);
  }
  return [pts];
}

/** Solid rod of radius r from x0 to x1 with small chamfers. */
export function rodProfile(r, x0, x1, chamfer = Math.min(r * 0.3, (x1 - x0) / 4)) {
  return [
    [[0, x0], [r - chamfer, x0]],
    [[r - chamfer, x0], [r, x0 + chamfer]],
    [[r, x0 + chamfer], [r, x1 - chamfer]],
    [[r, x1 - chamfer], [r - chamfer, x1]],
    [[r - chamfer, x1], [0, x1]],
  ];
}

/**
 * Thick-walled tube from x0 to x1, outer radius ro, inner radius ri, with
 * chamfered outer edges.
 */
export function tubeProfile(ri, ro, x0, x1, chamfer = Math.min(0.8, (ro - ri) / 3, (x1 - x0) / 4)) {
  return [
    [[ri, x0], [ro - chamfer, x0]],
    [[ro - chamfer, x0], [ro, x0 + chamfer]],
    [[ro, x0 + chamfer], [ro, x1 - chamfer]],
    [[ro, x1 - chamfer], [ro - chamfer, x1]],
    [[ro - chamfer, x1], [ri, x1]],
    [[ri, x1], [ri, x0]],
  ];
}
