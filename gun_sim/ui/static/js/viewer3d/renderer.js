// WebGL2 renderer: one physically based shader (GGX specular, Lambert diffuse,
// a procedural studio environment), meshes, an optional section cut, an
// optional point light (muzzle flash), and an overlay hook for volume effects.
//
// Section cut: fragments on the far side of a plane are discarded. Meshes are
// closed solids wound counter-clockwise from outside, so any back face that
// shows through the cut is the inside of solid material and is drawn flat in
// the section colour, which reads as a cut face.

import { multiply } from "./mat4.js";

// Volume effects need the scene's depth, so when an overlay is drawn the meshes
// are first rendered once more into a depth texture (the main framebuffer is
// multisampled, and its depth can't be read back).

const VERTEX_SHADER = `#version 300 es
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
uniform mat4 u_model;
uniform mat4 u_viewProj;
out vec3 v_world;
out vec3 v_normal;
void main() {
  vec4 world = u_model * vec4(a_position, 1.0);
  v_world = world.xyz;
  v_normal = mat3(u_model) * a_normal;  // models are rigid (no scaling)
  gl_Position = u_viewProj * world;
}`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec3 v_world;
in vec3 v_normal;
uniform vec3 u_eye;
uniform vec3 u_color;      // linear base colour
uniform float u_metallic;
uniform float u_roughness;
uniform vec4 u_clipPlane;  // discard where dot(xyz, p) + w > 0; all zero disables it
uniform vec3 u_sectionColor;
uniform vec3 u_pointPos;   // point light (muzzle flash): radiance u_pointColor, halved at u_pointRange
uniform vec3 u_pointColor;
uniform float u_pointRange;
uniform vec3 u_emissive;   // light the surface gives off itself (a tracer's flame), linear
out vec4 outColor;

const float PI = 3.14159265;

// Soft studio lighting: dark floor, bright overhead and a horizontal light strip,
// which gives metals something to reflect.
vec3 environment(vec3 d, float blur) {
  float y = d.y;
  vec3 col = mix(vec3(0.05, 0.05, 0.06), vec3(0.55, 0.58, 0.64), smoothstep(-0.3, 0.8, y));
  float sharp = mix(14.0, 2.5, blur);
  col += vec3(1.6) * exp(-sharp * abs(y - 0.35)) * mix(1.0, 0.45, blur);
  col += vec3(0.9, 0.85, 0.8) * pow(max(dot(d, normalize(vec3(-0.5, 0.6, 0.6))), 0.0), mix(60.0, 4.0, blur));
  return col;
}

float distributionGGX(float NdH, float a) {
  float a2 = a * a;
  float d = NdH * NdH * (a2 - 1.0) + 1.0;
  return a2 / (PI * d * d);
}

float geometrySmith(float NdV, float NdL, float rough) {
  float k = (rough + 1.0) * (rough + 1.0) / 8.0;
  return NdV / (NdV * (1.0 - k) + k) * NdL / (NdL * (1.0 - k) + k);
}

void main() {
  if (dot(u_clipPlane.xyz, v_world) + u_clipPlane.w > 0.0) discard;

  if (!gl_FrontFacing) {
    // Inside of a solid seen through the cut: flat section colour.
    outColor = vec4(pow(u_sectionColor, vec3(1.0 / 2.2)), 1.0);
    return;
  }

  vec3 N = normalize(v_normal);
  vec3 V = normalize(u_eye - v_world);
  float NdV = max(dot(N, V), 1e-4);
  vec3 F0 = mix(vec3(0.04), u_color, u_metallic);
  vec3 diffuse = u_color * (1.0 - u_metallic);
  float a = u_roughness * u_roughness;

  vec3 color = vec3(0.0);
  vec3 lightDirs[2] = vec3[2](normalize(vec3(0.4, 0.8, 0.6)), normalize(vec3(-0.7, 0.3, -0.5)));
  vec3 lightCols[2] = vec3[2](vec3(2.6, 2.5, 2.4), vec3(0.7, 0.75, 0.9));
  for (int i = 0; i < 2; i++) {
    vec3 L = lightDirs[i];
    float NdL = max(dot(N, L), 0.0);
    if (NdL <= 0.0) continue;
    vec3 H = normalize(L + V);
    float NdH = max(dot(N, H), 0.0);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - max(dot(V, H), 0.0), 5.0);
    vec3 spec = distributionGGX(NdH, a) * geometrySmith(NdV, NdL, u_roughness) * F / (4.0 * NdV * NdL + 1e-4);
    color += ((1.0 - F) * diffuse / PI + spec) * lightCols[i] * NdL;
  }
  if (u_pointRange > 0.0) {
    vec3 toLight = u_pointPos - v_world;
    float dist = length(toLight);
    vec3 L = toLight / dist;
    float NdL = max(dot(N, L), 0.0);
    if (NdL > 0.0) {
      vec3 H = normalize(L + V);
      float NdH = max(dot(N, H), 0.0);
      vec3 F = F0 + (1.0 - F0) * pow(1.0 - max(dot(V, H), 0.0), 5.0);
      vec3 spec = distributionGGX(NdH, a) * geometrySmith(NdV, NdL, u_roughness) * F / (4.0 * NdV * NdL + 1e-4);
      float atten = 1.0 / (1.0 + dist * dist / (u_pointRange * u_pointRange));
      color += ((1.0 - F) * diffuse / PI + spec) * u_pointColor * atten * NdL;
    }
  }

  // Image-based part from the procedural environment.
  vec3 Fr = F0 + (max(vec3(1.0 - u_roughness), F0) - F0) * pow(1.0 - NdV, 5.0);
  color += diffuse * environment(N, 1.0) * 0.6;
  color += Fr * environment(reflect(-V, N), u_roughness);
  color += u_emissive;

  color = color * (2.51 * color + 0.03) / (color * (2.43 * color + 0.59) + 0.14);  // ACES fit
  outColor = vec4(pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.2)), 1.0);
}`;

// Full-screen backdrop for opaque views: a dim vertical gradient with a soft glow.
const BACKGROUND_VS = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
out vec2 v_uv;
void main() {
  v_uv = P[gl_VertexID] * 0.5 + 0.5;
  gl_Position = vec4(P[gl_VertexID], 0.0, 1.0);
}`;

const BACKGROUND_FS = `#version 300 es
precision mediump float;
in vec2 v_uv;
out vec4 outColor;
void main() {
  vec3 lo = vec3(0.035, 0.037, 0.043), hi = vec3(0.16, 0.17, 0.19);
  float g = smoothstep(0.0, 1.0, v_uv.y);
  vec2 d = v_uv - vec2(0.5, 0.55);
  float glow = exp(-6.0 * dot(d, d));
  vec3 c = mix(lo, hi, g * 0.7 + glow * 0.4);
  // A little dither against banding.
  c += (fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) / 255.0;
  outColor = vec4(c, 1.0);
}`;

export function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error("shader compile failed: " + gl.getShaderInfoLog(shader));
  }
  return shader;
}

export function link(gl, vs, fs) {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error("shader link failed: " + gl.getProgramInfoLog(program));
  }
  return program;
}

export const srgbToLinear = (rgb) => rgb.map((c) => Math.pow(c, 2.2));

const NO_GLOW = [0, 0, 0];

// Core under a projectile's jacket (or a solid projectile's metal), indexed like the config's core_material.
export const CORE_MATERIALS = [
  { color: srgbToLinear([0.62, 0.63, 0.67]), metallic: 0.9, roughness: 0.5, section: srgbToLinear([0.5, 0.51, 0.55]) },     // lead
  { color: srgbToLinear([0.33, 0.35, 0.4]), metallic: 1, roughness: 0.34, section: srgbToLinear([0.22, 0.24, 0.28]) },      // steel
  { color: srgbToLinear([0.9, 0.52, 0.38]), metallic: 1, roughness: 0.3, section: srgbToLinear([0.7, 0.36, 0.24]) },        // copper
  { color: srgbToLinear([0.42, 0.43, 0.45]), metallic: 1, roughness: 0.42, section: srgbToLinear([0.55, 0.56, 0.58]) },     // tungsten
  { color: srgbToLinear([0.2, 0.21, 0.25]), metallic: 1, roughness: 0.28, section: srgbToLinear([0.36, 0.37, 0.42]) },      // hardened steel
  { color: srgbToLinear([0.3, 0.3, 0.32]), metallic: 0.8, roughness: 0.55, section: srgbToLinear([0.44, 0.5, 0.49]) },      // tungsten carbide
  { color: srgbToLinear([0.55, 0.55, 0.58]), metallic: 1, roughness: 0.38, section: srgbToLinear([0.62, 0.62, 0.66]) },     // titanium
  { color: srgbToLinear([0.26, 0.27, 0.25]), metallic: 0.9, roughness: 0.5, section: srgbToLinear([0.34, 0.36, 0.3]) },     // depleted uranium
  { color: srgbToLinear([0.78, 0.79, 0.81]), metallic: 1, roughness: 0.3, section: srgbToLinear([0.7, 0.71, 0.74]) },       // aluminium
  { color: srgbToLinear([0.86, 0.66, 0.34]), metallic: 1, roughness: 0.3, section: srgbToLinear([0.62, 0.45, 0.2]) },       // brass
  { color: srgbToLinear([0.72, 0.5, 0.4]), metallic: 0.5, roughness: 0.8, section: srgbToLinear([0.6, 0.42, 0.34]) },       // sintered copper
];
const CORE_INDEX = ["lead", "steel", "copper", "tungsten", "hardened_steel", "tungsten_carbide", "titanium", "depleted_uranium",
  "aluminium", "brass", "sintered_copper"];

const flat = (rgb, metallic = 0, roughness = 0.7) =>
  ({ color: srgbToLinear(rgb), metallic, roughness, section: srgbToLinear(rgb.map((c) => c * 0.85)) });

// Fills, in the colours of the usual cutaway drawings: explosives purple to buff, incendiaries red.
const FILL_MATERIALS = {
  tnt: flat([0.82, 0.7, 0.38]), comp_b: flat([0.66, 0.55, 0.66]), comp_a4: flat([0.55, 0.52, 0.72]),
  petn: flat([0.52, 0.5, 0.74]), octol: flat([0.6, 0.45, 0.7]), lx14: flat([0.5, 0.55, 0.75]), pe4: flat([0.9, 0.88, 0.8]),
  a_ix_1: flat([0.75, 0.72, 0.65]), a_ix_2: flat([0.58, 0.58, 0.64], 0.3, 0.6), tetryl: flat([0.85, 0.8, 0.4]),
  amatol: flat([0.8, 0.75, 0.6]), explosive_d: flat([0.9, 0.65, 0.3]),
  im11: flat([0.82, 0.33, 0.33]), zirconium: flat([0.8, 0.83, 0.81], 0.3, 0.8), magnesium: flat([0.75, 0.75, 0.78], 0.6, 0.5),
  thermite: flat([0.55, 0.28, 0.18]), white_phosphorus: flat([0.92, 0.9, 0.7], 0, 0.4), flash: flat([0.85, 0.85, 0.85]),
  polymer: flat([0.85, 0.12, 0.1], 0, 0.35), inert: flat([0.6, 0.58, 0.55]),
  fuze: { color: srgbToLinear([0.74, 0.75, 0.78]), metallic: 1, roughness: 0.42, section: srgbToLinear([0.62, 0.63, 0.66]) },
  cap: { color: srgbToLinear([0.38, 0.39, 0.43]), metallic: 1, roughness: 0.45, section: srgbToLinear([0.48, 0.49, 0.53]) },
  windshield: { color: srgbToLinear([0.32, 0.36, 0.22]), metallic: 0.3, roughness: 0.6, section: srgbToLinear([0.55, 0.56, 0.58]) },
};
const TRACER_COMPOSITION = { red: [0.6, 0.36, 0.32], green: [0.42, 0.55, 0.36], white: [0.68, 0.66, 0.6],
  orange: [0.66, 0.48, 0.3], dim: [0.42, 0.36, 0.34] };
export const TRACER_GLOW = { red: [1.0, 0.24, 0.12], green: [0.4, 1.0, 0.32], white: [1.0, 0.95, 0.85],
  orange: [1.0, 0.55, 0.15], dim: [0.7, 0.18, 0.1] };
const TRACER_BRIGHTNESS = { dim: 0.12, white: 1.3 };
const LINER_MATERIALS = { copper: CORE_MATERIALS[2], aluminium: CORE_MATERIALS[8], steel: CORE_MATERIALS[1],
  molybdenum: { color: srgbToLinear([0.6, 0.6, 0.63]), metallic: 1, roughness: 0.3, section: srgbToLinear([0.66, 0.66, 0.7]) },
  tantalum: { color: srgbToLinear([0.5, 0.52, 0.6]), metallic: 1, roughness: 0.32, section: srgbToLinear([0.56, 0.58, 0.66]) } };

/** What a projectile's part (cartridge.js fills: a metal, a fill, tracer:<colour>, liner:<metal>, ...) is drawn in. */
export function partMaterial(name) {
  const k = CORE_INDEX.indexOf(name);
  if (k >= 0) return CORE_MATERIALS[k];
  if (name.startsWith("tracer:")) return flat(TRACER_COMPOSITION[name.slice(7)] ?? TRACER_COMPOSITION.red, 0, 0.9);
  if (name.startsWith("liner:")) return LINER_MATERIALS[name.slice(6)] ?? LINER_MATERIALS.copper;
  return FILL_MATERIALS[name] ?? FILL_MATERIALS.inert;
}

/** A tracer's flame: it lights itself (emissive), in its composition's colour. */
export function tracerGlow(colour) {
  const rgb = srgbToLinear(TRACER_GLOW[colour] ?? TRACER_GLOW.red), k = 6 * (TRACER_BRIGHTNESS[colour] ?? 1);
  return { color: [0, 0, 0], metallic: 0, roughness: 1, section: rgb, emissive: rgb.map((c) => c * k) };
}

// Jackets (and a shell's painted body) by projectiles.JACKETS name; gilding metal is the viewer's own projectile colour.
const JACKET_MATERIALS = {
  copper: CORE_MATERIALS[2],
  clad_steel: { color: srgbToLinear([0.74, 0.5, 0.36]), metallic: 1, roughness: 0.38, section: srgbToLinear([0.42, 0.42, 0.45]) },
  steel: { color: srgbToLinear([0.33, 0.36, 0.22]), metallic: 0.25, roughness: 0.6, section: srgbToLinear([0.45, 0.46, 0.5]) },
  brass: CORE_MATERIALS[9],
  aluminium: CORE_MATERIALS[8],
  polymer: flat([0.3, 0.22, 0.5], 0, 0.4),
};

/** The jacket's material, or `fallback` (the gilding-metal colour) for gilding metal. */
export function jacketMaterial(name, fallback) {
  return JACKET_MATERIALS[name] ?? fallback;
}

/** The projectile's outside: its jacket (gilding metal = `fallback`), or a solid projectile's own metal. */
export function projectileMaterial(round, fallback) {
  if (round.jacketMaterial) return jacketMaterial(round.jacketMaterial, fallback);
  return round.solidMetal !== null && round.solidMetal !== undefined ? CORE_MATERIALS[round.solidMetal] : fallback;
}

/** A sabot's material by name: aluminium (the default look), steel or polymer. */
export function sabotMaterial(name, fallback) {
  return name === "polymer" ? flat([0.13, 0.13, 0.14], 0, 0.5) : name === "steel" ? CORE_MATERIALS[1] : fallback;
}

/** Materials of a round's parts that aren't brass, copper or a core (cartridge.js roundParts names them). */
export const ROUND_MATERIALS = {
  steelCase: { color: srgbToLinear([0.32, 0.33, 0.3]), metallic: 0.8, roughness: 0.5, section: srgbToLinear([0.45, 0.46, 0.44]) },
  felt: { color: srgbToLinear([0.62, 0.52, 0.36]), metallic: 0, roughness: 0.85, section: srgbToLinear([0.5, 0.4, 0.26]) },
  sabot: { color: srgbToLinear([0.72, 0.73, 0.75]), metallic: 1, roughness: 0.35, section: srgbToLinear([0.6, 0.61, 0.63]) },
  fins: { color: srgbToLinear([0.3, 0.31, 0.33]), metallic: 1, roughness: 0.4, section: srgbToLinear([0.4, 0.4, 0.42]) },
};

export class Renderer {
  /** opaque: draw a backdrop instead of leaving the canvas transparent. */
  constructor(canvas, { opaque = false } = {}) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: !opaque, premultipliedAlpha: true });
    if (!gl) throw new Error("WebGL 2 is not available");
    this.gl = gl;
    this.canvas = canvas;
    this.opaque = opaque;

    this.program = link(gl, VERTEX_SHADER, FRAGMENT_SHADER);
    this.uniforms = {};
    for (const name of ["u_model", "u_viewProj", "u_eye", "u_color", "u_metallic", "u_roughness",
                        "u_clipPlane", "u_sectionColor", "u_pointPos", "u_pointColor", "u_pointRange", "u_emissive"]) {
      this.uniforms[name] = gl.getUniformLocation(this.program, name);
    }
    if (opaque) {
      this.backgroundProgram = link(gl, BACKGROUND_VS, BACKGROUND_FS);
      this.emptyVao = gl.createVertexArray();
    }
    this.depthTarget = null;  // {fbo, depth, color, w, h}, made on first use
    gl.enable(gl.DEPTH_TEST);
  }

  /** A depth texture of the current canvas size, for overlays to read. */
  _depthTarget() {
    const gl = this.gl, w = this.canvas.width, h = this.canvas.height;
    const t = this.depthTarget;
    if (t && t.w === w && t.h === h) return t;
    if (t) {
      gl.deleteFramebuffer(t.fbo);
      gl.deleteTexture(t.depth);
      gl.deleteRenderbuffer(t.color);
    }
    const depth = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, depth);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.DEPTH_COMPONENT24, w, h, 0, gl.DEPTH_COMPONENT, gl.UNSIGNED_INT, null);
    for (const p of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, p, gl.NEAREST);
    for (const p of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T]) gl.texParameteri(gl.TEXTURE_2D, p, gl.CLAMP_TO_EDGE);
    const color = gl.createRenderbuffer();
    gl.bindRenderbuffer(gl.RENDERBUFFER, color);
    gl.renderbufferStorage(gl.RENDERBUFFER, gl.RGBA8, w, h);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.RENDERBUFFER, color);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, depth, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.depthTarget = { fbo, depth, color, w, h };
    return this.depthTarget;
  }

  /** Upload {positions, normals, indices} and return a mesh handle. */
  createMesh({ positions, normals, indices }) {
    const gl = this.gl;
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const buffers = [];
    for (const [location, data] of [[0, positions], [1, normals]]) {
      const buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 0, 0);
      buffers.push(buf);
    }
    const ibo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
    buffers.push(ibo);
    gl.bindVertexArray(null);
    return { vao, buffers, count: indices.length };
  }

  deleteMesh(mesh) {
    this.gl.deleteVertexArray(mesh.vao);
    for (const b of mesh.buffers) this.gl.deleteBuffer(b);
  }

  /** Match the drawing buffer to the canvas's CSS size. Returns the aspect ratio. */
  resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    return w / h;
  }

  _drawItems(items, clipPlane) {
    const gl = this.gl, u = this.uniforms;
    const noClip = [0, 0, 0, 0];
    for (const { mesh, model, material, clip = true } of items) {
      gl.uniform4fv(u.u_clipPlane, (clip && clipPlane) || noClip);
      gl.uniformMatrix4fv(u.u_model, false, model);
      gl.uniform3fv(u.u_color, material.color);
      gl.uniform1f(u.u_metallic, material.metallic);
      gl.uniform1f(u.u_roughness, material.roughness);
      gl.uniform3fv(u.u_sectionColor, material.section);
      gl.uniform3fv(u.u_emissive, material.emissive ?? NO_GLOW);
      gl.bindVertexArray(mesh.vao);
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_INT, 0);
    }
    gl.bindVertexArray(null);
  }

  /**
   * Draw a frame.
   * camera: {view, proj, eye}
   * items: [{mesh, model, material: {color, metallic, roughness, section}, clip?}]; clip: false
   *   keeps an item whole when the section cut is on.
   * clipPlane: [nx, ny, nz, d] or null.
   * pointLight: {position, color, range} or null.
   * overlay: optional function(gl, {depthTexture, viewProj}) called last, for volume effects.
   */
  render({ camera, items, clipPlane = null, pointLight = null, overlay = null }) {
    const gl = this.gl, u = this.uniforms;
    const viewProj = multiply(camera.proj, camera.view);
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(u.u_viewProj, false, viewProj);
    gl.uniform3fv(u.u_eye, camera.eye);
    gl.uniform3fv(u.u_pointPos, pointLight ? pointLight.position : [0, 0, 0]);
    gl.uniform3fv(u.u_pointColor, pointLight ? pointLight.color : [0, 0, 0]);
    gl.uniform1f(u.u_pointRange, pointLight ? pointLight.range : 0);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);

    let depthTexture = null;
    if (overlay) {
      const target = this._depthTarget();
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.colorMask(false, false, false, false);
      gl.clear(gl.DEPTH_BUFFER_BIT);
      this._drawItems(items, clipPlane);
      gl.colorMask(true, true, true, true);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      depthTexture = target.depth;
    }

    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (this.opaque) {
      gl.disable(gl.DEPTH_TEST);
      gl.useProgram(this.backgroundProgram);
      gl.bindVertexArray(this.emptyVao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
      gl.enable(gl.DEPTH_TEST);
      gl.useProgram(this.program);
    }
    this._drawItems(items, clipPlane);
    if (overlay) overlay(gl, { depthTexture, viewProj });
  }
}
