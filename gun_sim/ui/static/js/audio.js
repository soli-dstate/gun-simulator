// Plays synthesised shots with Web Audio.
//
// Python does the physics and hands over pressure at each ear, in pascals,
// plus the blast at 1 m as thrown forward, sideways and back (the "references")
// to feed reflections, and the supersonic part of the trajectory (the
// "crack source"). Here we add what depends on the surroundings and on
// playback: reverb and echoes of the blast and of the crack, hearing
// protection, level (with an optional overloaded recorder), a limiter and bursts.
//
//   ┌ the shot's mix, rendered offline once per surroundings ─────────┐
//   │ blast, jet, crack, gap, device (L/R) ─────────────────────────┐ │
//   │ reference front ─▶ convolver (front IR) ──────────────────────┤ │
//   │ reference side ──▶ convolver (side IR) ───────────────────────┤ │
//   │ reference rear ──▶ convolver (rear IR) ───────────────────────┤ │
//   │ crack echoes (L/R) ───────────────────────────────────────────┘ │
//   └─────────────────────────────────────────────────────────────────┘
//      mix + the action's clacks ─▶ protection ─┬─▶ clean ─────────────┬─▶ volume ─▶ limiter ─▶ speakers
//                                               └─▶ drive (tanh) ─▶ ───┘
//
// The shot comes in stems, one per event (muzzle blast, supersonic crack,
// each clack of the action), each with its time after ignition. Everything
// acoustic about the shot (the blast and crack with all their echoes and
// reverb) is mixed into one buffer, so it always plays together, echoes in
// time with the blast. On the range the mix and the action's clacks follow the
// animation's clock: each starts when the slowed-down clock reaches it, and,
// if the sound is stretched, plays slowed down with it (down to MIN_RATE,
// below which a blast would only be a rumble), speeding up as the clock does.

const P_REF = 20e-6;
export const MIN_RATE = 0.25;   // slowest a stem plays at when it follows the slow motion
const LOOKAHEAD = 0.1;          // s (real) of the animation's clock scheduled ahead
const SIDES = ["front", "side", "rear"];
const MAX_ECHO = 7;             // s, echoes arriving later than this are dropped
const FRESNEL_HZ = 500;         // frequency whose Fresnel zone sets how much of a surface reflects as one
const MAX_PATCHES = 600;        // per surface

// Surroundings. Levels are relative to the blast at 1 m, so they keep their
// real proportion to the direct sound at any listener distance.
//   tail: diffuse reverb {rt60 s, energy (sum of IR^2), start s, lp: [Hz at start, Hz at end]}
//   echoes: hand-placed reflections, for multiple bounces (flutter between walls):
//           [delay s, amplitude, smear s, low-pass Hz, "front" | "side" | "rear" (default side)]
//   surfaces: reflecting faces in the horizontal plane at muzzle height, from the
//           muzzle: x downrange, y to the left (m). Each is cut into patches and every
//           patch sends back both the muzzle blast and the bullet's crack, so long
//           surfaces give rolling echoes. {from: [x, y], to: [x, y], refl (pressure
//           reflection 0-1), lp (Hz, surface roughness), smear (s), blast: false to
//           leave the blast to `echoes`}
//   stop: m downrange where the bullet stops (backstop, hillside), else it flies on
export const ENVIRONMENTS = {
  none: { label: "Free field (no surroundings)" },
  open: {
    label: "Open field, treeline 120 m",
    tail: { rt60: 0.5, energy: 2e-6, start: 0.01, lp: [4000, 1500] },
    surfaces: [
      { from: [120, -250], to: [120, 250], refl: 0.35, lp: 3000, smear: 0.008 },
      { from: [450, -700], to: [450, 700], refl: 0.45, lp: 1800, smear: 0.02 },  // hillside behind
    ],
    stop: 450,
  },
  forest: {
    label: "Forest",
    tail: { rt60: 1.8, energy: 3e-4, start: 0.004, lp: [3000, 600] },
    // Trunks scatter like loose rows of reflectors on every side.
    surfaces: [20, -20, 55, -55].map((y) => ({ from: [-200, y], to: [400, y], refl: Math.abs(y) < 30 ? 0.12 : 0.09, lp: 2500, smear: 0.015 })),
    stop: 300,
  },
  indoor: {
    label: "Indoor range (concrete)",
    tail: { rt60: 1.1, energy: 0.15, start: 0.006, lp: [9000, 2500] },
    echoes: [[0.007, 0.12, 0.001, 9000, "side"], [0.011, 0.09, 0.0015, 8000, "side"], [0.016, 0.07, 0.002, 7000, "rear"],
             [0.024, 0.05, 0.003, 6000, "side"], [0.031, 0.04, 0.004, 5000, "front"]],
    // Side walls 3 m out and the backstop at 25 m; the blast is in `echoes`, these return the crack.
    surfaces: [
      { from: [-5, 3], to: [25, 3], refl: 0.8, lp: 8000, smear: 0.001, blast: false },
      { from: [-5, -3], to: [25, -3], refl: 0.8, lp: 8000, smear: 0.001, blast: false },
      { from: [25, -3], to: [25, 3], refl: 0.3, lp: 4000, smear: 0.002, blast: false },
    ],
    stop: 25,
  },
  urban: {
    label: "Street between buildings",
    tail: { rt60: 1.3, energy: 1e-3, start: 0.02, lp: [5000, 1200] },
    // Flutter between two facades 15 m either side: one round trip every 87 ms.
    echoes: [...Array(10).keys()].map((i) => [0.044 + 0.0437 * i, 0.03 * Math.pow(0.72, i), 0.004 + 0.002 * i, 6000 - 400 * i, "side"]),
    surfaces: [15, -15].map((y) => ({ from: [-150, y], to: [300, y], refl: 0.7, lp: 6000, smear: 0.003, blast: false })),
    stop: 300,
  },
  valley: {
    label: "Mountain valley",
    tail: { rt60: 1.0, energy: 2e-5, start: 0.02, lp: [3000, 800] },
    surfaces: [
      { from: [-800, 250], to: [1200, 250], refl: 0.8, lp: 2200, smear: 0.025 },
      { from: [-800, -250], to: [1200, -250], refl: 0.8, lp: 2200, smear: 0.025 },
      { from: [900, -250], to: [900, 250], refl: 0.8, lp: 1800, smear: 0.03 },  // head of the valley
    ],
    stop: 900,
  },
};

// Hearing protection: broadband attenuation plus filters for its frequency shape
// (passive protectors block highs far better than lows).
export const PROTECTION = {
  none: { label: "No hearing protection", gain: 0, filters: [] },
  plugs: { label: "Foam earplugs", gain: -28, filters: [["highshelf", 1500, -8]] },
  muffs: { label: "Earmuffs", gain: -14, filters: [["highshelf", 500, -18], ["lowpass", 3500, 0]] },
  both: { label: "Plugs + earmuffs", gain: -38, filters: [["highshelf", 500, -16], ["lowpass", 2500, 0]] },
};

function decode(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

function peakOf(...arrays) {
  let m = 0;
  for (const a of arrays) for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i]));
  return m;
}

/** Low-pass (Hz) standing in for air absorption over a path: about 3 dB down there (ISO 9613, 50 % RH). */
function airLowpass(dist) {
  return Math.min(16000, Math.max(400, 4000 * Math.pow(3 / (0.025 * Math.max(dist, 1)), 2 / 3)));
}

/** Points along a surface, each standing for w metres of it, with the surface's normal. */
function patches(surface) {
  const [x0, y0] = surface.from, [x1, y1] = surface.to;
  const len = Math.hypot(x1 - x0, y1 - y0);
  const n = Math.max(1, Math.min(MAX_PATCHES, Math.ceil(len)));
  const out = [];
  for (let i = 0; i < n; i++) {
    const f = (i + 0.5) / n;
    out.push({ x: x0 + (x1 - x0) * f, y: y0 + (y1 - y0) * f, w: len / n, nx: -(y1 - y0) / len, ny: (x1 - x0) / len });
  }
  return out;
}

/** Left/right gains for sound arriving from (dx, dy) relative to the listener's head. */
function pan(dx, dy, facingDeg) {
  const phi = facingDeg * Math.PI / 180;
  const s = (dx * Math.sin(phi) + dy * Math.cos(phi)) / (Math.hypot(dx, dy) || 1);  // +1 = from the left
  return [Math.sqrt(1 + 0.6 * s), Math.sqrt(1 - 0.6 * s)];
}

/** Share of the front/side/rear references for a direction at cos(theta) from the bore. */
function sideWeights(cos) {
  return cos >= 0 ? { front: cos, side: 1 - cos, rear: 0 } : { front: 0, side: 1 + cos, rear: -cos };
}

/**
 * How much of a patch reflects towards the listener. Patches are summed in
 * energy, so the ones within a Fresnel zone of the mirror point add up to a
 * plain mirror reflection; further out the surface scatters (Lambert).
 * Returns 0 if source and listener are on different sides of the surface.
 */
function patchGain(p, from, d1, d2, lx, ly, c) {
  const a = p.nx * (from[0] - p.x) + p.ny * (from[1] - p.y);
  const b = p.nx * (lx - p.x) + p.ny * (ly - p.y);
  if (a * b <= 0) return 0;
  const fresnel = Math.sqrt((c / FRESNEL_HZ) * d1 * d2 / (d1 + d2));
  return Math.sqrt(Math.min(1, p.w / fresnel) * Math.abs(a) / d1 * Math.abs(b) / d2);
}

/** Echoes of the muzzle blast off an environment's surfaces: delays after the direct blast. */
function blastEchoes(env, geom) {
  const [lx, ly, lz] = geom.listener, c = geom.c;
  const direct = Math.hypot(lx, ly, lz);
  const out = [];
  for (const surf of env.surfaces ?? []) {
    if (surf.blast === false) continue;
    for (const p of patches(surf)) {
      const d1 = Math.hypot(p.x, p.y);
      const d2 = Math.hypot(lx - p.x, ly - p.y, lz);
      const delay = (d1 + d2 - direct) / c;
      if (delay > MAX_ECHO) continue;
      const amp = surf.refl * patchGain(p, [0, 0], d1, d2, lx, ly, c) / (d1 + d2);
      if (amp < 1e-7) continue;
      const [gl, gr] = pan(p.x - lx, p.y - ly, geom.facing);
      out.push({ delay, amp, gl, gr, smear: surf.smear, lp: Math.min(surf.lp, airLowpass(d1 + d2)), weights: sideWeights(p.x / d1) });
    }
  }
  return out;
}

/**
 * Echoes of the supersonic crack. The Mach cone reaches a patch first from the
 * point on the trajectory that minimises (time there + distance / c); it is
 * then an N-wave (Whitham) that keeps weakening along the way back as if the
 * surface were a mirror. Times are s after ignition.
 */
function crackEchoes(env, geom, src) {
  if (!src) return [];
  const [lx, ly, lz] = geom.listener, c = src.sound_speed;
  const stop = env.stop ?? Infinity;
  let last = src.x.length - 1;
  while (last > 0 && src.x[last] > stop) last--;
  const out = [];
  for (const surf of env.surfaces ?? []) {
    for (const p of patches(surf)) {
      let best = Infinity, ib = -1;
      for (let i = 0; i <= last; i++) {
        const t = src.t[i] + Math.hypot(p.x - src.x[i], p.y) / c;
        if (t < best) { best = t; ib = i; }
      }
      // At the muzzle or the end of the supersonic flight: the cone never sweeps this patch.
      if (ib <= 0 || ib >= last) continue;
      const ex = src.x[ib];
      const d1 = Math.hypot(p.x - ex, p.y);
      const d2 = Math.hypot(lx - p.x, ly - p.y, lz);
      const time = src.exit_time + best + d2 / c;
      if (time > MAX_ECHO) continue;
      const miss = Math.max(Math.abs(p.y), 2);
      const path = miss + d2;
      const dp = src.kp[ib] * Math.pow(path, -0.75);
      const amp = surf.refl * patchGain(p, [ex, 0], d1, d2, lx, ly, c) * dp;
      if (amp < 1e-4) continue;
      const [gl, gr] = pan(p.x - lx, p.y - ly, geom.facing);
      out.push({ time, amp, gl, gr, duration: src.kt[ib] * Math.pow(path, 0.25), smear: surf.smear,
                 lp: Math.min(surf.lp, airLowpass(d1 + d2)) });
    }
  }
  return out;
}

/**
 * A reflection off a rough surface arrives smeared in time: a burst of noise
 * whose total energy equals that of a single reflection of `amp`.
 */
function addBurst(h, n0, amp, smear, lp, fs) {
  const nLen = Math.max(1, Math.floor(smear * fs * 3));
  const tau = Math.max(smear * fs, 1);
  const a = Math.exp(-2 * Math.PI * lp / fs);
  const tmp = new Float32Array(nLen);
  let y = 0, energy = 0;
  for (let k = 0; k < nLen; k++) {
    const x = (k === 0 ? 1 : (Math.random() * 2 - 1)) * Math.exp(-k / tau);
    y = (1 - a) * x + a * y;
    tmp[k] = y;
    energy += y * y;
  }
  const g = amp / Math.sqrt(energy || 1);
  for (let k = 0; k < nLen && n0 + k < h.length; k++) h[n0 + k] += tmp[k] * g;
}

/**
 * Impulse responses for a set of surroundings, one per reference (front, side,
 * rear), at the context's sample rate. null where nothing reflects that part of the blast.
 */
function buildIRs(ctx, env, geom) {
  const fs = ctx.sampleRate;
  const taps = { front: [], side: [], rear: [] };  // [delay, left amp, right amp, smear, lp]
  for (const [delay, amp, smear, lp, side = "side"] of env.echoes ?? []) taps[side].push([delay, amp, amp, smear, lp]);
  for (const e of blastEchoes(env, geom)) {
    for (const side of SIDES) {
      const w = e.weights[side];
      if (w > 0.01) taps[side].push([e.delay, e.amp * w * e.gl, e.amp * w * e.gr, e.smear, e.lp]);
    }
  }
  const irs = {};
  for (const side of SIDES) {
    const tail = side === "side" ? env.tail : null;
    if (!tail && !taps[side].length) { irs[side] = null; continue; }
    const echoEnd = Math.max(0, ...taps[side].map(([d, , , smear]) => d + smear * 3));
    const len = Math.ceil(fs * Math.max(tail ? tail.start + tail.rt60 * 1.2 : 0, echoEnd) + fs * 0.05);
    const ir = ctx.createBuffer(2, len, fs);
    for (let ch = 0; ch < 2; ch++) {
      const h = ir.getChannelData(ch);
      if (tail) {
        // Exponentially decaying noise, low-passed more and more over time (air
        // and surfaces absorb highs faster), scaled to the requested energy.
        const tmp = new Float32Array(len);
        let y = 0, energy = 0;
        const n0 = Math.floor(tail.start * fs);
        for (let n = n0; n < len; n++) {
          const t = (n - n0) / fs;
          const frac = Math.min(1, t / tail.rt60);
          const fc = tail.lp[0] * Math.pow(tail.lp[1] / tail.lp[0], frac);
          const a = Math.exp(-2 * Math.PI * fc / fs);
          const x = (Math.random() * 2 - 1) * Math.exp(-6.91 * t / tail.rt60);
          y = (1 - a) * x + a * y;
          // Short fade-in so the tail does not start with a click.
          tmp[n] = y * Math.min(1, t / 0.004);
          energy += tmp[n] * tmp[n];
        }
        const g = energy > 0 ? Math.sqrt(tail.energy / energy) : 0;
        for (let n = 0; n < len; n++) h[n] += tmp[n] * g;
      }
      for (const [delay, al, ar, smear, lp] of taps[side]) addBurst(h, Math.floor(delay * fs), ch ? ar : al, smear, lp, fs);
    }
    irs[side] = ir;
  }
  return irs;
}

/** The crack's echoes rendered as one stereo track: {time (s after ignition of sample 0), left, right} or null. */
function renderCrackEchoes(env, geom, src, fs) {
  const echoes = crackEchoes(env, geom, src);
  if (!echoes.length) return null;
  const t0 = Math.min(...echoes.map((e) => e.time)) - 0.002;
  const t1 = Math.max(...echoes.map((e) => e.time + e.smear + e.duration)) + 0.05;
  const len = Math.ceil((t1 - t0) * fs);
  const left = new Float32Array(len), right = new Float32Array(len);
  for (const e of echoes) {
    const a = Math.exp(-2 * Math.PI * e.lp / fs);
    const nN = Math.max(2, Math.round(e.duration * fs));
    const nTail = Math.ceil(5 / (1 - a));
    for (const [h, g] of [[left, e.gl], [right, e.gr]]) {
      // Rough surfaces spread the return a little, differently for each ear.
      const n0 = Math.floor((e.time - t0 + Math.random() * e.smear) * fs);
      let y = 0;
      for (let k = 0; k < nN + nTail && n0 + k < len; k++) {
        const x = k < nN ? e.amp * (1 - 2 * k / (nN - 1)) : 0;  // the N-wave, then the filter's tail
        y = (1 - a) * x + a * y;
        h[n0 + k] += y * g;
      }
    }
  }
  return { time: t0, left, right };
}

/** tanh saturation like an overloaded microphone preamp: the peak flattens, everything after it comes up by `db`. */
const curves = {};
function driveCurve(db) {
  if (curves[db]) return curves[db];
  const n = 65537, g = Math.pow(10, db / 20), norm = Math.tanh(g);
  const curve = new Float32Array(n);
  for (let i = 0; i < n; i++) curve[i] = Math.tanh(g * (2 * i / (n - 1) - 1)) / norm;
  return (curves[db] = curve);
}

/** A stereo (or mono) AudioBuffer of Float32Arrays at sample rate fs. */
function toBuffer(ctx, channels, fs) {
  const b = ctx.createBuffer(channels.length, Math.max(1, channels[0].length), fs);
  channels.forEach((c, i) => b.copyToChannel(c, i));
  return b;
}

export class ShotPlayer {
  constructor() {
    this.ctx = null;
    this.shot = null;        // decoded stems of the current shot
    this.environment = "open";
    this.protection = "none";
    this.irCache = {};
    this.sync = null;        // events following the range's clock
    this.stretch = true;     // slow the sound down with the clock (else it plays at real speed)
  }

  /** Create or wake the audio context. Call from a click handler (autoplay rules). */
  unlock() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) throw new Error("this browser has no Web Audio");
      this.ctx = new Ctx({ latencyHint: "interactive" });
      this._buildGraph();
      if (this.shot) this._mix();
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  }

  get ready() { return !!(this.ctx && this.shot); }

  _buildGraph() {
    const ctx = this.ctx;
    this.protIn = ctx.createGain();
    this.protOut = ctx.createGain();
    this.volume = ctx.createGain();
    // Level stage: straight through, or saturated like a recorder.
    this.clean = ctx.createGain();
    this.shaper = ctx.createWaveShaper();
    this.shaper.oversample = "4x";
    this.makeup = ctx.createGain();
    this.protOut.connect(this.clean).connect(this.volume);
    this.protOut.connect(this.shaper).connect(this.makeup).connect(this.volume);
    // Brick-wall-ish limiter: a real shot is far louder than any speaker.
    this.limiter = ctx.createDynamicsCompressor();
    this.limiter.threshold.value = -2;
    this.limiter.knee.value = 0;
    this.limiter.ratio.value = 20;
    this.limiter.attack.value = 0;
    this.limiter.release.value = 0.15;
    this.volume.connect(this.limiter).connect(ctx.destination);
    this.protFilters = [];
    this._wireProtection();
  }

  _wireProtection() {
    if (!this.ctx) return;
    this.protIn.disconnect();
    for (const f of this.protFilters) f.disconnect();
    const spec = PROTECTION[this.protection];
    this.protFilters = spec.filters.map(([type, freq, gain]) => {
      const f = this.ctx.createBiquadFilter();
      f.type = type;
      f.frequency.value = freq;
      f.gain.value = gain;
      return f;
    });
    let node = this.protIn;
    for (const f of this.protFilters) { node.connect(f); node = f; }
    node.connect(this.protOut);
  }

  /** Where the listener is, from the shot (older servers: at the muzzle). */
  _geometry(shot = this.shot) {
    const st = shot?.stats ?? {};
    return { listener: st.listener ?? [0, 0, 0], facing: st.facing ?? 0, c: st.sound_speed ?? 343 };
  }

  /** The surroundings' impulse responses for a shot's listener, at the context's rate. */
  _irs(name, shot) {
    const env = ENVIRONMENTS[name], geom = this._geometry(shot);
    const key = `${name}|${geom.listener.map((v) => v.toFixed(2))}|${geom.facing}|${geom.c.toFixed(1)}|${this.ctx.sampleRate}`;
    if (!this.irCache[key]) {
      if (Object.keys(this.irCache).length > 8) this.irCache = {};
      this.irCache[key] = buildIRs(this.ctx, env, geom);
    }
    return this.irCache[key];
  }

  setEnvironment(name) {
    this.environment = name;
    if (this.ctx && this.shot) this._mix();  // get it ready before it's played
  }

  setProtection(name) { this.protection = name; this._wireProtection(); if (this.level) this._setLevel(this.level); }

  /** Load a shot from the synthesize API. */
  load(data) {
    const left = decode(data.left), right = decode(data.right), ref = decode(data.reference);
    const refsOf = (many, one) => Object.fromEntries(SIDES.map((s) => [s, many?.[s] ? decode(many[s]) : one]));
    // Older servers send no stems: the whole mix is then one event.
    const stems = (data.stems?.length ? data.stems : [{ name: "shot", kind: "blast", time: data.start_time, left: data.left, right: data.right, reference: data.reference }])
      .map((st) => {
        const one = st.reference ? decode(st.reference) : null;
        return { name: st.name, kind: st.kind, time: st.time, left: decode(st.left), right: decode(st.right),
                 refs: one ? refsOf(st.references, one) : null };
      });
    // A muzzle device is normalised against the same gun without it, so the
    // suppression stays audible instead of being turned back up to full scale.
    const bare = data.stats?.bare_peak ?? 0;
    const acoustic = stems.filter((st) => st.kind !== "action");
    this.shot = { fs: data.sample_rate, start: data.start_time, left, right, refs: refsOf(data.references, ref),
                  peak: Math.max(peakOf(left, right), bare), stems, stats: data.stats ?? {},
                  acoustic, actions: stems.filter((st) => st.kind === "action"),
                  mixTime: Math.min(...acoustic.map((st) => st.time)),
                  crackSource: data.crack_source ?? null, mixes: {}, mixed: {} };
    if (this.ctx) this._mix();
  }

  /**
   * The shot's acoustic mix in the current surroundings: {time (s after ignition of its
   * first sample), buffer}. A promise; once it has resolved, also in shot.mixed[environment].
   */
  _mix() {
    const s = this.shot, name = this.environment;
    s.mixes[name] ??= this._renderMix(s, name).then((m) => {
      s.mixed[name] = m;
      return m;
    });
    return s.mixes[name];
  }

  async _renderMix(s, name) {
    const fs = this.ctx.sampleRate;
    const irs = this._irs(name, s);
    const echo = renderCrackEchoes(ENVIRONMENTS[name], this._geometry(s), s.crackSource, s.fs);
    const t0 = s.mixTime;
    const irLength = Math.max(0, ...SIDES.map((side) => irs[side]?.duration ?? 0));
    let end = 0;
    for (const st of s.acoustic) end = Math.max(end, st.time - t0 + st.left.length / s.fs + (st.refs ? irLength : 0));
    if (echo) end = Math.max(end, echo.time - t0 + echo.left.length / s.fs);
    const off = new OfflineAudioContext(2, Math.ceil((end + 0.05) * fs), fs);
    const add = (buffer, at, dest) => {
      const src = off.createBufferSource();
      src.buffer = buffer;
      src.connect(dest);
      src.start(Math.max(at, 0), Math.max(-at, 0));
    };
    for (const st of s.acoustic) {
      add(toBuffer(off, [st.left, st.right], s.fs), st.time - t0, off.destination);
      if (!st.refs) continue;
      for (const side of SIDES) {
        if (!irs[side]) continue;
        const conv = off.createConvolver();
        conv.normalize = false;
        conv.buffer = irs[side];
        conv.connect(off.destination);
        add(toBuffer(off, [st.refs[side]], s.fs), st.time - t0, conv);
      }
    }
    if (echo) add(toBuffer(off, [echo.left, echo.right], s.fs), echo.time - t0, off.destination);
    return { time: t0, buffer: await off.startRendering() };
  }

  /**
   * Gains for a level mode.
   * normalized: loudest ear at -1 dBFS (before protection; with a muzzle device, the loudest ear without it).
   * calibrated: 0 dBFS = fullScaleDb dB SPL, so distances and guns compare.
   * recorded: as normalised, then driven `drive` dB into a saturating recorder, the way
   *           recordings and films of shots sound: the peak flattens, the body and echoes come up.
   *           Hearing protection turns the input down, so it saturates less.
   */
  _setLevel({ level = "recorded", fullScaleDb = 150, volume = 0.8, drive = 36 } = {}) {
    this.level = { level, fullScaleDb, volume, drive };
    if (!this.shot || !this.ctx) return;
    const prot = PROTECTION[this.protection];
    const norm = this.shot.peak > 0 ? 1 / this.shot.peak : 1;
    let scale;
    if (level === "calibrated") scale = 1 / (P_REF * Math.pow(10, fullScaleDb / 20)) * Math.pow(10, prot.gain / 20);
    else if (level === "recorded") scale = norm * Math.pow(10, prot.gain / 20);
    else scale = norm * Math.pow(10, -1 / 20);
    this.protIn.gain.value = scale;
    const recorded = level === "recorded";
    this.clean.gain.value = recorded ? 0 : 1;
    this.makeup.gain.value = recorded ? Math.pow(10, -1 / 20) : 0;
    if (recorded) this.shaper.curve = driveCurve(Math.round(drive));
    this.volume.gain.value = volume;
  }

  _stemBuffer(stem) {
    if (stem.buffer?.ctx !== this.ctx) stem.buffer = { ctx: this.ctx, buffer: toBuffer(this.ctx, [stem.left, stem.right], this.shot.fs) };
    return stem.buffer.buffer;
  }

  _source(buffer, rate = 1) {
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.playbackRate.value = rate;
    src.connect(this.protIn);
    return src;
  }

  /**
   * Start following a shot on the range. shotTimes: ignition of each shot of a
   * burst (s, simulation clock). The events then play as syncTo() moves the clock.
   */
  startSync(shotTimes = [0], options = {}) {
    this.stopSync();
    if (!this.shot || !this.ctx) return;
    this._setLevel(options);
    const s = this.shot;
    this._mix();
    const t0s = shotTimes.length ? shotTimes : [0];
    const events = [];
    for (const t0 of t0s) {
      const shift = t0 - t0s[0];
      events.push({ at: shift + s.mixTime, mix: true });
      for (const stem of s.actions) events.push({ at: shift + stem.time, stem });
    }
    events.sort((a, b) => a.at - b.at);
    this.sync = { shot: s, environment: this.environment, events, next: 0, sources: [], rate: 1 };
  }

  stopSync() {
    if (!this.sync) return;
    for (const src of this.sync.sources) { try { src.stop(); } catch (e) { /* not started */ } }
    this.sync = null;
  }

  /** The range's clock: tSim (s since ignition) moving at rate simulated s per real s. */
  syncTo(tSim, rate) {
    const sync = this.sync;
    if (!sync || !this.ctx) return;
    const ctx = this.ctx;
    const play = this.stretch ? Math.min(1, Math.max(rate, MIN_RATE)) : 1;
    if (play !== sync.rate) {
      // Sounds already playing slow down or speed up with the clock.
      for (const src of sync.sources) src.playbackRate.setTargetAtTime(play, ctx.currentTime, 0.02);
      sync.rate = play;
    }
    const horizon = tSim + LOOKAHEAD * rate;
    while (sync.next < sync.events.length && sync.events[sync.next].at <= horizon) {
      const ev = sync.events[sync.next];
      let buffer;
      if (ev.mix) {
        const m = sync.shot.mixed[sync.environment];
        if (!m) break;  // still rendering (a few tens of ms): it starts late, part-way through
        buffer = m.buffer;
      } else {
        buffer = this._stemBuffer(ev.stem);
      }
      sync.next++;
      // Late (the sound loaded after the clock passed it): start part-way through.
      const late = Math.max(0, tSim - ev.at);
      if (late >= buffer.duration) continue;
      const src = this._source(buffer, play);
      src.start(ctx.currentTime + Math.max(0, ev.at - tSim) / Math.max(rate, 1e-9), late);
      src.onended = () => { if (this.sync === sync) sync.sources = sync.sources.filter((x) => x !== src); };
      sync.sources.push(src);
    }
  }

  /** Play the current shot. See _setLevel for the level modes. */
  async play({ shots = 1, rpm = 600, times = null, level = "recorded", fullScaleDb = 150, volume = 0.8, drive = 36 } = {}) {
    if (!this.shot) return;
    const ctx = this.unlock();
    this.stopSync();
    const s = this.shot;
    const mix = await this._mix();
    if (s !== this.shot) return;
    this._setLevel({ level, fullScaleDb, volume, drive });
    const t0 = ctx.currentTime + 0.03;
    // A burst from the action simulation plays at its shot times; otherwise evenly at rpm.
    const period = 60 / Math.max(rpm, 1);
    const starts = times && times.length
      ? times.map((t) => t - times[0])
      : [...Array(Math.max(1, Math.min(shots, 100))).keys()].map((i) => i * period);
    for (const at of starts) {
      this._source(mix.buffer).start(t0 + at + mix.time - s.start);
      for (const stem of s.actions) this._source(this._stemBuffer(stem)).start(t0 + at + stem.time - s.start);
    }
  }
}
