// Rotary guns in 3D, as gun_sim/rotary.py has them: a Gatling's cluster of barrels, each with a bolt on a
// cam, or a revolver cannon's drum of chambers behind one barrel. This module builds the shared parts
// (barrels or drum, the rotor's frame, the bolts) and animates them; each gun's look (housing, motor,
// grips, feed, mount...) is a style in rotary_styles/.
//
// Geometry: see rotary_kit.js for the frames and the station angles. The rotor's axis is geo.R below the
// bore line, so the station at the top is on the bore the projectile, flash and smoke already use.
//
// A style is a module exporting build(gun, geo) -> {
//   steel, furniture, paint, wood, bright: parts in the GUN's frame that recoil with it (dark steel, black,
//     olive paint, wood, bright steel);
//   rotorSteel, rotorBright, rotorPaint: extra parts that turn with the rotor, in the ROTOR frame (clamps...);
//   mount: parts that pitch with the gun but do not recoil (a cradle); pedestal: fixed parts (olive and black);
//   feedPath, returnPath: polylines [[x, y, z], ...] in the gun's frame, or null. feedPath runs from outside
//     the gun and ENDS at geo.feedPoint: rounds ride it into the gun as the rotor takes them. returnPath
//     starts at geo.ejectPoint: with it the cases ride out along it (a linkless gun returns them to its drum),
//     without it they are thrown clear;
//   layout: { recR, buttX, boltRear, pivot: [x, y], cgX, camera?: {x, y, width} }: recR the radius of the
//     gun's body about the bore line (camera framing), buttX the rearmost x of the whole gun, boltRear the
//     rotor's rear face, pivot where the gun pitches (a mount's trunnions), camera the breech view.
// }
// All lists are optional.
//
// The animation. The rotor turns by phi(t) from the action simulation (rotary.time/phi, from the first
// ignition: the spin-up comes first, at negative times). A station at angle theta = phi + 2 pi k / K has its
// bolt at -camTravel(theta) along the bore. Each fired shot j is one round's life in its station: fed at
// phi_fire - (2 pi - feed), fired at phi_fire, thrown out at phi_fire + eject; all follow from the shot times.
// Rounds queue up the feed path, advancing a pitch for every station that passes the feeder.

import { lathe } from "./lathe.js";
import { roundLayout, roundMeshes } from "./cartridge.js";
import { chain, rotationX, translation } from "./mat4.js";
import { merge } from "./meshops.js";
import { barrelMesh, boltMesh, camAngles, camTravel, pathLength, pathPoint, rotaryGeo, stationYZ, tubeX, TAU } from "./rotary_kit.js";
import { rodProfile, tubeProfile } from "./shapes.js";
import { STYLES } from "./rotary_styles/index.js";

const MM = 1e3;
const EASE = 0.15;                  // s (display), as range.js's PIN_FALL: the rotor eases to where the shot starts it
const CASE_CAP = 70;                // thrown cases kept in the air
const CHUTE_CAP = 44;               // rounds drawn on the feed path
const RETURN_CAP = 40;              // cases drawn on the return path
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const smooth = (x) => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };

/** Linear interpolation in a sampled curve (xs ascending). */
function interp(xs, ys, x) {
  const n = xs.length - 1;
  if (n < 0) return 0;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n]) return ys[n];
  let lo = 0, hi = n;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid; else hi = mid;
  }
  return ys[lo] + ((ys[hi] - ys[lo]) * (x - xs[lo])) / (xs[hi] - xs[lo] || 1);
}
const apply = (m, [x, y, z]) => [0, 1, 2].map((k) => m[k] * x + m[4 + k] * y + m[8 + k] * z + m[12 + k]);

// ---------- building ----------

/** The rotary gun's meshes and layout, in the shape buildRifle() returns (SI in, mm out). */
export function buildRotary(gun, cart, warnings = []) {
  const geo = rotaryGeo(gun, cart);
  const d = cart.dims, K = geo.K, R = geo.R;
  const style = (STYLES[geo.style] ?? STYLES.rotary)(gun, geo) ?? {};
  const list = (k) => style[k] ?? [];
  const at = (k) => [R * Math.cos((TAU * k) / K), -R * Math.sin((TAU * k) / K)];   // station k in the rotor frame (y, z)

  // The rotor: barrels (or chambers) held by a plate, a shaft and a rear plate between which the bolts run.
  const rotorSteel = [];
  const shaftR = Math.max(R - geo.boltR - 4, 6);
  const rearPlate = [lathe(rodProfile(R + geo.boltR + 6, geo.rotorRear, geo.rotorRear + 10), 64)];
  const statics = { steel: [...list("steel")] };
  if (geo.revolver) {
    // A drum: a tube round each chamber, tied by a ring and a shaft, and the one barrel fixed on the bore line.
    const ro = geo.baseR + 6;
    for (let k = 0; k < K; k++) {
      const [y, z] = at(k);
      rotorSteel.push(tubeX(geo.baseR + 0.3, ro, 0, d.length + 3, y, z, 32));
    }
    rotorSteel.push(lathe(tubeProfile(shaftR * 0.6, R + 0.4 * ro, 0.35 * d.length, 0.35 * d.length + 12), 64));
    rotorSteel.push(lathe(rodProfile(shaftR, geo.rotorRear, 0.35 * d.length), 48), ...rearPlate);
    statics.steel.push(barrelMesh(geo, false));
  } else {
    for (let k = 0; k < K; k++) {
      const [y, z] = at(k);
      rotorSteel.push([barrelMesh(geo, true), translation(0, y, z)]);
    }
    rotorSteel.push(lathe(rodProfile(geo.envelopeR, geo.rearX, geo.rearX + geo.plateT), 64));      // the barrels' plate
    rotorSteel.push(lathe(rodProfile(shaftR, geo.rotorRear, geo.rearX), 48), ...rearPlate);
  }
  rotorSteel.push(...list("rotorSteel"));

  const group = (parts) => (parts.length ? merge(...parts) : null);
  const meshes = {};
  const put = (name, parts) => { const m = group(parts); if (m) meshes[name] = m; };
  put("steel", statics.steel);
  put("furniture", list("furniture"));
  put("paint", list("paint"));
  put("wood", list("wood"));
  put("bright", list("bright"));
  put("mount", list("mount"));
  put("pedestal", list("pedestal"));
  put("rotorSteel", rotorSteel);
  put("rotorBright", list("rotorBright"));
  put("rotorPaint", list("rotorPaint"));
  meshes.rotorBolt = boltMesh(geo);
  Object.assign(meshes, roundMeshes(cart));

  const sl = style.layout ?? {};
  const feedPath = style.feedPath?.length > 1 ? style.feedPath : null;
  const returnPath = style.returnPath?.length > 1 ? style.returnPath : null;
  const mounted = gun.shooter?.stance === "mount";
  const type = gun.feed?.type ?? "belt";
  const capacity = Math.round(gun.feed?.capacity ?? (type === "linkless" ? 500 : 100));
  const recR = sl.recR ?? geo.envelopeR + 30;
  const buttX = sl.buttX ?? geo.rotorRear - 60;
  const camera = sl.camera ?? { x: (geo.rotorRear + d.length) / 2, y: geo.axisY, width: 7 * geo.R + 4 * geo.rimR + 200 };
  const rotary = {
    ...geo, camera, feedPath, returnPath,
    feedLen: feedPath ? pathLength(feedPath) : 0, returnLen: returnPath ? pathLength(returnPath) : 0,
    hasStyle: !!STYLES[geo.style],
  };
  return {
    cartridge: cart,
    meshes,
    layout: {
      bore: gun.barrel.bore_diameter * MM, boreR: geo.boreR, muzzleX: geo.muzzleX, rearX: geo.rearX, breechR: geo.breechR,
      muzzleR: geo.muzzleR, recR, boltR: geo.boltR, buttX, pivot: sl.pivot ?? [geo.rotorRear / 2, geo.axisY - 60],
      cgX: sl.cgX ?? geo.rotorRear / 2, style: geo.style, mech: { kind: "rotary", ratio: 1, unlock: 0 },
      mounted, mountStroke: (gun.mount?.stroke ?? 0.03) * MM, chain: null, wedge: null, hand: null,
      round: roundLayout(cart),
      device: null, deviceLength: 0, flashX: geo.muzzleX,
      boltRear: sl.boltRear ?? geo.rotorRear, portFront: 0, portRear: geo.rotorRear, bridgeRear: geo.rotorRear, oal: geo.oal,
      stroke: geo.stroke, pinTravel: 0,
      seat: cart.seat, projectileLength: cart.projectileLength, coreMaterial: cart.coreMaterial,
      caseLength: d.length, head: d.head, caseInnerR: d.innerR, neckX: d.xn, rimR: d.rimR,
      feed: { type, capacity, belt: false, rackStatic: false, geo: { hand: false }, rounds: () => [], rake: 0,
              label: type === "linkless" ? "chute" : "belt" },
      autoloader: null, rotary,
    },
    warnings,
  };
}

// ---------- the shot's table ----------

/**
 * Called as a shot starts: the rotor's series and the life of every round, with phi shifted by a whole number of
 * stations so the rotor carries on from where it rests. Sets r.shot.rot (null if the result has no rotor).
 */
export function startRotary(r, result) {
  const s = r.shot, rot = result.action?.rotary, G = r.layout.rotary;
  s.rot = null;
  if (!rot?.time?.length) return;
  const K = rot.stations ?? G.K, pa = TAU / K;
  const ang = { dwell: rot.dwell, extract: rot.extract, rear: rot.rear, lock: rot.lock, feed: rot.feed, eject: rot.eject };
  const shift = pa * Math.round((r.rotRest - rot.phi[0]) / pa);
  const phi = rot.phi.map((v) => v + shift);
  const times = result.action.shot_times ?? [];
  const rounds = times.map((t) => {
    const raw = interp(rot.time, phi, t);
    const station = ((Math.round(-raw / pa) % K) + K) % K;
    const phiFire = Math.round((raw + station * pa) / TAU) * TAU - station * pa;   // the station is exactly at the top
    return { t, station, phiFire, phiFeed: phiFire - (TAU - ang.feed), phiEject: phiFire + ang.eject };
  });
  const byStation = Array.from({ length: K }, () => []);
  rounds.forEach((q, j) => byStation[q.station].push(j));
  s.rot = {
    K, pa, ang, time: rot.time, phi, speed: rot.speed, cluster: rot.cluster ?? [], rounds, byStation,
    start: phi[0], rest: r.rotRest, mag0: result.action.rounds?.[0] ?? rounds.length, nextEject: 0, ended: false,
  };
}

/** The rotor's angle (rad) now: the shot's, easing in from where it rested; else at rest. */
export function rotaryPhi(r) {
  const rot = r.shot?.rot;
  if (!rot) return r.rotRest;
  const phi = interp(rot.time, rot.phi, r.tSim);
  return r.T < EASE ? rot.rest + (phi - rot.rest) * smooth(r.T / EASE) : phi;
}

/** The round in station i with the rotor at phi: its index, or -1. */
function roundAt(rot, i, phi) {
  const list = rot.byStation[i];
  let lo = 0, hi = list.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (rot.rounds[list[mid]].phiFeed <= phi) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return best >= 0 && phi < rot.rounds[list[best]].phiEject ? list[best] : -1;
}

/** How far the barrels (or the drum) have recoiled in the receiver, mm (the recoil drive's). */
function clusterRecoil(r, rot) {
  return rot && rot.cluster.length ? interp(rot.time, rot.cluster, r.tSim) * MM : 0;
}

/** [y, z] of the barrel that fired shot j, at simulation time t (it turns on as the bullet leaves). */
export function rotaryBarrel(r, j, t) {
  const rot = r.shot?.rot, G = r.layout.rotary;
  if (!rot || !rot.rounds[j]) return [0, 0];
  return stationYZ(G, interp(rot.time, rot.phi, t) + rot.rounds[j].station * rot.pa);
}

// ---------- stepping ----------

/** Each step of a shot: throw the cases whose station has reached the port, and keep the book. */
export function stepRotary(r) {
  const s = r.shot, rot = s.rot, G = r.layout.rotary;
  if (!rot) return;
  const phi = interp(rot.time, rot.phi, r.tSim);
  const a = s.result.action;
  if (!G.returnPath) {
    while (rot.nextEject < rot.rounds.length && rot.rounds[rot.nextEject].phiEject <= phi) {
      const q = rot.rounds[rot.nextEject++];
      // The station is at the port, the case drawn back eject mm. It leaves outwards with the rotor's own speed.
      const th = rot.ang.eject, [y, z] = stationYZ(G, th), w = interp(rot.time, rot.speed, r.tSim);
      const xc = clusterRecoil(r, rot);
      const world = apply(r._gunMatrix(), [G.ejectPoint[0] - xc, y, z]);
      const out = [Math.cos(th), -Math.sin(th)], tan = [-Math.sin(th), -Math.cos(th)];
      const speed = 2200 + 400 * ((q.station * 7) % 5) / 4;           // mm/s, a little different for each
      r.ejected.push({
        kind: "spent", pos: world,
        vel: [-300 + 90 * ((q.station * 3) % 5), speed * out[0] + w * G.R * tan[0], speed * out[1] + w * G.R * tan[1]],
        spin: 0, spinRate: -30, tumble: 0, tumbleRate: 14, age: 0,
      });
    }
    if (r.ejected.length > CASE_CAP) r.ejected.splice(0, r.ejected.length - CASE_CAP);
  } else {
    while (rot.nextEject < rot.rounds.length && rot.rounds[rot.nextEject].phiEject <= phi) rot.nextEject++;
  }
  if (!rot.ended && r.tSim >= rot.time[rot.time.length - 1]) {
    rot.ended = true;
    r.mag = a.rounds_left ?? r.mag;
  }
}

// ---------- drawing ----------

/** The gun's own meshes as draw items (the rotor turned to its angle). M: range.js's materials. */
export function rotaryParts(r, gunAt, mountAt, M) {
  const m = r.meshes, G = r.layout.rotary, rot = r.shot?.rot;
  const phi = r._rotPhi = rotaryPhi(r);
  r.rotRest = phi;
  const rotorAt = chain(gunAt, translation(-clusterRecoil(r, rot), G.axisY, 0), rotationX(-phi));
  const still = translation(0, 0, 0);
  const items = [];
  const add = (name, model, material) => { if (m[name]) items.push({ mesh: m[name], model, material }); };
  add("steel", gunAt, M.steel);
  add("furniture", gunAt, M.black);
  add("wood", gunAt, M.wood);
  add("paint", gunAt, M.paint);
  add("bright", gunAt, M.bolt);
  add("mount", mountAt, M.paint);
  add("pedestal", still, M.black);
  add("rotorSteel", rotorAt, M.steel);
  add("rotorBright", rotorAt, M.bolt);
  add("rotorPaint", rotorAt, M.paint);
  return items;
}

/**
 * The bolts, the rounds in the stations, the rounds queueing up the feed and the cases riding out.
 * addRound(kind, model) is range.js's. Everything is O(stations + rounds on the paths) per frame.
 */
export function rotaryDraw(r, items, addRound, gunAt, M) {
  const G = r.layout.rotary, m = r.meshes, rot = r.shot?.rot, phi = r._rotPhi;
  const K = G.K, pa = TAU / K, ang = rot?.ang ?? G.ang, xc = clusterRecoil(r, rot);
  for (let i = 0; i < K; i++) {
    const th = phi + i * pa, [y, z] = stationYZ(G, th);
    const x = -camTravel(th, ang, G.stroke) - xc;
    items.push({ mesh: m.rotorBolt, model: chain(gunAt, translation(x, y, z), rotationX(-th)), material: M.bolt, clip: false });
    const j = rot ? roundAt(rot, i, phi) : -1;
    if (j >= 0) addRound(phi >= rot.rounds[j].phiFire ? "spent" : "live", chain(gunAt, translation(x, y, z)));
  }
  // The rounds waiting on the feed path: round j reaches the feeder as the rotor reaches its phiFeed.
  if (G.feedPath) {
    const pitch = G.linkPitch, len = G.feedLen, n = rot ? rot.rounds.length : 0;
    const have = rot ? rot.mag0 : r.mag;
    let g = 0;
    if (rot && n) g = clamp((phi - rot.rounds[0].phiFeed) / pa, 0, n - 1);
    for (let j = Math.ceil(g - 1e-9), shown = 0; j < have && shown < CHUTE_CAP; j++, shown++) {
      const s = (j - g) * pitch;
      if (s > len) break;
      const p = pathPoint(G.feedPath, len - s);
      addRound("live", chain(gunAt, translation(p[0], p[1], p[2])));
    }
  }
  // The cases riding the return path away from the port.
  if (G.returnPath && rot && rot.rounds.length) {
    let lo = 0, hi = rot.rounds.length - 1, top = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (rot.rounds[mid].phiEject <= phi) { top = mid; lo = mid + 1; } else hi = mid - 1;
    }
    for (let j = top, shown = 0; j >= 0 && shown < RETURN_CAP; j--, shown++) {
      const s = ((phi - rot.rounds[j].phiEject) / pa) * G.linkPitch;
      if (s > G.returnLen) break;
      const p = pathPoint(G.returnPath, s);
      addRound("spent", chain(gunAt, translation(p[0], p[1], p[2])));
    }
  }
}

// ---------- readout ----------

/** The rotor's rounds/min now. */
function rate(r) {
  const rot = r.shot?.rot;
  return rot ? (interp(rot.time, rot.speed, r.tSim) * rot.K * 60) / TAU : 0;
}

/** The HUD's phase line, replacing range.js's where the rotor decides it. */
export function rotaryPhase(r, phase) {
  const rot = r.shot?.rot, a = r.shot?.result.action;
  if (!rot || r.T < EASE) return phase;
  const t = r.tSim, last = a.shot_times[a.shot_times.length - 1] ?? 0;
  if (t < 0) return `Spinning up: ${Math.round(rate(r)).toLocaleString()} rounds/min`;
  if (r.exitT === null || t - r.exitT < 0.003) return phase;
  if (t <= last) return `Firing: ${Math.round(rate(r)).toLocaleString()} rounds/min`;
  if (t <= a.rotary.end) return a.status === "empty" ? "Belt empty: the rotor clears the gun" : "Last round fired: the rotor clears the gun";
  return a.status === "fired" || a.status === "empty" ? "Smoke" : `Smoke · ${a.status}`;
}

/** Extra HUD rows: the rotor's speed. */
export function rotaryRows(r) {
  if (!r.shot?.rot) return [];
  return [["rotor", `${Math.round(rate(r)).toLocaleString()} rounds/min`]];
}

/** Camera: the breech view of a rotary gun. */
export function rotaryCamera(L) {
  return L.rotary.camera;
}

export { camAngles };
