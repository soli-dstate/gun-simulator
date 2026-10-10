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
// The whole belt is drawn, as a chain of links under gravity: those in the
// feed tray go where the gun and the feed slide put them, the rest hang from
// the tray's edge to the ground and lie along it, swinging as the gun recoils
// and yanked along a link each shot. A new belt goes in by hand: the top cover
// swings up, what is left of the old belt is pulled out and dropped, the new
// belt's end is laid in across the tray, the cover shuts, and the bolt is
// worked.
//
// Handguns. A pistol's slide is its bolt group: it runs back over the hammer,
// its recoil spring's coils bunching on the guide rod, while a short-recoil
// barrel goes back with it until it unlocks (a Browning barrel's breech
// dropping, a Beretta's locking block falling out of the slide); the trigger
// moves as the shooter pulls it. A revolver's cylinder turns a chamber on as
// its hammer is cocked (by the trigger, or a single action's thumb, before each
// shot) and the fired cases stay in their chambers. Reloading swings the
// cylinder out on its crane, the ejector star throws every case out and a
// speedloader puts the rounds in; or, through a single action's loading gate,
// it is turned a chamber at a time while the ejector rod punches each case out
// and a round goes in. The gas out of the cylinder gap flashes and smokes
// beside the frame.
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

import { beginCycle, cannedCycle, endCycle, loaderDraw, loaderPitch, loaderPose, loaderState, syncState,
         turretPitch } from "./autoloader.js";
import { petalDirection } from "./cartridge.js";
import { buildRifle } from "./gun.js";
import { chain, invert, lookAt, perspective, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { feedCheck } from "./feed.js";
import { rotaryBarrel, rotaryCamera, rotaryDraw, rotaryParts, rotaryPhase, rotaryRows, startRotary, stepRotary } from "./rotary.js";
import { CORE_MATERIALS, ROUND_MATERIALS, Renderer, srgbToLinear } from "./renderer.js";
import { VolumeEffects } from "./volume.js";

const MATERIALS = {
  steel: { color: srgbToLinear([0.2, 0.2, 0.22]), metallic: 1, roughness: 0.36, section: srgbToLinear([0.27, 0.28, 0.3]) },
  bolt: { color: srgbToLinear([0.74, 0.74, 0.76]), metallic: 1, roughness: 0.22, section: srgbToLinear([0.5, 0.5, 0.52]) },
  black: { color: srgbToLinear([0.06, 0.06, 0.065]), metallic: 0.6, roughness: 0.5, section: srgbToLinear([0.2, 0.2, 0.2]) },
  wood: { color: srgbToLinear([0.3, 0.13, 0.06]), metallic: 0, roughness: 0.45, section: srgbToLinear([0.55, 0.34, 0.18]) },
  case: { color: srgbToLinear([0.86, 0.66, 0.34]), metallic: 1, roughness: 0.32, section: srgbToLinear([0.62, 0.45, 0.2]) },
  spent: { color: srgbToLinear([0.7, 0.5, 0.26]), metallic: 1, roughness: 0.48, section: srgbToLinear([0.5, 0.36, 0.17]) },
  ground: { color: srgbToLinear([0.3, 0.28, 0.23]), metallic: 0, roughness: 0.92, section: srgbToLinear([0.36, 0.33, 0.27]) },
  primer: { color: srgbToLinear([0.78, 0.78, 0.76]), metallic: 1, roughness: 0.38, section: srgbToLinear([0.5, 0.5, 0.5]) },
  projectile: { color: srgbToLinear([0.80, 0.47, 0.30]), metallic: 1, roughness: 0.28, section: srgbToLinear([0.55, 0.3, 0.18]) },
  paint: { color: srgbToLinear([0.27, 0.3, 0.2]), metallic: 0.1, roughness: 0.7, section: srgbToLinear([0.35, 0.36, 0.3]) },
  spentSteel: { color: srgbToLinear([0.25, 0.25, 0.23]), metallic: 0.8, roughness: 0.6, section: srgbToLinear([0.4, 0.4, 0.38]) },
  ...ROUND_MATERIALS,
};

const DEFAULT_VIEW = { yaw: -0.42, pitch: 0.22, zoom: 1 };
const PIN_FALL = 0.15;          // s, trigger to ignition
const RAMP_HOLD = 0.0012;       // s of simulation after exit before the clock speeds up
const SMOKE_LIFE = 6;           // s, real time
const CYCLE_DELAY = 0.35;       // s after exit (real time) before the bolt is worked
const CYCLE = { lift: 0.18, back: 0.3, pause: 0.12, forward: 0.32, lower: 0.16 };
const CYCLE_LENGTH = Object.values(CYCLE).reduce((a, b) => a + b, 0);
const RELOAD = { out: 0.45, in: 0.55 };   // s: the empty magazine drops out, a full one goes in
// s: a loader opening a breech that stayed shut (and pulling the case), taking a round from the rack and
// lining it up behind the breech, ramming it, and the block springing shut as its rim trips the extractors.
const LOAD = { open: 0.5, fetch: 1.1, ram: 0.55, close: 0.25 };
const RACK_RELOAD = 1.2;        // s to restock the ready rack (or an autoloader)
// What an autoloader does with the spent case or stub (its events, which the sound plays too): thrown out of a
// hatch, kept by the stub catcher, or thrown out of the rear trapdoor.
const AL_CASE = { az: "the stub is thrown out through the turret's hatch", mz: "the stub catcher takes the stub",
                  oscillating: "the case bangs out through the rear trapdoor" };
const AL_HATCH = [-1400, 3600, 0];  // mm/s: a stub thrown up and back out of the turret's roof
const AL_TRAP = 0.26;           // s a case thrown out of the trapdoor takes to reach it (it is open for 0.32)
const LOAD_GAP = 60;            // mm between the round's tip and the breech as the loader lines it up
const CHAIN_CYCLE = 1.4;        // s to turn a chain gun's chain round once by hand
// Sabot petals, stripped off by the air at the muzzle: they fly out sideways at PETAL_SPREAD of the
// rod's speed, and both their speeds die away over PETAL_TAU, so they fall back behind the rod.
const PETAL_SPREAD = 0.04;
const PETAL_TAU = 0.02;         // s
const PETAL_TURN = 30;          // rad/s they tip outwards at, nose first
const PETAL_LIFE = 0.25;        // s after exit they are drawn for
const BELT_RELOAD = { open: 0.4, lay: 0.9, close: 0.35 };   // s: the cover swings up, a belt is laid in, it shuts
const COVER_OPEN = 1.2;         // rad the top cover swings up
const HAND_IN = 90;             // mm beyond the tray's edge the new belt's end starts from
const BELT_STEP = 1 / 600;      // s, longest step of the belt's chain
const BELT_ITERATIONS = 8;      // constraint passes per step
const BELT_DRAG = 1.5;          // 1/s, the air's damping of the swinging belt
const BELT_BEND = 1.5;          // links two apart stay this many pitches apart: a link only folds so far on the next
const BELT_FRICTION = 0.6;      // coefficient of friction of a link on the ground
const BELT_DROPPED = 2.5;       // s an old belt lies on the ground before it is cleared away
const G_MM = 9810;              // mm/s^2
// Revolvers: display s to cock the hammer (a double-action pull, or a single action's thumb, at least),
// and the steps of a reload: swinging the cylinder out, ejecting, the speedloader, swinging it back;
// or through the loading gate, a chamber at a time.
const COCK = 0.35;
const SWING = { open: 0.45, eject: 0.4, load: 0.7, close: 0.4 };
const GATE = { open: 0.3, turn: 0.22, eject: 0.35, load: 0.4, close: 0.3 };
const CRANE_SWING = 1.25;       // rad the crane swings the cylinder out
const GATE_SWING = 1.3;         // rad the loading gate opens
const GAP_FLASH = 4e-4;         // s (sim) the cylinder gap's flash glows for
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
/** A point under a column-major transform. */
const apply = (m, [x, y, z]) => [0, 1, 2].map((k) => m[k] * x + m[4 + k] * y + m[8 + k] * z + m[12 + k]);
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
    const A = this.rifle?.layout.autoloader;
    this.alS = A ? loaderState(A, this.mag) : null;     // what a tank gun's autoloader holds, and its cycle's round
    this.stuck = null;          // the bolt stopped short after a shot: {travel, round} (held open, or jammed)
    this.jam = null;            // why the round in the chamber is jammed
    this.reload = null;         // {t, swapped}
    this.beltAdv = 0;           // share of a link the belt has been drawn this cycle
    this.belt = null;           // the belt's chain {nodes: [{p, q, pin, local, round}], h}, the link at the feed position first
    this.idleBelt = null;       // a dual feed's other belt, waiting a link out
    this.dropped = [];          // old belts falling out of the gun, {nodes, h, age}
    this.beltMoving = false;
    this.chainQ = 0;            // a chain gun's chain, m round its track from the firing point (between shots)
    this.rotRest = 0;           // a rotary gun's rotor angle (rad) at rest, from the shot before
    // A revolver's cylinder: each chamber "live", "spent" or null; the one under the hammer; how far it has
    // turned (chambers); whether the hammer is cocked. Its hammer starts down: the first pull turns it on.
    const C = this.rifle?.layout.hand?.cyl;
    this.cyl = C ? { state: Array(C.n).fill("live"), at: 0, turn: 0, cocked: false, shotTurn: 0 } : null;
    if (this.cyl) { this.chamber = null; this.mag = C.n; }
  }

  /** The kind of breech: "chain" (a chain gun), "wedge" (a sliding wedge), "revolver", or "bolt" (anything else). */
  get _breech() {
    const k = this.rifle?.layout.mech.kind;
    return k === "chain" ? "chain" : k === "sliding_wedge" ? "wedge" : k === "revolver" ? "revolver" : "bolt";
  }

  /** A revolver's live rounds, in every chamber. */
  _liveCount() { return this.cyl ? this.cyl.state.filter((s) => s === "live").length : 0; }

  /**
   * A revolver: what is ready under the hammer (a live round only once it is cocked: until then the next
   * pull turns another chamber up), and the live rounds besides it, as the simulation counts them.
   */
  _syncCylinder() {
    const c = this.cyl, under = c.state[c.at];
    this.chamber = c.cocked ? under : under === "spent" ? "spent" : null;
    this.mag = this._liveCount() - (this.chamber === "live" ? 1 : 0);
  }

  /** True when a loader puts each round in by hand. */
  get _byHand() { return !!this.rifle?.layout.feed.geo.hand; }

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
    // A rotary gun has no chambered round: the rounds in its belt (or chute), or a fresh one if it has run dry.
    if (this.layout.rotary) return this.mag > 0 ? this.mag : this.layout.feed.capacity;
    if (this.cyl) {
      // The next pull turns a live round up (or a reload fills the cylinder): the rest of them follow it.
      const live = this._liveCount();
      return live > 0 ? live - 1 : this.cyl.state.length - 1;
    }
    if (this.chamber === "live") return this.mag;
    return this.mag > 0 ? this.mag - 1 : this.layout.feed.capacity - 1;
  }

  /** Animate a shot. result: one model's result from the simulate API. */
  fire(result) {
    if (!this.rifle) return;
    this.frozen = false;
    this._alAbort();
    this.shot = null;
    // A rotary gun feeds as it turns: nothing to chamber first (but a reload in progress finishes).
    if (this.layout.rotary) {
      if (this.reload) this.pendingShot = result; else this._startShot(result);
      return;
    }
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
    if (this.cyl) return this._startCylinderReload();
    if (this.layout.rotary && this.shot) return;   // not while a burst is on
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
    // A rotary gun's clock starts at the spin-up, before the first ignition (negative times).
    if (this.layout.rotary) {
      startRotary(this, result);
      if (this.shot.rot) this.tSim = this.shot.rot.time[0];
    }
    const A = this.layout.autoloader, al = result.action?.autoloader;
    if (A) {
      endCycle(A, this.alS, false);
      syncState(A, this.alS, this.mag);
      if (al && al.rounds_before > 0) beginCycle(A, this.alS, al);
    }
    this.stuck = this.jam = null;
    if (this.cyl) {
      // The cocked hammer falls on the round under it; the cylinder turns on from here as the simulation has it.
      this.cyl.cocked = false;
      this.cyl.shotTurn = this.cyl.turn;
    }
    this._kick();
    this.onShot?.(result);
    this.onChange?.();
  }

  /** Work the bolt: eject what's in the chamber (or clear a jam) and load a new round. */
  startCycle() {
    if (this.cycle || this.reload || !this.rifle) return;
    if (this.layout.rotary) return;           // nothing to work by hand: the rotor feeds and clears itself
    if (this._breech === "wedge") return this.layout.autoloader ? this._startAutoLoad() : this._startLoad();
    if (this.cyl) {
      // Cock the hammer: the hand turns the next chamber up under it.
      if (this.cyl.cocked) return;
      this.cycle = { cock: true, t: 0, from: this.cyl.turn, indexed: false };
      this._kick();
      this.onChange?.();
      return;
    }
    if (this._breech === "chain") {
      // The crew turns the chain round once by hand: the bolt draws back, ejects, and rams the next round.
      this.cycle = { chain: true, t: 0, round: this.chamber === "jammed" ? null : this.chamber, ejected: false, fed: false, feeding: false, adv: 0 };
      if (this.chamber === "jammed") this.chamber = null;
      this.stuck = this.jam = null;
      this._kick();
      this.onChange?.();
      return;
    }
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

  /**
   * A loader at a sliding wedge: open the breech if it stayed shut (pulling out what is in it), take a
   * round from the ready rack, line it up behind the breech and ram it; its rim trips the extractors
   * and the block springs shut.
   */
  _startLoad() {
    const open = !!this.stuck?.open;
    this.cycle = { loader: true, t: open ? LOAD.open : 0, round: open ? null : this.chamber, ejected: open, taken: false, feeding: false };
    this.stuck = this.jam = null;
    this._kick();
    this.onChange?.();
  }

  /** Where the round the loader carries is, `f` (0..1) of the way from its rack slot to behind the breech. */
  _fetchMatrix(f) {
    const L = this.layout, F = L.feed;
    const from = F.slot(Math.max(F.capacity - this.mag - 1, 0)), to = apply(this._gunMatrix(), [-(L.oal + LOAD_GAP), 0, 0]);
    const p = [0, 1, 2].map((k) => from[12 + k] + (to[k] - from[12 + k]) * f);
    p[1] += Math.sin(Math.PI * f) * Math.max(3 * L.rimR, 150);   // lifted clear of the rack and the guard
    return translation(...p);
  }

  // ---------- a tank gun's autoloader ----------

  /** The autoloader's cycle of the shot being shown, or null. */
  get _alShot() { return this.shot && this.T >= PIN_FALL ? this.shot.result.action?.autoloader ?? null : null; }

  /** The autoloader cycle being drawn and the time into it: the shot's (on its clock), or a canned one's. */
  get _al() {
    if (this.cycle?.autoload) return { al: this.cycle.al, t: this.cycle.t };
    const al = this._alShot;
    return al && this.alS?.cycle ? { al, t: this.tSim } : null;
  }

  /** When the autoloader takes the spent case or stub away, if it does (the sound's event), else null. */
  _alEjectTime() {
    const A = this.layout.autoloader, al = this._alShot ?? this._action?.autoloader;
    const name = A && AL_CASE[A.type];
    return al && name ? al.events.find((e) => e.name === name)?.time ?? null : null;
  }

  /** How far the autoloader has pitched the gun (rad) to its loading angle, at sim time t of the shot (or a canned cycle's own). */
  _loadPitch(t = this.tSim) {
    const A = this.layout.autoloader;
    if (!A) return 0;
    if (this.cycle?.autoload) return loaderPitch(A, this.cycle.al, this.cycle.t);
    const al = this._alShot;
    return al ? loaderPitch(A, al, t) : 0;
  }

  /** The turret's frame, in which the autoloader is fixed: the gun at its loading angle (the whole upper turret of an oscillating one goes with it). */
  _turretMatrix() {
    const A = this.layout.autoloader, a = A ? turretPitch(A) : 0;
    if (A?.loadAngle === null) return this._mountMatrix();
    if (!a) return translation(0, 0, 0);
    const [px, py] = this.layout.pivot;
    return chain(translation(px, py, 0), rotationZ(a), translation(-px, -py, 0));
  }

  /** The autoloader takes the round from where it has got to (a canned cycle: the breech may be shut on a spent case, or the loader empty). */
  _startAutoLoad() {
    const A = this.layout.autoloader, L = this.layout;
    if (this.chamber === "live" || this.chamber === "jammed") return;
    const open = !this.stuck?.open, empty = this.mag <= 0;
    syncState(A, this.alS, this.mag);
    const al = cannedCycle(A, { open, empty, mag: this.mag });
    this.cycle = { autoload: true, t: 0, al, done: new Set() };
    if (!empty) beginCycle(A, this.alS, al);
    this.stuck = this.jam = null;
    this._kick();
    this.onChange?.();
  }

  _stepAutoLoad(dt) {
    const c = this.cycle, L = this.layout;
    c.t += dt;
    this._alEvents(c.al, c.t, c.done);
    if (c.t < c.al.end) return;
    endCycle(L.autoloader, this.alS, c.al.loaded);
    if (!c.al.loaded) {
      // Nothing to load: the breech is left open.
      this.stuck = { travel: L.stroke, round: null, open: true };
      return this._endCycle(null);
    }
    this._endCycle("live");
  }

  /** Do what the autoloader's events say (cases thrown out, the block shut on the round) as the cycle's clock passes them. */
  _alEvents(al, t, done) {
    const A = this.layout.autoloader, L = this.layout;
    al.events.forEach((e, i) => {
      if (done.has(i) || t < e.time) return;
      done.add(i);
      if (e.name === AL_CASE.az) {
        this._alEject(AL_HATCH);                       // the stub flies up and back out of the roof
      } else if (e.name === AL_CASE.oscillating) {
        // Back through the rear trapdoor: far enough in AL_TRAP s, falling as far as the flap's middle.
        const y = A.flapTop - 0.4 * A.flapH, g = 9810;
        this._alEject([(A.xBack - 30) / AL_TRAP, (y + 0.5 * g * AL_TRAP * AL_TRAP) / AL_TRAP, 0]);
      } else if (e.name === AL_CASE.mz) {
        this.chamber = null;                           // the stub catcher keeps it
      } else if (e.name === "the extractors throw the case") {
        this._alEject([-2500, -400, 0]);
      } else if (e.name === "the block springs shut") {
        if (al.loaded) { this.chamber = "live"; this.pin = 0; this.stuck = null; this.mag = al.rounds_after; }
      }
    });
  }

  _alEject(vel) {
    const recoil = this._actionAt("recoil", this.tSim) * 1e3;
    if (this.chamber === "spent") {
      this.ejected.push({ kind: "spent", pos: [-recoil, 0, 0], vel: [...vel], spin: 0, spinRate: 0, tumble: 0, tumbleRate: -2, age: 0 });
    }
    this.chamber = null;
  }

  /** The shot's autoloader cycle is over: its round is out of its slot (if it loaded). */
  _alFinish(loaded) {
    if (this.layout.autoloader) endCycle(this.layout.autoloader, this.alS, loaded);
    if (this.shot) this.shot.alDone = true;
  }

  /** A new shot (or a hand cycle) comes while the shot's autoloader is still at work: it is taken as done, as far as it was going to get. */
  _alAbort() {
    const al = this._alShot;
    if (!al || !this.alS?.cycle) return;
    if (al.loaded) {
      this.chamber = "live"; this.pin = 0; this.stuck = null; this.mag = al.rounds_after;
      this.shot.done?.add("alEnd");
    }
    this._alFinish(al.loaded);
  }

  /** The autoloader's step of its cycle at tSim, for the readout, once the gun's own run-out is over. */
  _alText() {
    const a = this._action, al = a?.autoloader;
    if (!al || this.tSim <= a.time[a.time.length - 1]) return null;
    if (this.tSim > al.end) return `Smoke · autoloader ${al.loaded ? "loaded" : al.status}`;
    return this._alStage(al, this.tSim);
  }

  _alStage(al, t) {
    const st = al.stages.filter((s) => s.start <= t).pop();
    return st ? `Autoloader: ${st.name}` : "Autoloader";
  }

  /** Where a chain gun's chain is (mm round its track from the firing point): the simulation's, a hand cycle's, or at rest. */
  _chainQ() {
    const a = this._action, c = this.cycle;
    if (c?.chain) return this.layout.chain.track.perimeter * smooth(c.t / CHAIN_CYCLE);
    if (this.shot && a?.drive && this.T >= PIN_FALL) return interp(a.time, a.drive, Math.min(this.tSim, a.time[a.time.length - 1])) * 1e3;
    return this.chainQ;
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
        // A rotary gun's spin-up (before its first ignition) runs in real time; the slow motion starts with the first shot.
        if (this.exitT === null && s.rot && this.tSim < 0) this.rate = 1;
        else if (this.exitT === null || this.tSim < this.exitT + RAMP_HOLD) this.rate = slow;
        else this.rate = Math.min(1, this.rate * Math.exp((this._auto ? RAMP_AUTO : RAMP) * dt));
        const before = this.tSim;
        this.tSim += dt * this.rate;
        if (s.rot && before < 0) this.tSim = Math.min(this.tSim, 0);     // the spin-up ends exactly at the first ignition
        if (!this.frozen) this.onClock?.(this.tSim, this.rate);
        if (!s.fired) {
          s.fired = true;
          this.chamber = "spent";
          if (this.cyl) this.cyl.state[this.cyl.at] = "spent";
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
        // A sliding wedge's breech, opened as the gun ran out, is loaded next. A revolver's hammer is
        // cocked by the next shot's pull.
        // A tank gun's autoloader works through its own cycle (and leaves the breech open if it cannot load); it
        // is only taken up by hand when the breech stayed shut.
        const al = r.action?.autoloader;
        const alOwns = !!L.autoloader && !!al && al.status !== "breech not open";
        if (this.autoCycle && over && !this.cycle && (!this.stuck || this.stuck.open) && after > CYCLE_DELAY
            && this.chamber !== "live" && !s.cycled && !this.cyl && !alOwns && !L.rotary) {
          s.cycled = true;
          this.startCycle();
        }
        if (after > SMOKE_LIFE && !this.cycle && (!al || !this.alS?.cycle || this.tSim >= al.end)) {
          this.shot = null;
          this.onChange?.();
        }
      }
    }

    if (this.cycle?.loader) this._stepLoad(dt);
    else if (this.cycle?.autoload) this._stepAutoLoad(dt);
    else if (this.cycle?.chain) this._stepChainCycle(dt);
    else if (this.cycle?.cock) this._stepCock(dt);
    else if (this.cycle) {
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

    if (this.reload?.cylinder) this._stepCylinderReload(dt);
    else if (this.reload) {
      const r = this.reload;
      r.t += dt;
      const { swap, end } = this._reloadTimes();
      if (!r.swapped && r.t >= swap) {
        r.swapped = true;
        if (L.feed.belt) this._dropBelt();
        this.mag = L.feed.capacity;
        if (L.autoloader) syncState(L.autoloader, this.alS, this.mag);
        this.beltAdv = 0;
      }
      if (r.t >= end) {
        this.reload = null;
        this.onChange?.();
        if (L.rotary) { if (this.pendingShot) this._startShot(this.pendingShot); }
        else if (this.chamber !== "live" && this.chamber !== "jammed") this.startCycle();
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
    if (L.feed.belt) this._stepBelt(dtCase);
    for (const w of this.wisps) w.age += dt;
    this.wisps = this.wisps.filter((w) => w.age < 4);
  }

  /** A hand cycle is over: what is in the chamber now, and fire the shot waiting for it (or reload for it). */
  _endCycle(chamber) {
    this.cycle = null;
    this.pin = 0;
    this.chamber = chamber;
    this.onChange?.();
    if (this.pendingShot) {
      if (this.chamber === "live") this._startShot(this.pendingShot);
      else if (this.mag === 0) this.startReload();
      else this.pendingShot = null;
    }
  }

  _stepLoad(dt) {
    const c = this.cycle, L = this.layout;
    c.t += dt;
    if (!c.ejected && c.t >= LOAD.open) {
      // The loader has opened the breech by hand: the extractors throw out what was in it.
      c.ejected = true;
      if (c.round && c.round !== "live") this.ejected.push({ kind: c.round, pos: [-20, 0, 0], vel: [-2500, -400, 0], spin: 0, spinRate: 0, tumble: 0, tumbleRate: -2, age: 0 });
      else if (c.round === "live") this.mag = Math.min(this.mag + 1, L.feed.capacity);   // an unfired round goes back in the rack
      this.chamber = null;
    }
    if (!c.taken && c.t >= LOAD.open) {
      c.taken = true;
      if (this.mag > 0) { this.mag--; c.feeding = true; }
    }
    if (!c.feeding && c.t >= LOAD.open) {
      // The rack is empty: the breech is left open.
      this.stuck = { travel: L.stroke, round: null, open: true };
      return this._endCycle(null);
    }
    if (c.t >= LOAD.open + LOAD.fetch + LOAD.ram + LOAD.close) this._endCycle("live");
  }

  _stepChainCycle(dt) {
    const c = this.cycle, L = this.layout, F = L.feed, tr = L.chain.track;
    c.t += dt;
    const q = this._chainQ(), s = tr.at(q).s;
    if (!c.ejected && s >= L.caseLength + 3) {
      c.ejected = true;
      if (c.round) this.ejected.push({ kind: c.round, pos: [-s, -0.5 * L.boltR, 0], vel: [1800, -1400, 150], spin: 0, spinRate: -6, tumble: 0, tumbleRate: 4, age: 0 });
      this.chamber = null;
    }
    // Across the back of the track the feeder draws the belt a link; leaving it, the bolt strips the round.
    if (F.belt && q > tr.rearStart) c.adv = this.beltAdv = clamp((q - tr.rearStart) / Math.max(tr.rearLength, 1e-6), 0, 1);
    if (!c.fed && q > tr.rearStart + tr.rearLength) {
      c.fed = true;
      if (this.mag > 0) {
        this.mag--;
        c.feeding = true;
        if (F.belt) this._shedLink();
        this.beltAdv = 0;
      }
    }
    if (c.t >= CHAIN_CYCLE) {
      this.chainQ = 0;
      this._endCycle(c.feeding ? "live" : null);
    }
  }

  // ---------- a revolver's cylinder ----------

  /** Display s to cock the hammer: the trigger's double-action pull or the thumb, slowed enough to see. */
  get _cockTime() { return Math.max(COCK, 2.5 * (this.layout.hand?.trigger.pullTime ?? 0.12)); }

  /** Cocking the hammer: the hand turns the cylinder a chamber on over the middle of its swing. */
  _stepCock(dt) {
    const c = this.cycle, C = this.layout.hand.cyl;
    c.t += dt;
    if (!c.indexed && c.t >= C.index[1] * this._cockTime) {
      c.indexed = true;
      this.cyl.at = (this.cyl.at + 1) % C.n;
      this.cyl.turn = c.from + 1;
    }
    if (c.t >= this._cockTime) {
      this.cyl.cocked = true;
      this._syncCylinder();
      this._endCycle(this.chamber);
    }
  }

  /** Reload the cylinder: swing it out, eject and speedload, or through the gate a chamber at a time. */
  _startCylinderReload() {
    const C = this.layout.hand.cyl, c = this.cyl, steps = [];
    if (C.loading === "gate") {
      steps.push({ name: "open", d: GATE.open });
      for (let i = 1; i <= C.n; i++) {
        const k = (c.at + i) % C.n;
        if (c.state[k] === "live") continue;
        steps.push({ name: "turn", d: GATE.turn, k });
        if (c.state[k] === "spent") steps.push({ name: "eject", d: GATE.eject, k });
        steps.push({ name: "load", d: GATE.load, k });
      }
      steps.push({ name: "close", d: GATE.close });
    } else {
      for (const [name, d] of Object.entries(SWING)) steps.push({ name, d });
    }
    c.cocked = false;
    this.reload = { cylinder: true, t: 0, step: 0, steps };
    this._kick();
    this.onChange?.();
  }

  _stepCylinderReload(dt) {
    const r = this.reload, c = this.cyl, C = this.layout.hand.cyl, n = C.n;
    r.t += dt;
    while (r.step < r.steps.length) {
      const s = r.steps[r.step];
      if (s.name === "turn" && s.from === undefined) {
        // Turn on (the way the hand turns it) until chamber k is at the gate.
        s.from = c.turn;
        let to = s.k - (C.gateAngle * n) / (2 * Math.PI);
        while (to < s.from - 1e-6) to += n;
        s.to = to;
      }
      if (r.t < s.d) break;
      r.t -= s.d;
      this._finishReloadStep(s);
      r.step++;
    }
    if (r.step >= r.steps.length) {
      this.reload = null;
      this._syncCylinder();
      this.onChange?.();
      if (this.pendingShot) this._prepare();
    }
  }

  /** What a step of the reload leaves behind: cases thrown out, rounds in, the cylinder turned. */
  _finishReloadStep(s) {
    const c = this.cyl, C = this.layout.hand.cyl, n = C.n;
    const fling = (k, vel) => {
      if (!c.state[k]) return;
      const p = apply(this._chamberMatrix(this._cylMatrix(this._cylPose()).cyl, k), [0, 0, 0]);
      this.ejected.push({ kind: c.state[k], pos: p, vel, spin: 0, spinRate: 0, tumble: 0, tumbleRate: -3 - Math.random() * 3, age: 0 });
      c.state[k] = null;
    };
    if (s.name === "eject" && s.k !== undefined) fling(s.k, [-500, -200, 700]);              // out of the gate
    else if (s.name === "eject") for (let k = 0; k < n; k++) fling(k, [-700 - 200 * Math.random(), -400, -100]);   // off the star
    else if (s.name === "load" && s.k !== undefined) c.state[s.k] = "live";
    else if (s.name === "load") c.state.fill("live");
    else if (s.name === "turn") c.turn = s.to;
    else if (s.name === "close" && C.loading === "gate") {
      // Out of the loading notch: a chamber comes up under the hammer.
      c.turn = Math.ceil(c.turn - 1e-6);
      c.at = ((c.turn % n) + n) % n;
    }
  }

  /**
   * Where the cylinder is: {turn (chambers), swing (0 shut .. 1 out on its crane), gate (0..1 open), star (mm
   * the ejector star pushes every case back), rod (0..1, a single action's ejector rod punching), round: {k:
   * {dx, dr}} rounds moved from their chambers (back along the bore, out from the axis), incoming: [k...]}.
   */
  _cylPose() {
    const c = this.cyl, C = this.layout.hand.cyl, L = this.layout;
    const pose = { turn: c.turn, swing: 0, gate: 0, star: 0, rod: 0, round: {}, incoming: [] };
    const cy = this.cycle, a = this._action;
    if (cy?.cock) {
      const [i0, i1] = C.index, f = cy.t / this._cockTime;
      pose.turn = cy.indexed ? c.turn : cy.from + clamp((f - i0) / (i1 - i0), 0, 1);
      return pose;
    }
    if (this.shot && this._auto && this.T >= PIN_FALL && a?.cylinder?.length) {
      pose.turn = c.shotTurn + interp(a.time, a.cylinder, Math.min(this.tSim, a.time[a.time.length - 1]));
      return pose;
    }
    const r = this.reload;
    if (!r?.cylinder) return pose;
    const s = r.steps[Math.min(r.step, r.steps.length - 1)], f = clamp(r.t / s.d, 0, 1), e = smooth(f);
    if (C.loading === "gate") {
      pose.gate = s.name === "open" ? e : s.name === "close" ? 1 - e : 1;
      if (s.name === "turn" && s.from !== undefined) pose.turn = s.from + (s.to - s.from) * e;
      if (s.name === "eject") { pose.rod = Math.sin(Math.PI * f); pose.round[s.k] = { dx: -Math.min(f * 2, 1) * (L.caseLength + 6), dr: 0 }; }
      if (s.name === "load") { pose.incoming.push(s.k); pose.round[s.k] = { dx: -(L.oal + 20) * (1 - e), dr: 14 * (1 - e) }; }
    } else {
      pose.swing = s.name === "open" ? e : s.name === "close" ? 1 - e : 1;
      if (s.name === "eject") pose.star = Math.sin(Math.PI * f) * 0.8 * L.caseLength;
      if (s.name === "load") {
        for (let k = 0; k < C.n; k++) { pose.incoming.push(k); pose.round[k] = { dx: -(L.oal + 40) * (1 - e), dr: 0 }; }
      }
    }
    return pose;
  }

  /** The cylinder's axis (swung out on its crane, if it is) and the cylinder turned on it. */
  _cylMatrix(pose, gunAt = this._gunMatrix()) {
    const C = this.layout.hand.cyl;
    let axis = gunAt;
    if (pose.swing && C.crane) {
      axis = chain(gunAt, translation(0, C.crane.y, C.crane.z), rotationX(-CRANE_SWING * pose.swing),
                   translation(0, -C.crane.y, -C.crane.z));
    }
    axis = chain(axis, translation(0, -C.rC, 0));
    return { axis, cyl: chain(axis, rotationX((-pose.turn * 2 * Math.PI) / C.n)) };
  }

  /** Chamber k's round (its case head at the origin), moved dx back along it and dr out from the axis. */
  _chamberMatrix(cyl, k, dx = 0, dr = 0) {
    const C = this.layout.hand.cyl, a = (k * 2 * Math.PI) / C.n, r = C.rC + dr;
    return chain(cyl, translation(dx, r * Math.cos(a), r * Math.sin(a)));
  }

  /** Follow the simulation's string of shots: each fires the chamber under the hammer, each cocking turns the next up. */
  _stepRevolverAction() {
    const s = this.shot, a = this._action, t = this.tSim, c = this.cyl;
    s.done ??= new Set();
    const once = (key, at, fn) => { if (!s.done.has(key) && t >= at) { s.done.add(key); fn(); } };
    this._shotTimes.forEach((t0, i) => {
      if (i) once(`fire${i + 1}`, t0, () => { c.state[c.at] = "spent"; c.cocked = false; this._syncCylinder(); this.pin = 1; });
    });
    a.events.forEach((e, i) => {
      if (e.name === "cylinder locks") {
        once(`lock${i}`, e.time, () => { c.at = (c.at + 1) % c.state.length; c.cocked = true; this._syncCylinder(); });
      }
    });
    once("end", a.time[a.time.length - 1], () => {
      c.turn = c.shotTurn + (a.cylinder?.[a.cylinder.length - 1] ?? 0);
      c.cocked = false;
      this._syncCylinder();
    });
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
    // A bolt held open or jammed stays where it stopped, as does a sliding wedge's block (held open by
    // the extractors, or stuck part open); the rest settles home.
    if (key === "bolt" && (a.held_open || a.jam || a.kind === "sliding_wedge")) return v;
    return t > end ? v * (1 - smooth((t - end) / SETTLE)) : v;
  }

  /** Where the rifle is: recoil (mm back) and pitch (rad, muzzle up) about the shoulder. */
  _gunPose() {
    return { recoil: this._actionAt("recoil", this.tSim) * 1e3, pitch: this._actionAt("pitch", this.tSim) + this._loadPitch() };
  }

  _gunMatrix() {
    const { recoil, pitch } = this._gunPose();
    if (!recoil && !pitch) return translation(0, 0, 0);
    const [px, py] = this.layout.pivot;
    return chain(translation(-recoil, 0, 0), translation(px, py, 0), rotationZ(pitch), translation(-px, -py, 0));
  }

  /** A mount's cradle: it pitches about the trunnions with the gun, but the gun recoils in it. */
  _mountMatrix() {
    const pitch = this._actionAt("pitch", this.tSim) + this._loadPitch();
    if (!pitch) return translation(0, 0, 0);
    const [px, py] = this.layout.pivot;
    return chain(translation(px, py, 0), rotationZ(pitch), translation(-px, -py, 0));
  }

  /**
   * The sabot's petals of every shot that has left the muzzle in the last PETAL_LIFE: per shot, a model
   * per petal. Each flies out from the axis and tips outwards, nose first, as the air strips it off,
   * and both its speeds die away over PETAL_TAU.
   */
  _petals() {
    const s = this.shot, r = s?.result, L = this.layout, R = L.round, out = [];
    if (!r?.left_muzzle) return out;
    const v = r.muzzle_velocity * 1e3, len = R.sabotLength ?? 0;
    for (const t0 of this._shotTimes) {
      const tau = this.tSim - t0 - r.muzzle_time;
      if (tau <= 0 || tau > PETAL_LIFE) continue;
      const gone = PETAL_TAU * (1 - Math.exp(-tau / PETAL_TAU));
      const x = L.muzzleX - this._actionAt("recoil", t0 + r.muzzle_time) * 1e3 + v * gone;
      const spread = PETAL_SPREAD * v * gone, tilt = Math.min(PETAL_TURN * tau, 1.4);
      const models = [];
      for (let k = 0; k < R.petals; k++) {
        const [cy, cz] = petalDirection(k, R.petals), a = Math.atan2(cz, cy);
        models.push(chain(translation(x, 0, 0), rotationX(a), translation(len / 2, spread, 0), rotationZ(tilt),
                          translation(-len / 2, 0, 0), rotationX(-a)));
      }
      out.push(models);
    }
    return out;
  }

  /** Fire, eject and chamber when the action simulation says so, shot by shot. */
  _stepAutoAction() {
    if (this.cyl) return this._stepRevolverAction();
    if (this.layout.rotary) return stepRotary(this);
    const s = this.shot, a = this._action, t = this.tSim;
    s.done ??= new Set();
    const once = (key, at, fn) => { if (!s.done.has(key) && t >= at) { s.done.add(key); fn(); } };
    this._shotTimes.forEach((t0, i) => {
      const k = i + 1;
      if (k > 1) once(`fire${k}`, t0, () => { this.chamber = "spent"; this.pin = 1; });
      once(`eject${k}`, this._eventTime("case ejected", k), () => {
        const bolt = this._actionAt("bolt", t) * 1e3, recoil = this._actionAt("recoil", t) * 1e3;
        const speed = (interp(a.time, a.bolt_velocity, t) + interp(a.time, a.recoil_velocity, t)) * 1e3;  // mm/s
        const breech = this._breech;
        // An autoloader that takes the case away does it later (its event), out of its hatch, trapdoor or catcher.
        const taken = this._alEjectTime() !== null;
        if (breech === "wedge") {
          // The extractors flick the case (or a combustible case's stub) straight back out of the breech,
          // down into the bag; without the evacuator sweeping the bore, fumes come out after it.
          const out = (a.case_speed ?? 2) * 1e3;
          if (!taken) this.ejected.push({ kind: "spent", pos: [-recoil, 0, 0], vel: [-out, -0.08 * out, 0], spin: 0, spinRate: 0, tumble: 0, tumbleRate: -1.5, age: 0 });
          if (!this.shot.result.evacuator?.clear) this.wisps.push({ age: 0, gun: this._gunMatrix() });
        } else if (breech === "chain") {
          // A chain gun throws its cases forwards and down, out of the bottom of the receiver.
          this.ejected.push({ kind: "spent", pos: [-bolt - recoil, -0.5 * this.layout.boltR, 0], vel: [2200 + 0.3 * speed, -1500, 150],
                              spin: 0, spinRate: -8, tumble: 0, tumbleRate: 6, age: 0 });
        } else {
          this.ejected.push({
            kind: "spent", pos: [-bolt - recoil, 0, 0],
            vel: [-0.5 * speed, 1500 + 0.05 * speed, 2600 + 0.15 * speed],
            spin: 0, spinRate: -40, tumble: 0, tumbleRate: 18, age: 0,
          });
        }
        if (!taken) this.chamber = null;
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
      } else if (a.kind === "sliding_wedge" && a.open_time !== null) {
        // The breech is held open on the extractors for the loader.
        this.stuck = { travel: a.bolt[a.bolt.length - 1] * 1e3, round: null, open: true };
        if (this._alEjectTime() === null) this.chamber = null;
      }
    });
    // A tank gun's autoloader carries on from here, on the same clock.
    const al = a.autoloader;
    if (al && this.layout.autoloader) {
      this._alEvents(al, t, (s.alEvents ??= new Set()));
      once("alEnd", al.end, () => this._alFinish(al.loaded));
    }
  }

  /** An empty link falls out of the right of the feed tray. */
  _shedLink() {
    const F = this.layout.feed, [x, y, z] = F.ejectLink(), recoil = this._actionAt("recoil", this.tSim) * 1e3;
    this.ejected.push({ kind: "link", pos: [x - recoil, y, z], vel: [0, 200, 900], spin: 0, spinRate: 0, tumble: 0, tumbleRate: 8, age: 0 });
  }

  // ---------- the belt ----------

  /** When a reload swaps the ammunition, and when it is over (display s). */
  _reloadTimes() {
    const B = BELT_RELOAD;
    if (this.layout.feed.belt) return { swap: B.open, end: B.open + B.lay + B.close };
    if (this._byHand || this.layout.autoloader) return { swap: RACK_RELOAD / 2, end: RACK_RELOAD };
    return { swap: RELOAD.out, end: RELOAD.out + RELOAD.in };
  }

  /** How far the top cover is swung up (rad): open while a belt is changed. */
  _coverAngle() {
    const r = this.reload, B = BELT_RELOAD;
    if (!r || !this.layout.feed.belt) return 0;
    if (r.t < B.open) return COVER_OPEN * smooth(r.t / B.open);
    if (r.t < B.open + B.lay) return COVER_OPEN;
    return COVER_OPEN * (1 - smooth((r.t - B.open - B.lay) / B.close));
  }

  /** How far short of the feed position (mm) the new belt's end is, as it is laid in across the tray. */
  _layOffset() {
    const r = this.reload, B = BELT_RELOAD, F = this.layout.feed;
    if (!r || !r.swapped || !F.belt) return 0;
    return (F.trayLen + HAND_IN) * (1 - smooth((r.t - B.open) / (0.85 * B.lay)));
  }

  /**
   * Link i of the belt (0 at the feed position): whether it is held (in the tray, or in the hand) and where, in the
   * gun's frame. A dual feed's idle belt waits on the other side, its first round a link out from the feed position.
   */
  _beltSlot(i, adv, lay, idle = false) {
    const F = this.layout.feed;
    if (idle) {
      const u = (i + 1) * F.pitch;
      return { pin: u <= F.trayLen + 1e-6, local: F.point(u, -F.feedSide) };
    }
    const u = (i - adv) * F.pitch + lay;
    return { pin: u <= F.trayLen + 1e-6 || (lay > 0 && i === 0), local: F.point(u) };
  }

  /** A belt as it is put in: its held links in place, the rest hanging from the last of them to the ground and lying along it. */
  _newBelt(idle = false) {
    const F = this.layout.feed, M = this._gunMatrix(), adv = this._feedState().adv, lay = this._layOffset();
    const side = idle ? -F.feedSide : F.feedSide, count = idle ? F.capacity : this.mag + 1;
    const nodes = [];
    for (let i = 0; i < count; i++) {
      const s = this._beltSlot(i, adv, lay, idle);
      let p;
      if (s.pin || !nodes.length) {
        p = apply(M, s.local);
      } else {
        const [x, y, z] = nodes[i - 1].p, drop = y - F.rest;
        if (drop >= F.pitch) p = [x, y - F.pitch, z];
        else if (drop > 0) p = [x, F.rest, z + side * Math.sqrt(F.pitch ** 2 - drop ** 2)];
        else p = [x, F.rest, z + side * F.pitch];
      }
      nodes.push({ p, q: p.slice(), pin: s.pin, local: s.local, round: idle || i > 0 });
    }
    return { nodes, h: 0, idle };
  }

  /** Keep the chain to the rounds in the belt: a stripped link leaves it (it is shed), a new belt replaces it. */
  _beltSync() {
    const n = this.mag + 1;
    if (!this.belt || this.belt.nodes.length < n) this.belt = this._newBelt();
    while (this.belt.nodes.length > n) this.belt.nodes.shift();
    if (this.layout.feed.sides?.length > 1 && !this.idleBelt) this.idleBelt = this._newBelt(true);
  }

  /** Every belt's chain: the feeding one, a dual feed's idle one, and old ones falling away. */
  get _belts() { return [this.belt, ...(this.idleBelt ? [this.idleBelt] : []), ...this.dropped]; }

  /** What is left of the old belt is pulled out to the left and dropped. */
  _dropBelt() {
    const b = this.belt, h = BELT_STEP;
    this.belt = null;
    if (!b) return;
    const side = this.layout.feed.feedSide ?? -1;
    for (const n of b.nodes) {
      n.pin = false;
      n.q = [n.p[0], n.p[1] - 250 * h, n.p[2] - side * 700 * h];     // up and out to its side
    }
    this.dropped.push({ nodes: b.nodes, h, age: 0 });
  }

  /** Swing the belt (and any old one falling away) on through dt s. */
  _stepBelt(dt) {
    this._beltSync();
    const M = this._gunMatrix(), adv = this._feedState().adv, lay = this._layOffset();
    for (const belt of [this.belt, this.idleBelt]) {
      belt?.nodes.forEach((n, i) => {
        const s = this._beltSlot(i, adv, lay, belt.idle);
        n.pin = s.pin;
        n.local = s.local;
        n.from = n.p.slice();
        n.to = s.pin ? apply(M, s.local) : null;
      });
    }
    for (const c of this.dropped) c.age += dt;
    this.dropped = this.dropped.filter((c) => c.age < BELT_DROPPED);
    if (dt <= 0) return;
    const steps = Math.min(Math.ceil(dt / BELT_STEP), 40), h = dt / steps;
    let fastest = 0;
    for (let k = 1; k <= steps; k++) {
      for (const c of this._belts) fastest = Math.max(fastest, this._beltStep(c, h, k / steps));
    }
    this.beltMoving = fastest > 1 || this.dropped.length > 0;
  }

  /**
   * One step of h s of a chain (Verlet): free links fall and swing on, held ones move `w` of the way
   * to where they are put this frame; then the links are kept a pitch apart, folded no tighter than
   * a link allows, and on the ground. Returns the fastest free link's speed (mm/s).
   */
  _beltStep(c, h, w) {
    const F = this.layout.feed, nodes = c.nodes, rest = F.rest;
    const scale = c.h ? h / c.h : 1, damp = Math.exp(-BELT_DRAG * h), fall = G_MM * h * h;
    c.h = h;
    for (const n of nodes) {
      const { p, q } = n;
      if (n.pin) {
        for (let k = 0; k < 3; k++) { q[k] = p[k]; p[k] = n.from[k] + (n.to[k] - n.from[k]) * w; }
        continue;
      }
      for (let k = 0; k < 3; k++) { const v = (p[k] - q[k]) * scale * damp; q[k] = p[k]; p[k] += v; }
      p[1] -= fall;
    }
    const keep = (a, b, len, apart) => {
      const wa = a.pin ? 0 : 1, wb = b.pin ? 0 : 1;
      if (!wa && !wb) return;
      const dx = b.p[0] - a.p[0], dy = b.p[1] - a.p[1], dz = b.p[2] - a.p[2], dist = Math.hypot(dx, dy, dz) || 1e-9;
      if (apart && dist >= len) return;
      const f = (dist - len) / dist / (wa + wb);
      a.p[0] += wa * f * dx; a.p[1] += wa * f * dy; a.p[2] += wa * f * dz;
      b.p[0] -= wb * f * dx; b.p[1] -= wb * f * dy; b.p[2] -= wb * f * dz;
    };
    const bend = BELT_BEND * F.pitch, grip = BELT_FRICTION * fall;
    for (let it = 0; it < BELT_ITERATIONS; it++) {
      // From the held end down, so a pull runs along the whole belt in one pass.
      for (let i = 0; i + 1 < nodes.length; i++) keep(nodes[i], nodes[i + 1], F.pitch, false);
      for (let i = 0; i + 2 < nodes.length; i++) keep(nodes[i], nodes[i + 2], bend, true);
      for (const n of nodes) {
        const { p, q } = n;
        if (n.pin || p[1] > rest) continue;
        // On the ground: it does not bounce, and its weight holds it (Coulomb friction): it
        // stays put unless pulled harder than that, and then loses that much of its slide.
        p[1] = rest;
        q[1] = Math.max(q[1], rest);
        const dx = p[0] - q[0], dz = p[2] - q[2], slide = Math.hypot(dx, dz);
        const keepShare = slide > grip ? 1 - grip / slide : 0;
        p[0] = q[0] + dx * keepShare;
        p[2] = q[2] + dz * keepShare;
      }
    }
    let fastest = 0;
    for (const n of nodes) {
      if (!n.pin) fastest = Math.max(fastest, Math.hypot(n.p[0] - n.q[0], n.p[1] - n.q[1], n.p[2] - n.q[2]) / h);
    }
    return fastest;
  }

  /** A free link's frame: its rounds lie along the gun's bore as near as the belt's run across them lets them. */
  _linkFrame(nodes, i, gunAt) {
    const a = nodes[Math.max(i - 1, 0)].p, b = nodes[Math.min(i + 1, nodes.length - 1)].p, p = nodes[i].p;
    let Z = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];          // the belt runs on along -z
    const zl = Math.hypot(...Z);
    Z = zl > 1e-6 ? Z.map((v) => v / zl) : [0, 0, 1];
    let X = [gunAt[0], gunAt[1], gunAt[2]];
    const xz = X[0] * Z[0] + X[1] * Z[1] + X[2] * Z[2];
    X = X.map((v, k) => v - xz * Z[k]);
    const xl = Math.hypot(...X);
    X = xl > 1e-6 ? X.map((v) => v / xl) : [1, 0, 0];
    const Y = [Z[1] * X[2] - Z[2] * X[1], Z[2] * X[0] - Z[0] * X[2], Z[0] * X[1] - Z[1] * X[0]];
    return new Float32Array([...X, 0, ...Y, 0, ...Z, 0, ...p, 1]);
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
    if (!r || this.layout.feed.belt || this.layout.autoloader) return 0;
    const far = (this.layout.feed.depth ?? 0) + 120;
    return r.t < RELOAD.out ? far * smooth(r.t / RELOAD.out) : far * (1 - smooth((r.t - RELOAD.out) / RELOAD.in));
  }

  /** Bolt pose of an automatic action at the shot's clock. */
  _autoBoltPose() {
    const L = this.layout, a = this._action, t = this.tSim;
    const k = this._shotAt(t);
    let travel = this._actionAt("bolt", t) * 1e3;
    // Once the run-out is over, a tank gun's autoloader has the block: it springs shut as the rounds go in.
    const al = this._alShot;
    if (al && this._breech === "wedge" && t > a.time[a.time.length - 1]) {
      travel = a.bolt[a.bolt.length - 1] * 1e3 * loaderPose(L.autoloader, al, t).block;
    }
    // The simulation's own unlock travel and delay ratio, which the parts that follow the bolt use.
    const s = a.strokes;
    const mech = { ...L.mech, unlock: s.unlock * 1e3, ratio: s.carrier_unlock ? s.carrier_unlock / s.unlock : L.mech.ratio };
    const { angle, ...follow } = this._mechPose(travel, mech);
    let round = null;
    const jammed = a.jam && a.jam.shot === k;
    if (t < (this._alEjectTime() ?? this._eventTime("case ejected", k))) {
      // A sliding wedge drops away from the case, which stays in the chamber until the extractors throw it.
      if (this.chamber && this.chamber !== "jammed") round = { kind: this.chamber, x: this._breech === "wedge" ? 0 : -travel, y: 0 };
    } else if (!jammed && t >= this._eventTime("back in battery", k)) {
      round = { kind: "live", x: 0, y: 0 };
    } else if (t >= this._eventTime("strips the next round", k)) {
      round = this._feedingRound(travel);
    } else if (this.shot?.alDone && this.chamber === "live") {
      round = { kind: "live", x: 0, y: 0 };            // the autoloader's round, in the chamber (it is drawn with the autoloader until then)
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
    if (mech.kind === "gas" || mech.kind === "direct_impingement" || mech.kind === "chain") {
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
    if (this.cycle?.cock) return sear * smooth(Math.min(this.cycle.t / this._cockTime, 1));
    // A revolver's hammer rests down on the chamber it fired, until it is cocked again; so does a
    // double-action-only hammer, which nothing leaves cocked.
    const down = (this.cyl && !this.cyl.cocked) || this.layout.hand?.trigger.type === "double_action_only";
    if (!this.shot) return down ? 0 : sear;
    if (this.T < PIN_FALL) return sear * (1 - this.pin);
    if (!a?.hammer) return 0;
    return interp(a.time, a.hammer, Math.min(this.tSim, a.time[a.time.length - 1]));
  }

  /**
   * How far a handgun's trigger is pulled (mm): held through each shot's pull until just after it fires. A
   * double-action pull draws it back as the hammer comes; before a thumb-cocked shot it is only pressed at the end.
   */
  _triggerTravel() {
    const H = this.layout.hand;
    if (!H) return 0;
    const T = H.trigger, double = T.type === "double_action_only" || (this.cyl && T.type === "double_action");
    const full = double ? T.da : T.travel;
    if (this.cycle?.cock) return T.type === "single_action" ? 0 : full * smooth(Math.min(this.cycle.t / this._cockTime, 1));
    const s = this.shot;
    if (!s) return 0;
    if (this.T < PIN_FALL) return full;
    const a = this._action, t = this.tSim, times = this._shotTimes;
    if (!a) return t < 0.06 ? full : 0;
    for (let k = 1; k <= times.length; k++) {
      const t0 = times[k - 1];
      if (k === 1) { if (t <= t0 + 0.06) return full; continue; }
      const p = a.events.find((e) => e.shot === k - 1 && (e.name === "trigger pulled" || e.name === "hammer cocked by the thumb"));
      if (!p || t < p.time || t > t0 + 0.06) continue;
      const r = a.events.find((e) => e.shot === k - 1 && (e.name === "hammer released" || e.name === "striker released")) ?? p;
      if (t >= r.time) return full;
      return p.name === "hammer cocked by the thumb" ? 0 : full * smooth((t - p.time) / Math.max(r.time - p.time, 1e-6));
    }
    return 0;
  }

  get animating() {
    return this.shot || this.cycle || this.reload || this.ejected.length || this.wisps.length || this.beltMoving;
  }

  /** Bolt pose: {travel (mm back), angle (rad)} and the round riding on the bolt face. */
  _boltPose() {
    const L = this.layout;
    const c = this.cycle;
    // A revolver's rounds are in its cylinder (drawn with it); nothing slides.
    if (this.cyl || L.rotary) return { travel: 0, round: null, ...this._mechPose(0) };
    // Once the bolt has been worked by hand (or a wedge loaded), it is where that left it, not where the shot did.
    if (!c && this._auto && !this.shot?.cycled) return this._autoBoltPose();
    if (!c) {
      // Shut, or stopped short after the shot: held open on an empty magazine, or on a jammed round.
      const travel = this.stuck?.travel ?? 0;
      const round = this.stuck ? this.stuck.round : this.chamber ? { kind: this.chamber, x: 0, y: 0 } : null;
      return { travel, round, ...this._mechPose(travel) };
    }
    if (c.loader) return this._loadPose();
    if (c.autoload) {
      // A tank gun's autoloader: the block's drop (1 open .. 0 shut) as its cycle has it; what it rams is drawn with it.
      const travel = L.stroke * loaderPose(L.autoloader, c.al, c.t).block;
      return { travel, round: this.chamber === "spent" ? { kind: "spent", x: 0, y: 0 } : null, ...this._mechPose(travel) };
    }
    if (c.chain) {
      // Turning the chain by hand: the bolt follows the track.
      const travel = L.chain.track.at(this._chainQ()).s;
      let round = null;
      if (!c.ejected && c.round) round = { kind: c.round, x: -travel, y: 0 };
      else if (c.feeding) round = c.t >= CHAIN_CYCLE * 0.98 ? { kind: "live", x: 0, y: 0 } : this._feedingRound(travel);
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

  /** The loader at a sliding wedge: the block's drop, and the round on its way from the rack into the chamber. */
  _loadPose() {
    const L = this.layout, c = this.cycle, t = c.t, { open, fetch, ram, close } = LOAD;
    let travel = L.stroke, round = null;
    if (t < open) {
      travel = L.stroke * smooth(t / open);
      if (c.round) round = { kind: c.round, x: 0, y: 0 };
    } else if (t < open + fetch) {
      if (c.feeding) round = { kind: "live", world: this._fetchMatrix(smooth((t - open) / fetch)) };
    } else if (t < open + fetch + ram) {
      round = { kind: "live", x: -(L.oal + LOAD_GAP) * (1 - smooth((t - open - fetch) / ram)), y: 0 };
    } else {
      travel = L.stroke * (1 - smooth((t - open - fetch - ram) / close));
      round = { kind: "live", x: 0, y: 0 };
    }
    return { travel, round, ...this._mechPose(travel) };
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
    const times = this._shotTimes;
    for (let j = 0; j < times.length; j++) {
      const t0 = times[j], local = this.tSim - t0;
      if (local < 0) break;
      // Long gone (a burst of hundreds has most of its rounds far down range).
      if (r.left_muzzle && local > r.muzzle_time + Math.max(4000, 60 * L.bore) / (r.muzzle_velocity * 1e3)) continue;
      // Still inside a muzzle device: it moves with the gun, like the gas filling the device.
      const inDevice = r.left_muzzle && local > r.muzzle_time
        ? L.muzzleX + r.muzzle_velocity * (local - r.muzzle_time) * 1e3 : null;
      if (inDevice !== null && inDevice < L.flashX) {
        out.push({ x: inDevice, inBore: true, j, at: this.tSim });
      } else if (r.left_muzzle && local > r.muzzle_time) {
        const recoil = this._actionAt("recoil", t0 + r.muzzle_time) * 1e3;
        const x = L.muzzleX - recoil + r.muzzle_velocity * (local - r.muzzle_time) * 1e3;
        if (x < L.muzzleX + Math.max(4000, 60 * L.bore)) out.push({ x, inBore: false, j, at: t0 + r.muzzle_time });
      } else {
        out.push({ x: L.seat + interp(r.time, r.travel, local) * 1e3, inBore: true, j, at: this.tSim });
      }
    }
    // A rotary gun's barrels turn as the round goes down them: it is on its own barrel's line.
    if (L.rotary) for (const p of out) [p.y, p.z] = rotaryBarrel(this, p.j, p.at);
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
      const rc = this._actionAt("recoil", t) * 1e3, pc = this._actionAt("pitch", t) + this._loadPitch(t);
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
        // exit as it is now, into a puff that stays above where the muzzle was at exit. A bore evacuator
        // blows its charge, and the bore's fumes with it, out of the muzzle over the time it blows.
        const ev = r.evacuator, age = this.tSim - latest - P.times[P.times.length - 1];
        const tr = ev ? { ...P.trickle, mass: P.trickle.mass + ev.charge, tau: Math.max(P.trickle.tau, (ev.blow_end - r.muzzle_time) / 3) }
          : P.trickle;
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
    // A revolver's cylinder gap: the gas that escapes it flashes, then smokes in a puff over the frame, from
    // the moment the bullet's base clears the cylinder. One puff, thickening with each shot of a string.
    const gap = s?.result.gap, C = L.hand?.cyl;
    if (gap && C && this.T >= PIN_FALL) {
      const opened = this._shotTimes.map((t0) => t0 + gap.t[0]).filter((t) => this.tSim >= t);
      const latest = opened[opened.length - 1];
      const age = latest !== undefined ? this.tSim - latest : -1;
      if (age >= 0 && age < SMOKE_LIFE) {
        const mass = gap.mass * Math.sqrt(opened.length) * (1 - Math.exp(-age / 2e-3));
        const R = Math.cbrt(3 * mass * SEEP_DILUTION / (4 * Math.PI * 1.2)) * 1e3 + bore + 25 * age;
        const density = mass / (4 / 3 * Math.PI * (R * 1e-3) ** 3);
        const x = C.Lc + C.gap / 2, gE = gunAtT(latest), up = 0.4 * R + 40 * age;
        const where = at(gE, x, C.top, 0);
        state.smoke.push({
          ...puff(at(gT, x, C.top, 0), [where[0], where[1] + up, where[2]]), radius: R,
          extinction: SMOKE * density * Math.exp(-age / 2.5), rise: 0, age, group: 1, seed: 5.3, trail: 0.4,
        });
        if (age < GAP_FLASH) {
          const g = Math.min(gap.energy / 250, 2.5) * (1 - age / GAP_FLASH);
          const position = at(gE, x, 0, 0);
          if (!light || g > light.color[0] / 14) {
            light = { position, color: [14 * g, 7 * g, 2.6 * g], range: 14 * bore };
            state.light = { position, color: [0.6 * g, 0.3 * g, 0.11 * g], range: 14 * bore };
          }
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
    // A tank gun's autoloader fills the breech's view: from the rammer's chain to the breech, and all it stands on.
    const A = L.autoloader;
    if (A) {
      const b = A.bounds;
      goals.breech = { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2, width: Math.max(b.x1 - b.x0, 1.8 * (b.y1 - b.y0)) * 1.1 };
    }
    if (L.rotary) goals.breech = rotaryCamera(L);
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
    const wedge = this._breech === "wedge";
    // A sliding wedge drops to open; every other bolt draws back along the bore.
    const boltAt = chain(gunAt, wedge ? translation(0, -pose.travel, 0) : translation(-pose.travel, 0, 0));
    const pinBack = (this.cycle && this.cycle.t > CYCLE.lift * 0.5) || (this._auto && pose.travel > 0.5) ? 0 : this.pin;
    // A short-recoil barrel recoils on its own; a Browning barrel's breech drops about its bushing as it unlocks.
    const tl = L.tilt;
    const barrelAt = tl
      ? chain(gunAt, translation(-pose.barrel, 0, 0), translation(tl.x, 0, 0), rotationZ(Math.atan(tl.drop / tl.x) * pose.lock), translation(-tl.x, 0, 0))
      : chain(gunAt, translation(-pose.barrel, 0, 0));
    const H = L.hand;
    const mountAt = this._mountMatrix();       // a mount's cradle pitches with the gun but doesn't recoil
    const still = translation(0, 0, 0);
    const optional = (mesh, model, material, clip = false) => (mesh ? [{ mesh, model, material, clip }] : []);
    const lv = L.lever, ck = L.crank;
    const items = L.rotary ? rotaryParts(this, gunAt, mountAt, MATERIALS) : [
      { mesh: m.steel, model: gunAt, material: MATERIALS.steel },
      { mesh: m.furniture, model: gunAt, material: MATERIALS.black },
      ...optional(m.wood, gunAt, MATERIALS.wood, true),
      ...optional(m.barrel, barrelAt, MATERIALS.steel, true),
      ...optional(m.paint, gunAt, MATERIALS.paint, true),
      ...optional(m.mount, mountAt, MATERIALS.paint, true),
      ...optional(m.pedestal, still, MATERIALS.black, true),
      ...optional(m.rack, still, MATERIALS.black, true),
      // A sliding wedge's crank turns as the block drops.
      ...optional(m.crank, ck && chain(gunAt, translation(ck.px, ck.py, ck.z), rotationZ(-ck.turn * pose.travel / L.stroke)), MATERIALS.bolt),
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
      // A wedge's firing pin is in its block.
      { mesh: m.striker, model: wedge ? boltAt : chain(gunAt, translation(-pose.travel + pinBack * L.pinTravel, 0, 0)), material: MATERIALS.bolt, clip: false },
      // A pistol's slide, blued or black; a revolver's stainless frame; the trigger as the shooter pulls it.
      ...optional(m.slide, boltAt, H?.slideMaterial === "steel" ? MATERIALS.steel : MATERIALS.black),
      ...optional(m.bright, gunAt, MATERIALS.bolt),
      ...optional(m.trigger, H && chain(gunAt, translation(H.trigger.x - this._triggerTravel(), H.trigger.y, 0)), MATERIALS.bolt),
    ];
    // The recoil spring's coils, bunched between the guide rod's head and the slide's plug.
    if (H?.spring && m.coil) {
      const S = H.spring, front = S.x1 - pose.travel;
      for (let k = 0; k < S.n; k++) {
        items.push({ mesh: m.coil, model: chain(gunAt, translation(S.x0 + ((front - S.x0) * (k + 0.5)) / S.n, S.y, 0)), material: MATERIALS.steel });
      }
    }
    // A chain gun's chain round its track (the master link carrying the carrier's T-slot), and its sprockets turning.
    if (L.chain && m.chainLink) {
      const C = L.chain, tr = C.track, q = this._chainQ();
      for (let j = 0; j < C.links; j++) {
        const p = tr.at(q + (j * tr.perimeter) / C.links);
        items.push({ mesh: j ? m.chainLink : m.masterLink, material: j ? MATERIALS.steel : MATERIALS.bolt,
                     model: chain(gunAt, translation(C.xFront - p.x, C.yC + p.y, C.z), rotationZ(Math.PI - p.angle)) });
      }
      for (const [x, y] of C.corners) {
        items.push({ mesh: m.sprocket, model: chain(gunAt, translation(x, y, C.z), rotationZ(q / tr.radius)), material: MATERIALS.steel });
      }
    }
    const R = L.round;
    const projMaterial = R.solidMetal !== null && R.solidMetal !== undefined ? CORE_MATERIALS[R.solidMetal] : MATERIALS.projectile;
    const addProjectile = (model, clip, sabot = true) => {
      items.push({ mesh: m.projectile, model, material: projMaterial, clip });
      if (m.core) items.push({ mesh: m.core, model, material: CORE_MATERIALS[L.coreMaterial], clip });
      if (m.fins) items.push({ mesh: m.fins, model, material: MATERIALS.fins, clip });
      if (sabot) for (let k = 0; k < R.petals; k++) items.push({ mesh: m[`sabot${k}`], model, material: MATERIALS.sabot, clip });
    };
    const steelCase = R.caseMetal === "steel";
    const addRound = (kind, model) => {
      const caseMaterial = kind === "spent" ? (steelCase ? MATERIALS.spentSteel : MATERIALS.spent) : (steelCase ? MATERIALS.steelCase : MATERIALS.case);
      items.push({ mesh: m.case, model, material: caseMaterial });
      items.push({ mesh: m.primer, model, material: MATERIALS.primer });
      if (kind === "live") {
        // A combustible case's felt body burns with the charge: a spent one is only its stub.
        if (m.caseBody) items.push({ mesh: m.caseBody, model, material: MATERIALS.felt });
        addProjectile(chain(model, translation(L.seat, 0, 0)), true);
      }
    };
    if (L.rotary) rotaryDraw(this, items, addRound, gunAt, MATERIALS);
    if (pose.round) addRound(pose.round.kind, pose.round.world ?? chain(gunAt, translation(pose.round.x, pose.round.y, 0), rotationZ(pose.round.angle ?? 0)));
    if (L.autoloader && this.alS) {
      // A tank gun's autoloader, fixed in the turret, with the rounds it holds (a two-piece round's projectile and charge
      // apart) and the ones the rammer has taken, which are the gun's.
      const clock = this._al, A = L.autoloader;
      const view = loaderDraw(A, this.alS, loaderPose(A, clock?.al ?? null, clock?.t ?? 0), this._turretMatrix(), gunAt);
      for (const p of view.parts) if (m[p.mesh]) items.push({ mesh: m[p.mesh], model: p.model, material: MATERIALS[p.material], clip: true });
      for (const q of view.pieces) {
        if (q.kind === "projectile") addProjectile(q.model, true);
        else if (q.kind === "charge") {
          items.push({ mesh: m.case, model: q.model, material: steelCase ? MATERIALS.steelCase : MATERIALS.case });
          items.push({ mesh: m.primer, model: q.model, material: MATERIALS.primer });
          if (m.caseBody) items.push({ mesh: m.caseBody, model: q.model, material: MATERIALS.felt });
        } else addRound("live", q.model);
      }
    }
    if (this.cyl && m.cylinder) {
      // The cylinder on its axis (out on its crane while a double action is reloaded), turned as far as the hand
      // has taken it, with what is in each chamber; the ejector star and rod, the crane, a single action's gate.
      const C = H.cyl, cp = this._cylPose(), { axis, cyl } = this._cylMatrix(cp, gunAt);
      const finish = H.finish === "bright" ? MATERIALS.bolt : MATERIALS.steel;
      items.push({ mesh: m.cylinder, model: cyl, material: finish });
      if (m.star) items.push({ mesh: m.star, model: chain(cyl, translation(-cp.star, 0, 0)), material: finish });
      if (m.crane) items.push({ mesh: m.crane, model: axis, material: finish });
      if (m.ejector) items.push({ mesh: m.ejector, model: chain(axis, translation(-cp.star, 0, 0)), material: finish });
      if (m.gate && C.gate) {
        items.push({ mesh: m.gate, model: chain(gunAt, translation(C.gate.x, C.gate.y, C.gate.z), rotationX(GATE_SWING * cp.gate)), material: MATERIALS.steel });
      }
      if (m.ejectorRod && C.rod) {
        items.push({ mesh: m.ejectorRod, model: chain(gunAt, translation(C.rod.x0 - cp.rod * (C.rod.x0 - 1), C.rod.y, C.rod.z)), material: MATERIALS.bolt });
      }
      this.cyl.state.forEach((kind, k) => {
        const moved = cp.round[k], incoming = cp.incoming.includes(k);
        if (!kind && !incoming) return;
        const dx = (moved?.dx ?? 0) - cp.star;
        addRound(incoming ? "live" : kind, this._chamberMatrix(cyl, k, dx, moved?.dr ?? 0));
      });
    }
    // The magazine (dropped out while it is changed, along the grip's rake in a handgun), its follower and
    // the rounds left in it; a loader's ready rack, which stays put; or the belt.
    const F = L.feed, feedState = this._feedState();
    const drop = this._magDrop(), rake = F.rake ?? 0;
    const magAt = chain(gunAt, translation(-drop * Math.sin(rake), -drop * Math.cos(rake), 0));
    if (m.magazine) items.push({ mesh: m.magazine, model: magAt, material: MATERIALS.black });
    if (m.magFollower) items.push({ mesh: m.magFollower, model: chain(magAt, F.follower(this.mag, feedState.lift)), material: MATERIALS.black });
    if (F.rackStatic) {
      for (const e of F.rounds(this.mag)) addRound("live", e.m);
    } else if (!F.belt) {
      for (const e of F.rounds(this.mag, feedState.lift)) addRound("live", chain(magAt, e.m));
    } else {
      // The cover (swung up for a new belt) carries the feed lever and slide; the belt lies on the ground beside the gun.
      // A chain gun's feeder is driven off its chain rather than a cam on the carrier.
      const frac = L.chain ? feedState.adv : F.camFrac(pose.carrier), coverAt = chain(gunAt, F.coverAt(this._coverAngle()));
      items.push({ mesh: m.cover, model: coverAt, material: MATERIALS.black });
      items.push({ mesh: m.feedSlide, model: chain(coverAt, F.slide(frac)), material: MATERIALS.bolt });
      items.push({ mesh: m.feedLever, model: chain(coverAt, F.lever(frac)), material: MATERIALS.bolt });
      items.push({ mesh: m.ground, model: translation(0, 0, 0), material: MATERIALS.ground, clip: false });
      this._beltSync();
      // The round drawn to the feed position is held at the feed angle, ready for the bolt.
      const tilt = feedState.adv >= 1 ? F.geo.angle : 0;
      for (const c of this._belts) {
        c.nodes.forEach((n, i) => {
          const model = n.pin ? chain(gunAt, translation(...n.local), rotationZ(c === this.belt && i === 1 ? tilt : 0))
            : this._linkFrame(c.nodes, i, gunAt);
          items.push({ mesh: m.link, model, material: MATERIALS.steel });
          if (n.round) addRound("live", model);
        });
      }
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
    // An APFSDS's sabot is stripped off at the muzzle: its petals fly apart and fall behind the rod.
    if (this.shot) {
      for (const p of this._projectiles()) {
        addProjectile(p.inBore ? chain(gunAt, translation(p.x, p.y ?? 0, p.z ?? 0)) : translation(p.x, p.y ?? 0, p.z ?? 0), false, p.inBore);
      }
      if (R.apfsds) {
        for (const model of this._petals()) {
          for (let k = 0; k < R.petals; k++) items.push({ mesh: m[`sabot${k}`], model: model[k], material: MATERIALS.sabot, clip: false });
        }
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
    const where = this.layout.rotary ? `in the ${F.label}` : F.rackStatic ? "in the ready rack" : F.sides?.length > 1 ? `in the ${F.feedSide > 0 ? "right" : "left"} belt`
      : F.belt ? "in the belt" : this.layout.autoloader ? `in the ${this.layout.autoloader.label}` : "in the magazine";
    const ammo = this.layout.rotary ? ["rounds", `${this.mag} / ${F.capacity} ${where}`] : this.cyl ? ["rounds", `${this._liveCount()} / ${this.cyl.state.length} live in the cylinder`]
      : ["rounds", `${this.chamber === "live" ? 1 : 0} + ${this.mag} / ${F.capacity} ${where}`];
    const c = this.cycle, pistol = !!this.layout.hand && !this.cyl;
    const thumb = this.layout.hand?.trigger.type === "single_action";
    const working = c?.loader ? (c.t < LOAD.open ? "Loader opens the breech" : c.t < LOAD.open + LOAD.fetch ? "Loader takes a round from the rack"
      : c.t < LOAD.open + LOAD.fetch + LOAD.ram ? "Loader rams the round" : "The block springs shut")
      : c?.autoload ? this._alStage(c.al, c.t)
      : c?.chain ? "Turning the chain by hand"
      : c?.cock ? (thumb ? "Thumbing the hammer back: the cylinder turns" : "Double-action pull: the hammer comes back, the cylinder turns")
      : pistol ? "Racking the slide" : "Working the bolt";
    if (!s) {
      const belt = () => (this.reload.t < BELT_RELOAD.open ? "Opening the top cover"
        : this.reload.t < BELT_RELOAD.open + BELT_RELOAD.lay ? "Laying in a new belt" : "Closing the top cover");
      const cylinder = () => {
        const st = this.reload.steps[Math.min(this.reload.step, this.reload.steps.length - 1)].name;
        return { open: this.layout.hand.cyl.loading === "gate" ? "Opening the loading gate" : "Swinging out the cylinder",
                 eject: "Ejecting the fired cases", load: this.layout.hand.cyl.loading === "gate" ? "Loading a round" : "Speedloader in",
                 turn: "Turning the next chamber to the gate",
                 close: this.layout.hand.cyl.loading === "gate" ? "Closing the gate" : "Closing the cylinder" }[st];
      };
      const what = this.reload ? (this.reload.cylinder ? cylinder() : F.belt ? belt() : F.rackStatic ? "Restocking the ready rack" : this.layout.autoloader ? "Restocking the autoloader" : this.layout.rotary ? "Loading a fresh " + F.label : "Changing the magazine")
        : c ? working
        : this.cyl ? (this.chamber === "live" ? "Cocked: a round under the hammer"
          : this._liveCount() ? "Hammer down: the next pull turns a round up" : "Empty: reload the cylinder")
        : this.chamber === "jammed" ? `Jammed (${this.jam ?? "feed"}): ${pistol ? "rack the slide" : "work the bolt"} to clear it`
        : this.chamber === "live" ? "Ready: round chambered"
        : this.chamber === "spent" ? "Spent case in the chamber"
        : this.stuck?.open ? "Breech open: ready to load"
        : this.stuck ? (pistol ? "Empty: slide locked back" : "Empty: bolt held open") : this.mag === 0 ? "Empty" : "Chamber empty";
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
      const breech = this._breech;
      phase = this.cycle ? (breech === "bolt" ? (pistol ? "Clearing: racking the slide" : "Clearing: working the bolt by hand") : working)
        : s.cycled ? (this.chamber === "live" ? "Smoke · loaded by hand" : "Smoke")
        : this._alText() ?? (last && !done ? label(last)
        : !last && !done ? (breech === "wedge" ? "Recoiling" : breech === "chain" ? "The chain carries the bolt on"
          : breech === "revolver" ? "Recoiling" : pistol && this.layout.mech.kind === "short_recoil" ? "Barrel and slide recoil locked together"
          : "Gas drives the piston")
        : a.status === "cycled" ? "Smoke · reloaded" : a.status === "fired" ? "Smoke" : a.status === "breech opened" ? "Smoke · breech open" : `Smoke · ${a.status}`);
    }
    else phase = this.cycle ? working : "Smoke";
    if (this.layout.rotary) phase = rotaryPhase(this, phase);
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
      const { recoil } = this._gunPose(), pitch = this._actionAt("pitch", this.tSim);
      const vel = this._actionAt("recoil_velocity", this.tSim);
      rows.push(["recoil", `${recoil.toFixed(1)} mm at ${vel.toFixed(2)} m/s`],
                ["muzzle rise", `${(pitch * 180 / Math.PI).toFixed(2)}°`]);
      if (this._auto && !s.cycled && !this.cyl && !this.layout.rotary) {
        const bolt = this._actionAt("bolt", this.tSim) * 1e3, bv = this._actionAt("bolt_velocity", this.tSim);
        // A sliding wedge's block drops (and is open, or shut) rather than going back and forward.
        rows.push(this._breech === "wedge" ? ["breech block", `${bolt.toFixed(0)} mm down at ${Math.abs(bv).toFixed(2)} m/s`]
          : [pistol ? "slide" : "bolt", `${bolt.toFixed(0)} mm, ${bv >= 0 ? "back" : "forward"} at ${Math.abs(bv).toFixed(1)} m/s`]);
      }
    }
    rows.push(ammo);
    if (this.layout.rotary) rows.push(...rotaryRows(this));
    if (this._shotTimes.length > 1 && this.T >= PIN_FALL) {
      rows.unshift(["shot", `${this._shotAt(this.tSim)} of ${this._shotTimes.length}`]);
    }
    this.hud.innerHTML = `<b>${phase}</b>` + rows.map(([k, val]) => `<span>${k}</span><span>${val}</span>`).join("");
  }
}
