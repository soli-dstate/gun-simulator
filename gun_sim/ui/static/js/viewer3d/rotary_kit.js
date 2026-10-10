// Shared geometry and helpers for rotary guns (rotary.js and the styles in rotary_styles/).
//
// Units are millimetres, in the gun's frame as gun.js has it: x along the bore towards the muzzle
// with x = 0 at the case head of a chambered round (the bolt face when the bolt is shut), y up, z to
// the right. The firing station is on the bore line (y = 0, z = 0). The rotor's axis runs along x
// at y = -R (geo.axisY), z = 0, R being the cluster radius.
//
// Station angles. A station's angle theta (rad) is measured from the firing position (the top) in
// the direction the rotor turns, which is counter-clockwise seen from behind the gun. In the gun's
// frame the station is at (y, z) = (axisY + R cos theta, -R sin theta): theta = 90 deg is on the
// LEFT side (z < 0), 180 deg at the bottom, 270 deg on the right. A lathe's own angle, measured from
// +y towards +z, is the negative of theta.
//
// ROTOR FRAME. Parts that turn with the rotor are modelled with the rotor's axis as the x axis through
// the origin (so station 0 is at (y, z) = (R, 0), station k at (R cos(2 pi k / K), -R sin(2 pi k / K))).
// range.js turns them by the rotor's angle. Every other part is modelled in the gun's frame.
//
// A "part" is either mesh data or a [mesh, matrix] pair, as meshops.js merge() takes.

import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { merge } from "./meshops.js";
import { box, rodProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
export const TAU = 2 * Math.PI;
const DEG = Math.PI / 180;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// As gun_sim/rotary.py: the cam's legs (degrees from the firing position).
const EXTRACT_END = 180 * DEG, REAR_DWELL = 30 * DEG, LOCK_IN = 30 * DEG;

/** The cam's angles (rad) for a dwell angle in degrees, as rotary.py cam_angles(). */
export function camAngles(dwellDeg) {
  const dwell = dwellDeg * DEG, extract = EXTRACT_END, rear = extract + REAR_DWELL, lock = TAU - LOCK_IN;
  return { dwell, extract, rear, lock, feed: (extract + rear) / 2 };
}

/** A bolt's travel back from battery at angle theta, in the units of `stroke` (rotary.py cam()). */
export function camTravel(theta, ang, stroke) {
  theta = ((theta % TAU) + TAU) % TAU;
  const { dwell: a, extract: e, rear: r, lock: l } = ang;
  if (theta < a || theta >= l) return 0;
  if (theta < e) {
    const b = (theta - a) / (e - a);
    return stroke * (b - Math.sin(TAU * b) / TAU);
  }
  if (theta < r) return stroke;
  const b = (theta - r) / (l - r);
  return stroke * (1 - b + Math.sin(TAU * b) / TAU);
}

/** Angle on the stroke back at which the bolt has drawn the case `eject` clear (rotary.py eject_angle()). */
export function ejectAngle(ang, stroke, eject) {
  let lo = ang.dwell, hi = ang.extract;
  for (let k = 0; k < 50; k++) {
    const mid = (lo + hi) / 2;
    if (camTravel(mid, ang, stroke) < eject) lo = mid; else hi = mid;
  }
  return hi;
}

/** Everything about the rotor's layout that the styles need, from the gun config and its cartridge. */
export function rotaryGeo(gun, cart) {
  const a = gun.action ?? {}, d = cart.dims;
  const revolver = a.rotary_layout === "revolver";
  const K = Math.round(revolver ? (a.chambers ?? 5) : (a.barrels ?? 6));
  const sinK = Math.sin(Math.PI / K);
  const R = a.cluster_radius != null ? a.cluster_radius * MM
    : revolver ? (gun.case.rim_diameter * MM * 1.35) / (2 * sinK) : (gun.barrel.breech_diameter * MM + 2) / (2 * sinK);
  const stroke = a.bolt_travel != null ? a.bolt_travel * MM : gun.case.overall_length * MM + 11;
  const ang = camAngles(a.dwell_angle ?? 40);
  const eject = gun.case.length * MM + 3;
  ang.eject = ejectAngle(ang, stroke, eject);

  const oal = Math.max(gun.case.overall_length * MM, d.length);
  const rb = (gun.barrel.bore_diameter * MM) / 2, boreR = rb + 0.02, c = 0.05;
  const rearX = d.rimT + 0.6, throatX = d.length + 0.25;
  const leadeX = throatX + Math.max(0.6, (d.neckR + c - boreR) * 2.5);
  const boltR = Math.max(d.rimR + 2.2, d.baseR * 1.3);
  const boltLen = clamp(0.8 * d.length, 30, 160);
  let breechR = (gun.barrel.breech_diameter * MM) / 2;
  breechR = Math.max(breechR, Math.max(d.baseR, d.shR, d.rimR) + c + 2);
  let muzzleR = Math.max((gun.barrel.muzzle_diameter * MM) / 2, boreR + 1);
  muzzleR = Math.min(muzzleR, breechR);
  const muzzleX = Math.max(cart.seat + gun.barrel.travel * MM, leadeX + 5);
  // A revolver's barrel stands ahead of the drum, across a gap; a gatling's barrels start at the chamber.
  const barrelX0 = revolver ? d.length + 8 : rearX;
  const shankEnd = Math.min(d.length + 25, barrelX0 + (muzzleX - barrelX0) * 0.35);
  const taperEnd = shankEnd + (muzzleX - shankEnd) * 0.55;
  const barrelR = (x) => {
    const s = clamp((x - shankEnd) / (taperEnd - shankEnd), 0, 1);
    return breechR + (muzzleR - breechR) * s * s * (3 - 2 * s);
  };
  const plateT = Math.max(10, 1.4 * boltR);
  const geo = {
    K, layout: revolver ? "revolver" : "gatling", revolver, drive: a.rotary_drive ?? "electric",
    style: gun.appearance?.style ?? "rotary",
    R, axisY: -R, stroke, ang, pitchAngle: TAU / K,
    recoilStroke: a.rotary_drive === "recoil" ? (a.recoil_stroke ?? 0.02) * MM : 0,
    d, oal, caseLength: d.length, rimR: d.rimR, baseR: d.baseR, head: d.head,
    boreR, breechR, muzzleR, muzzleX, rearX, throatX, leadeX, barrelX0, shankEnd, taperEnd, barrelR,
    boltR, boltLen, plateT,
    rotorRear: -(stroke + boltLen + 14),        // x of the rotor's rear face
    rollerR: R + boltR + 7,                     // how far out the bolts' rollers reach from the rotor axis
    envelopeR: R + breechR,                     // radius of the rotor's barrel end
    linkPitch: 2 * d.rimR + 2,                  // round to round along a belt or chute
    seat: cart.seat, seatCase: gun.case.overall_length * MM,
  };
  const [fy, fz] = stationYZ(geo, ang.feed), [ey, ez] = stationYZ(geo, ang.eject);
  geo.feedPoint = [-stroke, fy, fz];           // the case head of a round as the feeder drops it in
  geo.ejectPoint = [-camTravel(ang.eject, ang, stroke), ey, ez];   // and of a case as it clears the chamber
  geo.feedDir = [Math.cos(ang.feed), -Math.sin(ang.feed)];         // [y, z] unit vectors, outward from the axis
  geo.ejectDir = [Math.cos(ang.eject), -Math.sin(ang.eject)];
  return geo;
}

/** [y, z] of the station at angle theta, in the gun's frame. */
export function stationYZ(geo, theta) {
  return [geo.axisY + geo.R * Math.cos(theta), -geo.R * Math.sin(theta)];
}

/**
 * Matrix placing a part built for the TOP station (barrel axis on the x axis at the origin, +y outward from the
 * rotor's axis) onto station k, in the ROTOR frame. Use it for things that ride with one barrel (a gas cylinder
 * beside it, a piston, a perforated sleeve...): chain(stationMatrix(geo, k), translation(...)) or [mesh, stationMatrix(geo, k)].
 */
export function stationMatrix(geo, k) {
  return chain(rotationX(-TAU * k / geo.K), translation(0, geo.R, 0));
}

/**
 * One barrel, built with its axis on the x axis: chamber and bore cut to the cartridge, tapering
 * from the breech to the muzzle, from geo.barrelX0 to geo.muzzleX. chamber = false for a revolver
 * cannon's fixed barrel (a bore only, with a short lead-in).
 */
export function barrelMesh(geo, chamber = true) {
  const { d, boreR, breechR, muzzleR, muzzleX, shankEnd, taperEnd, barrelX0: x0, throatX, leadeX } = geo;
  const c = 0.05;
  const r0 = d.baseR + (d.shR - d.baseR) * clamp((x0 - d.bodyStart) / Math.max(d.xs - d.bodyStart, 1e-6), 0, 1) + c;
  const ch = Math.min(0.8, (breechR - r0) / 3);
  const crown = Math.min(1.0, (muzzleR - boreR) * 0.4);
  const mc = Math.min(0.8, (muzzleR - boreR - crown) * 0.5);
  const contour = [];
  for (let k = 0; k <= 16; k++) {
    const s = k / 16, e = s * s * (3 - 2 * s);
    contour.push([breechR + (muzzleR - breechR) * e, shankEnd + (taperEnd - shankEnd) * s]);
  }
  const outside = [
    [[breechR - ch, x0], [breechR, x0 + ch]],
    [[breechR, x0 + ch], [breechR, shankEnd]],
    contour,
    [[muzzleR, taperEnd], [muzzleR, muzzleX - mc]],
    [[muzzleR, muzzleX - mc], [muzzleR - mc, muzzleX]],
    [[muzzleR - mc, muzzleX], [boreR + crown, muzzleX]],
    [[boreR + crown, muzzleX], [boreR, muzzleX - crown]],
  ];
  if (!chamber) {
    return lathe([[[boreR, x0], [breechR - ch, x0]], ...outside, [[boreR, muzzleX - crown], [boreR, x0]]], 64);
  }
  const chamberBody = d.bodyStart > x0
    ? [[d.shR + c, d.xs], [d.baseR + c, d.bodyStart], [r0, x0]]
    : [[d.shR + c, d.xs], [r0, x0]];
  return lathe([
    [[r0, x0], [breechR - ch, x0]],
    ...outside,
    [[boreR, muzzleX - crown], [boreR, leadeX]],
    [[boreR, leadeX], [d.neckR + c, throatX]],
    [[d.neckR + c, throatX], [d.neckR + c, d.xn]],
    [[d.neckR + c, d.xn], [d.shR + c, d.xs]],
    chamberBody,
  ], 64);
}

/**
 * One bolt (a revolver cannon's rammer), face at x = 0 and the body running back to x = -geo.boltLen,
 * built for a station at the top: a roller stud stands out of its back towards +y, the way the
 * housing's cam groove is.
 */
export function boltMesh(geo) {
  const { boltR, boltLen, d } = geo;
  const noseR = d.rimR + 1.0, recessR = d.rimR + 0.12;
  const body = lathe([
    [[1.0, -boltLen], [boltR - 0.8, -boltLen]],
    [[boltR - 0.8, -boltLen], [boltR, -boltLen + 0.8]],
    [[boltR, -boltLen + 0.8], [boltR, -0.6]],
    [[boltR, -0.6], [boltR - 0.6, 0]],
    [[boltR - 0.6, 0], [noseR, 0]],
    [[noseR, 0], [noseR, d.rimT + 0.35]],
    [[noseR, d.rimT + 0.35], [recessR, d.rimT + 0.35]],
    [[recessR, d.rimT + 0.35], [recessR, -0.05]],
    [[recessR, -0.05], [1.0, -0.05]],
    [[1.0, -0.05], [1.0, -boltLen]],
  ], 48);
  const stud = Math.max(3, 0.28 * boltR);
  return merge(
    body,
    [box(2.4 * stud, geo.rollerR - geo.R - boltR + 2, 1.6 * stud), translation(-boltLen * 0.55, boltR + (geo.rollerR - geo.R - boltR) / 2, 0)],
    [lathe(rodProfile(stud * 1.1, -1.5 * stud, 1.5 * stud), 16), chain(translation(-boltLen * 0.55, geo.rollerR - geo.R, 0), rotationZ(Math.PI / 2))],
  );
}

// ---------- helpers for the styles ----------

/** A tube (ri = 0 for a solid rod) along x from x0 to x1, centred at (y, z). A part. */
export function tubeX(ri, ro, x0, x1, y = 0, z = 0, seg = 48) {
  return [lathe(ri > 0 ? tubeProfile(ri, ro, x0, x1) : rodProfile(ro, x0, x1), seg), translation(0, y, z)];
}

/**
 * A tube about the ROTOR'S AXIS in the gun's frame (for housings), from x0 to x1. a0..a1 are lathe
 * angles (rad, from +y towards +z) if only part of the way round is wanted, e.g. a housing with an opening
 * at the bottom: lathe angle = -theta, so the opening at theta = 195 deg is at lathe angle -195 deg = 165 deg.
 */
export function axisTube(geo, ri, ro, x0, x1, a0 = 0, a1 = TAU, seg = 64) {
  return [lathe(tubeProfile(ri, ro, x0, x1), seg, a0, a1), translation(0, geo.axisY, 0)];
}

/**
 * A shell (tube) about the rotor's axis with windows cut in it, from x0 to x1. windows: [{theta, half}], each an
 * opening centred at station angle theta (rad, see the top of this file; geo.ang.feed is the feeder's, geo.ang.eject
 * the ejection port's) and 2 * half wide. Returns parts (one arc between each pair of windows).
 */
export function axisShell(geo, ri, ro, x0, x1, windows = [], seg = 64) {
  if (!windows.length) return [axisTube(geo, ri, ro, x0, x1, 0, TAU, seg)];
  // Each window as an interval of lathe angle (= -theta), start in [0, 2 pi).
  const gaps = windows.map((w) => ({ a: ((-(w.theta + w.half) % TAU) + TAU) % TAU, len: 2 * w.half }))
    .sort((p, q) => p.a - q.a);
  const parts = [];
  gaps.forEach((g, i) => {
    const next = gaps[(i + 1) % gaps.length];
    const from = g.a + g.len;
    let to = next.a;
    if (to <= from) to += TAU;
    if (to - from > 0.02) parts.push(axisTube(geo, ri, ro, x0, x1, from, to, seg));
  });
  return parts;
}

/** A solid disc or rod about the rotor's axis in the gun's frame. */
export function axisRod(geo, r, x0, x1, seg = 64) {
  return [lathe(rodProfile(r, x0, x1), seg), translation(0, geo.axisY, 0)];
}

/** A cylinder of radius r from point p0 to p1 (each [x, y, z]). A part. */
export function segment(r, p0, p1, seg = 16) {
  const [dx, dy, dz] = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
  const len = Math.hypot(dx, dy, dz);
  const yaw = Math.atan2(-dz, dx), pitch = Math.atan2(dy, Math.hypot(dx, dz));
  return [lathe(rodProfile(r, 0, len, Math.min(r * 0.3, len / 4)), seg), chain(translation(...p0), rotationY(yaw), rotationZ(pitch))];
}

/** A box h tall and w wide (across its length) from p0 to p1: a straight slab of a chute or a strap. A part. */
export function slab(h, w, p0, p1) {
  const [dx, dy, dz] = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
  const len = Math.hypot(dx, dy, dz);
  const yaw = Math.atan2(-dz, dx), pitch = Math.atan2(dy, Math.hypot(dx, dz));
  return [box(len, h, w), chain(translation(...p0), rotationY(yaw), rotationZ(pitch), translation(len / 2, 0, 0))];
}

/** A tube following a polyline [[x, y, z], ...]: a cylinder per leg and a ball-less joint (a short overlap). Parts. */
export function tubePath(r, path, seg = 16) {
  return path.slice(1).map((p, i) => segment(r, path[i], p, seg));
}

/** A square-section chute (h tall, w wide) following a polyline: a slab per leg. Parts. */
export function chutePath(h, w, path) {
  return path.slice(1).map((p, i) => slab(h, w, path[i], p));
}

/**
 * A carrier channel for the rounds of a feed or return path: along each leg, two thin end plates, one just
 * behind each round's case head and one just ahead of its nose, so the rounds ride between them. The plates
 * are axis-aligned, so the legs of the path should run along y or z (they may also run along x). Parts.
 */
export function chuteFrame(geo, path) {
  const d = 2 * geo.rimR + 6, parts = [];
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const sy = Math.abs(b[1] - a[1]) + d, sz = Math.abs(b[2] - a[2]) + d;
    const cy = (a[1] + b[1]) / 2, cz = (a[2] + b[2]) / 2;
    for (const x of [Math.min(a[0], b[0]) - 3, Math.max(a[0], b[0]) + geo.oal + 3]) {
      parts.push([box(3, sy, sz), translation(x, cy, cz)]);
    }
    if (Math.abs(b[0] - a[0]) > 1) {   // a leg along x: plates above and below instead
      const cx = (a[0] + b[0]) / 2 + geo.oal / 2, len = Math.abs(b[0] - a[0]) + geo.oal + 6;
      for (const s of [-1, 1]) parts.push([box(len, 3, d), translation(cx, a[1] + s * (geo.rimR + 3), a[2])]);
    }
  }
  return parts;
}

/** Length of a polyline. */
export function pathLength(path) {
  let s = 0;
  for (let i = 1; i < path.length; i++) s += Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1], path[i][2] - path[i - 1][2]);
  return s;
}

/** The point `s` along a polyline from its FIRST point (clamped to its ends): [x, y, z]. */
export function pathPoint(path, s) {
  let rest = Math.max(s, 0);
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i], len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    if (rest <= len || i === path.length - 1) {
      const f = len > 0 ? Math.min(rest / len, 1) : 0;
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
    }
    rest -= len;
  }
  return path[0];
}
