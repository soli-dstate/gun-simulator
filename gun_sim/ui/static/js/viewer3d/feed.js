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
//   the left, hanging down to the ground and lying along it (the range swings
//   it as a chain). A cam groove on top of the bolt group swings a feed lever in
//   the hinged top cover, whose front end slides the feed pawl across, drawing
//   the belt one link per cycle; empty links fall out to the right. A chain
//   gun's feeder is driven off its chain, so its bolt group carries no cam. A
//   dual feed has a belt coming in from each side; the selected one feeds, and
//   the other waits a link out from the feed position.
// * Hand: a loader's ready rack, the rounds lying side by side in rows, noses
//   forwards, beside and behind the breech. It is fixed in the turret, so it
//   doesn't recoil with the gun.
//
// The feed ramp runs from the chamber's edge back towards the magazine (from
// the top, for a belt). Units are mm, in the gun's frame (gun.js).

import { lathe } from "./lathe.js";
import { chain, rotationX, rotationY, rotationZ, translation } from "./mat4.js";
import { box, prism, rodProfile, tubeProfile } from "./shapes.js";

const MM = 1e3;
export const CAPACITY = { single_stack: 10, double_stack: 30, quad_stack: 60, drum: 75, belt: 100, dual_belt: 100, hand: 15 };
const RACK_ROW = 8;         // rounds side by side in each row of a ready rack
// As gun_sim/feed.py.
const PITCH = { single_stack: 1.0, double_stack: 0.6, quad_stack: 0.3, drum: 1.0 };
const STAGGER = 0.4, FUNNEL = 4, DRUM_TOWER = 4, LINK_PITCH = 1.2;
const PRESENT = 0.2, BELT_RAISE = 0.5, RAMP_FRICTION = 0.3;
const WALL = 1.0;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Where the next round is presented and the feed angle (mm, rad), as feed.py geometry(). */
export function feedGeometry(gun, dims) {
  const f = gun.feed ?? {}, type = f.type ?? "double_stack", belt = type === "belt" || type === "dual_belt";
  const hand = type === "hand";
  const d = 2 * dims.rimR, oal = Math.max(gun.case.overall_length * MM, dims.length);
  const boltR = Math.max(dims.rimR + 2.2, dims.baseR * 1.3);
  const sign = belt ? -1 : 1;
  const present = belt || hand ? 0 : PRESENT * d;
  let under = boltR + d / 2, drop;
  if (belt) { drop = under = under + BELT_RAISE * d; } else if (hand) { drop = under = 0; } else { drop = -(under - present); under = -under; }
  const angle = f.feed_angle != null ? sign * f.feed_angle * Math.PI / 180 : Math.asin(Math.min(-drop / oal, 0.9));
  return {
    type, belt, hand, dual: type === "dual_belt", sign, d, oal, present, drop, under, angle,
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
 * groupFront (bolt group's front, local x)}.
 * Returns {geo, furniture: [parts], magazine: [parts] (its body), steel: [parts], meshes: {name: mesh}, cam: [parts] (onto the
 * bolt group), layout} where layout places a magazine's rounds: rounds(n, lift) -> [{m, round}]; a belt's
 * links are placed by point(u) along it (the range hangs the rest as a chain).
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
  if (g.hand) {
    buildRack(ctx, g, { meshes, layout });
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

/**
 * The belt's tray, the hinged top cover, and the feed lever, slide and cam that draw it. The
 * belt itself is a hanging chain the range simulates (range.js): the links in the tray are held
 * there, the rest hangs `belt_hang` from the tray's edge and lies on the ground beyond.
 */
function buildBelt(gun, ctx, g, o) {
  const { headX, xm, steel, meshes, cam, layout, f } = o;
  const { d, oal } = g;
  const pitch = LINK_PITCH * d, yB = g.drop;
  const trayLen = ctx.recR + 2 * pitch;
  // The belt comes in from the left (-z); a dual feed has a second from the right, and feeds from the
  // selected one. fs is the feeding belt's side.
  const sides = g.dual ? [-1, 1] : [-1], fs = g.dual && f.select === "right" ? 1 : -1;
  /** Where the link u mm along the belt from the feed position lies, on side `side`: in the tray, or beyond its edge (rising, held up to it). */
  const point = (u, side = fs) => (u <= trayLen ? [headX, yB, side * u] : [headX, yB + 0.35 * (u - trayLen), side * u]);

  // Trays under the rounds (open over the bolt at the feed position) and the cover over them,
  // hinged at its front to swing up for a new belt.
  const trayY = yB - d / 2 - 1.2, trayFrom = 0.6 * pitch;
  for (const s of sides) {
    const zc = s * (trayFrom + trayLen) / 2, w = trayLen - trayFrom;
    steel.push(boxAt(oal, 1.5, w, xm, trayY, zc));
    steel.push(boxAt(oal * 0.3, 3, w, xm + oal * 0.3, trayY + 1.5, zc));   // cartridge guide
  }
  const coverY = yB + d / 2 + 4, coverLen = oal + 26;
  const coverFrom = g.dual ? trayLen + 2 : 2 * pitch, coverTo = -trayLen - 2;
  meshes.cover = boxMesh(coverLen, 3, coverFrom - coverTo, xm - 6, coverY, (coverFrom + coverTo) / 2);
  const hingeX = xm - 6 + coverLen / 2, hingeY = coverY + 1.5;

  // The ground the rest of the belt lies on, belt_hang below the tray, beside the gun (both sides for a dual feed).
  const hang = (f.belt_hang ?? 0.25) * MM, floor = yB - hang - d / 2;
  const far = trayLen + g.capacity * pitch + 60;
  meshes.ground = g.dual ? boxMesh(oal + 80, 6, 2 * far, xm, floor - 3, 0)
    : boxMesh(oal + 80, 6, far - trayLen, xm, floor - 3, -(trayLen + far) / 2);

  // A link: two clips round the case body and a loop out to the next one.
  const r = ctx.dims.baseR, x1 = 0.2 * oal, x2 = 0.45 * oal;
  meshes.link = mergeLocal([
    lathe(tubeProfile(r + 0.05, r + 0.6, x1, x1 + 3), 32),
    lathe(tubeProfile(r * 0.95, r * 0.95 + 0.55, x2, x2 + 3), 32),
    boxMesh(x2 + 3 - x1, 0.6, pitch - 2 * r + 1.5, (x1 + x2 + 3) / 2, -r * 0.3, -(pitch / 2)),
  ]);

  // Feed slide and pawl (moves towards the middle as the cam draws the belt), and the lever that drives it.
  const slideX = xm + 0.15 * oal, ySlide = yB + d / 2 + 1.6;
  meshes.feedSlide = mergeLocal([
    boxMesh(16, 1.4, 3 * pitch, slideX, ySlide, fs * pitch),
    boxMesh(10, 0.55 * d, 1.6, slideX, ySlide - 0.3 * d, fs * 1.5 * pitch),
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
  const lever = (frac) => fs * Math.asin(clamp(frac * pitch / armF, -0.95, 0.95));
  const zEnd = (xp - studX) * Math.sin(lever(1));
  // The groove on the bolt group the stud rides in (bolt group's own coordinates: travel c puts the
  // stud over x = studX + c): straight, a slant over the cam's travel, straight again.
  if (!ctx.chainDriven) {
    const end = Math.min(studX + strokeMM + 4, ctx.groupFront - 2), yRail = camTop + 1.2;
    const segsXZ = [[studX - 4, 0, studX + cs, 0], [studX + cs, 0, studX + ce, zEnd], [studX + ce, zEnd, Math.max(end, studX + ce + 2), zEnd]];
    for (const [ax, az, bx, bz] of segsXZ) {
      const len = Math.hypot(bx - ax, bz - az) || 1, nx = -(bz - az) / len, nz = (bx - ax) / len;
      for (const sgn of [1, -1]) cam.push(railXZ(ax + sgn * nx * 2.2, az + sgn * nz * 2.2, bx + sgn * nx * 2.2, bz + sgn * nz * 2.2, yRail, 2.4, 1.2));
    }
  }

  Object.assign(layout, {
    pitch, cam: [cs, ce], drop: yB, trayLen, point, floor, rest: floor + d / 2, sides, feedSide: fs,
    camFrac: (travel) => clamp((travel - cs) / Math.max(ce - cs, 1e-6), 0, 1),
    slide: (frac) => translation(0, 0, -fs * frac * pitch),
    lever: (frac) => chain(translation(xp, ySlide, 0), rotationY(lever(frac))),
    /** The top cover (and the feed lever and slide in it) swung up `angle` rad about its front hinge. */
    coverAt: (angle) => chain(translation(hingeX, hingeY, 0), rotationZ(-angle), translation(-hingeX, -hingeY, 0)),
    lowered: () => 0,
    ejectLink: () => [headX, yB, -fs * pitch],
  });
  layout.depth = 0;
}

/**
 * A loader's ready rack: rows of RACK_ROW rounds side by side, noses forwards, heads at ctx.rack.x,
 * the first row's first round at (ctx.rack.y, ctx.rack.z) and the rest going on to the left and down.
 * The loader takes them from the first slot on, so with n left they are in the last n slots. The
 * rack is fixed (it doesn't recoil): its matrices are in the world's frame.
 */
function buildRack(ctx, g, o) {
  const { meshes, layout } = o, { d, oal } = g, at = ctx.rack, gap = 1.15 * d;
  const rows = Math.ceil(g.capacity / RACK_ROW), across = Math.min(g.capacity, RACK_ROW);
  const slot = (i) => translation(at.x, at.y - Math.floor(i / RACK_ROW) * gap, at.z - (i % RACK_ROW) * gap);
  // A shelf under each row, and a stop the noses bear against.
  const parts = [];
  const zc = at.z - (across - 1) * gap / 2, wz = across * gap + 10;
  for (let r = 0; r < rows; r++) {
    const y = at.y - r * gap - d / 2 - 3;
    parts.push(boxMesh(0.25 * oal, 4, wz, at.x + 0.2 * oal, y, zc), boxMesh(0.25 * oal, 4, wz, at.x + 0.75 * oal, y, zc));
  }
  parts.push(boxMesh(6, rows * gap + 10, wz, at.x + oal + 8, at.y - (rows - 1) * gap / 2, zc));
  meshes.rack = mergeLocal(parts);
  Object.assign(layout, {
    rackStatic: true, slot,
    rounds: (n) => Array.from({ length: Math.max(0, Math.min(n, g.capacity)) }, (_, k) => ({ round: true, m: slot(g.capacity - n + k) })),
    /** Where the next round is taken from, with n left. */
    next: (n) => slot(Math.max(g.capacity - n, 0)),
    lowered: () => 0,
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
