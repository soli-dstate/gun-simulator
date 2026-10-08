// Volumetric effects, ray-marched in one full-screen pass over the scene:
//
// - Muzzle flash (emission only): the under-expanded jet's shock "bottle", the
//   Mach disk at its end, and the turbulent intermediate/secondary flash
//   downstream, where fuel-rich gas mixes with air and re-ignites.
// - Smoke (absorbing and scattering): puffs that are thrown out of an opening,
//   slow down, grow, rise and thin out. Shaped by 3D noise.
// - Hot propellant gas glowing in the bore behind the projectile. It's a thin
//   cylinder, so instead of marching it the ray's chord through it is found
//   exactly.
//
// The marched effects are split into two groups (around the muzzle, and
// around the breech), each with a bounding sphere, so every ray only marches
// the stretch that can hold something. The scene's depth stops rays at solid
// surfaces.
// World units are millimetres.

import { identity, invert } from "./mat4.js";
import { link } from "./renderer.js";

export const MAX_SMOKE = 4;

const VS = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }`;

const FS = `#version 300 es
precision highp float;
#define MAX_SMOKE ${MAX_SMOKE}
uniform mat4 u_invViewProj;
uniform vec3 u_eye;
uniform vec2 u_resolution;
uniform sampler2D u_depth;
uniform vec4 u_bound[2];                 // per group: bounding sphere (xyz centre, w radius; 0 = empty)
uniform vec4 u_clipPlane;                // the section cut (applied to the bore gas only)

uniform vec3 u_muzzle;
uniform vec4 u_flash;                    // primary intensity, secondary intensity, Mach-disk distance, bore radius
uniform float u_flashAge;                // ms since muzzle exit, animates the turbulence

uniform int u_smokeCount;
uniform vec3 u_smokeOrigin[MAX_SMOKE];
uniform vec3 u_smokeDir[MAX_SMOKE];
uniform vec4 u_smokeShape[MAX_SMOKE];    // reach along dir, radius, extinction (1/mm), rise (mm)
uniform vec4 u_smokeMisc[MAX_SMOKE];     // age (s), group, seed, trail strength

uniform vec4 u_gas;                      // start x, end x, emission (1/mm), bore radius
uniform vec2 u_gasCase;                  // case cavity radius, x where the case necks down
uniform vec4 u_dev;                      // gas filling a muzzle device: start x, end x, radius, emission (1/mm)
uniform mat4 u_gunInv;                   // world -> the rifle's frame (it recoils and pitches); the gas lives there

uniform vec3 u_flashLight;               // colour * intensity of the flash, lights the smoke
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

// ---- smoke ----
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

// ---- muzzle flash ----
vec3 flashEmission(vec3 p) {
  if (u_flash.x + u_flash.y <= 0.0) return vec3(0.0);
  vec3 q = mat3(u_gunInv) * (p - u_muzzle);   // in the muzzle's frame, axis along the pitched barrel
  float u = q.x, rr = length(q.yz);
  float xm = u_flash.z, rb = u_flash.w;
  vec3 e = vec3(0.0);
  if (u_flash.x > 0.0) {
    // Shock bottle: widens out of the muzzle, then closes towards the Mach disk.
    float s = clamp(u / xm, 0.0, 1.0);
    float w = rb + xm * 0.3 * sin(3.14159 * s * 0.8);
    float n = noise(q / (rb * 1.2) - vec3(u_flashAge * 40.0, 0.0, 0.0));
    float core = exp(-3.0 * (rr / w) * (rr / w)) * smoothstep(-rb, rb, u) * (1.0 - smoothstep(xm, xm * 1.15, u));
    // Hottest along the axis and right at the muzzle.
    core *= 0.35 + 0.65 * exp(-2.0 * s) + 0.6 * exp(-8.0 * (rr / w) * (rr / w));
    e += vec3(1.0, 0.72, 0.36) * core * (0.4 + n) * 1.1;
    float md = exp(-pow((u - xm) / (0.04 * xm + 0.3 * rb), 2.0)) * exp(-pow(rr / (0.2 * xm + rb), 2.0));
    e += vec3(1.0, 0.88, 0.62) * md * 2.2;
    e *= u_flash.x;
  }
  if (u_flash.y > 0.0) {
    // Intermediate and secondary flash: a turbulent fireball past the Mach disk.
    vec3 c2 = vec3(xm * (1.8 + u_flashAge * 0.4), 0.0, 0.0);
    float R2 = xm * (0.75 + u_flashAge * 0.15);
    float d2 = length((q - c2) * vec3(0.7, 1.0, 1.0)) / R2;
    if (d2 < 1.5) {
      float n2 = fbm(q / (R2 * 0.3) + vec3(-u_flashAge * 2.0, u_flashAge * 0.7, 0.0));
      float ball = smoothstep(0.0, 0.55, 1.0 - d2 + (n2 - 0.5) * 1.3);
      vec3 col = mix(vec3(0.9, 0.2, 0.03), vec3(1.0, 0.55, 0.16), ball);
      e += col * ball * ball * u_flash.y;
    }
  }
  return e / xm * 1.2;
}

// ---- hot gas in the bore ----
// Length of the ray inside the cylinder r < R about the x axis with xa < x < xb,
// before tMax and behind the section cut. Returns (length, t at its middle).
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
  return t1 > t0 ? vec2(t1 - t0, 0.5 * (t0 + t1)) : vec2(0.0);
}

vec3 gasGlow(vec3 roW, vec3 rdW, float tScene) {
  if (u_gas.z <= 0.0 && u_dev.w <= 0.0) return vec3(0.0);
  // Rigid transform, so distances along the ray are the same in both frames.
  mat3 Ri = mat3(u_gunInv);
  vec3 ro = Ri * roW + u_gunInv[3].xyz, rd = Ri * rdW;
  vec3 cn = Ri * u_clipPlane.xyz;
  gClip = vec4(cn, u_clipPlane.w - dot(cn, u_gunInv[3].xyz));
  vec3 res = vec3(0.0);
  if (u_gas.z > 0.0) {
    float neck = clamp(u_gasCase.y, u_gas.x, u_gas.y);
    vec2 inCase = chord(ro, rd, u_gasCase.x, u_gas.x, neck, tScene);
    vec2 inBore = chord(ro, rd, u_gas.w, neck, u_gas.y, tScene);
    float len = inCase.x + inBore.x;
    if (len > 0.0) {
      float tm = (inCase.x * inCase.y + inBore.x * inBore.y) / len;
      vec3 pm = ro + rd * tm;
      float f = clamp((pm.x - u_gas.x) / max(u_gas.y - u_gas.x, 1e-3), 0.0, 1.0);
      float n = noise(vec3(pm.x * 0.12 - u_flashAge * 6.0, pm.y * 0.3, pm.z * 0.3));
      vec3 col = mix(vec3(1.0, 0.8, 0.5), vec3(1.0, 0.42, 0.12), f);
      res += col * u_gas.z * len * (0.65 + 0.7 * n);
    }
  }
  if (u_dev.w > 0.0) {
    vec2 c = chord(ro, rd, u_dev.z, u_dev.x, u_dev.y, tScene);
    if (c.x > 0.0) {
      vec3 pm = ro + rd * c.y;
      float f = clamp((pm.x - u_dev.x) / max(u_dev.y - u_dev.x, 1e-3), 0.0, 1.0);
      float n = noise(vec3(pm.x * 0.08 - u_flashAge * 2.0, pm.y * 0.2, pm.z * 0.2));
      vec3 col = mix(vec3(1.0, 0.62, 0.28), vec3(1.0, 0.38, 0.1), f);   // hotter near the projectile
      res += col * u_dev.w * c.x * (0.7 + 0.6 * n);
    }
  }
  return res;
}

// Density, emission and lit colour of one sample.
void sampleAt(int group, vec3 p, out float sigma, out vec3 emit, out vec3 lit) {
  sigma = 0.0;
  emit = group == 0 ? flashEmission(p) : vec3(0.0);
  float shade = 0.0;
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
  float dm = length(p - u_muzzle) / max(u_flash.z, 1.0);
  lit = ambient + sun * lightness + u_flashLight / (1.0 + dm * dm);
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

const UNIFORMS = ["u_invViewProj", "u_eye", "u_resolution", "u_depth", "u_bound", "u_clipPlane", "u_muzzle",
  "u_flash", "u_flashAge", "u_smokeCount", "u_smokeOrigin", "u_smokeDir", "u_smokeShape", "u_smokeMisc",
  "u_gas", "u_gasCase", "u_dev", "u_gunInv", "u_flashLight"];

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

export class VolumeEffects {
  constructor(gl) {
    this.program = link(gl, VS, FS);
    this.u = {};
    for (const name of UNIFORMS) this.u[name] = gl.getUniformLocation(this.program, name);
    this.vao = gl.createVertexArray();
  }

  /**
   * Effects state (all optional):
   *   flash: {muzzle: [x,y,z], primary, secondary, machDisk, boreR, age}
   *   smoke: [{origin, dir, reach, radius, extinction, rise, age, group, seed, trail}]
   *   gas: {x0, x1, emission, boreR, caseR, neckX}   (in the rifle's frame)
   *   dev: {x0, x1, radius, emission}                (gas filling a muzzle device, rifle's frame)
   *   gunModel: the rifle's model matrix (recoil and pitch)
   * flash.dir: unit vector along the (pitched) barrel, default +x
   *   flashLight: [r, g, b]
   * Returns true if there is anything to draw.
   */
  set(state) {
    this.state = state;
    const f = state.flash, g = state.gas, dv = state.dev;
    const groups = [[], []];
    if (f && f.primary + f.secondary > 0) {
      const xm = f.machDisk;
      const d = f.dir || [1, 0, 0], reach = xm * (1.4 + f.age * 0.3);
      groups[0].push([f.muzzle[0] + d[0] * reach, f.muzzle[1] + d[1] * reach, f.muzzle[2] + d[2] * reach, xm * (2.0 + f.age * 0.3)]);
    }
    for (const s of (state.smoke || []).slice(0, MAX_SMOKE)) {
      const c = s.origin.map((v, k) => v + s.dir[k] * s.reach / 2 + (k === 1 ? s.rise : 0));
      groups[s.group].push([...c, s.reach / 2 + s.radius * 2.2]);
    }
    this.bounds = groups.map(enclose);
    return this.bounds.some((b) => b[3] > 0) || !!(g && g.emission > 0) || !!(dv && dv.emission > 0);
  }

  /** Overlay callback for Renderer.render. */
  draw(gl, { depthTexture, viewProj }, eye, clipPlane) {
    const { u } = this, s = this.state;
    gl.useProgram(this.program);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, depthTexture);
    gl.uniform1i(u.u_depth, 0);
    gl.uniformMatrix4fv(u.u_invViewProj, false, invert(viewProj));
    gl.uniform3fv(u.u_eye, eye);
    gl.uniform2f(u.u_resolution, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.uniform4fv(u.u_bound, this.bounds.flat());
    gl.uniform4fv(u.u_clipPlane, clipPlane || [0, 0, 0, 0]);

    const f = s.flash || { muzzle: [0, 0, 0], primary: 0, secondary: 0, machDisk: 1, boreR: 1, age: 0 };
    gl.uniform3fv(u.u_muzzle, f.muzzle);
    gl.uniform4f(u.u_flash, f.primary, f.secondary, f.machDisk, f.boreR);
    gl.uniform1f(u.u_flashAge, f.age);
    gl.uniform3fv(u.u_flashLight, s.flashLight || [0, 0, 0]);

    const smoke = (s.smoke || []).slice(0, MAX_SMOKE);
    const pad = (arr, n) => arr.concat(new Array(MAX_SMOKE * n - arr.length).fill(0));
    gl.uniform1i(u.u_smokeCount, smoke.length);
    gl.uniform3fv(u.u_smokeOrigin, pad(smoke.flatMap((p) => p.origin), 3));
    gl.uniform3fv(u.u_smokeDir, pad(smoke.flatMap((p) => p.dir), 3));
    gl.uniform4fv(u.u_smokeShape, pad(smoke.flatMap((p) => [p.reach, p.radius, p.extinction, p.rise]), 4));
    gl.uniform4fv(u.u_smokeMisc, pad(smoke.flatMap((p) => [p.age, p.group, p.seed, p.trail]), 4));

    const g = s.gas || { x0: 0, x1: 0, emission: 0, boreR: 1, caseR: 1, neckX: 0 };
    gl.uniform4f(u.u_gas, g.x0, g.x1, g.emission, g.boreR);
    gl.uniform2f(u.u_gasCase, g.caseR, g.neckX);

    const dv = s.dev || { x0: 0, x1: 0, radius: 1, emission: 0 };
    gl.uniform4f(u.u_dev, dv.x0, dv.x1, dv.radius, dv.emission);
    gl.uniformMatrix4fv(u.u_gunInv, false, s.gunModel ? invert(s.gunModel) : identity());

    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    gl.disable(gl.BLEND);
    gl.enable(gl.DEPTH_TEST);
  }
}
