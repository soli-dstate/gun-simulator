// Procedural rifle around the cartridge: a barrel (chamber, throat, bore and
// crown cut to fit the case), a receiver, the parts of the action that move,
// and furniture whose butt sits where [action] puts the shoulder (cg_distance
// behind the centre of mass, bore_height below the bore).
//
// The moving parts follow [action] type:
// * bolt: a two-lug rotating bolt with a handle, extractor and firing pin.
// * gas: a carrier with an op rod running forward to a piston in the gas
//   cylinder over the gas block (at the gas port), and a bolt head that turns
//   in it (two lugs in an AK, six or seven otherwise).
// * direct_impingement: no piston; a gas tube runs from the gas block back to
//   a key on top of the carrier, and a seven-lug bolt head turns in it.
// * blowback: a plain heavy bolt with a charging knob.
// * short_recoil: the barrel (and its extension) is its own part and recoils
//   with the bolt until it stops; a locking block under the bolt drops out of
//   it as it does.
// * roller_delayed / lever_delayed: a light bolt head and a carrier behind it
//   that runs ahead of it while the delay lasts; two rollers come in from the
//   sides of the head, or a lever on top of it tips back.
// * gas_delayed: a sleeve around the barrel, tied to the bolt by two rods,
//   whose front closes on a piston ring on the barrel just ahead of the port.
//
// With action.hammer, a hammer on a pivot behind the bolt group turns as the
// action simulation has it.
// [appearance] style dresses it: "rifle" a sporting stock round a turned
// receiver; "ar15" an aluminium upper and lower, rail, A-frame front sight,
// round handguard, buffer tube and collapsible stock; "ak" a stamped receiver
// and dust cover, rear sight block, gas tube with its wooden handguards and a
// wooden stock. A muzzle device is turned from the same dimensions the 2D
// solver draws (gun_sim/devices.py). The magazine or belt is [feed]'s, built
// by feed.js.
//
// Units are millimetres. x runs along the bore towards the muzzle, with x = 0
// at the case head of a chambered round (= the bolt face when the bolt is
// closed); y is up and z is to the right, where the bolt handle and the
// ejection port are.

import { buildCartridge } from "./cartridge.js";
import { buildFeed, feedGeometry } from "./feed.js";
import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { box, prism, rodProfile, sphereProfile, torusProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// As gun_sim/action.py fills them in: unlock travel (mm; carrier travel for a delayed blowback) and delay ratio.
const UNLOCK = { gas: 6, direct_impingement: 7, short_recoil: 3, roller_delayed: 5, lever_delayed: 6 };
const DELAY_RATIO = { roller_delayed: 4, lever_delayed: 6 };

/** Apply a rigid transform to mesh data. */
function bake(mesh, m) {
  const p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i], y = p[i + 1], z = p[i + 2];
    positions[i] = m[0] * x + m[4] * y + m[8] * z + m[12];
    positions[i + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
    positions[i + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    const a = n[i], b = n[i + 1], c = n[i + 2];
    normals[i] = m[0] * a + m[4] * b + m[8] * c;
    normals[i + 1] = m[1] * a + m[5] * b + m[9] * c;
    normals[i + 2] = m[2] * a + m[6] * b + m[10] * c;
  }
  return { positions, normals, indices: mesh.indices };
}

/** Scale mesh data about the origin; normals by the inverse scale, renormalised. */
function scaled(mesh, sx, sy, sz) {
  const p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    positions[i] = p[i] * sx; positions[i + 1] = p[i + 1] * sy; positions[i + 2] = p[i + 2] * sz;
    const a = n[i] / sx, b = n[i + 1] / sy, c = n[i + 2] / sz, l = Math.hypot(a, b, c) || 1;
    normals[i] = a / l; normals[i + 1] = b / l; normals[i + 2] = c / l;
  }
  return { positions, normals, indices: mesh.indices };
}

/** Join several meshes into one. Pass [mesh, transform] pairs or bare meshes. */
function merge(...entries) {
  const meshes = entries.map((e) => (Array.isArray(e) ? bake(e[0], e[1]) : e));
  const nv = meshes.reduce((s, m) => s + m.positions.length, 0);
  const ni = meshes.reduce((s, m) => s + m.indices.length, 0);
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

const boxAt = (sx, sy, sz, x, y, z) => [box(sx, sy, sz), translation(x, y, z)];
/** Rods of radius r along x (at y, z) and along y (at x, z). */
const rodX = (r, x0, x1, y = 0, z = 0, seg = 24) => [lathe(rodProfile(r, x0, x1), seg), translation(0, y, z)];
const rodY = (r, y0, y1, x, z = 0, seg = 24) => [lathe(rodProfile(r, y0, y1), seg), chain(translation(x, 0, z), rotationZ(Math.PI / 2))];
/** A pistol grip: top edge centred on x at yTop, raked back by `rake` per unit of height. */
const gripAt = (x, yTop, h, w, rake, sz) =>
  prism([[x + w / 2, yTop], [x - w / 2, yTop], [x - w / 2 - rake * h, yTop - h], [x + w / 2 - rake * h, yTop - h]], sz);

/** Boxes along x from x0 to x1, leaving out [a, b]: a receiver part with the feed opening cut from it. */
function cutX(x0, x1, a, b, make) {
  if (b <= x0 || a >= x1) return [make(x0, x1)];
  const out = [];
  if (a - x0 > 0.5) out.push(make(x0, a));
  if (x1 - b > 0.5) out.push(make(b, x1));
  return out;
}

/** Muzzle device dimensions in mm, filled in as gun_sim/devices.py dimensions() does; null for none. */
export function deviceDims(gun) {
  const d = gun.muzzle_device ?? {};
  if (!d.type || d.type === "none") return null;
  const bore = gun.barrel.bore_diameter;
  // Bores long, bores across and baffles (prongs) of each kind, as devices.py fills them in.
  const [long, across, count] = { brake: [8, 2.8, 3], flash_hider: [6, 2.4, 4] }[d.type] ?? [23, 5.1, 8];
  const wall = d.wall ?? 2e-3;
  const length = d.length ?? long * bore;
  const od = d.outer_diameter ?? Math.max(gun.barrel.muzzle_diameter + 4 * wall, across * bore);
  const rh = bore / 2 + (d.bore_clearance ?? 1e-3) / 2;
  const flare = Math.tan(((d.flare_angle ?? 4) * Math.PI) / 180);
  return {
    type: d.type, L: length * MM, R: (od / 2) * MM, n: d.baffles ?? count,
    rh: rh * MM, w: wall * MM,
    blast: (d.blast_chamber ?? Math.min(5 * bore, 0.4 * length)) * MM,
    angle: d.baffle_angle ?? 0, vent: d.vent_fraction ?? 0.5,
    // Flash hider: the collar (FLASH_COLLAR in devices.py), then the bore's radius as it opens.
    slotStart: 0.3 * length * MM, boreAt: (x) => Math.min(rh * MM + x * flare, (od / 2 - wall) * MM),
  };
}

/** Brake, suppressor or flash hider on the muzzle at x0 (mm). */
function buildDevice(dd, x0, boreR, rMuzzle) {
  const { L, R, rh, w } = dd;
  const ri = R - w;
  const parts = [];
  const tube = (a, b) => { if (b - a > 0.2) parts.push(lathe(tubeProfile(ri, R, x0 + a, x0 + b), 64)); };
  if (dd.type === "flash_hider") {
    // Collar, its bore opening up, then prongs with slots between them to the open front.
    const xs = dd.slotStart, rs = dd.boreAt(xs);
    parts.push(lathe([
      [[rh, x0], [R, x0]], [[R, x0], [R, x0 + xs]], [[R, x0 + xs], [rs, x0 + xs]], [[rs, x0 + xs], [rh, x0]],
    ], 64));
    const inner = 0.5 * (rs + dd.boreAt(L)), mid = 0.5 * (inner + R);
    const width = 2 * mid * Math.sin(Math.max(0.05, ((1 - dd.vent) * Math.PI) / dd.n));
    for (let k = 0; k < dd.n; k++) {
      parts.push([box(L - xs, R - inner, width),
                  chain(rotationX(((k + 0.5) * 2 * Math.PI) / dd.n), translation(x0 + (xs + L) / 2, mid, 0))]);
    }
  } else if (dd.type === "suppressor") {
    tube(0, L);
    parts.push(lathe(tubeProfile(boreR + 0.05, ri, x0, x0 + w), 64));         // rear cap
    parts.push(lathe(tubeProfile(rh, ri, x0 + L - w, x0 + L), 64));           // front cap
    const start = w + dd.blast, end = L - w;
    const tan = Math.tan((dd.angle * Math.PI) / 180);
    for (let k = 0; k < dd.n; k++) {
      const xk = x0 + start + ((end - start) * k) / dd.n;
      const rise = Math.min((ri - rh) * tan, x0 + end - xk - w);
      if (rise <= 0.05) {
        parts.push(lathe(tubeProfile(rh, ri, xk, xk + w), 64));
      } else {  // a cone, tip (the hole) towards the muzzle
        parts.push(lathe([
          [[rh, xk], [ri, xk + rise]], [[ri, xk + rise], [ri, xk + rise + w]],
          [[ri, xk + rise + w], [rh, xk + w]], [[rh, xk + w], [rh, xk]],
        ], 64));
      }
    }
  } else {
    const pitch = L / dd.n;
    parts.push(lathe(tubeProfile(rMuzzle, R, x0, x0 + w), 64));                // rear ring
    for (let k = 1; k <= dd.n; k++) {
      const xb = k * pitch;
      parts.push(lathe(tubeProfile(rh, R, x0 + xb - w, x0 + xb), 64));        // baffle
      const xs = (k - 1) * pitch + (k > 1 ? w : 0) + w, xe = xb - 2 * w;
      tube((k - 1) * pitch + (k > 1 ? w : 0), xs);
      tube(xe, xb - w);
      // Bars top and bottom between the side vents.
      const half = Math.max(0.05, (1 - dd.vent) * Math.PI / 2);
      const chord = 2 * R * Math.sin(half);
      if (xe - xs > 0.2) {
        for (const sgn of [1, -1]) parts.push(bake(box(xe - xs, w, chord), translation(x0 + (xs + xe) / 2, sgn * (R - w / 2), 0)));
      }
    }
  }
  return merge(...parts);
}

/** Geometry and layout of the rifle for a gun config (SI in, mm out). */
export function buildRifle(gun) {
  const cart = buildCartridge(gun);
  const d = cart.dims;
  const warnings = [...cart.warnings];
  const rb = (gun.barrel.bore_diameter * MM) / 2;
  const boreR = rb + 0.02;                  // a hair over the projectile, so the surfaces don't z-fight
  const c = 0.05;                           // chamber clearance around the case
  const oal = Math.max(gun.case.overall_length * MM, d.length);
  const act = gun.action ?? {};
  const kind = act.type ?? "bolt";
  const style = gun.appearance?.style ?? "rifle";
  const ar = style === "ar15", ak = style === "ak";

  // ---- barrel ----
  const rearX = d.rimT + 0.6;               // the bolt nose fits in front of the case head
  const throatX = d.length + 0.25;
  const leadeX = throatX + Math.max(0.6, (d.neckR + c - boreR) * 2.5);
  let muzzleX = cart.seat + gun.barrel.travel * MM;
  if (muzzleX < leadeX + 5) {
    warnings.push("barrel is shorter than the chamber; lengthened for display");
    muzzleX = leadeX + 5;
  }
  const bodyR = (x) => d.baseR + (d.shR - d.baseR) * clamp((x - d.bodyStart) / Math.max(d.xs - d.bodyStart, 1e-6), 0, 1);
  const r0 = bodyR(rearX) + c;
  let breechR = (gun.barrel.breech_diameter * MM) / 2;
  const minBreech = Math.max(d.baseR, d.shR, d.rimR) + c + 2;
  if (breechR < minBreech) {
    warnings.push("barrel is thinner than the chamber walls allow; widened");
    breechR = minBreech;
  }
  let muzzleR = (gun.barrel.muzzle_diameter * MM) / 2;
  if (muzzleR < boreR + 1) {
    warnings.push("muzzle is thinner than the bore allows; widened");
    muzzleR = boreR + 1;
  }
  muzzleR = Math.min(muzzleR, breechR);

  const shankEnd = Math.min(d.length + 25, rearX + (muzzleX - rearX) * 0.35);
  const taperEnd = shankEnd + (muzzleX - shankEnd) * 0.55;
  /** Outside radius of the barrel at x. */
  const barrelR = (x) => {
    const s = clamp((x - shankEnd) / (taperEnd - shankEnd), 0, 1);
    return breechR + (muzzleR - breechR) * s * s * (3 - 2 * s);
  };
  const contour = [];
  for (let k = 0; k <= 16; k++) {
    const s = k / 16, e = s * s * (3 - 2 * s);
    contour.push([breechR + (muzzleR - breechR) * e, shankEnd + (taperEnd - shankEnd) * s]);
  }
  const ch = Math.min(0.8, (breechR - r0) / 3);
  const crown = Math.min(1.0, (muzzleR - boreR) * 0.4);
  const mc = Math.min(0.8, (muzzleR - boreR - crown) * 0.5);
  const chamberBody = d.bodyStart > rearX
    ? [[d.shR + c, d.xs], [d.baseR + c, d.bodyStart], [r0, rearX]]
    : [[d.shR + c, d.xs], [r0, rearX]];
  const barrel = lathe([
    [[r0, rearX], [breechR - ch, rearX]],
    [[breechR - ch, rearX], [breechR, rearX + ch]],
    [[breechR, rearX + ch], [breechR, shankEnd]],
    contour,
    [[muzzleR, taperEnd], [muzzleR, muzzleX - mc]],
    [[muzzleR, muzzleX - mc], [muzzleR - mc, muzzleX]],
    [[muzzleR - mc, muzzleX], [boreR + crown, muzzleX]],      // muzzle face
    [[boreR + crown, muzzleX], [boreR, muzzleX - crown]],     // crown
    [[boreR, muzzleX - crown], [boreR, leadeX]],              // bore
    [[boreR, leadeX], [d.neckR + c, throatX]],                // throat
    [[d.neckR + c, throatX], [d.neckR + c, d.xn]],            // chamber neck
    [[d.neckR + c, d.xn], [d.shR + c, d.xs]],                 // chamber shoulder
    chamberBody,                                              // chamber body
  ], 128);
  const device = deviceDims(gun);
  const deviceMesh = device ? buildDevice(device, muzzleX, boreR, muzzleR) : null;

  // ---- action dimensions shared by every style ----
  const boltR = Math.max(d.rimR + 2.2, d.baseR * 1.3);
  const lugH = Math.max(2.5, boltR * 0.3), lugLen = Math.max(6, boltR * 0.9), lugW = boltR * 0.8;
  const raceR = boltR + lugH + 0.4;         // raceway the lugs turn in
  const pinR = 1.0;
  const noseR = d.rimR + 1.0, noseX = d.rimT + 0.35, recessR = d.rimR + 0.12;
  const headR = Math.max(boltR * 0.82, noseR + 0.6);
  const delayed = kind === "roller_delayed" || kind === "lever_delayed";
  const ratio = delayed ? (act.delay_ratio ?? DELAY_RATIO[kind]) : 1;
  const unlockSet = act.unlock_travel != null ? act.unlock_travel * MM : (UNLOCK[kind] ?? 0);
  const mech = { kind, ratio, unlock: delayed ? unlockSet / ratio : unlockSet };
  // How far the bolt goes back: as the action simulation has it, or a bolt-action's throw.
  const stroke = kind === "bolt" ? oal + 5 : act.bolt_travel ? act.bolt_travel * MM : oal + 11;
  const pistonR = ((act.piston_diameter ?? 10e-3) / 2) * MM;
  const portX = cart.seat + (act.gas_port_position ?? (kind === "gas_delayed" ? 0.1 : 0.75) * gun.barrel.travel) * MM;
  const cylLen = Math.max((act.gas_stroke ?? 8e-3) * MM + 12, 22);
  const pivotY = -(act.bore_height ?? 0.03) * MM;
  // The feed (feed.js): a magazine under the round as the bolt strips it, or a belt over it.
  const fgeo = feedGeometry(gun, d), belt = fgeo.belt;
  const magLen = oal + 6, magX = -oal / 2 - 2.5;
  const magW = (fgeo.type === "single_stack" ? fgeo.d : 1.8 * fgeo.d) + 3;   // the magazine's top, in the magwell
  const [openA, openB] = belt ? [-oal - 24, -1] : [0, 0];                   // a belt's opening in the receiver's top
  const portRear = -(d.length + 14);        // ejection port, the AR and AK; the rifle's is longer

  const steelParts = [], furnParts = [], woodParts = [];
  const shortRecoil = kind === "short_recoil";
  if (!shortRecoil) {
    steelParts.push(barrel);
    if (deviceMesh) steelParts.push(deviceMesh);
  }

  // ---- receiver and furniture, by style. Each sets where the bolt group ends at the back
  // (boltRear), the receiver's size for the camera (recR), and where the gas runs. ----
  let recR, boltRear, magTop, cgX, buttX, portFront, portRearL, bridgeRear, yGas, yTube, frontOfReceiver;
  if (ar) {
    // Upper: walls round the carrier, tall enough over it for the gas tube and the key.
    yTube = Math.max(boltR + 4, breechR + 3.5);
    yGas = yTube;
    const wi = boltR + 1, wall = 2.5, W = wi + wall;
    const yTop = yTube + 4.5, yBot = -(boltR + 2);
    const upF = rearX + 28, upLen = Math.max(3.1 * oal, 120), upR = upF - upLen;
    boltRear = upR - 5;
    recR = W;
    portFront = -2; portRearL = portRear; bridgeRear = upR;
    magTop = yBot;
    frontOfReceiver = upF + 14;
    const H = yTop - yBot, xm = (upF + upR) / 2;
    const pTop = boltR * 0.75, pBot = -boltR * 0.75;
    // A belt's tray comes in over the left wall, through an opening in the top.
    const cutA = Math.max(openA, upR), cutB = Math.min(openB, upF);
    furnParts.push(
      ...cutX(upR, upF, openA, openB, (a, b) => boxAt(b - a, H, wall, (a + b) / 2, (yTop + yBot) / 2, -(wi + wall / 2))),  // left wall
      ...(belt ? [boxAt(cutB - cutA, boltR - yBot, wall, (cutA + cutB) / 2, (boltR + yBot) / 2, -(wi + wall / 2))] : []),
      ...cutX(upR, upF, openA, openB, (a, b) => boxAt(b - a, 3, 2 * W, (a + b) / 2, yTop + 1.5, 0)),                      // top
      ...cutX(upR + 3, upF - 3, openA, openB, (a, b) => boxAt(b - a, 3, 21, (a + b) / 2, yTop + 4.5, 0)),                  // rail
      boxAt(upF - portFront, H, wall, (upF + portFront) / 2, (yTop + yBot) / 2, wi + wall / 2),       // right, ahead of the port
      boxAt(portRear - upR, H, wall, (portRear + upR) / 2, (yTop + yBot) / 2, wi + wall / 2),         // right, behind it
      boxAt(portFront - portRear, yTop - pTop, wall, (portFront + portRear) / 2, (yTop + pTop) / 2, wi + wall / 2),
      boxAt(portFront - portRear, pBot - yBot, wall, (portFront + portRear) / 2, (pBot + yBot) / 2, wi + wall / 2),
      boxAt(3, H, 2 * W, upF - 1.5, (yTop + yBot) / 2, 0),                                            // front
      boxAt(10, 10, 4, portRear - 5, pTop + 4, W + 2),                                              // brass deflector
      [lathe(rodProfile(4, 0, 20), 24), translation(upR + 8, boltR * 0.55, W + 4)],                    // forward assist
      boxAt(8, 4, 2 * W + 16, upR - 2, yTop - 1, 0),                                                  // charging handle
    );
    for (let x = upR + 8; x < upF - 6; x += 10) {
      if (x + 2.5 < openA || x - 2.5 > openB) furnParts.push(boxAt(5, 3, 21, x, yTop + 7.5, 0));   // rail teeth
    }
    // Lower: body, magazine well, grip, guard and trigger.
    const lowB = yBot - 16, mwF = magX + magLen / 2 + 4, mwR = magX - magLen / 2 - 4;
    const gx = mwR - 40;
    furnParts.push(
      boxAt(mwF + 10 - (upR + 6), 16, 2 * W - 1, (mwF + 10 + upR + 6) / 2, yBot - 8, 0),
      ...(belt ? [] : [boxAt(mwF - mwR, 26, magW + 6, magX, lowB - 13 + 0.5, 0)]),
      gripAt(gx, lowB, 85, 26, 0.38, 24),
      boxAt(mwR - (gx + 13), 3, 12, (mwR + gx + 13) / 2, lowB - 24, 0),
      boxAt(4, 14, 4, gx + 24, lowB - 9, 0),
    );
    // Buffer tube on the bore line, and the collapsible stock on it.
    const tubeR = Math.max(14.9, boltR + 3);
    const tubeEnd = Math.min(upR - 180, boltRear - stroke - 30);
    cgX = magX;
    buttX = Math.min(cgX - (act.cg_distance ?? 0.4) * MM, tubeEnd + 40);
    const top = tubeR + 3, bottom = pivotY - 52, stockLen = 150;
    furnParts.push(
      lathe(tubeProfile(tubeR - 1.5, tubeR, tubeEnd, upR), 48),
      lathe(tubeProfile(tubeR - 0.5, tubeR + 4, upR - 8, upR), 48),                                   // castle nut
      prism([[buttX, top], [buttX + stockLen, top], [buttX + stockLen, -tubeR - 2], [buttX, bottom]], 2 * tubeR + 1),
      boxAt(8, top - bottom + 4, 2 * tubeR + 6, buttX - 4, (top + bottom) / 2, 0),                  // butt pad
    );
    // Barrel nut, delta ring and round handguard back from the front sight.
    const hgR = Math.max(breechR + 9, yTube + 6);
    const rB = barrelR(portX), ySight = yTop + 38;
    furnParts.push(
      lathe(tubeProfile(breechR - 0.3, breechR + 4, upF, upF + 14), 48),
      lathe(tubeProfile(hgR - 1.5, hgR + 2.5, upF + 14, upF + 22), 64),
    );
    if (portX - 14 > upF + 30) furnParts.push(lathe(tubeProfile(hgR - 2.5, hgR, upF + 22, portX - 14), 64));
    // Front sight base, which is also the gas block.
    steelParts.push(
      lathe(tubeProfile(rB - 0.3, rB + 4.5, portX - 11, portX + 11), 48),
      boxAt(20, yTube + 4 - rB, 12, portX, (yTube + 4 + rB) / 2, 0),
      prism([[portX - 9, yTube + 3], [portX + 9, yTube + 3], [portX + 2.5, ySight], [portX - 2.5, ySight]], 6),
      boxAt(5, 14, 2.5, portX, ySight - 5, 6), boxAt(5, 14, 2.5, portX, ySight - 5, -6),
      boxAt(1.8, 9, 1.8, portX, ySight + 2.5, 0),
      boxAt(14, 7, 6, portX - 2, -rB - 6, 0),                                                         // bayonet lug
    );
  } else if (ak) {
    const rw = boltR + 6;                   // receiver half-width
    yGas = Math.max(rw, breechR + 2) + pistonR + 1.5;
    yTube = yGas;
    const hDC = yGas + pistonR + 3;         // top of the dust cover
    const rxF = rearX + 40;
    boltRear = -2 * oal - 4;
    const rxR = boltRear - stroke - 10, rxLen = rxF - rxR, xm = (rxF + rxR) / 2;
    const rbot = -(boltR + 9), yRight = -boltR * 0.35;
    recR = rw;
    portFront = -2; portRearL = portRear; bridgeRear = rxR;
    magTop = rbot;
    frontOfReceiver = rxF + 38;
    // Stamped receiver: walls (the right one low, for the carrier's handle), floor, rear trunnion.
    const well = belt ? [0, 0] : [magX - magLen / 2 - 1, magX + magLen / 2 + 1];   // the magazine goes through the floor
    steelParts.push(
      boxAt(rxLen, -rbot, 1.2, xm, rbot / 2, -(rw - 0.6)),
      boxAt(rxLen, yRight - rbot, 1.2, xm, (yRight + rbot) / 2, rw - 0.6),
      ...cutX(rxR, rxF, well[0], well[1], (a, b) => boxAt(b - a, 1.2, 2 * rw, (a + b) / 2, rbot + 0.6, 0)),
      boxAt(10, -rbot, 2 * rw - 0.2, rxR + 5, rbot / 2, 0),
    );
    // Dust cover: a half-round shell stretched up over the carrier, and its back.
    steelParts.push(...cutX(rxR, rxF, openA, openB,
      (a, b) => scaled(lathe(tubeProfile(rw - 1.2, rw, a, b), 48, -Math.PI / 2, Math.PI / 2), 1, hDC / rw, 1)));
    const back = [];
    for (let k = 0; k <= 12; k++) { const a = -Math.PI / 2 + (k / 12) * Math.PI; back.push([rw * Math.sin(a), hDC * Math.cos(a)]); }
    steelParts.push([prism(back, 3), chain(translation(rxR + 1.5, 0, 0), rotationY(Math.PI / 2))]);
    // Rear sight block, leaf, gas tube; the gas block's 45-degree port; front sight.
    const rB = barrelR(portX);
    steelParts.push(
      boxAt(38, 2 * breechR + 4, 2 * breechR + 4, rxF + 19, 0, 0),
      boxAt(38, hDC - breechR, 2 * (pistonR + 4), rxF + 19, (hDC + breechR) / 2, 0),
      boxAt(60, 2.5, 10, rxF - 20, hDC + 1.2, 0),
      [lathe(tubeProfile(pistonR + 0.3, pistonR + 1.8, rxF + 38, portX - 4), 48), translation(0, yGas, 0)],
      prism([[portX - 6, -rB * 0.7], [portX + 10, -rB * 0.7], [portX + 10, yGas + pistonR + 2],
             [portX - 8 - (yGas + pistonR + 2 + rB * 0.7) * 0.6, yGas + pistonR + 2]], 2 * (pistonR + 3)),
    );
    const fsX = muzzleX - 28, rM = barrelR(fsX);
    steelParts.push(
      boxAt(22, 2 * rM + 6, 2 * rM + 6, fsX, 0, 0),
      prism([[fsX - 8, rM + 3], [fsX + 8, rM + 3], [fsX + 3, rM + 24], [fsX - 3, rM + 24]], 7),
      boxAt(4, 16, 2, fsX, rM + 17, 5), boxAt(4, 16, 2, fsX, rM + 17, -5),
      boxAt(1.6, 8, 1.6, fsX, rM + 22, 0),
      boxAt(16, 6, 8, fsX - 4, -(rM + 5), 0),                                                         // bayonet lug
      rodX(3, rxF + 40, fsX + 8, -(breechR + 4)),                                                     // cleaning rod
    );
    // Wooden handguards: the upper round the gas tube, the lower under the barrel, and its retainer.
    const hg0 = rxF + 38, hg1 = hg0 + clamp(0.75 * (portX - hg0), 40, 165);
    const yU = breechR * 0.5, yL = -(breechR + 12);
    if (portX - 62 > rxF + 50) woodParts.push([lathe(tubeProfile(pistonR + 1.8, pistonR + 5.5, rxF + 40, portX - 62), 48), translation(0, yGas, 0)]);
    woodParts.push(prism([[hg0, yU], [hg1, yU], [hg1 - 4, yL], [hg0 + 4, yL]], 2 * (breechR + 5)));
    steelParts.push(boxAt(8, yU - yL + 2, 2 * (breechR + 5) + 2, hg1 + 4, (yU + yL) / 2, 0));
    // Trigger guard, grip, selector lever and the stock.
    const xg0 = magX - magLen / 2 - 6, gx = xg0 - 42;
    steelParts.push(
      boxAt(xg0 - gx - 8, 2.5, 9, (xg0 + gx + 8) / 2, rbot - 26, 0),
      boxAt(2.5, 26, 9, xg0, rbot - 13, 0),
      boxAt(4, 14, 4, xg0 - 14, rbot - 8, 0),
      [box(85, 7, 1.2), chain(translation(rxR + 60, rbot * 0.35, rw + 0.6), rotationZ(-0.1))],
    );
    woodParts.push(gripAt(gx, rbot, 88, 26, 0.32, 24));
    cgX = magX + 20;
    buttX = Math.min(cgX - (act.cg_distance ?? 0.4) * MM, rxR - 170);
    woodParts.push(prism([[rxR + 2, hDC * 0.55], [rxR + 2, rbot], [buttX, pivotY - 62], [buttX, pivotY + 42]], 34));
    steelParts.push(boxAt(5, 108, 36, buttX - 2.5, pivotY - 10, 0));
  } else {
    // Rifle: turned receiver rings with an ejection port between them, and a magazine below.
    recR = Math.max(breechR + 2, raceR + 2.5);
    const ringFront = rearX + Math.max(18, breechR * 1.1);
    portFront = -(lugLen + 4);
    const portLen = oal + 8;
    portRearL = portFront - portLen;
    const bridgeLen = Math.max(20, boltR * 2.4);
    bridgeRear = portRearL - bridgeLen;
    boltRear = bridgeRear - 16;
    magTop = -recR;
    frontOfReceiver = ringFront;
    yGas = recR + pistonR + 1.5;
    yTube = Math.max(boltR + 3.5, breechR + 3);
    const rc = 1.0;
    steelParts.push(lathe([
      [[raceR, portFront], [recR - rc, portFront]],
      [[recR - rc, portFront], [recR, portFront + rc]],
      [[recR, portFront + rc], [recR, ringFront - rc]],
      [[recR, ringFront - rc], [recR - rc, ringFront]],
      [[recR - rc, ringFront], [breechR - 0.3, ringFront]],
      [[breechR - 0.3, ringFront], [breechR - 0.3, rearX + 0.3]],  // barrel threads in here
      [[breechR - 0.3, rearX + 0.3], [raceR, rearX + 0.3]],
      [[raceR, rearX + 0.3], [raceR, portFront]],
    ]));
    steelParts.push(lathe(tubeProfile(boltR + 0.3, recR, bridgeRear, portRearL, rc)));
    const floorTop = -(boltR + 0.6);
    const floorLen = ringFront - bridgeRear - 2;
    const well = belt ? [0, 0] : [magX - magLen / 2 - 1, magX + magLen / 2 + 1];   // the magazine comes up through it
    steelParts.push(...cutX(bridgeRear + 1, ringFront - 1, well[0], well[1],
      (a, b) => [box(b - a, recR + floorTop, recR * 1.3), translation((a + b) / 2, (-recR + floorTop) / 2, 0)]));
    // Trigger and guard; the stock is a low wrist the bolt can run back over, rising to the butt.
    // The centre of mass is taken to be over the magazine.
    const mX = magX;
    const guardR = Math.max(13, recR * 0.85), guardX = portRearL - guardR * 0.7, guardY = -recR - guardR * 0.55;
    const boltBack = Math.max(oal + 15, stroke + 10);
    const wristRear = bridgeRear - boltBack - 40;
    cgX = mX;
    buttX = Math.min(cgX - (act.cg_distance ?? 0.4) * MM, wristRear - 60);
    const wristTop = -(boltR + 4), wristBottom = -recR - Math.max(22, guardR * 1.6);
    furnParts.push(
      prism([[bridgeRear + 6, -recR * 0.2], [bridgeRear + 6, wristBottom], [wristRear, wristBottom], [wristRear, wristTop]], 2 * recR * 0.7),
      prism([[wristRear + 1, wristTop], [wristRear + 1, wristBottom], [buttX, Math.min(pivotY - 60, wristBottom - 15)],
             [buttX, Math.max(pivotY + 45, wristTop)]], 2 * recR * 0.75),
      [lathe(torusProfile(guardR, 2.2), 64), chain(translation(guardX, guardY, 0), rotationY(Math.PI / 2))],
      boxAt(4, guardR * 1.15, 5, guardX + 3, guardY + guardR * 0.05, 0),                     // trigger
    );
  }

  // ---- the feed: magazine or belt, and the feed cam the bolt group carries for a belt ----
  const groupFront = kind === "gas" || kind === "direct_impingement" ? -(lugLen + 10)
    : delayed ? -Math.max(14, boltR * 1.6) : -2;
  const feed = buildFeed(gun, { dims: d, boltR, recR, stroke, camTop: boltR, groupFront, lowest: magTop - 10 });
  furnParts.push(...feed.furniture);
  steelParts.push(...feed.steel);

  // ---- the moving parts (local: bolt face at x = 0, closed) ----
  /** Body of a bolt or bolt head of radius r from `rear` to the face: nose ring, recess, firing-pin channel. */
  const boltBody = (r, rear, seg = 96) => lathe([
    [[pinR, rear], [r - 0.8, rear]],
    [[r - 0.8, rear], [r, rear + 0.8]],
    [[r, rear + 0.8], [r, -0.6]],
    [[r, -0.6], [r - 0.6, 0]],
    [[r - 0.6, 0], [noseR, 0]],
    [[noseR, 0], [noseR, noseX]],                  // nose ring around the rim
    [[noseR, noseX], [recessR, noseX]],
    [[recessR, noseX], [recessR, -0.05]],          // bolt-face recess
    [[recessR, -0.05], [pinR, -0.05]],
    [[pinR, -0.05], [pinR, rear]],                 // firing-pin channel
  ], seg);
  const extractor = (len, r) => boxAt(len + noseX, 3, 1.2, (noseX - len) / 2, 0, r + 0.3);
  /** A knob on a stem out of the right side at x, for a bolt or carrier that is cocked by hand. */
  const knob = (x, r) => [
    [lathe(rodProfile(2.5, 0, 16), 24), chain(translation(x, 0, r - 1), rotationY(-Math.PI / 2))],
    [lathe(sphereProfile(5, 16), 24), chain(translation(x, 0, r - 1), rotationY(-Math.PI / 2))],
  ];
  const handKnob = !ar;                     // an AR is cocked by the T-handle on the upper
  /** A bolt head that turns in a carrier: n lugs and an extractor. */
  const rotatingHead = (len, n) => {
    const lugs = [];
    const w = lugW * Math.min(0.9, 2.6 / n);
    for (let k = 0; k < n; k++) {
      lugs.push([box(lugLen * 0.8, lugH * 0.8, w), chain(rotationX((k * 2 * Math.PI) / n), translation(-2 - lugLen * 0.4, headR + lugH * 0.35, 0))]);
    }
    return merge(boltBody(headR, -len, 64), ...lugs, extractor(20, headR));
  };

  let boltMesh, carrier = null, shroud = null, barrelMesh = null, lock = null, rollers = null, lever = null;
  const extra = {};                         // layout of the parts that follow the bolt
  if (kind === "bolt") {
    const handleLen = recR + 24;
    const handleAt = chain(translation(boltRear + 8, 0, 0), rotationX(0.3), rotationY(-Math.PI / 2));
    const lugY = boltR - 1 + (lugH + 1) / 2;
    boltMesh = merge(
      boltBody(boltR, boltRear),
      boxAt(lugLen, lugH + 1, lugW, -2 - lugLen / 2, lugY, 0),
      boxAt(lugLen, lugH + 1, lugW, -2 - lugLen / 2, -lugY, 0),
      extractor(30, boltR),
      [lathe(rodProfile(3.0, 0, handleLen), 32), handleAt],
      [lathe(sphereProfile(7.0, handleLen), 32), handleAt],
    );
    shroud = lathe(rodProfile(boltR * 0.92, boltRear - 14, boltRear - 0.3, 1.5));
  } else if (kind === "gas" || kind === "direct_impingement") {
    const headLen = lugLen + 10;
    const front = -headLen;
    boltMesh = rotatingHead(headLen, kind === "direct_impingement" || ar ? 7 : ak ? 2 : 6);
    const parts = [
      lathe(tubeProfile(headR + 0.3, boltR, boltRear, front, 0.8), 64),
      lathe(rodProfile(boltR, boltRear - 4, boltRear + 0.5, 1), 48),                        // carrier back
    ];
    if (handKnob) parts.push(boxAt(10, 6, 18, boltRear + 18, 2, boltR + 8));                // charging handle
    if (kind === "gas") {
      // Op rod from a lug on the carrier forward to the piston.
      const rodR = Math.max(1.5, pistonR * 0.42);
      parts.push(
        boxAt(16, yGas - boltR + 2, 2 * rodR + 3, front - 8, (yGas + boltR) / 2, 0),
        [lathe(rodProfile(rodR, front - 16, portX - cylLen + 8, 0.6), 24), translation(0, yGas, 0)],
        [lathe(rodProfile(pistonR, portX - cylLen + 4, portX - cylLen + 14, 0.6), 48), translation(0, yGas, 0)],
      );
      if (!ak) {
        // Gas block and cylinder (an AK's are part of its gas tube, above).
        const blockLen = Math.max(14, 2 * pistonR + 8);
        steelParts.push(boxAt(blockLen, yGas + pistonR + 3 - muzzleR * 0.4, 2 * (pistonR + 3), portX - blockLen / 2 + 3,
                              (yGas + pistonR + 3 + muzzleR * 0.4) / 2, 0));
        steelParts.push([lathe(tubeProfile(pistonR + 0.25, pistonR + 2.2, portX - cylLen, portX + 3), 48), translation(0, yGas, 0)]);
      }
    } else {
      // Gas key on top of the carrier, which the gas tube runs into when it is home.
      const keyFront = front - 6, keyLen = 28;
      parts.push(boxAt(keyLen, yTube + 3 - boltR + 1, 6, keyFront - keyLen / 2, (yTube + 3 + boltR - 1) / 2, 0));
      steelParts.push(rodX(2.3, keyFront, portX - 2.3, yTube), rodY(2.3, barrelR(portX) - 1, yTube, portX - 2.3));
      if (!ar && !ak) steelParts.push(boxAt(14, yTube + 4 - barrelR(portX) * 0.4, 10, portX, (yTube + 4 + barrelR(portX) * 0.4) / 2, 0));
    }
    carrier = merge(...parts);
  } else if (kind === "blowback" || kind === "gas_delayed" || shortRecoil) {
    boltMesh = merge(boltBody(boltR, boltRear), extractor(25, boltR),
                     ...(handKnob && kind !== "gas_delayed" ? knob(boltRear + 8, boltR) : []));
    if (shortRecoil) {
      // The barrel and its extension (side plates reaching back past the bolt's front) are one part,
      // with the locking block that rises into the bolt from below.
      const extRear = -(lugLen + 12);
      barrelMesh = merge(barrel, ...(deviceMesh ? [deviceMesh] : []),
        boxAt(rearX - extRear, boltR * 1.4, 1.5, (rearX + extRear) / 2, 0, boltR + 1.0),
        boxAt(rearX - extRear, boltR * 1.4, 1.5, (rearX + extRear) / 2, 0, -(boltR + 1.0)));
      const lockH = Math.max(2, boltR * 0.3);
      lock = merge(boxAt(lugLen, lockH + 4, boltR * 1.1, -(lugLen / 2 + 6), -(boltR - lockH) - (lockH + 4) / 2, 0));
      extra.lockDrop = lockH + 0.8;
    }
    if (kind === "gas_delayed") {
      // The sleeve: round the barrel ahead of the receiver, closed in front of the port; rods tie it to the bolt.
      const riS = breechR + 0.6, roS = riS + 2.5;
      const gasLen = ((act.gas_volume ?? 1e-6) / (Math.PI / 4 * (act.piston_diameter ?? 10e-3) ** 2)) * MM;
      const sleeveRear = frontOfReceiver + 2;
      const sleeveFront = Math.max(portX + Math.max(gasLen, (act.gas_stroke ?? 8e-3) * MM + 6), sleeveRear + 20);
      const zRod = Math.max(recR, roS) + 3;
      carrier = merge(
        lathe(tubeProfile(riS, roS, sleeveRear, sleeveFront - 3), 64),
        lathe(tubeProfile(barrelR(sleeveFront) + 0.3, roS, sleeveFront - 3, sleeveFront), 64),     // closes on the piston
        rodX(2, boltRear + 3, sleeveRear + 8, 0, zRod), rodX(2, boltRear + 3, sleeveRear + 8, 0, -zRod),
        boxAt(6, 6, 2 * zRod + 4, boltRear + 3, 0, 0),                                               // yoke behind the bolt
        boxAt(8, 5, zRod - roS + 1, sleeveRear + 4, 0, (roS + zRod) / 2),
        boxAt(8, 5, zRod - roS + 1, sleeveRear + 4, 0, -(roS + zRod) / 2),
      );
      // The piston: a ring on the barrel just behind the port.
      steelParts.push(lathe(tubeProfile(barrelR(portX - 8) - 0.2, riS - 0.2, portX - 10, portX - 2), 64));
    }
  } else {
    // Delayed blowback: a short head, and the carrier behind it.
    const headLen = Math.max(14, boltR * 1.6);
    const hR = Math.max(boltR * 0.85, noseR + 0.6);
    const head = [boltBody(hR, -headLen, 64), extractor(headLen - 2, hR)];
    const carrierParts = [
      lathe(rodProfile(boltR, boltRear, -headLen - 0.4, 1), 64),
      lathe(rodProfile(hR * 0.35, -headLen - 1, -headLen * 0.3, 0.4), 24),                // locking piece, into the head
      ...(handKnob ? knob(boltRear + 8, boltR) : []),
    ];
    if (kind === "roller_delayed") {
      // Two rollers, axes upright, standing out of the head's sides into the receiver while locked.
      const rr = Math.max(1.4, hR * 0.28), rLen = hR * 1.1, zr = hR + rr * 0.3;
      const roller = (z) => merge([lathe(rodProfile(rr, -rLen / 2, rLen / 2), 24), chain(translation(-headLen * 0.5, 0, z), rotationZ(Math.PI / 2))]);
      rollers = { right: roller(zr), left: roller(-zr) };
      extra.rollerIn = rr * 1.1;
    } else {
      // A lever pivoted in the top of the head; the carrier's tongue bears on its upper end.
      const up = boltR * 0.7, px = -headLen * 0.5, py = hR * 0.3, y0 = py - hR * 0.6, y1 = hR + up;
      lever = merge(boxAt(3.5, y1 - y0, hR * 0.7, px, (y0 + y1) / 2, 0));
      carrierParts.push(boxAt(px - 1.95 - (-headLen - 0.4), up * 0.8, hR * 0.7, (px - 1.95 - headLen - 0.4) / 2, hR + up * 0.55, 0));
      extra.lever = { px, py, arm: y1 - py };
    }
    boltMesh = merge(...head);
    carrier = merge(...carrierParts);
  }
  // A belt's feed cam rides on the carrier (on a one-piece bolt, or a gas-delayed slide's bolt).
  if (feed.cam.length) {
    if (carrier && kind !== "gas_delayed") carrier = merge(carrier, ...feed.cam);
    else boltMesh = merge(boltMesh, ...feed.cam);
  }
  // Firing pin and cocking piece move together; tip 0.9 mm behind the face when cocked.
  const pinTravel = 1.3;
  const striker = merge(
    lathe(rodProfile(pinR - 0.15, boltRear - 10, -0.9, 0.3), 24),
    lathe(rodProfile(boltR * 0.45, boltRear - 24, boltRear - 12, 1.0), 48),
  );
  // Hammer: pivoted below the bolt's path, its head resting on the tail of the firing pin. It
  // turns back (rotationZ(+angle) swings the head rearwards and down) as the carrier rides over
  // it; sized so the head sweeps about the carrier travel that cocks it, and lies below the
  // carrier when it is fully back.
  let hammer = null;
  if (act.hammer && kind !== "bolt") {
    const sear = ((act.hammer_angle ?? 60) * Math.PI) / 180;
    const top = Math.min(sear * 1.15, Math.PI / 2);
    const w = Math.max(3, boltR * 0.45), t = Math.max(4, boltR * 0.8), headH = Math.max(5, boltR * 0.7);
    // An AK's shallow receiver keeps the pivot above its floor.
    const deepest = ak ? -magTop - 1.5 - w * 0.45 + headH / 2 : boltR * 4;
    const len = Math.min(clamp(((act.hammer_cock_travel ?? 0.025) * MM) / Math.sin(top), boltR * 1.8, boltR * 4), deepest);
    hammer = merge(
      boxAt(w, len - headH / 2, t, 0, (len - headH / 2) / 2, 0),                         // arm
      boxAt(w * 1.5, headH, t * 1.1, w * 0.25, len - headH / 2, 0),                       // head
      boxAt(w * 1.2, w, t, -w * 0.6, len * 0.55, 0),                                      // sear notch
      [lathe(rodProfile(w * 0.45, -t * 0.9, t * 0.9), 24), rotationY(-Math.PI / 2)],      // pivot pin
    );
    extra.hammer = { px: boltRear - 24 - w, py: -len + headH / 2, sear };
  }

  return {
    cartridge: cart,
    meshes: {
      steel: merge(...steelParts), furniture: merge(...furnParts), bolt: boltMesh, striker,
      ...(woodParts.length ? { wood: merge(...woodParts) } : {}),
      ...(shroud ? { shroud } : {}), ...(carrier ? { carrier } : {}),
      ...(barrelMesh ? { barrel: barrelMesh } : {}), ...(lock ? { lock } : {}),
      ...(rollers ? { rollerRight: rollers.right, rollerLeft: rollers.left } : {}), ...(lever ? { lever } : {}),
      ...(hammer ? { hammer } : {}),
      ...(feed.magazine.length ? { magazine: merge(...feed.magazine) } : {}),
      ...(feed.meshes.follower ? { magFollower: feed.meshes.follower } : {}),
      ...(feed.meshes.link ? { link: feed.meshes.link, feedSlide: feed.meshes.feedSlide, feedLever: feed.meshes.feedLever } : {}),
      case: lathe(cart.parts.case),
      primer: lathe(cart.parts.primer),
      projectile: lathe(cart.parts.projectile),
      ...(cart.parts.core ? { core: lathe(cart.parts.core) } : {}),
    },
    layout: {
      bore: 2 * rb, boreR, muzzleX, rearX, breechR, muzzleR, recR, boltR,
      buttX, pivot: [buttX, pivotY], cgX, style, mech, ...extra,
      device, deviceLength: device ? device.L : 0, flashX: muzzleX + (device ? device.L : 0),
      boltRear: boltRear - 24, portFront, portRear: portRearL, bridgeRear, oal,
      stroke, pinTravel,
      seat: cart.seat, projectileLength: cart.projectileLength, coreMaterial: cart.coreMaterial,
      caseLength: d.length, head: d.head, caseInnerR: d.innerR, neckX: d.xn, rimR: d.rimR,
      feed: feed.layout,
    },
    warnings,
  };
}
