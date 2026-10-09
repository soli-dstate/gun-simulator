// Operations on mesh data ({positions, normals, indices}) shared by the gun
// builders: rigid transforms, scaling, merging, and a few placed primitives.

import { lathe } from "./lathe.js";
import { chain, rotationY, rotationZ, translation } from "./mat4.js";
import { box, prism, rodProfile } from "./shapes.js";

/** Apply a rigid transform to mesh data. */
export function bake(mesh, m) {
  const p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i], y = p[i + 1], z = p[i + 2];
    positions[i] = m[0] * x + m[4] * y + m[8] * z + m[12];
    positions[i + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
    positions[i + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    const a = n[i], b = n[i + 1], c = n[i + 2];
    normals[i] = m[0] * a + m[4] * b + m[8] * c;
    normals[i + 1] = m[1] * a + m[5] * b + m[9] * c;
    normals[i + 2] = m[2] * a + m[6] * b + m[10] * c;
  }
  return { positions, normals, indices: mesh.indices };
}

/** Scale mesh data about the origin; normals by the inverse scale, renormalised. */
export function scaled(mesh, sx, sy, sz) {
  const p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    positions[i] = p[i] * sx; positions[i + 1] = p[i + 1] * sy; positions[i + 2] = p[i + 2] * sz;
    const a = n[i] / sx, b = n[i + 1] / sy, c = n[i + 2] / sz, l = Math.hypot(a, b, c) || 1;
    normals[i] = a / l; normals[i + 1] = b / l; normals[i + 2] = c / l;
  }
  return { positions, normals, indices: mesh.indices };
}

/** Join several meshes into one. Pass [mesh, transform] pairs or bare meshes. */
export function merge(...entries) {
  const meshes = entries.map((e) => (Array.isArray(e) ? bake(e[0], e[1]) : e));
  const nv = meshes.reduce((s, m) => s + m.positions.length, 0);
  const ni = meshes.reduce((s, m) => s + m.indices.length, 0);
  const positions = new Float32Array(nv), normals = new Float32Array(nv), indices = new Uint32Array(ni);
  let vo = 0, io = 0;
  for (const m of meshes) {
    positions.set(m.positions, vo);
    normals.set(m.normals, vo);
    for (let i = 0; i < m.indices.length; i++) indices[io + i] = m.indices[i] + vo / 3;
    vo += m.positions.length;
    io += m.indices.length;
  }
  return { positions, normals, indices };
}

export const boxAt = (sx, sy, sz, x, y, z) => [box(sx, sy, sz), translation(x, y, z)];
/** Rods of radius r along x (at y, z) and along y (at x, z). */
export const rodX = (r, x0, x1, y = 0, z = 0, seg = 24) => [lathe(rodProfile(r, x0, x1), seg), translation(0, y, z)];
export const rodY = (r, y0, y1, x, z = 0, seg = 24) => [lathe(rodProfile(r, y0, y1), seg), chain(translation(x, 0, z), rotationZ(Math.PI / 2))];
/** A pin along z through (x, y). */
export const pinZ = (r, half, x, y, seg = 32) => [lathe(rodProfile(r, -half, half), seg), chain(translation(x, y, 0), rotationY(Math.PI / 2))];
/** A pistol grip: top edge centred on x at yTop, raked back by `rake` per unit of height. */
export const gripAt = (x, yTop, h, w, rake, sz) =>
  prism([[x + w / 2, yTop], [x - w / 2, yTop], [x - w / 2 - rake * h, yTop - h], [x + w / 2 - rake * h, yTop - h]], sz);

/** Boxes along x from x0 to x1, leaving out [a, b]: a receiver part with an opening cut from it. */
export function cutX(x0, x1, a, b, make) {
  if (b <= x0 || a >= x1) return [make(x0, x1)];
  const out = [];
  if (a - x0 > 0.5) out.push(make(x0, a));
  if (x1 - b > 0.5) out.push(make(b, x1));
  return out;
}
