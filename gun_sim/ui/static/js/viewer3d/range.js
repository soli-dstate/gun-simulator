// The firing range: the rifle in 3D, and an animated shot driven by the
// ballistics result.
//
// Timeline of a shot (display seconds unless noted):
//   1. The firing pin falls (0.15 s).
//   2. Ignition. From here the clock is the simulation's, slowed down so the
//      ~1 ms in the bore takes a few seconds: the projectile follows the
//      solver's travel-vs-time curve and the gas behind it glows with the
//      breech pressure. In real-time mode the clock runs at real speed
//      throughout. The sound follows this clock (see onClock).
//   3. Muzzle exit: flash and smoke. A couple of milliseconds later the clock
//      ramps up to real time, so the smoke drifts and thins at its real pace.
//   4. The bolt cycles. A manual bolt turns up, draws back extracting the
//      case, which is flung out of the port, then pushes a new round from the
//      magazine into the chamber and turns down again. An automatic action
//      follows the action simulation instead, on the shot's clock: the bolt
//      unlocks, flies back, ejects, strips the next round and slams home.
//
// Throughout, the whole rifle moves as the recoil simulation says: back into
// the shoulder and pitching about it, muzzle up.
//
// A burst from a self-loading action is one action simulation with several
// shots: each fires when the simulation says, with its own projectile, flash,
// smoke and ejected case, while the recoil and muzzle climb build up. With a
// muzzle device the flash comes out of the device (a suppressor keeps most of
// it inside).

import { buildRifle } from "./gun.js";
import { chain, lookAt, perspective, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { CORE_MATERIALS, Renderer, srgbToLinear } from "./renderer.js";
import { VolumeEffects } from "./volume.js";

const MATERIALS = {
  steel: { color: srgbToLinear([0.2, 0.2, 0.22]), metallic: 1, roughness: 0.36, section: srgbToLinear([0.27, 0.28, 0.3]) },
  bolt: { color: srgbToLinear([0.74, 0.74, 0.76]), metallic: 1, roughness: 0.22, section: srgbToLinear([0.5, 0.5, 0.52]) },
  black: { color: srgbToLinear([0.06, 0.06, 0.065]), metallic: 0.6, roughness: 0.5, section: srgbToLinear([0.2, 0.2, 0.2]) },
  case: { color: srgbToLinear([0.86, 0.66, 0.34]), metallic: 1, roughness: 0.32, section: srgbToLinear([0.62, 0.45, 0.2]) },
  spent: { color: srgbToLinear([0.7, 0.5, 0.26]), metallic: 1, roughness: 0.48, section: srgbToLinear([0.5, 0.36, 0.17]) },
  primer: { color: srgbToLinear([0.78, 0.78, 0.76]), metallic: 1, roughness: 0.38, section: srgbToLinear([0.5, 0.5, 0.5]) },
  projectile: { color: srgbToLinear([0.80, 0.47, 0.30]), metallic: 1, roughness: 0.28, section: srgbToLinear([0.55, 0.3, 0.18]) },
};

const DEFAULT_VIEW = { yaw: -0.42, pitch: 0.22, zoom: 1 };
const PIN_FALL = 0.15;          // s, trigger to ignition
const RAMP_HOLD = 0.0012;       // s of simulation after exit before the clock speeds up
const SMOKE_LIFE = 6;           // s, real time
const CYCLE_DELAY = 0.35;       // s after exit (real time) before the bolt is worked
const CYCLE = { lift: 0.18, back: 0.3, pause: 0.12, forward: 0.32, lower: 0.16 };
const CYCLE_LENGTH = Object.values(CYCLE).reduce((a, b) => a + b, 0);
const RAMP = 3.2;               // 1/s, growth of the clock rate after exit
const RAMP_AUTO = 1.6;          // slower, so an automatic action's cycle can be seen
const LUG_TURN = Math.PI / 8;   // a gas action's bolt turns this much to unlock
const SETTLE = 0.6;             // s (sim) to ease the gun home after the recoil data ends
const ATM = 101325;

const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Linear interpolation in a sampled curve (xs ascending). */
function interp(xs, ys, x) {
  if (!xs.length) return 0;
  if (x <= xs[0]) return ys[0];
  const n = xs.length - 1;
  if (x >= xs[n]) return ys[n];
  let lo = 0, hi = n;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid; else hi = mid;
  }
  const f = (x - xs[lo]) / (xs[hi] - xs[lo] || 1);
  return ys[lo] + (ys[hi] - ys[lo]) * f;
}

export class FiringRange {
  /**
   * hud: optional element for the readout. interactive: false for a static preview.
   * Callbacks: onExit() at muzzle exit, onChange() when ready/busy changes,
   * onShot(result) when a shot starts and onClock(tSim, rate) on every step of
   * its clock (simulated s since ignition, simulated s per real s), so its
   * sound can follow the slow motion.
   */
  constructor(canvas, { hud = null, onExit = null, onChange = null, onShot = null, onClock = null } = {}) {
    this.canvas = canvas;
    this.hud = hud;
    this.onExit = onExit;
    this.onShot = onShot;
    this.onClock = onClock;
    this.onChange = onChange;
    this.renderer = new Renderer(canvas, { opaque: true });
    this.volume = new VolumeEffects(this.renderer.gl);
    this.meshes = {};
    this.rifle = null;
    this.view = { ...DEFAULT_VIEW };
    this.cameraMode = "auto";
    this.cutaway = false;
    this.slowMotion = 2;        // display seconds per simulated millisecond in the bore; 0 = real time
    this.autoCycle = true;
    this.cam = null;            // eased camera target {x, y, width}
    this.frame = 0;
    this.lastTime = 0;
    this.frozen = false;        // debug: hold a seeked moment
    this._resetState();
    this._bindControls();
    new ResizeObserver(() => this.requestDraw()).observe(canvas);
  }

  _resetState() {
    this.shot = null;           // the shot being shown
    this.T = 0;                 // display time since the trigger
    this.tSim = 0;              // simulation time since ignition
    this.rate = 0;              // simulated seconds per display second
    this.exitT = null;          // tSim at muzzle exit
    this.pin = 0;               // 0 cocked, 1 fired
    this.chamber = "live";      // what's in the chamber: "live", "spent" or null
    this.cycle = null;          // {t, round, startT}
    this.ejected = [];          // cases in the air
    this.wisps = [];            // smoke from the opened breech
    this.cycleQueued = false;
    this.pendingShot = null;
  }

  // ---------- public API ----------

  setGun(gun) {
    const rifle = buildRifle(gun);
    for (const mesh of Object.values(this.meshes)) this.renderer.deleteMesh(mesh);
    this.meshes = {};
    for (const [name, data] of Object.entries(rifle.meshes)) this.meshes[name] = this.renderer.createMesh(data);
    this.rifle = rifle;
    this.gun = gun;
    this._resetState();
    this.requestDraw();
    this.onChange?.();
    return rifle;
  }

  get busy() { return !!(this.shot || this.cycle || this.pendingShot); }

  /** Animate a shot. result: one model's result from the simulate API. */
  fire(result) {
    if (!this.rifle) return;
    this.frozen = false;
    this.shot = null;
    if (this.chamber !== "live" || this.cycle) {
      // Work the bolt first (or let it finish), then fire.
      this.pendingShot = result;
      this.startCycle();
      return;
    }
    this._startShot(result);
  }

  _startShot(result) {
    const pe = result.base_pressure[result.base_pressure.length - 1] || ATM;
    this.shot = {
      result,
      peak: Math.max(...result.breech_pressure, 1),
      exitPressure: pe,
      exited: false,
    };
    this.T = 0;
    this.tSim = 0;
    this.rate = 0;
    this.exitT = null;
    this.pin = 0;
    this.chamber = "live";
    this.pendingShot = null;
    this._kick();
    this.onShot?.(result);
    this.onChange?.();
  }

  /** Work the bolt (eject what's in the chamber and load a new round). */
  startCycle() {
    if (this.cycle || !this.rifle) return;
    this.cycle = { t: 0, round: this.chamber, ejected: false, wispT: null };
    this._kick();
    this.onChange?.();
  }

  setCutaway(on) { this.cutaway = on; this.requestDraw(); }
  setCameraMode(mode) { this.cameraMode = mode; this._kick(); }
  /** s: display seconds per simulated millisecond in the bore, or 0 for real time. */
  setSlowMotion(s) { this.slowMotion = s; }
  setAutoCycle(on) { this.autoCycle = on; }

  resetView() {
    this.view = { ...DEFAULT_VIEW };
    this._kick();
  }

  /** Debug: jump to display time T of a shot and hold it there. */
  seek(result, T) {
    this._resetState();
    this._startShot(result);
    this.frozen = true;
    const dt = 1 / 60;
    for (let t = 0; t < T; t += dt) this._step(dt);
    this.cam = null;
    this.requestDraw();
  }

  requestDraw() {
    if (!this.frame) this.frame = requestAnimationFrame((now) => this._tick(now));
  }

  _kick() {
    this.lastTime = 0;
    this.requestDraw();
  }

  // ---------- simulation of the animation ----------

  get layout() { return this.rifle.layout; }

  _step(dt) {
    const L = this.layout;
    if (this.shot) {
      const s = this.shot, r = s.result;
      this.T += dt;
      if (this.T < 0.06) this.pin = smooth(this.T / 0.05);
      if (this.T >= PIN_FALL) {
        const slow = this.slowMotion > 0 ? 1e-3 / this.slowMotion : 1;   // sim s per display s in the bore
        if (this.exitT === null || this.tSim < this.exitT + RAMP_HOLD) this.rate = slow;
        else this.rate = Math.min(1, this.rate * Math.exp((this._auto ? RAMP_AUTO : RAMP) * dt));
        this.tSim += dt * this.rate;
        if (!this.frozen) this.onClock?.(this.tSim, this.rate);
        if (!s.fired) {
          s.fired = true;
          this.chamber = "spent";
        }
        const tEnd = r.time[r.time.length - 1] ?? 0;
        if (this.exitT === null && this.tSim >= (r.left_muzzle ? r.muzzle_time : tEnd)) {
          this.exitT = r.left_muzzle ? r.muzzle_time : tEnd;
          s.exited = r.left_muzzle;
          s.exitRecoil = this._actionAt("recoil", this.exitT) * 1e3;
          if (r.left_muzzle) this.onExit?.();
        }
      }
      if (this._auto) this._stepAutoAction();
      if (this.exitT !== null) {
        const last = this._shotTimes[this._shotTimes.length - 1];
        const after = this.tSim - this.exitT - last;
        // A manual bolt is worked now; so is an automatic one that failed to reload (once its cycle is over).
        const over = !this._auto || this.tSim > this._action.time[this._action.time.length - 1];
        if (this.autoCycle && over && !this.cycle && after > CYCLE_DELAY && this.chamber !== "live" && !s.cycled) {
          s.cycled = true;
          this.startCycle();
        }
        if (after > SMOKE_LIFE && !this.cycle) {
          this.shot = null;
          this.onChange?.();
        }
      }
    }

    if (this.cycle) {
      const c = this.cycle;
      c.t += dt;
      const t = c.t;
      if (t > CYCLE.lift && c.wispT === null && c.round === "spent") {
        c.wispT = 0;
        this.wisps.push({ age: 0 });
      }
      if (!c.ejected && t >= CYCLE.lift + CYCLE.back) {
        c.ejected = true;
        if (c.round) {
          this.ejected.push({
            kind: c.round,
            pos: [-L.stroke, 0, 0],
            vel: [-180, 1500, 2300],          // mm/s: up and out of the port
            spin: 0, spinRate: -14, tumble: 0, tumbleRate: 5, age: 0,
          });
        }
        this.chamber = null;
      }
      if (t >= CYCLE_LENGTH) {
        this.cycle = null;
        this.chamber = "live";
        this.pin = 0;
        this.onChange?.();
        if (this.pendingShot) this._startShot(this.pendingShot);
      }
    }

    // Cases fly on the shot's clock, so they are in slow motion too.
    const dtCase = this.shot && this.rate > 0 ? dt * this.rate : dt;
    for (const e of this.ejected) {
      e.age += dtCase;
      e.vel[1] -= 9810 * dtCase;
      for (let k = 0; k < 3; k++) e.pos[k] += e.vel[k] * dtCase;
      e.spin += e.spinRate * dtCase;
      e.tumble += e.tumbleRate * dtCase;
    }
    this.ejected = this.ejected.filter((e) => e.age < 1.5);
    for (const w of this.wisps) w.age += dt;
    this.wisps = this.wisps.filter((w) => w.age < 4);
  }

  // ---------- recoil and automatic actions ----------

  /** The shot's action simulation, if it has one. */
  get _action() { return this.shot?.result.action ?? null; }

  /** True while showing a shot from a self-loading action. */
  get _auto() { const a = this._action; return !!a && a.kind !== "bolt"; }

  /** Ignition times of the shots (one, or a burst). */
  get _shotTimes() {
    const t = this._action?.shot_times;
    return t && t.length ? t : [0];
  }

  /** Time of an event of shot k (1-based) in the action simulation, or Infinity. */
  _eventTime(name, k = 1) {
    return this._action?.events.find((e) => e.name === name && (e.shot ?? 1) === k)?.time ?? Infinity;
  }

  /** The shot (1-based) whose cycle is under way at simulation time t. */
  _shotAt(t) {
    let k = 1;
    this._shotTimes.forEach((t0, i) => { if (t >= t0) k = i + 1; });
    return k;
  }

  /** Sample an action series at simulation time t; eased to rest after the data ends. */
  _actionAt(key, t) {
    const a = this._action;
    if (!a || this.T < PIN_FALL) return 0;
    const end = a.time[a.time.length - 1];
    const v = interp(a.time, a[key], Math.min(t, end));
    return t > end ? v * (1 - smooth((t - end) / SETTLE)) : v;
  }

  /** Where the rifle is: recoil (mm back) and pitch (rad, muzzle up) about the shoulder. */
  _gunPose() {
    return { recoil: this._actionAt("recoil", this.tSim) * 1e3, pitch: this._actionAt("pitch", this.tSim) };
  }

  _gunMatrix() {
    const { recoil, pitch } = this._gunPose();
    if (!recoil && !pitch) return translation(0, 0, 0);
    const [px, py] = this.layout.pivot;
    return chain(translation(-recoil, 0, 0), translation(px, py, 0), rotationZ(pitch), translation(-px, -py, 0));
  }

  /** Fire, eject and chamber when the action simulation says so, shot by shot. */
  _stepAutoAction() {
    const s = this.shot, a = this._action, t = this.tSim;
    s.done ??= new Set();
    const once = (key, at, fn) => { if (!s.done.has(key) && t >= at) { s.done.add(key); fn(); } };
    this._shotTimes.forEach((t0, i) => {
      const k = i + 1;
      if (k > 1) once(`fire${k}`, t0, () => { this.chamber = "spent"; this.pin = 1; });
      once(`eject${k}`, this._eventTime("case ejected", k), () => {
        const bolt = this._actionAt("bolt", t) * 1e3, recoil = this._actionAt("recoil", t) * 1e3;
        const speed = (interp(a.time, a.bolt_velocity, t) + interp(a.time, a.recoil_velocity, t)) * 1e3;  // mm/s
        this.ejected.push({
          kind: "spent", pos: [-bolt - recoil, 0, 0],
          vel: [-0.5 * speed, 1500 + 0.05 * speed, 2600 + 0.15 * speed],
          spin: 0, spinRate: -40, tumble: 0, tumbleRate: 18, age: 0,
        });
        this.chamber = null;
      });
      once(`battery${k}`, this._eventTime("back in battery", k), () => { this.chamber = "live"; this.pin = 0; });
    });
  }

  /** Bolt pose of an automatic action at the shot's clock. */
  _autoBoltPose() {
    const L = this.layout, a = this._action, t = this.tSim;
    const k = this._shotAt(t);
    const travel = this._actionAt("bolt", t) * 1e3;
    const unlock = a.strokes.unlock * 1e3;
    const angle = a.kind === "gas" && unlock > 0 ? -LUG_TURN * clamp(travel / unlock, 0, 1) : 0;
    let round = null;
    if (t < this._eventTime("case ejected", k)) {
      if (this.chamber) round = { kind: this.chamber, x: -travel, y: 0 };
    } else if (t >= this._eventTime("back in battery", k)) {
      round = { kind: "live", x: 0, y: 0 };
    } else if (t >= this._eventTime("strips the next round", k)) {
      const feed = a.strokes.feed * 1e3;
      const rise = smooth((feed - travel) / (0.5 * feed));
      round = { kind: "live", x: -travel + 0.5, y: (L.magTop + L.rimR * 0.6) * (1 - rise) };
    }
    return { travel, angle, round };
  }

  get animating() {
    return this.shot || this.cycle || this.ejected.length || this.wisps.length;
  }

  /** Bolt pose: {travel (mm back), angle (rad)} and the round riding on the bolt face. */
  _boltPose() {
    const L = this.layout;
    const c = this.cycle;
    if (!c && this._auto) return this._autoBoltPose();
    if (!c) return { travel: 0, angle: 0, round: this.chamber ? { kind: this.chamber, x: 0, y: 0 } : null };
    const t = c.t;
    const t1 = CYCLE.lift, t2 = t1 + CYCLE.back, t3 = t2 + CYCLE.pause, t4 = t3 + CYCLE.forward;
    let travel = 0, angle = 0, round = null;
    if (t < t1) {
      angle = -Math.PI / 2 * smooth(t / t1);
      round = c.round && { kind: c.round, x: 0, y: 0 };
    } else if (t < t2) {
      angle = -Math.PI / 2;
      travel = L.stroke * smooth((t - t1) / CYCLE.back);
      round = c.round && !c.ejected && { kind: c.round, x: -travel, y: 0 };
    } else if (t < t3) {
      angle = -Math.PI / 2;
      travel = L.stroke;
    } else if (t < t4) {
      angle = -Math.PI / 2;
      const f = (t - t3) / CYCLE.forward;
      travel = L.stroke * (1 - smooth(f));
      // The next round pops up from the magazine and is pushed into the chamber.
      const rise = smooth(f / 0.5);
      round = { kind: "live", x: -travel + 0.5, y: (L.magTop + L.rimR * 0.6) * (1 - rise) };
    } else {
      angle = -Math.PI / 2 * (1 - smooth((t - t4) / CYCLE.lower));
      round = { kind: "live", x: 0, y: 0 };
    }
    return { travel, angle, round };
  }

  /** Projectile base position (mm) of the first shot when it is under way, or null. */
  _projectileX() {
    return this._projectiles()[0]?.x ?? null;
  }

  /** Every fired shot's projectile: {x (mm), inBore}. In the bore x is in the gun's frame. */
  _projectiles() {
    const s = this.shot;
    if (!s || this.T < 0) return [];
    const L = this.layout, r = s.result, out = [];
    for (const t0 of this._shotTimes) {
      const local = this.tSim - t0;
      if (local < 0) break;
      // Still inside a muzzle device: it moves with the gun, like the gas filling the device.
      const inDevice = r.left_muzzle && local > r.muzzle_time
        ? L.muzzleX + r.muzzle_velocity * (local - r.muzzle_time) * 1e3 : null;
      if (inDevice !== null && inDevice < L.flashX) {
        out.push({ x: inDevice, inBore: true });
      } else if (r.left_muzzle && local > r.muzzle_time) {
        const recoil = this._actionAt("recoil", t0 + r.muzzle_time) * 1e3;
        const x = L.muzzleX - recoil + r.muzzle_velocity * (local - r.muzzle_time) * 1e3;
        if (x < L.muzzleX + 4000) out.push({ x, inBore: false });
      } else {
        out.push({ x: L.seat + interp(r.time, r.travel, local) * 1e3, inBore: true });
      }
    }
    return out;
  }

  _effects() {
    const L = this.layout, s = this.shot;
    const bore = L.bore;
    const state = { smoke: [], flash: null, gas: null, flashLight: [0, 0, 0] };
    let light = null;
    const dev = L.device?.type;
    // A suppressor keeps the flash inside; a brake throws it out of its vents.
    const flashScale = dev === "suppressor" ? [0.03, 0.08] : dev === "brake" ? [0.6, 0.8] : [1, 1];
    const fx = L.flashX;
    // The rifle's model matrix at a sim time (recoil, then pitch about the pivot), and its action on points.
    const gunAtT = (t) => {
      const rc = this._actionAt("recoil", t) * 1e3, pc = this._actionAt("pitch", t);
      if (!rc && !pc) return translation(0, 0, 0);
      const [px, py] = L.pivot;
      return chain(translation(-rc, 0, 0), translation(px, py, 0), rotationZ(pc), translation(-px, -py, 0));
    };
    const at = (m, x, y, z) => [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
    const gm = this._gunMatrix();
    state.gunModel = gm;
    if (s && this.T >= PIN_FALL) {
      const r = s.result;
      const times = this._shotTimes;
      const k = this._shotAt(this.tSim);
      const local = this.tSim - times[k - 1];
      const exitLocal = r.left_muzzle ? r.muzzle_time : r.time[r.time.length - 1];
      const pressure = interp(r.time, r.breech_pressure, Math.min(Math.max(local, 0), r.time[r.time.length - 1]));
      let emission = clamp(pressure / s.peak, 0, 1);
      // With a device the projectile runs on through it (gun frame, mm); the flash waits for it to leave the front.
      const v = r.muzzle_velocity, dd = L.device;
      const inDev = !!dd && r.left_muzzle && v > 0;
      const devDelay = inDev ? L.deviceLength / (v * 1e3) : 0;
      const gasEnd = inDev ? L.flashX : L.muzzleX;
      const decayFrom = exitLocal + devDelay;
      let x1 = local < exitLocal ? L.seat + interp(r.time, r.travel, local) * 1e3
        : inDev ? L.muzzleX + v * (local - exitLocal) * 1e3 : L.muzzleX;
      const pExit = clamp(interp(r.time, r.breech_pressure, Math.min(exitLocal, r.time[r.time.length - 1])) / s.peak, 0, 1);
      if (local >= decayFrom) emission *= Math.exp(-(local - decayFrom) / 0.0008);
      if (inDev && local >= exitLocal) {
        // The device fills with gas behind the projectile, front-ward, and holds it (a suppressor much longer than a brake).
        const age = local - exitLocal, tau = dd.type === "suppressor" ? 0.003 : 0.0005;
        const ri = dd.R - dd.w, e = pExit * Math.exp(-age / tau);
        if (e > 0.01) {
          state.dev = { x0: L.muzzleX + dd.w, x1: Math.min(x1, L.flashX), radius: ri, emission: e * (dd.type === "suppressor" ? 0.5 : 0.35) / ri };
        }
      }
      if (emission > 0.01 && local >= 0) {
        state.gas = { x0: L.head, x1: Math.min(x1, gasEnd), emission: emission * 0.7 / L.boreR, boreR: L.boreR, caseR: L.caseInnerR, neckX: L.neckX };
      }
      const exited = times.map((t0) => t0 + decayFrom).filter((te) => r.left_muzzle && this.tSim >= te);
      if (exited.length) {
        const ratio = Math.max(s.exitPressure / ATM, 1);
        const xm = clamp(0.67 * bore * Math.sqrt(ratio), 3 * bore, 22 * bore) * (dev ? 0.5 : 1);
        const unburnt = clamp(1 - r.burnt_at_muzzle, 0, 1);
        const ms = (this.tSim - exited[exited.length - 1]) * 1e3;   // the latest shot's flash
        const primary = flashScale[0] * smooth(ms / 0.015) * Math.exp(-ms / 0.25) * clamp(Math.sqrt(ratio / 300), 0.3, 1.5);
        const secondary = flashScale[1] * clamp(0.15 + ratio / 2000 + 2 * unburnt, 0.1, 1.2) * smooth((ms - 0.04) / 0.25) * Math.exp(-Math.max(ms - 0.3, 0) / 0.55);
        if (primary + secondary > 0.003) {
          state.flash = { muzzle: at(gm, fx, 0, 0), dir: [gm[0], gm[1], gm[2]], primary, secondary, machDisk: xm, boreR: bore / 2, age: ms };
          const glow = primary * 2 + secondary * 1.4;
          state.flashLight = [1.0 * glow, 0.5 * glow, 0.18 * glow].map((v) => v * 0.6);
          light = { position: at(gm, fx + xm, 0, 0), color: [14 * glow, 7 * glow, 2.6 * glow], range: xm * 1.5 };
        }
        // Smoke: the first shot's cloud (thicker for each shot after it) and the latest shot's puffs.
        const pf = clamp(Math.sqrt(s.exitPressure / 50e6), 0.4, 2) * (dev === "suppressor" ? 0.5 : 1);
        const puff = (age, thick, main, rising, te) => {
          const gT = gunAtT(te), o = at(gT, fx, 0, 0);   // where the muzzle was when it was emitted
          const msA = age * 1e3;
          if (main) {
            const reach = clamp(22 * bore * pf, 60, 600), R0 = clamp(5 * bore * pf, 15, 150);
            const grow = 1 - Math.exp(-age / 0.012);
            const radius = R0 * (0.3 + 0.7 * grow + 0.4 * age);
            const fade = Math.exp(-age / 1.8) * smooth(msA / 0.3);
            if (fade > 0.01) {
              state.smoke.push({
                origin: o, dir: [gT[0], gT[1], gT[2]], reach: reach * grow + 25 * age, radius,
                extinction: 1.4 * thick * fade / radius, rise: 45 * Math.pow(age, 1.5), age, group: 0, seed: 3.1, trail: 0.7,
              });
            }
          }
          const a2 = age - 0.06;
          if (rising && a2 > 0 && a2 < SMOKE_LIFE) {
            const r2 = 1.6 * bore + 12 * a2;
            state.smoke.push({
              origin: o, dir: [0, 1, 0], reach: 2 * bore + 45 * a2, radius: r2,
              extinction: 0.7 * Math.exp(-a2 / 2.2) * smooth(a2 / 0.2) / r2, rise: 0, age: a2, group: 0, seed: 7.7, trail: 1,
            });
          }
        };
        const first = this.tSim - exited[0];
        if (exited.length === 1) puff(first, 1, true, true, exited[0]);
        else {
          puff(first, Math.sqrt(Math.min(exited.length, 4)), true, false, exited[0]);
          const latest = this.tSim - exited[exited.length - 1];
          puff(latest, 1, true, true, exited[exited.length - 1]);
        }
      }
    }
    for (const w of this.wisps) {
      const r = 1.8 * bore + 14 * w.age;
      state.smoke.push({
        origin: [L.rearX - 4, 0, 0], dir: [-0.75, 0.55, 0.37], reach: 2 * bore + 40 * w.age, radius: r,
        extinction: 0.55 * Math.exp(-w.age / 1.3) * smooth(w.age / 0.15) / r, rise: 20 * w.age * w.age,
        age: w.age, group: 1, seed: 12.4, trail: 0.8,
      });
    }
    return { state, light };
  }

  // ---------- camera ----------

  _cameraGoal() {
    const L = this.layout;
    const rear = Math.min(L.boltRear, L.buttX) - 10, front = L.muzzleX;
    const goals = {
      // The butt is nearest the default camera, so the frame leans towards it.
      rifle: { x: (rear + front) / 2 - 0.06 * (front - rear), y: -L.recR * 1.5, width: (front - rear) * 1.3 },
      breech: { x: (L.portRear - 40 + L.caseLength + 30) / 2, y: -L.recR * 0.3, width: (L.caseLength + 70 - L.portRear) * 1.25 },
      muzzle: { x: L.flashX + 16 * L.bore - 0.3 * L.deviceLength, y: 0, width: Math.max(70 * L.bore, 200) + L.deviceLength },
      follow: null,
    };
    const projX = this._projectileX();
    goals.follow = projX !== null
      ? { x: Math.min(projX + L.projectileLength / 2, L.flashX + 30 * L.bore), y: 0, width: Math.max(16 * L.bore, 90) }
      : goals.muzzle;
    let mode = this.cameraMode;
    if (mode === "auto") {
      const s = this.shot;
      // An automatic action cycles within milliseconds of exit, while the clock is still slow.
      const toBreech = this._auto ? RAMP_HOLD : CYCLE_DELAY * 0.8;
      if (this.cycle || (s && this.exitT !== null && this.tSim - this.exitT > toBreech)) mode = "breech";
      else if (s && this.exitT !== null) mode = "muzzle";
      else if (s && this.slowMotion > 0 && this.T > PIN_FALL + 0.15 * this.slowMotion) mode = "follow";
      else if (s || this.pendingShot) mode = "breech";
      else mode = "rifle";
    }
    return { goal: goals[mode], mode };
  }

  _updateCamera(dt) {
    const { goal, mode } = this._cameraGoal();
    if (!this.cam || dt === null) {
      this.cam = { ...goal };
      return false;
    }
    const k = 1 - Math.exp(-(mode === "follow" ? 14 : 5) * dt);
    const c = this.cam;
    c.x += (goal.x - c.x) * k;
    c.y += (goal.y - c.y) * k;
    c.width *= Math.exp(Math.log(goal.width / c.width) * k);
    return Math.abs(goal.x - c.x) > 0.05 || Math.abs(goal.width / c.width - 1) > 1e-3;
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
      this.view.yaw -= (e.clientX - drag.x) * 0.008;
      this.view.pitch = clamp(this.view.pitch + (e.clientY - drag.y) * 0.008, -1.45, 1.45);
      drag = { x: e.clientX, y: e.clientY };
      this.requestDraw();
    });
    const end = () => { drag = null; };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.view.zoom = clamp(this.view.zoom * Math.exp(e.deltaY * 0.001), 0.08, 6);
      this.requestDraw();
    }, { passive: false });
    c.addEventListener("dblclick", () => this.resetView());
  }

  // ---------- drawing ----------

  _tick(now) {
    this.frame = 0;
    if (!this.rifle) return;
    const dt = this.lastTime ? Math.min((now - this.lastTime) / 1000, 0.05) : 1 / 60;
    this.lastTime = now;
    if (!this.frozen && this.animating) this._step(dt);
    const moving = this._updateCamera(this.frozen ? null : dt);
    this._draw();
    if ((!this.frozen && this.animating) || moving) {
      this.requestDraw();
    } else {
      this.lastTime = 0;
    }
  }

  _draw() {
    const L = this.layout, m = this.meshes;
    const aspect = this.renderer.resize();
    const fov = 30 * Math.PI / 180;
    const fovX = 2 * Math.atan(Math.tan(fov / 2) * aspect);
    const cam = this.cam;
    const { yaw, pitch, zoom } = this.view;
    const dist = (cam.width / 2 / Math.tan(fovX / 2) + L.recR) * zoom;
    const target = [cam.x, cam.y, 0];
    const eye = [
      target[0] + dist * Math.cos(pitch) * Math.sin(yaw),
      target[1] + dist * Math.sin(pitch),
      target[2] + dist * Math.cos(pitch) * Math.cos(yaw),
    ];
    const camera = {
      eye,
      view: lookAt(eye, target, [0, 1, 0]),
      proj: perspective(fov, aspect, Math.max(dist * 0.02, 0.5), dist * 4 + 6000),
    };

    const pose = this._boltPose();
    const gunAt = this._gunMatrix();           // the whole rifle, recoiling
    const boltAt = chain(gunAt, translation(-pose.travel, 0, 0));
    const pinBack = (this.cycle && this.cycle.t > CYCLE.lift * 0.5) || (this._auto && pose.travel > 0.5) ? 0 : this.pin;
    const items = [
      { mesh: m.steel, model: gunAt, material: MATERIALS.steel },
      { mesh: m.furniture, model: gunAt, material: MATERIALS.black },
      // The bolt stays whole in the cutaway, so it reads clearly inside the cut receiver.
      { mesh: m.bolt, model: chain(boltAt, rotationX(pose.angle)), material: MATERIALS.bolt, clip: false },
      ...(m.shroud ? [{ mesh: m.shroud, model: boltAt, material: MATERIALS.steel, clip: false }] : []),
      // A gas rifle's carrier slides without turning; its bolt head (above) turns in it.
      ...(m.carrier ? [{ mesh: m.carrier, model: boltAt, material: MATERIALS.steel, clip: false }] : []),
      { mesh: m.striker, model: chain(gunAt, translation(-pose.travel + pinBack * L.pinTravel, 0, 0)), material: MATERIALS.bolt, clip: false },
    ];
    const addProjectile = (model, clip) => {
      items.push({ mesh: m.projectile, model, material: MATERIALS.projectile, clip });
      if (m.core) items.push({ mesh: m.core, model, material: CORE_MATERIALS[L.coreMaterial], clip });
    };
    const addRound = (kind, model) => {
      items.push({ mesh: m.case, model, material: kind === "spent" ? MATERIALS.spent : MATERIALS.case });
      items.push({ mesh: m.primer, model, material: MATERIALS.primer });
      if (kind === "live") addProjectile(chain(model, translation(L.seat, 0, 0)), true);
    };
    if (pose.round) addRound(pose.round.kind, chain(gunAt, translation(pose.round.x, pose.round.y, 0)));
    for (const e of this.ejected) {
      const half = L.caseLength / 2;
      addRound(e.kind, chain(translation(...e.pos), translation(half, 0, 0), rotationY(e.spin), rotationZ(e.tumble), translation(-half, 0, 0)));
    }
    // Fired projectiles are drawn on their own, whole even in the cutaway; in the bore they move with the gun.
    if (this.shot) {
      for (const p of this._projectiles()) {
        addProjectile(p.inBore ? chain(gunAt, translation(p.x, 0, 0)) : translation(p.x, 0, 0), false);
      }
    }

    const ny = eye[1] - target[1], nz = eye[2] - target[2], n = Math.hypot(ny, nz) || 1;
    const clipPlane = this.cutaway ? [0, ny / n, nz / n, 0] : null;
    const { state, light } = this._effects();
    const overlay = this.volume.set(state)
      ? (gl, info) => this.volume.draw(gl, info, eye, clipPlane)
      : null;
    this.renderer.render({ camera, items, clipPlane, pointLight: light, overlay });
    this._updateHud();
  }

  _updateHud() {
    if (!this.hud) return;
    const s = this.shot;
    if (!s) {
      const what = this.cycle ? "Working the bolt" : this.chamber === "live" ? "Ready: round chambered"
        : this.chamber === "spent" ? "Spent case in the chamber" : "Chamber empty";
      this.hud.innerHTML = `<b>${what}</b>`;
      return;
    }
    const r = s.result;
    let phase, slow;
    if (this.T < PIN_FALL) phase = "Firing pin falls";
    else if (this.exitT === null) phase = this.tSim < 0.05 * r.muzzle_time ? "Ignition" : "Projectile in the bore";
    else if (!s.exited) phase = "Projectile stuck in the bore";
    else if (this.tSim - this.exitT < 0.003) phase = "Muzzle exit: flash";
    else if (this._auto) {
      const a = this._action;
      // The latest step of the cycle; the first shot's firing is the flash above.
      const last = a.events.filter((e) => e.time <= this.tSim && !(e.name === "fires" && e.shot === 1)).pop();
      const done = this.tSim > a.time[a.time.length - 1];
      const label = (e) => (e.name === "fires" ? `Shot ${e.shot} fires` : e.name[0].toUpperCase() + e.name.slice(1));
      phase = this.cycle ? "Clearing: working the bolt by hand"
        : last && !done ? label(last)
        : !last && !done ? "Gas drives the piston"
        : a.status === "cycled" ? "Smoke · reloaded" : `Smoke · ${a.status}`;
    }
    else phase = this.cycle ? "Working the bolt" : "Smoke";
    if (this.rate >= 0.999) slow = "real time";
    else if (this.rate > 0) slow = `${Math.round(1 / this.rate).toLocaleString()}× slower`;
    else slow = "";
    const t = Math.min(this.tSim, r.time[r.time.length - 1]);
    const inBore = this.exitT === null;
    const travel = inBore ? interp(r.time, r.travel, t) * 1e3 : null;
    const v = inBore ? interp(r.time, r.velocity, t) : r.muzzle_velocity;
    const pb = interp(r.time, r.breech_pressure, t) / 1e6, pbase = interp(r.time, r.base_pressure, t) / 1e6;
    const tms = this.tSim * 1e3;
    const rows = [
      ["t", tms < 100 ? `${tms.toFixed(3)} ms` : `${(tms / 1e3).toFixed(2)} s`],
      ["speed", slow],
    ];
    if (inBore) {
      rows.push(["travel", `${travel.toFixed(1)} mm`], ["velocity", `${v.toFixed(0)} m/s`],
                ["breech", `${pb.toFixed(1)} MPa`], ["base", `${pbase.toFixed(1)} MPa`]);
    } else if (s.exited) {
      rows.push(["muzzle velocity", `${r.muzzle_velocity.toFixed(0)} m/s`],
                ["exit pressure", `${(s.exitPressure / 1e6).toFixed(1)} MPa`]);
    }
    if (this._action && this.T >= PIN_FALL) {
      const { recoil, pitch } = this._gunPose();
      const vel = this._actionAt("recoil_velocity", this.tSim);
      rows.push(["recoil", `${recoil.toFixed(1)} mm at ${vel.toFixed(2)} m/s`],
                ["muzzle rise", `${(pitch * 180 / Math.PI).toFixed(2)}°`]);
      if (this._auto) {
        const bolt = this._actionAt("bolt", this.tSim) * 1e3, bv = this._actionAt("bolt_velocity", this.tSim);
        rows.push(["bolt", `${bolt.toFixed(0)} mm, ${bv >= 0 ? "back" : "forward"} at ${Math.abs(bv).toFixed(1)} m/s`]);
      }
    }
    if (this._shotTimes.length > 1 && this.T >= PIN_FALL) {
      rows.unshift(["shot", `${this._shotAt(this.tSim)} of ${this._shotTimes.length}`]);
    }
    this.hud.innerHTML = `<b>${phase}</b>` + rows.map(([k, val]) => `<span>${k}</span><span>${val}</span>`).join("");
  }
}
