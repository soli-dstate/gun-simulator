// Sounds of the hit, synthesised here from the target's physics:
//
// - A steel (or aluminium) plate rings in the modes of a free circular plate
//   (Kirchhoff): f = lambda^2 / (2 pi a^2) sqrt(D / (rho h)), D = E h^3 / (12 (1 - nu^2)),
//   each dying away at its loss factor (t60 = 2.2 / (eta f)). A hit near the
//   middle mostly drives the axisymmetric modes. A hole lets it ring duller and shorter.
// - The contact itself: a click as short as the projectile takes to stop on the face.
// - A shot that goes through tears the steel (a short crunch); spall and debris,
//   and splash, land around it a little later as scattered small hits.
// - Gelatin: a wet, low thump as the temporary cavity swells, and a slap on the face.

// Free circular plate, nu = 0.3: lambda^2 and whether the mode is axisymmetric (no nodal diameters).
const PLATE_MODES = [[5.253, false], [9.084, true], [12.23, false], [20.52, false], [21.6, false], [33.06, false],
  [35.25, false], [38.55, true], [46.2, false], [52.91, false], [59.86, false], [87.8, true]];
const NU = 0.3;

function mulberry(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class ImpactSound {
  constructor() {
    this.ctx = null;
    this.enabled = true;
    this.volume = 0.7;
  }

  /** Call from a user gesture: browsers only let audio start from one. */
  unlock() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      this.ctx = new Ctx();
      this.out = this.ctx.createDynamicsCompressor();
      this.out.threshold.value = -6;
      this.out.ratio.value = 8;
      this.out.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
  }

  get ready() { return this.enabled && this.ctx && this.ctx.state === "running"; }

  _play(buffer, delay = 0, gain = 1) {
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    const g = this.ctx.createGain();
    g.gain.value = gain * this.volume;
    src.connect(g).connect(this.out);
    src.start(this.ctx.currentTime + Math.max(0, delay));
  }

  _buffer(seconds) {
    const fs = this.ctx.sampleRate;
    return this.ctx.createBuffer(1, Math.max(1, Math.round(seconds * fs)), fs);
  }

  /**
   * A plate hit. p: {thickness, diameter (m), modulus (Pa), density (kg/m^3), loss, energy (J), contact (s: how long the
   * projectile takes to stop or pass), holed (bool), tear (0..1: how much steel is torn), debris (count of pieces
   * flying off), splash (count), seed}.
   */
  plate(p) {
    if (!this.ready) return;
    const rnd = mulberry(p.seed ?? 1);
    const fs = this.ctx.sampleRate;
    const h = p.thickness, a = p.diameter / 2;
    const D = p.modulus * h ** 3 / (12 * (1 - NU * NU));
    const k = Math.sqrt(D / (p.density * h)) / (2 * Math.PI * a * a);
    // Radiation and the chains it hangs from damp it as well as the steel's own loss; a hole more.
    const eta = p.loss + 0.0025 + (p.holed ? 0.006 : 0);
    const level = Math.min(1, 0.12 + 0.11 * Math.log10(Math.max(p.energy, 1)));
    const modes = PLATE_MODES.map(([l2, axi]) => ({ f: l2 * k * (1 + 0.004 * (rnd() - 0.5)), w: axi ? 1 : 0.25 + 0.35 * rnd() }))
      .filter((m) => m.f > 25 && m.f < 16000);
    const t60 = Math.min(4, Math.max(...modes.map((m) => 2.2 / (eta * m.f)), 0.05));
    const buf = this._buffer(t60 + 0.05);
    const d = buf.getChannelData(0);
    // Higher modes are driven harder by a shorter blow: weight by the contact's spectrum.
    const fc = 1 / Math.max(p.contact ?? 1e-4, 2e-6);
    for (const m of modes) {
      const amp = m.w / Math.sqrt(m.f / modes[0].f) / (1 + (m.f / fc) ** 2);
      const decay = 6.9 / (2.2 / (eta * m.f));   // 1/s, amplitude
      const ph = rnd() * 6.283, w = 2 * Math.PI * m.f / fs;
      for (let i = 0; i < d.length; i++) d[i] += amp * Math.exp(-decay * i / fs) * Math.sin(w * i + ph);
    }
    let peak = 0;
    for (let i = 0; i < d.length; i++) peak = Math.max(peak, Math.abs(d[i]));
    for (let i = 0; i < d.length; i++) d[i] *= level / (peak || 1);
    // The click of the contact, and a crunch of tearing steel.
    const click = Math.round(Math.min(0.004, Math.max(3e-4, 3 * (p.contact ?? 1e-4))) * fs);
    let lp = 0;
    for (let i = 0; i < click; i++) {
      const env = Math.exp(-5 * i / click);
      lp += 0.6 * ((rnd() * 2 - 1) - lp);
      d[i] += level * 0.9 * env * lp;
    }
    if (p.tear > 0) {
      const n = Math.round(0.03 * fs);
      for (let i = 0; i < n && i < d.length; i++) {
        const env = Math.exp(-4 * i / n) * (rnd() < 0.3 ? 1 : 0.3);
        d[i] += level * 0.5 * p.tear * env * (rnd() * 2 - 1);
      }
    }
    this._play(buf);
    this._scatter(p.debris ?? 0, 0.03, 0.35, 0.5, rnd);
    this._scatter(p.splash ?? 0, 0.01, 0.12, 0.25, rnd);
  }

  /** Pieces landing around: small, bright, quickly damped tinks, spread over [t0, t1] s. */
  _scatter(count, t0, t1, gain, rnd) {
    const n = Math.min(14, Math.round(Math.sqrt(count) * 2));
    if (!n) return;
    const fs = this.ctx.sampleRate;
    for (let j = 0; j < n; j++) {
      const buf = this._buffer(0.08);
      const d = buf.getChannelData(0);
      const f1 = 2500 + 6000 * rnd(), f2 = f1 * (1.5 + rnd());
      for (let i = 0; i < d.length; i++) {
        const t = i / fs;
        d[i] = (Math.sin(2 * Math.PI * f1 * t) + 0.5 * Math.sin(2 * Math.PI * f2 * t)) * Math.exp(-t * (60 + 60 * rnd()));
      }
      this._play(buf, t0 + (t1 - t0) * rnd() ** 1.5, gain * (0.2 + 0.8 * rnd()) / Math.sqrt(n));
    }
  }

  /** A hit on a gelatin block: energy (J) it leaves in it, cavity (m: the temporary cavity's widest). */
  gel({ energy, cavity, seed = 3 }) {
    if (!this.ready) return;
    const rnd = mulberry(seed);
    const fs = this.ctx.sampleRate;
    const level = Math.min(1, 0.18 + 0.12 * Math.log10(Math.max(energy, 1)));
    // A bigger cavity swells slower and sounds lower.
    const f0 = Math.max(45, Math.min(160, 9 / Math.max(cavity, 0.01)));
    const buf = this._buffer(0.35);
    const d = buf.getChannelData(0);
    let lp = 0, lp2 = 0;
    for (let i = 0; i < d.length; i++) {
      const t = i / fs;
      // Thump: a falling sine; slap: noise, low-passed, very short; then a wet rumble.
      const thump = Math.sin(2 * Math.PI * f0 * t * (1 - 0.6 * Math.min(t / 0.12, 1))) * Math.exp(-t / 0.06);
      lp += 0.35 * ((rnd() * 2 - 1) - lp);
      lp2 += 0.05 * ((rnd() * 2 - 1) - lp2);
      const slap = lp * Math.exp(-t / 0.004);
      const wet = lp2 * Math.exp(-t / 0.08) * 3;
      d[i] = level * (0.9 * thump + 0.6 * slap + 0.4 * wet);
    }
    this._play(buf);
  }
}
