import { ENVIRONMENTS, PROTECTION, ShotPlayer } from "./audio.js";
import { connect } from "./backend.js";
import { cssVar, drawChart } from "./charts.js";
import { META, SECTIONS, sliderFor } from "./fields.js";
import { FiringRange } from "./viewer3d/range.js";
import { CartridgeViewer } from "./viewer3d/viewer.js";

let backend = null;
let schema = null;
let lastResult = null;
let lastSound = null;
let lastGun = null;      // the gun of the last successful shot (sound is resynthesised for it)
let lastShot = null;     // the result the range animates, for Replay
let soundRequest = 0;    // only the newest synthesis result is used
let soundForShot = null; // which shot the loaded sound belongs to
let playOnLoad = null;   // shot on the range whose sound was not ready when it fired
let rangeClock = null;   // the range's clock {tSim, rate}, while a shot is shown
let shotId = 0;
let cartViewer = null;
let rifleView = null;
let range = null;
let cartridge = null;
let gunVersion = 0;      // bumped on every edit; the range rebuilds when it is behind
let rangeVersion = -1;
let previewMode = "cartridge";
let currentSection = SECTIONS[0].id;
const player = new ShotPlayer();
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

// ---------- form ----------
// Gun fields have ids f-<section>-<key>; sound fields s-<key>.

/** [{id, key (for META), label, unit, scale}] for an editor section. */
function sectionFields(id) {
  if (id.startsWith("sound:")) {
    const group = id.slice(6);
    return schema.sound.fields[group].map(([key, label, unit, scale]) =>
      ({ id: `s-${key}`, key: `sound.${key}`, label, unit, scale }));
  }
  return schema.fields[id].map(([key, label, unit, scale]) =>
    ({ id: `f-${id}-${key}`, key: `${id}.${key}`, label, unit, scale }));
}

const toSlider = (cfg, v) => (cfg.log ? Math.log(v / cfg.min) / Math.log(cfg.max / cfg.min) : (v - cfg.min) / (cfg.max - cfg.min));
const fromSlider = (cfg, f) => (cfg.log ? cfg.min * Math.pow(cfg.max / cfg.min, f) : cfg.min + f * (cfg.max - cfg.min));
const tidy = (v) => Number(v.toPrecision(v !== 0 && Math.abs(v) < 1e-3 ? 3 : 4));

function fieldRow(f) {
  const row = document.createElement("div");
  row.className = "field";
  row.dataset.key = f.key;
  if (f.unit === "choice" || f.unit === "flag") {
    const input = f.unit === "flag" ? `<input type="checkbox" id="${f.id}">`
      : `<select id="${f.id}">${f.scale.map((o) => `<option value="${o}">${o || "none"}</option>`).join("")}</select>`;
    row.innerHTML = `<label for="${f.id}">${f.label}</label>${input}<span></span>
      <div class="help">${META[f.key]?.help ?? ""}</div>`;
    return row;
  }
  row.innerHTML = `<label for="${f.id}">${f.label}</label>
    <input type="number" step="any" id="${f.id}">
    <span class="unit">${f.unit}</span>
    <input type="range" min="0" max="1" step="0.001" aria-label="${f.label}" tabindex="-1">
    <div class="help">${META[f.key]?.help ?? ""}</div>`;
  const num = row.querySelector("input[type=number]"), slider = row.querySelector("input[type=range]");
  let cfg = null;
  // The slider range adapts to the value when the value is typed or loaded.
  row.sync = () => {
    const v = Number(num.value);
    row.classList.toggle("invalid", num.value === "" ? !META[f.key]?.optional : !isFinite(v));
    if (!isFinite(v) || num.value === "") return;
    if (!cfg || v < cfg.min || v > cfg.max) cfg = sliderFor(f.key, v);
    slider.value = toSlider(cfg, v);
  };
  num.addEventListener("input", row.sync);
  slider.addEventListener("input", () => {
    if (!cfg) cfg = sliderFor(f.key, Number(num.value) || 0);
    let v = fromSlider(cfg, Number(slider.value));
    const step = META[f.key]?.step;
    v = step ? Math.round(v / step) * step : tidy(v);
    num.value = Number(v.toPrecision(10));
    row.classList.remove("invalid");
    num.dispatchEvent(new Event("input", { bubbles: true }));
  });
  return row;
}

function buildEditor() {
  const nav = $("sections");
  let group = null;
  for (const sec of SECTIONS) {
    if (sec.group !== group) {
      group = sec.group;
      nav.insertAdjacentHTML("beforeend", `<h4>${group}</h4>`);
    }
    const b = document.createElement("button");
    b.className = "sec";
    b.textContent = sec.title;
    b.dataset.section = sec.id;
    b.onclick = () => showSection(sec.id);
    nav.appendChild(b);
  }
  // Every section is built once and toggled, so all inputs always exist.
  const panel = $("fields");
  for (const sec of SECTIONS) {
    const box = document.createElement("div");
    box.dataset.section = sec.id;
    box.innerHTML = `<h2>${sec.title}</h2><p class="blurb">${sec.blurb}</p>`;
    if (sec.id === "sound:listener") {
      const presets = Object.entries(schema.sound.presets).map(([k, p]) => `<option value="${k}">${p.label}</option>`).join("");
      box.insertAdjacentHTML("beforeend",
        `<div class="preset-row"><label for="listener">Quick pick</label><select id="listener">${presets}<option value="custom">Custom</option></select></div>`);
    }
    for (const f of sectionFields(sec.id)) box.appendChild(fieldRow(f));
    if (sec.id === "sound:listener") {
      const grounds = schema.sound.grounds.map((g) => `<option value="${g}">${g}</option>`).join("");
      box.insertAdjacentHTML("beforeend",
        `<div class="field"><label for="s-ground">Ground</label><select id="s-ground">${grounds}</select><span></span>
         <div class="help">What the sound reflects off between the gun and the listener.</div></div>`);
    }
    panel.appendChild(box);
  }
  showSection(currentSection);
}

function showSection(id) {
  currentSection = id;
  for (const b of document.querySelectorAll("#sections button.sec")) b.setAttribute("aria-selected", b.dataset.section === id);
  for (const box of $("fields").children) box.hidden = box.dataset.section !== id;
  if (id === "barrel") setPreview("rifle");
  else if (id === "case" || id === "projectile") setPreview("cartridge");
}

const syncAll = () => document.querySelectorAll(".field").forEach((row) => row.sync?.());

/** Put an SI config value into its form field. */
function writeField(section, [key, , unit, scale], v) {
  const el = $(`f-${section}-${key}`);
  if (unit === "flag") el.checked = !!v;
  else if (unit === "choice") el.value = typeof v === "number" ? scale[v] : (v ?? "");
  else el.value = v === undefined || v === null ? "" : Number((v / scale).toPrecision(10));
}

/** SI config value of a form field (null for "none" or a blank optional number). */
function readField(section, [key, label, unit, scale]) {
  const el = $(`f-${section}-${key}`);
  if (unit === "flag") return el.checked;
  if (unit === "choice") return el.value || null;
  const raw = el.value;
  if (raw === "" && META[`${section}.${key}`]?.optional) return null;
  if (raw === "" || !isFinite(Number(raw))) throw new Error(`${section}: "${label}" needs a number`);
  return Number(raw) * scale;
}

// Form functions a named grain works out for itself; sent only without one.
const GRAIN_FORM = ["form_chi", "form_lambda", "form_mu", "form_chi_s", "form_lambda_s", "form_z_k"];

/** With a grain chosen, its chi, lambda and mu come from the geometry and can't be typed. */
function syncGrainFields() {
  const fromGrain = !!$("f-propellant-grain").value;
  for (const key of ["form_chi", "form_lambda", "form_mu"]) {
    const row = $(`f-propellant-${key}`).closest(".field");
    row.classList.toggle("derived", fromGrain);
    row.querySelectorAll("input").forEach((el) => { el.disabled = fromGrain; });
  }
}

/** Fill the thermochemistry from the chosen library composition. */
function applyComposition() {
  const values = schema.compositions[$("f-propellant-composition").value];
  if (!values) return;
  for (const f of schema.fields.propellant) if (f[0] in values) writeField("propellant", f, values[f[0]]);
  syncAll();
}

// The last gun loaded, so fields the form doesn't show survive a save or a shot.
let loadedGun = {};

function setGun(gun) {
  loadedGun = structuredClone(gun);
  $("f-name").value = gun.name ?? "";
  for (const [section, fields] of Object.entries(schema.fields)) {
    for (const f of fields) writeField(section, f, gun[section]?.[f[0]]);
  }
  syncAll();
  syncGrainFields();
  gunChanged();
}

function getGun() {
  const gun = structuredClone(loadedGun);
  gun.name = $("f-name").value || "unnamed";
  for (const [section, fields] of Object.entries(schema.fields)) {
    gun[section] = { ...(gun[section] ?? {}) };
    for (const f of fields) gun[section][f[0]] = readField(section, f);
  }
  if (gun.propellant.grain) for (const key of GRAIN_FORM) delete gun.propellant[key];
  return gun;
}

function toToml(gun) {
  const fmt = (v) => (typeof v === "string" ? JSON.stringify(v) : typeof v === "boolean" ? String(v)
    : Number.isInteger(v) && Math.abs(v) < 1e6 ? String(v) : v.toExponential(6).replace(/\.?0+e/, "e"));
  let out = `name = ${JSON.stringify(gun.name)}\n`;
  for (const [section, values] of Object.entries(gun)) {
    if (typeof values !== "object") continue;
    out += `\n[${section}]\n`;
    for (const [k, v] of Object.entries(values)) if (v !== null && v !== undefined) out += `${k} = ${fmt(v)}\n`;
  }
  return out;
}

// ---------- sound settings ----------
function setSound(values) {
  for (const fields of Object.values(schema.sound.fields)) {
    for (const [key, , , scale] of fields) {
      if (values[key] !== undefined) $(`s-${key}`).value = Number((values[key] / scale).toPrecision(10));
    }
  }
  if (values.ground) $("s-ground").value = values.ground;
  syncAll();
}

function getSound() {
  const out = { ground: $("s-ground").value };
  for (const fields of Object.values(schema.sound.fields)) {
    for (const [key, label, , scale] of fields) {
      const raw = $(`s-${key}`).value;
      if (raw === "" || !isFinite(Number(raw))) throw new Error(`sound: "${label}" needs a number`);
      out[key] = Number(raw) * scale;
    }
  }
  return out;
}

function applyListenerPreset() {
  const key = $("listener").value;
  if (key === "custom") return;
  const { label, ...preset } = schema.sound.presets[key];
  setSound({ ...preset });
  resynthesize();
}

let resynthTimer = null;
function resynthesize() {
  clearTimeout(resynthTimer);
  if (!lastGun || !$("sound-on").checked) return;
  resynthTimer = setTimeout(() => synthesizeSound(lastGun, soundForShot), 250);
}

// ---------- sound ----------
function playOptions() {
  // A burst the action simulated plays at its own shot times.
  const times = lastShot?.action?.shot_times;
  return {
    shots: Math.round(Number($("shots").value) || 1),
    rpm: Number($("rpm").value) || 600,
    times: times && times.length > 1 ? times : null,
    level: $("level-mode").value,
    fullScaleDb: Number($("full-scale").value) || 150,
    drive: Number($("drive").value),
    volume: Number($("volume").value),
  };
}

function play() {
  try {
    player.unlock();
    player.play(playOptions());
  } catch (e) {
    $("sound-status").textContent = e.message;
  }
}

/** Synthesise the sound for a gun; shot is the id of the shot it goes with. */
async function synthesizeSound(gun, shot) {
  const id = ++soundRequest;
  const status = $("sound-status");
  let settings;
  try { settings = getSound(); } catch (e) { status.textContent = e.message; return; }
  status.textContent = "Synthesising…";
  try {
    const data = await backend.synthesize({ gun, sound: settings });
    if (id !== soundRequest) return;  // a newer request superseded this one
    lastSound = data;
    soundForShot = shot;
    player.load(data);
    $("play").disabled = false;
    status.textContent = `${(player.shot.left.length / data.sample_rate).toFixed(2)} s at ${data.sample_rate / 1000} kHz`;
    showSoundStats(data);
    drawAll();
    // The range already fired this shot: join its clock where it is now.
    if (playOnLoad !== null && playOnLoad === shot && player.ctx && range?.shot) syncSound(range.shot.result);
    playOnLoad = null;
  } catch (e) {
    if (id !== soundRequest) return;
    status.textContent = "";
    showError(`Sound: ${e.message}`);
  }
}

function showSoundStats(data) {
  const s = data.stats;
  const ms = (t) => `${(t * 1e3).toFixed(1)} ms`;
  const crack = s.crack
    ? `<span>Supersonic crack</span><span>Mach ${s.crack.mach.toFixed(2)} at emission, ${s.crack.miss_distance.toFixed(1)} m miss distance, ${(s.crack.duration * 1e6).toFixed(0)} µs N-wave</span>`
    : `<span>Supersonic crack</span><span>${s.muzzle_mach > 1 ? "not heard here (outside the Mach cone)" : "none (subsonic)"}</span>`;
  const events = data.events.map((e) =>
    `<span>${e.name}</span><span>${ms(e.time)}</span><span>${e.peak_db.toFixed(1)} dB</span>`).join("");
  $("sound-out").innerHTML = `
    <div class="stats">
      <span>Peak at the listener</span><span>${s.peak_db.toFixed(1)} dB (${s.peak_pressure.toFixed(0)} Pa)</span>
      <span>Left / right ear</span><span>${s.peak_left_db.toFixed(1)} / ${s.peak_right_db.toFixed(1)} dB</span>
      <span>Listener distance</span><span>${s.distance.toFixed(2)} m at ${s.angle.toFixed(0)}°</span>
      <span>Blast at 1 m (omnidirectional)</span><span>${s.blast_1m_db.toFixed(1)} dB</span>
      <span>Muzzle exit pressure</span><span>${(s.muzzle_exit_pressure / 1e6).toFixed(1)} MPa</span>
      <span>Gas ejected after the projectile</span><span>${(s.ejected_gas * 1e3).toFixed(2)} g, ${(s.ejected_energy / 1e3).toFixed(1)} kJ</span>
      <span>Recoil impulse (incl. gas jet)</span><span>${s.recoil_impulse.toFixed(2)} N·s</span>
      ${crack}
    </div>
    <div class="events"><span><b>Arrivals</b></span><span>after shot</span><span>peak</span>${events}</div>
    <div class="note">Peaks are unweighted (dBZ). Above about 140 dB peak, unprotected exposure risks permanent hearing damage.</div>`;
}

// ---------- editor previews ----------
function gunChanged() {
  gunVersion++;
  updatePreview();
}

function updatePreview() {
  let gun;
  try {
    gun = getGun();
    $("editor-status").textContent = "";
  } catch (e) {
    $("editor-status").textContent = e.message;
    return;  // half-typed form: keep the last good shape
  }
  const warnings = [];
  if (cartViewer) {
    cartridge = cartViewer.setGun(gun);
    warnings.push(...cartridge.warnings);
  }
  let rifle = null;
  if (rifleView) {
    rifle = rifleView.setGun(gun);
    if (previewMode === "rifle") warnings.push(...rifle.warnings.filter((w) => !warnings.includes(w)));
  }
  $("preview-warnings").textContent = warnings.join(" · ");
  $("burst").disabled = (gun.action?.type ?? "bolt") === "bolt";
  showDerived(gun, rifle);
}

function showDerived(gun, rifle) {
  const rows = [];
  const fromCase = gun.barrel.chamber_shape === "case" && cartridge;
  const chamber = fromCase ? cartridge.stats.powderSpace : gun.barrel.chamber_volume * 1e6;
  let mismatch = false;
  if (cartridge) {
    const s = cartridge.stats;
    mismatch = !fromCase && Math.abs(s.powderSpace - chamber) > 0.1 * chamber;
    rows.push(["Case capacity", `${s.capacity.toFixed(2)} cm³`]);
    rows.push(["Space under the projectile", `${s.powderSpace.toFixed(2)} cm³`, mismatch]);
  }
  rows.push(["Chamber volume (solver)", `${chamber.toFixed(2)} cm³`]);
  const solid = gun.propellant.charge_mass / gun.propellant.density * 1e6;
  rows.push(["Powder fills", `${(solid / chamber * 100).toFixed(0)} % of the chamber`, solid >= chamber]);
  rows.push(["Loading density", `${(gun.propellant.charge_mass * 1e3 / chamber).toFixed(2)} g/cm³`]);
  const boreVol = Math.PI * gun.barrel.bore_diameter ** 2 / 4 * gun.barrel.travel * 1e6;
  rows.push(["Expansion ratio", `${((chamber + boreVol) / chamber).toFixed(1)}`]);
  rows.push(["Charge / projectile mass", `${(gun.propellant.charge_mass / gun.projectile.mass).toFixed(2)}`]);
  if (rifle) rows.push(["Barrel length (bolt face to muzzle)", `${rifle.layout.muzzleX.toFixed(0)} mm`]);
  if (cartridge) rows.push(["Projectile density", `${cartridge.stats.density.toFixed(1)} g/cm³`]);
  const pr = gun.propellant;
  if (!pr.grain && !(pr.form_z_k > 1)) {  // a grain, or a sliver phase, finishes the burn itself
    const psi = pr.form_chi * (1 + pr.form_lambda + (pr.form_mu ?? 0));
    if (Math.abs(psi - 1) > 1e-6) rows.push(["Form function χ·(1+λ+μ)", `${psi.toFixed(3)} (must be 1)`, true]);
  }
  $("derived-stats").innerHTML = rows.map(([k, v, warn]) => `<span>${k}</span><span class="${warn ? "warn" : ""}">${v}</span>`).join("");
  $("use-capacity").hidden = !mismatch;
}

function setPreview(mode) {
  if (mode === "rifle" && !rifleView) mode = "cartridge";
  if (mode === "cartridge" && !cartViewer) mode = "rifle";
  previewMode = mode;
  $("pv-cartridge").setAttribute("aria-pressed", mode === "cartridge");
  $("pv-rifle").setAttribute("aria-pressed", mode === "rifle");
  $("cartridge-view").hidden = mode !== "cartridge";
  $("rifle-view").hidden = mode !== "rifle";
  $("pv-pull-wrap").hidden = mode !== "cartridge";
  updatePreview();
}

function initPreviews() {
  const failed = [];
  try { cartViewer = new CartridgeViewer($("cartridge-view")); } catch (e) { failed.push(e.message); }
  try {
    rifleView = new FiringRange($("rifle-view"));
    rifleView.setCameraMode("rifle");
  } catch (e) { failed.push(e.message); }
  if (failed.length) $("preview-warnings").textContent = `3D view unavailable: ${failed[0]}`;
  $("pv-cartridge").onclick = () => setPreview("cartridge");
  $("pv-rifle").onclick = () => setPreview("rifle");
  $("pv-cutaway").onchange = (e) => { cartViewer?.setCutaway(e.target.checked); rifleView?.setCutaway(e.target.checked); };
  $("pv-pull").onchange = (e) => cartViewer?.setPulled(e.target.checked);
  $("use-capacity").onclick = () => {
    if (!cartridge) return;
    $("f-barrel-chamber_volume").value = Number(cartridge.stats.powderSpace.toPrecision(4));
    syncAll();
    gunChanged();
  };
}

// ---------- firing range ----------
// Display s per simulated ms, or 0 for real time.
const slowMotion = () => $("realtime").checked ? 0 : 0.2 * Math.pow(100, Number($("slowmo").value));

/** Start the sound of the shot on the range, following its clock. */
function syncSound(result) {
  if (!$("sound-on").checked) return;
  try {
    player.unlock();
    player.startSync(result.action?.shot_times ?? [0], playOptions());
    if (rangeClock) player.syncTo(rangeClock.tSim, rangeClock.rate);
  } catch (e) {
    $("sound-status").textContent = e.message;
  }
}

function initRange() {
  try {
    range = new FiringRange($("range"), {
      hud: $("hud"),
      // The sound follows the animation's clock, event by event.
      onShot: (result) => {
        rangeClock = null;
        player.stopSync();
        if (!$("sound-on").checked) return;
        if (soundForShot === shotId && player.ready) syncSound(result);
        else playOnLoad = shotId;
      },
      onClock: (tSim, rate) => {
        rangeClock = { tSim, rate };
        player.syncTo(tSim, rate);
      },
      onChange: () => { $("cycle").disabled = !!range.cycle; },
    });
  } catch (e) {
    $("range-warnings").textContent = `3D view unavailable: ${e.message}`;
    return;
  }
  const showSlow = () => {
    const s = slowMotion();
    range.setSlowMotion(s);
    $("slowmo").disabled = s === 0;
    $("slowmo-label").textContent = s === 0 ? "real time" : `1 ms → ${s < 1 ? s.toFixed(2) : s.toFixed(1)} s`;
  };
  $("slowmo").oninput = showSlow;
  $("realtime").onchange = showSlow;
  $("slowmo-sound").onchange = (e) => { player.stretch = e.target.value === "stretch"; };
  player.stretch = $("slowmo-sound").value === "stretch";
  showSlow();
  $("camera").onchange = (e) => range.setCameraMode(e.target.value);
  if (params.has("camera")) {
    $("camera").value = params.get("camera");
    range.setCameraMode($("camera").value);
  }
  $("cutaway").onchange = (e) => range.setCutaway(e.target.checked);
  $("auto-cycle").onchange = (e) => range.setAutoCycle(e.target.checked);
  $("device-snap").oninput = drawDevice;
  if (params.has("burst")) $("burst").value = params.get("burst");
  range.setCutaway($("cutaway").checked);
  $("cycle").onclick = () => range.startCycle();
  $("replay").onclick = () => {
    if (!lastShot) return;
    unlockAudio();
    range.fire(lastShot);
  };
}

function syncRange() {
  if (!range || rangeVersion === gunVersion) return;
  try {
    const rifle = range.setGun(getGun());
    $("range-warnings").textContent = rifle.warnings.join(" · ");
    rangeVersion = gunVersion;
  } catch (e) {
    $("range-warnings").textContent = e.message;
  }
}

function showTab(name) {
  for (const b of document.querySelectorAll("nav.tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
  $("editor").hidden = name !== "editor";
  $("range-tab").hidden = name !== "range";
  if (name === "range") {
    syncRange();
    requestAnimationFrame(drawAll);
  } else {
    updatePreview();
  }
}

// ---------- charts ----------
function drawAll() {
  if ($("range-tab").hidden) return;
  const colors = ["--s1", "--s2", "--s3", "--s4"].map(cssVar);
  const results = lastResult ? lastResult.results : [];
  const pressure = [], velocity = [], profile = [];
  results.forEach((r, i) => {
    const c = colors[i % colors.length];
    const t = r.time.map((v) => v * 1e3);
    pressure.push({ label: `${r.model} breech`, color: c, x: t, y: r.breech_pressure.map((p) => p / 1e6) });
    pressure.push({ label: `${r.model} base`, color: c, dash: true, x: t, y: r.base_pressure.map((p) => p / 1e6) });
    velocity.push({ label: r.model, color: c, x: r.travel.map((x) => x * 1e3), y: r.velocity });
  });
  const fluid = results.find((r) => r.profiles.length);
  if (fluid) {
    // Up to 4 evenly spread snapshots; colour by order.
    const step = Math.max(1, Math.floor(fluid.profiles.length / 4));
    fluid.profiles.filter((_, i) => i % step === 0).slice(0, 4).forEach((pr, i) => {
      profile.push({ label: `${(pr.time * 1e3).toFixed(3)} ms`, color: colors[i % colors.length],
                     x: pr.x.map((x) => x * 1e3), y: pr.p.map((p) => p / 1e6) });
    });
  }
  const drop = [], flight = [];
  if (lastTraj) {
    drop.push({ label: "drop", color: colors[0], x: lastTraj.range, y: lastTraj.drop.map((y) => y * 100) });
    flight.push({ label: "velocity", color: colors[1], x: lastTraj.range, y: lastTraj.velocity });
  }
  drawChart($("c-drop"), { series: drop, xlabel: "range (m)", ylabel: "drop (cm)", legendBottom: true });
  drawChart($("c-flight"), { series: flight, xlabel: "range (m)", ylabel: "velocity (m/s)" });
  drawChart($("c-pressure"), { series: pressure, xlabel: "time (ms)", ylabel: "pressure (MPa)" });
  drawChart($("c-velocity"), { series: velocity, xlabel: "travel (mm)", ylabel: "velocity (m/s)", legendBottom: true });
  drawChart($("c-profile"), { series: profile, xlabel: "position from seated base (mm)", ylabel: "pressure (MPa)" });

  // Recoil: the animated result's (fluid if run), plus the other model's shoulder force for comparison.
  const motion = [], shoulder = [];
  const shown = results.find((r) => r.model === "fluid" && r.action) || results.find((r) => r.action);
  if (shown) {
    const a = shown.action, t = a.time.map((v) => v * 1e3);
    motion.push({ label: "gun recoil (mm)", color: colors[0], x: t, y: a.recoil.map((v) => v * 1e3) });
    if (a.kind !== "bolt") motion.push({ label: "bolt travel (mm)", color: colors[1], x: t, y: a.bolt.map((v) => v * 1e3) });
    motion.push({ label: "muzzle rise (mrad)", color: colors[2], x: t, y: a.pitch.map((v) => v * 1e3) });
  }
  results.forEach((r, i) => {
    if (!r.action) return;
    const a = r.action;
    const y = a.stance === "shoulder" ? a.shoulder_force : a.recoil_velocity.map((v) => v * 100);
    shoulder.push({ label: r.model, color: colors[i % colors.length], x: a.time.map((v) => v * 1e3), y });
  });
  const free = shown && shown.action.stance !== "shoulder";
  $("c-shoulder-title").textContent = free ? "Free recoil velocity" : "Force on the shooter's shoulder";
  drawChart($("c-motion"), { series: motion, xlabel: "time (ms)", ylabel: "mm · mrad" });
  drawDevice();
  drawChart($("c-shoulder"), { series: shoulder, xlabel: "time (ms)", ylabel: free ? "velocity (cm/s)" : "force (N)" });

  const sound = [], blast = [];
  if (lastSound) {
    const w = lastSound.waveform;
    sound.push({ label: "pressure", color: colors[0], x: w.time.map((t) => t * 1e3), y: w.pressure });
    const nf = lastSound.near_field;
    const t0 = nf.time[0] ?? 0;
    nf.radii.forEach((r, i) => blast.push({ label: `${r.toFixed(2)} m`, color: colors[i % colors.length],
      x: nf.time.map((t) => (t - t0) * 1e3), y: nf.pressure[i].map((p) => p / 1e3) }));
  }
  drawChart($("c-sound"), { series: sound, xlabel: "time after the shot (ms)", ylabel: "pressure (Pa)" });
  drawChart($("c-blast"), { series: blast, xlabel: "time after muzzle exit (ms)", ylabel: "overpressure (kPa)" });
}

// ---------- trajectory (external ballistics) ----------
let lastTraj = null;
let trajRequest = 0;

/** Fly the last shot's projectile downrange from its muzzle velocity and show curves and table. */
async function updateTrajectory() {
  if (!lastGun || !lastResult) return;
  const shot = lastResult.results.find((r) => r.model === "fluid") || lastResult.results[0];
  const num = (id) => Number($(id).value);
  const id = ++trajRequest;
  const payload = {
    gun: lastGun, muzzle_velocity: shot.muzzle_velocity,
    zero_range: num("t-zero"), max_range: num("t-range"), sight_height: num("t-sight") / 1e3, crosswind: num("t-wind"),
  };
  try { const s = getSound(); payload.atmosphere = { temperature: s.temperature, humidity: s.humidity, pressure: s.pressure }; } catch (e) { /* defaults */ }
  try {
    const data = await backend.trajectory(payload);
    if (id !== trajRequest) return;
    lastTraj = data;
    $("traj-status").textContent = `${data.drag_model} BC ${(data.ballistic_coefficient / 703.0696).toFixed(3)} lb/in²` +
      (data.stability ? ` · spin drift included (Sg ${data.stability.toFixed(2)})` : "") +
      (data.stop_reason === "max range" ? "" : ` · flight ended at ${data.max_range.toFixed(0)} m (${data.stop_reason})`);
    const f = (v, d) => v.toFixed(d);
    $("traj-table").innerHTML = "<table><tr><th>range (m)</th><th>drop (cm)</th><th>drop (MOA)</th><th>windage (cm)</th><th>of which spin (cm)</th>" +
      "<th>velocity (m/s)</th><th>energy (J)</th><th>time (s)</th></tr>" +
      data.table.map((r) => `<tr><td>${f(r.range, 0)}</td><td>${f(r.drop * 100, 1)}</td><td>${f(r.drop_moa, 1)}</td>` +
        `<td>${f(r.windage * 100, 1)}</td><td>${f(r.spin_drift * 100, 1)}</td><td>${f(r.velocity, 0)}</td><td>${f(r.energy, 0)}</td><td>${f(r.time, 3)}</td></tr>`).join("") +
      "</table>";
  } catch (e) {
    if (id !== trajRequest) return;
    lastTraj = null;
    $("traj-status").textContent = e.message;
    $("traj-table").innerHTML = "";
  }
  drawAll();
}

// ---------- results ----------
function showCards(data, gun) {
  const cards = $("cards");
  cards.innerHTML = "";
  for (const r of data.results) {
    const card = document.createElement("div");
    card.className = "panel card";
    const status = r.left_muzzle ? "" : '<div class="bad">Projectile did not leave the muzzle</div>';
    card.innerHTML = `<h2>${r.model} model</h2>${status}<div class="stats">
      <span>Muzzle velocity</span><span>${r.muzzle_velocity.toFixed(1)} m/s</span>
      <span>Muzzle energy</span><span>${(0.5 * gun.projectile.mass * r.muzzle_velocity ** 2).toFixed(0)} J</span>
      <span>Time in barrel</span><span>${(r.muzzle_time * 1e3).toFixed(3)} ms</span>
      <span>Peak breech pressure</span><span>${(r.peak_breech_pressure / 1e6).toFixed(1)} MPa</span>
      <span>Charge burnt at exit</span><span>${(r.burnt_at_muzzle * 100).toFixed(1)} %</span>${spinRows(r.spin)}${actionRows(r.action)}${deviceRows(r.device)}</div>
      ${(r.action?.warnings ?? []).map((w) => `<div class="bad">${w}</div>`).join("")}`;
    cards.appendChild(card);
  }
}

/** Card rows for the projectile's spin, if the barrel is rifled. */
function spinRows(s) {
  if (!s || !s.spin_rpm) return "";
  const sg = s.stability;
  const verdict = sg < 1 ? '<span class="bad">unstable</span>' : sg < 1.4 ? "marginal" : "stable";
  return `
      <span>Spin at the muzzle</span><span>${(s.spin_rpm / 1e3).toFixed(0)}k rpm</span>
      <span>Stability S<sub>g</sub></span><span>${sg.toFixed(2)} (${verdict})</span>
      <span>Peak rifling torque</span><span>${s.peak_torque.toFixed(2)} N·m</span>`;
}

/** Card rows for recoil and the action cycle. */
function actionRows(a) {
  if (!a) return "";
  const deg = (rad) => (rad * 180 / Math.PI).toFixed(2);
  let rows = `
      <span>Recoil impulse (incl. gas jet)</span><span>${a.impulse.toFixed(2)} N·s</span>
      <span>Free recoil</span><span>${a.free_recoil_velocity.toFixed(2)} m/s, ${a.free_recoil_energy.toFixed(1)} J</span>`;
  if (a.stance === "shoulder") {
    rows += `
      <span>Into the shoulder</span><span>${(a.max_recoil * 1e3).toFixed(1)} mm, up to ${a.peak_recoil_velocity.toFixed(2)} m/s</span>
      <span>Peak shoulder force</span><span>${a.peak_shoulder_force.toFixed(0)} N</span>`;
  }
  rows += `<span>Muzzle rise</span><span>${deg(a.max_pitch)}°</span>`;
  if (a.kind === "bolt") return rows;
  if (a.shot_times.length > 1) {
    const climb = (a.max_pitch * 180 / Math.PI).toFixed(2);
    rows += `<span>Burst</span><span>${a.shot_times.length} shots in ${((a.shot_times.at(-1) - a.shot_times[0]) * 1e3).toFixed(0)} ms, muzzle climbs to ${climb}°</span>`;
  }
  const ok = a.status === "cycled";
  const kind = a.kind.replace("_", " ");
  rows += `<span>${kind[0].toUpperCase() + kind.slice(1)} action</span><span class="${ok ? "" : "bad"}">${a.status}` +
    (a.cycle_time ? ` in ${(a.cycle_time * 1e3).toFixed(1)} ms (${a.cyclic_rate.toFixed(0)} rounds/min)` : "") + "</span>";
  if (a.rear_speed !== null) rows += `<span>Bolt into the rear stop</span><span>${a.rear_speed.toFixed(1)} m/s</span>`;
  else rows += `<span>Bolt travel</span><span>${(a.bolt_max_travel * 1e3).toFixed(0)} of ${(a.strokes.stroke * 1e3).toFixed(0)} mm</span>`;
  if (a.unlock_pressure !== null) rows += `<span>Chamber pressure at unlock</span><span>${(a.unlock_pressure / 1e6).toFixed(1)} MPa</span>`;
  if (a.gas_peak_pressure !== null) rows += `<span>Peak gas cylinder pressure</span><span>${(a.gas_peak_pressure / 1e6).toFixed(1)} MPa</span>`;
  if (a.port_cd !== null) rows += `<span>Gas port discharge coefficient</span><span>${a.port_cd.toFixed(2)}${a.port_cd_2d ? " (2D)" : " (assumed)"}</span>`;
  return rows;
}

/** Card rows for the muzzle device's 2D solution. */
function deviceRows(d) {
  if (!d) return "";
  return `
      <span>${d.dims.type[0].toUpperCase() + d.dims.type.slice(1)} (2D)</span><span>pushes the gun forwards ${d.impulse.toFixed(2)} N·s</span>
      <span>Peak pressure inside</span><span>${(d.peak_pressure / 1e6).toFixed(2)} MPa</span>
      <span>Heat to its walls</span><span>${d.heat.toFixed(0)} J</span>
      <span>Jet momentum leaving forwards</span><span>${(d.momentum_ratio * 100).toFixed(0)} %</span>`;
}

function showError(msg) {
  const el = $("error");
  el.textContent = msg || "";
  el.style.display = msg ? "block" : "none";
}

function unlockAudio() {
  // Browsers only allow audio to start from a user action, so wake it here.
  if (!$("sound-on").checked) return;
  try { player.unlock(); } catch (e) { $("sound-status").textContent = e.message; }
}

/** Simulate the gun in the editor. animate: show the shot on the range (a user's Fire). */
async function fire(animate = true) {
  showError("");
  if (animate) unlockAudio();
  let gun;
  try { gun = getGun(); } catch (e) { showError(e.message); return; }
  const models = [...document.querySelectorAll("#model-boxes input:checked")].map((b) => b.value);
  if (!models.length) { showError("Select at least one model."); return; }
  syncRange();
  const id = ++shotId;
  // Start the sound right away; it's needed by the time the projectile leaves the muzzle.
  if ($("sound-on").checked) synthesizeSound(gun, id);
  const btn = $("run");
  btn.disabled = true;
  btn.textContent = gun.muzzle_device?.type && gun.muzzle_device.type !== "none" ? "Simulating (2D)…" : "Simulating…";
  try {
    // The sound's air and blowdown time, so the shot and its sound share one bore (and 2D device) run.
    const request = { gun, models, burst: burstCount() };
    try {
      const snd = getSound();
      request.blowdown = snd.blast_time;
      request.ambient_pressure = snd.pressure;
    } catch (e) { /* defaults */ }
    lastResult = await backend.simulate(request);
    showCards(lastResult, gun);
    drawAll();
    lastGun = gun;
    updateTrajectory();
  } catch (e) {
    showError(e.message);
    return;
  } finally {
    btn.disabled = false; btn.textContent = "Fire";
  }
  lastShot = lastResult.results.find((r) => r.model === "fluid") || lastResult.results[0];
  $("replay").disabled = false;
  if (!range) return;
  const at = Number(params.get("at"));
  if (params.has("at") && isFinite(at)) range.seek(lastShot, at);
  else if (animate) range.fire(lastShot);
}

/** Shots per trigger pull: only a self-loading action fires more than one. */
function burstCount() {
  const n = Math.round(Number($("burst").value) || 1);
  return Math.min(30, Math.max(1, n));
}

// ---------- the muzzle device's 2D field ----------
const DEVICE_COLORS = [[0.05, 0.07, 0.25], [0.29, 0.1, 0.5], [0.68, 0.15, 0.42], [0.96, 0.45, 0.2], [0.99, 0.85, 0.35], [1, 1, 0.85]];

function heat(f) {
  const x = Math.min(1, Math.max(0, f)) * (DEVICE_COLORS.length - 1);
  const i = Math.min(Math.floor(x), DEVICE_COLORS.length - 2), w = x - i;
  return DEVICE_COLORS[i].map((c, k) => Math.round(255 * (c + (DEVICE_COLORS[i + 1][k] - c) * w)));
}

/** Draw a pressure snapshot on the device's grid, mirrored about the axis. */
function drawDevice() {
  const shot = lastResult?.results.find((r) => r.device);
  $("device-panel").hidden = $("device-force-panel").hidden = !shot;
  if (!shot) return;
  const d = shot.device, snaps = d.snapshots;
  const slider = $("device-snap");
  slider.max = Math.max(0, snaps.length - 1);
  const k = Math.min(Number(slider.value), snaps.length - 1);
  const snap = snaps[k];
  const canvas = $("c-device");
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const nr = d.kind.length, nx = d.kind[0].length;
  const cell = Math.min(W / nx, (H - 20) / (2 * nr));
  const ox = (W - cell * nx) / 2, oy = (H - 20) / 2;
  const muted = cssVar("--muted");
  const ambient = 101.325;
  for (let j = 0; j < nr; j++) {
    for (let i = 0; i < nx; i++) {
      const kind = d.kind[j][i];
      let rgb;
      if (kind === 1) rgb = [70, 72, 78];
      else if (kind === 2) rgb = [150, 154, 160];
      else {
        const p = snap ? snap.p[j][i] : ambient;
        rgb = heat(Math.log10(Math.max(p, 1) / ambient) / 2.6);  // 1 bar to 400 bar
        if (kind === 3) rgb = rgb.map((c) => Math.round(c * 0.75 + 40));
      }
      ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      ctx.fillRect(ox + i * cell, oy - (j + 1) * cell, cell + 0.5, cell + 0.5);
      ctx.fillRect(ox + i * cell, oy + j * cell, cell + 0.5, cell + 0.5);
    }
  }
  ctx.fillStyle = muted; ctx.font = "12px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "bottom";
  ctx.fillText("1 bar", 4, H - 2);
  for (let q = 0; q <= 40; q++) {
    const [r, g, b] = heat(q / 40);
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fillRect(40 + q * 3, H - 14, 3, 10);
  }
  ctx.fillStyle = muted;
  ctx.fillText("400 bar", 166, H - 2);
  const exitT = shot.muzzle_time;
  $("device-snap-label").textContent = snap
    ? `${((snap.t - exitT) * 1e3).toFixed(2)} ms after exit · ${d.dims.type}, ${(d.dims.h * 1e3).toFixed(2)} mm cells`
    : "";
  drawChart($("c-device-force"), {
    series: [{ label: "forwards (against recoil)", color: cssVar("--s1"), x: d.t.map((t) => (t - exitT) * 1e3), y: d.force }],
    xlabel: "time after exit (ms)", ylabel: "force (N)",
  });
}

// ---------- setup ----------
async function init() {
  try {
    backend = await connect();
    schema = await backend.schema();
  } catch (e) {
    showError(e.message);
    return;
  }
  buildEditor();
  for (const [key, env] of Object.entries(ENVIRONMENTS)) $("environment").add(new Option(env.label, key));
  for (const [key, p] of Object.entries(PROTECTION)) $("protection").add(new Option(p.label, key));
  $("environment").value = player.environment;
  $("protection").value = player.protection;
  setSound({ ...schema.sound.defaults, ...schema.sound.presets.shooter });
  $("listener").value = "shooter";
  initPreviews();
  initRange();

  const preset = $("preset");
  for (const name of Object.keys(schema.presets)) preset.add(new Option(schema.presets[name].name, name));
  preset.onchange = () => setGun(schema.presets[preset.value]);
  if (schema.presets[params.get("preset")]) preset.value = params.get("preset");
  if (preset.options.length) setGun(schema.presets[preset.value]);

  $("model-boxes").innerHTML = schema.models
    .map((m) => `<label><input type="checkbox" value="${m}" checked> ${m}</label>`).join(" ");

  for (const id of ["t-zero", "t-range", "t-sight", "t-wind"]) $(id).onchange = updateTrajectory;
  for (const b of document.querySelectorAll("nav.tabs button")) b.onclick = () => showTab(b.dataset.tab);
  $("go-range").onclick = () => showTab("range");
  let pending = false;
  const gunForm = (e) => {
    if (!e.target.id?.startsWith("f-")) return;
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; gunChanged(); });
  };
  $("fields").addEventListener("input", gunForm);
  $("f-name").addEventListener("input", gunForm);
  $("f-propellant-grain").addEventListener("change", syncGrainFields);
  $("f-propellant-composition").addEventListener("change", applyComposition);
  $("fields").addEventListener("input", (e) => {
    if (!e.target.id?.startsWith("s-")) return;
    $("listener").value = "custom";
    resynthesize();
  });
  $("listener").onchange = applyListenerPreset;

  $("run").onclick = () => fire(true);
  $("play").onclick = play;
  $("sound-on").onchange = (e) => { if (e.target.checked) resynthesize(); };
  $("environment").onchange = (e) => player.setEnvironment(e.target.value);
  $("protection").onchange = (e) => player.setProtection(e.target.value);
  $("level-mode").onchange = (e) => {
    $("full-scale-wrap").hidden = e.target.value !== "calibrated";
    $("drive-wrap").hidden = e.target.value !== "recorded";
  };
  $("save-btn").onclick = async () => {
    try {
      const gun = getGun();
      await backend.saveToml(toToml(gun), (gun.name.replace(/[^\w.-]+/g, "_") || "gun") + ".toml");
    } catch (e) {
      showError(e.message);
    }
  };
  $("load-btn").onclick = () => $("file").click();
  $("file").onchange = async (ev) => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    try {
      setGun(await backend.parse(await file.text()));
      showError("");
    } catch (e) {
      showError(`${file.name}: ${e.message}`);
    }
  };
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(e.target.tagName);
    if ($("range-tab").hidden || typing) return;
    if (e.key === "Enter") fire(true);
    // Space replays the sound.
    if (e.key === " " && player.ready) {
      e.preventDefault();
      play();
    }
  });
  window.addEventListener("resize", drawAll);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);

  showTab(params.get("tab") === "range" ? "range" : "editor");
  // Fill in the results for the first preset without animating it.
  if (preset.options.length) fire(params.has("at"));
}
init();
