// The Target tab: a steel plate downrange, what the shot does to it there, and
// its RHA equivalents (terminal.py does the physics).

import { cssVar, drawChart } from "./charts.js";
import { fmt, imperial, label, num, onUnits, toDisplay, toSI } from "./units.js";

const $ = (id) => document.getElementById(id);
const INCH = 0.0254;
// Standard AR500 plate thicknesses.
const PLATES = [["1/4", 0.25], ["5/16", 0.3125], ["3/8", 0.375], ["1/2", 0.5], ["5/8", 0.625], ["3/4", 0.75], ["1", 1.0]];
const VERDICTS = {
  stopped: ["STOPPED", "The plate holds, marked no deeper than a scuff in the paint."],
  cratered: ["CRATERED", "The plate stops it, but it is dented: a crater throws splash back and weakens the plate."],
  perforated: ["PERFORATED", "It goes through the plate."],
  ricochet: ["RICOCHET", "Too steep: the round glances off the face."],
};

export class TargetRange {
  /** getShot(): {gun, muzzle_velocity, atmosphere} of the last shot, or null. ensureShot(): simulates one. */
  constructor(backend, schema, { getShot, ensureShot, onError }) {
    this.backend = backend;
    this.getShot = getShot;
    this.ensureShot = ensureShot;
    this.onError = onError;
    this.thickness = 0.375 * INCH;
    this.distance = imperial() ? 91.44 : 100;   // 100 yd or 100 m
    this.angle = 0;
    this.result = null;
    this.request = 0;
    const mats = schema.targets.materials;
    $("t-material").innerHTML = Object.entries(mats).map(([k, m]) => `<option value="${k}">${m.label} (${m.hardness} BHN)</option>`).join("");
    this.renderPlates();
    $("t-plates").onclick = (e) => {
      const b = e.target.closest("button[data-in]");
      if (!b) return;
      this.thickness = Number(b.dataset.in) * INCH;
      this.renderPlates();
      this.schedule();
    };
    $("t-thick").onchange = () => {
      const si = toSI(Number($("t-thick").value), "length_mm");
      if (si > 0) { this.thickness = si; this.renderPlates(); this.schedule(); }
    };
    $("t-dist-slider").oninput = () => {
      this.distance = Math.round(1000 * Number($("t-dist-slider").value) ** 2 / 5) * 5;
      $("t-dist").value = num(this.distance, "length_m");
      this.schedule(300);
    };
    $("t-dist").onchange = () => {
      this.distance = Math.max(0, Math.min(5000, toSI(Number($("t-dist").value), "length_m")));
      this.renderDistance();
      this.schedule();
    };
    $("t-angle").oninput = () => {
      this.angle = Number($("t-angle").value);
      $("t-angle-label").textContent = `${this.angle}°`;
      this.schedule(300);
    };
    $("t-material").onchange = () => this.schedule();
    $("t-fire").onclick = () => this.shoot(true);
    this.renderDistance();
    onUnits(() => { this.renderPlates(); this.renderDistance(); if (this.result) this.show(this.result); });
    window.addEventListener("resize", () => { if (this.result && !$("target-tab").hidden) this.show(this.result); });
  }

  renderPlates() {
    $("t-plates").innerHTML = PLATES.map(([name, inches]) => {
      const mm = (inches * 25.4).toFixed(1);
      const text = imperial() ? `${name}″` : `${mm} mm`;
      const on = Math.abs(inches * INCH - this.thickness) < 1e-6;
      return `<button data-in="${inches}" aria-pressed="${on}" title="${name}″ = ${mm} mm">${text}</button>`;
    }).join("");
    $("t-thick").value = num(this.thickness, "length_mm", imperial() ? 3 : 2);
  }

  renderDistance() {
    $("t-dist-slider").value = Math.sqrt(Math.min(1, this.distance / 1000));
    $("t-dist").value = num(this.distance, "length_m");
  }

  schedule(delay = 150) {
    if (!this.result) return;   // until the first shot, wait for the button
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.shoot(false), delay);
  }

  /** The gun changed: the last result no longer applies. */
  stale() {
    if (!this.result) return;
    $("t-status").textContent = "The gun has changed: shoot again.";
  }

  async shoot(simulate) {
    const id = ++this.request;
    let shot = this.getShot();
    if (!shot && simulate) {
      $("t-status").innerHTML = '<span class="busy">Simulating the shot…</span>';
      try { shot = await this.ensureShot(); } catch (e) { shot = null; }
      if (id !== this.request) return;
    }
    if (!shot) {
      $("t-status").textContent = "Fire the gun first (Range tab), or press Shoot the plate.";
      return;
    }
    $("t-status").innerHTML = '<span class="busy">Working it out…</span>';
    try {
      const r = await this.backend.target({
        gun: shot.gun, muzzle_velocity: shot.muzzle_velocity, atmosphere: shot.atmosphere,
        distance: this.distance, thickness: this.thickness, angle: this.angle, target: $("t-material").value,
        max_range: Math.max(1000, this.distance * 1.5),
      });
      if (id !== this.request) return;
      this.result = r;
      this.gun = shot.gun;
      this.onError("");
      $("t-status").textContent = "";
      this.show(r);
    } catch (e) {
      if (id !== this.request) return;
      $("t-status").textContent = "";
      this.onError(`Target: ${e.message}`);
    }
  }

  show(r) {
    const [word, why] = VERDICTS[r.verdict];
    const v = $("t-verdict");
    v.className = `verdict ${r.verdict}`;
    const at = r.distance > 0 ? `at ${fmt(r.distance, "length_m")}` : "at the muzzle";
    v.innerHTML = `<div><div class="big">${word}</div><div class="why">${why}</div></div><span class="spacer"></span>
      <div class="muted" style="text-align:right">${fmt(this.thickness, "length_mm", imperial() ? 3 : 1)} ${r.target_label}<br>${at}${r.angle ? `, ${r.angle}° off square` : ""}</div>`;

    const tiles = [];
    const tile = (k, val, s = "", cls = "") => tiles.push(`<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`);
    const mmIn = (m) => fmt(m, "length_mm", imperial() ? 2 : 1);
    tile("Impact velocity", fmt(r.velocity, "velocity"), `${(r.time * 1e3).toFixed(0)} ms after the shot`);
    tile("Impact energy", fmt(r.energy, "energy"), "the whole projectile");
    tile(`Into ${r.target_label}`, mmIn(r.depth), { rigid: "hard core, stays whole", eroding: "core eroding as it goes", splash: "splashes on the face" }[r.regime]);
    tile("Round's penetration, RHAe", mmIn(r.rha_depth), "into rolled homogeneous armour");
    tile("This plate in RHAe", mmIn(r.plate_rhae), `${r.efficiency.toFixed(2)}× its ${r.angle ? "line-of-sight " : ""}thickness against this round`);
    if (r.perforated) {
      tile("Exits at", fmt(r.residual_velocity, "velocity"), r.ballistic_limit ? `it needs ${fmt(r.ballistic_limit, "velocity")} to get through` : "", "bad");
    } else {
      tile("Gets through", mmIn(r.limit_thickness), "the thickest plate it would perforate here");
    }
    $("t-stats").innerHTML = tiles.join("");

    const notes = [];
    const core = r.core;
    notes.push(["info", "Penetrator", `${core.label} core, ${fmt(core.mass, "mass_g")}, ${mmIn(core.diameter)} across` +
      (this.gun?.projectile?.jacket_thickness > 0 ? "; the jacket strips off in the plate." : ".")]);
    const rng = (m) => fmt(m, "length_m");
    if (r.perforates_to === null) notes.push(["info", "Never gets through", `Not even at the muzzle does it perforate this plate.`]);
    else if (r.perforates_to >= r.flown - 1) notes.push(["bad", "Gets through all the way", `It perforates this plate at every range out to ${rng(r.flown)}.`]);
    else notes.push(["bad", "Gets through", `It perforates this plate out to ${rng(r.perforates_to)}. Beyond that the plate holds.`]);
    if (r.craters_to !== null && r.craters_to > 0) {
      notes.push(["warn", "Craters the plate", `It dents (craters) ${r.target_label} out to ${rng(Math.min(r.craters_to, r.flown))}. Shoot this plate with it from further away than that.`]);
    } else if (r.perforates_to === null) {
      notes.push(["info", "Steel-safe", "It does not crater this plate even at the muzzle (keep the minimum safe distance for splash)."]);
    }
    if (r.ricochet) notes.push(["warn", "Ricochet", "At this angle a hard core skips off the face instead of biting."]);
    $("t-notes").innerHTML = notes.map(([k, t, x]) => `<li class="${k}"><b>${t}</b>${x}</li>`).join("");

    this.drawSection(r);
    this.drawChart(r);
  }

  drawChart(r) {
    const s = r.series;
    const x = s.range.map((m) => toDisplay(m, "length_m"));
    const y = (arr) => arr.map((m) => toDisplay(m, "length_mm"));
    const los = toDisplay(r.line_of_sight, "length_mm");
    drawChart($("c-pen"), {
      xlabel: `range (${label("length_m")})`, ylabel: `penetration (${label("length_mm")})`,
      series: [
        { label: `into ${r.target_label}`, color: cssVar("--s2"), x, y: y(s.depth) },
        { label: "into RHA (RHAe)", color: cssVar("--s1"), x, y: y(s.rha_depth) },
        { label: "gets through (plate it perforates)", color: cssVar("--s4"), x, y: y(s.limit_thickness), dash: true },
        { label: "this plate", color: cssVar("--muted"), x: [x[0], x[x.length - 1]], y: [los, los], dash: true },
      ],
    });
  }

  /** The plate cut along the line of flight, at true scale, with the bullet beside it. */
  drawSection(r) {
    const canvas = $("t-section");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    const text = cssVar("--text"), muted = cssVar("--muted"), accent = cssVar("--accent"), bad = cssVar("--error");
    const gun = this.gun;
    const p = gun.projectile;
    const apfsds = p.type === "apfsds";
    const bulletD = apfsds ? p.penetrator_diameter : gun.barrel.bore_diameter;
    const bulletL = p.length;
    const T = r.line_of_sight, theta = r.angle * Math.PI / 180;
    // Scale: the plate, the depth and the bullet must fit.
    const spanX = bulletL * 1.6 + Math.max(T, r.depth) * 1.5 + T * Math.tan(theta) + 0.01;
    const spanY = Math.max(bulletD * 4, T * 1.4, 0.02);
    const k = Math.min((W - 40) / spanX, (H - 50) / spanY);
    const cy = H / 2 - 6;
    const px0 = 20 + bulletL * 1.4 * k;   // where the line of flight meets the plate's face

    // Plate: a slab whose faces lean theta off vertical; the cut shows the steel.
    const half = (H - 40) / 2;
    const tLean = Math.tan(theta) * half;
    const face = (y) => px0 + (cy - y) * Math.tan(theta);   // x of the front face at height y
    ctx.fillStyle = "#6b7078";
    ctx.beginPath();
    ctx.moveTo(px0 + tLean, cy - half);
    ctx.lineTo(px0 + tLean + T * k, cy - half);   // T is along the line of flight, so the back face is T * k behind
    ctx.lineTo(px0 - tLean + T * k, cy + half);
    ctx.lineTo(px0 - tLean, cy + half);
    ctx.closePath();
    ctx.fill();
    // Hatching on the cut face.
    ctx.save(); ctx.clip();
    ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = 1;
    for (let i = -H; i < W + H; i += 7) { ctx.beginPath(); ctx.moveTo(i, cy - half); ctx.lineTo(i + 2 * half, cy + half); ctx.stroke(); }
    ctx.restore();

    // The hole, crater or channel along the line of flight.
    const r0 = bulletD / 2 * k;
    const depthPx = Math.min(r.depth, T) * k;
    ctx.fillStyle = cssVar("--panel");
    if (r.perforated) {
      ctx.beginPath();
      ctx.moveTo(face(cy - r0) - 1, cy - r0 * 1.15);
      ctx.lineTo(px0 + T * k + 2, cy - r0 * 1.6);
      ctx.lineTo(px0 + T * k + 2, cy + r0 * 1.6);
      ctx.lineTo(face(cy + r0) - 1, cy + r0 * 1.15);
      ctx.closePath(); ctx.fill();
    } else if (r.depth > 0) {
      const w = r.regime === "splash" ? Math.max(r0 * 1.8, depthPx * 1.6) : r0 * 1.1;
      ctx.beginPath();
      ctx.moveTo(face(cy - w) - 1, cy - w);
      if (r.regime === "splash") ctx.quadraticCurveTo(px0 + depthPx * 2, cy, face(cy + w) - 1, cy + w);
      else { ctx.lineTo(px0 + depthPx - r0, cy - r0 * 0.9); ctx.quadraticCurveTo(px0 + depthPx + r0 * 0.6, cy, px0 + depthPx - r0, cy + r0 * 0.9); ctx.lineTo(face(cy + w) - 1, cy + w); }
      ctx.closePath(); ctx.fill();
    }

    // The bullet coming in (or what is left of it going out).
    const drawBullet = (xTip, alpha) => {
      const L = bulletL * k, R = bulletD / 2 * k;
      const nose = Math.min(L * 0.5, (apfsds ? 3 : 1.3) * R * 2);
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = apfsds ? "#8b8f96" : "#c48a52";
      ctx.beginPath();
      ctx.moveTo(xTip, cy);
      ctx.quadraticCurveTo(xTip - nose * 0.35, cy - R, xTip - nose, cy - R);
      ctx.lineTo(xTip - L, cy - R);
      ctx.lineTo(xTip - L, cy + R);
      ctx.lineTo(xTip - nose, cy + R);
      ctx.quadraticCurveTo(xTip - nose * 0.35, cy + R, xTip, cy);
      ctx.fill();
      ctx.restore();
    };
    drawBullet(face(cy) - 3, 1);
    ctx.strokeStyle = muted; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(8, cy); ctx.lineTo(face(cy) - bulletL * k - 6, cy); ctx.stroke(); ctx.setLineDash([]);
    if (r.perforated) {
      const exitX = px0 + T * k + 10;
      ctx.strokeStyle = bad; ctx.fillStyle = bad; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(exitX, cy); ctx.lineTo(Math.min(W - 10, exitX + 60), cy); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(Math.min(W - 10, exitX + 60), cy); ctx.lineTo(Math.min(W - 10, exitX + 60) - 8, cy - 5);
      ctx.lineTo(Math.min(W - 10, exitX + 60) - 8, cy + 5); ctx.fill();
      ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      ctx.fillText(fmt(r.residual_velocity, "velocity"), exitX + 4, cy - 6);
    } else if (r.regime === "splash") {
      ctx.strokeStyle = accent; ctx.lineWidth = 1.5;
      for (const a of [-60, -35, -15, 15, 35, 60]) {
        const rad = a * Math.PI / 180, x0 = face(cy) - 4;
        ctx.beginPath(); ctx.moveTo(x0, cy); ctx.lineTo(x0 - Math.cos(rad) * 26, cy + Math.sin(rad) * 26); ctx.stroke();
      }
    }

    // Dimensions.
    ctx.fillStyle = text; ctx.strokeStyle = text; ctx.lineWidth = 1;
    ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "top";
    const yDim = cy + half + 6;
    ctx.beginPath(); ctx.moveTo(px0 - tLean, yDim); ctx.lineTo(px0 - tLean + T * k, yDim); ctx.stroke();
    ctx.fillText(`${fmt(T, "length_mm", imperial() ? 3 : 1)}${r.angle ? " line of sight" : ""}`, px0 - tLean + T * k / 2, yDim + 3);
    if (r.depth > 0 && !r.perforated) {
      ctx.fillStyle = accent; ctx.textBaseline = "bottom";
      ctx.fillText(`${fmt(r.depth, "length_mm", imperial() ? 3 : 1)} deep`, px0 + depthPx / 2, cy - r0 * 2 - 4);
    }
    ctx.fillStyle = muted; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText("to scale", 8, 6);
  }
}
