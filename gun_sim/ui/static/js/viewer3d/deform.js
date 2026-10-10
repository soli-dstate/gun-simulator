// Crumpling a projectile: the projectile's own (lathe) mesh, bent by one mapping
// that covers what a target does to it.
//
// The front of it, from xs to its tip, is squashed into a cap h long and
// spread: a point at radius r goes out to r * E, where E rises from `base` at xs
// to e towards the front. A nose's points close to the axis stay close to it
// (they make the cap's face) and its shoulder becomes the cap's rim, which is
// how a hollow point or soft point mushrooms. Then
//   petals: the rim splits into n petals (jacketed hollow points, monolithics),
//     or with n = 0 frays raggedly by `amp` (soft points, lead);
//   curl: the rim folds back towards the base, petals most;
//   jag: the cap's face is torn (a bullet broken at its cannelure, an eroded rod);
//   bend: the body bows sideways (a ricochet).
// The whole body, xs at its base, spread to e, is a bullet pancaked on steel; a
// long xs..tip squashed into a short h is a rod eroded down to a stub.
// Normals are carried through the map's Jacobian, so hard edges stay hard.

function hash(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** Smooth 1D value noise, period-free. */
function noise1(x) {
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
  return hash(i) * (1 - u) + hash(i + 1) * u;
}

/** Ragged noise round a circle (periodic in theta). */
function ring(theta, seed, k = 7) {
  const t = ((theta / (2 * Math.PI)) % 1 + 1) % 1;
  // Blend the two ends so it joins up at theta = 2 pi.
  const a = noise1(t * k + seed * 13.1), b = noise1((t - 1) * k + seed * 13.1);
  return a * (1 - t) + b * t;
}

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/**
 * The mapping. p: {x0, x1 (the mesh's base and tip), R (its radius), xs, h, e, base = 1, petals = 0, amp = 0,
 * curl = 0, jag = 0, bend = 0, seed = 0}.
 */
export function crumpler(p) {
  const { x0, x1, R, xs, h, e } = p;
  const base = p.base ?? 1, n = p.petals ?? 0, amp = p.amp ?? 0, curl = p.curl ?? 0, jag = p.jag ?? 0;
  const bend = p.bend ?? 0, seed = p.seed ?? 0;
  const span = Math.max(x1 - xs, 1e-6), L = Math.max(x1 - x0, 1e-6);
  return (x, y, z) => {
    let r = Math.hypot(y, z);
    const th = Math.atan2(z, y);
    let X = x;
    if (x > xs) {
      const u = Math.min(1, (x - xs) / span);
      let E = base + (e - base) * smooth(0, 0.55, u);
      const front = smooth(0.25, 1, u);
      if (n > 0) {
        // Petals: lobes round the rim, with splits between them that open as it spreads.
        const lobe = 0.5 + 0.5 * Math.cos(n * th + seed);
        E *= 1 + amp * (Math.pow(lobe, 0.6) - 0.6) * front;
      } else if (amp > 0) {
        E *= 1 + amp * (ring(th, seed) - 0.5) * 2 * front;
      }
      X = xs + h * (1 - (1 - u) * (1 - u));
      r *= E;
      // Folding back: what has spread past the original radius curls towards the base.
      const out = Math.max(0, r - R);
      X -= curl * out * (n > 0 ? 0.6 + 0.4 * Math.cos(n * th + seed) : 1) * front;
      if (jag > 0) X += jag * R * (ring(th * 1.7, seed + 3, 11) - 0.5) * 2 * front * (1 - Math.min(1, r / (R * e)) * 0.5);
    }
    let Y = r * Math.cos(th), Z = r * Math.sin(th);
    if (bend) Y += bend * L * Math.pow((X - x0) / L, 2);
    return [X, Y, Z];
  };
}

/** Mesh data {positions, normals, indices} bent by crumpler(params). */
export function crumple(mesh, params) {
  const f = crumpler(params);
  const P = mesh.positions, N = mesh.normals;
  const positions = new Float32Array(P.length), normals = new Float32Array(N.length);
  const eps = Math.max(1e-3, (params.x1 - params.x0) * 1e-4);
  for (let i = 0; i < P.length; i += 3) {
    const x = P[i], y = P[i + 1], z = P[i + 2];
    const q = f(x, y, z);
    positions[i] = q[0]; positions[i + 1] = q[1]; positions[i + 2] = q[2];
    // Jacobian columns by central differences; the normal goes as the inverse transpose (cofactors).
    const fx1 = f(x + eps, y, z), fx0 = f(x - eps, y, z);
    const fy1 = f(x, y + eps, z), fy0 = f(x, y - eps, z);
    const fz1 = f(x, y, z + eps), fz0 = f(x, y, z - eps);
    const a = [0, 1, 2].map((k) => (fx1[k] - fx0[k]) / (2 * eps));
    const b = [0, 1, 2].map((k) => (fy1[k] - fy0[k]) / (2 * eps));
    const c = [0, 1, 2].map((k) => (fz1[k] - fz0[k]) / (2 * eps));
    // cof(J) = [b x c, c x a, a x b] as rows; n' = cof(J) n.
    const bc = [b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0]];
    const ca = [c[1] * a[2] - c[2] * a[1], c[2] * a[0] - c[0] * a[2], c[0] * a[1] - c[1] * a[0]];
    const ab = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const nx = N[i], ny = N[i + 1], nz = N[i + 2];
    let mx = bc[0] * nx + ca[0] * ny + ab[0] * nz;
    let my = bc[1] * nx + ca[1] * ny + ab[1] * nz;
    let mz = bc[2] * nx + ca[2] * ny + ab[2] * nz;
    const det = a[0] * bc[0] + a[1] * bc[1] + a[2] * bc[2];
    if (det < 0) { mx = -mx; my = -my; mz = -mz; }
    const l = Math.hypot(mx, my, mz) || 1;
    normals[i] = mx / l; normals[i + 1] = my / l; normals[i + 2] = mz / l;
  }
  return { positions, normals, indices: mesh.indices };
}

/** Length along x, and radius, of mesh data. */
export function extent(mesh) {
  const P = mesh.positions;
  let x0 = Infinity, x1 = -Infinity, R = 0;
  for (let i = 0; i < P.length; i += 3) {
    x0 = Math.min(x0, P[i]); x1 = Math.max(x1, P[i]);
    R = Math.max(R, Math.hypot(P[i + 1], P[i + 2]));
  }
  return { x0, x1, R };
}

/** Lerp crumple params from untouched (k = 0) to fully crumpled (k = 1). */
export function partway(p, k) {
  // The cap shortens geometrically, so that as it spreads (by e^2) its volume stays about the same.
  const h0 = Math.max(p.x1 - p.xs, 1e-6);
  return {
    ...p,
    h: h0 * Math.pow(Math.max(p.h, 1e-6) / h0, k),
    e: 1 + (p.e - 1) * k,
    base: 1 + ((p.base ?? 1) - 1) * k,
    amp: (p.amp ?? 0) * k,
    curl: (p.curl ?? 0) * k,
    jag: (p.jag ?? 0) * k,
    bend: (p.bend ?? 0) * k,
  };
}

/** Irregular chunks (fragments, spall, splash): one mesh, each chunk a squashed, turned octahedron at its spot. */
export function chunks(list) {
  // list: [{p: [x, y, z], s: size, seed}]
  const positions = [], normals = [], indices = [];
  for (const { p, s, seed } of list) {
    const k = (i) => hash(seed * 7.3 + i);
    const ax = s * (0.6 + 0.8 * k(1)), ay = s * (0.4 + 0.6 * k(2)), az = s * (0.3 + 0.7 * k(3));
    const verts = [[ax, 0, 0], [-ax * (0.5 + k(4)), 0, 0], [0, ay, 0], [0, -ay * (0.5 + k(5)), 0], [0, 0, az], [0, 0, -az * (0.6 + k(6))]];
    const faces = [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]];
    // A random turn.
    const a = k(7) * 6.283, b = k(8) * 6.283;
    const ca = Math.cos(a), sa = Math.sin(a), cb = Math.cos(b), sb = Math.sin(b);
    const rot = ([x, y, z]) => {
      const x1 = ca * x - sa * y, y1 = sa * x + ca * y;
      return [x1, cb * y1 - sb * z, sb * y1 + cb * z];
    };
    const v = verts.map(rot);
    for (const [i, j, l] of faces) {
      // Wound counter-clockwise seen from outside: the face's normal points away from the chunk's centre.
      let A = v[i], B = v[j], C = v[l];
      const cross = (P, Q, S) => {
        const u = [Q[0] - P[0], Q[1] - P[1], Q[2] - P[2]], w = [S[0] - P[0], S[1] - P[1], S[2] - P[2]];
        return [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
      };
      let n = cross(A, B, C);
      if (n[0] * (A[0] + B[0] + C[0]) + n[1] * (A[1] + B[1] + C[1]) + n[2] * (A[2] + B[2] + C[2]) < 0) {
        [B, C] = [C, B];
        n = n.map((q) => -q);
      }
      const nl = Math.hypot(...n) || 1;
      const b0 = positions.length / 3;
      for (const q of [A, B, C]) { positions.push(q[0] + p[0], q[1] + p[1], q[2] + p[2]); normals.push(n[0] / nl, n[1] / nl, n[2] / nl); }
      indices.push(b0, b0 + 1, b0 + 2);
    }
  }
  return { positions: new Float32Array(positions), normals: new Float32Array(normals), indices: new Uint32Array(indices) };
}

export { hash };
