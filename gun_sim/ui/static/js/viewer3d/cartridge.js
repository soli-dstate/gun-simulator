// Procedural cartridge: profiles for the case, primer and projectile, built
// from the gun config. Everything here is in millimetres, with x measured
// along the axis from the case head.
//
// A combustible case is split at its stub: the metal stub base, and the felt
// body that burns with the charge. An APFSDS round is a long rod with fins at
// its tail and a three-petal sabot round it; the projectile's origin is the
// sabot's rear face (where the gas pushes), so the fins reach back behind it
// into the propellant.

import { lathe, profileVolume, radiusAt, radiusVolume } from "./lathe.js";
import { rotationX } from "./mat4.js";
import { prism } from "./shapes.js";

const MM = 1e3;
const DEG = Math.PI / 180;
const CORE_NAMES = ["lead", "steel", "copper", "tungsten", "hardened_steel", "tungsten_carbide"];   // config.CORE_MATERIALS, in index order
export const FINS = 6;
export const PETALS = 3;
const PETAL_GAP = 0.04;   // rad between the sabot's petals
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Bottleneck case. Returns {parts, cavity, dims, warnings}; cavity is the inner wall as [r, x] sorted by x. */
export function caseProfile(c, bore) {
  const warnings = [];
  const R = bore / 2 + 0.01;                           // neck bore: projectile radius + 10 µm so the surfaces don't z-fight
  const L = c.length;
  const rimR = c.rim_diameter / 2, rimT = clamp(c.rim_thickness, 0.05, L / 4);
  const baseR = Math.max(c.base_diameter / 2, R + 0.2);
  let shR = c.shoulder_diameter / 2;
  if (shR > baseR) { warnings.push("shoulder is wider than the base; clamped"); shR = baseR; }
  const nw = Math.max(c.neck_wall, 0.05), bw = Math.max(c.body_wall, 0.05);
  const neckR = R + nw;
  if (shR < neckR) { warnings.push("shoulder is narrower than the neck; clamped"); shR = neckR; }
  const head = clamp(c.head_thickness, rimT, L / 2);
  const pr = clamp(c.primer_diameter / 2, 0.3, baseR - 1);
  const pd = clamp(c.primer_depth, 0.2, head - 0.3);
  const flashR = Math.min(0.13 * bore, pr / 2);
  const chamfer = Math.min(0.4, rimT * 0.3, rimR * 0.1);

  const parts = [
    [[flashR, pd], [pr, pd]],                       // primer pocket floor
    [[pr, pd], [pr, 0]],                            // pocket wall
    [[pr, 0], [rimR - chamfer, 0]],                 // head face
    [[rimR - chamfer, 0], [rimR, chamfer]],         // edge chamfer
    [[rimR, chamfer], [rimR, rimT]],                // rim
  ];
  let bodyStart = rimT;
  const grooveR = c.groove_diameter / 2;
  if (grooveR < Math.min(rimR, baseR) - 0.05) {
    const gw = Math.max(c.groove_width, 0.1);
    bodyStart = rimT + gw + (baseR - grooveR);    // 45° ramp back up to the body
    parts.push(
      [[rimR, rimT], [grooveR, rimT]],
      [[grooveR, rimT], [grooveR, rimT + gw]],
      [[grooveR, rimT + gw], [baseR, bodyStart]],
    );
  } else if (Math.abs(rimR - baseR) > 1e-3) {
    parts.push([[rimR, rimT], [baseR, rimT]]);     // rimmed: a step from rim to body
  }

  // Shoulder: a cone from shoulder_position, angle measured from the axis-normal plane.
  const angle = clamp(c.shoulder_angle, 5, 85) * DEG;
  const shoulderLen = (shR - neckR) / Math.tan(angle);
  let xs = c.shoulder_position;
  if (xs + shoulderLen > L - 0.5) {
    warnings.push("neck is shorter than 0.5 mm; shoulder moved back");
    xs = L - 0.5 - shoulderLen;
  }
  if (xs < Math.max(bodyStart, head) + 1) {
    warnings.push("shoulder is too close to the head");
    xs = Math.max(bodyStart, head) + 1;
  }
  const xn = xs + shoulderLen;

  // Inside: the wall thickens towards the head, then a fillet into the solid web.
  const innerShR = shR - bw, innerBaseR = Math.max(baseR - 1.8 * bw, flashR + 1);
  const xsIn = xs + bw * 0.6, xnIn = Math.min(xn + nw * 0.6, L - 0.2);
  const fillet = Math.min(1.2, (innerBaseR - flashR) / 2, (xsIn - head) / 3);
  const filletPts = [];
  for (let k = 0; k <= 8; k++) {
    const phi = (-k / 8) * (Math.PI / 2);
    filletPts.push([innerBaseR - fillet + fillet * Math.cos(phi), head + fillet + fillet * Math.sin(phi)]);
  }

  parts.push(
    [[baseR, bodyStart], [shR, xs]],                // body taper
    [[shR, xs], [neckR, xn]],                       // shoulder
    [[neckR, xn], [neckR, L]],                      // neck
    [[neckR, L], [R, L]],                           // mouth
    [[R, L], [R, xnIn]],                            // neck bore
    [[R, xnIn], [innerShR, xsIn]],                  // inside of the shoulder
    [[innerShR, xsIn], [innerBaseR, head + fillet]],// inside of the body
    filletPts,
    [[innerBaseR - fillet, head], [flashR, head]],  // top of the web
    [[flashR, head], [flashR, pd]],                 // flash hole
  );

  const cavity = [[innerBaseR - fillet, head], ...filletPts.slice().reverse().slice(1),
                  [innerShR, xsIn], [R, xnIn], [R, L]];
  cavity.sort((a, b) => a[1] - b[1]);
  const dims = { rimR, rimT, baseR, bodyStart, shR, xs, xn, neckR, length: L, head, innerR: innerShR };
  return { parts, cavity, pocket: { r: pr, depth: pd }, dims, warnings };
}

/** Primer cup sitting in the pocket, slightly below the head face. */
export function primerProfile({ r, depth }) {
  const pr = r - 0.01, x0 = 0.08, top = depth - 0.02, ch = Math.min(0.15, pr * 0.1);
  return [
    [[0, x0], [pr - ch, x0]],
    [[pr - ch, x0], [pr, x0 + ch]],
    [[pr, x0 + ch], [pr, top]],
    [[pr, top], [0, top]],
  ];
}

// Points of the nose from (R, x0) to (rm, x0 + ogive). ratio = ogive radius / tangent-ogive radius:
// 1 is a tangent ogive (it meets the body smoothly); above 1 it is a secant ogive, a flatter arc
// that meets the body at an angle.
function nosePoints(R, rm, x0, ogive, ratio, n = 32) {
  const dR = R - rm, c = Math.hypot(ogive, dR);
  const rhoT = (c * c) / (2 * dR);                    // tangent ogive: circle centred at (R - rhoT, x0)
  const pts = [];
  if (ratio <= 1.0001) {
    for (let k = 0; k <= n; k++) {
      const x = x0 + ogive * (1 - (1 - k / n) ** 1.5);  // denser near the tip
      pts.push([R - rhoT + Math.sqrt(Math.max(rhoT * rhoT - (x - x0) ** 2, 0)), x]);
    }
    pts[n][0] = rm;
    return pts;
  }
  // Secant: a circle of radius rho through both ends, its centre on the axis side of the chord.
  const rho = rhoT * ratio, h = Math.sqrt(Math.max(rho * rho - (c * c) / 4, 0));
  const cr = (R + rm) / 2 - (h * ogive) / c, cx = x0 + ogive / 2 - (h * dR) / c;
  const a0 = Math.atan2(x0 - cx, R - cr), a1 = Math.atan2(x0 + ogive - cx, rm - cr);
  for (let k = 0; k <= n; k++) {
    const a = a0 + (a1 - a0) * (1 - (1 - k / n) ** 1.5);
    pts.push([cr + rho * Math.cos(a), cx + rho * Math.sin(a)]);
  }
  pts[0] = [R, x0];
  pts[n] = [rm, x0 + ogive];
  return pts;
}

/** Points of a profile's parts with x <= xMax (the last segment is cut where it crosses). */
function clipParts(parts, xMax) {
  const out = [];
  for (const part of parts) {
    const kept = [];
    for (let i = 0; i < part.length; i++) {
      const [r, x] = part[i];
      if (x <= xMax) { kept.push([r, x]); continue; }
      if (i > 0 && part[i - 1][1] < xMax) {
        const [r0, x0] = part[i - 1];
        kept.push([r0 + ((r - r0) * (xMax - x0)) / (x - x0), xMax]);
      }
      break;
    }
    if (kept.length >= 2) out.push(kept);
    if (kept.length < part.length) break;
  }
  return out;
}

/** Points of a profile's parts with x >= xMin (the first segment is cut where it crosses). */
function tailParts(parts, xMin) {
  const out = [];
  for (const part of parts) {
    const kept = [];
    for (let i = 0; i < part.length; i++) {
      const [r, x] = part[i];
      if (x >= xMin) {
        if (!kept.length && i > 0) {
          const [r0, x0] = part[i - 1];
          kept.push([r0 + ((r - r0) * (xMin - x0)) / (x - x0), xMin]);
        }
        kept.push([r, x]);
      }
    }
    if (kept.length >= 2) out.push(kept);
  }
  return out;
}

/**
 * A closed profile cut across at x = xc into the solid below it and the solid above it, each
 * closed by a flat face across the wall there (r from the outside of the cut to its inside).
 */
function splitParts(parts, xc) {
  const below = [], above = [], cuts = [];
  for (const part of parts) {
    let run = [part[0]], side = part[0][1] <= xc;
    for (let i = 1; i < part.length; i++) {
      const [r0, x0] = part[i - 1], [r1, x1] = part[i];
      const now = x1 <= xc;
      if (now !== side) {
        const p = [r0 + ((r1 - r0) * (xc - x0)) / (x1 - x0), xc];
        run.push(p);
        cuts.push(p[0]);
        (side ? below : above).push(run);
        run = [p];
        side = now;
      }
      run.push(part[i]);
    }
    if (run.length >= 2) (side ? below : above).push(run);
  }
  // The first crossing is the outside going up, the last the inside coming down.
  const rOut = Math.max(...cuts), rIn = Math.min(...cuts);
  below.push([[rOut, xc], [rIn, xc]]);
  above.push([[rIn, xc], [rOut, xc]]);
  return { below, above };
}

/** Polyline [r, x] pushed inward (towards the axis) by d, mitred at the corners. */
function insetPolyline(pts, d) {
  const normals = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const dr = pts[i + 1][0] - pts[i][0], dx = pts[i + 1][1] - pts[i][1], len = Math.hypot(dr, dx) || 1;
    normals.push([dx / len, -dr / len]);               // outward [n_r, n_x]
  }
  const out = pts.map(([r, x], i) => {
    const a = normals[Math.max(0, i - 1)], b = normals[Math.min(normals.length - 1, i)];
    let mr = a[0] + b[0], mx = a[1] + b[1];
    const len = Math.hypot(mr, mx) || 1;
    mr /= len; mx /= len;
    const k = d / Math.max(mr * a[0] + mx * a[1], 0.35);
    return [Math.max(r - mr * k, 0), x - mx * k];
  });
  const mono = [];                                     // keep x increasing where a concave corner folds back
  for (const pt of out) if (!mono.length || pt[1] > mono[mono.length - 1][1] + 1e-6) mono.push(pt);
  return mono;
}

/**
 * Projectile with its variants. Base at x = 0.
 *   outer shape: boat tail, bearing surface (optional cannelure), tangent or secant ogive, meplat,
 *                optional hollow point
 *   jacketed:    `parts` is the whole envelope in the jacket's metal (or just its part up to the
 *                jacket mouth for a soft point) and `core` a smaller solid inside it, so a cutaway
 *                shows a jacket ring around the core. The core is inset by the jacket thickness.
 * Returns {parts, core (or null), outline, body, warnings}.
 */
export function projectileProfile(p, bore) {
  const warnings = [];
  const R = bore / 2;
  const len = Math.max(p.length, 1);
  let bt = clamp(p.boat_tail_length, 0, len * 0.4);
  const baseR = Math.max(R - bt * Math.tan(clamp(p.boat_tail_angle, 0, 30) * DEG), 0.3 * R);
  if (bt > 0 && baseR === 0.3 * R) warnings.push("boat tail is very steep; base clamped");
  let ogive = clamp(p.ogive_length, 0, len - bt);
  if (ogive < p.ogive_length) warnings.push("ogive + boat tail are longer than the projectile");
  let rm = clamp(p.meplat_diameter / 2, 0, R * 0.95);
  const x0 = len - ogive;                          // ogive starts here

  // Construction and hollow point (all 0 = absent).
  const t = p.jacket_thickness > 0 ? clamp(p.jacket_thickness, 0.05, R * 0.5) : 0;
  let hpR = clamp((p.hollow_point_diameter || 0) / 2, 0, R * 0.9), hd = hpR > 0 ? clamp(p.hollow_point_depth || 0, 0, len * 0.7) : 0;
  if (hd <= 0) hpR = 0;
  // Soft point: the jacket stops `soft` short of the tip; it has to stop short of the cavity bottom too.
  let soft = t > 0 ? clamp(p.exposed_core_length || 0, 0, len - Math.max(t, bt) - 0.3) : 0;
  if (soft > 0 && hd > 0) {
    soft = Math.min(Math.max(soft, hd + 0.05), len - Math.max(t, bt) - 0.3);
    hd = Math.min(hd, soft - 0.05);
    if (hd <= 0) hpR = 0;
  }
  if (hpR > 0) {
    const need = hpR + (t > 0 ? 2 * t + 0.05 : Math.max(0.1, 0.1 * R));   // meplat has to leave a rim around the cavity
    if (rm < need) {
      rm = Math.min(need, R * 0.95);
      warnings.push("meplat widened to fit the hollow point");
    }
    if (t > 0) hpR = Math.max(Math.min(hpR, rm - 2 * t - 0.05), 0);
    if (hpR < 0.05) hpR = hd = 0;
  }
  const xb = len - hd;                             // bottom of the cavity

  // Outside, from the base edge to the tip, as parts with hard edges between them.
  const outer = [];
  if (bt > 0) outer.push([[baseR, 0], [R, bt]]);
  const cd = clamp(p.cannelure_depth || 0, 0, R * 0.3), cw = p.cannelure_width || 0;
  let xc = clamp(p.cannelure_position || 0, 0, len);
  if (cd > 0 && cw > 0) {
    // Crimp groove: flat bottom, 45° flanks. It has to sit on the bearing surface.
    const lo = bt + cw / 2 + 0.05, hi = x0 - cw / 2 - 0.05;
    if (hi < lo) warnings.push("no room for the cannelure on the bearing surface");
    else {
      if (xc < lo || xc > hi) warnings.push("cannelure moved onto the bearing surface");
      xc = clamp(xc, lo, hi);
      const f = Math.min(cd, cw / 4), a = xc - cw / 2, b = xc + cw / 2;
      outer.push(
        [[R, bt], [R, a]], [[R, a], [R - cd, a + f]], [[R - cd, a + f], [R - cd, b - f]],
        [[R - cd, b - f], [R, b]], [[R, b], [R, x0]],
      );
    }
  }
  if (outer.length === (bt > 0 ? 1 : 0)) outer.push([[R, bt], [R, x0]]);
  outer.push(ogive > 0.01 ? nosePoints(R, rm, x0, ogive, p.ogive_radius_ratio || 1) : [[R, x0], [rm, len]]);

  // Front end: flat meplat, or an annulus round a cavity (walls at radius r, bottom at depth x).
  const front = (r, x) => (hpR > 0 ? [[[rm, len], [r, len]], [[r, len], [r, x]], [[r, x], [0, x]]] : rm > 0 ? [[[rm, len], [0, len]]] : []);
  const baseDisc = [[0, 0], [baseR, 0]];
  const body = [baseDisc, ...outer, ...front(hpR, xb)];
  const flat = [baseDisc, ...outer, ...(rm > 0 ? [[[rm, len], [0, len]]] : [])].flat();
  const outline = flat.filter((pt, i, all) => i === 0 || pt[1] >= all[i - 1][1]);
  if (t === 0) return { parts: body, core: null, outline, body, warnings };

  // Jacketed. The envelope is the outside of the projectile; the core sits inside it.
  const eps = 0.01;                                // keeps the core's surfaces off the envelope's
  const xf = len - soft;                           // jacket mouth
  let shell;
  if (soft > 0) {
    const cut = clipParts(outer, xf - eps);
    const last = cut[cut.length - 1];
    const end = last[last.length - 1];
    shell = [baseDisc, ...cut, [end, [0, end[1]]]];
  } else {
    shell = [baseDisc, ...outer, ...front(hpR + eps, xb)];
  }

  // Inner surface of the jacket, from the base plate forward.
  const ring = insetPolyline([[baseR, 0], ...outer.flat().filter((pt, i, all) => i === 0 || pt[0] !== all[i - 1][0] || pt[1] !== all[i - 1][1])], t + eps);
  const rAt = (x) => radiusAt(ring, x);
  const xBase = t + eps;
  const inner = [[rAt(xBase), xBase], ...ring.filter((pt) => pt[1] > xBase)];
  const core = [[[0, xBase], [rAt(xBase), xBase]]];
  const upTo = (x) => {
    const pts = inner.filter((pt) => pt[1] < x);
    return [...pts, [rAt(x), x]];
  };
  if (soft > 0) {
    // Bare core from the jacket mouth: step out to the outside, follow it to the tip.
    const rOut = tailParts(outer, xf)[0][0][0];
    core.push(upTo(xf), [[rAt(xf), xf], [rOut, xf]], ...tailParts(outer, xf), ...front(hpR, xb + eps));
  } else if (hpR > 0) {
    const xe = len - eps * 2;
    core.push(upTo(xe), [[rAt(xe), xe], [hpR, xe]], [[hpR, xe], [hpR, xb + eps]], [[hpR, xb + eps], [0, xb + eps]]);
  } else {
    const xe = len - t - eps;                      // jacket closes over the nose
    core.push(upTo(xe), [[rAt(xe), xe], [0, xe]]);
  }
  return { parts: shell, core, outline, body, warnings };
}

/** Parts shifted by dx along the axis. */
const shiftParts = (parts, dx) => parts.map((part) => part.map(([r, x]) => [r, x + dx]));

/**
 * An APFSDS sabot round a rod of radius rr, filling a bore of radius R, rear face at x = 0: a double
 * ramp, thick at the bore-riding band in the middle and tapering to both ends.
 */
function sabotProfile(R, rr, len) {
  const a = 0.35 * len, b = 0.55 * len, front = rr + 0.3 * (R - rr);
  return [
    [[rr, 0], [0.55 * R, 0]],                    // rear face
    [[0.55 * R, 0], [R, a]],                     // rear ramp
    [[R, a], [R, b]],                            // the bore-riding band and obturator
    [[R, b], [0.85 * R, b + 0.04 * len]],        // step down to the front scoop
    [[0.85 * R, b + 0.04 * len], [front, len]],  // front ramp
    [[front, len], [rr, len]],                   // front face
    [[rr, len], [rr, 0]],                        // the bore round the rod
  ];
}

/** Everything the viewer needs for one gun (SI config in, mm out). */
export function buildCartridge(gun) {
  const bore = gun.barrel.bore_diameter * MM;
  const toMM = (obj, keep) => Object.fromEntries(
    Object.entries(obj).map(([k, v]) => [k, keep.includes(k) || typeof v !== "number" ? v : v * MM]));
  const c = toMM(gun.case, ["shoulder_angle"]);
  const p = toMM(gun.projectile, ["boat_tail_angle", "mass", "shot_start_pressure", "bore_resistance", "ogive_radius_ratio", "core_material", "penetrator_mass", "engraving_pressure", "ballistic_coefficient"]);
  const apfsds = p.type === "apfsds";

  const kase = caseProfile(c, bore);
  const warnings = [...kase.warnings];
  // An APFSDS's rod is drawn with its own nose, with its tail sabot_offset behind the sabot's rear face.
  const rodD = apfsds ? Math.min(p.penetrator_diameter ?? 0.2 * bore, 0.9 * bore) : bore;
  const offset = apfsds ? (p.sabot_offset ?? 0) : 0;
  const proj = projectileProfile(apfsds ? { ...p, boat_tail_length: 0, jacket_thickness: 0, hollow_point_diameter: 0, cannelure_depth: 0 } : p, rodD);
  warnings.push(...proj.warnings);
  const seat = c.overall_length - p.length + offset;   // x of the projectile base (an APFSDS's sabot)
  if (seat < c.head_thickness) warnings.push("projectile base is below the top of the web (overall length too short)");
  if (seat > c.length) warnings.push("projectile is not in the case (overall length too long)");

  // Volumes in mm³. Behind an APFSDS's sabot is the case up to it, less the rod's tail.
  const capacity = radiusVolume(kase.cavity, kase.cavity[0][1], c.length);
  const intrusion = apfsds
    ? capacity - radiusVolume(kase.cavity, kase.cavity[0][1], Math.min(seat, c.length)) + Math.PI * (rodD / 2) ** 2 * offset
    : radiusVolume(proj.outline, 0, Math.max(0, c.length - seat));
  const projVolume = profileVolume(proj.body);
  const coreMaterial = Math.max(0, typeof p.core_material === "string"
    ? CORE_NAMES.indexOf(p.core_material.toLowerCase()) : Math.round(p.core_material || 0));
  // A combustible case: the metal stub base and the felt body above it.
  const stub = c.combustible ? clamp(c.stub_length ?? c.head_thickness + 0.2 * c.base_diameter, kase.dims.head + 0.1, c.length - 1) : null;
  const split = stub !== null ? splitParts(kase.parts, stub) : null;
  const parts = {
    case: split ? split.below : kase.parts, primer: primerProfile(kase.pocket),
    projectile: shiftParts(proj.parts, -offset), ...(proj.core ? { core: proj.core } : {}),
    ...(split ? { caseBody: split.above } : {}),
  };
  let sabot = null, fins = null;
  if (apfsds) {
    const R = bore / 2 - 0.05, rr = rodD / 2 + 0.05;
    const length = Math.min(p.sabot_length ?? 1.2 * bore, p.length - offset);
    sabot = { profile: sabotProfile(R, rr, length), petals: PETALS, length };
    const span = Math.min(p.fin_span ?? 3.5 * rodD, 0.95 * bore) / 2, fl = p.fin_length ?? 6 * rodD;
    fins = { x0: -offset, length: fl, root: rodD / 2 * 0.9, tip: span, thickness: Math.max(0.6, 0.06 * rodD), count: FINS };
  }
  return {
    parts,
    coreMaterial,
    // A solid projectile of steel or tungsten is drawn in that metal (a solid lead or copper one in copper).
    solidMetal: !proj.core && (coreMaterial === 1 || coreMaterial === 3) ? coreMaterial : null,
    caseMetal: gun.case.material === "steel" ? "steel" : "brass",
    combustible: stub !== null,
    sabot, fins, apfsds,
    dims: kase.dims,
    projectileLength: p.length,
    rodRadius: rodD / 2,
    seat,
    length: Math.max(c.overall_length, c.length),
    radius: Math.max(c.rim_diameter, c.base_diameter) / 2,
    stats: {
      capacity: capacity / 1e3,                          // cm³
      powderSpace: Math.max(capacity - intrusion, 0) / 1e3, // cm³
      projVolume: projVolume / 1e3,                      // cm³
      // An APFSDS's rod: its own mass over its volume.
      density: (apfsds ? (gun.projectile.penetrator_mass ?? 0.6 * gun.projectile.mass) : gun.projectile.mass) * 1e3 / (projVolume / 1e3), // g/cm³
    },
    warnings,
  };
}

/** Merge bare meshes. */
function mergeMeshes(meshes) {
  const nv = meshes.reduce((s, m) => s + m.positions.length, 0), ni = meshes.reduce((s, m) => s + m.indices.length, 0);
  const positions = new Float32Array(nv), normals = new Float32Array(nv), indices = new Uint32Array(ni);
  let vo = 0, io = 0;
  for (const m of meshes) {
    positions.set(m.positions, vo);
    normals.set(m.normals, vo);
    for (let i = 0; i < m.indices.length; i++) indices[io + i] = m.indices[i] + vo / 3;
    vo += m.positions.length;
    io += m.indices.length;
  }
  return { positions, normals, indices };
}

/** Mesh data rotated about the x axis by a. */
function turned(mesh, a) {
  const m = rotationX(a), p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      positions[i + k] = m[k] * p[i] + m[4 + k] * p[i + 1] + m[8 + k] * p[i + 2];
      normals[i + k] = m[k] * n[i] + m[4 + k] * n[i + 1] + m[8 + k] * n[i + 2];
    }
  }
  return { positions, normals, indices: mesh.indices };
}

/**
 * The round's meshes: case (the metal case, or a combustible case's stub), caseBody (the felt body),
 * primer, projectile, core, fins and sabot0.. (the sabot's petals, one each so they can fly apart).
 * The projectile's parts are at the projectile's origin (its base, or an APFSDS's sabot rear face).
 */
export function roundMeshes(cart) {
  const out = {};
  for (const [name, parts] of Object.entries(cart.parts)) out[name] = lathe(parts);
  if (cart.fins) {
    const f = cart.fins;
    const fin = prism([[f.x0, f.root], [f.x0 + f.length, f.root], [f.x0 + 0.45 * f.length, f.tip], [f.x0, f.tip]], f.thickness);
    out.fins = mergeMeshes(Array.from({ length: f.count }, (_, k) => turned(fin, (k * 2 * Math.PI) / f.count)));
  }
  if (cart.sabot) {
    const n = cart.sabot.petals;
    for (let k = 0; k < n; k++) {
      const a0 = (k * 2 * Math.PI) / n + PETAL_GAP / 2;
      out[`sabot${k}`] = lathe(cart.sabot.profile, 32, a0, a0 + (2 * Math.PI) / n - PETAL_GAP);
    }
  }
  return out;
}

/** The direction (unit [y, z]) a sabot petal flies off in: out from the middle of its sector. */
export function petalDirection(k, n = PETALS) {
  const a = ((k + 0.5) * 2 * Math.PI) / n;
  return [Math.cos(a), Math.sin(a)];
}
