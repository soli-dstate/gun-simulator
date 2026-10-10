// The Target tab: a plate (or a block of ballistic gelatin) downrange, what the shot does to it there, its RHA
// equivalents, and what the round's fills do (terminal.py does the physics).

import { cssVar, drawChart } from "./charts.js";
import { ImpactSound } from "./impactsound.js";
import { bulletMass, fmt, imperial, label, num, onUnits, toDisplay, toSI } from "./units.js";
import { TerminalView } from "./viewer3d/terminal3d.js";

const $ = (id) => document.getElementById(id);
const INCH = 0.0254;
const GEL = "gelatin";
const SUB_CALIBRE = ["apfsds", "apds"];
// Standard AR500 plate thicknesses.
const PLATES = [["1/4", 0.25], ["5/16", 0.3125], ["3/8", 0.375], ["1/2", 0.5], ["5/8", 0.625], ["3/4", 0.75], ["1", 1.0]];
const VERDICTS = {
  stopped: ["STOPPED", "The plate holds, marked no deeper than a scuff in the paint."],
  cratered: ["CRATERED", "The plate stops it, but it is dented: a crater throws splash back and weakens the plate."],
  perforated: ["PERFORATED", "It goes through the plate."],
  ricochet: ["RICOCHET", "Too steep: the round glances off the face."],
  breached: ["BREACHED", "It goes off on the face and the blast tears a hole through the plate."],
  scabbed: ["SCABBED", "The squashed explosive's shock knocks a scab off the back face: it flies off inside at a few hundred m/s."],
  spalled: ["SPALLED", "It doesn't get through, but the back face breaks away: steel flies off behind the plate."],
  dusted: ["DUSTED", "Frangible: it turns to powder on the face, without a crater or splash back."],
  airburst: ["AIRBURST", "The time fuze bursts it in the air before it gets there."],
  "self-destructed": ["SELF-DESTRUCTED", "It destroyed itself in flight before it got there."],
  detonated: ["DETONATED", "Its fuze fires on contact: blast and fragments."],
};
const GEL_VERDICTS = {
  stopped: ["STOPPED", "It comes to rest in the block."],
  through: ["THROUGH", "It goes through 1.5 m of gelatin."],
};
const REGIMES = { rigid: "hard core, stays whole", eroding: "core eroding as it goes", splash: "splashes on the face",
                  jet: "the shaped charge's jet", blast: "goes off on the face" };
const FUZE_WHERE = { face: "on the face", behind: "behind the plate", air: "in the air" };

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
    $("t-material").innerHTML = Object.entries(mats).map(([k, m]) =>
      `<option value="${k}">${m.label}${m.hardness ? ` (${m.hardness} BHN)` : ""}</option>`).join("");
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
    $("t-material").onchange = () => { this.renderMode(); this.schedule(); };
    $("t-fire").onclick = () => { this.sound.unlock(); this.shoot(true); };
    this.sound = new ImpactSound();
    try {
      this.view = new TerminalView($("t-3d"), $("t-3d-inset"), this.sound);
    } catch (e) {
      this.view = null;
      $("t-3d-panel").hidden = true;   // no WebGL 2
    }
    $("t-replay").onclick = () => { this.sound.unlock(); this.view?.replay(); };
    $("t-cut").onchange = (e) => this.view?.setCut(e.target.checked);
    $("t-sound").onchange = (e) => { this.sound.enabled = e.target.checked; if (e.target.checked) this.sound.unlock(); };
    this.renderDistance();
    this.renderMode();
    onUnits(() => { this.renderPlates(); this.renderDistance(); if (this.result) this.show(this.result); });
    window.addEventListener("resize", () => { if (this.result && !$("target-tab").hidden) this.show(this.result); });
  }

  get gel() { return $("t-material").value === GEL; }

  /** Gelatin has no thickness or angle: a block, shot square on. */
  renderMode() {
    $("t-thick-row").hidden = this.gel;
    $("t-angle-row").hidden = this.gel;
    $("t-fire").textContent = this.gel ? "Shoot the block" : "Shoot the plate";
    $("t-section-title").textContent = this.gel ? "The wound track through the block" : "Cross-section through the plate";
    $("t-chart-title").textContent = this.gel ? "Energy it leaves in the block, by depth" : "Penetration against range";
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
      $("t-status").textContent = "Fire the gun first (Range tab), or press Shoot.";
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
    if (r.kind === "gel") return this.showGel(r);
    const [word, why] = VERDICTS[r.verdict] ?? [r.verdict.toUpperCase(), ""];
    const v = $("t-verdict");
    v.className = `verdict ${r.verdict}`;
    const at = r.distance > 0 ? `at ${fmt(r.distance, "length_m")}` : "at the muzzle";
    v.innerHTML = `<div><div class="big">${word}</div><div class="why">${why}</div></div><span class="spacer"></span>
      <div class="muted" style="text-align:right">${fmt(this.thickness, "length_mm", imperial() ? 3 : 1)} ${r.target_label}<br>${at}${r.angle ? `, ${r.angle}° off square` : ""}</div>`;

    const tiles = [];
    const tile = (k, val, s = "", cls = "") => tiles.push(`<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`);
    const mmIn = (m) => fmt(m, "length_mm", imperial() ? 2 : 1);
    tile("Impact velocity", fmt(r.velocity, "velocity"), `${(r.time * 1e3).toFixed(0)} ms after the shot`);
    tile("Impact energy", fmt(r.energy, "energy"), "what arrives");
    tile(`Into ${r.target_label}`, mmIn(r.depth), REGIMES[r.regime] ?? r.regime);
    tile("Round's penetration, RHAe", mmIn(r.rha_depth), "into rolled homogeneous armour");
    tile("This plate in RHAe", mmIn(r.plate_rhae), `${r.efficiency.toFixed(2)}× its ${r.angle ? "line-of-sight " : ""}thickness against this round`);
    if (r.perforated && r.regime !== "jet") {
      tile("Exits at", fmt(r.residual_velocity, "velocity"), r.ballistic_limit ? `it needs ${fmt(r.ballistic_limit, "velocity")} to get through` : "", "bad");
    } else {
      tile("Gets through", mmIn(r.limit_thickness), "the thickest plate it would defeat here");
    }
    const sp = r.spall, spl = r.splash;
    if (sp?.cause) {
      const what = { debris: "Debris behind", shock: "Spall (shock)", bulge: "Spall (bulge)", scab: "Scab" }[sp.cause];
      tile(what, fmt(sp.mass, "mass_g", 1), `${sp.count} pieces at up to ${fmt(sp.velocity, "velocity")}, in a ${Math.round(2 * sp.cone)}° cone`, "bad");
    }
    if (spl) tile("Splash back", fmt(spl.mass, "mass_g", 2), `about ${spl.count} pieces off the face at up to ${fmt(spl.velocity, "velocity")}`, spl.velocity > 150 ? "warn" : "");
    $("t-stats").innerHTML = tiles.join("");
    this.showPayload(r);

    const notes = [];
    if (sp?.cause === "shock") {
      notes.push(["bad", "Spalls", `The impact's shock reflects off the back face as tension (${(sp.back_stress / 1e9).toFixed(1)} GPa against the plate's ${(sp.strength / 1e9).toFixed(1)} GPa spall strength) and tears a layer ${mmIn(sp.thickness)} thick off it.`]);
    } else if (sp?.cause === "bulge") {
      notes.push(["bad", "Spalls", `It nearly gets through: the back face bulges and a dish ${mmIn(sp.diameter)} across cracks off it.`]);
    } else if (sp?.bulge > 0) {
      notes.push(["warn", "Bulges", "It nearly gets through: the back face bulges, though it holds."]);
    }
    if (sp?.cause === "debris") notes.push(["bad", "Behind-armour debris", `The plug and pieces of plate${r.regime === "eroding" ? " and rod" : ""} fly on in a ${Math.round(2 * sp.cone)}° cone.`]);
    if (spl && spl.velocity > 100) notes.push(["warn", "Splash", `Bullet fragments spray off the face, within about ${Math.round(spl.off_face)}° of it, at up to ${fmt(spl.velocity, "velocity")}. Angle the plate down to throw them at the ground.`]);
    const core = r.core;
    const what = { insert: "penetrator", rod: "rod", body: "body", core: "core" }[core.what] ?? "core";
    notes.push(["info", "Penetrator", `${core.label} ${what}, ${fmt(core.mass, "mass_g")}, ${mmIn(core.diameter)} across` +
      (core.what === "insert" || (core.what === "core" && this.gun?.projectile?.jacket_thickness > 0) ? "; the jacket strips off in the plate." : ".") +
      (core.capped ? " A penetrating cap spreads the blow on its nose." : "")]);
    if (core.shatter_speed) {
      notes.push([r.shattered ? "warn" : "info", r.shattered ? "Shatters" : "Shatter speed",
        `A ${core.label} core breaks up on this plate above ${fmt(core.shatter_speed, "velocity")}` +
        (r.shattered ? ": this one does, and goes less deep than it would whole." : ".")]);
    }
    const rng = (m) => fmt(m, "length_m");
    if (r.perforates_to === null) notes.push(["info", "Never gets through", "Not even at the muzzle does it defeat this plate."]);
    else if (r.perforates_to >= r.flown - 1) notes.push(["bad", "Gets through all the way", `It defeats this plate at every range out to ${rng(r.flown)}.`]);
    else notes.push(["bad", "Gets through", `It defeats this plate out to ${rng(r.perforates_to)}. Beyond that the plate holds.`]);
    if (r.craters_to !== null && r.craters_to > 0 && r.verdict !== "dusted") {
      notes.push(["warn", "Craters the plate", `It dents (craters) ${r.target_label} out to ${rng(Math.min(r.craters_to, r.flown))}. Shoot this plate with it from further away than that.`]);
    } else if (r.perforates_to === null) {
      notes.push(["info", "Steel-safe", "It does not crater this plate even at the muzzle (keep the minimum safe distance for splash)."]);
    }
    if (r.ricochet) notes.push(["warn", "Ricochet", "At this angle it skips off the face instead of biting."]);
    notes.push(...this.payloadNotes(r));
    $("t-notes").innerHTML = notes.map(([k, t, x]) => `<li class="${k}"><b>${t}</b>${x}</li>`).join("");

    this.view?.show(r, this.gun);
    this.drawSection(r);
    this.drawChart(r);
  }

  /** Tiles for the fills (explosive, jet, incendiary, tracer) and the parts list. */
  showPayload(r) {
    const pay = r.payload ?? {};
    const tiles = [];
    const tile = (k, val, s = "", cls = "") => tiles.push(`<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`);
    const ch = pay.charges ?? {};
    const fz = pay.fuze ?? {};
    if (fz.type && fz.type !== "none") {
      const state = !fz.armed ? "not armed yet: it hits as a slug" : fz.where ? `goes off ${FUZE_WHERE[fz.where]}` : "does not go off";
      tile("Fuze", fz.type, state + (fz.behind > 0 ? `, ${fmt(fz.behind, "length_m", 2)} behind` : ""), fz.fires ? "bad" : "");
    }
    if (ch.explosive_mass > 0) {
      tile("Explosive", fmt(ch.explosive_mass, "mass_g", 1), `${ch.explosive.map((e) => e[1]).join(", ")}; ${fmt(ch.tnt, "mass_g", 1)} TNT equivalent`);
    }
    if (pay.blast) {
      tile("Blast", fmt(pay.blast.eardrums, "length_m", 1), `eardrums at 35 kPa; lungs within ${fmt(pay.blast.lungs, "length_m", 1)}, windows out to ${fmt(pay.blast.windows, "length_m", 0)}`);
    }
    const f = pay.fragments;
    if (f) {
      tile("Fragments", `${Math.round(f.count).toLocaleString()} × ${bulletMass(f.mean_mass)}`,
        `thrown at ${fmt(f.velocity, "velocity")}; the heaviest carry 80 J to ${fmt(f.lethal_radius, "length_m", 1)}, one per m² to ${fmt(f.dense_radius, "length_m", 1)}`);
    }
    if (pay.jet) {
      const j = pay.jet;
      tile("Shaped-charge jet", fmt(j.depth ?? j.rha_depth, "length_mm", 0),
        `${fmt(j.rha_depth, "length_mm", 0)} RHA; standoff ${j.standoff_cd.toFixed(1)} cone diameters` + (j.spin_factor < 0.99 ? `; spin costs ${Math.round((1 - j.spin_factor) * 100)} %` : ""),
        j.works ? "bad" : "");
    }
    if (pay.scab !== undefined) tile("Scabs plate up to", fmt(pay.scab, "length_mm", 0), "squash head: the shock spalls the back face");
    if (pay.breach !== undefined) tile("Blast breaches up to", fmt(pay.breach, "length_mm", 1), "a contact burst on the face");
    if (pay.incendiary) {
      const inc = pay.incendiary;
      tile("Incendiary", `${(inc.energy / 1e3).toFixed(1)} kJ`, `${fmt(ch.incendiary_mass, "mass_g", 2)}; ${inc.lights ? (inc.carried ? "flashes, and follows it through" : "flashes on the face") : "does not light"}`,
        inc.lights ? "bad" : "");
    }
    if (pay.tracer) {
      tile("Tracer", pay.tracer.colour, `burns ${pay.tracer.burn_time.toFixed(1)} s` +
        (r.tracer_burnout ? `, out at ${fmt(r.tracer_burnout, "length_m")}` : "") + (pay.tracer.alight ? "; still alight here" : "; burnt out here"));
    }
    if (pay.pyrophoric) tile("Pyrophoric", "burns", "its fragments catch fire in the air behind the plate", "bad");
    $("t-payload").innerHTML = tiles.join("");
    const parts = r.parts ?? [];
    $("t-parts").innerHTML = parts.length ? `<tr><th>part</th><th>material</th><th>mass</th></tr>` + parts.map((p) =>
      `<tr><td>${p.role}</td><td>${p.label}</td><td>${bulletMass(p.mass)}</td></tr>`).join("") : "";
    $("t-payload-panel").hidden = !tiles.length && parts.length <= 2;
  }

  payloadNotes(r) {
    const pay = r.payload ?? {}, fz = pay.fuze ?? {}, notes = [];
    const rng = (m) => fmt(m, "length_m");
    if (fz.type && fz.type !== "none" && !fz.armed) {
      notes.push(["warn", "Fuze not armed", `It arms ${rng(this.gun?.projectile?.arming_distance ?? 0)} from the muzzle: closer than that it is only a slug.`]);
    }
    if (fz.airburst) notes.push(["info", "Airburst", `The time fuze bursts it ${fz.airburst.toFixed(2)} s out` + (r.fuze_burst !== null ? `, at ${rng(r.fuze_burst)}` : "") + "."]);
    if (fz.self_destruct) notes.push(["info", "Self-destruct", `It destroys itself ${fz.self_destruct.toFixed(1)} s out` + (r.fuze_burst !== null ? `, at ${rng(r.fuze_burst)}` : "") + ": it never gets here."]);
    if (fz.where === "behind") notes.push(["bad", "Bursts behind the plate", `The ${fz.type === "base" ? "base fuze" : "delay"} sets it off ${fmt(fz.behind, "length_m", 2)} past the back face.`]);
    if (pay.jet && pay.jet.works) {
      notes.push(["bad", "Shaped charge", `The jet reaches ${fmt(pay.jet.depth, "length_mm", 0)} into this plate, whatever the range` +
        (pay.jet.residual > 0 ? `; ${fmt(pay.jet.residual, "length_mm", 0)} of it is left behind the plate.` : ".")]);
    }
    if (pay.pyrophoric) notes.push(["bad", "Depleted uranium", "The rod's fragments burn in the air behind the plate."]);
    if (pay.tracer && pay.tracer.alight && r.perforated) notes.push(["warn", "Tracer", "Still burning as it goes through: it can light fuel behind the plate."]);
    return notes;
  }

  showGel(r) {
    const [word, why] = GEL_VERDICTS[r.verdict] ?? VERDICTS[r.verdict] ?? [r.verdict.toUpperCase(), ""];
    const v = $("t-verdict");
    v.className = `verdict ${r.verdict}`;
    const at = r.distance > 0 ? `at ${fmt(r.distance, "length_m")}` : "at the muzzle";
    v.innerHTML = `<div><div class="big">${word}</div><div class="why">${why}</div></div><span class="spacer"></span>
      <div class="muted" style="text-align:right">${r.target_label}<br>${at} · ${r.construction_label}</div>`;
    const tiles = [];
    const tile = (k, val, s = "", cls = "") => tiles.push(`<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`);
    const cm = (m) => fmt(m, "drop");
    tile("Impact velocity", fmt(r.velocity, "velocity"), `${(r.time * 1e3).toFixed(0)} ms after the shot`);
    tile("Impact energy", fmt(r.energy, "energy"));
    const notes = [];
    if (r.series) {
      tile("Penetration", cm(r.depth), { under: "short of the FBI's 12–18 in", in: "inside the FBI's 12–18 in", over: "past the FBI's 18 in" }[r.fbi], r.fbi === "in" ? "" : "bad");
      tile("Expanded to", fmt(r.expanded_diameter, "length_mm", imperial() ? 3 : 1), `${r.expansion.toFixed(2)}× its diameter`);
      tile("Weight kept", `${(r.retained_share * 100).toFixed(0)} %`, bulletMass(r.retained_mass));
      tile("Temporary cavity", cm(r.temporary_cavity), "widest stretch of the block");
      tile("Most energy", `${fmt(r.peak_dedx * 0.01, "energy")} per cm`, `at ${cm(r.peak_depth)}`);
      if (r.yaw_depth !== null) notes.push(["info", "Yaws", `A slender bullet that doesn't open turns sideways after about ${cm(r.yaw_depth)} (its "neck"), tumbles and tears a wider track.`]);
      if (r.fragmented) notes.push(["warn", "Fragments", `It breaks up at ${cm(r.fragment_depth)}; the fragments fly out from the track and leave much of the energy there.`]);
      if (r.expansion > 1.05) notes.push(["info", "Expands", `It opens to ${r.expansion.toFixed(1)}× its diameter over its first few centimetres.`]);
      else if (r.expansion <= 1.05 && /jhp|hp|jsp|polymer_tip|bonded|monolithic/.test(r.construction)) notes.push(["warn", "Doesn't open", "Too slow here to expand: it goes on like a round nose."]);
      const rec = r.recovered;
      if (rec && rec.yaw > 120) notes.push(["info", "Comes to rest base first", "It turned right round in the block: it is dug out with its base towards the face."]);
      if (rec && rec.petals && rec.expansion > 1.05) notes.push(["info", "Petals", `It opens into ${rec.petals} petals, folded back over its shank.`]);
    }
    $("t-stats").innerHTML = tiles.join("");
    this.showPayload(r);
    notes.push(...this.payloadNotes(r));
    if (r.verdict === "detonated") notes.push(["bad", "Detonates", "An explosive round's fuze fires on the block: see what it carries."]);
    $("t-notes").innerHTML = notes.map(([k, t, x]) => `<li class="${k}"><b>${t}</b>${x}</li>`).join("");
    this.view?.show(r, this.gun);
    this.drawGel(r);
    this.drawGelChart(r);
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
        { label: "gets through (plate it defeats)", color: cssVar("--s4"), x, y: y(s.limit_thickness), dash: true },
        { label: "this plate", color: cssVar("--muted"), x: [x[0], x[x.length - 1]], y: [los, los], dash: true },
      ],
    });
  }

  drawGelChart(r) {
    const s = r.series;
    if (!s) {
      drawChart($("c-pen"), { xlabel: `depth (${label("drop")})`, ylabel: `energy (${label("energy")}/cm)`, series: [] });
      return;
    }
    const x = s.depth.map((m) => toDisplay(m, "drop"));
    drawChart($("c-pen"), {
      xlabel: `depth (${label("drop")})`, ylabel: `energy left per cm (${label("energy")})`,
      series: [{ label: "energy per cm of track", color: cssVar("--s2"), x, y: s.dedx.map((e) => toDisplay(e * 0.01, "energy")) }],
    });
  }

  /** The block from the side: the permanent track (the bullet's width) inside the temporary cavity's stretch. */
  drawGel(r) {
    const canvas = $("t-section");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);
    const muted = cssVar("--muted"), text = cssVar("--text");
    const blockL = Math.max(0.6, Math.min(1.5, (r.depth || 0) * 1.15 + 0.05));
    const k = (W - 40) / blockL, cy = H / 2, x0 = 20;
    // The block.
    ctx.fillStyle = "rgba(214, 170, 110, 0.28)";
    ctx.fillRect(x0, cy - Math.min(0.15 * k, H / 2 - 24), blockL * k, 2 * Math.min(0.15 * k, H / 2 - 24));
    const s = r.series;
    if (s && s.depth.length > 1) {
      const span = Math.min(0.15 * k, H / 2 - 24);
      // The temporary cavity, then the permanent track.
      for (const [arr, style, scale] of [[s.cavity, "rgba(220, 90, 70, 0.25)", 0.5], [s.width, "rgba(140, 30, 25, 0.85)", 0.5]]) {
        ctx.fillStyle = style;
        ctx.beginPath();
        ctx.moveTo(x0, cy);
        s.depth.forEach((d, i) => ctx.lineTo(x0 + d * k, cy - Math.min(Math.max(arr[i] * scale * k, 0.6), span)));
        for (let i = s.depth.length - 1; i >= 0; i--) ctx.lineTo(x0 + s.depth[i] * k, cy + Math.min(Math.max(arr[i] * scale * k, 0.6), span));
        ctx.closePath();
        ctx.fill();
      }
      // FBI window.
      ctx.strokeStyle = muted; ctx.setLineDash([4, 4]);
      for (const d of [0.305, 0.457]) { ctx.beginPath(); ctx.moveTo(x0 + d * k, cy - span - 6); ctx.lineTo(x0 + d * k, cy + span + 6); ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.fillStyle = text; ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "top";
      ctx.fillText(`${fmt(r.depth, "drop")}`, x0 + r.depth * k, cy + span + 6);
    } else {
      ctx.fillStyle = muted; ctx.font = "13px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(r.verdict === "detonated" ? "It goes off on the face of the block." : "It never reaches the block.", W / 2, cy);
    }
    ctx.fillStyle = muted; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.font = "12px system-ui, sans-serif";
    ctx.fillText("to scale · dashed: the FBI's 12–18 in", 8, 6);
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
    const rod = SUB_CALIBRE.includes(p.type);
    const bulletD = rod ? p.penetrator_diameter : gun.barrel.bore_diameter;
    const bulletL = p.length;
    const T = r.line_of_sight, theta = r.angle * Math.PI / 180;
    // Scale: the plate, the depth and the bullet must fit.
    const spanX = bulletL * 1.6 + Math.max(T, Math.min(r.depth, 3 * T + 0.05)) * 1.5 + T * Math.tan(theta) + 0.01;
    const spanY = Math.max(bulletD * 4, T * 1.4, 0.02);
    const k = Math.min((W - 40) / spanX, (H - 50) / spanY);
    const cy = H / 2 - 6;
    const px0 = 20 + bulletL * 1.4 * k;   // where the line of flight meets the plate's face

    // Plate: a slab whose faces lean theta off vertical; the cut shows the steel.
    const half = (H - 40) / 2;
    const tLean = Math.tan(theta) * half;
    const face = (y) => px0 + (cy - y) * Math.tan(theta);   // x of the front face at height y
    ctx.fillStyle = r.target === "aluminium" ? "#9aa1aa" : "#6b7078";
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

    // The hole, crater, channel or jet along the line of flight.
    const r0 = bulletD / 2 * k;
    const depthPx = Math.min(r.depth, T) * k;
    ctx.fillStyle = cssVar("--panel");
    if (r.regime === "jet") {
      const rj = Math.max(1.5, r0 * 0.25);
      ctx.beginPath();
      ctx.moveTo(face(cy - rj * 3) - 1, cy - rj * 3);
      ctx.lineTo(px0 + depthPx, cy - rj * 0.6);
      ctx.lineTo(px0 + depthPx, cy + rj * 0.6);
      ctx.lineTo(face(cy + rj * 3) - 1, cy + rj * 3);
      ctx.closePath(); ctx.fill();
    } else if (r.perforated || r.verdict === "breached") {
      ctx.beginPath();
      const w = r.verdict === "breached" ? 2.2 : 1;
      ctx.moveTo(face(cy - r0 * w) - 1, cy - r0 * 1.15 * w);
      ctx.lineTo(px0 + T * k + 2, cy - r0 * 1.6 * w);
      ctx.lineTo(px0 + T * k + 2, cy + r0 * 1.6 * w);
      ctx.lineTo(face(cy + r0 * w) - 1, cy + r0 * 1.15 * w);
      ctx.closePath(); ctx.fill();
    } else if (r.depth > 0) {
      const w = r.regime === "splash" || r.regime === "blast" ? Math.max(r0 * 1.8, depthPx * 1.6) : r0 * 1.1;
      ctx.beginPath();
      ctx.moveTo(face(cy - w) - 1, cy - w);
      if (r.regime === "splash" || r.regime === "blast") ctx.quadraticCurveTo(px0 + depthPx * 2, cy, face(cy + w) - 1, cy + w);
      else { ctx.lineTo(px0 + depthPx - r0, cy - r0 * 0.9); ctx.quadraticCurveTo(px0 + depthPx + r0 * 0.6, cy, px0 + depthPx - r0, cy + r0 * 0.9); ctx.lineTo(face(cy + w) - 1, cy + w); }
      ctx.closePath(); ctx.fill();
    }
    if (r.verdict === "scabbed") {
      // The scab knocked off the back face.
      const sw = Math.min(T * k * 1.2, half * 0.8), bx = px0 + T * k;
      ctx.fillStyle = "#6b7078";
      ctx.beginPath(); ctx.ellipse(bx + 18, cy, 6, sw / 2, 0, 0, 2 * Math.PI); ctx.fill();
      ctx.fillStyle = cssVar("--panel");
      ctx.beginPath(); ctx.ellipse(bx, cy, Math.min(T * k * 0.3, 10), sw / 2, 0, -Math.PI / 2, Math.PI / 2); ctx.fill();
    }

    // The bullet coming in (or what is left of it going out).
    const drawBullet = (xTip, alpha) => {
      const L = bulletL * k, R = bulletD / 2 * k;
      const nose = Math.min(L * 0.5, (rod ? 3 : 1.3) * R * 2);
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = rod ? "#8b8f96" : p.jacket_material === "steel" ? "#545b3a" : "#c48a52";
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
    const burst = (x, size, color) => {
      ctx.strokeStyle = color; ctx.lineWidth = 1.5;
      for (let a = 0; a < 12; a++) {
        const rad = (a / 12) * 2 * Math.PI;
        ctx.beginPath(); ctx.moveTo(x + Math.cos(rad) * size * 0.3, cy + Math.sin(rad) * size * 0.3);
        ctx.lineTo(x + Math.cos(rad) * size, cy + Math.sin(rad) * size); ctx.stroke();
      }
    };
    const fz = r.payload?.fuze;
    if (r.perforated) {
      const exitX = px0 + T * k + 10;
      ctx.strokeStyle = bad; ctx.fillStyle = bad; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(exitX, cy); ctx.lineTo(Math.min(W - 10, exitX + 60), cy); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(Math.min(W - 10, exitX + 60), cy); ctx.lineTo(Math.min(W - 10, exitX + 60) - 8, cy - 5);
      ctx.lineTo(Math.min(W - 10, exitX + 60) - 8, cy + 5); ctx.fill();
      ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      if (r.regime !== "jet") ctx.fillText(fmt(r.residual_velocity, "velocity"), exitX + 4, cy - 6);
      if (fz?.where === "behind") burst(Math.min(W - 30, exitX + 70), 20, bad);
    } else if (fz?.fires && fz.where === "face") {
      burst(face(cy) - 6, 26, accent);
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
