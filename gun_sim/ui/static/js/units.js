// Metric and imperial display units. The simulator works in SI throughout;
// these only change what the page shows and what typed numbers mean.

const GRAIN = 64.79891e-6;   // kg

// Quantity -> { metric: [label, SI per unit, decimals], imperial: [...] }
const Q = {
  length_mm: { metric: ["mm", 1e-3, 1], imperial: ["in", 0.0254, 3] },
  length_m: { metric: ["m", 1, 0], imperial: ["yd", 0.9144, 0] },
  drop: { metric: ["cm", 0.01, 1], imperial: ["in", 0.0254, 1] },
  mass_g: { metric: ["g", 1e-3, 2], imperial: ["gr", GRAIN, 1] },
  mass_kg: { metric: ["kg", 1, 2], imperial: ["lb", 0.45359237, 2] },
  velocity: { metric: ["m/s", 1, 0], imperial: ["ft/s", 0.3048, 0] },
  wind: { metric: ["m/s", 1, 1], imperial: ["mph", 0.44704, 1] },
  energy: { metric: ["J", 1, 0], imperial: ["ft·lbf", 1.3558179483, 0] },
  pressure: { metric: ["MPa", 1e6, 0], imperial: ["psi", 6894.757, 0] },
  impulse: { metric: ["N·s", 1, 2], imperial: ["lbf·s", 4.4482216, 2] },
  force: { metric: ["N", 1, 0], imperial: ["lbf", 4.4482216, 0] },
  volume: { metric: ["cm³", 1e-6, 2], imperial: ["gr H₂O", 0.0648e-6, 0] },
};

// Expert-editor field units: metric display unit -> [imperial unit, metric units per imperial unit].
const FIELD_IMPERIAL = {
  mm: ["in", 25.4],
  g: ["gr", GRAIN * 1e3],
  kg: ["lb", 0.45359237],
  MPa: ["psi", 6894.757e-6],
  "cm³": ["in³", 16.387064],
  N: ["lbf", 4.4482216],
  "N/mm": ["lbf/in", 0.17512685],
  L: ["in³", 0.016387064],
  "m/s": ["ft/s", 0.3048],
  kW: ["hp", 0.745699872],
};

let system = "metric";
const listeners = new Set();

export const getSystem = () => system;
export const imperial = () => system === "imperial";

export function setSystem(s) {
  if (s === system) return;
  system = s;
  try { localStorage.setItem("gun-sim-units", s); } catch (e) { /* private window */ }
  for (const fn of listeners) fn(s);
}

export function savedSystem() {
  try { return localStorage.getItem("gun-sim-units") === "imperial" ? "imperial" : "metric"; } catch (e) { return "metric"; }
}

export const onUnits = (fn) => listeners.add(fn);

/** [label, SI per unit, decimals] for a quantity in the current system. */
export const unit = (q) => Q[q][system];
export const label = (q) => Q[q][system][0];
/** An SI value in display units. */
export const toDisplay = (si, q) => si / Q[q][system][1];
/** A display value back to SI. */
export const toSI = (v, q) => v * Q[q][system][1];

/** "838 m/s" or "2749 ft/s". digits overrides the quantity's usual decimals. */
export function fmt(si, q, digits) {
  if (si === null || si === undefined || !isFinite(si)) return "—";
  const [lab, scale, d] = Q[q][system];
  return `${(si / scale).toFixed(digits ?? d)} ${lab}`;
}

/** The number alone, rounded as fmt would. */
export function num(si, q, digits) {
  const [, scale, d] = Q[q][system];
  return Number((si / scale).toFixed(digits ?? d));
}

/** Display unit and SI scale for an expert field whose metric unit is `unitName` and scale `scale`. */
export function fieldUnit(unitName, scale) {
  if (system === "imperial" && FIELD_IMPERIAL[unitName]) {
    const [u, f] = FIELD_IMPERIAL[unitName];
    return { unit: u, scale: scale * f, factor: f };
  }
  return { unit: unitName, scale, factor: 1 };
}

/** Bullet weight the way it is quoted in both systems: "124 gr (8.04 g)" or "8.04 g (124 gr)". */
export function bulletMass(kg) {
  const gr = `${(kg / GRAIN).toFixed(kg / GRAIN < 100 ? 1 : 0)} gr`, g = `${(kg * 1e3).toFixed(2)} g`;
  return system === "imperial" ? `${gr} (${g})` : `${g} (${gr})`;
}

/** Inputs carrying data-q show a quantity in display units; data-si holds the SI value. */
export function bindUnitInputs(root = document) {
  for (const el of root.querySelectorAll("input[data-q]")) {
    const q = el.dataset.q;
    if (el.dataset.si !== undefined && el.value === "") el.value = num(Number(el.dataset.si), q, 2);
    el.addEventListener("input", () => { el.dataset.si = toSI(Number(el.value), q); });
  }
  const refresh = () => {
    for (const el of root.querySelectorAll("input[data-q]")) {
      if (el.dataset.si !== undefined && el.dataset.si !== "") el.value = num(Number(el.dataset.si), el.dataset.q, 2);
    }
    for (const el of root.querySelectorAll("[data-unit]")) el.textContent = label(el.dataset.unit);
  };
  onUnits(refresh);
  refresh();
}

/** SI value of a data-q input. */
export const siOf = (el) => Number(el.dataset.si ?? toSI(Number(el.value), el.dataset.q));
