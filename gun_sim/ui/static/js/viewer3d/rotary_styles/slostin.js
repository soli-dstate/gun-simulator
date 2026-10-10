// The Slostin (1946): eight barrels round a stationary breech, each barrel with its own gas cylinder
// beside it, a perforated shroud round the rear third of the cluster, a receiver at the back with spade
// grips and a trigger, a charging handle on the right, a belt from the left and a low tripod. The barrels,
// bolts and rotor are rotary.js's; the gas cylinders, the shroud and the clamp are rotor parts.

import { chain, translation } from "../mat4.js";
import { lathe } from "../lathe.js";
import { rodProfile, tubeProfile } from "../shapes.js";
import { boxAt, gripAt, merge, rodX, rodY } from "../meshops.js";
import { axisRod, axisShell, chutePath, chuteFrame, pathLength, pathPoint, segment, stationMatrix, tubeX } from "../rotary_kit.js";

export function build(gun, geo) {
  // ---- stationary housing round the rotor's rear, with the feed and ejection windows ----
  const ri = geo.rollerR + 3, ro = ri + 5;
  const x0 = geo.rotorRear - 8, x1 = geo.rearX + geo.plateT + 8;
  const [fx, fy, fz] = geo.feedPoint;

  // The belt: from the left (out at z = -240), along to the feeder's window, then up into it.
  const feedPath = [[fx, -150, -240], [fx, -150, fz], [fx, fy, fz]];
  const beltLen = pathLength(feedPath);

  const steel = [
    ...axisShell(geo, ri, ro, x0, x1, [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.45 }]),
    // The charging handle on the right side of the receiver: a rod with a knob at its rear end.
    rodX(3.5, -185, -120, geo.axisY, 66, 16),
    boxAt(16, 16, 16, -190, geo.axisY, 66),
  ];

  // ---- rotor parts: a gas cylinder beside each barrel, the perforated shroud, a clamp near the muzzle ----
  // Built for the top station (barrel on the x axis, +y outward), then placed on every station.
  const gas = merge(
    tubeX(2.6, 3.6, 26, 150, 17, 0, 16),          // the cylinder
    tubeX(0, 4.5, 146, 150, 17, 0, 16),           // its rear cap
    tubeX(0, 1.2, 4, 26, 17, 0, 12),              // the piston rod, running back toward the rotor
    boxAt(8, 9, 8, 26, 14, 0),                    // the gas block joining the cylinder to the barrel
  );
  const rotorSteel = [];
  for (let k = 0; k < geo.K; k++) rotorSteel.push([gas, stationMatrix(geo, k)]);
  // The muzzle clamp: a solid disc round the cluster just behind the muzzle.
  rotorSteel.push(lathe(rodProfile(geo.R + geo.barrelR(562) + 3, 555, 570), 64));

  // The shroud over the rear third of the barrels, inside which the cylinders sit; bands stand out of it.
  const Ri = geo.R + 22, Ro = Ri + 4;
  const rotorPaint = [lathe(tubeProfile(Ri, Ro, 24, 204), 64)];
  for (const x of [30, 70, 110, 150, 190]) rotorPaint.push(lathe(tubeProfile(Ri - 1, Ro + 2, x, x + 5), 64));

  // ---- the receiver at the back: a rear cap, spade grips and a trigger between them ----
  const paint = [
    axisRod(geo, 56, -190, x0 + 2),                // the rear receiver
    boxAt(70, 60, 60, fx, -180, -265),             // the ammunition box on the left, hanging off the belt's far end
  ];
  const furniture = [
    boxAt(26, 12, 96, -190, -58, 0),               // the spade grips' top bar
    [gripAt(-185, -62, 48, 22, 0.2, 14), translation(0, 0, 40)],
    [gripAt(-185, -62, 48, 22, 0.2, 14), translation(0, 0, -40)],
    gripAt(-172, -66, 24, 8, 0.3, 6),              // the trigger
    ...chuteFrame(geo, feedPath),
    ...chutePath(3, 2 * geo.rimR + 6, feedPath),
  ];
  // The belt's link boxes along the feed, above the carrier.
  for (let s = 20; s < beltLen; s += 40) {
    const p = pathPoint(feedPath, s);
    furniture.push(boxAt(10, 6, 9, p[0], p[1] + 12, p[2]));
  }

  // ---- a low infantry tripod: a head under the housing's cradle, three legs to the ground ----
  const pivot = [-40, -110];
  const head = [-40, -140, 0];
  const floor = geo.axisY - 450;
  const feet = [[-200, floor, -190], [-200, floor, 190], [140, floor, 0]];
  const pedestal = [
    boxAt(36, 14, 36, head[0], head[1] + 2, head[2]),          // the head
    rodY(7, -132, -112, -40, 0),                                // the pintle the cradle turns on
    ...feet.map((g) => segment(7, head, g)),                    // the legs
    ...feet.map((g) => boxAt(60, 12, 60, g[0], floor + 6, g[2])), // the foot pads
  ];
  const mount = [boxAt(60, 22, 44, pivot[0], -102, 0)];         // the cradle under the housing

  return {
    steel,
    paint,
    furniture,
    rotorSteel,
    rotorPaint,
    mount,
    pedestal,
    feedPath,
    returnPath: null,
    layout: { recR: ro + 22, buttX: -206, boltRear: x0, pivot, cgX: -40,
              camera: { x: -60, y: -50, width: 440 } },
  };
}
