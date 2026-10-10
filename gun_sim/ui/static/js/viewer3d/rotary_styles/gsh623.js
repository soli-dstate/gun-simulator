// The GSh-6-23: six short barrels in a squat, stout housing, driven by the gas of its own barrels. Each barrel
// has a gas cylinder beside it, riding with it in the rotor frame, from its gas port back to the rotor plate. A
// pyrotechnic starter holder sits on top of the front collar; the belt comes in from the left, to the feeder at the
// bottom. The mount is a cradle on trunnions, on a field pedestal.

import { lathe } from "../lathe.js";
import { translation } from "../mat4.js";
import { boxAt, merge, pinZ, rodY } from "../meshops.js";
import { axisRod, axisShell, chuteFrame, stationMatrix, tubeX } from "../rotary_kit.js";
import { rodProfile } from "../shapes.js";

const TWO_PI = 2 * Math.PI;

/** A row of small links along each leg of a belt path (axis-aligned legs), spaced `pitch` apart. Parts. */
function beltLinks(path, pitch, cross = 10) {
  const parts = [];
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    const n = Math.max(1, Math.floor(len / pitch));
    const axis = [0, 1, 2].find((j) => Math.abs(b[j] - a[j]) > 1e-6);
    if (axis === undefined) continue;
    const size = [cross, cross, cross];
    size[axis] = 0.7 * pitch;
    for (let j = 0; j < n; j++) {
      const f = (j + 0.5) / n;
      const p = [0, 1, 2].map((q) => a[q] + (b[q] - a[q]) * f);
      parts.push(boxAt(size[0], size[1], size[2], p[0], p[1], p[2]));
    }
  }
  return parts;
}

export function build(gun, geo) {
  const R = geo.R, K = geo.K;
  const x0 = geo.rotorRear - 8;                 // rear of the housing
  const x1 = geo.rearX + geo.plateT + 8;        // front of the housing (the barrel plate's front)
  const collarX = -40;                          // where the front bearing collar begins
  const ri = geo.rollerR + 3;                   // inside radius: clears the rollers
  const ro = ri + 15;                           // main housing outside radius
  const roC = ri + 30;                          // front bearing collar outside radius
  const windows = [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.45 }];

  // ---- housing (painted) ----
  const paint = [
    ...axisShell(geo, ri, ro, x0, collarX, windows),
    ...axisShell(geo, ri, roC, collarX, x1, windows),
    axisRod(geo, ro + 4, x0 - 30, x0),           // rear cover
  ];

  // ---- starter cartridge holder on top of the front collar: a fat cylinder of squib chambers ----
  const yS = geo.axisY + roC + 22;
  const steel = [
    [lathe(rodProfile(24, -20, 30), 48), translation(0, yS, 0)],
  ];
  for (let k = 0; k < 6; k++) {
    const a = (k * TWO_PI) / 6;
    steel.push([lathe(rodProfile(3.5, -20, 36, 1), 12), translation(0, yS + 24 * Math.cos(a), 24 * Math.sin(a))]);
  }
  // The short feed-in box on the gun's left side, joining the holder to the collar.
  steel.push(boxAt(44, 34, 30, 0, geo.axisY + roC + 16, -34));

  // ---- gas cylinders: one per barrel, in the barrel's local frame (axis = x, +y outward, +z tangential) ----
  const gasX = geo.seat + 550;                  // the gas port, 0.55 m from the seat
  const zt = geo.breechR + 8;                   // the cylinder's offset from the barrel axis
  const rg = geo.barrelR(gasX);
  const pistonLocal = merge(
    tubeX(0, 7, geo.rearX + geo.plateT, gasX, 0, zt, 16),          // the cylinder, back to the rotor plate
    boxAt(28, 20, zt - rg + 6, gasX, 0, (rg + zt) / 2),           // the gas block where it meets the barrel
  );
  const rotorSteel = [];
  for (let k = 0; k < K; k++) rotorSteel.push([pistonLocal, stationMatrix(geo, k)]);

  // ---- barrel clamps: solid discs about the rotor's axis, enclosing the barrels (rotor frame) ----
  for (const [a, b] of [[440, 470], [930, 960]]) {
    const Ro = R + geo.barrelR((a + b) / 2) + 5;
    rotorSteel.push(lathe(rodProfile(Ro, a, b), 64));
  }

  // ---- belt feed: from the left at the bottom, to the feeder ----
  const [fx, fy, fz] = geo.feedPoint;
  const feedPath = [[fx, -230, -250], [fx, -230, fz], [fx, fy, fz]];
  const furniture = [...chuteFrame(geo, feedPath), ...beltLinks(feedPath, geo.linkPitch)];

  // ---- mount: a cradle with side plates and trunnions (pitches with the gun) ----
  const pivotX = (x0 + x1) / 2, pivotY = geo.axisY;
  const zP = roC + 14, cx = (x0 + x1) / 2, cLen = x1 - x0;
  const mount = [
    boxAt(cLen, 2 * (roC + 10), 14, cx, pivotY, zP),
    boxAt(cLen, 2 * (roC + 10), 14, cx, pivotY, -zP),
    pinZ(12, zP + 22, pivotX, pivotY),
  ];

  // ---- pedestal: two posts and a base, the ground ~700 mm below the rotor axis ----
  const floor = geo.axisY - 700, bearZ = roC + 34;
  const pedestal = [
    rodY(18, floor + 8, pivotY, pivotX, -bearZ),
    rodY(18, floor + 8, pivotY, pivotX, bearZ),
    boxAt(50, 40, 20, pivotX, pivotY, -bearZ),
    boxAt(50, 40, 20, pivotX, pivotY, bearZ),
    boxAt(340, 16, 2 * bearZ + 40, pivotX, floor + 8, 0),
  ];

  return {
    steel,
    paint,
    furniture,
    rotorSteel,
    mount,
    pedestal,
    feedPath,
    returnPath: null,
    layout: {
      recR: R + roC + 12,
      buttX: x0 - 30,
      boltRear: x0,
      pivot: [pivotX, pivotY],
      cgX: pivotX,
      camera: { x: -120, y: -60, width: 640 },
    },
  };
}
