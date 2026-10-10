import { ENVIRONMENTS, PROTECTION, ShotPlayer } from "./audio.js";
import { connect } from "./backend.js";
import { cssVar, drawChart } from "./charts.js";
import { EasyMode } from "./easy.js";
import { META, SECTIONS, sliderFor } from "./fields.js";
import { TargetRange } from "./target.js";
import { bindUnitInputs, fieldUnit, fmt, getSystem, imperial, label, onUnits, savedSystem, setSystem, siOf, toDisplay } from "./units.js";
import { FiringRange } from "./viewer3d/range.js";
import { CartridgeViewer } from "./viewer3d/viewer.js";

let backend = null;
let schema = null;
let lastResult = null;
let lastSound = null;
let lastGun = null;      // the gun of the last successful shot (sound is resynthesised for it)
let lastShot = null;     // the result the range animates, for Replay
let lastRequest = null;  // what it was simulated with (burst, air), so a replay can re-run its cycle
let soundRequest = 0;    // only the newest synthesis result is used
let soundForShot = null; // which shot the loaded sound belongs to
let playOnLoad = null;   // shot on the range whose sound was not ready when it fired
let rangeClock = null;   // the range's clock {tSim, rate}, while a shot is shown
let shotId = 0;
let cartViewer = null;
let rifleView = null;
let range = null;
let cartridge = null;
let easy = null;
let target = null;
let gunVersion = 0;      // bumped on every edit; the range rebuilds when it is behind
let rangeVersion = -1;
let shotVersion = -1;    // the gun version the last shot was fired with
let previewMode = "cartridge";
let currentSection = SECTIONS[0].id;
let mode = "easy";
let currentTab = "workshop";
const player = new ShotPlayer();
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } };
const recall = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };

// ---------- form ----------
// Gun fields have ids f-<section>-<key>; sound fields s-<key>.

/** [{id, key (for META), label, unit, scale}] for an editor section. */
function sectionFields(id) {
  if (id.startsWith("sound:")) {
    const group = id.slice(6);
    return schema.sound.fields[group].map(([key, label, unit, scale]) =>
      ({ id: `s-${key}`, key: `sound.${key}`, label, unit, scale, sound: true }));
  }
  return schema.fields[id].map(([key, label, unit, scale]) =>
    ({ id: `f-${id}-${key}`, key: `${id}.${key}`, label, unit, scale }));
}

const toSlider = (cfg, v) => (cfg.log ? Math.log(v / cfg.min) / Math.log(cfg.max / cfg.min) : (v - cfg.min) / (cfg.max - cfg.min));
const fromSlider = (cfg, f) => (cfg.log ? cfg.min * Math.pow(cfg.max / cfg.min, f) : cfg.min + f * (cfg.max - cfg.min));
const tidy = (v) => Number(v.toPrecision(v !== 0 && Math.abs(v) < 1e-3 ? 3 : 4));

/** Display unit of a gun field now (sound fields stay metric). */
const unitOf = (f) => (f.sound ? { unit: f.unit, scale: f.scale, factor: 1 } : fieldUnit(f.unit, f.scale));

/** Slider settings in display units: META's ranges are metric. */
function sliderCfg(f, v) {
  const { factor } = unitOf(f);
  const m = sliderFor(f.key, v * factor);
  return { ...m, min: m.min / factor, max: m.max / factor, step: factor === 1 ? m.step : undefined };
}

function fieldRow(f) {
  const row = document.createElement("div");
  row.className = "field";
  row.dataset.key = f.key;
  if (f.unit === "choice" || f.unit === "flag") {
    const input = f.unit === "flag" ? `<input type="checkbox" id="${f.id}">`
      : `<select id="${f.id}">${f.scale.map((o) => `<option value="${o}">${o ? o.replaceAll("_", " ") : "none"}</option>`).join("")}</select>`;
    row.innerHTML = `<label for="${f.id}">${f.label}</label>${input}<span></span>
      <div class="help">${META[f.key]?.help ?? ""}</div>`;
    return row;
  }
  row.innerHTML = `<label for="${f.id}">${f.label}</label>
    <input type="number" step="any" id="${f.id}">
    <span class="unit">${unitOf(f).unit}</span>
    <input type="range" min="0" max="1" step="0.001" aria-label="${f.label}" tabindex="-1">
    <div class="help">${META[f.key]?.help ?? ""}</div>`;
  const num = row.querySelector("input[type=number]"), slider = row.querySelector("input[type=range]");
  let cfg = null;
  // The slider range adapts to the value when the value is typed or loaded.
  row.sync = () => {
    const v = Number(num.value);
    row.classList.toggle("invalid", num.value === "" ? !META[f.key]?.optional : !isFinite(v));
    if (!isFinite(v) || num.value === "") return;
    if (!cfg || v < cfg.min || v > cfg.max) cfg = sliderCfg(f, v);
    slider.value = toSlider(cfg, v);
  };
  row.resetUnits = () => {
    cfg = null;
    row.querySelector(".unit").textContent = unitOf(f).unit;
  };
  num.addEventListener("input", row.sync);
  slider.addEventListener("input", () => {
    if (!cfg) cfg = sliderCfg(f, Number(num.value) || 0);
    let v = fromSlider(cfg, Number(slider.value));
    v = cfg.step ? Math.round(v / cfg.step) * cfg.step : tidy(v);
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
function writeField(section, [key, label, unit, scale], v) {
  const el = $(`f-${section}-${key}`);
  if (unit === "flag") el.checked = !!v;
  else if (unit === "choice") el.value = typeof v === "number" ? scale[v] : (v ?? "");
  else el.value = v === undefined || v === null ? "" : Number((v / fieldUnit(unit, scale).scale).toPrecision(10));
}

/** SI config value of a form field (null for "none" or a blank optional number). */
function readField(section, [key, label, unit, scale]) {
  const el = $(`f-${section}-${key}`);
  if (unit === "flag") return el.checked;
  if (unit === "choice") return el.value || null;
  const raw = el.value;
  if (raw === "" && META[`${section}.${key}`]?.optional) return null;
  if (raw === "" || !isFinite(Number(raw))) throw new Error(`${section}: "${label}" needs a number`);
  return Number(raw) * fieldUnit(unit, scale).scale;
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
  const fmtv = (v) => (typeof v === "string" ? JSON.stringify(v) : typeof v === "boolean" ? String(v)
    : Number.isInteger(v) && Math.abs(v) < 1e6 ? String(v) : v.toExponential(6).replace(/\.?0+e/, "e"));
  let out = `name = ${JSON.stringify(gun.name)}\n`;
  for (const [section, values] of Object.entries(gun)) {
    if (typeof values !== "object") continue;
    out += `\n[${section}]\n`;
    for (const [k, v] of Object.entries(values)) if (v !== null && v !== undefined) out += `${k} = ${fmtv(v)}\n`;
  }
  return out;
}

/** The units changed: relabel every field and rewrite its value in the new units. */
function unitsChanged() {
  let gun = null;
  try { gun = getGun(); } catch (e) { /* half-typed: keep the loaded one */ }
  for (const row of document.querySelectorAll(".field")) row.resetUnits?.();
  if (gun) {
    loadedGun = gun;
    for (const [section, fields] of Object.entries(schema.fields)) for (const f of fields) writeField(section, f, gun[section]?.[f[0]]);
  }
  syncAll();
  for (const b of document.querySelectorAll("#units-seg button")) b.setAttribute("aria-pressed", b.dataset.units === getSystem());
  updatePreview();
  if (lastResult) { showCards(lastResult, lastGun); showSummary(lastResult, lastGun); }
  if (lastSound) showSoundStats(lastSound);
  if (lastTraj) showTrajTable(lastTraj);
  drawAll();
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

function atmosphere() {
  try {
    const s = getSound();
    return { temperature: s.temperature, humidity: s.humidity, pressure: s.pressure };
  } catch (e) { return null; }
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
    player.play(playOptions()).catch((e) => { $("sound-status").textContent = e.message; });
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
  status.innerHTML = '<span class="busy">Synthesising…</span>';
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
  const dist = imperial() ? `${(s.distance / 0.3048).toFixed(1)} ft` : `${s.distance.toFixed(2)} m`;
  const crack = s.crack
    ? `<span>Supersonic crack</span><span>Mach ${s.crack.mach.toFixed(2)} at emission, ${s.crack.miss_distance.toFixed(1)} m miss distance, ${(s.crack.duration * 1e6).toFixed(0)} µs N-wave</span>`
    : `<span>Supersonic crack</span><span>${s.muzzle_mach > 1 ? "not heard here (outside the Mach cone)" : "none (subsonic)"}</span>`;
  const events = data.events.map((e) =>
    `<span>${e.name}</span><span>${ms(e.time)}</span><span>${e.peak_db.toFixed(1)} dB</span>`).join("");
  $("sound-out").innerHTML = `
    <div class="stats">
      <span>Peak at the listener</span><span>${s.peak_db.toFixed(1)} dB (${s.peak_pressure.toFixed(0)} Pa)</span>
      <span>Left / right ear</span><span>${s.peak_left_db.toFixed(1)} / ${s.peak_right_db.toFixed(1)} dB</span>
      <span>Listener distance</span><span>${dist} at ${s.angle.toFixed(0)}°</span>
      <span>Blast at 1 m (omnidirectional)</span><span>${s.blast_1m_db.toFixed(1)} dB</span>
      <span>Muzzle exit pressure</span><span>${fmt(s.muzzle_exit_pressure, "pressure", 1)}</span>
      <span>Gas ejected after the projectile</span><span>${(s.ejected_gas * 1e3).toFixed(2)} g, ${(s.ejected_energy / 1e3).toFixed(1)} kJ</span>
      <span>Recoil impulse (incl. gas jet)</span><span>${fmt(s.recoil_impulse, "impulse")}</span>
      ${crack}
    </div>
    <div class="events"><span><b>Arrivals</b></span><span>after shot</span><span>peak</span>${events}</div>
    <div class="note">Peaks are unweighted (dBZ). Above about 140 dB peak, unprotected exposure risks permanent hearing damage.</div>`;
}

// ---------- workshop previews ----------
function gunChanged() {
  gunVersion++;
  updatePreview();
  target?.stale();
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
  const kind = gun.action?.type ?? "bolt";
  $("burst").disabled = kind === "bolt";
  // The hand-cycle button names what it works: a revolver's hammer, a pistol's slide, or a bolt.
  const pistol = ["1911", "beretta", "polymer"].includes(gun.appearance?.style) && kind !== "revolver";
  $("cycle").textContent = kind === "revolver" ? "Cock hammer" : pistol ? "Rack slide" : "Cycle bolt";
  $("cycle").title = kind === "revolver" ? "Cock the hammer: the hand turns the next chamber up under it"
    : "Work the bolt: eject and chamber a new round (clears a jam)";
  $("reload").title = kind === "revolver" ? (gun.feed?.loading === "gate"
    ? "Open the loading gate and reload a chamber at a time" : "Swing the cylinder out, eject, and speedload it")
    : "Change the magazine (or belt) for a full one";
  showDerived(gun, rifle);
}

function showDerived(gun, rifle) {
  const rows = [];
  const fromCase = gun.barrel.chamber_shape === "case" && cartridge;
  const chamber = fromCase ? cartridge.stats.powderSpace : gun.barrel.chamber_volume * 1e6;
  let mismatch = false;
  const vol = (cm3) => fmt(cm3 * 1e-6, "volume");
  if (cartridge) {
    const s = cartridge.stats;
    mismatch = !fromCase && Math.abs(s.powderSpace - chamber) > 0.1 * chamber;
    rows.push(["Case capacity", vol(s.capacity)]);
    rows.push(["Space under the projectile", vol(s.powderSpace), mismatch]);
  }
  rows.push(["Chamber volume (solver)", vol(chamber)]);
  const solid = gun.propellant.charge_mass / gun.propellant.density * 1e6;
  rows.push(["Powder fills", `${(solid / chamber * 100).toFixed(0)} % of the chamber`, solid >= chamber]);
  rows.push(["Loading density", `${(gun.propellant.charge_mass * 1e3 / chamber).toFixed(2)} g/cm³`]);
  const boreVol = Math.PI * gun.barrel.bore_diameter ** 2 / 4 * gun.barrel.travel * 1e6;
  rows.push(["Expansion ratio", `${((chamber + boreVol) / chamber).toFixed(1)}`]);
  rows.push(["Charge / projectile mass", `${(gun.propellant.charge_mass / gun.projectile.mass).toFixed(2)}`]);
  if (rifle) rows.push(["Barrel length (bolt face to muzzle)", fmt(rifle.layout.muzzleX * 1e-3, "length_mm", imperial() ? 2 : 0)]);
  if (cartridge) rows.push(["Projectile density", `${cartridge.stats.density.toFixed(1)} g/cm³`]);
  const pr = gun.propellant;
  if (!pr.grain && !(pr.form_z_k > 1)) {  // a grain, or a sliver phase, finishes the burn itself
    const psi = pr.form_chi * (1 + pr.form_lambda + (pr.form_mu ?? 0));
    if (Math.abs(psi - 1) > 1e-6) rows.push(["Form function χ·(1+λ+μ)", `${psi.toFixed(3)} (must be 1)`, true]);
  }
  $("derived-stats").innerHTML = rows.map(([k, v, warn]) => `<span>${k}</span><span class="${warn ? "warn" : ""}">${v}</span>`).join("");
  $("use-capacity").hidden = !mismatch;
}

function setPreview(m) {
  if (m === "rifle" && !rifleView) m = "cartridge";
  if (m === "cartridge" && !cartViewer) m = "rifle";
  previewMode = m;
  $("pv-cartridge").setAttribute("aria-pressed", m === "cartridge");
  $("pv-rifle").setAttribute("aria-pressed", m === "rifle");
  $("cartridge-view").hidden = m !== "cartridge";
  $("rifle-view").hidden = m !== "rifle";
  $("pv-pull-wrap").hidden = m !== "cartridge";
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
    const f = schema.fields.barrel.find((x) => x[0] === "chamber_volume");
    writeField("barrel", f, cartridge.stats.powderSpace * 1e-6);
    syncAll();
    gunChanged();
  };
}

// ---------- mode (easy / expert) ----------
function setMode(m) {
  mode = m;
  store("gun-sim-mode", m);
  for (const b of document.querySelectorAll("#mode-seg button")) b.setAttribute("aria-pressed", b.dataset.mode === m);
  $("easy").hidden = m !== "easy";
  $("easy-out").hidden = m !== "easy";
  $("expert").hidden = m !== "expert";
  $("derived").hidden = m !== "expert";
  if (m === "easy") setPreview("rifle");
  else updatePreview();
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
      onChange: () => {
        $("cycle").disabled = !!(range.cycle || range.reload);
        $("reload").disabled = !!(range.cycle || range.reload);
      },
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
  $("reload").onclick = () => range.startReload();
  $("replay").onclick = async () => {
    if (!lastShot) return;
    unlockAudio();
    // The feed depends on the rounds left: re-simulate the action cycle (not the bore) for this magazine.
    const rounds = range.roundsAtNextShot();
    if (lastShot.action && lastRequest && lastShot.action.rounds?.[0] !== rounds) {
      const btn = $("replay");
      btn.disabled = true;
      try {
        const act = await backend.cycle({
          gun: lastGun, model: lastShot.model, burst: lastRequest.burst, rounds,
          blowdown: lastRequest.blowdown, ambient_pressure: lastRequest.ambient_pressure,
        });
        lastShot = { ...lastShot, action: act };
      } catch (e) {
        showError(`Replay: ${e.message}`);
        return;
      } finally {
        btn.disabled = false;
      }
    }
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
  currentTab = name;
  for (const b of document.querySelectorAll("nav.tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
  $("workshop").hidden = name !== "workshop";
  $("range-tab").hidden = name !== "range";
  $("target-tab").hidden = name !== "target";
  $("analysis-tab").hidden = name !== "analysis";
  if (name === "range") {
    syncRange();
  } else if (name === "analysis") {
    requestAnimationFrame(drawAll);
  } else if (name === "target") {
    if (target?.result) requestAnimationFrame(() => target.show(target.result));
    else if (lastResult && shotVersion === gunVersion) target?.shoot(false);
  } else {
    updatePreview();
  }
  window.scrollTo({ top: 0 });
}

// ---------- charts ----------
function drawAll() {
  if ($("analysis-tab").hidden) return;
  const colors = ["--s1", "--s2", "--s3", "--s4"].map(cssVar);
  const results = lastResult ? lastResult.results : [];
  const P = (p) => toDisplay(p, "pressure"), V = (v) => toDisplay(v, "velocity");
  const X = (m) => toDisplay(m, "length_mm");
  const pressure = [], velocity = [], profile = [];
  results.forEach((r, i) => {
    const c = colors[i % colors.length];
    const t = r.time.map((v) => v * 1e3);
    pressure.push({ label: `${r.model} breech`, color: c, x: t, y: r.breech_pressure.map(P) });
    pressure.push({ label: `${r.model} base`, color: c, dash: true, x: t, y: r.base_pressure.map(P) });
    velocity.push({ label: r.model, color: c, x: r.travel.map(X), y: r.velocity.map(V) });
  });
  const fluid = results.find((r) => r.profiles.length);
  if (fluid) {
    // Up to 4 evenly spread snapshots; colour by order.
    const step = Math.max(1, Math.floor(fluid.profiles.length / 4));
    fluid.profiles.filter((_, i) => i % step === 0).slice(0, 4).forEach((pr, i) => {
      profile.push({ label: `${(pr.time * 1e3).toFixed(3)} ms`, color: colors[i % colors.length], x: pr.x.map(X), y: pr.p.map(P) });
    });
  }
  const drop = [], flight = [];
  if (lastTraj) {
    const R = (m) => toDisplay(m, "length_m");
    drop.push({ label: "drop", color: colors[0], x: lastTraj.range.map(R), y: lastTraj.drop.map((y) => toDisplay(y, "drop")) });
    flight.push({ label: "velocity", color: colors[1], x: lastTraj.range.map(R), y: lastTraj.velocity.map(V) });
  }
  const pl = label("pressure"), vl = label("velocity"), ml = label("length_mm"), rl = label("length_m");
  drawChart($("c-drop"), { series: drop, xlabel: `range (${rl})`, ylabel: `drop (${label("drop")})`, legendBottom: true });
  drawChart($("c-flight"), { series: flight, xlabel: `range (${rl})`, ylabel: `velocity (${vl})` });
  drawChart($("c-pressure"), { series: pressure, xlabel: "time (ms)", ylabel: `pressure (${pl})` });
  drawChart($("c-velocity"), { series: velocity, xlabel: `travel (${ml})`, ylabel: `velocity (${vl})`, legendBottom: true });
  drawChart($("c-profile"), { series: profile, xlabel: `position from seated base (${ml})`, ylabel: `pressure (${pl})` });
  const bed = results.find((r) => r.grain_bed)?.grain_bed;
  $("bed-panel").hidden = !bed;
  if (bed) {
    const t = bed.t.map((v) => v * 1e3);
    drawChart($("c-bed"), { xlabel: "time (ms)", ylabel: "share of the charge (%)", series: [
      { label: "alight", color: colors[0], x: t, y: bed.lit.map((v) => v * 100) },
      { label: "burnt", color: colors[1], x: t, y: bed.burnt.map((v) => v * 100) },
    ] });
  }

  // Recoil: the animated result's (fluid if run), plus the other model's shoulder force for comparison.
  const motion = [], shoulder = [];
  const shown = results.find((r) => r.model === "fluid" && r.action) || results.find((r) => r.action);
  if (shown) {
    const a = shown.action, t = a.time.map((v) => v * 1e3);
    motion.push({ label: "gun recoil (mm)", color: colors[0], x: t, y: a.recoil.map((v) => v * 1e3) });
    if (a.kind === "revolver") motion.push({ label: "cylinder turned (chambers × 10)", color: colors[1], x: t, y: a.cylinder.map((v) => v * 10) });
    else if (a.kind !== "bolt") motion.push({ label: "bolt travel (mm)", color: colors[1], x: t, y: a.bolt.map((v) => v * 1e3) });
    motion.push({ label: "muzzle rise (mrad)", color: colors[2], x: t, y: a.pitch.map((v) => v * 1e3) });
  }
  const F = (f) => toDisplay(f, "force");
  results.forEach((r, i) => {
    if (!r.action) return;
    const a = r.action;
    const y = a.stance === "free" ? a.recoil_velocity.map((v) => v * 100) : a.shoulder_force.map(F);
    shoulder.push({ label: r.model, color: colors[i % colors.length], x: a.time.map((v) => v * 1e3), y });
  });
  const stance = shown?.action.stance ?? "shoulder", free = stance === "free";
  $("c-shoulder-title").textContent = free ? "Free recoil velocity" : stance === "mount" ? "Force on the mount"
    : stance === "hands" ? "Force on the shooter's hands" : "Force on the shooter's shoulder";
  drawChart($("c-motion"), { series: motion, xlabel: "time (ms)", ylabel: "mm · mrad" });
  drawDevice();
  drawChart($("c-shoulder"), { series: shoulder, xlabel: "time (ms)", ylabel: free ? "velocity (cm/s)" : `force (${label("force")})` });

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

const mainShot = () => lastResult ? (lastResult.results.find((r) => r.model === "fluid") || lastResult.results[0]) : null;

/** Fly the last shot's projectile downrange from its muzzle velocity and show curves and table. */
async function updateTrajectory() {
  if (!lastGun || !lastResult) return;
  const shot = mainShot();
  if (!shot.left_muzzle) return;
  const id = ++trajRequest;
  const payload = {
    gun: lastGun, muzzle_velocity: shot.muzzle_velocity,
    zero_range: siOf($("t-zero")), max_range: siOf($("t-range")), sight_height: siOf($("t-sight")), crosswind: siOf($("t-wind")),
  };
  const atm = atmosphere();
  if (atm) payload.atmosphere = atm;
  try {
    const data = await backend.trajectory(payload);
    if (id !== trajRequest) return;
    lastTraj = data;
    showTrajTable(data);
  } catch (e) {
    if (id !== trajRequest) return;
    lastTraj = null;
    $("traj-status").textContent = e.message;
    $("traj-table").innerHTML = "";
  }
  drawAll();
}

function showTrajTable(data) {
  $("traj-status").textContent = `${data.drag_model} BC ${(data.ballistic_coefficient / 703.0696).toFixed(3)} lb/in²` +
    (data.stability ? ` · spin drift included (Sg ${data.stability.toFixed(2)})` : "") +
    (data.stop_reason === "max range" ? "" : ` · flight ended at ${fmt(data.max_range, "length_m")} (${data.stop_reason})`);
  const f = (v, d) => v.toFixed(d);
  const L = label("length_m"), D = label("drop"), V = label("velocity"), E = label("energy");
  $("traj-table").innerHTML = `<table class="data"><tr><th>range (${L})</th><th>drop (${D})</th><th>drop (MOA)</th><th>drop (mil)</th>` +
    `<th>windage (${D})</th><th>of which spin (${D})</th><th>velocity (${V})</th><th>energy (${E})</th><th>time (s)</th></tr>` +
    data.table.map((r) => `<tr><td>${f(toDisplay(r.range, "length_m"), 0)}</td><td>${f(toDisplay(r.drop, "drop"), 1)}</td>` +
      `<td>${f(r.drop_moa, 1)}</td><td>${f(r.drop_mil, 2)}</td><td>${f(toDisplay(r.windage, "drop"), 1)}</td>` +
      `<td>${f(toDisplay(r.spin_drift, "drop"), 1)}</td><td>${f(toDisplay(r.velocity, "velocity"), 0)}</td>` +
      `<td>${f(toDisplay(r.energy, "energy"), 0)}</td><td>${f(r.time, 3)}</td></tr>`).join("") + "</table>";
}

// ---------- results ----------
function showSummary(data, gun) {
  const r = data.results.find((x) => x.model === "fluid") || data.results[0];
  const tiles = [];
  const tile = (k, v, s = "", cls = "") => tiles.push(`<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`);
  if (!r.left_muzzle) tile("Projectile", "stuck", "it did not leave the muzzle", "bad");
  tile("Muzzle velocity", fmt(r.muzzle_velocity, "velocity"), `${r.model} model`);
  const mass = gun.projectile.type === "apfsds" ? gun.projectile.penetrator_mass : gun.projectile.mass;
  tile("Muzzle energy", fmt(0.5 * mass * r.muzzle_velocity ** 2, "energy"));
  tile("Peak breech pressure", fmt(r.peak_breech_pressure, "pressure"));
  tile("Time in barrel", `${(r.muzzle_time * 1e3).toFixed(3)} ms`, `${(r.burnt_at_muzzle * 100).toFixed(0)} % of the powder burnt`);
  const a = r.action;
  if (a) {
    tile("Recoil", fmt(a.impulse, "impulse"), `free recoil ${fmt(a.free_recoil_energy, "energy", 1)}`);
    const ok = ["cycled", "manual", "fired", "breech opened"].includes(a.status) || a.status.startsWith("empty");
    tile("Action", a.cyclic_rate ? `${a.cyclic_rate.toFixed(0)} rpm` : (ok ? "OK" : "fault"), a.status, ok ? "" : "bad");
  }
  if (r.spin?.stability) tile("Stability", `S<sub>g</sub> ${r.spin.stability.toFixed(2)}`, `${(r.spin.spin_rpm / 1e3).toFixed(0)}k rpm`, r.spin.stability < 1 ? "bad" : "");
  $("shot-summary").innerHTML = tiles.join("");
}

function showCards(data, gun) {
  const cards = $("cards");
  cards.innerHTML = "";
  for (const r of data.results) {
    const card = document.createElement("details");
    card.className = "panel card";
    const status = r.left_muzzle ? "" : '<span class="bad">· projectile did not leave the muzzle</span>';
    const mass = gun.projectile.type === "apfsds" ? gun.projectile.penetrator_mass : gun.projectile.mass;
    card.innerHTML = `<summary>${r.model[0].toUpperCase() + r.model.slice(1)} model: all the numbers ${status}</summary><div class="stats">
      <span>Muzzle velocity</span><span>${fmt(r.muzzle_velocity, "velocity", 1)}</span>
      <span>Muzzle energy</span><span>${fmt(0.5 * gun.projectile.mass * r.muzzle_velocity ** 2, "energy")}</span>${
        gun.projectile.type === "apfsds" ? `
      <span>The rod's, once the sabot has gone</span><span>${fmt(0.5 * mass * r.muzzle_velocity ** 2, "energy")}</span>` : ""}
      <span>Time in barrel</span><span>${(r.muzzle_time * 1e3).toFixed(3)} ms</span>
      <span>Peak breech pressure</span><span>${fmt(r.peak_breech_pressure, "pressure", 1)}</span>
      <span>Charge burnt at exit</span><span>${(r.burnt_at_muzzle * 100).toFixed(1)} %</span>${bedRows(r.grain_bed)}${gapRows(r.gap, gun)}${spinRows(r.spin)}${actionRows(r.action)}${deviceRows(r.device)}${evacuatorRows(r.evacuator)}</div>
      ${(r.action?.warnings ?? []).map((w) => `<div class="bad" style="padding:0 16px 10px">${w}</div>`).join("")}`;
    cards.appendChild(card);
  }
}

/** Card row for a revolver's cylinder gap: the gas it let out. */
function gapRows(g, gun) {
  if (!g) return "";
  const share = g.mass / gun.propellant.charge_mass * 100;
  return `
      <span>Out of the cylinder gap</span><span>${(g.mass * 1e3).toFixed(0)} mg of gas (${share.toFixed(1)} % of the charge), ${g.energy.toFixed(0)} J</span>`;
}

/** Card rows for a two-phase grain bed. */
function bedRows(b) {
  if (!b) return "";
  const spread = b.flame_spread_time !== null
    ? `${(b.flame_spread_time * 1e3).toFixed(3)} ms after the primer`
    : `<span class="bad">only ${(b.lit.at(-1) * 100).toFixed(0)} % by exit</span>`;
  let rows = `
      <span>Whole charge alight</span><span>${spread}</span>`;
  if (b.ejected > 1e-7) rows += `<span>Blown out unburnt</span><span>${(b.ejected * 1e6).toFixed(1)} mg</span>`;
  return rows;
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
  const mm = (m) => fmt(m, "length_mm", imperial() ? 2 : 1);
  let rows = `
      <span>Recoil impulse (incl. gas jet)</span><span>${fmt(a.impulse, "impulse")}</span>
      <span>Free recoil</span><span>${fmt(a.free_recoil_velocity, "velocity", 2)}, ${fmt(a.free_recoil_energy, "energy", 1)}</span>`;
  if (a.stance === "shoulder" || a.stance === "hands") {
    const into = a.stance === "hands" ? "hands" : "shoulder";
    rows += `
      <span>Into the ${into}</span><span>${mm(a.max_recoil)}, up to ${fmt(a.peak_recoil_velocity, "velocity", 2)}</span>
      <span>Peak force on the ${into}</span><span>${fmt(a.peak_shoulder_force, "force")}</span>`;
  } else if (a.stance === "mount") {
    const home = a.battery_time !== null
      ? `back in battery after ${(a.battery_time * 1e3).toFixed(0)} ms at ${a.battery_speed.toFixed(2)} m/s`
      : '<span class="bad">not back in battery</span>';
    rows += `
      <span>Recoil on the mount</span><span>${mm(a.max_recoil)}, up to ${a.peak_recoil_velocity.toFixed(2)} m/s; ${home}</span>
      <span>Peak force on the mount</span><span>${(a.peak_shoulder_force / 1e3).toFixed(1)} kN</span>`;
    if (a.stop_speed !== null) rows += `<span>Recoil stop</span><span class="bad">hit at ${a.stop_speed.toFixed(2)} m/s</span>`;
  }
  rows += a.stance === "mount" ? `<span>Jump</span><span>${(a.max_pitch * 1e3).toFixed(2)} mrad</span>`
    : `<span>${a.stance === "hands" ? "Muzzle flip" : "Muzzle rise"}</span><span>${deg(a.max_pitch)}°</span>`;
  if (a.kind === "revolver") {
    rows += `<span>Cylinder</span><span>${a.rounds[0] + 1} of ${a.capacity + 1} chambers loaded, ${a.rounds_left} live to come</span>`;
  } else if (a.rounds?.length) {
    rows += `<span>Feed</span><span>${a.rounds[0]} of ${a.capacity} rounds in, ${a.rounds_left} left · fed at ${deg(Math.abs(a.feed_angle))}°</span>`;
  }
  rows += triggerRows(a);
  if (a.kind === "bolt") return rows;
  if (a.kind === "revolver") {
    const ok = a.status === "fired" || a.status === "empty";
    rows += `<span>Revolver</span><span class="${ok ? "" : "bad"}">${a.status}, ${a.shot_times.length} shot${a.shot_times.length > 1 ? "s" : ""}` +
      (a.shot_times.length > 1 ? ` (${a.cyclic_rate.toFixed(0)} rounds/min), muzzle climbs to ${deg(a.max_pitch)}°` : "") + "</span>";
    if (a.cylinder_lock_speed !== null) rows += `<span>Cylinder onto its stop</span><span>${a.cylinder_lock_speed.toFixed(0)} rad/s, ${(a.cylinder_lock_energy * 1e3).toFixed(1)} mJ</span>`;
    if (a.hammer_energy !== null) rows += `<span>Hammer</span><span>${(a.lock_time * 1e3).toFixed(1)} ms from the sear to ignition, hits the pin with ${a.hammer_energy.toFixed(2)} J</span>`;
    return rows;
  }
  if (a.kind === "sliding_wedge") {
    const ok = a.status === "breech opened";
    rows += `<span>Sliding wedge</span><span class="${ok ? "" : "bad"}">${a.status}` +
      (a.open_time !== null ? ` ${(a.open_time * 1e3).toFixed(0)} ms after the shot` : "") + "</span>";
    if (a.case_speed !== null) rows += `<span>Case thrown out</span><span>${a.case_speed.toFixed(1)} m/s</span>`;
    const al = a.autoloader;
    if (al) {
      rows += `<span>Autoloader</span><span class="${al.loaded ? "" : "bad"}">${al.label}, ${al.drive}: ` +
        (al.loaded ? `loaded, ready to fire ${al.ready_time.toFixed(1)} s after the shot (${al.rate.toFixed(1)} rounds/min); ${al.rounds_after} left`
          : al.status) + "</span>";
      if (al.seat_speed !== null) rows += `<span>Rammed home</span><span class="${al.seat_speed < 1.2 ? "bad" : ""}">the ${al.two_piece ? "projectile" : "round"} seats at ${fmt(al.seat_speed, "velocity", 2)}${al.block_speed !== null ? `; the block springs shut at ${al.block_speed.toFixed(2)} m/s` : ""}</span>`;
      const steps = al.stages.map((s) => `${s.start.toFixed(2)}–${s.end.toFixed(2)} s ${s.name}`).join("<br>");
      if (steps) rows += `<span>Its cycle</span><span>${steps}</span>`;
    }
    return rows;
  }
  if (a.shot_times.length > 1) {
    const climb = (a.max_pitch * 180 / Math.PI).toFixed(2);
    rows += `<span>${a.semi ? "String" : "Burst"}</span><span>${a.shot_times.length} shots in ${((a.shot_times.at(-1) - a.shot_times[0]) * 1e3).toFixed(0)} ms, muzzle climbs to ${climb}°</span>`;
  }
  const ok = a.status === "cycled" || a.status.startsWith("empty");
  const kind = a.kind.replace("_", " ");
  rows += `<span>${kind[0].toUpperCase() + kind.slice(1)} action</span><span class="${ok ? "" : "bad"}">${a.status}` +
    (a.cycle_time ? ` in ${(a.cycle_time * 1e3).toFixed(1)} ms${a.cyclic_rate ? ` (${a.cyclic_rate.toFixed(0)} rounds/min)` : ""}` : "") + "</span>";
  if (a.rear_speed !== null) rows += `<span>Bolt into the rear stop</span><span>${fmt(a.rear_speed, "velocity", 1)}</span>`;
  else rows += `<span>Bolt travel</span><span>${mm(a.bolt_max_travel)} of ${mm(a.strokes.stroke)}</span>`;
  if (a.unlock_pressure !== null) rows += `<span>Chamber pressure at unlock</span><span>${fmt(a.unlock_pressure, "pressure", 1)}</span>`;
  if (a.gas_peak_pressure !== null) rows += `<span>Peak gas cylinder pressure</span><span>${fmt(a.gas_peak_pressure, "pressure", 1)}</span>`;
  if (a.port_cd !== null) rows += `<span>Gas port discharge coefficient</span><span>${a.port_cd.toFixed(2)}${a.port_cd_2d ? " (2D)" : " (assumed)"}</span>`;
  if (a.hammer_energy !== null) rows += `<span>Hammer</span><span>${(a.lock_time * 1e3).toFixed(1)} ms from the sear to ignition, hits the pin with ${a.hammer_energy.toFixed(2)} J</span>`;
  if (a.striker_energy !== null) {
    const weak = a.striker_energy < a.strike_energy;
    rows += `<span>Striker</span><span class="${weak ? "bad" : ""}">${(a.lock_time * 1e3).toFixed(1)} ms from release to ignition, hits the primer with ${(a.striker_energy * 1e3).toFixed(0)} mJ (it needs ${(a.strike_energy * 1e3).toFixed(0)})</span>`;
  }
  if (a.motor_peak_power !== null) rows += `<span>Chain drive</span><span>motor peaking at ${a.motor_peak_power.toFixed(0)} W</span>`;
  return rows;
}

/** Card row for the trigger: its type and the work of its pulls (only for a handgun's or a semi-automatic's). */
function triggerRows(a) {
  if (a.trigger_work === null) return "";
  const kind = a.trigger.replaceAll("_", " ");
  const then = a.follow_up_work !== null && Math.abs(a.follow_up_work - a.trigger_work) > 1e-6
    ? `, then ${(a.follow_up_work * 1e3).toFixed(0)} mJ` : "";
  return `<span>Trigger</span><span>${kind[0].toUpperCase() + kind.slice(1)}${a.semi ? ", a pull a shot" : ""}: ${(a.trigger_work * 1e3).toFixed(0)} mJ to fire${then}</span>`;
}

/** Card rows for a bore evacuator. */
function evacuatorRows(e) {
  if (!e) return "";
  let rows = `
      <span>Bore evacuator</span><span>charged to ${(e.peak_pressure / 1e6).toFixed(2)} MPa with ${(e.charge * 1e3).toFixed(0)} g of gas, blowing until ${e.blow_end.toFixed(2)} s</span>`;
  if (e.open_time !== null) {
    rows += e.clear
      ? `<span>Fumes</span><span>the breech opens at ${e.open_time.toFixed(2)} s; the jets draw air up the bore at ${e.open_flow.toFixed(1)} m/s, sweeping it clear in ${e.sweep_time.toFixed(2)} s</span>`
      : `<span>Fumes</span><span class="bad">the breech opens at ${e.open_time.toFixed(2)} s with too little flow left: they come back in</span>`;
  }
  return rows;
}

/** Card rows for the muzzle device's 2D solution. */
function deviceRows(d) {
  if (!d) return "";
  return `
      <span>${d.dims.type[0].toUpperCase() + d.dims.type.slice(1).replace("_", " ")} (2D)</span><span>pushes the gun forwards ${fmt(d.impulse, "impulse")}</span>
      <span>Peak pressure inside</span><span>${fmt(d.peak_pressure, "pressure", 2)}</span>
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
  try { gun = getGun(); } catch (e) { showError(e.message); return false; }
  const models = [...document.querySelectorAll("#model-boxes input:checked")].map((b) => b.value);
  if (!models.length) { showError("Select at least one model."); return false; }
  syncRange();
  const id = ++shotId;
  const version = gunVersion;
  // Start the sound right away; it's needed by the time the projectile leaves the muzzle.
  if ($("sound-on").checked) synthesizeSound(gun, id);
  const btn = $("run");
  btn.disabled = true;
  btn.textContent = gun.muzzle_device?.type && gun.muzzle_device.type !== "none" ? "Simulating (2D)…" : "Simulating…";
  // The sound's air and blowdown time, so the shot, its sound and its flash share one bore (and 2D device) run.
  // The range's magazine: the shot is simulated with the rounds it will have left.
  const request = { gun, models, burst: burstCount(), rounds: range ? range.roundsAtNextShot() : null };
  try {
    const snd = getSound();
    request.blowdown = snd.blast_time;
    request.ambient_pressure = snd.pressure;
  } catch (e) { /* defaults */ }
  // The muzzle flash and smoke are solved in 2D alongside; the range waits for them.
  const plume = range
    ? backend.plume({ gun, blowdown: request.blowdown, ambient_pressure: request.ambient_pressure })
      .catch((e) => { showError(`Flash and smoke: ${e.message}`); return null; })
    : Promise.resolve(null);
  try {
    lastResult = await backend.simulate(request);
    lastGun = gun;
    lastRequest = request;
    shotVersion = version;
    showCards(lastResult, gun);
    showSummary(lastResult, gun);
    drawAll();
    updateTrajectory();
    lastShot = mainShot();
    if (lastShot.left_muzzle) {
      btn.textContent = "Simulating flash (2D)…";
      lastShot.plume = await plume;
    }
  } catch (e) {
    showError(e.message);
    return false;
  } finally {
    btn.disabled = false; btn.textContent = "Fire";
  }
  $("replay").disabled = false;
  if (target && currentTab === "target") target.shoot(false);
  if (!range) return true;
  const at = Number(params.get("at"));
  if (params.has("at") && isFinite(at)) range.seek(lastShot, at);
  else if (animate) range.fire(lastShot);
  return true;
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
  if (!shot || $("analysis-tab").hidden) return;
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
    ? `${((snap.t - exitT) * 1e3).toFixed(2)} ms after exit · ${d.dims.type.replace("_", " ")}, ${(d.dims.h * 1e3).toFixed(2)} mm cells`
    : "";
  drawChart($("c-device-force"), {
    series: [{ label: "forwards (against recoil)", color: cssVar("--s1"), x: d.t.map((t) => (t - exitT) * 1e3), y: d.force.map((f) => toDisplay(f, "force")) }],
    xlabel: "time after exit (ms)", ylabel: `force (${label("force")})`,
  });
}

// ---------- setup ----------
async function init() {
  setSystem(params.get("units") === "imperial" ? "imperial" : savedSystem());
  try {
    backend = await connect();
    schema = await backend.schema();
  } catch (e) {
    showError(e.message);
    return;
  }
  buildEditor();
  if (imperial()) {   // round numbers in the units on screen: 100 and 1000 yd
    $("t-zero").dataset.si = 91.44;
    $("t-range").dataset.si = 914.4;
  }
  bindUnitInputs();
  onUnits(unitsChanged);
  for (const b of document.querySelectorAll("#units-seg button")) {
    b.setAttribute("aria-pressed", b.dataset.units === getSystem());
    b.onclick = () => setSystem(b.dataset.units);
  }
  for (const [key, env] of Object.entries(ENVIRONMENTS)) $("environment").add(new Option(env.label, key));
  for (const [key, p] of Object.entries(PROTECTION)) $("protection").add(new Option(p.label, key));
  $("environment").value = player.environment;
  $("protection").value = player.protection;
  setSound({ ...schema.sound.defaults, ...schema.sound.presets.shooter });
  $("listener").value = "shooter";
  initPreviews();
  initRange();

  const preset = $("preset");
  preset.add(new Option("—", ""));
  for (const name of Object.keys(schema.presets)) preset.add(new Option(schema.presets[name].name, name));
  preset.onchange = () => { if (preset.value) setGun(schema.presets[preset.value]); };

  $("model-boxes").innerHTML = schema.models
    .map((m) => `<label><input type="checkbox" value="${m}" checked> ${m}</label>`).join(" ");

  target = new TargetRange(backend, schema, {
    getShot: () => {
      const shot = mainShot();
      if (!shot || !shot.left_muzzle || shotVersion !== gunVersion) return null;
      return { gun: lastGun, muzzle_velocity: shot.muzzle_velocity, atmosphere: atmosphere() };
    },
    ensureShot: async () => (await fire(false)) ? target.getShot() : null,
    onError: showError,
  });

  // A preset in the URL starts in expert mode with it; otherwise easy mode builds the gun.
  const startPreset = schema.presets[params.get("preset")] ? params.get("preset") : null;
  const startMode = startPreset ? "expert" : (params.get("mode") ?? recall("gun-sim-mode") ?? "easy");
  let firstBuild = true;
  easy = new EasyMode(backend, schema, {
    onGun: (gun) => {
      if (mode !== "easy" && !firstBuild) return;
      setGun(gun);
      $("preset").value = "";
      if (firstBuild && !startPreset) fire(params.has("at"));
      firstBuild = false;
    },
    onError: showError,
  });
  if (startPreset) {
    preset.value = startPreset;
    setGun(schema.presets[startPreset]);
    firstBuild = false;
    fire(params.has("at"));
  }
  for (const b of document.querySelectorAll("#mode-seg button")) b.onclick = () => {
    setMode(b.dataset.mode);
    if (b.dataset.mode === "easy") easy.build();
  };
  setMode(startMode === "expert" ? "expert" : "easy");
  $("e-to-expert").onclick = () => setMode("expert");

  for (const id of ["t-zero", "t-range", "t-sight", "t-wind"]) $(id).addEventListener("change", updateTrajectory);
  for (const b of document.querySelectorAll("nav.tabs button")) b.onclick = () => showTab(b.dataset.tab);
  for (const b of document.querySelectorAll("[data-go]")) b.onclick = () => {
    showTab(b.dataset.go);
    if (b.dataset.go === "range" && shotVersion !== gunVersion) fire(true);
    if (b.dataset.go === "target") target.shoot(true);
  };
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
      setMode("expert");
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

  const tab = params.get("tab");
  showTab(["range", "target", "analysis"].includes(tab) ? tab : "workshop");
}
init();
