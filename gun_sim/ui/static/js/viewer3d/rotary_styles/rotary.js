// The plain rotary style: a round housing round the rotor with windows at the feeder and the ejection port,
// a carrier channel feeding the rounds in from below on the left, and a simple pedestal. Barrels, bolts and
// the rotor are rotary.js's.

import { boxAt, rodY } from "../meshops.js";
import { axisRod, axisShell, chuteFrame } from "../rotary_kit.js";

export function build(gun, geo) {
  const ri = geo.rollerR + 3, ro = ri + 4;
  const x0 = geo.rotorRear - 8, x1 = geo.rearX + geo.plateT + 8;
  const steel = [
    ...axisShell(geo, ri, ro, x0, x1, [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.45 }]),
    axisRod(geo, ro, x0 - 8, x0),
  ];
  // The feed: out of the feeder window along its radius, then off to the left.
  const [fx, fy, fz] = geo.feedPoint, [dy, dz] = geo.feedDir;
  const mid = [fx, fy + dy * 90, fz + dz * 90];
  const feedPath = [[fx, mid[1] - 20, mid[2] - 260], [fx, mid[1], mid[2]], [fx, fy, fz]];
  const pivot = [x0 + 0.4 * (x1 - x0), geo.axisY - ro - 30];
  const floor = geo.axisY - 700;
  return {
    steel,
    paint: [],
    furniture: chuteFrame(geo, feedPath),
    feedPath,
    mount: [boxAt(0.5 * (x1 - x0), 24, 2 * ro + 40, pivot[0], pivot[1], 0)],
    pedestal: [rodY(18, floor + 8, pivot[1], pivot[0]), boxAt(240, 8, 240, pivot[0], floor + 4, 0)],
    layout: { recR: ro + 20, buttX: x0 - 16, boltRear: x0, pivot, cgX: pivot[0],
              camera: { x: (x0 + geo.d.length) / 2, y: geo.axisY, width: Math.max(8 * ro, x1 - x0 + 200) } },
  };
}
