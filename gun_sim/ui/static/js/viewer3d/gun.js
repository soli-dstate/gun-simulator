// Procedural bolt-action rifle around the cartridge: barrel (chamber, throat,
// bore and crown cut to fit the case), receiver rings with an ejection port,
// a two-lug rotating bolt with handle, extractor and firing pin, plus a
// magazine, trigger guard and a stock whose butt sits where [action] puts the
// shoulder (cg_distance behind the centre of mass, bore_height below the bore).
//
// A gas-operated rifle gets a bolt carrier instead: a carrier with a charging
// handle and an op rod running forward to a piston in the gas cylinder over the
// gas block (at the gas port), and a separate six-lug bolt head that turns in it.
// A muzzle brake or suppressor is turned from the same dimensions the 2D solver
// draws (gun_sim/devices.py).
//
// Units are millimetres. x runs along the bore towards the muzzle, with x = 0
// at the case head of a chambered round (= the bolt face when the bolt is
// closed); y is up and z is to the right, where the bolt handle and the
// ejection port are.

import { buildCartridge } from "./cartridge.js";
import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, translation } from "./mat4.js";
import { box, prism, rodProfile, sphereProfile, torusProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

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

/** Muzzle device dimensions in mm, filled in as gun_sim/devices.py dimensions() does; null for none. */
export function deviceDims(gun) {
  const d = gun.muzzle_device ?? {};
  if (!d.type || d.type === "none") return null;
  const bore = gun.barrel.bore_diameter, brake = d.type === "brake";
  const wall = d.wall ?? 2e-3;
  const length = d.length ?? (brake ? 8 : 23) * bore;
  const od = d.outer_diameter ?? Math.max(gun.barrel.muzzle_diameter + 4 * wall, (brake ? 2.8 : 5.1) * bore);
  return {
    type: d.type, L: length * MM, R: (od / 2) * MM, n: d.baffles ?? (brake ? 3 : 8),
    rh: (bore / 2 + (d.bore_clearance ?? 1e-3) / 2) * MM, w: wall * MM,
    blast: (d.blast_chamber ?? Math.min(5 * bore, 0.4 * length)) * MM,
    angle: d.baffle_angle ?? 0, vent: d.vent_fraction ?? 0.5,
  };
}

/** Brake or suppressor on the muzzle at x0 (mm). */
function buildDevice(dd, x0, boreR, rMuzzle) {
  const { L, R, rh, w } = dd;
  const ri = R - w;
  const parts = [];
  const tube = (a, b) => { if (b - a > 0.2) parts.push(lathe(tubeProfile(ri, R, x0 + a, x0 + b), 64)); };
  if (dd.type === "suppressor") {
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

  // ---- receiver ----
  const boltR = Math.max(d.rimR + 2.2, d.baseR * 1.3);
  const lugH = Math.max(2.5, boltR * 0.3), lugLen = Math.max(6, boltR * 0.9), lugW = boltR * 0.8;
  const raceR = boltR + lugH + 0.4;         // raceway the lugs turn in
  const recR = Math.max(breechR + 2, raceR + 2.5);
  const ringFront = rearX + Math.max(18, breechR * 1.1);
  const portFront = -(lugLen + 4);
  const portLen = oal + 8;
  const portRear = portFront - portLen;
  const bridgeLen = Math.max(20, boltR * 2.4);
  const bridgeRear = portRear - bridgeLen;
  const rc = 1.0;
  const frontRing = lathe([
    [[raceR, portFront], [recR - rc, portFront]],
    [[recR - rc, portFront], [recR, portFront + rc]],
    [[recR, portFront + rc], [recR, ringFront - rc]],
    [[recR, ringFront - rc], [recR - rc, ringFront]],
    [[recR - rc, ringFront], [breechR - 0.3, ringFront]],
    [[breechR - 0.3, ringFront], [breechR - 0.3, rearX + 0.3]],  // barrel threads in here
    [[breechR - 0.3, rearX + 0.3], [raceR, rearX + 0.3]],
    [[raceR, rearX + 0.3], [raceR, portFront]],
  ]);
  const bridge = lathe(tubeProfile(boltR + 0.3, recR, bridgeRear, portRear, rc));
  const floorTop = -(boltR + 0.6);
  const floorLen = ringFront - bridgeRear - 2;
  const floor = box(floorLen, recR + floorTop, recR * 1.3);
  const device = deviceDims(gun);
  const steelParts = [
    barrel, frontRing, bridge,
    [floor, translation(bridgeRear + 1 + floorLen / 2, (-recR + floorTop) / 2, 0)],
  ];
  if (device) steelParts.push(buildDevice(device, muzzleX, boreR, muzzleR));

  // Magazine, floorplate, trigger and guard.
  const magLen = portLen - 6, magDepth = d.rimR * 3.6 + 6, magW = 2 * (d.rimR + 2.5);
  const magX = (portRear + portFront) / 2;
  const guardR = Math.max(13, recR * 0.85), guardX = portRear - guardR * 0.7, guardY = -recR - guardR * 0.55;
  // ---- gas system (gas-operated rifles): block, cylinder, and the piston's op rod ----
  const act0 = gun.action ?? {};
  const gasOp = act0.type === "gas";
  const pistonR = ((act0.piston_diameter ?? 10e-3) / 2) * MM;
  const yGas = recR + pistonR + 1.5;
  const portX = cart.seat + (act0.gas_port_position ?? 0.75 * gun.barrel.travel) * MM;
  const cylLen = Math.max((act0.gas_stroke ?? 8e-3) * MM + 12, 22);
  if (gasOp) {
    const blockLen = Math.max(14, 2 * pistonR + 8);
    steelParts.push(boxAt(blockLen, yGas + pistonR + 3 - muzzleR * 0.4, 2 * (pistonR + 3), portX - blockLen / 2 + 3,
                          (yGas + pistonR + 3 + muzzleR * 0.4) / 2, 0));
    steelParts.push([lathe(tubeProfile(pistonR + 0.25, pistonR + 2.2, portX - cylLen, portX + 3), 48), translation(0, yGas, 0)]);
  }
  const steel = merge(...steelParts);

  // Stock: a low wrist the bolt can run back over, rising to the butt. The
  // centre of mass is taken to be over the magazine.
  const act = gun.action ?? {};
  const boltBack = oal + 15;                // about how far any bolt goes back
  const wristRear = bridgeRear - boltBack - 40;
  const cgX = magX;
  const buttX = Math.min(cgX - (act.cg_distance ?? 0.4) * MM, wristRear - 60);
  const pivotY = -(act.bore_height ?? 0.03) * MM;
  const wristTop = -(boltR + 4), wristBottom = -recR - Math.max(22, guardR * 1.6);
  const stock = merge(
    prism([[bridgeRear + 6, -recR * 0.2], [bridgeRear + 6, wristBottom], [wristRear, wristBottom], [wristRear, wristTop]], 2 * recR * 0.7),
    prism([[wristRear + 1, wristTop], [wristRear + 1, wristBottom], [buttX, Math.min(pivotY - 60, wristBottom - 15)],
           [buttX, Math.max(pivotY + 45, wristTop)]], 2 * recR * 0.75),
  );
  const furniture = merge(
    stock,
    boxAt(magLen, magDepth, magW, magX, -recR - magDepth / 2 + 0.5, 0),
    boxAt(magLen + 8, 2.5, magW + 4, magX, -recR - magDepth - 0.75, 0),
    [lathe(torusProfile(guardR, 2.2), 64), chain(translation(guardX, guardY, 0), rotationY(Math.PI / 2))],
    boxAt(4, guardR * 1.15, 5, guardX + 3, guardY + guardR * 0.05, 0),                     // trigger
  );

  // ---- bolt (local: bolt face at x = 0) ----
  const pinR = 1.0;
  const noseR = d.rimR + 1.0, noseX = d.rimT + 0.35, recessR = d.rimR + 0.12;
  const boltRear = bridgeRear - 16;
  const boltBody = lathe([
    [[pinR, boltRear], [boltR - 0.8, boltRear]],
    [[boltR - 0.8, boltRear], [boltR, boltRear + 0.8]],
    [[boltR, boltRear + 0.8], [boltR, -0.6]],
    [[boltR, -0.6], [boltR - 0.6, 0]],
    [[boltR - 0.6, 0], [noseR, 0]],
    [[noseR, 0], [noseR, noseX]],                  // nose ring around the rim
    [[noseR, noseX], [recessR, noseX]],
    [[recessR, noseX], [recessR, -0.05]],          // bolt-face recess
    [[recessR, -0.05], [pinR, -0.05]],
    [[pinR, -0.05], [pinR, boltRear]],             // firing-pin channel
  ]);
  const lugY = boltR - 1 + (lugH + 1) / 2;
  const handleLen = recR + 24;
  const handleAt = chain(translation(boltRear + 8, 0, 0), rotationX(0.3), rotationY(-Math.PI / 2));
  const bolt = merge(
    boltBody,
    boxAt(lugLen, lugH + 1, lugW, -2 - lugLen / 2, lugY, 0),
    boxAt(lugLen, lugH + 1, lugW, -2 - lugLen / 2, -lugY, 0),
    boxAt(30 + noseX, 3.5, 1.2, (noseX - 30) / 2, 0, boltR + 0.3),   // extractor
    [lathe(rodProfile(3.0, 0, handleLen), 32), handleAt],
    [lathe(sphereProfile(7.0, handleLen), 32), handleAt],
  );
  let shroud = lathe(rodProfile(boltR * 0.92, boltRear - 14, boltRear - 0.3, 1.5));
  let carrier = null;
  let boltMesh = bolt;
  if (gasOp) {
    // Bolt head: turns in the carrier, six small lugs; the carrier slides, with the op rod and handle.
    const headLen = lugLen + 10;
    const headR = boltR * 0.82;
    const head = lathe([
      [[pinR, -headLen], [headR - 0.6, -headLen]],
      [[headR - 0.6, -headLen], [headR, -headLen + 0.6]],
      [[headR, -headLen + 0.6], [headR, -0.6]],
      [[headR, -0.6], [headR - 0.6, 0]],
      [[headR - 0.6, 0], [noseR, 0]],
      [[noseR, 0], [noseR, noseX]],
      [[noseR, noseX], [recessR, noseX]],
      [[recessR, noseX], [recessR, -0.05]],
      [[recessR, -0.05], [pinR, -0.05]],
      [[pinR, -0.05], [pinR, -headLen]],
    ], 64);
    const lugs = [];
    for (let k = 0; k < 6; k++) {
      lugs.push([box(lugLen * 0.8, lugH * 0.8, lugW * 0.45), chain(rotationX((k * Math.PI) / 3), translation(-2 - lugLen * 0.4, headR + lugH * 0.35, 0))]);
    }
    boltMesh = merge(head, ...lugs, boxAt(20 + noseX, 3, 1.2, (noseX - 20) / 2, 0, headR + 0.3));
    const front = -headLen;
    const rodR = Math.max(1.5, pistonR * 0.42);
    carrier = merge(
      lathe(tubeProfile(headR + 0.3, boltR, boltRear, front, 0.8), 64),
      lathe(rodProfile(boltR, boltRear - 4, boltRear + 0.5, 1), 48),                        // carrier back
      boxAt(16, yGas - boltR + 2, 2 * rodR + 3, front - 8, (yGas + boltR) / 2, 0),         // op rod lug
      [lathe(rodProfile(rodR, front - 16, portX - cylLen + 8, 0.6), 24), translation(0, yGas, 0)],  // op rod
      [lathe(rodProfile(pistonR, portX - cylLen + 4, portX - cylLen + 14, 0.6), 48), translation(0, yGas, 0)],  // piston
      boxAt(10, 6, 18, boltRear + 18, 2, boltR + 8),                                        // charging handle
    );
    shroud = null;
  }
  // Firing pin and cocking piece move together; tip 0.9 mm behind the face when cocked.
  const pinTravel = 1.3;
  const striker = merge(
    lathe(rodProfile(pinR - 0.15, boltRear - 10, -0.9, 0.3), 24),
    lathe(rodProfile(boltR * 0.45, boltRear - 24, boltRear - 12, 1.0), 48),
  );

  return {
    cartridge: cart,
    meshes: {
      steel, furniture, bolt: boltMesh, striker,
      ...(shroud ? { shroud } : {}), ...(carrier ? { carrier } : {}),
      case: lathe(cart.parts.case),
      primer: lathe(cart.parts.primer),
      projectile: lathe(cart.parts.projectile),
      ...(cart.parts.core ? { core: lathe(cart.parts.core) } : {}),
    },
    layout: {
      bore: 2 * rb, boreR, muzzleX, rearX, breechR, muzzleR, recR, boltR,
      buttX, pivot: [buttX, pivotY], cgX,
      device, deviceLength: device ? device.L : 0, flashX: muzzleX + (device ? device.L : 0), gasOp,
      boltRear: boltRear - 24, portFront, portRear, bridgeRear, oal,
      stroke: oal + 5, pinTravel,
      seat: cart.seat, projectileLength: cart.projectileLength, coreMaterial: cart.coreMaterial,
      caseLength: d.length, head: d.head, caseInnerR: d.innerR, neckX: d.xn, rimR: d.rimR,
      magTop: -recR,
    },
    warnings,
  };
}
