// Tank gun autoloaders in 3D, as gun_sim/autoloader.py has them: where each mechanism's
// parts are, and where they are at a time in its cycle. Millimetres, in the gun's frame
// (gun.js): x along the bore from the case head, y up, z to the right. The mechanism is
// fixed in the turret, so range.js draws it in the turret's frame (the gun at its loading
// angle, or pitching with the cradle for an oscillating turret); the rounds it rams go
// on into the gun's.
//
// * az (T-72, T-90): a carousel under the gun, a cassette round it for every round, the
//   projectile lying flat in the cassette's upper lane and the charge in the lane under it,
//   noses to the middle. The cassette under the breech is raised behind it by the lift
//   (two posts and a carriage), then raised on one more lane to bring the charge into line.
// * mz (T-64, T-80): a bigger carousel, the charges standing upright round its outside and
//   the projectiles lying flat inside them. The raised cassette's tray swings its charge
//   down into line behind the projectile.
// * bustle (Leclerc, Type 90): a conveyor in the turret bustle, an oval of cells (two rows,
//   joined by round sprockets) each holding a round nose-forwards. The front cell's round
//   drops onto the ramming tray in line with the bore, in front of the bustle, where a blast
//   door slides up to let the rammer push it through.
// * oscillating (AMX-13): two revolver drums side by side over the loading tray, rounds
//   nose-forwards, and a spring rammer behind it; the case goes out through a rear trapdoor.
//
// A rammer (a chain, or a spring) pushes each piece along from where it lies lined up behind
// the breech. That is a longer way than the simulation's stroke (the reach of its drive), so
// the head's travel on the screen is scaled to seat each piece when the simulation says it does.

import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { boxAt, merge } from "./meshops.js";
import { box, rodProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
const TAU = 2 * Math.PI;
export const AUTOLOADERS = ["az", "mz", "bustle", "oscillating"];
// As gun_sim/autoloader.py: rims between positions, up to the rammer's line, between an AZ cassette's tiers, an
// oscillating turret's round's fall; the rammer's head starts this far behind its piece (m).
const PITCH = 1.2, LIFT = 4.5, TIER = 1.2, DROP = 1.1, RAM_GAP = 0.1;
const DEFAULTS = { az: { n: 22, two: true, load: 3 }, mz: { n: 28, two: true, load: 3 },
                   bustle: { n: 22, two: false, load: 0 }, oscillating: { n: 12, two: false, load: null } };
export const LABELS = { az: "carousel", mz: "carousel", bustle: "bustle conveyor", oscillating: "drums" };
const SEAT_EVENT = { projectile: "the projectile seats in the forcing cone", round: "the round seats in the forcing cone",
                     charge: "the charge is rammed home" };
const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const wrap = (v, n) => ((v % n) + n) % n;

/** Linear interpolation in a sampled curve (xs ascending). */
function lerp(xs, ys, x) {
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

/** A tube (ri > 0) or rod turned about a vertical axis through (cx, cz), from y0 to y1. */
const vertical = (ri, ro, y0, y1, cx = 0, cz = 0, seg = 64) =>
  [lathe(ri > 0 ? tubeProfile(ri, ro, y0, y1) : rodProfile(ro, y0, y1), seg), chain(translation(cx, 0, cz), rotationZ(Math.PI / 2))];
/** A tube or rod along x from x0 to x1 at (y, z). */
const along = (ri, ro, x0, x1, y = 0, z = 0, seg = 32) =>
  [lathe(ri > 0 ? tubeProfile(ri, ro, x0, x1) : rodProfile(ro, x0, x1), seg), translation(0, y, z)];
/** A pin along z through (x, y). */
const pinZ = (r, half, x, y) => [lathe(rodProfile(r, -half, half), 24), chain(translation(x, y, 0), rotationY(Math.PI / 2))];

/**
 * The autoloader for a gun: its meshes and layout. ctx: {d (the cartridge's dims), oal, cart, wedge (gun.js's
 * wedgeLayout, or null), mountStroke}.
 */
export function buildAutoloader(gun, ctx) {
  const { d, oal, cart } = ctx;
  const f = gun.feed ?? {}, type = f.type, df = DEFAULTS[type];
  const D = gun.case.rim_diameter * MM, rimR = D / 2, Dc = 2 * Math.max(d.baseR, d.shR);
  const n = Math.max(2, Math.round(f.capacity ?? df.n));
  const twoPiece = f.ammunition == null ? df.two : f.ammunition === "two_piece";
  const loadAngle = df.load === null ? null : (f.load_angle ?? df.load);
  const gunElev = f.gun_elevation ?? 0;
  const W = ctx.wedge ?? { ringRear: -Math.max(1.8 * rimR, 20) - 0.3 * rimR, ringHalf: 2.2 * rimR };
  const pl = cart.projectileLength, cl = d.length, seat = cart.seat;
  // A sabot round's rod (a finned round's boom) reaches behind its origin, so less of it is ahead of that.
  const ahead = pl - (cart.subCalibre || cart.finned ? Math.max(-(cart.fins?.x0 ?? 0), pl - (oal - seat)) : 0);
  const stroke = ctx.mountStroke ?? 0;
  const P = PITCH * D, lift = LIFT * D, tier = TIER * D, drop = DROP * D;
  const bore = gun.barrel.bore_diameter * MM;
  const A = { type, label: LABELS[type], n, twoPiece, loadAngle, gunElev, D, rimR, Dc, P, lift, tier, drop, oal, pl, cl, seat, ahead };
  // Rounds behind the breech: a carousel's lift stops just behind the ring; the others load across the gun's
  // recoil path, which the breech goes back along.
  const carousel = type === "az" || type === "mz";
  const xLine = W.ringRear - (carousel ? 10 : stroke + 0.6 * rimR);
  A.xLine = xLine;
  // What is rammed, in order: where its base (a case's head) lies lined up, and where it seats. A projectile and a
  // charge share one lane (the charge behind) unless the lifts hold them in two.
  const lanes = type === "az" ? 2 : 1;
  A.pieces = (twoPiece ? [{ name: "projectile", len: pl, xEnd: seat }, { name: "charge", len: cl, xEnd: 0 }]
    : [{ name: "round", len: oal, xEnd: 0 }]).map((p, i) => {
    const base0 = i && lanes === 1 ? xLine - pl - 20 - cl : xLine - (p.name === "projectile" ? ahead : p.len);
    return { ...p, base0, delta: p.xEnd - base0, ram: p.len / MM + RAM_GAP };
  });
  const xHome = Math.min(...A.pieces.map((p) => p.base0)) - RAM_GAP * MM;
  A.xHome = xHome;
  for (const p of A.pieces) p.k = (p.xEnd - xHome) / (p.ram * MM);       // head travel on screen per m of the simulation's
  const parts = {};
  const add = (name, ...entries) => { (parts[name] ??= []).push(...entries); };

  // ---- the rammer: its head and chain, and the housing the chain stows in behind it ----
  const rh = 0.5 * rimR, rr = 0.2 * rimR;
  parts.alRammer = [lathe(rodProfile(rh, -26, 0, 2), 32), lathe(rodProfile(rr, -280, -26), 24)];
  add("alFrame", along(rr + 3, 0.64 * rimR, xHome - 330, xHome + 30), along(rr + 3, 0.8 * rimR, xHome - 40, xHome + 30),
      along(rr + 3, 0.8 * rimR, xHome - 330, xHome - 290));

  if (carousel) buildCarousel(A, { add, W, bore, stroke, rimR, xLine });
  else if (type === "bustle") buildBustle(A, { add, W, bore, rimR, xLine });
  else buildDrums(A, { add, W, bore, rimR, xLine });

  const meshes = {};
  for (const [name, list] of Object.entries(parts)) meshes[name] = merge(...list);
  return { meshes, layout: A };
}

/** The carousel's cassettes and ring, the lift's frame and carriage, and an MZ's tray (az and mz). */
function buildCarousel(A, { add, W, bore, stroke, rimR, xLine }) {
  const { n, D, Dc, P, lift, tier, pl, cl, type } = A;
  const mz = type === "mz";
  const zcas = 0.5 * Math.max(D, Dc) + 14;
  // The cassette's frame: its origin the projectile lane's middle, x towards the carousel's middle (noses first).
  const Lh = mz ? pl / 2 : Math.max(pl, cl) / 2;
  const laneC = mz ? 0 : -tier;                                    // an AZ's charge lane is under the projectile's
  const reach = Math.max(n * P / TAU, 2 * D);                      // the simulation's pitch radius
  let xch = 0, yb = 0, hx = 0, hy = 0, xt = 0;
  let outer = -Lh - 10, shelfY = -0.5 * Dc - 5, floorY;
  if (mz) {
    // The charge stands behind the projectile's base, on its head; its tray swings it down into line about a
    // pivot behind it: head at (xt, 0) lying along the bore when it is done.
    xch = -Lh - 14 - Dc / 2;
    xt = -Lh - 20 - cl;
    hx = xch - Dc / 2 - 6;
    hy = Dc / 2 + 6;
    yb = xt - hx + hy;
    outer = hx - 18;
    floorY = yb - 6;
  } else {
    floorY = laneC - 0.5 * Dc - 5;
  }
  // Far enough out that neighbouring rounds clear each other where they are closest: a charge at its nose, an MZ's
  // projectile where its bearing part is (a fifth of its length from the nose).
  const need = mz ? n * 1.1 * bore / TAU + 0.2 * pl : n * 1.12 * Dc / TAU + Lh;
  const Rcp = Math.max(reach, need);
  const xc = xLine + Rcp - Lh;                                     // the carousel's centre
  const yRest = -lift;                                             // the projectile lane's height with the cassette down
  const top = 0.5 * Dc + 10;
  // The cassette: shelves under its lanes, side walls, a bar across its front.
  const cass = [boxAt(2 * Lh + 20, 6, 2 * zcas, 0, shelfY - 3, 0), boxAt(8, 24, 2 * zcas, Lh + 12, floorY + 12, 0)];
  if (!mz) cass.push(boxAt(2 * Lh + 20, 6, 2 * zcas, 0, floorY - 3, 0));
  // Low side walls (up to the lower lane's top, or an MZ's projectile's axis), so the rounds in them show.
  const wallTop = mz ? 0 : laneC + 0.5 * Dc + 10, wallH = wallTop - (floorY - 6);
  cass.push(boxAt(Lh + 10 - outer, wallH, 4, (Lh + 10 + outer) / 2, (wallTop + floorY - 6) / 2, zcas),
            boxAt(Lh + 10 - outer, wallH, 4, (Lh + 10 + outer) / 2, (wallTop + floorY - 6) / 2, -zcas));
  if (mz) {
    cass.push(boxAt(Dc + 30, 5, 2 * zcas, xch, yb - 3, 0), pinZ(7, zcas + 6, hx, hy),
              boxAt(8, hy - yb + 12, 6, hx, (hy + yb) / 2, zcas), boxAt(8, hy - yb + 12, 6, hx, (hy + yb) / 2, -zcas));
    add("alTray", boxAt(cl, 8, 0.8 * Dc, cl / 2, -(Dc / 2 + 6), 0), boxAt(8, Dc + 16, 0.9 * Dc, -6, 0, 0));
  }
  add("alCassette", ...cass);
  // The ring the cassettes ride on (its y from the lane's height): a floor, rim, hub, and a divider between cassettes.
  const r1 = Rcp - Lh - 40, r2 = Rcp - outer + 30;
  const fy = floorY - 12;
  add("alRing", vertical(r1, r2, fy - 12, fy, 0, 0, 96), vertical(r2 - 5, r2, fy, fy + 70, 0, 0, 96),
      vertical(0, 0.12 * r1, fy, fy + 0.5 * Dc + 20, 0, 0, 32), vertical(r1 - 4, r1, fy, fy + 50, 0, 0, 96));
  const divLen = Lh + 10 - outer, divAt = Rcp - (Lh + 10 + outer) / 2;
  for (let k = 0; k < n; k++) {
    add("alRing", [box(divLen, 36, 4), chain(rotationY(TAU * (k + 0.5) / n), translation(-divAt, fy + 18, 0))]);
  }
  // The lift: two posts beside the rear cassette, a beam across their tops, and the carriage on them that
  // holds the cassette (arms to its sides).
  const xPost = Math.min(xLine - 1.5 * Lh, W.ringRear - stroke - rimR), zpost = zcas + 26;
  const postTop = top + tier + 70;
  for (const s of [1, -1]) add("alFrame", [lathe(rodProfile(12, yRest + fy - 30, postTop), 20), chain(translation(xPost, 0, s * zpost), rotationZ(Math.PI / 2))]);
  add("alFrame", boxAt(36, 20, 2 * zpost + 40, xPost, postTop + 10, 0));
  const carryH = top - floorY + 20, carryY = yRest + (top + floorY) / 2;
  for (const s of [1, -1]) {
    add("alCarriage", boxAt(48, carryH, 40, xPost, carryY, s * zpost), boxAt(30, 26, zpost - zcas, xPost, yRest + floorY + 40, s * (zcas + zpost) / 2));
  }
  Object.assign(A, { Lh, laneC, zcas, Rcp, xc, yRest, xch, yb, hx, hy, xt, xPost, outer, floorY, top, ringY: fy });
  A.bounds = { x0: A.xHome - 340, x1: W.ringRear + 520, y0: yRest + floorY - 60, y1: top + tier + 120 };
}

/** The bustle's frame, conveyor cells and sprockets, ramming tray and blast door. */
function buildBustle(A, { add, W, rimR, xLine }) {
  const { n, D, Dc, P, drop, oal } = A;
  const re = 0.65 * D, rowGap = 2 * re;
  const S = Math.max((n * P - TAU * re) / 2, 2 * P);                     // a row's straight length
  const yb = drop, yt = drop + rowGap, ym = drop + re;
  const x0 = xLine - oal;                                                 // a round's base on the tray
  const halfW = S / 2 + re + 90, xFront = xLine + 36, xBack = x0 - 70;
  const yBot = -0.8 * D, yTop = yt + 0.75 * D;
  // The shell: floor, a front wall with the door's opening, posts and rails, low sills along the sides.
  const hole = 1.3 * D, holeW = 1.5 * D;
  const side = halfW - holeW / 2;
  add("alFrame",
    boxAt(xFront - xBack, 10, 2 * halfW, (xFront + xBack) / 2, yBot, 0),
    boxAt(14, yTop - hole / 2, 2 * halfW, xFront, (yTop + hole / 2) / 2, 0),             // the front wall, round the hole
    boxAt(14, -hole / 2 - yBot, 2 * halfW, xFront, (yBot - hole / 2) / 2, 0),
    boxAt(14, hole, side, xFront, 0, (halfW + holeW / 2) / 2), boxAt(14, hole, side, xFront, 0, -(halfW + holeW / 2) / 2));
  for (const s of [1, -1]) {
    for (const x of [xFront, xBack]) add("alFrame", boxAt(16, yTop - yBot, 16, x, (yTop + yBot) / 2, s * halfW));
    add("alFrame", boxAt(xFront - xBack, 14, 14, (xFront + xBack) / 2, yTop, s * halfW),
        boxAt(xFront - xBack, 60, 6, (xFront + xBack) / 2, yBot + 35, s * halfW));
  }
  add("alFrame", boxAt(14, 14, 2 * halfW, xBack, yTop, 0), boxAt(14, 14, 2 * halfW, xFront, yTop, 0),
      boxAt(xFront - xBack, 14, 14, (xFront + xBack) / 2, yTop, 0));
  // Chain rails along both rows, at the two saddles' stations.
  const stations = [x0 + 0.2 * oal, x0 + 0.8 * oal];
  for (const x of stations) {
    for (const y of [yb, yt]) add("alFrame", boxAt(24, 6, S, x, y - 0.5 * Dc - 16, 0));
  }
  // A cell: two saddles under the round (origin on its axis at its base). A sprocket: a disc with a bar across
  // it, so its turning shows.
  for (const x of stations) add("alCell", boxAt(44, 12, P - 8, x - x0, -0.5 * Dc - 8, 0));
  add("alSprocket", lathe(rodProfile(re, -5, 5, 2), 32), boxAt(10, 2 * re - 8, 16, 0, 0, 0));
  // The ramming tray (origin: the round's base on the axis) and the blast door.
  add("alRamTray", boxAt(oal, 8, 0.8 * Dc, oal / 2, -0.5 * Dc - 6, 0), boxAt(oal, 0.3 * Dc, 6, oal / 2, -0.28 * Dc, 0.4 * Dc + 3),
      boxAt(oal, 0.3 * Dc, 6, oal / 2, -0.28 * Dc, -(0.4 * Dc + 3)));
  const doorH = 1.45 * D;
  add("alDoor", boxAt(10, doorH, holeW + 40, 0, 0, 0));
  Object.assign(A, { re, S, yb, yt, ym, x0, halfW, xFront, xBack, yBot, yTop, stations, doorX: xFront - 12, holeW, hole });
  A.bounds = { x0: A.xHome - 340, x1: W.ringRear + 520, y0: yBot - 40, y1: yTop + 60 };
}

/** The oscillating turret's two drums, loading tray, spring rammer's wall, and the trapdoor. */
function buildDrums(A, { add, W, rimR, xLine }) {
  const { n, D, Dc, P, drop, oal } = A;
  const per = Math.ceil(n / 2);
  const Rd = Math.max(per * P / TAU, 0.8 * D);
  const x0 = xLine - oal, yd = Rd + drop, zd = Rd + 0.6 * D + 6;
  const rn = 0.5 * Dc;
  // A drum, centred on its axis: a rear plate and a bar across it, two rings round the rounds and a hub.
  const ring = (x) => along(Rd + rn + 2, Rd + rn + 10, x - 5, x + 5, 0, 0, 48);
  add("alDrum", [lathe(rodProfile(Rd + rn + 10, x0 - 14, x0 - 4, 2), 48), translation(0, 0, 0)],
      boxAt(10, 2 * Rd - 20, 24, x0 - 9, 0, 0), ring(x0 + 0.5 * oal), ring(xLine - 40),
      along(0, Math.max(Rd - rn - 6, 0.2 * Rd), x0 - 14, xLine - 30, 0, 0, 24));
  // The tray the round drops onto, and the turret's rear wall with the trapdoor below the rammer.
  add("alTray", boxAt(oal, 6, 0.8 * Dc, oal / 2, -rn - 6, 0), boxAt(oal, 0.3 * Dc, 5, oal / 2, -0.28 * Dc, 0.4 * Dc + 2),
      boxAt(oal, 0.3 * Dc, 5, oal / 2, -0.28 * Dc, -(0.4 * Dc + 2)));
  const xBack = x0 - 40, yTop = yd + Rd + rn + 40, yBot = -1.7 * Dc, halfW = zd + Rd + rn + 40;
  const flapTop = -0.3 * Dc, flapH = 1.2 * Dc;
  // A frame round the drums.
  for (const s of [1, -1]) {
    for (const x of [xBack, xLine + 10]) add("alFrame", boxAt(16, yTop - yBot, 16, x, (yTop + yBot) / 2, s * halfW));
    add("alFrame", boxAt(xLine + 10 - xBack, 14, 14, (xLine + 10 + xBack) / 2, yTop, s * halfW),
        boxAt(xLine + 10 - xBack, 14, 14, (xLine + 10 + xBack) / 2, yBot, s * halfW),
        boxAt(xLine + 10 - xBack, 60, 6, (xLine + 10 + xBack) / 2, -rn - 30, s * halfW));
  }
  // The rear wall under the flap (the rammer goes through the open part above it).
  add("alFrame", boxAt(14, 14, 2 * halfW, xBack, yTop, 0), boxAt(14, flapTop - flapH - yBot, 2 * halfW, xBack, (yBot + flapTop - flapH) / 2, 0));
  add("alFlap", boxAt(6, flapH, 1.6 * Dc, 0, -flapH / 2, 0));
  Object.assign(A, { per, Rd, x0, yd, zd, rn, xBack, yTop, yBot, halfW, flapTop, flapH });
  A.bounds = { x0: A.xHome - 340, x1: W.ringRear + 520, y0: yBot - 20, y1: yTop + 60 };
}

// ---------- the cycle ----------

/** A track's value at time t, or `none` if the cycle has no such part. */
function track(al, part, t, none = 0) {
  const tr = al?.tracks?.[part];
  return tr && tr.t.length ? lerp(tr.t, tr.x, t) : none;
}

/** The most a track has been, from t0 to t. */
function trackMax(al, part, t0, t) {
  const tr = al?.tracks?.[part];
  if (!tr || !tr.t.length) return 0;
  let best = Math.max(lerp(tr.t, tr.x, t0), lerp(tr.t, tr.x, t));
  for (let i = 0; i < tr.t.length; i++) if (tr.t[i] > t0 && tr.t[i] < t) best = Math.max(best, tr.x[i]);
  return best;
}

/**
 * The mechanism's pose t s into a cycle (al: the autoloader's result, or a canned cycle; null: at rest).
 * Returns {carousel, conveyor, drum (positions turned), lift (mm), door, tray (0..1), block (1 open .. 0 shut),
 * rammer (m), head (mm: the rammer's head), trapdoor (rad), elevation (deg or null), pieces: [{dx}]}: dx is how far
 * (mm) a piece has been pushed from where it lies lined up, up to its way to its seat.
 */
export function loaderPose(A, al, t) {
  const g = (part) => track(al, part, t);
  const pose = { carousel: g("carousel"), conveyor: g("conveyor"), drum: g("drum"), lift: g("lift") * MM, door: g("door"),
                 tray: g("tray"), block: al ? track(al, "block", t, 1) : 0, rammer: g("rammer"), head: A.xHome,
                 trapdoor: 0, elevation: al && al.tracks?.elevation ? g("elevation") : null, pieces: [] };
  let active = null;
  A.pieces.forEach((p) => {
    const st = al?.stages?.find((s) => s.piece === p.name);
    let dx = 0;
    if (st && t >= st.start) {
      const seat = al.events?.find((e) => e.name === SEAT_EVENT[p.name])?.time;
      const headMax = A.xHome + trackMax(al, "rammer", st.start, t) * p.k * MM;
      dx = seat !== undefined && t >= seat ? p.delta : clamp(Math.max(p.base0, headMax) - p.base0, 0, p.delta);
      active = p;
    }
    pose.pieces.push({ dx });
  });
  if (active) pose.head = A.xHome + pose.rammer * active.k * MM;
  if (A.type === "oscillating" && al) {
    const open = al.events?.find((e) => e.name === "the case bangs out through the rear trapdoor")?.time;
    const shut = al.events?.find((e) => e.name === "the trapdoor swings shut")?.time;
    if (open !== undefined) pose.trapdoor = 1.2 * smooth((t - open) / 0.05) * (shut === undefined ? 1 : 1 - smooth((t - (shut - 0.08)) / 0.08));
  }
  return pose;
}

/** How far the gun is pitched (rad, muzzle up) from its aimed elevation to the loading angle at time t. */
export function loaderPitch(A, al, t) {
  if (A.loadAngle === null || !al?.tracks?.elevation) return 0;
  const span = A.loadAngle - A.gunElev;
  if (Math.abs(span) < 1e-9) return 0;
  const x = track(al, "elevation", t, A.gunElev);
  return clamp(Math.abs(x - A.gunElev) / Math.abs(span), 0, 1) * span * Math.PI / 180;
}

/** The turret's pitch (rad) of the mechanism, fixed to it, off the gun's aimed elevation. */
export function turretPitch(A) {
  return A.loadAngle === null ? 0 : (A.loadAngle - A.gunElev) * Math.PI / 180;
}

// ---------- what it holds ----------

/** A new state of what the autoloader holds: n rounds (or `mag` of them), where its carousel has got to. */
export function loaderState(A, mag) {
  const S = A.type === "oscillating"
    ? { drums: [Array(A.per).fill(false), Array(A.per).fill(false)], at: [0, 0], next: 0, cycle: null }
    : { slots: Array(A.n).fill(false), at: 0, cycle: null };
  return syncState(A, S, mag);
}

/** Make the state hold exactly `mag` rounds, filled in order from the one after where it has got to. */
export function syncState(A, S, mag) {
  mag = clamp(Math.round(mag), 0, A.n);
  if (A.type === "oscillating") {
    const have = S.drums[0].filter(Boolean).length + S.drums[1].filter(Boolean).length;
    if (have === mag) return S;
    const counts = [Math.ceil(mag / 2), Math.floor(mag / 2)];
    for (let k = 0; k < 2; k++) {
      S.drums[k].fill(false);
      for (let i = 1; i <= counts[k]; i++) S.drums[k][(S.at[k] + i) % A.per] = true;
    }
    return S;
  }
  if (S.slots.filter(Boolean).length === mag) return S;
  S.slots.fill(false);
  for (let i = 1; i <= mag; i++) S.slots[(S.at + i) % A.n] = true;
  return S;
}

/**
 * A cycle is about to start (al: its result): which cassette, cell or drum round it will take, once what the
 * carousel, conveyor or drum turns takes it round.
 */
export function beginCycle(A, S, al) {
  const part = A.type === "bustle" ? "conveyor" : A.type === "oscillating" ? "drum" : "carousel";
  const tr = al?.tracks?.[part];
  const steps = tr && tr.x.length ? Math.round(tr.x[tr.x.length - 1]) : 0;
  if (A.type === "oscillating") {
    let d = S.next;
    if (!S.drums[d].some(Boolean)) d = 1 - d;
    const slots = S.drums[d], used = wrap(S.at[d] + steps, A.per);
    if (!slots.some(Boolean)) { S.cycle = { drum: d, used: -1, at0: S.at[d], steps }; return S; }
    if (!slots[used]) { slots[slots.findIndex(Boolean)] = false; slots[used] = true; }
    S.cycle = { drum: d, used, at0: S.at[d], steps };
    return S;
  }
  const used = wrap(S.at + steps, A.n);
  if (!S.slots.some(Boolean)) { S.cycle = { used: -1, at0: S.at, steps }; return S; }
  if (!S.slots[used]) { S.slots[S.slots.findIndex(Boolean)] = false; S.slots[used] = true; }
  S.cycle = { used, at0: S.at, steps };
  return S;
}

/** The cycle is over: the round it took is gone from its slot (if it loaded), and the carousel has turned. */
export function endCycle(A, S, loaded) {
  const c = S.cycle;
  S.cycle = null;
  if (!c) return S;
  if (A.type === "oscillating") {
    S.at[c.drum] = c.used >= 0 ? c.used : S.at[c.drum];
    if (c.used >= 0 && loaded) { S.drums[c.drum][c.used] = false; S.next = 1 - c.drum; }
    return S;
  }
  if (c.used >= 0) {
    S.at = c.used;
    if (loaded) S.slots[c.used] = false;
  }
  return S;
}

/** Rounds the state holds. */
export function heldRounds(A, S) {
  return A.type === "oscillating" ? S.drums[0].filter(Boolean).length + S.drums[1].filter(Boolean).length
    : S.slots.filter(Boolean).length;
}

// ---------- drawing ----------

/** A point on the bustle conveyor's oval, s mm along it from the middle of its lower row: {y, z}. */
function oval(A, s) {
  const { S, re, yb, yt, ym } = A, half = S / 2, arc = Math.PI * re;
  s = wrap(s, 2 * S + 2 * arc);
  if (s <= half) return { y: yb, z: s };
  if (s <= half + arc) { const a = (s - half) / re; return { y: ym - re * Math.cos(a), z: half + re * Math.sin(a) }; }
  if (s <= half + arc + S) return { y: yt, z: half - (s - half - arc) };
  if (s <= half + 2 * arc + S) { const a = (s - half - arc - S) / re; return { y: ym + re * Math.cos(a), z: -half - re * Math.sin(a) }; }
  return { y: yb, z: -half + (s - half - 2 * arc - S) };
}

/**
 * What to draw: {parts: [{mesh, model, material}], pieces: [{kind, model}]} for the autoloader in state S at `pose`.
 * T: the turret's frame (what the mechanism is fixed in), G: the gun's; a piece the rammer has taken is the gun's.
 */
export function loaderDraw(A, S, pose, T, G) {
  const parts = [], pieces = [];
  const part = (mesh, model, material) => parts.push({ mesh, model, material });
  const c = S.cycle;
  // The cycle's round, once the rammer has taken piece i: lined up behind the breech (the gun's frame) and pushed on.
  const taken = (i) => !!c && c.used >= 0 && pose.pieces[i].dx > 0;
  part("alFrame", T, "steel");
  part("alRammer", chain(T, translation(pose.head, 0, 0)), "bolt");
  if (A.type === "az" || A.type === "mz") drawCarousel(A, S, pose, T, part, pieces, taken);
  else if (A.type === "bustle") drawBustle(A, S, pose, T, part, pieces, taken);
  else drawDrums(A, S, pose, T, part, pieces, taken);
  A.pieces.forEach((p, i) => {
    if (taken(i)) pieces.push({ kind: p.name, model: chain(G, translation(p.base0 + pose.pieces[i].dx, 0, 0)) });
  });
  return { parts, pieces };
}

function drawCarousel(A, S, pose, T, part, pieces, taken) {
  const { n, Rcp, Lh, pl, cl, laneC, xc, yRest } = A, mz = A.type === "mz";
  const c = S.cycle;
  const turn = (c ? c.at0 : S.at) + pose.carousel;
  const around = rotationY(-TAU * turn / n);
  part("alRing", chain(T, translation(xc, yRest, 0), around), "paint");
  part("alCarriage", chain(T, translation(0, pose.lift, 0)), "steel");
  const theta = pose.tray * Math.PI / 2;
  for (let k = 0; k < n; k++) {
    const mine = !!c && c.used === k && c.used >= 0;
    // The cycle's cassette rides up with the lift.
    const cass = chain(T, translation(0, mine ? pose.lift : 0, 0), translation(xc, yRest, 0), around, rotationY(TAU * k / n), translation(-Rcp, 0, 0));
    part("alCassette", cass, "paint");
    // An MZ's charge stands upright on its tray, which swings it about its pivot into line (the cycle's cassette).
    const upright = chain(translation(A.xch, A.yb, 0), rotationZ(Math.PI / 2));
    const charge = !mz ? chain(cass, translation(Lh - cl, laneC, 0))
      : chain(cass, translation(A.hx, A.hy, 0), rotationZ(mine ? -theta : 0), translation(-A.hx, -A.hy, 0), upright);
    if (mz) part("alTray", charge, "steel");
    if (!S.slots[k] && !mine) continue;
    if (A.twoPiece) {
      if (!(mine && taken(0))) pieces.push({ kind: "projectile", model: chain(cass, translation(Lh - A.ahead, 0, 0)) });
      if (!(mine && taken(1))) pieces.push({ kind: "charge", model: charge });
    } else if (!(mine && taken(0))) {
      pieces.push({ kind: "round", model: chain(cass, translation(Lh - A.oal, 0, 0)) });
    }
  }
}

function drawBustle(A, S, pose, T, part, pieces, taken) {
  const { n, P, drop, re, S: row, x0, ym } = A;
  const c = S.cycle;
  const turn = (c ? c.at0 : S.at) + pose.conveyor;
  // The conveyor's cells and their rounds; the front cell's round goes down onto the ramming tray.
  for (let k = 0; k < n; k++) {
    const p = oval(A, (k - turn) * P), front = !!c && c.used === k && c.used >= 0;
    part("alCell", chain(T, translation(x0, p.y, p.z)), "black");
    if (!S.slots[k] && !front) continue;
    if (!front) {
      pieces.push({ kind: "round", model: chain(T, translation(x0, p.y, p.z)) });
    } else {
      const y = p.y - drop * pose.tray;
      A.pieces.forEach((q, i) => { if (!taken(i)) pieces.push({ kind: q.name, model: chain(T, translation(q.base0, y, p.z)) }); });
    }
  }
  const spin = -turn * P / re;
  for (const z of [row / 2, -row / 2]) {
    for (const x of A.stations) part("alSprocket", chain(T, translation(x, ym, z), rotationX(spin)), "steel");
  }
  part("alRamTray", chain(T, translation(x0, drop * (1 - pose.tray), 0)), "steel");
  part("alDoor", chain(T, translation(A.doorX, 1.4 * A.D * pose.door, 0)), "steel");
}

function drawDrums(A, S, pose, T, part, pieces, taken) {
  const { per, Rd, x0, yd, zd, drop } = A;
  const c = S.cycle;
  part("alTray", chain(T, translation(x0, 0, 0)), "steel");
  part("alFlap", chain(T, translation(A.xBack, A.flapTop, 0), rotationZ(-pose.trapdoor)), "steel");
  for (let d = 0; d < 2; d++) {
    const mine = !!c && c.drum === d, z = d ? zd : -zd;
    const turn = (mine ? c.at0 + pose.drum : S.at[d]);
    const drum = chain(T, translation(0, yd, z), rotationX(-TAU * turn / per));
    part("alDrum", drum, "paint");
    for (let j = 0; j < per; j++) {
      const phi = Math.PI + TAU * j / per, front = mine && c.used === j && c.used >= 0;
      if (!S.drums[d][j] && !front) continue;
      const slot = (base) => chain(drum, translation(base, Rd * Math.cos(phi), Rd * Math.sin(phi)));
      if (!front) { pieces.push({ kind: "round", model: slot(x0) }); continue; }
      // The round the drum has brought to its bottom drops onto the tray, sliding in towards the middle.
      const f = pose.tray, y = yd - Rd - drop * f, zz = z * (1 - smooth(f));
      A.pieces.forEach((q, i) => {
        if (!taken(i)) pieces.push({ kind: q.name, model: f > 0 ? chain(T, translation(q.base0, y, zz)) : slot(q.base0) });
      });
    }
  }
}

// ---------- a cycle of its own ----------

/**
 * A canned cycle, shaped like the simulation's: the autoloader taking a round from where it is, in the same
 * tracks, stages and events, from a breech that is open (or shut with a spent case in it, which it opens first).
 * opts: {open: the block is shut, empty: nothing to load, mag: rounds held}.
 */
export function cannedCycle(A, { open = false, empty = false, mag = A.n } = {}) {
  const tracks = {}, events = [], stages = [];
  const at = (part, t, x) => { const q = (tracks[part] ??= { t: [], x: [] }); q.t.push(t); q.x.push(x); };
  const val = (part, none = 0) => { const q = tracks[part]; return q ? q.x[q.x.length - 1] : none; };
  const ease = (part, t0, dur, to, name = null, piece = null) => {
    const from = val(part);
    at(part, t0, from);
    for (let i = 1; i <= 12; i++) at(part, t0 + dur * i / 12, from + (to - from) * smooth(i / 12));
    if (name) stages.push({ name, part, start: t0, end: t0 + dur, piece });
    return t0 + dur;
  };
  const event = (time, name) => events.push({ time, name, detail: "", energy: 0, mass: 0, where: "turret" });
  for (const part of ["rammer", "lift", "door", "tray", "carousel", "conveyor", "drum"]) at(part, 0, 0);
  at("block", 0, open ? 0 : 1);
  at("elevation", 0, A.gunElev);
  let now = 0.1;
  if (open) {
    now = ease("block", 0, 0.5, 1, "open the breech");
    event(now, { az: "the stub is thrown out through the turret's hatch", mz: "the stub catcher takes the stub",
                 oscillating: "the case bangs out through the rear trapdoor" }[A.type] ?? "the extractors throw the case");
    if (A.type === "oscillating") event(now + 0.32, "the trapdoor swings shut");
  }
  if (empty) return finish(A, { tracks, events, stages, loaded: false, mag, status: "empty" });
  const start = now + 0.05;
  let ready = start;
  const lay = A.loadAngle !== null && Math.abs(A.loadAngle - A.gunElev) > 1e-6;
  if (lay) ready = Math.max(ready, ease("elevation", start, 1.0, A.loadAngle, "bring the gun to its loading angle"));
  if (A.type === "oscillating") ready = Math.max(ready, ease("drum", start, 0.4, 1, "turn the drum a round on"));
  else if (A.type === "bustle") {
    ready = Math.max(ready, ease("conveyor", start, 0.9, 1, "run the conveyor"), ease("door", start, 0.6, 1, "open the blast door"));
  } else ready = Math.max(ready, ease("carousel", start, 0.9, 1, "turn the carousel"));
  now = ready + 0.1;
  const L = A.lift / MM, Tr = A.tier / MM;
  if (A.type === "az" || A.type === "mz") {
    now = ease("lift", now, 1.0, L, "raise the cassette behind the breech");
    if (A.type === "mz") now = ease("tray", now, 0.7, 1, "swing the charge tray into line");
  } else if (A.type === "bustle") {
    now = ease("tray", now, 0.5, 1, "transfer the round onto the ramming tray");
    event(now, "the round drops onto the ramming tray");
  } else {
    now = ease("tray", now, 0.25, 1, "the round drops onto the loading tray");
    event(now, "the round drops onto the loading tray");
    now += 0.1;
  }
  let seatAt = now;
  A.pieces.forEach((p, i) => {
    if (i && A.type === "az") now = ease("lift", now, 0.5, L + Tr, "raise the charge's tier into line");
    const t0 = now, dur = 0.75;
    ease("rammer", t0, dur, p.ram, `ram the ${p.name}`, p.name);
    seatAt = t0 + dur + 0.04;
    event(seatAt, SEAT_EVENT[p.name]);
    at("rammer", seatAt, p.ram);
    now = ease("rammer", seatAt, 0.6, 0, "draw the rammer back");
  });
  const shut = 0.35;
  ease("block", seatAt, shut, 0, "the block springs shut");
  event(seatAt + shut, "the block springs shut");
  if (A.type === "az" || A.type === "mz") {
    if (A.type === "mz") ease("tray", now, 0.5, 0, "swing the charge tray back");
    now = ease("lift", now, 1.0, 0, "lower the empty cassette");
  } else if (A.type === "bustle") {
    ease("tray", now, 0.5, 0, "return the ramming tray");
    now = ease("door", now, 0.6, 0, "shut the blast door");
  }
  if (lay) now = Math.max(now, ease("elevation", now, 1.0, A.gunElev, "lay the gun again"));
  return finish(A, { tracks, events, stages, loaded: true, mag, status: "loaded" });
}

function finish(A, al) {
  const end = Math.max(0, ...al.stages.map((s) => s.end), ...al.events.map((e) => e.time),
                       ...Object.values(al.tracks).map((q) => q.t[q.t.length - 1]));
  for (const q of Object.values(al.tracks)) if (q.t[q.t.length - 1] < end) { q.t.push(end); q.x.push(q.x[q.x.length - 1]); }
  return { ...al, type: A.type, two_piece: A.twoPiece, load_angle: A.loadAngle, rounds_before: al.mag,
           rounds_after: al.loaded ? al.mag - 1 : al.mag, end };
}
