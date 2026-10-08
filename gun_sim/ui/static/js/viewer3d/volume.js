// Volumetric effects, ray-marched in one full-screen pass over the scene:
//
// - The muzzle plume (gun_sim/plume.py): the gas that left the muzzle, solved
//   in 2D. Its temperature and propellant-gas density come as frames of an
//   axisymmetric field, held in a 3D texture (x, r, frame) and spun about the
//   bore axis. Hot propellant gas glows by Wien's law with a blackbody colour
//   (primary, intermediate and secondary flash are just where it is hot); the
//   same gas carries the smoke. After the solved window the last frame is
//   carried on as a growing, thinning puff (range.js works out how).
// - Smoke puffs (absorbing and scattering): gas seeping out of the exit
//   afterwards, and out of the opened breech. Shaped by 3D noise.
// - Hot propellant gas in the bore behind the projectile, glowing as hot as
//   the fluid model says it is. It's a thin cylinder, so instead of marching
//   it the ray's chord through it is found exactly and sampled along.
//
// The marched effects are split into two groups (around the muzzle, and
// around the breech), each with a bounding sphere, so every ray only marches
// the stretch that can hold something. The scene's depth stops rays at solid
// surfaces.
// World units are millimetres.

import { identity, invert } from "./mat4.js";
import { link } from "./renderer.js";

export const MAX_SMOKE = 4;
export const MAX_FIELD = 2;
export const BORE_POINTS = 24;   // temperatures along the gas column (fluid.BORE_GAS_POINTS)
const LUT = 1024;                // samples of the grid's mm -> cell maps

const VS = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }`;

const FS = `#version 300 es
precision highp float;
precision highp sampler3D;
#define MAX_SMOKE ${MAX_SMOKE}
#define MAX_FIELD ${MAX_FIELD}
#define BORE_POINTS ${BORE_POINTS}
#define LUT ${LUT}
// Brightness of glowing gas per mm of path and kg/m^3 of propellant gas at 2500 K; smoke's
// extinction per mm and kg/m^3 (some tenths of a percent of the gas is particles and condensate,
// at a few m^2 per gram); glow of the gas in the bore per mm at 2500 K.
const float GLOW = 0.1, SMOKE = 0.012, BORE_GLOW = 0.04;
const float WIEN = 23980.0, T_REF = 2500.0, T_AIR = 288.0;

uniform mat4 u_invViewProj;
uniform vec3 u_eye;
uniform vec2 u_resolution;
uniform sampler2D u_depth;
uniform vec4 u_bound[2];                 // per group: bounding sphere (xyz centre, w radius; 0 = empty)
uniform vec4 u_clipPlane;                // the section cut (applied to the bore gas only)
uniform float u_time;                    // s since the latest exit, animates the turbulence

uniform sampler3D u_field;               // RG: temperature, log density of propellant gas; z = frame
uniform sampler2D u_lut;                 // row 0: x (mm) -> cell, row 1: r (mm) -> cell
uniform vec4 u_fieldGrid;                // x from, x to, r to (mm, from the muzzle face), unused
uniform vec2 u_fieldCells;               // nx, nr
uniform int u_fieldCount;
uniform mat4 u_fieldInv[MAX_FIELD];      // world -> the field's frame (mm, x along the bore from the muzzle face)
uniform vec4 u_fieldA[MAX_FIELD];        // frame (texture z), scale, density factor, temperature factor
uniform vec4 u_fieldB[MAX_FIELD];        // x the field scales about, noise seed, -, -

uniform int u_smokeCount;
uniform vec3 u_smokeOrigin[MAX_SMOKE];
uniform vec3 u_smokeDir[MAX_SMOKE];
uniform vec4 u_smokeShape[MAX_SMOKE];    // reach along dir, radius, extinction (1/mm), rise (mm)
uniform vec4 u_smokeMisc[MAX_SMOKE];     // age (s), group, seed, trail strength

uniform vec4 u_gas;                      // start x, end x, on (0/1), bore radius
uniform vec2 u_gasCase;                  // case cavity radius, x where the case necks down
uniform float u_boreT[BORE_POINTS];      // K, evenly along the gas column from start to end
uniform mat4 u_gunInv;                   // world -> the rifle's frame (it recoils and pitches); the bore gas lives there

uniform vec3 u_lightPos;                 // the flash's light, which lights the smoke
uniform vec3 u_lightColor;
uniform float u_lightRange;
out vec4 outColor;

float hash(vec3 p) {
  p = fract(p * 0.3183099 + 0.1);
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x),
                 mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
                 mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

const mat3 ROT = mat3(0.00, 0.80, 0.60, -0.80, 0.36, -0.48, -0.60, -0.48, 0.64);
float fbm(vec3 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * noise(p); p = ROT * p * 2.03; a *= 0.5; }
  return v / 0.9375;
}

// Glow of hot gas relative to gas at T_REF (Wien's law in orange light), and its colour.
float wien(float T) { return exp(-WIEN * (1.0 / max(T, 300.0) - 1.0 / T_REF)); }
vec3 blackbody(float T) {
  vec3 c = mix(vec3(1.0, 0.1, 0.0), vec3(1.0, 0.42, 0.1), smoothstep(900.0, 1600.0, T));
  return mix(c, vec3(1.0, 0.72, 0.45), smoothstep(1600.0, 2900.0, T));
}

// ---- smoke puffs ----
float smokeShape(int i, vec3 p, out vec3 q) {
  vec4 s = u_smokeShape[i];
  q = p - u_smokeOrigin[i];
  q.y -= s.w;
  vec3 d = u_smokeDir[i];
  float along = dot(q, d);
  float rr2 = max(dot(q, q) - along * along, 0.0);
  float c = s.x, R = s.y;
  float ball = exp(-((along - c) * (along - c) + rr2) / (R * R));
  float k = clamp(along / max(c, 1e-3), 0.0, 1.0);
  float tr = R * mix(0.3, 0.8, k);
  float trail = u_smokeMisc[i].w * exp(-rr2 / (tr * tr)) * step(0.0, along) * step(along, c);
  return max(ball, trail);
}

float smokeDensity(int i, vec3 p, bool detail) {
  vec3 q;
  float shape = smokeShape(i, p, q);
  if (shape < 0.03) return 0.0;
  vec4 s = u_smokeShape[i], m = u_smokeMisc[i];
  if (!detail) return shape * s.z;
  float n = fbm(q / (s.y * 0.42) + vec3(m.z, m.z * 1.7, m.z * 0.3) + vec3(0.0, -m.x * 0.5, m.x * 0.2));
  return clamp(shape * 1.5 - 0.5 + (n - 0.5) * 1.3, 0.0, 1.0) * s.z;
}

// ---- the plume field ----
// Fractional cell coordinate of v (mm) along one axis of the stretched grid.
float cellAt(int row, float v, float lo, float hi) {
  float f = clamp((v - lo) / (hi - lo), 0.0, 1.0) * float(LUT - 1);
  int i = int(f);
  float a = texelFetch(u_lut, ivec2(i, row), 0).r, b = texelFetch(u_lut, ivec2(min(i + 1, LUT - 1), row), 0).r;
  return mix(a, b, f - float(i));
}

// Propellant gas density (kg/m^3) and temperature (K) of field i at world point p.
vec2 fieldAt(int i, vec3 p) {
  vec3 q = (u_fieldInv[i] * vec4(p, 1.0)).xyz;
  vec4 A = u_fieldA[i];
  float o = u_fieldB[i].x;
  float x = o + (q.x - o) / A.y, r = length(q.yz) / A.y;
  if (x <= u_fieldGrid.x || x >= u_fieldGrid.y || r >= u_fieldGrid.z) return vec2(0.0, T_AIR);
  vec2 uv = vec2(cellAt(0, x, u_fieldGrid.x, u_fieldGrid.y), cellAt(1, r, 0.0, u_fieldGrid.z)) / u_fieldCells;
  vec2 c = texture(u_field, vec3(uv, A.x)).rg;
  float rho = c.g > 0.002 ? pow(10.0, 7.0 * c.g - 5.0) * A.z : 0.0;
  return vec2(rho, T_AIR + (250.0 + 3000.0 * c.r - T_AIR) * A.w);
}

// Smoke extinction (1/mm) and glow of the plume at p.
void plumeAt(vec3 p, out float sigma, out vec3 emit, out float shadow) {
  sigma = 0.0; emit = vec3(0.0); shadow = 0.0;
  for (int i = 0; i < MAX_FIELD; i++) {
    if (i >= u_fieldCount) break;
    vec2 f = fieldAt(i, p);
    if (f.x <= 0.0) continue;
    float scale = u_fieldA[i].y;
    // Turbulence the 2D solution can't hold: breaks up the axisymmetry.
    float n = fbm(p / (14.0 * scale) + vec3(u_fieldB[i].y, -u_time * 3.0 / scale, u_time * 1.5 / scale));
    float k = 0.25 + 1.5 * n;
    // Hot gas is clear and bright; the smoke shows as it cools. Water and the products condense
    // only once the gas has mixed with air, so the dense, fresh gas of the jet carries little yet.
    sigma += SMOKE * f.x / (1.0 + f.x / 0.15) * k * mix(0.15, 1.0, smoothstep(1400.0, 600.0, f.y));
    emit += GLOW * f.x * wien(f.y) * k * blackbody(f.y);
    // Self-shadowing: the smoke above this point, towards the sky.
    vec2 above = fieldAt(i, p + vec3(0.0, 25.0 * scale, 0.0));
    shadow += SMOKE * above.x * 50.0 * scale;
  }
}

// ---- hot gas in the bore ----
// The part of the ray inside the cylinder r < R about the x axis with xa < x < xb,
// before tMax and behind the section cut: (t in, t out), equal if it misses.
vec4 gClip;                               // the section plane in the rifle's frame

vec2 chord(vec3 ro, vec3 rd, float R, float xa, float xb, float tMax) {
  if (xb <= xa) return vec2(0.0);
  float t0 = 0.0, t1 = tMax;
  float a = dot(rd.yz, rd.yz), b = dot(ro.yz, rd.yz), c = dot(ro.yz, ro.yz) - R * R;
  if (a < 1e-8) {
    if (c > 0.0) return vec2(0.0);
  } else {
    float disc = b * b - a * c;
    if (disc <= 0.0) return vec2(0.0);
    float sq = sqrt(disc);
    t0 = max(t0, (-b - sq) / a);
    t1 = min(t1, (-b + sq) / a);
  }
  if (abs(rd.x) < 1e-8) {
    if (ro.x < xa || ro.x > xb) return vec2(0.0);
  } else {
    float ta = (xa - ro.x) / rd.x, tb = (xb - ro.x) / rd.x;
    t0 = max(t0, min(ta, tb));
    t1 = min(t1, max(ta, tb));
  }
  float nd = dot(gClip.xyz, rd);
  if (abs(nd) > 1e-8) {
    float tc = -(dot(gClip.xyz, ro) + gClip.w) / nd;
    if (nd > 0.0) t1 = min(t1, tc); else t0 = max(t0, tc);
  }
  return t1 > t0 ? vec2(t0, t1) : vec2(0.0);
}

float boreTemperature(float x) {
  float f = clamp((x - u_gas.x) / max(u_gas.y - u_gas.x, 1e-3), 0.0, 1.0) * float(BORE_POINTS) - 0.5;
  int i = clamp(int(floor(f)), 0, BORE_POINTS - 1), j = min(i + 1, BORE_POINTS - 1);
  return mix(u_boreT[i], u_boreT[j], clamp(f - float(i), 0.0, 1.0));
}

// Glow along the ray's chord c through the gas.
vec3 boreChord(vec3 ro, vec3 rd, vec2 c) {
  if (c.y <= c.x) return vec3(0.0);
  vec3 sum = vec3(0.0);
  const int N = 6;
  for (int k = 0; k < N; k++) {
    vec3 pm = ro + rd * mix(c.x, c.y, (float(k) + 0.5) / float(N));
    float T = boreTemperature(pm.x);
    float n = noise(vec3(pm.x * 0.12 - u_time * 6.0, pm.y * 0.3, pm.z * 0.3));
    sum += blackbody(T) * wien(T) * (0.65 + 0.7 * n);
  }
  return sum * BORE_GLOW * (c.y - c.x) / float(N);
}

vec3 gasGlow(vec3 roW, vec3 rdW, float tScene) {
  if (u_gas.z <= 0.0) return vec3(0.0);
  // Rigid transform, so distances along the ray are the same in both frames.
  mat3 Ri = mat3(u_gunInv);
  vec3 ro = Ri * roW + u_gunInv[3].xyz, rd = Ri * rdW;
  vec3 cn = Ri * u_clipPlane.xyz;
  gClip = vec4(cn, u_clipPlane.w - dot(cn, u_gunInv[3].xyz));
  float neck = clamp(u_gasCase.y, u_gas.x, u_gas.y);
  return boreChord(ro, rd, chord(ro, rd, u_gasCase.x, u_gas.x, neck, tScene))
       + boreChord(ro, rd, chord(ro, rd, u_gas.w, neck, u_gas.y, tScene));
}

// Density, emission and lit colour of one sample.
void sampleAt(int group, vec3 p, out float sigma, out vec3 emit, out vec3 lit) {
  sigma = 0.0;
  emit = vec3(0.0);
  float shade = 0.0;
  if (group == 0) {
    float above;
    plumeAt(p, sigma, emit, above);
    shade = sigma * exp(-above);
  }
  for (int i = 0; i < MAX_SMOKE; i++) {
    if (i >= u_smokeCount || int(u_smokeMisc[i].y) != group) continue;
    float s = smokeDensity(i, p, true);
    if (s <= 0.0) continue;
    // Self-shadowing: optical depth towards an overhead light, from the smooth shape.
    float above = smokeDensity(i, p + vec3(0.0, u_smokeShape[i].y * 0.6, 0.0), false);
    shade += s * exp(-above * u_smokeShape[i].y * 0.9);
    sigma += s;
  }
  vec3 ambient = vec3(0.13, 0.135, 0.15), sun = vec3(0.55, 0.54, 0.52);
  float lightness = sigma > 0.0 ? shade / sigma : 0.0;
  float dl = length(p - u_lightPos) / max(u_lightRange, 1.0);
  lit = ambient + sun * lightness + u_lightColor / (1.0 + dl * dl);
}

vec4 march(int group, vec3 ro, vec3 rd, float tScene, float jitter) {
  vec4 b = u_bound[group];
  if (b.w <= 0.0) return vec4(0.0);
  vec3 oc = ro - b.xyz;
  float hb = dot(oc, rd), cc = dot(oc, oc) - b.w * b.w, disc = hb * hb - cc;
  if (disc <= 0.0) return vec4(0.0);
  float sq = sqrt(disc);
  float t0 = max(-hb - sq, 0.0), t1 = min(-hb + sq, tScene);
  if (t1 <= t0) return vec4(0.0);
  const int STEPS = 80;
  float dt = (t1 - t0) / float(STEPS);
  float T = 1.0;
  vec3 col = vec3(0.0);
  for (int k = 0; k < STEPS; k++) {
    vec3 p = ro + rd * (t0 + (float(k) + jitter) * dt);
    float sigma; vec3 emit, lit;
    sampleAt(group, p, sigma, emit, lit);
    float a = 1.0 - exp(-sigma * dt);
    col += T * (emit * dt + lit * a);
    T *= 1.0 - a;
    if (T < 0.01) break;
  }
  return vec4(col, 1.0 - T);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution;
  vec2 ndc = uv * 2.0 - 1.0;
  vec4 far = u_invViewProj * vec4(ndc, 1.0, 1.0);
  vec3 rd = normalize(far.xyz / far.w - u_eye);
  float depth = texture(u_depth, uv).r;
  float tScene = 1e9;
  if (depth < 1.0) {
    vec4 w = u_invViewProj * vec4(ndc, depth * 2.0 - 1.0, 1.0);
    tScene = length(w.xyz / w.w - u_eye);
  }
  float jitter = hash(vec3(gl_FragCoord.xy, 0.0));
  vec4 a = march(0, u_eye, rd, tScene, jitter);
  vec4 b = march(1, u_eye, rd, tScene, jitter);
  b.rgb += gasGlow(u_eye, rd, tScene) * (1.0 - b.a);
  // Composite the nearer group over the farther one.
  float da = dot(u_bound[0].xyz - u_eye, rd), db = dot(u_bound[1].xyz - u_eye, rd);
  vec4 front = da < db ? a : b, back = da < db ? b : a;
  vec3 col = front.rgb + (1.0 - front.a) * back.rgb;
  float alpha = 1.0 - (1.0 - front.a) * (1.0 - back.a);
  if (alpha <= 0.0 && dot(col, col) <= 0.0) discard;
  // Same tone curve as the meshes, then gamma. Colour stays premultiplied by alpha.
  col = col * (2.51 * col + 0.03) / (col * (2.43 * col + 0.59) + 0.14);
  outColor = vec4(pow(clamp(col, 0.0, 1.0), vec3(1.0 / 2.2)), alpha);
}`;

const UNIFORMS = ["u_invViewProj", "u_eye", "u_resolution", "u_depth", "u_bound", "u_clipPlane", "u_time",
  "u_field", "u_lut", "u_fieldGrid", "u_fieldCells", "u_fieldCount", "u_fieldInv", "u_fieldA", "u_fieldB",
  "u_smokeCount", "u_smokeOrigin", "u_smokeDir", "u_smokeShape", "u_smokeMisc",
  "u_gas", "u_gasCase", "u_boreT", "u_gunInv", "u_lightPos", "u_lightColor", "u_lightRange"];

/** Bounding sphere of a set of spheres [cx, cy, cz, r] (r = 0 entries ignored). */
function enclose(spheres) {
  const live = spheres.filter((s) => s[3] > 0);
  if (!live.length) return [0, 0, 0, 0];
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const s of live) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], s[k] - s[3]); hi[k] = Math.max(hi[k], s[k] + s[3]); }
  const c = lo.map((v, k) => (v + hi[k]) / 2);
  const r = Math.max(...live.map((s) => Math.hypot(s[0] - c[0], s[1] - c[1], s[2] - c[2]) + s[3]));
  return [...c, r];
}

/** Fractional cell coordinate at LUT evenly spaced points of [lo, hi], for face positions edges. */
function cellMap(edges, lo, hi) {
  const out = new Float32Array(LUT);
  let k = 0;
  for (let i = 0; i < LUT; i++) {
    const v = lo + (hi - lo) * i / (LUT - 1);
    while (k < edges.length - 2 && edges[k + 1] <= v) k++;
    out[i] = k + Math.min(1, Math.max(0, (v - edges[k]) / (edges[k + 1] - edges[k])));
  }
  return out;
}

export class VolumeEffects {
  constructor(gl) {
    this.gl = gl;
    this.program = link(gl, VS, FS);
    this.u = {};
    for (const name of UNIFORMS) this.u[name] = gl.getUniformLocation(this.program, name);
    this.vao = gl.createVertexArray();
    this.field = null;      // the plume whose frames are in the textures
    this.fieldTex = gl.createTexture();
    this.lutTex = gl.createTexture();
  }

  /** Load a plume (the plume API's result) into the textures, once. */
  _loadField(plume) {
    if (this.field === plume) return;
    const gl = this.gl;
    this.field = plume;
    plume.cells ??= Uint8Array.from(atob(plume.frames), (c) => c.charCodeAt(0));
    gl.bindTexture(gl.TEXTURE_3D, this.fieldTex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage3D(gl.TEXTURE_3D, 0, gl.RG8, plume.nx, plume.nr, plume.layers, 0, gl.RG, gl.UNSIGNED_BYTE, plume.cells);
    for (const p of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_3D, p, gl.LINEAR);
    for (const p of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(gl.TEXTURE_3D, p, gl.CLAMP_TO_EDGE);
    const xe = plume.x_edges, re = plume.r_edges;
    const lut = new Float32Array(2 * LUT);
    lut.set(cellMap(xe, xe[0], xe[xe.length - 1]), 0);
    lut.set(cellMap(re, 0, re[re.length - 1]), LUT);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, LUT, 2, 0, gl.RED, gl.FLOAT, lut);
    for (const p of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, p, gl.NEAREST);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
  }

  /**
   * Effects state (all optional):
   *   plume: the plume API's result, and fields: [{inverse, frame, scale, density, temperature, origin, seed, bound}]
   *     (inverse: world -> the field's frame; bound: [x, y, z, r] world sphere holding it)
   *   smoke: [{origin, dir, reach, radius, extinction, rise, age, group, seed, trail}]
   *   gas: {x0, x1, temps, boreR, caseR, neckX}      (in the rifle's frame; temps along x0..x1, K)
   *   gunModel: the rifle's model matrix (recoil and pitch)
   *   light: {position, color, range} of the flash, which lights the smoke; time: s since the latest exit
   * Returns true if there is anything to draw.
   */
  set(state) {
    this.state = state;
    const groups = [[], []];
    const fields = state.plume ? (state.fields || []).slice(0, MAX_FIELD) : [];
    for (const f of fields) groups[0].push(f.bound);
    for (const s of (state.smoke || []).slice(0, MAX_SMOKE)) {
      const c = s.origin.map((v, k) => v + s.dir[k] * s.reach / 2 + (k === 1 ? s.rise : 0));
      groups[s.group].push([...c, s.reach / 2 + s.radius * 2.2]);
    }
    this.fields = fields;
    this.bounds = groups.map(enclose);
    return this.bounds.some((b) => b[3] > 0) || !!state.gas;
  }

  /** Overlay callback for Renderer.render. */
  draw(gl, { depthTexture, viewProj }, eye, clipPlane) {
    const { u } = this, s = this.state;
    if (s.plume) this._loadField(s.plume);
    gl.useProgram(this.program);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, depthTexture);
    gl.uniform1i(u.u_depth, 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, this.fieldTex);
    gl.uniform1i(u.u_field, 1);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTex);
    gl.uniform1i(u.u_lut, 2);
    gl.activeTexture(gl.TEXTURE0);
    gl.uniformMatrix4fv(u.u_invViewProj, false, invert(viewProj));
    gl.uniform3fv(u.u_eye, eye);
    gl.uniform2f(u.u_resolution, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform4fv(u.u_bound, this.bounds.flat());
    gl.uniform4fv(u.u_clipPlane, clipPlane || [0, 0, 0, 0]);
    gl.uniform1f(u.u_time, s.time || 0);

    const fields = this.fields, P = s.plume;
    gl.uniform1i(u.u_fieldCount, fields.length);
    if (P) {
      gl.uniform4f(u.u_fieldGrid, P.x_edges[0], P.x_edges[P.x_edges.length - 1], P.r_edges[P.r_edges.length - 1], 0);
      gl.uniform2f(u.u_fieldCells, P.nx, P.nr);
    }
    const padF = (arr, n) => arr.concat(new Array(MAX_FIELD * n - arr.length).fill(0));
    gl.uniformMatrix4fv(u.u_fieldInv, false, padF(fields.flatMap((f) => Array.from(f.inverse)), 16));
    gl.uniform4fv(u.u_fieldA, padF(fields.flatMap((f) => [f.frame, f.scale, f.density, f.temperature]), 4));
    gl.uniform4fv(u.u_fieldB, padF(fields.flatMap((f) => [f.origin, f.seed, 0, 0]), 4));

    const smoke = (s.smoke || []).slice(0, MAX_SMOKE);
    const pad = (arr, n) => arr.concat(new Array(MAX_SMOKE * n - arr.length).fill(0));
    gl.uniform1i(u.u_smokeCount, smoke.length);
    gl.uniform3fv(u.u_smokeOrigin, pad(smoke.flatMap((p) => p.origin), 3));
    gl.uniform3fv(u.u_smokeDir, pad(smoke.flatMap((p) => p.dir), 3));
    gl.uniform4fv(u.u_smokeShape, pad(smoke.flatMap((p) => [p.reach, p.radius, p.extinction, p.rise]), 4));
    gl.uniform4fv(u.u_smokeMisc, pad(smoke.flatMap((p) => [p.age, p.group, p.seed, p.trail]), 4));

    const g = s.gas;
    gl.uniform4f(u.u_gas, g ? g.x0 : 0, g ? g.x1 : 0, g ? 1 : 0, g ? g.boreR : 1);
    gl.uniform2f(u.u_gasCase, g ? g.caseR : 1, g ? g.neckX : 0);
    gl.uniform1fv(u.u_boreT, g ? g.temps : new Float32Array(BORE_POINTS).fill(300));
    gl.uniformMatrix4fv(u.u_gunInv, false, s.gunModel ? invert(s.gunModel) : identity());

    const light = s.light || { position: [0, 0, 0], color: [0, 0, 0], range: 1 };
    gl.uniform3fv(u.u_lightPos, light.position);
    gl.uniform3fv(u.u_lightColor, light.color);
    gl.uniform1f(u.u_lightRange, light.range);

    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    gl.disable(gl.BLEND);
    gl.enable(gl.DEPTH_TEST);
  }
}
