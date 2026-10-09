// Handguns for gun.js: pistols (a slide over the barrel, a frame with a raked
// grip holding the magazine) and revolvers (a frame round a cylinder that
// turns its chambers in line with the barrel). Units are mm, in the gun's
// frame: x along the bore from the case head of the round in battery, y up,
// z to the right.
//
// Pistols ([appearance] style "1911", "beretta" or "polymer"; any self-loading
// action): the slide is the bolt group, a shell round the barrel with the
// breech face at x = 0, an ejection port on the right, sights and serrations.
// Short recoil moves the barrel with it: "tilt" (Browning: 1911, Glock) has a
// hood over the chamber that locks into the port and a lug under it, and the
// barrel's breech drops as it unlocks; "block" (Beretta) has a locking block
// under the chamber whose wings drop out of the slide. The recoil spring lies
// on a guide rod under the barrel, its coils bunching as the slide comes back.
// The frame carries the slide on its rails, the dust cover over the spring,
// the trigger guard, the trigger and, raked back with the grip, the magazine.
// A hammer (1911 spur, Beretta round spur) turns on its pin at the frame's
// rear; a striker-fired gun has none.
//
// Revolvers (action "revolver"; style "revolver" or "single_action"): the
// cylinder is a ring of chamber walls round a hub (so it is fluted between
// them), turning about its axis rC below the bore; the recoil shield behind it
// carries the firing pin, the top strap runs over it to the frame's front,
// into which the barrel screws a cylinder gap ahead of it. "revolver" is a
// double-action frame: the cylinder swings out to the left on its crane, with
// an ejector rod and star; a full-length underlug and a ventilated rib on the
// barrel. "single_action" is the army's: a fixed cylinder on its base pin, a
// loading gate on the right of the recoil shield, the ejector rod in its
// housing beside the barrel, and a plow-handle grip.

import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { boxAt, cutX, merge, pinZ, rodX } from "./meshops.js";
import { box, prism, rodProfile, torusProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const HANDGUN_STYLES = ["1911", "beretta", "polymer", "revolver", "single_action"];
// As gun_sim/revolver.py.
const WEB = 1.5, WALL = 1.8, INDEX = [0.2, 0.85];
const COILS = 14;           // turns of the recoil spring drawn
const RAKE = { "1911": 18, beretta: 20, polymer: 22, revolver: 18, single_action: 28 };   // degrees

/** How far the grip rakes back (rad) for a style; 0 for a long gun. */
export function gripRake(style) {
  return ((RAKE[style] ?? 0) * Math.PI) / 180;
}

/** A revolver's cylinder (mm), as gun_sim/revolver.py has it. */
export function cylinderDims(gun, dims) {
  const n = Math.round(gun.feed?.capacity ?? 6), a = gun.action ?? {}, bar = gun.barrel;
  const rim = Math.max(2 * dims.rimR, 2 * dims.baseR);
  const rC = a.cylinder_radius != null ? a.cylinder_radius * MM : (2 * dims.rimR + WEB) / (2 * Math.sin(Math.PI / n));
  const Lc = bar.cylinder_length != null ? bar.cylinder_length * MM : gun.case.overall_length * MM + 1;
  return { n, rC, Ro: rC + rim / 2 + WALL, Lc, gap: (bar.cylinder_gap ?? 0) * MM, index: INDEX };
}

/** A revolver's barrel: from the cylinder gap (its forcing cone) to the muzzle. */
export function revolverBarrel(c) {
  const { boreR, muzzleX, barrelR, style } = c, cyl = c.cyl;
  const x0 = cyl.Lc + cyl.gap, cone = Math.max(1.2, (c.leade ?? 5) * 0.12 * boreR), crown = Math.min(0.8, (barrelR(muzzleX) - boreR) * 0.3);
  const pts = [];
  for (let k = 0; k <= 12; k++) { const x = x0 + ((muzzleX - x0) * k) / 12; pts.push([barrelR(x), x]); }
  const tube = lathe([
    [[boreR + cone, x0], [barrelR(x0), x0]],
    pts,
    [[barrelR(muzzleX), muzzleX], [boreR + crown, muzzleX]],
    [[boreR + crown, muzzleX], [boreR, muzzleX - crown]],
    [[boreR, muzzleX - crown], [boreR, x0 + 4]],
    [[boreR, x0 + 4], [boreR + cone, x0]],                // the forcing cone
  ], 96);
  const parts = [tube];
  const rB = barrelR(muzzleX), len = muzzleX - x0;
  if (style === "single_action") {
    // A blade front sight.
    parts.push(prism([[muzzleX - 12, rB - 1], [muzzleX - 3, rB - 1], [muzzleX - 5, rB + 6], [muzzleX - 10, rB + 6]], 2.2));
  } else {
    // Full-length underlug shrouding the ejector rod, and a ventilated rib on top.
    const lugTop = -rB * 0.5, lugBot = -(cyl.rC + 0.15 * cyl.Ro);
    parts.push(boxAt(len, lugTop - lugBot, 2 * rB * 0.85, x0 + len / 2, (lugTop + lugBot) / 2, 0));
    const ribY = rB + 1.2, posts = Math.max(3, Math.round(len / 22));
    parts.push(boxAt(len, 1.6, 2 * rB * 0.7, x0 + len / 2, ribY + 4, 0));
    for (let k = 0; k <= posts; k++) parts.push(boxAt(4, 4.2, 2 * rB * 0.7, x0 + 2 + ((len - 4) * k) / posts, ribY + 1.6, 0));
    parts.push(prism([[muzzleX - 14, ribY + 4.8], [muzzleX - 2, ribY + 4.8], [muzzleX - 2, ribY + 10], [muzzleX - 9, ribY + 10]], 2.6));
  }
  return merge(...parts);
}

/**
 * Dimensions of the slide (a pistol) or the frame round the cylinder (a revolver), before the feed is
 * known, and the values gun.js keeps for the rest of the gun (recR, boltRear, ...).
 */
export function handgunReceiver(c) {
  const { d, oal, boltR, breechR, muzzleX, style } = c;
  if (c.revolver) {
    const cyl = c.cyl, shield = Math.max(4, 0.35 * d.rimR * 2);
    const top = cyl.Ro - cyl.rC;                                    // the cylinder's top, over the bore
    return {
      revolver: true, cyl, shield, top, recR: cyl.Ro, boltRear: -shield + 24 - 8, portFront: cyl.Lc, portRearL: -shield - 30,
      bridgeRear: -shield - 30, magTop: -cyl.rC - cyl.Ro, frontOfReceiver: cyl.Lc + cyl.gap + 14, yGas: top + 6, yTube: top + 6,
    };
  }
  const wide = style === "polymer" ? 1.1 : 1;
  const bw = Math.max(boltR + 4, breechR + 2.6) * wide;           // half the slide's width
  const yT = Math.max(breechR + 3, boltR + 4.5) * (style === "polymer" ? 1.05 : 1);
  const yB = -(Math.max(boltR, breechR) + 6);
  const xF = muzzleX + (style === "1911" ? 1.5 : style === "beretta" ? -1 : 0);
  const xR = -(2 * oal + 10);
  return {
    pistol: true, bw, yT, yB, xF, xR, portA: -4, portB: d.length + 5,
    recR: bw, boltRear: xR + 24, portFront: d.length + 5, portRearL: -(oal + 20), bridgeRear: xR, magTop: yB,
    frontOfReceiver: xF, yGas: yT, yTube: yT,
  };
}

/** A hammer: arm up from its pin, the head (its face forwards, at the top) and a spur back from it. */
function hammerMesh(len, w, t, spur, round) {
  const headH = Math.max(5, len * 0.28);
  const parts = [
    boxAt(w, len - headH / 2, t, 0, (len - headH / 2) / 2, 0),
    boxAt(w * 1.4, headH, t, w * 0.2, len - headH / 2, 0),
    [lathe(rodProfile(w * 0.45, -t * 0.7, t * 0.7), 24), rotationY(-Math.PI / 2)],     // the pin
  ];
  if (round) {
    // A rounded spur with a hole through it (Beretta's).
    parts.push([lathe(torusProfile(spur * 0.45, spur * 0.18), 24), chain(translation(-spur * 0.6, len + spur * 0.05, 0), rotationY(Math.PI / 2))]);
  } else {
    parts.push(prism([[0, len - headH], [0, len], [-spur, len + spur * 0.35], [-spur, len + spur * 0.1]], t * 0.9));
  }
  return { mesh: merge(...parts), headH };
}

/** A trigger blade hanging from (x, y), curved back towards its foot. */
function triggerMesh(x, y, h, w) {
  return merge(prism([[x + 2.4, y + 3], [x - 2.4, y + 3], [x - 3.2, y - h * 0.55], [x - 0.6, y - h], [x + 1.6, y - h * 0.6]], w));
}

/** A rounded-rectangle trigger guard below the frame from x0 to x1, hanging `drop` below y0. */
function guardParts(x0, x1, y0, drop, w, t = 3) {
  return [
    boxAt(x1 - x0, t, w, (x0 + x1) / 2, y0 - drop + t / 2, 0),
    prism([[x1 - t, y0 - drop], [x1, y0 - drop], [x1 + t * 0.6, y0], [x1 - t * 0.4, y0]], w),
  ];
}

/**
 * The frame, grip, trigger guard and the fixed parts of a handgun, once the feed (a pistol's magazine,
 * raked in the grip) is known. Returns {steel, furniture, wood, bright, pivotX, buttX, cgX, recR, ...}.
 */
export function buildHandgunFrame(c, R, feed) {
  const { act, style, pivotY } = c;
  const out = { steel: [], furniture: [], wood: [], bright: [] };
  const rake = gripRake(style), tan = Math.tan(rake);
  if (R.revolver) return revolverFrame(c, R, out, tan);
  const { bw, yT, yB, xF, xR } = R, d = c.d, oal = c.oal;
  // The recoil spring's guide rod under the barrel, and the frame round it (the dust cover).
  const springR = Math.max(3, 0.32 * c.breechR), ySpring = -(c.muzzleR + springR + 0.8);
  const coverBottom = Math.min(yB - 6, ySpring - springR - 2.2);
  const xD = xF - (style === "1911" ? 42 : style === "beretta" ? 30 : 10);
  const headX = feed.headX, magBack = headX - 2, magFront = headX + oal + 3;
  const frame = style === "1911" ? out.steel : out.furniture;
  frame.push(...cutX(xR + 6, xD, magBack - 1, magFront + 1, (a, b) => boxAt(b - a, yB - coverBottom, 2 * bw - 1, (a + b) / 2, (yB + coverBottom) / 2, 0)));
  // Rails the slide rides on: a lip each side.
  for (const s of [1, -1]) frame.push(boxAt(xD - xR - 10, 1.5, 1.4, (xD + xR + 4) / 2, yB + 0.75, s * (bw - 1.6)));
  if (style === "polymer") frame.push(boxAt(Math.max(xD - c.d.length - 30, 10), 3, 2 * bw - 6, xD - Math.max(xD - c.d.length - 30, 10) / 2, coverBottom - 1.5, 0));   // accessory rail
  // The grip, raked back round the magazine, from under the frame down past its floorplate.
  const y0 = coverBottom, yBot = feed.geo.drop - feed.depth - 4, H = y0 - yBot;
  const front0 = magFront + 3, back0 = magBack - (style === "1911" ? 9 : 7);
  const gw = 2 * bw * (style === "polymer" ? 1.05 : 0.95);
  const grip = [[front0, y0], [front0 - tan * H, yBot], [back0 - tan * H - 2, yBot], [back0, y0]];
  frame.push(prism(grip, gw));
  // The frame's ears either side of the hammer (or striker) behind the slide, and the tang over the web
  // of the hand under them (a 1911's grip safety, a beavertail on the rest).
  const slot = 4.2;
  for (const s of [1, -1]) frame.push(boxAt(xR + 6 - (xR - 12), yT - 4 - y0, bw - slot, (xR + 6 + xR - 12) / 2, (yT - 4 + y0) / 2, s * (bw + slot) / 2));
  const tang = [[back0 + 2, y0 + 0.5], [back0 - 2 - tan * 14, y0 - 14], [xR - 16, y0 - 3], [xR - 14, y0 + 0.5]];
  (style === "1911" ? out.steel : frame).push(prism(tang, gw * 0.8));
  // Grip panels: walnut on a 1911, black plastic on a Beretta; the polymer frame's is moulded in.
  if (style !== "polymer") {
    const inset = 4, panel = [[front0 - 2, y0 - inset], [front0 - 2 - tan * (H - 2 * inset), yBot + inset], [back0 + 2 - tan * (H - 2 * inset), yBot + inset], [back0 + 2, y0 - inset]];
    for (const s of [1, -1]) (style === "1911" ? out.wood : out.furniture).push([prism(panel, 2.4), translation(0, 0, s * (gw / 2 + 1.1))]);
  } else {
    for (let k = 1; k < 8; k++) {
      const y = y0 - (H * k) / 8;
      for (const s of [1, -1]) frame.push([prism([[front0 - 3 - tan * (y0 - y), y], [back0 + 3 - tan * (y0 - y), y], [back0 + 3 - tan * (y0 - y + 1.2), y - 1.2], [front0 - 3 - tan * (y0 - y + 1.2), y - 1.2]], 0.8), translation(0, 0, s * (gw / 2 + 0.3))]);
    }
  }
  // The trigger guard and trigger.
  const gx0 = front0 - 2, gx1 = front0 + (style === "polymer" ? 40 : 44), drop = style === "1911" ? 22 : 24;
  frame.push(...guardParts(gx0, gx1, y0, drop, 6));
  const tx = front0 + 14;
  out.trigger = triggerMesh(0, 0, drop - 6, style === "1911" ? 5 : 6);
  out.triggerAt = { x: tx, y: y0 };
  // The slide stop on the left over the trigger, a 1911's thumb safety, the magazine release.
  out.steel.push(boxAt(18, 4, 1.6, tx + 6, y0 + 5, -(bw + 0.8)));
  if (style === "1911") out.steel.push(boxAt(12, 4, 1.6, back0 + 6, y0 + 6, -(bw + 0.8)));
  if (style === "beretta") out.bright.push(boxAt(8, 3, 1.6, tx - 6, yB - 3, -(bw + 0.8)));   // the takedown lever
  frame.push(boxAt(5, 5, 2, front0 - 4, y0 - 4, -(gw / 2 + 0.5)));
  // Spring and guide rod.
  out.spring = { x0: d.length + 8, x1: xF - (style === "beretta" ? 6 : 8), y: ySpring, r: springR, n: COILS };
  out.steel.push(rodX(springR * 0.45, out.spring.x0 - 4, out.spring.x1 - 6, ySpring));
  out.steel.push(boxAt(4, 2 * springR, 2 * springR, out.spring.x0 - 2, ySpring, 0));      // the guide rod's head
  out.coil = lathe(torusProfile(springR - 0.5, 0.55), 20);
  // Where the gun pivots in the hand: the web of the hand against the back of the grip at bore_height
  // below the bore; its centre of mass cg_distance ahead of that.
  const yWeb = clamp(pivotY, yBot + 10, y0);
  out.pivotX = back0 - tan * (y0 - yWeb) - 2;
  out.pivotY = yWeb;
  out.cgX = out.pivotX + (act.cg_distance ?? 0.04) * MM;
  out.buttX = Math.min(xR - 6, back0 - tan * H - 4);
  out.recR = 0.35 * (yT - yBot);
  out.gripBottom = yBot;
  out.rake = rake;
  return out;
}

function revolverFrame(c, R, out, tan) {
  const { d, style, pivotY, breechR } = c, { cyl, shield, top } = R;
  const saa = style === "single_action";
  const { rC, Ro, Lc, gap } = cyl, yAxis = -rC;
  const finish = saa ? out.steel : out.bright;
  const front = Lc + gap, yFrameBot = yAxis - Ro - 1;
  // Recoil shield behind the cylinder (a gate's notch on the right of a single action's).
  finish.push([lathe(rodProfile(Ro * 0.97, -shield, -0.35, 0.8), 64), translation(0, yAxis, 0)]);
  // Top strap over the cylinder, and the frame's front round the barrel's shank.
  const strapW = Math.max(Ro * 0.45, breechR + 1);
  finish.push(boxAt(front + 14 + shield, 5.5, 2 * strapW, (front + 14 - shield) / 2, top + 3.4, 0));
  finish.push(boxAt(14, top + 6 - (yAxis - Ro * 0.45), 2 * Math.max(strapW, breechR + 3), front + 7, (top + 6 + yAxis - Ro * 0.45) / 2, 0));
  // The frame under the cylinder, and behind it round the hammer (two side plates with the hammer between).
  finish.push(boxAt(front + 14 + shield + 8, 7, 2 * Ro * 0.62, (front + 14 - shield - 8) / 2, yFrameBot - 3.5, 0));
  const rear0 = -shield, rear1 = -shield - 30, hw = Ro * 0.45, slot = 4.6;
  for (const s of [1, -1]) finish.push(boxAt(rear0 - rear1, top + 6 - yFrameBot + 7, hw - slot, (rear0 + rear1) / 2, (top + 6 + yFrameBot - 7) / 2, s * (hw + slot) / 2));
  // The grip frame, raked down and back, and the grips round it.
  const y0 = yFrameBot - 7, H = saa ? 92 : 98;
  const g0 = -shield - 4, g1 = -shield - 36, yBot = y0 - H;
  const flare = saa ? 8 : 3;
  const grip = [[g0, y0], [g0 - tan * H + flare, yBot], [g1 - tan * H - flare, yBot], [g1, y0]];
  finish.push(prism(grip, 2 * hw * 0.7));
  const pad = [[g0 + 2, y0 - 2], [g0 - tan * H + flare + 2.5, yBot - 1], [g1 - tan * H - flare - 2.5, yBot - 1], [g1 - 3, y0 + 2]];
  (saa ? out.wood : out.furniture).push(...(saa ? [1, -1].map((s) => [prism(pad, 3.5), translation(0, 0, s * (hw * 0.7 + 1.6))])
    : [prism(pad, 2 * hw * 0.7 + 7)]));
  // The trigger guard and trigger.
  const gx0 = g0 - 4, gx1 = g0 + (saa ? 34 : 40), drop = saa ? 26 : 28;
  finish.push(...guardParts(gx0, gx1, y0, drop, 6));
  out.trigger = triggerMesh(0, 0, drop - 7, 6);
  out.triggerAt = { x: g0 + 12, y: y0 };
  // The firing pin through the shield, and its bushing (a single action's is on the hammer's face).
  out.firingPin = saa ? merge(rodX(0.6, -shield + 0.5, -shield + 1)) : merge(rodX(1.0, -shield - 0.6, -0.8), rodX(2.2, -shield, -shield + 1));
  if (saa) {
    // The base pin along the cylinder's axis, from the frame's front, and its catch.
    out.steel.push(rodX(2.6, -1, front + 18, yAxis), boxAt(6, 5, 5, front + 16, yAxis - 4, 4));
    // The ejector rod's housing beside the barrel, lined up with the chamber at the loading gate.
    const a = c.gateAngle, gy = yAxis + rC * Math.cos(a), gz = rC * Math.sin(a);
    out.steel.push([lathe(tubeProfile(2.0, 3.6, front + 2, front + 0.55 * (c.muzzleX - front)), 32), translation(0, gy, gz)]);
    out.rod = { y: gy, z: gz, x0: front + 2 };
    out.ejectorRod = merge(rodX(1.7, -c.oal * 0.0, c.oal * 1.3), boxAt(6, 4, 4, c.oal * 1.3 + 2, -3.5, 1.5));
    // The loading gate, hinged at its lower edge, over the chamber on the right.
    out.gate = merge(boxAt(4, 2 * d.rimR + 2, 3, -shield / 2 - 0.3, 0, 0));
    out.gateAt = { x: 0, y: gy, z: gz + Math.max(d.rimR, d.baseR) * 0.6 + 1.5 };
  } else {
    // The crane under the cylinder's front, carrying it out to the left; the ejector rod along its axis.
    out.crane = merge(boxAt(5, Ro * 0.9, 6, Lc + 1.8, -Ro * 0.45, -Ro * 0.25), [lathe(tubeProfile(2.7, 4.2, Lc + 0.3, Lc + gap + 10), 32), translation(0, 0, 0)]);
    out.ejector = merge(rodX(2.2, Lc, Lc + Math.min(0.9 * (c.muzzleX - front), 50)), rodX(3.2, Lc + Math.min(0.9 * (c.muzzleX - front), 50), Lc + Math.min(0.9 * (c.muzzleX - front), 50) + 5));
    out.craneAt = { y: yAxis - Ro * 0.9, z: -Ro * 0.5, out: 1.25 };   // its pivot, under and left of the cylinder
    // Rear sight on the strap, the cylinder latch on the left.
    out.bright.push(boxAt(10, 4, 8, -shield + 6, top + 8, 0));
    out.steel.push(boxAt(10, 4, 2, -shield - 10, yAxis + 3, -(hw + 1)));
  }
  // The web of the hand against the back of the grip, bore_height below the bore.
  const yWeb = clamp(pivotY, yBot + 10, y0);
  out.pivotX = g1 - tan * (y0 - yWeb) - 2;
  out.pivotY = yWeb;
  out.cgX = out.pivotX + (c.act.cg_distance ?? 0.06) * MM;
  out.buttX = g1 - tan * H - 6;
  out.recR = 0.35 * (top + 10 - yBot);
  out.gripBottom = yBot;
  out.rake = Math.atan(tan);
  return out;
}

/**
 * A pistol's moving parts: the slide (the bolt group's shell), the bolt (the extractor and breech face, bright
 * steel), the short-recoil barrel and a locking block, and the hammer. Returns meshes and layout.
 */
export function buildPistolParts(c, R) {
  const { d, style, barrel, deviceMesh, breechR, muzzleR, act, kind } = c;
  const { bw, yT, yB, xF, xR, portA, portB } = R, wall = 2.4;
  const open = style === "beretta";
  const parts = [];
  const plate = (a, b, w = 2 * bw, z = 0) => boxAt(b - a, 3, w, (a + b) / 2, yT - 1.5, z);
  // Top: a 1911's closed over the port (it opens only on the side); a Beretta's only over the breech and
  // a bridge at the front sight, the barrel bare between; the rest open over the port on the right.
  if (open) parts.push(plate(xR, portA), plate(xF - 16, xF));
  else if (style === "1911") parts.push(plate(xR, xF));
  else parts.push(...cutX(xR, xF, portA, portB, (p, q) => plate(p, q)), plate(portA, portB, bw * 0.9, -bw * 0.55));
  // Sides: the right one cut for the ejection port; a Beretta's cut down along its open top.
  const yPort = open ? -breechR * 0.2 : -breechR * 0.35, low = breechR * 0.25;
  const wallSeg = (s, a, b, top) => boxAt(b - a, top - yB, wall, (a + b) / 2, (top + yB) / 2, s * (bw - wall / 2));
  const runs = open ? [[xR, portB, yT], [portB, xF - 16, low], [xF - 16, xF, yT]] : [[xR, xF, yT]];
  for (const s of [1, -1]) {
    for (const [a, b, top] of runs) parts.push(...cutX(a, b, s > 0 ? portA : 1e9, s > 0 ? portB : 1e9, (p, q) => wallSeg(s, p, q, top)));
  }
  parts.push(wallSeg(1, portA, portB, yPort));
  // The breech block behind the breech face, round the firing pin (the striker's channel is left open in the cutaway).
  parts.push(boxAt(-0.3 - xR, yT - yB - 3, 2 * (bw - wall), (xR - 0.3) / 2, (yT + yB - 3) / 2, 0));
  // The nose round the muzzle: a 1911's bushing, the others' solid front.
  const hb = muzzleR + 0.35;
  if (style === "1911") {
    // The bushing round the muzzle, and the housing of the recoil spring's plug under it.
    parts.push(lathe(tubeProfile(hb, Math.min(bw, yT) - 0.3, xF - 14, xF + 1.5), 48));
    parts.push(boxAt(14, -hb - yB, 2 * bw, xF - 7, (-hb + yB) / 2, 0));
  } else {
    parts.push(boxAt(14, yT - hb, 2 * bw, xF - 7, (yT + hb) / 2, 0));
    parts.push(boxAt(14, -hb - yB, 2 * bw, xF - 7, (-hb + yB) / 2, 0));
    for (const s of [1, -1]) parts.push(boxAt(14, 2 * hb, bw - hb, xF - 7, 0, s * (bw + hb) / 2));
  }
  // Sights and the cocking serrations at the rear.
  parts.push(boxAt(7, 5, 2 * bw * 0.7, xR + 10, yT + 2.5, 0));
  parts.push(prism([[xF - (open ? 10 : 9), yT], [xF - 3, yT], [xF - 4, yT + 5.5], [xF - 8, yT + 5.5]], 2.6));
  for (let k = 0; k < 7; k++) {
    for (const s of [1, -1]) parts.push(boxAt(1.2, (yT - yB) * 0.8, 0.5, xR + 6 + 2.6 * k, (yT + yB) / 2, s * (bw + 0.2)));
  }
  if (style === "beretta") for (const s of [1, -1]) parts.push(boxAt(9, 3.5, 2, xR + 18, yT - 6, s * (bw + 1)));   // safety/decocker
  const slide = merge(...parts);
  // The bolt: an extractor along the right, its claw at the breech face.
  const bolt = merge(boxAt(-xR * 0.45, 3, 1.2, xR * 0.225, 1.5, bw - wall - 0.2), boxAt(1.4, 2.2, 1.6, 0.5, 0.6, d.rimR + 0.2));
  // The barrel: its hood (over the chamber, locking in the port) and the lug or block under it.
  let barrelMesh = null, lock = null, lockDrop = 0, tilt = null;
  if (kind === "short_recoil") {
    const hood = boxAt(portB - 1 - c.rearX, yT - 3 - breechR * 0.4, 2 * breechR * 0.95, (portB - 1 + c.rearX) / 2, (yT - 3 + breechR * 0.4) / 2, 0);
    const extra = [hood];
    if ((act.locking ?? "block") === "tilt") {
      // A lug under the chamber, on a link (1911) or against a cam (the rest); the breech drops about the bushing.
      extra.push(prism([[d.length * 0.25, -breechR + 1], [d.length + 8, -breechR + 1], [d.length + 4, -breechR - 6], [d.length * 0.4, -breechR - 6]], breechR));
      tilt = { x: xF - 10, drop: Math.max(1.6, breechR * 0.18) };
    } else {
      const lh = 3.4;
      lock = merge(boxAt(10, lh, 2 * bw - 2 * wall - 0.4, d.length * 0.7, -breechR - lh / 2 + 1.2, 0));
      lockDrop = lh;
    }
    barrelMesh = merge(barrel, ...(deviceMesh ? [deviceMesh] : []), ...extra);
  }
  // The hammer at the frame's rear, its face on the firing pin.
  let hammer = null, hammerAt = null;
  if (act.hammer) {
    const sear = ((act.hammer_angle ?? 60) * Math.PI) / 180;
    const len = clamp(((act.hammer_cock_travel ?? 0.012) * MM) / Math.sin(Math.min(sear * 1.15, Math.PI / 2)), 14, 26);
    const w = 5.5, t = Math.min(7.5, 2 * bw * 0.4);
    const h = hammerMesh(len, w, t, style === "beretta" ? 9 : 10, style === "beretta");
    hammer = h.mesh;
    hammerAt = { px: xR - w * 0.9, py: -len + h.headH / 2, sear };
  }
  return { slide, bolt, barrelMesh, lock, lockDrop, tilt, hammer, hammerAt };
}

/** The meshes of a revolver's cylinder (local: its axis on x, chamber 0 at +y, rC out), and its hammer. */
export function buildRevolverParts(c, R) {
  const { d, style, act } = c, cyl = R.cyl;
  const { n, rC, Ro, Lc } = cyl, saa = style === "single_action";
  const hole = d.baseR + 0.05, rimHole = d.rimR + 0.15, wallR = Ro - rC;
  const parts = [];
  for (let k = 0; k < n; k++) {
    const a = (k * 2 * Math.PI) / n, y = rC * Math.cos(a), z = rC * Math.sin(a);
    // Each chamber: counterbored for the rim at the rear, the case's bore, and the throat.
    parts.push([lathe([
      [[rimHole, 0], [wallR - 0.6, 0]], [[wallR - 0.6, 0], [wallR, 0.6]], [[wallR, 0.6], [wallR, Lc - 0.6]],
      [[wallR, Lc - 0.6], [wallR - 0.6, Lc]], [[wallR - 0.6, Lc], [c.boreR, Lc]], [[c.boreR, Lc], [c.boreR, d.length + 1]],
      [[c.boreR, d.length + 1], [hole, d.length]], [[hole, d.length], [hole, d.rimT]], [[hole, d.rimT], [rimHole, d.rimT]],
      [[rimHole, d.rimT], [rimHole, 0]],
    ], 40), translation(0, y, z)]);
  }
  // The hub between the chambers, the ratchet behind it, and (a double action's) the ejector star in its face.
  parts.push(lathe(tubeProfile(3.0, rC * 0.62, 0.2, Lc - 0.2), 48));
  parts.push(lathe(tubeProfile(2.4, rC * 0.45, -1.4, 0.2), 24));
  const cylinder = merge(...parts);
  const star = saa ? null : merge(lathe(tubeProfile(2.6, rC * 0.55, -0.05, d.rimT * 0.9), 6), ...Array.from({ length: n }, (_, k) => {
    const a = (k * 2 * Math.PI) / n;
    return [box(d.rimT * 0.9, rC * 0.5, 3), chain(rotationX(a), translation(d.rimT * 0.45, rC * 0.55, 0))];
  }));
  // The hammer: big, behind the shield, its nose (a single action's firing pin) on the primer.
  const sear = ((act.hammer_angle ?? 55) * Math.PI) / 180;
  const len = saa ? 30 : 27, w = 7, t = saa ? 7 : 8;
  const h = hammerMesh(len, w, t, saa ? 15 : 11, false);
  const parts2 = [h.mesh];
  if (saa) parts2.push(rodX(0.9, w * 0.9, w * 0.9 + R.shield + 0.4, len - h.headH / 2));   // the firing pin on its face
  const hammer = merge(...parts2);
  const hammerAt = { px: -R.shield - w * 0.9 - 0.5, py: -len + h.headH / 2, sear };
  return { cylinder, star, hammer, hammerAt };
}
