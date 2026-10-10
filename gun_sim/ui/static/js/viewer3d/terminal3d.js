// The Target tab in 3D: the shot meeting a steel plate or a block of ballistic
// gelatin, replayed in slow motion, with the projectile crumpling as the
// physics (terminal.py) says it does.
//
// Plate: a hanging gong, turned (lathe) about its normal so a crater, a hole, a
// bulge or a spall dish on its back are all part of its profile. Splash flies
// off the face, spall and debris off the back, each at its speed from the
// physics on the same slow-motion scale as the shot, then falls to the ground.
//
// Gelatin: the block is ray-marched (GelVolume): amber, a little cloudy. Along
// the track a texture holds, by depth, the temporary cavity's widest radius,
// the permanent channel's radius, when the bullet got there and how long the
// cavity takes to swell. The cavity swells behind the bullet, collapses and
// pulses (|sin|, damped), and where it stretched the gel it leaves the radial
// fissures a real block shows. The bullet opens, yaws and breaks up along the
// track as the gel series says. World units are millimetres; x is the line of flight.

import { buildCartridge, roundMeshes } from "./cartridge.js";
import { chunks, crumple, extent, hash, partway } from "./deform.js";
import { lathe } from "./lathe.js";
import { chain, invert, lookAt, perspective, rotationX, rotationY, rotationZ, translation } from "./mat4.js";import { CORE_MATERIALS, Renderer, link, projectileMaterial, srgbToLinear } from "./renderer.js";
import { box, rodProfile } from "./shapes.js";

const MM = 1e3;
const GEL_SIZE = 152;          // mm: a 6 x 6 in block
const GEL_BLOCK = 406;         // mm: 16 in long (blocks are laid end to end for a longer track)
const TRACK_SAMPLES = 512;
const PLAY_GEL = 4.5;          // s the gel's replay takes
const APPROACH = 0.7, CONTACT = 0.35, AFTER = 2.4;   // s: the plate's replay

const mat = (rgb, metallic, roughness, sec = rgb.map((c) => c * 0.8)) =>
  ({ color: srgbToLinear(rgb), metallic, roughness, section: srgbToLinear(sec) });
const GILDING = mat([0.8, 0.47, 0.3], 1, 0.28, [0.55, 0.3, 0.18]);
const PLATE_STEEL = mat([0.29, 0.3, 0.32], 0.85, 0.5, [0.58, 0.59, 0.63]);
const PLATE_ALU = mat([0.7, 0.71, 0.73], 0.9, 0.4, [0.75, 0.76, 0.78]);
const STAND = mat([0.13, 0.13, 0.14], 0.3, 0.7);
const GROUND = mat([0.2, 0.19, 0.17], 0, 0.95);
const CHAIN = mat([0.45, 0.46, 0.48], 1, 0.4);
const FLASH = { color: [0, 0, 0], metallic: 0, roughness: 1, section: [1, 0.6, 0.2], emissive: [9, 4, 1.2] };
const JET = { color: [0, 0, 0], metallic: 0, roughness: 1, section: [1, 0.8, 0.5], emissive: [7, 5.5, 3.5] };

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const smooth = (x) => { const t = clamp(x, 0, 1); return t * t * (3 - 2 * t); };
const norm = (v) => { const l = Math.hypot(...v) || 1; return v.map((c) => c / l); };
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** A matrix taking x to the unit vector d (and y, z to two perpendiculars), at p. */
function frame(d, p = [0, 0, 0]) {
  const up = Math.abs(d[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  const z = norm(cross(d, up)), y = cross(z, d);
  return new Float32Array([d[0], d[1], d[2], 0, y[0], y[1], y[2], 0, z[0], z[1], z[2], 0, p[0], p[1], p[2], 1]);
}

/** Interpolate the column `ys` of a series at `x` in the sorted column `xs`. */
function interp(xs, ys, x) {
  if (!xs.length) return 0;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let lo = 0, hi = xs.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  const t = (x - xs[lo]) / (xs[hi] - xs[lo] || 1);
  return ys[lo] + (ys[hi] - ys[lo]) * t;
}

// ---------------------------------------------------------------------------
// The gelatin block, ray-marched
// ---------------------------------------------------------------------------
const GEL_VS = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }`;

const GEL_FS = `#version 300 es
precision highp float;
uniform mat4 u_invViewProj;
uniform vec3 u_eye;
uniform vec2 u_resolution;
uniform sampler2D u_depth;
uniform sampler2D u_track;   // by depth: temporary cavity's widest radius, channel radius (mm), ms it got there, ms to swell
uniform vec3 u_boxMin, u_boxMax;
uniform float u_len;         // mm of track the texture covers
uniform float u_time;        // ms since the bullet met the face
uniform int u_pass;          // 0: what the gel lets through (multiplied), 1: the light it gives (added)
out vec4 outColor;

const vec3 SIGMA = vec3(0.0016, 0.0032, 0.0072);   // amber gel's absorption per mm
const vec3 AMBER = vec3(0.95, 0.6, 0.24);

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

// Fissures: n thin sheets fanning out from the track, wandering with depth; each reaches its own way out.
float fissures(vec3 p, float r, float reach, float n, float seed, float width) {
  float th = atan(p.z, p.y);
  float a = th / 6.28318 * n + (noise(vec2(p.x * 0.025, seed)) - 0.5) * 2.0 + (noise(vec2(p.x * 0.09, seed + 5.0)) - 0.5) * 0.6;
  float k = floor(a + 0.5);
  float d = abs(a - k) * 6.28318 / n * r;
  float own = reach * (0.3 + 0.7 * hash(vec2(k + seed, floor(p.x / 7.0))));
  return exp(-d * d / (width * width)) * (1.0 - smoothstep(own * 0.6, own, r));
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  float depth = texture(u_depth, uv).r;
  vec4 h = u_invViewProj * vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
  vec3 hit = h.xyz / h.w;
  vec3 rd = normalize(hit - u_eye);
  float tScene = length(hit - u_eye);
  vec3 inv = 1.0 / rd;
  vec3 ta = (u_boxMin - u_eye) * inv, tb = (u_boxMax - u_eye) * inv;
  vec3 tlo = min(ta, tb), thi = max(ta, tb);
  float tn = max(max(tlo.x, tlo.y), tlo.z), tf = min(min(thi.x, thi.y), thi.z);
  tn = max(tn, 0.0);
  float tEnd = min(tf, tScene);
  if (tEnd <= tn) discard;
  // (Float literals throughout: D3D's HLSL can't tell vec3(float, int, int) constructors apart.)
  vec3 n = tlo.x >= tlo.y && tlo.x >= tlo.z ? vec3(-sign(rd.x), 0.0, 0.0)
         : tlo.y >= tlo.z ? vec3(0.0, -sign(rd.y), 0.0) : vec3(0.0, 0.0, -sign(rd.z));

  const int STEPS = 200;
  float dt = (tEnd - tn) / float(STEPS);
  float jitter = hash(gl_FragCoord.xy);
  vec3 T = vec3(1.0), L = vec3(0.0);
  for (int i = 0; i < STEPS; i++) {
    vec3 p = u_eye + rd * (tn + (float(i) + jitter) * dt);
    float r = length(p.yz);
    vec4 tr = texture(u_track, vec2(clamp(p.x / u_len, 0.0, 1.0), 0.5));
    float cm = tr.r, ch = tr.g, age = u_time - tr.b, tau = max(tr.a, 0.05);
    float dens = 1.0, cloud = 0.0;
    vec3 emit = AMBER * 0.0005;   // the room's light scattered in the gel
    if (age > 0.0 && cm > 0.0) {
      float s = age / tau;
      // A real cavity is lumpy: its wall bulges unevenly round the track and along it.
      float th = atan(p.z, p.y);
      float lump = 1.0 + 0.32 * (noise(vec2(th * 1.6 + p.x * 0.01, p.x * 0.035)) - 0.5) + 0.12 * (noise(vec2(th * 4.0, p.x * 0.12 + 9.0)) - 0.5);
      float rc = cm * lump * abs(sin(1.5708 * s)) * exp(-0.7 * max(s - 1.0, 0.0)) * step(s, 8.0);
      if (r < rc) {
        dens = 0.0;   // the cavity: air
        emit = vec3(0.0);
      } else {
        float wall = exp(-pow((r - rc) / max(0.8, 0.05 * rc), 2.0)) * step(0.5, rc);
        emit += vec3(1.0, 0.93, 0.82) * wall * 0.05;
        float grown = smoothstep(0.0, 1.0, s);
        // The permanent channel: crushed, cloudy gel.
        float chan = 1.0 - smoothstep(ch * 0.7, ch * 1.4, r);
        emit += vec3(0.9, 0.78, 0.68) * chan * 0.06 * grown;
        cloud += chan * 0.05 * grown;
        // The stretch cracks, longer where the cavity was wider.
        float w = max(0.35, dt * 0.35);
        float f = fissures(p, r, cm * 0.85 * grown, 9.0, 1.3, w) + 0.6 * fissures(p, r, cm * 0.5 * grown, 17.0, 7.7, w);
        f *= step(ch * 0.5, r);
        emit += vec3(0.92, 0.9, 0.85) * f * 0.3;
        cloud += f * 0.06;
      }
    }
    L += T * emit * dt;
    T *= exp(-(SIGMA * dens + vec3(cloud)) * dt);
  }
  // A little of the room reflects off the face it is seen through.
  float F = 0.02 + 0.5 * pow(1.0 - abs(dot(n, rd)), 5.0);
  vec3 refl = reflect(rd, n);
  vec3 env = mix(vec3(0.04), vec3(0.75, 0.77, 0.82), smoothstep(-0.2, 0.8, refl.y));
  // Gel is glossy: the room's two lights glint off its faces (the same lights the meshes have).
  env += vec3(2.6, 2.5, 2.4) * pow(max(dot(refl, normalize(vec3(0.4, 0.8, 0.6))), 0.0), 120.0)
       + vec3(0.7, 0.75, 0.9) * pow(max(dot(refl, normalize(vec3(-0.7, 0.3, -0.5))), 0.0), 120.0);
  if (u_pass == 0) {
    outColor = vec4(pow(T * (1.0 - F), vec3(1.0 / 2.2)), 1.0);
  } else {
    vec3 c = L * (1.0 - F) + env * F;
    c = c * (2.51 * c + 0.03) / (c * (2.43 * c + 0.59) + 0.14);
    outColor = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)), 0.0);
  }
}`;

class GelVolume {
  constructor(gl) {
    this.gl = gl;
    this.program = link(gl, GEL_VS, GEL_FS);
    this.u = {};
    for (const k of ["u_invViewProj", "u_eye", "u_resolution", "u_depth", "u_track", "u_boxMin", "u_boxMax", "u_len", "u_time", "u_pass"]) {
      this.u[k] = gl.getUniformLocation(this.program, k);
    }
    this.vao = gl.createVertexArray();
    this.tex = gl.createTexture();
  }

  setTrack(data) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, TRACK_SAMPLES, 1, 0, gl.RGBA, gl.FLOAT, data);
    for (const p of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, p, gl.LINEAR);
    for (const p of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D, p, gl.CLAMP_TO_EDGE);
  }

  draw(gl, { depthTexture, viewProj }, eye, s) {
    const u = this.u;
    gl.useProgram(this.program);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, depthTexture);
    gl.uniform1i(u.u_depth, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.uniform1i(u.u_track, 1);
    gl.activeTexture(gl.TEXTURE0);
    gl.uniformMatrix4fv(u.u_invViewProj, false, invert(viewProj));
    gl.uniform3fv(u.u_eye, eye);
    gl.uniform2f(u.u_resolution, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform3fv(u.u_boxMin, s.boxMin);
    gl.uniform3fv(u.u_boxMax, s.boxMax);
    gl.uniform1f(u.u_len, s.len);
    gl.uniform1f(u.u_time, s.time);
    gl.bindVertexArray(this.vao);
    // What is behind is tinted by what the gel lets through, then the gel's own light is added.
    gl.blendFunc(gl.ZERO, gl.SRC_COLOR);
    gl.uniform1i(u.u_pass, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.blendFunc(gl.ONE, gl.ONE);
    gl.uniform1i(u.u_pass, 1);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    gl.disable(gl.BLEND);
    gl.enable(gl.DEPTH_TEST);
  }
}

// ---------------------------------------------------------------------------
// The projectile, and how it crumples
// ---------------------------------------------------------------------------
/** The projectile's meshes (mm, base at x = 0 along +x) and materials. */
function projectileModel(gun) {
  const cart = buildCartridge(gun);
  const m = roundMeshes(cart);
  const outer = m.projectile;
  const ext = extent(outer);
  const insert = cart.fills.find((f) => f.role === "insert");
  const coreMesh = insert ? m[insert.mesh] : m.core ?? null;
  return {
    outer, ext, coreMesh, coreExt: coreMesh ? extent(coreMesh) : ext,
    material: projectileMaterial(cart, GILDING),
    coreMaterial: CORE_MATERIALS[cart.coreMaterial] ?? CORE_MATERIALS[0],
    d: 2 * ext.R, L: ext.x1 - ext.x0,
    ogive: (gun.projectile.ogive_length ?? 0) * MM,
  };
}

/** Crumple parameters for what the physics says is left of it (null: it stays as it is). */
function crumpleFor(state, rem, pm, ext = pm.ext) {
  const { x0, x1, R } = ext, d = 2 * R, L = x1 - x0;
  const base = { x0, x1, R, seed: 2.3 };
  switch (state) {
    case "mushroom": {
      const e = rem.expansion;
      const xs = Math.max(x0 + 0.25 * L, x1 - Math.max(pm.ogive || 0.5 * L, 0.6 * d) - 0.25 * d);
      const petals = rem.petals ?? 0;
      return { ...base, xs, e, h: Math.max(0.15 * d, (x1 - xs) * 0.8 / e ** 1.5), petals,
               amp: petals ? 0.4 : rem.flattened ? 0.18 : 0.1, curl: petals ? 0.6 : 0.25, jag: 0.04 };
    }
    case "broken": {
      const xs = x0 + L * clamp(rem.length_share, 0.2, 0.95);
      return { ...base, xs, e: 1.08, h: 0.12 * d, amp: 0.15, jag: 0.7 };
    }
    case "splash": {
      const e = rem.expansion;
      return { ...base, xs: x0, e, base: e * 0.8, h: Math.max(0.05 * d, L * rem.length_share), amp: 0.3, jag: 0.15 };
    }
    case "ricochet":
      return { ...base, xs: x1 - 0.5 * d, e: rem.expansion, h: 0.3 * d, amp: 0.1, bend: 0.12 };
    case "eroded": {
      const keep = L * clamp(rem.length_share, 0.04, 1);
      const xs = Math.max(x0, x0 + keep - 0.6 * d);
      return { ...base, xs, e: 1.35, h: Math.min(0.6 * d, keep), amp: 0.2, jag: 0.35, curl: 0.3 };
    }
    case "jacket":
      // The jacket stripped off a core, crushed on the face.
      return { ...base, xs: x0, e: 1.8, base: 1.6, h: 0.18 * L, amp: 0.45, jag: 0.4 };
    default:
      return null;
  }
}

/** Where the front of a crumpled projectile is, k of the way (in _crumpled's steps), or `plain` if it isn't. */
function capFront(params, k, plain) {
  if (!params) return plain;
  return params.xs + partway(params, Math.round(clamp(k, 0, 1) * 24) / 24).h;
}

// ---------------------------------------------------------------------------
// The plate
// ---------------------------------------------------------------------------
/** The plate's profile for lathe (x across its thickness, the struck face at x = 0), damaged `k` of the way. */
export function plateParts(P, k) {
  const { Rp, T } = P;
  const ch = Math.min(1.5, T * 0.15);
  const bowl = (r0, x0, depth, q, back) => {
    // From r0 at the surface (x0) to the axis at x0 +- depth: x = x0 + depth (1 - (r / r0)^q).
    const pts = [];
    for (let i = 0; i <= 12; i++) {
      const r = r0 * (1 - i / 12);
      pts.push([r, x0 + (back ? -1 : 1) * depth * (1 - (r / r0) ** q)]);
    }
    return pts;
  };
  const parts = [];
  const holed = P.hole && k >= 0.6;
  const rim = [[[Rp - ch, 0], [Rp, ch]], [[Rp, ch], [Rp, T - ch]], [[Rp, T - ch], [Rp - ch, T]]];
  if (holed) {
    const rIn = P.rIn, rOut = P.rOut, lip = P.lip;
    parts.push([[rIn, 0], [Rp - ch, 0]], ...rim, [[Rp - ch, T], [rOut * 1.6, T]], [[rOut * 1.6, T], [rOut, T + lip]],
      [[rOut, T + lip], [rIn * 1.05, T * 0.5], [rIn, 0]]);
    return parts;
  }
  const dc = Math.min(P.dc * (P.hole ? Math.min(1, k / 0.6) : k), T * 0.92);
  const cr = P.cr * (0.4 + 0.6 * Math.min(1, k * 1.5));
  if (dc > 0.02) {
    const lipH = P.lipH * k;
    parts.push(bowl(cr, 0, dc, P.q, false).reverse(), [[cr, 0], [cr * 1.15, -lipH], [cr * 1.4, 0]], [[cr * 1.4, 0], [Rp - ch, 0]]);
  } else {
    parts.push([[0, 0], [Rp - ch, 0]]);
  }
  parts.push(...rim);
  const bulge = P.bulge * k;
  const ds = Math.min(P.ds * smooth((k - 0.75) / 0.25), Math.max(T - dc - 0.3, 0));
  if (ds > 0.05) {
    const rs = P.rs;
    parts.push([[Rp - ch, T], [rs, T]], bowl(rs, T, ds, 2, true));
  } else if (bulge > 0.02) {
    const rb = P.rb;
    const dome = [];
    for (let i = 0; i <= 12; i++) { const r = rb * (1 - i / 12); dome.push([r, T + bulge * (1 - (r / rb) ** 2) ** 2]); }
    parts.push([[Rp - ch, T], [rb, T]], dome);
  } else {
    parts.push([[Rp - ch, T], [0, T]]);
  }
  return parts;
}

// ---------------------------------------------------------------------------
// The view
// ---------------------------------------------------------------------------
const DEFAULT_VIEW = { gel: { yaw: -0.55, pitch: 0.3 }, plate: { yaw: -0.95, pitch: 0.22 } };

export class TerminalView {
  /** canvas: the scene; inset: a small canvas for the recovered projectile beside a new one; sound: ImpactSound. */
  constructor(canvas, inset, sound) {
    this.canvas = canvas;
    this.renderer = new Renderer(canvas, { opaque: true });
    this.gel = new GelVolume(this.renderer.gl);
    this.inset = inset ? new Renderer(inset) : null;
    this.insetCanvas = inset;
    this.sound = sound;
    this.meshes = [];          // GPU meshes of the current scene, freed on rebuild
    this.insetMeshes = [];
    this.cache = new Map();    // crumpled projectile meshes by key
    this.cut = false;
    this.t = 0;
    this.playing = false;
    this.zoom = 1;
    this.frame = 0;
    this.scene = null;
    this._bindControls();
    new ResizeObserver(() => this.requestDraw()).observe(canvas);  }

  setCut(on) {
    this.cut = on;
    // Look at the cut face.
    if (on && this.scene) this.yaw = this.scene.kind === "plate" ? -0.25 : -0.15;
    this.requestDraw();
  }

  /** Show a target result. A new result rebuilds the scene and replays it; the same one only redraws. */
  show(r, gun, { replay = true } = {}) {
    // The same hit asked for again (a redraw, or the app fetching it anew) doesn't replay it.
    const key = JSON.stringify([r.kind, r.target, r.velocity, r.thickness, r.angle, r.depth, r.verdict, gun]);
    if (key === this.key) { this.requestDraw(); return; }
    this.key = key;
    this.result = r;
    this.gun = gun;
    this._free();
    try {
      this.pm = projectileModel(gun);
    } catch (e) {
      this.pm = null;
    }
    const kind = r.kind === "gel" ? "gel" : "plate";
    if (!this.scene || this.scene.kind !== kind) {
      Object.assign(this, DEFAULT_VIEW[kind], { zoom: 1 });
      if (this.cut) this.yaw = kind === "plate" ? -0.25 : -0.15;
    }
    this.scene = kind === "gel" ? this._buildGel(r) : this._buildPlate(r);
    this._buildInset();
    if (replay) this.replay(); else { this.t = this.scene.duration; this.requestDraw(); }
  }

  replay() {
    if (!this.scene) return;
    this.t = 0;
    this.sounded = false;
    this.playing = true;
    this.last = performance.now();
    this.requestDraw();
  }

  requestDraw() {
    if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this._tick(); });
  }

  _free() {
    for (const m of this.meshes) this.renderer.deleteMesh(m);
    for (const m of this.cache.values()) this.renderer.deleteMesh(m);
    this.meshes = [];
    this.cache.clear();
  }

  _mesh(data) {
    const m = this.renderer.createMesh(data);
    this.meshes.push(m);
    return m;
  }

  /** The projectile's outer mesh crumpled `k` of the way to `params` (cached in steps). */
  _crumpled(key, mesh, params, k = 1) {
    if (!params) {
      const id = `${key}:plain`;
      if (!this.cache.has(id)) this.cache.set(id, this.renderer.createMesh(mesh));
      return this.cache.get(id);
    }
    const step = Math.round(clamp(k, 0, 1) * 24);
    const id = `${key}:${step}`;
    if (!this.cache.has(id)) this.cache.set(id, this.renderer.createMesh(crumple(mesh, partway(params, step / 24))));
    return this.cache.get(id);
  }

  _bindControls() {
    const c = this.canvas;
    let drag = null;
    c.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); });
    c.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw -= (e.clientX - drag.x) * 0.008;
      this.pitch = clamp(this.pitch + (e.clientY - drag.y) * 0.008, -1.4, 1.4);
      drag = { x: e.clientX, y: e.clientY };
      this.requestDraw();
    });
    const end = () => { drag = null; };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.zoom = clamp(this.zoom * Math.exp(e.deltaY * 0.001), 0.04, 4);
      this.requestDraw();
    }, { passive: false });
    c.addEventListener("dblclick", () => {
      if (this.scene) Object.assign(this, DEFAULT_VIEW[this.scene.kind], { zoom: 1 });
      this.requestDraw();
    });
  }

  _tick() {
    if (!this.scene) return;
    const now = performance.now();
    if (this.playing) {
      this.t += Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      if (this.t >= this.scene.duration) { this.t = this.scene.duration; this.playing = false; }
      this.requestDraw();
    }
    const items = this.scene.items(this.t);
    this._draw(items);
    if (this.inset) this._drawInset(now);
  }

  _camera(aspect, target, radius) {
    const fov = 32 * Math.PI / 180;
    const fovX = 2 * Math.atan(Math.tan(fov / 2) * aspect);
    const dist = radius / Math.sin(Math.min(fov, fovX) / 2) * this.zoom;
    const eye = [
      target[0] + dist * Math.cos(this.pitch) * Math.sin(this.yaw),
      target[1] + dist * Math.sin(this.pitch),
      target[2] + dist * Math.cos(this.pitch) * Math.cos(this.yaw),
    ];
    return { eye, view: lookAt(eye, target, [0, 1, 0]), proj: perspective(fov, aspect, Math.max(0.5, dist * 0.02), dist * 6 + radius * 4) };
  }

  _draw(items) {
    const s = this.scene;
    const aspect = this.renderer.resize();
    const camera = this._camera(aspect, s.target, s.radius);
    const clipPlane = this.cut ? [0, 0, 1, 0] : null;
    let overlay = null;
    if (s.kind === "gel") {
      const g = s.gelState(this.t);
      const boxMax = [s.Lb, GEL_SIZE / 2, this.cut ? 0 : GEL_SIZE / 2];
      overlay = (gl, ctx) => this.gel.draw(gl, ctx, camera.eye, { ...g, boxMin: [0, -GEL_SIZE / 2, -GEL_SIZE / 2], boxMax, len: s.Lb });
    }
    this.renderer.render({ camera, items, clipPlane, overlay, pointLight: s.light ? s.light(this.t) : null });
  }

  // -------------------------------------------------------------------------
  // Gel
  // -------------------------------------------------------------------------
  _buildGel(r) {
    const pm = this.pm, ser = r.series, rec = r.recovered;
    const depth = (r.depth ?? 0) * MM;
    const nBlocks = Math.max(1, Math.ceil((depth + 60) / GEL_BLOCK));
    const Lb = Math.min(1500, nBlocks * GEL_BLOCK);
    const v0 = r.velocity;
    const scene = { kind: "gel", Lb, target: [Lb / 2, 0, 0], radius: Math.max(Lb, GEL_SIZE * 2) * 0.4 };
    const statics = [{ mesh: this._mesh(box(Lb + 240, 24, GEL_SIZE + 140)), model: translation(Lb / 2, -GEL_SIZE / 2 - 12.5, 0), material: STAND }];
    // Blocks are laid end to end: a thin dark seam shows where they meet.
    const L = pm ? pm.L : 30, d = pm ? pm.d : 9;
    const approach = Math.max(120, 6 * L);
    const tIn = -approach / Math.max(v0, 1);   // ms before it meets the face (mm / (m/s) = ms)

    if (!ser || ser.depth.length < 2) {
      // It never gets into the block (an airburst) or goes off on its face.
      const burst = r.verdict === "detonated";
      const track = new Float32Array(TRACK_SAMPLES * 4).fill(0);
      for (let i = 0; i < TRACK_SAMPLES; i++) track[i * 4 + 2] = 1e4;
      this.gel.setTrack(track);
      const sphere = this._mesh(lathe([Array.from({ length: 17 }, (_, k) => {
        const a = -Math.PI / 2 + k / 16 * Math.PI; return [Math.cos(a), Math.sin(a)];
      })], 24));
      Object.assign(scene, {
        duration: 1.6, gelState: () => ({ time: -1 }),
        items: (t) => {
          const items = [...statics];
          const tt = -approach + approach * clamp(t / 0.8, 0, 1);
          if (pm && t < 0.8) items.push({ mesh: this._crumpled("p", pm.outer, null), model: translation(tt - pm.ext.x1, 0, 0), material: pm.material });
          if (burst && t >= 0.8 && t < 1.2) {
            const s = 60 * Math.sin(Math.PI * (t - 0.8) / 0.4) + 1;
            items.push({ mesh: sphere, model: chain(translation(-s * 0.3, 0, 0), new Float32Array([s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1])), material: FLASH, clip: false });
          }
          if (burst && t >= 0.8 && !this.sounded && this.playing) { this.sounded = true; this.sound?.gel({ energy: r.energy, cavity: 0.2 }); }
          return items;
        },
        light: (t) => (burst && t >= 0.8 && t < 1.3 ? { position: [-40, 0, 0], color: [40, 20, 6], range: 200 } : null),
      });
      return scene;
    }

    const xs = ser.depth.map((v) => v * MM), ts = ser.time.map((v) => v * MM);   // mm, ms
    const yaw = ser.yaw, open = ser.expansion;
    const cav = ser.cavity.map((v) => v * MM / 2), chan = ser.width.map((v) => v * MM / 2);
    const swell = (ser.swell ?? ser.cavity.map((c) => c / 2 * 0.0186)).map((v) => v * MM);   // ms
    // The track texture.
    const track = new Float32Array(TRACK_SAMPLES * 4);
    let tauMax = 0;
    for (let i = 0; i < TRACK_SAMPLES; i++) {
      const x = (i + 0.5) / TRACK_SAMPLES * Lb;
      const inside = x <= depth;
      const cm = inside ? interp(xs, cav, x) : 0;
      const tau = clamp(interp(xs, swell, x), 0.05, 5);
      tauMax = Math.max(tauMax, inside ? tau : 0);
      track.set([cm, inside ? interp(xs, chan, x) : 0, inside ? (x < xs[0] ? x / v0 : interp(xs, ts, x)) : 1e4, tau], i * 4);
    }
    this.gel.setTrack(track);
    const tTrack = ts[ts.length - 1];
    const tEnd = tTrack + 8.5 * tauMax;   // every cavity has collapsed (the shader drops it after 8 swell times)
    const total = tEnd - tIn;
    const simAt = (t) => tIn + total * clamp(t / PLAY_GEL, 0, 1);

    // How it crumples: opening along the track, or breaking up where it fragments.
    let params = null, kAt = () => 1;
    const eEnd = rec.expansion;
    if (pm) {
      if (rec.fragmented) {
        params = crumpleFor("broken", rec, pm);
        const tf = interp(xs, ts, (r.fragment_depth ?? 0) * MM);
        kAt = (tm) => (tm >= tf ? 1 : 0);
      } else if (eEnd > 1.05) {
        params = crumpleFor("mushroom", rec, pm);
        kAt = (tm) => (tm <= 0 ? 0 : (interp(ts, open, tm) - 1) / (eEnd - 1));
      }
    }
    // Fragments: thrown out from where it broke up into the cavity's stretch.
    const frags = [];
    if (rec.fragmented && rec.fragments > 0) {
      const xf = (r.fragment_depth ?? 0) * MM;
      const tf = interp(xs, ts, xf);
      const reach = interp(xs, cav, xf + 20);
      const each = rec.fragment_mass / rec.fragments;
      for (let i = 0; i < rec.fragments; i++) {
        const a = hash(i * 3.1) * 6.283, rho = (0.15 + 0.85 * hash(i * 5.7) ** 2) * reach * 0.9;
        const size = Math.cbrt(each * (0.3 + 1.4 * hash(i * 9.1)) / 11340 * 1e9) * 0.8;
        frags.push({
          mesh: this._mesh(chunks([{ p: [0, 0, 0], s: Math.max(0.4, size), seed: i + 1 }])),
          from: [xf, 0, 0], to: [xf + 5 + 70 * hash(i * 2.3), rho * Math.cos(a), rho * Math.sin(a)], t0: tf, dur: 0.25 + 0.3 * hash(i * 4.4),
        });
      }
    }
    const fragMat = pm?.coreMaterial ?? CORE_MATERIALS[0];
    Object.assign(scene, {
      duration: PLAY_GEL,
      gelState: (t) => ({ time: simAt(t) }),
      items: (t) => {
        const tm = simAt(t);
        const items = [...statics];
        if (tm >= 0 && !this.sounded && this.playing) {
          this.sounded = true;
          this.sound?.gel({ energy: r.energy, cavity: r.temporary_cavity });
        }
        if (pm) {
          const x = tm < 0 ? tm * v0 : interp(ts, xs, tm);   // the front of it
          const phi = (tm < 0 ? 0 : interp(ts, yaw, tm)) * Math.PI / 180;
          const k = params ? clamp(kAt(tm), 0, 1) : 0;
          const mesh = this._crumpled("gel", pm.outer, params, k);
          // Turn it about its middle; keep its leading point at x.
          const e = pm.ext, mid = (e.x0 + e.x1) / 2;
          const half = (e.x1 - e.x0) / 2 * (params ? 1 - 0.4 * k : 1);
          const lead = half * Math.abs(Math.cos(phi)) + e.R * Math.abs(Math.sin(phi));
          items.push({ mesh, model: chain(translation(x - lead, 0, 0), rotationZ(phi), translation(-mid, 0, 0)), material: pm.material });
        }
        for (const f of frags) {
          if (tm < f.t0) continue;
          const s = 1 - (1 - clamp((tm - f.t0) / f.dur, 0, 1)) ** 3;
          const p = f.from.map((v, i) => v + (f.to[i] - v) * s);
          items.push({ mesh: f.mesh, model: translation(...p), material: fragMat });
        }
        return items;
      },
    });
    return scene;
  }

  // -------------------------------------------------------------------------
  // Plate
  // -------------------------------------------------------------------------
  _buildPlate(r) {
    const pm = this.pm, rem = r.remnant ?? { state: "intact" }, sp = r.spall, spl = r.splash;
    const T = r.thickness * MM, theta = r.angle * Math.PI / 180;
    const bore = (this.gun.barrel.bore_diameter ?? 0.01) * MM;
    const d = pm ? pm.d : bore, L = pm ? pm.L : 3 * bore;
    const Rp = clamp(Math.max(100, 14 * T, 8 * bore), 100, 900);
    const n = [Math.cos(theta), -Math.sin(theta), 0];       // the plate's normal, into it
    const plateModel = rotationZ(-theta);
    const depth = Math.min(r.depth * MM, T * 3);
    const los = r.line_of_sight * MM;
    const coreD = (r.core?.diameter ?? d / MM) * MM;
    const regime = r.regime, perforated = r.perforated;
    // The damage, in the plate's own frame.
    const P = { Rp, T, hole: perforated || r.verdict === "breached", dc: depth * Math.cos(theta), cr: coreD * 0.6, q: 6,
                lipH: 0, bulge: 0, rb: coreD * 2, ds: 0, rs: 0, rIn: coreD * 0.55, rOut: coreD * 0.75, lip: Math.min(T * 0.3, coreD * 0.4) };
    if (regime === "splash") Object.assign(P, { cr: Math.max(coreD * 0.9, depth * 3), q: 2, lipH: depth * 0.25 });
    if (regime === "eroding") Object.assign(P, { cr: coreD * 1.1, rIn: coreD * 0.95, rOut: coreD * 1.3, q: 4, lipH: coreD * 0.15 });
    if (regime === "jet") Object.assign(P, { cr: Math.max(coreD * 0.3, 2), rIn: Math.max(bore * 0.1, 2), rOut: Math.max(bore * 0.08, 1.5), q: 8 });
    if (regime === "blast") Object.assign(P, { cr: bore * 0.8, rIn: bore * 0.7, rOut: bore * 0.9, q: 2, lipH: bore * 0.05 });
    if (rem.state === "ricochet") Object.assign(P, { dc: Math.max(depth, 0.3), cr: d * 0.8, q: 2, lipH: 0.2 });
    if (sp?.bulge) Object.assign(P, { bulge: sp.bulge * Math.min(T * 0.35, coreD), rb: coreD + T });
    if (sp && ["shock", "bulge", "scab"].includes(sp.cause)) Object.assign(P, { ds: (sp.thickness ?? 0) * MM, rs: Math.min(Rp * 0.8, sp.diameter * MM / 2) });

    const plateMat = r.target === "aluminium" ? PLATE_ALU : PLATE_STEEL;
    const plateCache = new Map();
    const plateMesh = (k) => {
      const step = Math.round(clamp(k, 0, 1) * 16);
      if (!plateCache.has(step)) plateCache.set(step, this._mesh(lathe(plateParts(P, step / 16), 96)));
      return plateCache.get(step);
    };
    // The face is painted, as targets are: a thin disc just in front of it, holed where the plate is.
    const groundY = -Rp * 1.55;
    const statics = [
      { mesh: this._mesh(box(Rp * 8, 10, Rp * 6)), model: translation(Rp * 0.5, groundY - 5, 0), material: GROUND },
    ];
    // Hung from a crossbar by two chains.
    const top = (z) => {
      const y = Rp * 0.88, x = 0;
      return [x * Math.cos(theta) + y * Math.sin(theta), -x * Math.sin(theta) + y * Math.cos(theta), z];
    };
    const barY = Rp * 1.45, barX = T / 2;
    const rod = (a, b, rad) => {
      const dv = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], len = Math.hypot(...dv);
      return { mesh: this._mesh(lathe(rodProfile(rad, 0, len), 12)), model: frame(norm(dv), a), material: CHAIN };
    };
    for (const z of [-Rp * 0.45, Rp * 0.45]) statics.push(rod(top(z), [barX, barY, z], Math.max(1.2, Rp * 0.012)));
    statics.push({ ...rod([barX, barY, -Rp * 1.2], [barX, barY, Rp * 1.2], Math.max(4, Rp * 0.04)), material: STAND });
    for (const z of [-Rp * 1.2, Rp * 1.2]) statics.push({ ...rod([barX, groundY, z], [barX, barY, z], Math.max(4, Rp * 0.04)), material: STAND });

    // Visual scale: the projectile closes the last `approach` mm in APPROACH s; everything else flies on the same scale.
    const approach = Math.max(6 * L, 0.7 * Rp);
    const scale = approach / APPROACH / Math.max(r.velocity, 1);   // mm per (m/s) per s of replay
    const g = 2 * (Rp * 1.6) / 1.4 ** 2;                            // falls from the middle to the ground in ~1.4 s
    const fly = (p0, dir, speed, t, size = 1) => {
      // Slowed by the air (decay over `stop` mm), falling, until it lands.
      const stop = Rp * 2.4 * Math.min(1, speed * scale / (approach / APPROACH));
      const tau = stop / Math.max(speed * scale, 1e-6);
      const s = stop * (1 - Math.exp(-t / tau));
      const p = [p0[0] + dir[0] * s, p0[1] + dir[1] * s - 0.5 * g * t * t, p0[2] + dir[2] * s];
      p[1] = Math.max(p[1], groundY + size * 0.5);
      return p;
    };
    const rnd = (i, k) => hash(i * 12.9898 + k * 78.233);
    const coneDir = (axis, half, i) => {
      // A direction within `half` (deg) of axis, spread evenly by area.
      const c = 1 - (1 - Math.cos(half * Math.PI / 180)) * rnd(i, 1), s = Math.sqrt(1 - c * c), a = 6.283 * rnd(i, 2);
      const f = frame(axis);
      return [0, 1, 2].map((k) => f[k] * c + f[4 + k] * s * Math.cos(a) + f[8 + k] * s * Math.sin(a));
    };
    // Splash off the face: out across the face and back a little towards the shooter.
    const splash = [];
    if (spl && spl.count > 0) {
      const N = Math.min(40, spl.count), each = spl.mass / spl.count;
      const f = frame(n);
      for (let i = 0; i < N; i++) {
        const a = 6.283 * rnd(i, 3), b = (spl.off_face * (0.3 + 0.9 * rnd(i, 4))) * Math.PI / 180;
        const radial = [0, 1, 2].map((k) => f[4 + k] * Math.cos(a) + f[8 + k] * Math.sin(a));
        const dir = norm(radial.map((v, k) => v * Math.cos(b) - n[k] * Math.sin(b)));
        const size = Math.max(0.35, Math.cbrt(each * (0.3 + 1.4 * rnd(i, 5)) / 11340 * 1e9));
        splash.push({ mesh: this._mesh(chunks([{ p: [0, 0, 0], s: size, seed: i + 7 }])), dir, speed: spl.velocity * (0.5 + 0.7 * rnd(i, 6)), size });
      }
    }
    // Off the back: debris (once through), a spalled scab or dish, and its pieces.
    const debris = [];
    let disc = null;
    if (sp && sp.cause) {
      const N = Math.min(40, sp.count ?? 8), each = (sp.mass ?? 0) / Math.max(sp.count ?? 8, 1);
      const back = [n[0] * T, n[1] * T, n[2] * T];
      for (let i = 0; i < N; i++) {
        const dir = coneDir([1, 0, 0], sp.cone ?? 25, i + 50);
        const size = clamp(Math.cbrt(each * (0.3 + 1.4 * rnd(i, 8)) / 7850 * 1e9), 0.4, Rp * 0.12);
        debris.push({ mesh: this._mesh(chunks([{ p: [0, 0, 0], s: size, seed: i + 70 }])), dir, from: back, speed: sp.velocity * (0.4 + 0.8 * rnd(i, 9)), size });
      }
      if (["shock", "bulge", "scab"].includes(sp.cause) && P.ds > 0) {
        const rs = P.rs, ds = P.ds;
        disc = { mesh: this._mesh(lathe([[[0, 0], [rs, 0]], [[rs, 0], [rs * 0.8, ds]], [[rs * 0.8, ds], [0, ds * 1.6]]], 48)), speed: sp.velocity, from: [n[0] * (T - ds), n[1] * (T - ds), 0] };
      }
    }
    // The projectile: in, crumpling, and what is left of it going on.
    const state = rem.state;
    const crumpleState = { splash: "splash", ricochet: "ricochet", eroded: "eroded" }[state];
    const params = pm && crumpleState ? crumpleFor(crumpleState, rem, pm) : null;
    const jacketParams = pm && rem.stripped ? crumpleFor("jacket", rem, pm) : null;
    const pieces = [];
    if (state === "shattered" && pm) {
      const N = rem.pieces ?? 10, each = (r.core?.mass ?? 0.005) / N;
      for (let i = 0; i < N; i++) {
        const size = Math.max(0.5, Math.cbrt(each / 7850 * 1e9) * (0.6 + 0.8 * rnd(i, 11)));
        pieces.push({ mesh: this._mesh(chunks([{ p: [0, 0, 0], s: size, seed: i + 120 }])), dir: coneDir([perforated ? 1 : -1, 0, 0], perforated ? 20 : 70, i + 90), speed: (perforated ? r.residual_velocity : 0.2 * r.velocity) * (0.6 + 0.6 * rnd(i, 12)), size });
      }
    }
    const sphere = this._mesh(lathe([Array.from({ length: 17 }, (_, k) => { const a = -Math.PI / 2 + k / 16 * Math.PI; return [Math.cos(a), Math.sin(a)]; })], 24));
    const scaleM = (s) => new Float32Array([s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]);
    // Where it leaves the face, if it glances off.
    let ricochetDir = null;
    if (state === "ricochet") {
      const dIn = [1, 0, 0], dn = dIn[0] * n[0] + dIn[1] * n[1] + dIn[2] * n[2];
      const tang = norm(dIn.map((v, k) => v - dn * n[k]));
      const b = (rem.departure ?? 10) * Math.PI / 180;
      ricochetDir = norm(tang.map((v, k) => v * Math.cos(b) - n[k] * Math.sin(b)));
    }
    const duration = APPROACH + CONTACT + AFTER;
    const target = [T / 2, 0, 0];
    const scene = { kind: "plate", target, radius: Rp * 1.25, duration };
    const coreMesh = pm?.coreMesh ?? pm?.outer;
    const coreExt = pm?.coreExt ?? pm?.ext;
    const exits = perforated && !["burst", "dust"].includes(state);
    const mmDepth = Math.min(depth, los);

    scene.items = (t) => {
      const items = [...statics];
      const tc = t - APPROACH;                         // s since contact
      const k = clamp(tc / CONTACT, 0, 1), ke = smooth(k);
      if (tc >= 0 && !this.sounded && this.playing) {
        this.sounded = true;
        this.sound?.plate({
          thickness: r.thickness, diameter: 2 * Rp / MM, modulus: r.plate?.modulus ?? 205e9, density: r.plate?.density ?? 7850,
          loss: r.plate?.loss ?? 6e-4, energy: r.energy, contact: L / MM / Math.max(r.velocity, 1), holed: perforated,
          tear: perforated ? 1 : sp?.cause ? 0.5 : 0, debris: sp?.count ?? 0, splash: spl?.count ?? 0, seed: Math.round(r.velocity),
        });
      }
      items.push({ mesh: plateMesh(tc < 0 ? 0 : ke), model: plateModel, material: plateMat });
      if (pm) {
        const e = pm.ext;
        if (tc < 0) {
          const front = -approach * (-tc / APPROACH);
          items.push({ mesh: this._crumpled("p", pm.outer, null), model: translation(front - e.x1, 0, 0), material: pm.material });
        } else if (state === "splash" || state === "ricochet") {
          // Squashed against the face (which it pushes into: the crater), then a ricochet leaves.
          const mesh = this._crumpled("hit", pm.outer, params, ke);
          const front = capFront(params, ke, e.x1);
          let model = translation(mmDepth * ke - front, 0, 0);
          if (ricochetDir && tc > CONTACT) {
            const p = fly([0, 0, 0], ricochetDir, r.velocity * 0.6, tc - CONTACT, d);
            model = chain(translation(...p), frame(ricochetDir), translation(-(e.x0 + e.x1) / 2, 0, 0));
          }
          items.push({ mesh, model, material: pm.material });
        } else if (state === "eroded" || state === "intact" || state === "shattered") {
          // It goes in, getting shorter if it erodes; through and on if it perforates.
          const body = state === "eroded" ? this._crumpled("hit", pm.outer, params, ke) : null;
          const useCore = rem.stripped && coreMesh;
          const ex = useCore ? coreExt : e;
          let tip = mmDepth * ke;
          if (exits && tc > CONTACT) tip = los + ((r.residual_velocity ?? 0) * scale) * (tc - CONTACT) + 2;
          const tipNow = state === "eroded" ? capFront(params, ke, ex.x1) : ex.x1;
          if (!(state === "shattered" && k >= 0.5)) {
            const mesh = body ?? (useCore ? this._crumpled("core", coreMesh, null) : this._crumpled("p", pm.outer, null));
            items.push({ mesh, model: translation(tip - tipNow, 0, 0), material: useCore ? pm.coreMaterial : pm.material });
          }
          if (jacketParams) {
            const jm = this._crumpled("jacket", pm.outer, jacketParams, ke);
            const front = capFront(jacketParams, ke);
            items.push({ mesh: jm, model: translation(-front - 0.2, 0, 0), material: pm.material });
          }
        }
      }
      if (tc >= 0) {
        // A flash: the round going off on the face, or the jet.
        if (state === "burst" && tc < 0.35) {
          const s = Math.max(1, bore * 3 * Math.sin(Math.PI * tc / 0.35));
          items.push({ mesh: sphere, model: chain(translation(-s * 0.4, 0, 0), scaleM(s)), material: FLASH, clip: false });
        }
        if (regime === "jet" && tc < CONTACT) {
          const len = Math.max(1, (r.payload?.jet?.depth ?? los / MM) * MM * ke);
          items.push({ mesh: sphere, model: chain(translation(len / 2, 0, 0), new Float32Array([len / 2, 0, 0, 0, 0, 1.2, 0, 0, 0, 0, 1.2, 0, 0, 0, 0, 1])), material: JET, clip: false });
        }
        const ta = Math.max(0, tc - 0.02);
        for (const s of splash) items.push({ mesh: s.mesh, model: translation(...fly([-1 * n[0], -1 * n[1], 0], s.dir, s.speed, ta, s.size)), material: CORE_MATERIALS[0] });
        const tb = Math.max(0, tc - CONTACT * 0.7);
        if (tc > CONTACT * 0.7) {
          for (const p of debris) items.push({ mesh: p.mesh, model: translation(...fly(p.from, p.dir, p.speed, tb, p.size)), material: plateMat });
          for (const p of pieces) items.push({ mesh: p.mesh, model: translation(...fly([mmDepth, 0, 0], p.dir, p.speed, tb, p.size)), material: pm.coreMaterial });
          if (disc) {
            const p = fly(disc.from, n, disc.speed, tb, P.ds * 2);
            items.push({ mesh: disc.mesh, model: chain(translation(...p), plateModel, rotationX(tb * 2)), material: plateMat });
          }
        }
      }
      return items;
    };
    scene.light = (t) => {
      const tc = t - APPROACH;
      if (tc < 0 || tc > 0.4) return null;
      if (state === "burst") return { position: [-bore * 2, 0, 0], color: [60, 30, 8].map((c) => c * (1 - tc / 0.4)), range: bore * 20 };
      // Sparks off steel struck hard.
      if (r.velocity > 600 && r.target !== "aluminium" && tc < 0.12) return { position: [-5, 0, 0], color: [8, 5, 2], range: Math.max(30, d * 6) };
      return null;
    };
    return scene;
  }

  // -------------------------------------------------------------------------
  // The recovered projectile beside a new one
  // -------------------------------------------------------------------------
  _buildInset() {
    if (!this.inset) return;
    for (const m of this.insetMeshes) this.inset.deleteMesh(m);
    this.insetMeshes = [];
    this.insetItems = null;
    const pm = this.pm, r = this.result;
    this.insetCanvas.parentElement.hidden = true;
    if (!pm) return;
    let mesh = null, material = pm.material, ext = pm.ext, label = "recovered";
    if (r.kind === "gel") {
      const rec = r.recovered;
      if (!rec) return;
      const p = rec.fragmented ? crumpleFor("broken", rec, pm) : rec.expansion > 1.05 ? crumpleFor("mushroom", rec, pm) : null;
      mesh = p ? crumple(pm.outer, p) : pm.outer;
    } else {
      const rem = r.remnant;
      if (!rem || ["burst", "dust", "shattered"].includes(rem.state)) return;
      const st = { splash: "splash", ricochet: "ricochet", eroded: "eroded" }[rem.state];
      if (rem.stripped && pm.coreMesh) {
        mesh = pm.coreMesh; material = pm.coreMaterial; ext = pm.coreExt; label = "the core, stripped";
      } else {
        const p = st ? crumpleFor(st, rem, pm) : null;
        mesh = p ? crumple(pm.outer, p) : pm.outer;
      }
    }
    const a = this.inset.createMesh(pm.outer), b = this.inset.createMesh(mesh);
    this.insetMeshes.push(a, b);
    const be = extent(mesh);
    this.insetItems = { a, b, ext: pm.ext, be, material, label, R: Math.max(pm.ext.R, be.R) };
    this.insetCanvas.parentElement.hidden = false;
    const cap = this.insetCanvas.parentElement.querySelector(".cap");
    if (cap) cap.textContent = `as fired · ${label}`;
  }

  _drawInset(now) {
    const it = this.insetItems;
    if (!it) return;
    const aspect = this.inset.resize();
    const R = it.R, L = Math.max(it.ext.x1 - it.ext.x0, it.be.x1 - it.be.x0);
    const gap = Math.max(R * 2.6, L * 0.25);
    const fov = 30 * Math.PI / 180, tn = Math.tan(fov / 2);
    // Stood up, they are L tall and 2 (gap + R) wide.
    const dist = Math.max(L * 0.62 / tn, (gap + R * 1.5) / (tn * aspect));
    const spin = now / 1000 * 0.6;
    const eye = [dist * 0.25, dist * 0.35, dist];
    const camera = { eye, view: lookAt(eye, [0, 0, 0], [0, 1, 0]), proj: perspective(fov, aspect, dist * 0.05, dist * 4) };
    // Stood up on their bases, side by side, turning slowly.
    const stand = (ext) => chain(rotationY(spin), rotationZ(Math.PI / 2), translation(-(ext.x0 + ext.x1) / 2, 0, 0));
    const items = [
      { mesh: it.a, model: chain(translation(-gap, 0, 0), stand(it.ext)), material: this.pm.material },
      { mesh: it.b, model: chain(translation(gap, 0, 0), stand(it.be)), material: it.material },
    ];
    this.inset.render({ camera, items });
    // Keep it turning while it is on screen (the main view only redraws when something changes).
    if (!this.playing && this.insetCanvas.offsetParent !== null) {
      this.insetFrame ||= requestAnimationFrame(() => { this.insetFrame = 0; if (this.insetItems) this._drawInset(performance.now()); });
    }
  }
}
