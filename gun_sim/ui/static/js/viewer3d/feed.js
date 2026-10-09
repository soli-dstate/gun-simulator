// Procedural magazines and belts, as gun_sim/feed.py has them: where the next
// round is presented and at what angle, the magazine body or belt mechanism,
// and where every round left sits.
//
// * Box magazines (single, double, quad stack): the stack curves forward as it
//   goes down, by as much as the case's taper makes it (the base end of each
//   round is thicker, so each one lies tilted on the one below): an AK's 7.62 x
//   39 magazine curves hard, an AR's 5.56 a little. A staggered stack's rounds
//   alternate sides, so the top round changes side every shot. A quad stack is
//   two double stacks side by side under a double-stack funnel.
// * Drum: a straight tower, then the rounds wound in a spiral round a sprung
//   rotor whose arm follows the last round.
// * Belt: the rounds lie in a feed tray over the bolt, the belt running off to
//   the left and down into a box. A cam groove on top of the bolt group swings a
//   feed lever in the top cover, whose front end slides the feed pawl across,
//   drawing the belt one link per cycle; empty links fall out to the right.
//
// The feed ramp runs from the chamber's edge back towards the magazine (from
// the top, for a belt). Units are mm, in the gun's frame (gun.js).

import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { box, prism, rodProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
export const CAPACITY = { single_stack: 10, double_stack: 30, quad_stack: 60, drum: 75, belt: 100 };
// As gun_sim/feed.py.
const PITCH = { single_stack: 1.0, double_stack: 0.6, quad_stack: 0.3, drum: 1.0 };
const STAGGER = 0.4, FUNNEL = 4, DRUM_TOWER = 4, LINK_PITCH = 1.2;
const PRESENT = 0.2, BELT_RAISE = 0.5, RAMP_FRICTION = 0.3;
const WALL = 1.0;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Where the next round is presented and the feed angle (mm, rad), as feed.py geometry(). */
export function feedGeometry(gun, dims) {
  const f = gun.feed ?? {}, type = f.type ?? "double_stack", belt = type === "belt";
  const d = 2 * dims.rimR, oal = Math.max(gun.case.overall_length * MM, dims.length);
  const boltR = Math.max(dims.rimR + 2.2, dims.baseR * 1.3);
  const sign = belt ? -1 : 1;
  const present = belt ? 0 : PRESENT * d;
  let under = boltR + d / 2, drop;
  if (belt) { drop = under = under + BELT_RAISE * d; } else { drop = -(under - present); under = -under; }
  const angle = f.feed_angle != null ? sign * f.feed_angle * Math.PI / 180 : Math.asin(Math.min(-drop / oal, 0.9));
  return {
    type, belt, sign, d, oal, present, drop, under, angle,
    capacity: Math.round(f.capacity ?? CAPACITY[type]),
    mouth: dims.baseR + 0.05, tip: Math.max((gun.projectile.meplat_diameter ?? 0) * MM / 2, 0.3),
    ramp: (f.ramp_angle ?? 35) * Math.PI / 180, face: dims.rimT + 0.6,
  };
}

/** What the round does as the bolt drives it, as feed.py check(): {jam, travel (mm), angle}. */
export function feedCheck(g, lift = 1, feedAt = g.oal + 3) {
  const s = g.sign, y = s * g.drop - (1 - lift) * g.present, th = s * g.angle;
  const tip = y + g.oal * Math.sin(th), clear = g.mouth - g.tip, foot = s * g.under;
  const tipX = -feedAt + g.oal * Math.cos(th);
  const out = { jam: null, travel: 0, angle: g.angle };
  if (tip > clear) return { ...out, jam: "stub", travel: Math.max(g.face - tipX, 0.5) };
  if (tip >= -clear) return out;
  if (tip < foot) return { ...out, jam: "nosedive", travel: Math.max(g.face - (-clear - foot) / Math.tan(g.ramp) - tipX, 0.5) };
  if (g.ramp - th > Math.PI / 2 - Math.atan(RAMP_FRICTION)) {
    return { ...out, jam: "nosedive", travel: Math.max(g.face - (-clear - tip) / Math.tan(g.ramp) - tipX, 0.5) };
  }
  return out;
}

const boxAt = (sx, sy, sz, x, y, z) => [box(sx, sy, sz), translation(x, y, z)];

/** A box along the segment (x0, z0)-(x1, z1) at height y: a rail of the feed cam. */
function railXZ(x0, z0, x1, z1, y, h, w) {
  const dx = x1 - x0, dz = z1 - z0, len = Math.hypot(dx, dz);
  return [box(len, h, w), chain(translation((x0 + x1) / 2, y, (z0 + z1) / 2), rotationY(Math.atan2(-dz, dx)))];
}

/**
 * The feed for a gun. ctx: {dims, boltR, recR, stroke (mm), camTop (y of the bolt group's top),
 * groupFront (bolt group's front, local x), lowest (y below which a belt box may hang)}.
 * Returns {geo, furniture: [parts], magazine: [parts] (its body), steel: [parts], meshes: {name: mesh}, cam: [parts] (onto the
 * bolt group), layout} where layout places the rounds: rounds(n, lift, adv) -> [{m, round, link}].
 */
export function buildFeed(gun, ctx) {
  const g = feedGeometry(gun, ctx.dims), { d, oal } = g, f = gun.feed ?? {};
  const headX = -oal - 2.5;                 // the next round's head, just ahead of the bolt face at the feed point
  const xm = headX + oal / 2;
  const furniture = [], magazine = [], steel = [], meshes = {}, cam = [];
  const layout = { geo: g, headX, type: g.type, belt: g.belt, capacity: g.capacity };

  // The feed ramp from the chamber's edge to where the top round lies under the bolt; only the part
  // below the bolt's path is drawn (the rest is cut into the barrel extension around the bolt).
  {
    const s = g.sign, top = Math.max(g.mouth, ctx.boltR + 0.3), foot = Math.abs(g.under);
    if (foot > top + 0.3) {
      const t = Math.tan(g.ramp), x0 = g.face - (top - g.mouth) / t, x1 = g.face - (foot - g.mouth) / t;
      steel.push(prism([[x0, s * -top], [x1, s * -foot], [x1, s * -(foot + 2)], [x0, s * -(foot + 2)]], 2 * g.mouth));
    }
  }

  if (g.belt) {
    buildBelt(gun, ctx, g, { headX, xm, furniture, steel, meshes, cam, layout, f });
    return { geo: g, furniture, magazine, steel, meshes, cam, layout };
  }

  const yTop = g.drop, Lx = oal + 4;
  layout.lowered = (lift) => (1 - lift) * g.present;

  if (g.type === "drum") {
    // Tower, then a spiral of rounds round the rotor (y, z), the drum's axis along the bore.
    const r0 = Math.max(1.6 * d, 12);
    const Rs = Math.sqrt(Math.max(g.capacity - DRUM_TOWER, 1) * d * d / Math.PI + r0 * r0) + 0.5 * d;
    const yc = yTop - DRUM_TOWER * d - Rs;
    const track = [{ u: 0, y: yc + Rs, z: 0, a: 0 }];
    for (let a = 0.02; ; a += 0.02) {
      const r = Rs - d * a / (2 * Math.PI);
      if (r < r0) break;
      const y = yc + r * Math.cos(a), z = r * Math.sin(a), p = track[track.length - 1];
      track.push({ u: p.u + Math.hypot(y - p.y, z - p.z), y, z, a });
    }
    const along = (u) => {
      let k = 0;
      while (k < track.length - 2 && track[k + 1].u < u) k++;
      const a = track[k], b = track[k + 1] ?? a, w = clamp((u - a.u) / ((b.u - a.u) || 1), 0, 1);
      return { y: a.y + (b.y - a.y) * w, z: a.z + (b.z - a.z) * w, a: a.a + (b.a - a.a) * w };
    };
    const slot = (i) => (i < DRUM_TOWER ? { y: yTop - i * d, z: 0, a: 0 } : along((i - DRUM_TOWER) * d));
    // Tower walls and the drum: shell, end plates and hub.
    const w = d + 1, towerBottom = yc + Rs + 0.5 * d, towerTop = yTop + 0.6 * d, H = towerTop - towerBottom;
    magazine.push(
      boxAt(Lx + 2 * WALL, H, WALL, xm, (towerTop + towerBottom) / 2, w / 2 + WALL / 2),
      boxAt(Lx + 2 * WALL, H, WALL, xm, (towerTop + towerBottom) / 2, -w / 2 - WALL / 2),
      boxAt(WALL, H, w, xm + Lx / 2 + WALL / 2, (towerTop + towerBottom) / 2, 0),
      boxAt(WALL, H, w, xm - Lx / 2 - WALL / 2, (towerTop + towerBottom) / 2, 0),
    );
    const R = Rs + 0.5 * d + 0.6, x0 = xm - Lx / 2, x1 = xm + Lx / 2;
    magazine.push(
      [lathe(tubeProfile(R, R + 1.6, x0 - 2, x1 + 2), 96), translation(0, yc, 0)],
      [lathe(rodProfile(R + 1.6, x0 - 4, x0 - 2, 0.6), 96), translation(0, yc, 0)],
      [lathe(rodProfile(R + 1.6, x1 + 2, x1 + 4, 0.6), 96), translation(0, yc, 0)],
      [lathe(rodProfile(r0 - 0.5 * d - 0.5, x0 - 2, x1 + 2, 0.6), 48), translation(0, yc, 0)],
    );
    // The rotor's arm, pushing the last round round the spiral.
    const rIn = r0 - 0.5 * d - 0.5, rOut = Rs + 0.5 * d;
    meshes.follower = boxMesh(Lx - 2, rOut - rIn, 3, 0, (rIn + rOut) / 2, 0);
    layout.follower = (n, lift) => {
      const a = n < DRUM_TOWER ? 0 : slot(n).a + 0.5 * d / Math.max(Rs, 1);
      return chain(translation(xm, yc - layout.lowered(lift), 0), rotationX(a));
    };
    layout.rounds = (n, lift) => {
      const out = [], dy = layout.lowered(lift);
      for (let i = 0; i < n; i++) {
        const p = slot(i);
        out.push({ round: true, m: i === 0 ? chain(translation(headX, p.y - dy, 0), rotationZ(g.angle * lift))
          : translation(headX, p.y - dy, p.z) });
      }
      return out;
    };
    layout.drum = { yc, R };
    layout.depth = yTop - (yc - R);
    return { geo: g, furniture, magazine, steel, meshes, cam, layout };
  }

  // Box magazines: the stack's centre line curves forward by the case's taper.
  const taper = Math.max(0, 2 * (ctx.dims.baseR - ctx.dims.shR)) / Math.max(ctx.dims.xs, 1);
  let kappa = taper / d;                     // rad per mm of depth
  const pitch = PITCH[g.type] * d;
  const sigma = (i) => (g.type === "quad_stack" && i > FUNNEL
    ? FUNNEL * PITCH.double_stack * d + (i - FUNNEL) * pitch
    : i * (g.type === "quad_stack" ? PITCH.double_stack * d : pitch));
  const sEnd = sigma(g.capacity) + 0.5 * d + 6;
  kappa = Math.min(kappa, 1.0 / Math.max(sEnd, 1));           // no more than a radian in all
  const P = (s) => (kappa < 1e-7 ? [0, -s, 0]
    : [(1 - Math.cos(kappa * s)) / kappa, -Math.sin(kappa * s) / kappa, kappa * s]);
  const sFunnel = sigma(FUNNEL);
  const inner = (s) => {
    if (g.type === "single_stack") return d + 1;
    if (g.type === "double_stack") return (1 + 2 * STAGGER) * d + 1;
    const k = clamp((s - sFunnel) / d, 0, 1);
    return (1 + 2 * STAGGER) * d * (1 + k * k * (3 - 2 * k)) + 1;
  };
  /** Which side of centre a round sits, counting from the bottom of the stack so the top one alternates. */
  const sideZ = (i, n) => {
    const b = n - 1 - i;
    if (g.type === "single_stack") return 0;
    if (g.type === "quad_stack" && i > FUNNEL) {
      return [-1.3, 0.5, -0.5, 1.3][b % 4] * d;
    }
    return (b % 2 ? 1 : -1) * STAGGER * d;
  };
  // Body: side, front and back walls in short segments along the curve, and the floorplate.
  const s0 = -0.6 * d, segs = 18;
  const at = (s) => { const [px, py, th] = P(s); return { x: xm + px, y: yTop + py, th }; };
  for (let k = 0; k < segs; k++) {
    const sa = s0 + (sEnd - s0) * k / segs, sb = s0 + (sEnd - s0) * (k + 1) / segs;
    const a = at(sa), b = at(sb), w = inner((sa + sb) / 2);
    const edge = (p, off) => [p.x + Math.cos(p.th) * off, p.y + Math.sin(p.th) * off];
    const hl = Lx / 2;
    const side = prism([edge(a, -hl - WALL), edge(a, hl + WALL), edge(b, hl + WALL), edge(b, -hl - WALL)], WALL);
    magazine.push([side, translation(0, 0, w / 2 + WALL / 2)], [side, translation(0, 0, -w / 2 - WALL / 2)]);
    for (const sgn of [1, -1]) {
      magazine.push([prism([edge(a, sgn * hl), edge(a, sgn * (hl + WALL)), edge(b, sgn * (hl + WALL)), edge(b, sgn * hl)], w), translation(0, 0, 0)]);
    }
  }
  const e = at(sEnd);
  magazine.push([box(Lx + 2 * WALL + 4, 3.5, inner(sEnd) + 2 * WALL + 3), chain(translation(e.x, e.y - 1.5, 0), rotationZ(e.th))]);
  // Feed lips: the walls turn in over the top round's rear.
  const lipY = yTop + 0.5 * d + 0.4, lipW = Math.max(0.5, (inner(0) - 0.55 * d) / 2);
  for (const sgn of [1, -1]) magazine.push(boxAt(Lx * 0.45, 1, lipW, xm - Lx * 0.27, lipY, sgn * (inner(0) / 2 - lipW / 2)));

  meshes.follower = boxMesh(Lx - 1.5, 4, (1 + 2 * STAGGER) * d - 0.6, 0, 0, 0);
  layout.follower = (n, lift) => {
    const p = at(n > 0 ? sigma(n - 1) + 0.5 * d + 2 : -0.5 * d + 2);
    return chain(translation(p.x, p.y - layout.lowered(lift), 0), rotationZ(p.th));
  };
  layout.rounds = (n, lift) => {
    const out = [], dy = layout.lowered(lift);
    for (let i = 0; i < n; i++) {
      const z = sideZ(i, n);
      if (i === 0) { out.push({ round: true, m: chain(translation(headX, yTop - dy, z), rotationZ(g.angle * lift)) }); continue; }
      const p = at(sigma(i));
      out.push({ round: true, m: chain(translation(p.x, p.y - dy, z), rotationZ(p.th), translation(-oal / 2, 0, 0)) });
    }
    return out;
  };
  layout.width = inner(0) + 2 * WALL;
  layout.depth = yTop - e.y;
  return { geo: g, furniture, magazine, steel, meshes, cam, layout };
}

/** A box mesh centred at (x, y, z). */
function boxMesh(sx, sy, sz, x, y, z) {
  const b = box(sx, sy, sz);
  const p = b.positions;
  for (let i = 0; i < p.length; i += 3) { p[i] += x; p[i + 1] += y; p[i + 2] += z; }
  return b;
}

/** The belt, its tray and box, the top cover, and the feed lever, slide and cam that draw it. */
function buildBelt(gun, ctx, g, o) {
  const { headX, xm, furniture, steel, meshes, cam, layout, f } = o;
  const { d, oal } = g;
  const pitch = LINK_PITCH * d, yB = g.drop, Rb = 1.5 * d;
  const trayLen = ctx.recR + 2 * pitch;
  const boxTop = ctx.lowest - 20, boxH = 70;
  const straight = Math.max(yB - Rb - boxTop, 0);
  /** A point on the belt (y, z), u mm along it from the feed position towards the box. */
  const along = (u) => {
    if (u <= trayLen) return [yB, -u];
    const arc = Rb * Math.PI / 2;
    if (u <= trayLen + arc) { const a = (u - trayLen) / Rb; return [yB - Rb + Rb * Math.cos(a), -trayLen - Rb * Math.sin(a)]; }
    return [yB - Rb - (u - trayLen - arc), -trayLen - Rb];
  };
  const visible = trayLen + Rb * Math.PI / 2 + straight + 2;

  // Tray under the rounds (open over the bolt at the feed position), the cover over them, and the box.
  const trayY = yB - d / 2 - 1.2, trayFrom = -0.6 * pitch, trayTo = -trayLen;
  steel.push(boxAt(oal, 1.5, trayFrom - trayTo, xm, trayY, (trayFrom + trayTo) / 2));
  steel.push(boxAt(oal * 0.3, 3, trayFrom - trayTo, xm + oal * 0.3, trayY + 1.5, (trayFrom + trayTo) / 2));   // cartridge guide
  const coverY = yB + d / 2 + 4, coverFrom = 2 * pitch, coverTo = -trayLen - 2;
  furniture.push(boxAt(oal + 26, 3, coverFrom - coverTo, xm - 6, coverY, (coverFrom + coverTo) / 2));
  const boxZ = -trayLen - Rb;
  furniture.push(
    boxAt(oal + 16, 2, 4.5 * d, xm, boxTop - 1, boxZ + 0),
    boxAt(oal + 16, boxH, 1.5, xm, boxTop - boxH / 2, boxZ + 2.25 * d),
    boxAt(oal + 16, boxH, 1.5, xm, boxTop - boxH / 2, boxZ - 2.25 * d),
    boxAt(1.5, boxH, 4.5 * d, xm + oal / 2 + 8, boxTop - boxH / 2, boxZ),
    boxAt(1.5, boxH, 4.5 * d, xm - oal / 2 - 8, boxTop - boxH / 2, boxZ),
    boxAt(oal + 16, 1.5, 4.5 * d, xm, boxTop - boxH, boxZ),
  );

  // A link: two clips round the case body and a loop out to the next one.
  const r = ctx.dims.baseR, x1 = 0.2 * oal, x2 = 0.45 * oal;
  meshes.link = mergeLocal([
    lathe(tubeProfile(r + 0.05, r + 0.6, x1, x1 + 3), 32),
    lathe(tubeProfile(r * 0.95, r * 0.95 + 0.55, x2, x2 + 3), 32),
    boxMesh(x2 + 3 - x1, 0.6, pitch - 2 * r + 1.5, (x1 + x2 + 3) / 2, -r * 0.3, -(pitch / 2)),
  ]);

  // Feed slide and pawl (moves +z as the cam draws the belt), and the lever that drives it.
  const slideX = xm + 0.15 * oal, ySlide = yB + d / 2 + 1.6;
  meshes.feedSlide = mergeLocal([
    boxMesh(16, 1.4, 3 * pitch, slideX, ySlide, -pitch),
    boxMesh(10, 0.55 * d, 1.6, slideX, ySlide - 0.3 * d, -1.5 * pitch),
  ]);
  const studX = headX - 8, xp = studX + 0.4 * (slideX - studX), armF = slideX - xp;
  const camTop = ctx.camTop;
  meshes.feedLever = mergeLocal([
    boxMesh(slideX - studX, 1.6, 3.5, (studX + slideX) / 2 - xp, 0, 0),
    boxMesh(2.4, ySlide - camTop - 0.5, 2.4, studX - xp, -(ySlide - camTop - 0.5) / 2, 0),
    moved(lathe(rodProfile(2.2, -2.5, 1.5), 24), rotationZ(Math.PI / 2)),     // pivot pin, upright
  ]);
  const strokeMM = ctx.stroke;
  const cs = (f.belt_cam_start != null ? f.belt_cam_start * MM : 0.2 * strokeMM);
  const ce = Math.min(cs + (f.belt_cam != null ? f.belt_cam * MM : 0.35 * strokeMM), 0.95 * strokeMM);
  const lever = (frac) => -Math.asin(clamp(frac * pitch / armF, -0.95, 0.95));
  const zEnd = (xp - studX) * Math.sin(lever(1));
  // The groove on the bolt group the stud rides in (bolt group's own coordinates: travel c puts the
  // stud over x = studX + c): straight, a slant over the cam's travel, straight again.
  const end = Math.min(studX + strokeMM + 4, ctx.groupFront - 2), yRail = camTop + 1.2;
  const segsXZ = [[studX - 4, 0, studX + cs, 0], [studX + cs, 0, studX + ce, zEnd], [studX + ce, zEnd, Math.max(end, studX + ce + 2), zEnd]];
  for (const [ax, az, bx, bz] of segsXZ) {
    const len = Math.hypot(bx - ax, bz - az) || 1, nx = -(bz - az) / len, nz = (bx - ax) / len;
    for (const sgn of [1, -1]) cam.push(railXZ(ax + sgn * nx * 2.2, az + sgn * nz * 2.2, bx + sgn * nx * 2.2, bz + sgn * nz * 2.2, yRail, 2.4, 1.2));
  }

  Object.assign(layout, {
    pitch, cam: [cs, ce], drop: yB,
    camFrac: (travel) => clamp((travel - cs) / Math.max(ce - cs, 1e-6), 0, 1),
    slide: (frac) => translation(0, 0, frac * pitch),
    lever: (frac) => chain(translation(xp, ySlide, 0), rotationY(lever(frac))),
    lowered: () => 0,
    /** Links from the empty one at the feed position (k = -1) along the belt, and the n rounds in them. */
    rounds: (n, lift, adv) => {
      const out = [];
      for (let k = -1; k < n; k++) {
        const u = (k + 1 - adv) * pitch;
        if (u > visible) break;
        const [y, z] = along(u);
        const tilt = k === 0 && adv >= 1 ? g.angle : 0;
        out.push({ round: k >= 0, link: true, m: chain(translation(headX, y, z), rotationZ(tilt)) });
      }
      return out;
    },
    ejectLink: () => [headX, yB, pitch],
  });
  layout.depth = 0;
}

/** Mesh data under a rigid transform. */
function moved(mesh, m) {
  const p = mesh.positions, n = mesh.normals;
  const positions = new Float32Array(p.length), normals = new Float32Array(n.length);
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i], y = p[i + 1], z = p[i + 2], a = n[i], b = n[i + 1], c = n[i + 2];
    for (let k = 0; k < 3; k++) {
      positions[i + k] = m[k] * x + m[4 + k] * y + m[8 + k] * z + m[12 + k];
      normals[i + k] = m[k] * a + m[4 + k] * b + m[8 + k] * c;
    }
  }
  return { positions, normals, indices: mesh.indices };
}

/** Merge bare meshes (no transforms). */
function mergeLocal(meshes) {
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
