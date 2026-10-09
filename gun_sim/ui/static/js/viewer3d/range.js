// The firing range: the rifle in 3D, and an animated shot driven by the
// ballistics result.
//
// Timeline of a shot (display seconds unless noted):
//   1. The firing pin falls (0.15 s).
//   2. Ignition. From here the clock is the simulation's, slowed down so the
//      ~1 ms in the bore takes a few seconds: the projectile follows the
//      solver's travel-vs-time curve and the gas behind it glows as hot as the
//      fluid model says it is. In real-time mode the clock runs at real speed
//      throughout. The sound follows this clock (see onClock).
//   3. Muzzle exit: flash and smoke, as the 2D plume solution (gun_sim/plume.py)
//      has them: the gas glows where it is hot and carries the smoke. A couple
//      of milliseconds later the clock ramps up to real time, so the smoke
//      drifts and thins at its real pace.
//   4. The bolt cycles. A manual bolt turns up, draws back extracting the
//      case, which is flung out of the port, then pushes a new round from the
//      magazine into the chamber and turns down again. An automatic action
//      follows the action simulation instead, on the shot's clock: the bolt
//      unlocks, flies back, ejects, strips the next round and slams home.
//
// Ammunition. The range counts the rounds in the magazine (or belt) from shot
// to shot, replays included: each shot is simulated with the rounds it has
// left, and the magazine shows them, its stack rising as the spring lifts it
// (as the simulation has it), its top round changing side each shot; a belt is
// drawn across by the feed slide as the bolt group's cam swings the lever, and
// sheds its empty links. The stripped round tips up the feed ramp at the feed
// angle; a jam leaves it wedged there, and a bolt caught open by an empty
// magazine stays back, until the bolt is worked or the magazine changed.
//
// Throughout, the whole rifle moves as the recoil simulation says: back into
// the shoulder and pitching about it, muzzle up. Gas and smoke stay in the air
// where they left the gun; only their source, the barrel tip or the breech,
// moves with it, so a seeping trail joins the moving gun to the still cloud.
//
// A burst from a self-loading action is one action simulation with several
// shots: each fires when the simulation says, with its own projectile, flash,
// smoke and ejected case, while the recoil and muzzle climb build up. A muzzle
// device is in the plume solution, so its flash and smoke come out of it as
// they were solved to (a brake's sideways, a suppressor's late and dim).

import { buildRifle } from "./gun.js";
import { chain, invert, lookAt, perspective, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { feedCheck } from "./feed.js";
import { CORE_MATERIALS, Renderer, srgbToLinear } from "./renderer.js";
import { VolumeEffects } from "./volume.js";

const MATERIALS = {
  steel: { color: srgbToLinear([0.2, 0.2, 0.22]), metallic: 1, roughness: 0.36, section: srgbToLinear([0.27, 0.28, 0.3]) },
  bolt: { color: srgbToLinear([0.74, 0.74, 0.76]), metallic: 1, roughness: 0.22, section: srgbToLinear([0.5, 0.5, 0.52]) },
  black: { color: srgbToLinear([0.06, 0.06, 0.065]), metallic: 0.6, roughness: 0.5, section: srgbToLinear([0.2, 0.2, 0.2]) },
  wood: { color: srgbToLinear([0.3, 0.13, 0.06]), metallic: 0, roughness: 0.45, section: srgbToLinear([0.55, 0.34, 0.18]) },
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
const RELOAD = { out: 0.45, in: 0.55 };   // s: the empty magazine drops out, a full one goes in
const RAMP = 3.2;               // 1/s, growth of the clock rate after exit
const RAMP_AUTO = 1.6;          // slower, so an automatic action's cycle can be seen
const LUG_TURN = Math.PI / 8;   // a gas action's bolt turns this much to unlock
const SETTLE = 0.6;             // s (sim) to ease the gun home after the recoil data ends
const ATM = 101325;
const T_AIR = 288;              // K
const WIEN = 23980;             // K, as volume.js: glow ~ exp(-WIEN / T)
const FLASH_LIGHT = 2e4;        // light from the flash per unit of the plume's glow
const SEEP_DILUTION = 20;       // air taken in per volume of gas seeping out of the exit
const SMOKE = 0.012;            // smoke extinction per mm per kg/m^3 of propellant gas (volume.js)
const RISE_DRAG = 0.8;          // s, how fast the rising cloud comes to its terminal speed

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

/**
 * How far the cloud has risen (mm) t s after the solved window: its warmth lifts it, falling as
 * the puff takes in air (excess temperature ~ scale^-3), against drag. Returns {t, h}.
 */
function riseTable(cloud) {
  const t = [0], h = [0];
  let v = 0, z = 0, prev = 0;
  for (let i = 0; i <= 300; i++) {
    const now = 1e-5 * Math.pow(8 / 1e-5, i / 300), dt = now - prev;
    const scale = Math.pow((cloud.age + now) / cloud.age, 0.25);
    v += dt * (9810 * cloud.warmth * scale ** -3 - v / RISE_DRAG);
    z += dt * v;
    t.push(now); h.push(z);
    prev = now;
  }
  return { t, h };
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
    this.mag = this.rifle?.layout.feed.capacity ?? 0;   // rounds in the magazine or belt
    this.stuck = null;          // the bolt stopped short after a shot: {travel, round} (held open, or jammed)
    this.jam = null;            // why the round in the chamber is jammed
    this.reload = null;         // {t, swapped}
    this.beltAdv = 0;           // share of a link the belt has been drawn this cycle
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

  get busy() { return !!(this.shot || this.cycle || this.reload || this.pendingShot); }

  /**
   * Rounds that will be in the magazine when the next shot fires: as now with a round chambered,
   * else one fewer once the bolt is worked, or a fresh magazine's less one if this one is empty.
   */
  roundsAtNextShot() {
    if (!this.rifle) return null;
    if (this.chamber === "live") return this.mag;
    return this.mag > 0 ? this.mag - 1 : this.layout.feed.capacity - 1;
  }

  /** Animate a shot. result: one model's result from the simulate API. */
  fire(result) {
    if (!this.rifle) return;
    this.frozen = false;
    this.shot = null;
    if (this.chamber !== "live" || this.cycle || this.reload) {
      // Load (and work the bolt) first, or let that finish, then fire.
      this.pendingShot = result;
      if (!this.cycle && !this.reload) this._prepare();
      return;
    }
    this._startShot(result);
  }

  /** Get a live round into the chamber: change an empty magazine first, then work the bolt. */
  _prepare() {
    if (this.mag === 0 && this.chamber !== "live") this.startReload();
    else this.startCycle();
  }

  /** Change the magazine (or belt) for a full one. */
  startReload() {
    if (this.reload || this.cycle || !this.rifle) return;
    this.reload = { t: 0, swapped: false };
    this._kick();
    this.onChange?.();
  }

  _startShot(result) {
    const pe = result.base_pressure[result.base_pressure.length - 1] || ATM;
    this.shot = {
      result,
      plume: result.plume ?? null,
      rise: result.plume ? riseTable(result.plume.cloud) : null,
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
    // The simulation was fired with the rounds this magazine has (a replay is re-simulated to match).
    this.mag = result.action?.rounds?.[0] ?? this.mag;
    this.stuck = this.jam = null;
    this._kick();
    this.onShot?.(result);
    this.onChange?.();
  }

  /** Work the bolt: eject what's in the chamber (or clear a jam) and load a new round. */
  startCycle() {
    if (this.cycle || this.reload || !this.rifle) return;
    const from = this.stuck?.travel ?? 0;
    const c = this.cycle = { t: 0, round: this.chamber, ejected: false, wispT: null, from, adv: 0, lift: 0, fed: false, jamAt: null };
    const heldOpen = this.stuck && !this.chamber;
    if (this.chamber === "jammed") {
      // The wedged round is pulled free and falls out of the open action.
      const r = this.stuck?.round;
      if (r) this.ejected.push({ kind: "live", pos: [r.x, r.y, 0], vel: [-60, -300, 500], spin: 0, spinRate: -4, tumble: r.angle ?? 0, tumbleRate: 3, age: 0 });
      c.round = null;
      this.chamber = null;
    }
    // A bolt held open has nothing to extract: it only runs home.
    if (heldOpen) { c.t =CYCLE.lift + CYCLE.back + CYCLE.pause; c.ejected = true; c.fwdFrom = from; }
    this.stuck = this.jam = null;
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
        // A bolt held open on an empty magazine, or a jam, stays as it is for the shooter to clear.
        if (this.autoCycle && over && !this.cycle && !this.stuck && after > CYCLE_DELAY && this.chamber !== "live" && !s.cycled) {
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
        this.wisps.push({ age: 0, gun: this._gunMatrix() });   // where the breech was when it opened
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
      const F = L.feed, t3 = CYCLE.lift + CYCLE.back + CYCLE.pause;
      const travel = this._boltPose().travel;
      if (t < t3) {
        // Going back: the belt is drawn as the cam swings the lever; past the round, the spring lifts it.
        if (F.belt) c.adv = this.beltAdv = Math.max(c.adv, F.camFrac(this._mechPose(travel).carrier));
        c.lift = smooth((travel - (L.oal + 3)) / 4);
      } else if (!c.fed) {
        // Coming forward, the bolt strips the next round, if there is one, and drives it at the feed angle.
        c.fed = true;
        if (this.mag > 0) {
          this.mag--;
          c.feeding = true;
          if (F.belt) this._shedLink();
          this.beltAdv = 0;
          const check = feedCheck(F.geo, 1, L.oal + 3);
          if (check.jam) { c.jamAt = Math.max(L.oal + 3 - check.travel, 1); c.jam = check.jam; }
        }
      }
      if (t >= CYCLE_LENGTH) {
        this.cycle = null;
        this.pin = 0;
        if (c.jamAt !== null) {
          this.chamber = "jammed";
          this.jam = c.jam;
          this.stuck = { travel: c.jamAt, round: this._feedingRound(c.jamAt) };
          this.pendingShot = null;
        } else {
          this.chamber = c.feeding ? "live" : null;
        }
        this.onChange?.();
        if (this.pendingShot) {
          if (this.chamber === "live") this._startShot(this.pendingShot);
          else if (this.mag === 0) this.startReload();
          else this.pendingShot = null;
        }
      }
    }

    if (this.reload) {
      const r = this.reload;
      r.t += dt;
      if (!r.swapped && r.t >= RELOAD.out) {
        r.swapped = true;
        this.mag = L.feed.capacity;
        this.beltAdv = 0;
      }
      if (r.t >= RELOAD.out + RELOAD.in) {
        this.reload = null;
        this.onChange?.();
        if (this.chamber !== "live" && this.chamber !== "jammed") this.startCycle();
        else if (this.pendingShot && this.chamber === "live") this._startShot(this.pendingShot);
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
    this.ejected = this.ejected.filter((e) => e.age < (e.kind === "live" ? 3 : 1.5));
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
    // A bolt held open or jammed stays where it stopped; the rest settles home.
    if (key === "bolt" && (a.held_open || a.jam)) return v;
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
    // Each round stripped leaves the magazine (a belt sheds its link); a jam wedges it.
    a.events.forEach((e, i) => {
      if (e.name === "strips the next round") {
        once(`strip${i}`, e.time, () => {
          this.mag = e.rounds ?? Math.max(this.mag - 1, 0);
          if (this.layout.feed.belt) this._shedLink();
        });
      } else if (e.name === "jams") {
        once(`jam${i}`, e.time, () => { this.chamber = "jammed"; this.jam = a.jam?.jam ?? "jam"; });
      }
    });
    const end = a.time[a.time.length - 1];
    once("end", end, () => {
      this.beltAdv = a.feed?.length ? a.feed[a.feed.length - 1] : 0;
      if (a.held_open || a.jam) {
        const travel = a.bolt[a.bolt.length - 1] * 1e3;
        this.stuck = { travel, round: a.jam ? this._feedingRound(travel) : null };
      }
    });
  }

  /** An empty link falls out of the right of the feed tray. */
  _shedLink() {
    const F = this.layout.feed, [x, y, z] = F.ejectLink(), recoil = this._actionAt("recoil", this.tSim) * 1e3;
    this.ejected.push({ kind: "link", pos: [x - recoil, y, z], vel: [0, 200, 900], spin: 0, spinRate: 0, tumble: 0, tumbleRate: 8, age: 0 });
  }

  /** The round the bolt is driving into the chamber, the bolt `travel` mm back: it tips up the ramp from the feed angle. */
  _feedingRound(travel) {
    const L = this.layout, g = L.feed.geo, feedAt = L.oal + 3;
    const p = clamp((feedAt - travel) / feedAt, 0, 1);
    return { kind: "live", x: -travel + 0.5, y: g.drop * (1 - smooth(p / 0.55)), angle: g.angle * (1 - smooth(p / 0.75)) };
  }

  /** How far up the magazine spring has lifted the top round (0 under the bolt, 1 at the lips), or a belt's draw. */
  _feedState() {
    const a = this._action, F = this.layout.feed;
    if (this.shot && this._auto && this.T >= PIN_FALL && a.feed?.length) {
      const v = interp(a.time, a.feed, Math.min(this.tSim, a.time[a.time.length - 1]));
      return F.belt ? { lift: 1, adv: v } : { lift: v, adv: 0 };
    }
    if (this.cycle) return { lift: F.belt ? 1 : this.cycle.fed ? 0 : this.cycle.lift, adv: this.beltAdv };
    return { lift: F.belt || this.stuck?.travel > this.layout.oal + 3 ? 1 : 0, adv: this.beltAdv };
  }

  /** How far the magazine is dropped out of the gun (mm) while it is changed. */
  _magDrop() {
    const r = this.reload;
    if (!r || this.layout.feed.belt) return 0;
    const far = (this.layout.feed.depth ?? 0) + 120;
    return r.t < RELOAD.out ? far * smooth(r.t / RELOAD.out) : far * (1 - smooth((r.t - RELOAD.out) / RELOAD.in));
  }

  /** Bolt pose of an automatic action at the shot's clock. */
  _autoBoltPose() {
    const L = this.layout, a = this._action, t = this.tSim;
    const k = this._shotAt(t);
    const travel = this._actionAt("bolt", t) * 1e3;
    // The simulation's own unlock travel and delay ratio, which the parts that follow the bolt use.
    const s = a.strokes;
    const mech = { ...L.mech, unlock: s.unlock * 1e3, ratio: s.carrier_unlock ? s.carrier_unlock / s.unlock : L.mech.ratio };
    const { angle, ...follow } = this._mechPose(travel, mech);
    let round = null;
    const jammed = a.jam && a.jam.shot === k;
    if (t < this._eventTime("case ejected", k)) {
      if (this.chamber && this.chamber !== "jammed") round = { kind: this.chamber, x: -travel, y: 0 };
    } else if (!jammed && t >= this._eventTime("back in battery", k)) {
      round = { kind: "live", x: 0, y: 0 };
    } else if (t >= this._eventTime("strips the next round", k)) {
      round = this._feedingRound(travel);
    }
    return { travel, angle, round, ...follow };
  }

  /**
   * Where the parts that follow the bolt are, with the bolt (head) `travel` mm back: a rotating
   * bolt's turn, a carrier's travel, a short-recoil barrel's, how far a locking block, rollers or a
   * lever have come out of engagement (0 locked, 1 free), and the lever's tilt.
   */
  _mechPose(travel, mech = this.layout.mech) {
    const L = this.layout, u = mech.unlock;
    const free = u > 0 ? clamp(travel / u, 0, 1) : 0;
    const out = { angle: 0, carrier: travel, barrel: 0, lock: 0, lever: 0 };
    if (mech.kind === "gas" || mech.kind === "direct_impingement") {
      out.angle = -LUG_TURN * free;
    } else if (mech.kind === "roller_delayed" || mech.kind === "lever_delayed") {
      // The carrier runs `ratio` times as fast as the head until the delay ends, then keeps its lead.
      out.carrier = travel < u ? mech.ratio * travel : travel + (mech.ratio - 1) * u;
      out.lock = free;
      if (L.lever) out.lever = Math.atan((out.carrier - travel) / L.lever.arm);
    } else if (mech.kind === "short_recoil") {
      out.barrel = Math.min(travel, u);
      out.lock = free;
    }
    return out;
  }

  /**
   * The hammer's angle back from the firing pin (rad): on the sear until the trigger is pulled,
   * falling as the firing pin does, then as the action simulation has it.
   */
  _hammerAngle() {
    const sear = this.layout.hammer?.sear ?? 0, a = this._action;
    if (!this.shot) return sear;
    if (this.T < PIN_FALL) return sear * (1 - this.pin);
    if (!a?.hammer) return 0;
    return interp(a.time, a.hammer, Math.min(this.tSim, a.time[a.time.length - 1]));
  }

  get animating() {
    return this.shot || this.cycle || this.reload || this.ejected.length || this.wisps.length;
  }

  /** Bolt pose: {travel (mm back), angle (rad)} and the round riding on the bolt face. */
  _boltPose() {
    const L = this.layout;
    const c = this.cycle;
    if (!c && this._auto) return this._autoBoltPose();
    if (!c) {
      // Shut, or stopped short after the shot: held open on an empty magazine, or on a jammed round.
      const travel = this.stuck?.travel ?? 0;
      const round = this.stuck ? this.stuck.round : this.chamber ? { kind: this.chamber, x: 0, y: 0 } : null;
      return { travel, round, ...this._mechPose(travel) };
    }
    const t = c.t;
    const t1 = CYCLE.lift, t2 = t1 + CYCLE.back, t3 = t2 + CYCLE.pause, t4 = t3 + CYCLE.forward;
    let travel = 0, angle = 0, round = null;
    if (t < t1) {
      angle = -Math.PI / 2 * smooth(t / t1);
      travel = c.from;
      round = c.round && { kind: c.round, x: -travel, y: 0 };
    } else if (t < t2) {
      angle = -Math.PI / 2;
      travel = c.from + (L.stroke - c.from) * smooth((t - t1) / CYCLE.back);
      round = c.round && !c.ejected && { kind: c.round, x: -travel, y: 0 };
    } else if (t < t3) {
      angle = -Math.PI / 2;
      travel = L.stroke;
    } else if (t < t4 || c.jamAt !== null) {
      // The next round is stripped and driven up the ramp into the chamber, unless it wedges.
      angle = -Math.PI / 2;
      const f = Math.min((t - t3) / CYCLE.forward, 1);
      travel = Math.max((c.fwdFrom ?? L.stroke) * (1 - smooth(f)), c.jamAt ?? 0);
      if (c.feeding) round = this._feedingRound(travel);
    } else {
      angle = -Math.PI / 2 * (1 - smooth((t - t4) / CYCLE.lower));
      if (c.feeding) round = { kind: "live", x: 0, y: 0 };
    }
    // A self-loader is drawn back by its handle: no lift; its bolt turns (or its parts follow) as it goes.
    if (L.mech.kind !== "bolt") return { travel, round, ...this._mechPose(travel) };
    return { travel, round, ...this._mechPose(travel), angle };
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

  /** Gas temperatures along the column at a shot's local time, from the fluid model (K), or null when it's cold. */
  _boreTemps(P, local, exitLocal) {
    // The plume comes from the fluid model; another model's shot is lined up on it at exit.
    const tf = local < exitLocal ? local * P.muzzle_time / exitLocal : P.muzzle_time + (local - exitLocal);
    const ts = P.bore.t;
    let k = 0;
    while (k < ts.length - 2 && ts[k + 1] <= tf) k++;
    const w = clamp((tf - ts[k]) / (ts[k + 1] - ts[k] || 1), 0, 1);
    const a = P.bore.T[k], b = P.bore.T[k + 1] ?? a;
    const temps = a.map((v, i) => v + (b[i] - v) * w);
    return Math.max(...temps) > 700 ? temps : null;
  }

  /**
   * One shot's plume tau s after its exit, in the gun's frame at exit (gT). Within the solved
   * window it's the frames; after it, the last frame (the cloud) carried on as a puff that
   * grows as age^(1/4), thins and cools as it takes in air, and rises with its warmth.
   */
  _plumeAt(P, rise, tau, gT, thick, seed) {
    const L = this.layout, n = P.times.length, last = P.times[n - 1], c = P.cloud;
    // The cloud grows about its own centre, so it spreads back over the barrel as well as forward.
    let frame, scale = 1, height = 0, extent;
    if (tau < last) {
      let k = 0;
      while (k < n - 2 && P.times[k + 1] <= tau) k++;
      frame = k + clamp((tau - P.times[k]) / (P.times[k + 1] - P.times[k]), 0, 1);
      extent = P.extent[Math.min(Math.ceil(frame), n - 1)];
    } else {
      frame = n;   // the cloud layer
      scale = Math.pow((c.age + tau - last) / c.age, 0.25);
      height = interp(rise.t, rise.h, tau - last);
      const [x0, x1, r] = P.extent[n - 1];
      extent = [c.x + (x0 - c.x) * scale, c.x + (x1 - c.x) * scale, r * scale];
    }
    const dilute = scale ** -3;
    const m = chain(translation(0, height, 0), gT);
    const cx = L.muzzleX + (extent[0] + extent[1]) / 2;
    const centre = [m[0] * cx + m[12], m[1] * cx + m[13], m[2] * cx + m[14]];
    return {
      inverse: chain(translation(-L.muzzleX, 0, 0), invert(m)),
      frame: (frame + 0.5) / P.layers, scale, density: thick * dilute, temperature: dilute,
      origin: c.x, seed, smoke: P.smoke ?? 1,
      bound: [...centre, Math.hypot((extent[1] - extent[0]) / 2, extent[2]) + 10],
      // The flash's light: the solved glow, then the cloud's, falling with its temperature.
      glow: tau < last ? interp(P.times, P.glow, tau)
        : P.glow[n - 1] * Math.exp(-WIEN * (1 / (T_AIR * (1 + c.warmth * dilute)) - 1 / (T_AIR * (1 + c.warmth)))),
      glowX: L.muzzleX + (tau < last ? interp(P.times, P.glow_x, tau) : c.x + (P.glow_x[n - 1] - c.x) * scale),
      size: Math.max(extent[1] - extent[0], extent[2], 20),
    };
  }

  _effects() {
    const L = this.layout, s = this.shot;
    const bore = L.bore;
    const state = { smoke: [], fields: [], gas: null, plume: null, light: null, time: 0 };
    let light = null;
    // The rifle's model matrix at a sim time (recoil, then pitch about the pivot), and its action on points.
    const gunAtT = (t) => {
      const rc = this._actionAt("recoil", t) * 1e3, pc = this._actionAt("pitch", t);
      if (!rc && !pc) return translation(0, 0, 0);
      const [px, py] = L.pivot;
      return chain(translation(-rc, 0, 0), translation(px, py, 0), rotationZ(pc), translation(-px, -py, 0));
    };
    const at = (m, x, y, z) => [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]];
    // A puff that stays in the air where it was put: its body is centred at `centre`, while its trail
    // runs back to its source on the gun as the gun is now.
    const puff = (source, centre) => {
      const d = centre.map((v, i) => v - source[i]), reach = Math.hypot(...d);
      return { origin: source, dir: reach > 1e-6 ? d.map((v) => v / reach) : [0, 1, 0], reach };
    };
    const gT = state.gunModel = this._gunMatrix();
    if (s && this.T >= PIN_FALL && s.plume) {
      const r = s.result, P = s.plume;
      const times = this._shotTimes;
      const k = this._shotAt(this.tSim);
      const local = this.tSim - times[k - 1];
      const exitLocal = r.left_muzzle ? r.muzzle_time : r.time[r.time.length - 1];
      // The gas behind the projectile, then the bore emptying.
      const x1 = local < exitLocal ? L.seat + interp(r.time, r.travel, local) * 1e3 : L.muzzleX;
      const temps = local >= 0 ? this._boreTemps(P, local, exitLocal) : null;
      if (temps) state.gas = { x0: L.head, x1: Math.min(x1, L.muzzleX), temps, boreR: L.boreR, caseR: L.caseInnerR, neckX: L.neckX };

      const exited = times.map((t0) => t0 + exitLocal).filter((te) => r.left_muzzle && this.tSim >= te);
      if (exited.length) {
        state.plume = P;
        const latest = exited[exited.length - 1];
        state.time = this.tSim - latest;
        // The first shot's cloud (thicker for each shot after it) and the latest shot's plume.
        const shown = exited.length > 1 ? [exited[0], latest] : [latest];
        for (const te of shown) {
          const thick = te === latest ? 1 : Math.sqrt(Math.min(exited.length - 1, 4));
          // The gas is left in the air where the muzzle was when it came out.
          state.fields.push(this._plumeAt(P, s.rise, this.tSim - te, gunAtT(te), thick, 3.1 + te * 1e3));
        }
        const f = state.fields[state.fields.length - 1], gE = gunAtT(latest);
        const g = FLASH_LIGHT * f.glow;
        if (g > 0.003) {
          light = { position: at(gE, f.glowX, 0, 0), color: [14 * g, 7 * g, 2.6 * g], range: f.size };
          state.light = { position: light.position, color: [0.6 * g, 0.3 * g, 0.11 * g], range: f.size };
        }
        // What was left in the bore and the device seeps out of the exit afterwards and rises: from the
        // exit as it is now, into a puff that stays above where the muzzle was at exit.
        const age = this.tSim - latest - P.times[P.times.length - 1], tr = P.trickle;
        if (age > 0 && age < SMOKE_LIFE && tr.mass > 0) {
          const out = tr.mass * (1 - Math.exp(-age / tr.tau));
          const R = Math.cbrt(3 * out * SEEP_DILUTION / (4 * Math.PI * 1.2)) * 1e3 + 1.5 * bore + 15 * age;
          const density = out / (4 / 3 * Math.PI * (R * 1e-3) ** 3);
          const exit = at(gE, L.muzzleX + tr.x, 0, 0), up = R * 0.5 + 40 * age;
          state.smoke.push({
            ...puff(at(gT, L.muzzleX + tr.x, 0, 0), [exit[0] + 0.35 * up, exit[1] + 0.94 * up, exit[2]]), radius: R,
            extinction: SMOKE * (P.smoke ?? 1) * density * Math.exp(-age / 2.5), rise: 0, age, group: 0, seed: 7.7, trail: 1,
          });
        }
      }
    }
    for (const w of this.wisps) {
      const r = 1.8 * bore + 14 * w.age, out = 2 * bore + 40 * w.age;
      const port = at(w.gun, L.rearX - 4, 0, 0);
      state.smoke.push({
        ...puff(at(gT, L.rearX - 4, 0, 0), [port[0] - 0.75 * out, port[1] + 0.55 * out + 20 * w.age * w.age, port[2] + 0.37 * out]), radius: r,
        extinction: 0.55 * Math.exp(-w.age / 1.3) * smooth(w.age / 0.15) / r, rise: 0,
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
      muzzle: { x: L.flashX + 24 * L.bore - 0.3 * L.deviceLength, y: 0, width: Math.max(95 * L.bore, 260) + L.deviceLength },
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
    const barrelAt = chain(gunAt, translation(-pose.barrel, 0, 0));   // a short-recoil barrel recoils on its own
    const optional = (mesh, model, material, clip = false) => (mesh ? [{ mesh, model, material, clip }] : []);
    const lv = L.lever;
    const items = [
      { mesh: m.steel, model: gunAt, material: MATERIALS.steel },
      { mesh: m.furniture, model: gunAt, material: MATERIALS.black },
      ...optional(m.wood, gunAt, MATERIALS.wood, true),
      ...optional(m.barrel, barrelAt, MATERIALS.steel, true),
      // The bolt stays whole in the cutaway, so it reads clearly inside the cut receiver.
      { mesh: m.bolt, model: chain(boltAt, rotationX(pose.angle)), material: MATERIALS.bolt, clip: false },
      ...optional(m.shroud, boltAt, MATERIALS.steel),
      // A carrier slides without turning (its bolt head, above, turns in it); a delayed blowback's runs ahead of the head.
      ...optional(m.carrier, chain(gunAt, translation(-pose.carrier, 0, 0)), MATERIALS.steel),
      // A short-recoil locking block drops out of the bolt as the barrel stops; rollers come in; a lever tips back.
      ...optional(m.lock, chain(barrelAt, translation(0, -pose.lock * (L.lockDrop ?? 0), 0)), MATERIALS.bolt),
      ...optional(m.rollerRight, chain(boltAt, translation(0, 0, -pose.lock * (L.rollerIn ?? 0))), MATERIALS.bolt),
      ...optional(m.rollerLeft, chain(boltAt, translation(0, 0, pose.lock * (L.rollerIn ?? 0))), MATERIALS.bolt),
      ...optional(m.lever, lv && chain(boltAt, translation(lv.px, lv.py, 0), rotationZ(pose.lever), translation(-lv.px, -lv.py, 0)), MATERIALS.bolt),
      // The hammer turns on its pin in the receiver.
      ...optional(m.hammer, L.hammer && chain(gunAt, translation(L.hammer.px, L.hammer.py, 0), rotationZ(this._hammerAngle())), MATERIALS.bolt),
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
    if (pose.round) addRound(pose.round.kind, chain(gunAt, translation(pose.round.x, pose.round.y, 0), rotationZ(pose.round.angle ?? 0)));
    // The magazine (dropped out while it is changed), its follower and the rounds left in it; or the belt.
    const F = L.feed, feedState = this._feedState();
    const magAt = chain(gunAt, translation(0, -this._magDrop(), 0));
    if (m.magazine) items.push({ mesh: m.magazine, model: magAt, material: MATERIALS.black });
    if (m.magFollower) items.push({ mesh: m.magFollower, model: chain(magAt, F.follower(this.mag, feedState.lift)), material: MATERIALS.black });
    for (const e of F.rounds(this.mag, feedState.lift, feedState.adv)) {
      const model = chain(magAt, e.m);
      if (e.link) items.push({ mesh: m.link, model, material: MATERIALS.steel });
      if (e.round) addRound("live", model);
    }
    if (F.belt) {
      const frac = F.camFrac(pose.carrier);
      items.push({ mesh: m.feedSlide, model: chain(gunAt, F.slide(frac)), material: MATERIALS.bolt });
      items.push({ mesh: m.feedLever, model: chain(gunAt, F.lever(frac)), material: MATERIALS.bolt });
    }
    for (const e of this.ejected) {
      if (e.kind === "link") {
        items.push({ mesh: m.link, model: chain(translation(...e.pos), rotationX(e.tumble)), material: MATERIALS.steel });
        continue;
      }
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
    const F = this.layout.feed;
    const ammo = ["rounds", `${this.chamber === "live" ? 1 : 0} + ${this.mag} / ${F.capacity} ${F.belt ? "in the belt" : "in the magazine"}`];
    if (!s) {
      const what = this.reload ? (F.belt ? "Loading a new belt" : "Changing the magazine")
        : this.cycle ? "Working the bolt"
        : this.chamber === "jammed" ? `Jammed (${this.jam ?? "feed"}): work the bolt to clear it`
        : this.chamber === "live" ? "Ready: round chambered"
        : this.chamber === "spent" ? "Spent case in the chamber"
        : this.stuck ? "Empty: bolt held open" : this.mag === 0 ? "Empty" : "Chamber empty";
      this.hud.innerHTML = `<b>${what}</b><span>${ammo[0]}</span><span>${ammo[1]}</span>`;
      return;
    }
    const r = s.result;
    let phase, slow;
    if (this.T < PIN_FALL) phase = "Firing pin falls";
    else if (this.exitT === null) phase = this.tSim < 0.05 * r.muzzle_time ? "Ignition" : "Projectile in the bore";
    else if (!s.exited) phase = "Projectile stuck in the bore";
    else if (this.tSim - this.exitT < 0.003) phase = s.plume ? "Muzzle exit: flash" : "Muzzle exit (flash not solved)";
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
      if (s.plume) {
        rows.push(["afterburning", `${(s.plume.afterburn / 1e3).toFixed(1)} kJ`],
                  ["hottest gas", `${s.plume.peak_temperature.toFixed(0)} K`]);
        if ((s.plume.smoke ?? 1) > 1.005) rows.push(["smoke (suppressant)", `×${s.plume.smoke.toFixed(1)}`]);
      }
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
    rows.push(ammo);
    if (this._shotTimes.length > 1 && this.T >= PIN_FALL) {
      rows.unshift(["shot", `${this._shotAt(this.tSim)} of ${this._shotTimes.length}`]);
    }
    this.hud.innerHTML = `<b>${phase}</b>` + rows.map(([k, val]) => `<span>${k}</span><span>${val}</span>`).join("");
  }
}
