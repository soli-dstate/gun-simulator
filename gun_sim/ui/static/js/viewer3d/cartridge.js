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
// projectiles.CORE_MATERIALS, in index order.
export const CORE_NAMES = ["lead", "steel", "copper", "tungsten", "hardened_steel", "tungsten_carbide", "titanium",
  "depleted_uranium", "aluminium", "brass", "sintered_copper"];
const EXPLOSIVES = new Set(["tnt", "comp_b", "comp_a4", "petn", "octol", "lx14", "pe4", "a_ix_1", "a_ix_2", "tetryl",
  "amatol", "explosive_d"]);
const SHELL_BORE = 15;      // mm: from this bore up a fuze body and a base fuze are drawn (projectiles.SHELL_BORE)
const BOOM_RADIUS = 0.17;   // a finned round's tail boom, in bores (projectiles.BOOM_RADIUS)
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
export function projectileProfile(p, bore, { gunBore = bore, coreName = "lead" } = {}) {
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
  const ctx = { p, R, len, t, ogive, baseDisc, outer, flat, outline, bore: gunBore, coreName };
  if (t === 0) return withFills({ parts: body, core: null, outline, body, warnings }, ctx);

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
  return withFills({ parts: shell, core, outline, body, warnings }, { ...ctx, ring, rAt, xBase });
}

// ---------- fills: the parts inside the projectile (projectiles.layout, drawn) ----------

const lineAt = (line, x, dflt) => (line ? line[0] + line[1] * x : dflt);

/** The pieces inside the projectile, as projectiles.layout lays them out (mm): see there. */
function fillLayout(c) {
  const { p, len: L, t, R } = c, d = 2 * R, big = c.bore >= SHELL_BORE;
  const pieces = [], explicit = [], regions = [];
  const xLo = t;
  let top = t > 0 ? L - t : L;
  if (t > 0 && p.exposed_core_length > 0) top = L;
  if (p.hollow_point_diameter > 0 && p.hollow_point_depth > 0) top = Math.min(top, L - p.hollow_point_depth);
  const explosive = EXPLOSIVES.has(p.filler);
  const capB = p.cap === "ballistic" || p.cap === "both";
  let cut = L;
  const ogive = c.ogive > 0.05 * d ? c.ogive : 0.5 * d;
  if (capB) {
    const xw = L - 0.55 * ogive;
    pieces.push({ material: "windshield", role: "windshield", x0: xw, x1: L, outside: true });
    cut = xw;
  }
  if (["impact", "delay", "time"].includes(p.fuze) && (explosive || p.liner_material || p.filler === "white_phosphorus") && big && !capB) {
    const fl = Math.min(0.8 * d, 0.7 * ogive, 0.3 * L);
    pieces.push({ material: "fuze", role: "fuze", x0: cut - fl, x1: cut, outside: true });
    cut -= fl;
  }
  if (p.tip_filler === "polymer") {
    const tl = p.tip_filler_length || Math.min(0.35 * d, 0.4 * ogive);
    pieces.push({ material: "polymer", role: "tip", x0: cut - tl, x1: cut, outside: true });
    cut -= tl;
  }
  if (p.cap === "penetrating" || p.cap === "both") {
    pieces.push({ material: "cap", role: "cap", x0: cut - 0.5 * d, x1: cut, outside: true });
    cut -= 0.5 * d;
  }
  top = Math.max(Math.min(top, cut), xLo + 1e-3);
  const wall = (x) => (t > 0 ? c.rIn(x) : c.rOut(x));
  let lo = xLo;
  const hi = top;
  if (p.fuze === "base" && big && (explosive || p.filler === "white_phosphorus")) {
    const bl = Math.min(0.35 * d, 0.25 * (hi - lo));
    regions.push(["fuze", "fuze", lo, lo + bl]);
    lo += bl;
  }
  let tracer = null;
  if (p.tracer) {
    const trl = Math.min(p.tracer_length || 1.5 * d, 0.6 * (top - xLo));
    const rt = 0.55 * Math.max(wall(xLo + 1e-3), 1e-3);
    tracer = { r: rt, x1: xLo + trl };
    explicit.push({ material: `tracer:${p.tracer}`, role: "tracer", x0: xLo, x1: xLo + trl, lo: null, hi: [rt, 0] });
  }
  if (p.liner_material) {
    const span = hi - lo;
    let xl = Math.min(lo + (p.filler_length || 0.5 * span), hi - 0.05 * d);
    xl = Math.max(xl, lo + 0.1 * span);
    const rl = 0.97 * wall(xl);
    const half = clamp(p.liner_angle ?? 30, 10, 70) * DEG;
    const h = Math.min(rl / Math.tan(half), 0.85 * (xl - lo));
    const slope = rl / Math.max(h, 1e-9), xa = xl - h;
    const th = (p.liner_thickness || 0.025 * 2 * rl) / Math.max(Math.cos(Math.atan(slope)), 0.2);
    const cone = [-slope * xa, slope];
    explicit.push({ material: "air", role: "air", x0: xa, x1: xl, lo: null, hi: cone });
    explicit.push({ material: `liner:${p.liner_material}`, role: "liner", x0: xa, x1: xl, lo: cone, hi: [cone[0] + th, slope] });
    explicit.push({ material: "air", role: "air", x0: xl, x1: hi, lo: null, hi: null });
    regions.push([p.filler || "comp_b", "fill", lo, xl]);
  } else {
    let cur = hi;
    if (p.tip_filler && p.tip_filler !== "polymer") {
      const tl = Math.min(p.tip_filler_length || 0.6 * d, cur - lo);
      regions.push([p.tip_filler, "tip", cur - tl, cur]);
      cur -= tl;
    }
    if (p.filler) {
      let x0, x1;
      if (p.filler_position > 0) {
        x0 = Math.min(lo + p.filler_position, cur);
        x1 = Math.min(x0 + (p.filler_length || cur - x0), cur);
      } else if (p.filler_length > 0) {
        x1 = cur; x0 = Math.max(cur - p.filler_length, lo); cur = x0;
      } else {
        x0 = lo; x1 = cur;
      }
      regions.push([p.filler, "fill", x0, x1]);
      if (!p.filler_length && !p.filler_position) cur = lo;
    }
    if (p.insert_material) {
      const roomy = cur - lo > 0.2 * d;
      const room = roomy ? cur - lo : hi - lo;
      const il = Math.min(p.insert_length || 0.6 * room, hi - lo);
      const x0 = p.insert_position > 0 ? Math.min(lo + p.insert_position, hi - il) : Math.max((roomy ? cur : hi) - il, lo);
      const x1 = x0 + il;
      const w = wall(x0);
      const ri = Math.min(p.insert_diameter ? p.insert_diameter / 2 : 0.72 * w, 0.95 * w);
      const nose = Math.min(2.4 * ri, 0.45 * il);
      const slope = (-0.95 * ri) / nose;
      explicit.push({ material: p.insert_material, role: "insert", x0, x1: x1 - nose, lo: null, hi: [ri, 0] });
      explicit.push({ material: p.insert_material, role: "insert", x0: x1 - nose, x1, lo: null, hi: [ri - slope * (x1 - nose), slope] });
    }
  }
  pieces.push(...partition(explicit, regions, xLo, top, c.coreName));
  return { pieces, cut, hollow: !!p.liner_material, tracer };
}

/** projectiles._partition: the explicit pieces, and the rest of the cavity in its region's fill or the core. */
function partition(explicit, regions, xLo, xHi, core) {
  const xs = new Set([xLo, xHi]);
  for (const e of explicit) { xs.add(e.x0); xs.add(e.x1); }
  for (const [, , a, b] of regions) { xs.add(a); xs.add(b); }
  const sorted = [...xs].filter((x) => x >= xLo - 1e-9 && x <= xHi + 1e-9).sort((a, b) => a - b);
  const out = [...explicit];
  for (let i = 0; i + 1 < sorted.length; i++) {
    const xa = sorted[i], xb = sorted[i + 1];
    if (xb - xa < 1e-6) continue;
    const xm = (xa + xb) / 2;
    const reg = regions.find(([, , a, b]) => a - 1e-9 <= xm && xm <= b + 1e-9);
    const [material, role] = reg ? [reg[0], reg[1]] : [core, "core"];
    const active = explicit.filter((e) => e.x0 - 1e-9 <= xm && xm <= e.x1 + 1e-9)
      .sort((a, b) => lineAt(a.lo, xm, 0) - lineAt(b.lo, xm, 0));
    let lo = null, wall = false;
    for (const e of active) {
      if (lineAt(e.lo, xm, 0) > lineAt(lo, xm, 0) + 1e-6) out.push({ material, role, x0: xa, x1: xb, lo, hi: e.lo });
      if (!e.hi) { wall = true; break; }
      if (!lo || lineAt(e.hi, xm, 0) > lineAt(lo, xm, 0)) lo = e.hi;
    }
    if (!wall) out.push({ material, role, x0: xa, x1: xb, lo, hi: null });
  }
  return out;
}

/** Sutherland-Hodgman: the part of a closed [r, x] polygon where f([r, x]) >= 0 (f linear). */
function clipHalf(poly, f) {
  const out = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const fa = f(a), fb = f(b);
    if (fa >= 0) out.push(a);
    if ((fa >= 0) !== (fb >= 0)) {
      const s = fa / (fa - fb);
      out.push([a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s]);
    }
  }
  return out;
}

/** A closed polygon as lathe parts: split at its corners so they shade with hard edges. */
function polygonParts(poly) {
  const pts = poly.filter((q, i) => i === 0 || Math.hypot(q[0] - poly[i - 1][0], q[1] - poly[i - 1][1]) > 1e-6);
  if (pts.length > 1 && Math.hypot(pts[0][0] - pts.at(-1)[0], pts[0][1] - pts.at(-1)[1]) <= 1e-6) pts.pop();
  const n = pts.length;
  if (n < 3) return [];
  const corner = (i) => {
    const a = pts[(i - 1 + n) % n], b = pts[i], c = pts[(i + 1) % n];
    const u = [b[0] - a[0], b[1] - a[1]], v = [c[0] - b[0], c[1] - b[1]];
    return (u[0] * v[0] + u[1] * v[1]) / ((Math.hypot(...u) * Math.hypot(...v)) || 1) < Math.cos(25 * DEG);
  };
  let s = pts.findIndex((_, i) => corner(i));
  if (s < 0) s = 0;
  const parts = [];
  let cur = [pts[s]];
  for (let k = 1; k <= n; k++) {
    const i = (s + k) % n;
    cur.push(pts[i]);
    if (corner(i) || k === n) { parts.push(cur); cur = [pts[i]]; }
  }
  return parts;
}

/** Profile parts up to x = cut, closed by a flat face across to the axis there. */
function cutParts(parts, cut) {
  const kept = clipParts(parts, cut);
  const last = kept.at(-1), end = last.at(-1);
  if (end[0] > 1e-6) kept.push([end, [0, end[1]]]);
  return kept;
}

/**
 * The projectile's fills drawn into its profile: `fills` is [{material, role, parts}] for each piece, and the
 * envelope is cut short under any piece that sits on its outside (a fuze, a polymer tip, caps). A shaped charge's
 * body is drawn as a real shell, hollow in front of its liner.
 */
function withFills(res, c) {
  const p = c.p;
  const has = p.insert_material || p.filler || p.tip_filler || p.tracer || p.liner_material || (p.cap && p.cap !== "none")
    || (p.fuze && p.fuze !== "none");
  if (!has) return { ...res, fills: [], tracer: null };
  const rOut = (x) => radiusAt(res.outline, x);
  const rIn = c.ring ? (x) => c.rAt(x) : rOut;
  const lay = fillLayout({ ...c, rOut, rIn, bore: c.bore ?? 2 * c.R, coreName: c.coreName ?? "lead" });
  const meaningful = lay.pieces.some((pc) => pc.role !== "core");
  if (!meaningful) return { ...res, fills: [], tracer: null };
  const L = c.len, eps = 0.02;
  let parts = res.parts;
  if (lay.hollow && c.ring) {
    // The body as a real shell: the outside up to the cut, then the inside of the jacket back down.
    const down = c.ring.filter(([, x]) => x < lay.cut && x > c.xBase).reverse();
    parts = [c.baseDisc, ...clipParts(c.outer, lay.cut), [[rOut(lay.cut), lay.cut], [rIn(lay.cut), lay.cut]],
      [[rIn(lay.cut), lay.cut], ...down, [rIn(c.xBase), c.xBase]], [[rIn(c.xBase), c.xBase], [0, c.xBase]]];
  } else if (lay.cut < L - 1e-6) {
    parts = cutParts(parts, lay.cut);
  }
  // The polygons the pieces are cut from: the cavity inside the jacket (or just inside a solid), the outside.
  const cavity = res.core ? res.core.flat() : [[0, eps], ...res.outline.slice(1).map(([r, x]) => [Math.max(r - eps, 0), clamp(x, eps, L - eps)]), [0, L - eps]];
  const outside = c.flat.map(([r, x]) => [r > 0 ? r + 0.01 : 0, x]);
  let windshield = null;
  const ws = lay.pieces.find((pc) => pc.role === "windshield");
  if (ws) {
    const tw = Math.max(0.04 * 2 * c.R, 0.1);
    const top = [[rOut(ws.x0) + 0.01, ws.x0], ...res.outline.filter(([, x]) => x > ws.x0).map(([r, x]) => [r + 0.01, x])];
    const inner = insetPolyline(top, tw).filter(([, x]) => x >= ws.x0 && x <= L - tw);
    windshield = [...top, [0, L], [0, L - tw], ...inner.reverse(), [Math.max(rOut(ws.x0) - tw, 0), ws.x0]];
  }
  const fills = [];
  for (const pc of lay.pieces) {
    if (pc.role === "air" || (pc.role === "core" && !res.core)) continue;
    let poly;
    if (pc.role === "tracer") {
      poly = [[0, -eps], [pc.hi[0], -eps], [pc.hi[0], pc.x1], [0, pc.x1]];   // open at the base, where the gas lights it
    } else {
      poly = pc.outside ? (pc.role === "windshield" ? windshield : outside) : cavity;
      poly = clipHalf(poly, ([, x]) => x - pc.x0);
      poly = clipHalf(poly, ([, x]) => pc.x1 - x);
      if (pc.lo) poly = clipHalf(poly, ([r, x]) => r - lineAt(pc.lo, x, 0));
      if (pc.hi) poly = clipHalf(poly, ([r, x]) => lineAt(pc.hi, x, 0) - r);
    }
    const pp = polygonParts(poly);
    if (pp.length) fills.push({ material: pc.material, role: pc.role, parts: pp });
  }
  return { ...res, parts, core: null, fills, tracer: lay.tracer };
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
  const p = toMM(gun.projectile, ["boat_tail_angle", "mass", "shot_start_pressure", "bore_resistance", "ogive_radius_ratio",
    "core_material", "penetrator_mass", "engraving_pressure", "ballistic_coefficient", "liner_angle", "fuze_delay", "fuze_time",
    "arming_distance"]);
  const apfsds = p.type === "apfsds", subCalibre = apfsds || p.type === "apds", finned = p.type === "finned";

  const kase = caseProfile(c, bore);
  const warnings = [...kase.warnings];
  // A sabot round's rod is drawn with its own nose, with its tail sabot_offset behind the sabot's rear face; a finned
  // round's body sits on its tail boom, which reaches back boom_length behind where the gas pushes.
  const rodD = subCalibre ? Math.min(p.penetrator_diameter ?? (apfsds ? 0.2 : 0.45) * bore, 0.9 * bore) : bore;
  const boom = finned ? Math.min(p.boom_length || 0, 0.8 * p.length) : 0;
  const offset = subCalibre ? (p.sabot_offset ?? 0) : boom;
  const coreMaterial = Math.max(0, typeof p.core_material === "string"
    ? CORE_NAMES.indexOf(p.core_material.toLowerCase()) : Math.round(p.core_material || 0));
  const shape = subCalibre ? { ...p, boat_tail_length: 0, jacket_thickness: 0, hollow_point_diameter: 0, cannelure_depth: 0 }
    : finned ? { ...p, length: p.length - boom } : p;
  const proj = projectileProfile(shape, rodD, { gunBore: bore, coreName: CORE_NAMES[coreMaterial] });
  warnings.push(...proj.warnings);
  const seat = c.overall_length - p.length + offset;   // x of where the gas pushes: the base, a sabot's rear, a finned body's rear
  if (seat < c.head_thickness) warnings.push("projectile base is below the top of the web (overall length too short)");
  if (seat > c.length) warnings.push("projectile is not in the case (overall length too long)");

  // Volumes in mm³. Behind a sabot (or a finned body) is the case up to it, less the rod's tail (or the boom).
  const capacity = radiusVolume(kase.cavity, kase.cavity[0][1], c.length);
  const tailR = subCalibre ? rodD / 2 : BOOM_RADIUS * bore;
  const intrusion = subCalibre || finned
    ? capacity - radiusVolume(kase.cavity, kase.cavity[0][1], Math.min(seat, c.length)) + Math.PI * tailR ** 2 * offset
      + (finned ? radiusVolume(proj.outline, 0, Math.max(0, c.length - seat)) : 0)
    : radiusVolume(proj.outline, 0, Math.max(0, c.length - seat));
  const projVolume = profileVolume(proj.body);
  // A combustible case: the metal stub base and the felt body above it.
  const stub = c.combustible ? clamp(c.stub_length ?? c.head_thickness + 0.2 * c.base_diameter, kase.dims.head + 0.1, c.length - 1) : null;
  const split = stub !== null ? splitParts(kase.parts, stub) : null;
  const shiftBy = subCalibre ? -offset : 0;
  const parts = {
    case: split ? split.below : kase.parts, primer: primerProfile(kase.pocket),
    projectile: shiftParts(proj.parts, shiftBy), ...(proj.core ? { core: shiftParts(proj.core, shiftBy) } : {}),
    ...(split ? { caseBody: split.above } : {}),
  };
  proj.fills.forEach((f, k) => { parts[`fill${k}`] = shiftParts(f.parts, shiftBy); });
  let sabot = null, fins = null;
  if (subCalibre) {
    const R = bore / 2 - 0.05, rr = rodD / 2 + 0.05;
    const length = Math.min(p.sabot_length ?? (apfsds ? 1.2 * bore : 0.85 * p.length), p.length - offset);
    sabot = { profile: sabotProfile(R, rr, length), petals: PETALS, length };
  }
  if (apfsds) {
    const span = Math.min(p.fin_span ?? 3.5 * rodD, 0.95 * bore) / 2, fl = p.fin_length ?? 6 * rodD;
    fins = { x0: -offset, length: fl, root: rodD / 2 * 0.9, tip: span, thickness: Math.max(0.6, 0.06 * rodD), count: FINS };
  } else if (finned) {
    const rb = BOOM_RADIUS * bore, span = Math.min(p.fin_span ?? 0.95 * bore, 0.98 * bore) / 2;
    const fl = Math.min(p.fin_length ?? 0.6 * bore, boom);
    fins = { x0: -boom, length: fl, root: rb * 0.9, tip: span, thickness: Math.max(0.6, 0.03 * bore), count: FINS,
             boom: { x0: -boom, x1: 0, r: rb } };
  }
  // What each part is drawn in: the jacket's metal over a core, or a solid projectile's own metal.
  const jacketed = (shape.jacket_thickness ?? 0) > 0;
  return {
    parts,
    coreMaterial,
    solidMetal: jacketed ? null : coreMaterial,
    jacketMaterial: jacketed ? (p.jacket_material || "gilding_metal") : null,
    fills: proj.fills.map((f, k) => ({ mesh: `fill${k}`, material: f.material, role: f.role })),
    tracer: proj.tracer && p.tracer ? { colour: p.tracer, r: proj.tracer.r, x: shiftBy } : null,
    sabotMaterial: p.sabot_material || "aluminium",
    caseMetal: gun.case.material === "steel" ? "steel" : "brass",
    combustible: stub !== null,
    sabot, fins, apfsds, subCalibre, finned,
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
      // A sabot round's rod: its own mass over its volume.
      density: (subCalibre ? (gun.projectile.penetrator_mass ?? 0.6 * gun.projectile.mass) : gun.projectile.mass) * 1e3 / (projVolume / 1e3), // g/cm³
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
 * primer, projectile, core, fill0.. (what is inside it), fins (with a finned round's boom), sabot0.. (the
 * sabot's petals, one each so they can fly apart) and tracerGlow (a tracer's flame behind the base).
 * The projectile's parts are at the projectile's origin (its base, or a sabot's rear face).
 */
export function roundMeshes(cart) {
  const out = {};
  for (const [name, parts] of Object.entries(cart.parts)) out[name] = lathe(parts);
  if (cart.fins) {
    const f = cart.fins;
    const fin = prism([[f.x0, f.root], [f.x0 + f.length, f.root], [f.x0 + 0.45 * f.length, f.tip], [f.x0, f.tip]], f.thickness);
    const meshes = Array.from({ length: f.count }, (_, k) => turned(fin, (k * 2 * Math.PI) / f.count));
    if (f.boom) {
      const { x0, x1, r } = f.boom;
      meshes.push(lathe([[[0, x0], [r, x0]], [[r, x0], [r, x1]], [[r, x1], [0, x1]]], 32));
    }
    out.fins = mergeMeshes(meshes);
  }
  if (cart.tracer) {
    // The flame: a teardrop trailing back from the base, as wide as the tracer's cavity at the base.
    const r = cart.tracer.r * 1.3, L = Math.max(14 * cart.tracer.r, 6);
    const x = cart.fins ? Math.min(cart.fins.x0, cart.tracer.x) : cart.tracer.x;   // behind the fins, if any
    out.tracerGlow = lathe([[[0, x - L], [0.35 * r, x - 0.75 * L], [0.8 * r, x - 0.35 * L], [r, x - 0.08 * L], [0.6 * r, x + 0.02], [0, x + 0.04]]], 24);
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

/** What the firing range needs to draw the round (the layout's `round`). */
export function roundLayout(cart) {
  return {
    apfsds: cart.apfsds, subCalibre: cart.subCalibre, petals: cart.sabot?.petals ?? 0, solidMetal: cart.solidMetal,
    jacketMaterial: cart.jacketMaterial, fills: cart.fills, tracer: cart.tracer, sabotMaterial: cart.sabotMaterial,
    caseMetal: cart.caseMetal, combustible: cart.combustible, rodRadius: cart.rodRadius, sabotLength: cart.sabot?.length ?? 0,
  };
}

/** The direction (unit [y, z]) a sabot petal flies off in: out from the middle of its sector. */
export function petalDirection(k, n = PETALS) {
  const a = ((k + 0.5) * 2 * Math.PI) / n;
  return [Math.cos(a), Math.sin(a)];
}
