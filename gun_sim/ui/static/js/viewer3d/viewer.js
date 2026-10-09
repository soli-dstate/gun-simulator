// Interactive 3D view of the cartridge: drag to orbit, wheel to zoom,
// double-click to reset. Redraws only when something changes.

import { buildCartridge, roundMeshes } from "./cartridge.js";
import { lookAt, perspective, translation } from "./mat4.js";
import { CORE_MATERIALS, ROUND_MATERIALS, Renderer, srgbToLinear } from "./renderer.js";

const MATERIALS = {
  case: { color: srgbToLinear([0.86, 0.66, 0.34]), metallic: 1, roughness: 0.32, section: srgbToLinear([0.62, 0.45, 0.2]) },
  primer: { color: srgbToLinear([0.78, 0.78, 0.76]), metallic: 1, roughness: 0.38, section: srgbToLinear([0.5, 0.5, 0.5]) },
  projectile: { color: srgbToLinear([0.80, 0.47, 0.30]), metallic: 1, roughness: 0.28, section: srgbToLinear([0.55, 0.3, 0.18]) },
};

const DEFAULT_VIEW = { yaw: -0.35, pitch: 0.25 };

export class CartridgeViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new Renderer(canvas);
    this.meshes = {};
    this.cartridge = null;
    this.cutaway = false;
    this.pulled = 0;        // 0 = seated, 1 = projectile drawn out of the case (animated)
    this.pullTarget = 0;
    this.yaw = DEFAULT_VIEW.yaw;
    this.pitch = DEFAULT_VIEW.pitch;
    this.zoom = 1;
    this.frame = 0;
    this._bindControls();
    new ResizeObserver(() => this.requestDraw()).observe(canvas);
  }

  /** Rebuild the cartridge from a gun config (SI units). Returns the cartridge stats and warnings. */
  setGun(gun) {
    const cart = buildCartridge(gun);
    for (const mesh of Object.values(this.meshes)) this.renderer.deleteMesh(mesh);
    this.meshes = {};
    for (const [name, data] of Object.entries(roundMeshes(cart))) this.meshes[name] = this.renderer.createMesh(data);
    this.cartridge = cart;
    this.requestDraw();
    return cart;
  }

  setCutaway(on) { this.cutaway = on; this.requestDraw(); }
  setPulled(on) { this.pullTarget = on ? 1 : 0; this.requestDraw(); }

  resetView() {
    Object.assign(this, DEFAULT_VIEW, { zoom: 1 });
    this.requestDraw();
  }

  requestDraw() {
    if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = 0; this._draw(); });
  }

  _bindControls() {
    const c = this.canvas;
    let drag = null;
    c.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.yaw -= (e.clientX - drag.x) * 0.008;
      this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch + (e.clientY - drag.y) * 0.008));
      drag = { x: e.clientX, y: e.clientY };
      this.requestDraw();
    });
    const end = () => { drag = null; };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.zoom = Math.max(0.15, Math.min(4, this.zoom * Math.exp(e.deltaY * 0.001)));
      this.requestDraw();
    }, { passive: false });
    c.addEventListener("dblclick", () => this.resetView());
  }

  _draw() {
    if (!this.cartridge) return;
    // Ease the projectile in or out.
    if (this.pulled !== this.pullTarget) {
      const step = 0.08;
      this.pulled += Math.sign(this.pullTarget - this.pulled) * Math.min(step, Math.abs(this.pullTarget - this.pulled));
      this.requestDraw();
    }
    const cart = this.cartridge;
    const ease = this.pulled * this.pulled * (3 - 2 * this.pulled);
    const pullDist = ease * (cart.length - cart.seat) * 0.9;
    const totalLen = cart.length + pullDist;

    const aspect = this.renderer.resize();
    const fov = 30 * Math.PI / 180;
    // Fit the length across the view and a few radii top to bottom; back off a little
    // when looking along the axis, where the near end grows in perspective.
    const halfLen = totalLen / 2, fovX = 2 * Math.atan(Math.tan(fov / 2) * aspect);
    const fit = Math.max(halfLen * 1.3 / Math.tan(fovX / 2), cart.radius * 3 / Math.tan(fov / 2));
    const dist = (fit + halfLen * Math.abs(Math.sin(this.yaw)) + cart.radius) * this.zoom;
    const eye = [
      dist * Math.cos(this.pitch) * Math.sin(this.yaw),
      dist * Math.sin(this.pitch),
      dist * Math.cos(this.pitch) * Math.cos(this.yaw),
    ];
    const camera = {
      eye,
      view: lookAt(eye, [0, 0, 0], [0, 1, 0]),
      proj: perspective(fov, aspect, dist * 0.05, dist * 4),
    };

    const x0 = -totalLen / 2, m = this.meshes;
    const head = translation(x0, 0, 0), proj = translation(x0 + cart.seat + pullDist, 0, 0);
    const items = [
      { mesh: m.case, model: head, material: cart.caseMetal === "steel" ? ROUND_MATERIALS.steelCase : MATERIALS.case },
      { mesh: m.primer, model: head, material: MATERIALS.primer },
      { mesh: m.projectile, model: proj, material: cart.solidMetal !== null ? CORE_MATERIALS[cart.solidMetal] : MATERIALS.projectile },
    ];
    if (m.caseBody) items.push({ mesh: m.caseBody, model: head, material: ROUND_MATERIALS.felt });
    if (m.core) items.push({ mesh: m.core, model: proj, material: CORE_MATERIALS[cart.coreMaterial] });
    if (m.fins) items.push({ mesh: m.fins, model: proj, material: ROUND_MATERIALS.fins });
    for (let k = 0; m[`sabot${k}`]; k++) items.push({ mesh: m[`sabot${k}`], model: proj, material: ROUND_MATERIALS.sabot });
    // Cut away the half facing the camera with a plane through the axis (x), so
    // its normal is the camera direction with the x part removed.
    const ny = eye[1], nz = eye[2], n = Math.hypot(ny, nz) || 1;
    const clipPlane = this.cutaway ? [0, ny / n, nz / n, 0] : null;
    this.renderer.render({ camera, items, clipPlane });
  }
}
