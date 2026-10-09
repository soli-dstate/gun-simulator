// Easy mode: pick a cartridge, a load, a kind of gun and a barrel; the backend
// (designer.py) builds the whole gun and says what it worked out.

import { bulletMass, fmt, getSystem, imperial, num, onUnits, toSI } from "./units.js";

const $ = (id) => document.getElementById(id);
const INCH = 0.0254;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = (s) => s.toLowerCase().replace(/×/g, "x").replace(/[\s.\-_]/g, "");

export class EasyMode {
  /** onGun(gun): a gun was built. onBusy(bool). onError(message). */
  constructor(backend, schema, { onGun, onError }) {
    this.backend = backend;
    this.easy = schema.easy;
    this.onGun = onGun;
    this.onError = onError;
    this.byId = Object.fromEntries(this.easy.cartridges.map((c) => [c.id, c]));
    this.state = { cartridge: "556", load: null, platform: "ar_auto", barrel: null, device: "none",
                   twistAuto: true, twist: null, capacity: null, name: "", kind: "all", search: "" };
    this.request = 0;
    this.timer = null;
    this.last = null;
    try {
      const saved = JSON.parse(localStorage.getItem("gun-sim-easy") || "null");
      if (saved && this.byId[saved.cartridge]) Object.assign(this.state, saved, { search: "", kind: "all" });
    } catch (e) { /* nothing saved */ }
    this.render();
    onUnits(() => { this.renderCartridges(); this.renderLoads(); this.renderBarrel(); if (this.last) this.showResult(this.last); });
  }

  get cartridge() { return this.byId[this.state.cartridge]; }

  render() {
    const kinds = $("e-kinds");
    kinds.innerHTML = `<button class="chip" data-kind="all">All</button>` +
      Object.entries(this.easy.kinds).map(([k, v]) => `<button class="chip" data-kind="${k}">${esc(v)}</button>`).join("");
    kinds.onclick = (e) => {
      const b = e.target.closest("button[data-kind]");
      if (!b) return;
      this.state.kind = b.dataset.kind;
      this.renderCartridges();
    };
    $("e-search").oninput = (e) => { this.state.search = e.target.value; this.renderCartridges(); };
    $("e-cartridges").onclick = (e) => {
      const b = e.target.closest("button[data-id]");
      if (b) this.pickCartridge(b.dataset.id);
    };
    $("e-loads").onclick = (e) => {
      const b = e.target.closest("button[data-id]");
      if (!b) return;
      this.state.load = b.dataset.id;
      this.renderLoads();
      this.schedule();
    };
    $("e-platforms").onclick = (e) => {
      const b = e.target.closest("button[data-id]");
      if (!b) return;
      this.state.platform = b.dataset.id;
      this.renderPlatforms();
      this.renderBarrel();
      this.schedule();
    };
    $("e-device").innerHTML = Object.entries(this.easy.devices)
      .map(([k, v]) => `<button data-device="${k}">${esc(v)}</button>`).join("");
    $("e-device").onclick = (e) => {
      const b = e.target.closest("button[data-device]");
      if (!b) return;
      this.state.device = b.dataset.device;
      this.renderDevice();
      this.schedule();
    };
    const slider = $("e-barrel-slider"), box = $("e-barrel");
    slider.oninput = () => {
      const [lo, hi] = this.barrelRange();
      this.state.barrel = lo + Number(slider.value) * (hi - lo);
      box.value = this.barrelDisplay();
      this.schedule(500);
    };
    box.onchange = () => {
      const [lo, hi] = this.barrelRange();
      const si = toSI(Number(box.value), "length_mm");
      if (!isFinite(si)) return;
      this.state.barrel = Math.min(hi, Math.max(lo, si));
      this.renderBarrel();
      this.schedule();
    };
    $("e-twist-auto").onchange = (e) => {
      this.state.twistAuto = e.target.checked;
      $("e-twist-wrap").hidden = this.state.twistAuto;
      if (!this.state.twistAuto && !this.state.twist) this.state.twist = Math.abs(this.cartridge.twist / INCH) || 10;
      $("e-twist").value = this.state.twist ?? "";
      this.schedule();
    };
    $("e-twist").onchange = (e) => { this.state.twist = Number(e.target.value) || null; this.schedule(); };
    $("e-capacity").onchange = (e) => { this.state.capacity = Number(e.target.value) || null; this.schedule(); };
    $("e-name").onchange = (e) => { this.state.name = e.target.value.trim(); this.schedule(); };
    $("e-twist-auto").checked = this.state.twistAuto;
    $("e-twist-wrap").hidden = this.state.twistAuto;
    $("e-twist").value = this.state.twist ?? "";
    $("e-capacity").value = this.state.capacity ?? "";
    $("e-name").value = this.state.name;
    this.pickCartridge(this.state.cartridge, true);
  }

  matches(c) {
    if (this.state.kind !== "all" && c.kind !== this.state.kind) return false;
    const q = norm(this.state.search);
    if (!q) return true;
    return [c.metric, c.imperial, ...c.aliases].some((n) => norm(n).includes(q));
  }

  /** The cartridge's two names, the one for the current units first. */
  names(c) {
    if (!c.imperial) return [c.metric, c.kind_label];
    return imperial() ? [c.imperial, c.metric] : [c.metric, c.imperial];
  }

  renderCartridges() {
    for (const b of $("e-kinds").children) b.setAttribute("aria-pressed", b.dataset.kind === this.state.kind);
    const list = this.easy.cartridges.filter((c) => this.matches(c));
    $("e-cartridges").innerHTML = list.length ? list.map((c) => {
      const [a, b] = this.names(c);
      return `<button class="tile" data-id="${c.id}" aria-pressed="${c.id === this.state.cartridge}">
        <span class="t1">${esc(a)}</span><span class="t2">${esc(b)}</span><span class="t3">${esc(c.kind_label)}</span></button>`;
    }).join("") : `<div class="muted">Nothing matches “${esc(this.state.search)}”.</div>`;
  }

  pickCartridge(id, initial = false) {
    const c = this.byId[id];
    if (!c) return;
    const changed = id !== this.state.cartridge;
    this.state.cartridge = id;
    if (changed || !c.loads.some((l) => l.id === this.state.load)) this.state.load = c.loads[0].id;
    if (!c.platforms.some((p) => p.id === this.state.platform)) this.state.platform = c.platforms[0].id;
    if (changed) { this.state.twist = null; }
    this.renderCartridges();
    this.renderLoads();
    this.renderPlatforms();
    this.renderBarrel();
    this.renderDevice();
    this.schedule(initial ? 0 : 150);
  }

  renderLoads() {
    const c = this.cartridge;
    const kinds = { fmj: "FMJ", ap: "AP", sp: "Soft point", hp: "Hollow point", match: "Match", lead: "Lead",
                    apfsds: "APFSDS", service: "Service" };
    $("e-loads").innerHTML = c.loads.map((l) => {
      const ref = l.velocity ? `${fmt(l.velocity, "velocity")} from ${fmt(l.barrel, "length_mm", imperial() ? 1 : 0)}` : "";
      const core = l.core && l.core !== "lead" ? ` · ${l.core.replace("_", " ")} core` : "";
      return `<button class="load" data-id="${l.id}" aria-pressed="${l.id === this.state.load}">
        <span class="t1">${esc(l.name)}</span><span class="badge ${l.kind}">${kinds[l.kind] ?? l.kind}</span>
        <span class="t2">${bulletMass(l.mass)}${ref ? " · " + ref : ""}${core}</span></button>`;
    }).join("");
  }

  renderPlatforms() {
    const c = this.cartridge;
    $("e-platforms").innerHTML = c.platforms.map(({ id }) => {
      const p = this.easy.platforms[id];
      return `<button class="tile" data-id="${id}" aria-pressed="${id === this.state.platform}">
        <span class="t1">${esc(p.label)}</span><span class="t2">${esc(p.blurb)}</span></button>`;
    }).join("");
  }

  barrelRange() {
    const p = this.cartridge.platforms.find((x) => x.id === this.state.platform) ?? this.cartridge.platforms[0];
    return p.barrel;   // [min, max, default] in m
  }

  barrelDisplay() { return num(this.state.barrel, "length_mm", imperial() ? 2 : 0); }

  renderBarrel() {
    const [lo, hi, def] = this.barrelRange();
    if (!(this.state.barrel >= lo && this.state.barrel <= hi)) this.state.barrel = def;
    $("e-barrel-slider").value = (this.state.barrel - lo) / (hi - lo);
    $("e-barrel").value = this.barrelDisplay();
  }

  renderDevice() {
    for (const b of $("e-device").children) b.setAttribute("aria-pressed", b.dataset.device === this.state.device);
  }

  schedule(delay = 250) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.build(), delay);
  }

  async build() {
    const s = this.state;
    const id = ++this.request;
    try { localStorage.setItem("gun-sim-easy", JSON.stringify(s)); } catch (e) { /* private window */ }
    const payload = { cartridge: s.cartridge, load: s.load, platform: s.platform, barrel_length: s.barrel,
                      device: s.device, twist: s.twistAuto || !s.twist ? "auto" : s.twist * INCH * Math.sign(this.cartridge.twist || 1),
                      capacity: s.capacity, name: s.name || null };
    $("e-busy").hidden = false;
    try {
      const out = await this.backend.design(payload);
      if (id !== this.request) return;
      this.last = out;
      this.onError("");
      this.onGun(out.gun);
      this.showResult(out);
    } catch (e) {
      if (id !== this.request) return;
      this.onError(`Build: ${e.message}`);
    } finally {
      if (id === this.request) $("e-busy").hidden = true;
    }
  }

  showResult(out) {
    const p = out.prediction;
    const tiles = [];
    const tile = (k, v, s = "", cls = "", extra = "") => tiles.push(
      `<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div>${extra}</div>`);
    if (!p.left_muzzle) {
      tile("Muzzle velocity", "stuck", "the bullet never leaves", "bad");
    } else {
      const other = getSystem() === "metric" ? `${Math.round(p.muzzle_velocity / 0.3048)} ft/s`
        : `${Math.round(p.muzzle_velocity)} m/s`;
      tile("Muzzle velocity", fmt(p.muzzle_velocity, "velocity"), other);
      tile("Muzzle energy", fmt(p.muzzle_energy, "energy"),
        getSystem() === "metric" ? `${Math.round(p.muzzle_energy / 1.3558)} ft·lbf` : `${Math.round(p.muzzle_energy)} J`);
      if (p.max_pressure) {
        const r = p.peak_pressure / p.max_pressure;
        const cls = r > 1.1 ? "bad" : r > 1.0 ? "warn" : "";
        tile("Chamber pressure", fmt(p.peak_pressure, "pressure"), `${Math.round(r * 100)} % of ${esc(p.standard)}`, cls,
          `<div class="gauge ${cls}"><div style="width:${Math.min(100, r * 100).toFixed(0)}%"></div></div>`);
      } else {
        tile("Chamber pressure", fmt(p.peak_pressure, "pressure"), "peak, mean over the chamber");
      }
      if (p.free_recoil_energy !== null) {
        tile("Free recoil", fmt(p.free_recoil_energy, "energy", 1), `${fmt(p.recoil_impulse, "impulse")} into a ${fmt(p.gun_mass, "mass_kg")} gun`);
      }
      if (p.stability) {
        const sg = p.stability;
        tile("Stability", `S<sub>g</sub> ${sg.toFixed(2)}`, `1 in ${(Math.abs(p.twist) / INCH).toFixed(1)}″ twist`,
          sg < 1 ? "bad" : sg < 1.3 ? "warn" : "");
      }
      if (p.status) {
        const ok = ["cycled", "manual", "fired", "breech opened"].includes(p.status);
        const what = p.status === "manual" ? "bolt worked by hand" : p.status === "fired" ? "fires a pull at a time" : p.status;
        tile("Action", ok ? (p.cyclic_rate ? `${Math.round(p.cyclic_rate)} rpm` : "works") : "fails", esc(what), ok ? "good" : "bad");
      }
      tile("Powder burnt", `${(p.burnt * 100).toFixed(0)} %`, "by the muzzle", p.burnt < 0.85 ? "warn" : "");
    }
    $("e-stats").innerHTML = tiles.join("");
    $("e-notes").innerHTML = out.notes.map((n) => `<li class="${n.kind}"><b>${esc(n.title)}</b>${esc(n.text)}</li>`).join("");
  }
}
