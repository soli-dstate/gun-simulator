// The Mauser BK-27 revolver cannon: one fixed 27 mm barrel on the bore line, a five-chamber drum behind it,
// a squarish receiver round the drum with a belt feed from the right and the ejection port on the lower left,
// a gas cylinder under the barrel running back to the receiver, a barrel shroud, an electric solenoid on the
// rear, and a trunnion cradle on a field pedestal. The barrel, drum, bolts and rounds are rotary.js's.

import { boxAt, pinZ, rodX, rodY } from "../meshops.js";
import { axisShell, chuteFrame, pathLength, pathPoint, tubeX } from "../rotary_kit.js";

const MM = 1e3;

export function build(gun, geo) {
  const ax = geo.axisY;                       // rotor axis height (-R)
  const ri = geo.rollerR + 3, ro = ri + 8;    // housing ring: clears the rolling bolts
  const x0 = geo.rotorRear - 8, x1 = geo.barrelX0 + 40;
  const L = x1 - x0, xc = (x0 + x1) / 2;      // receiver length and centre; the trunnions sit at xc
  const [fx, fy, fz] = geo.feedPoint;

  // Receiver: the lower half is a ring with windows at the feeder (bottom right) and the ejection port
  // (lower left); the roof, side walls and front and rear plates close it up squarely.
  const steel = [
    ...axisShell(geo, ri, ro, x0, x1, [
      { theta: 0, half: Math.PI / 2 },                      // no ring above the axis: the roof and sides are boxes
      { theta: geo.ang.feed, half: 0.5 },
      { theta: geo.ang.eject, half: 0.45 },
    ]),
    boxAt(L, 8, 190, xc, 40, 0),                           // roof, underside clear of the rollers
    boxAt(L, 85.9, 10, xc, (ax + 40) / 2, 95),             // right side wall, from the axis up
    boxAt(L, 85.9, 10, xc, (ax + 40) / 2, -95),            // left side wall
    boxAt(6, 180, 200, x1 - 3, ax - 0.1, 0),               // front plate (the barrel passes through it)
    boxAt(8, 180, 200, x0 + 4, ax - 0.1, 0),               // rear plate, against the rotor's rear face
    // Muzzle device: a thick sleeve with a ring at each end, clear of the barrel.
    tubeX(26, 34, geo.muzzleX - 100, geo.muzzleX - 10, 0, 0, 48),
    tubeX(26, 40, geo.muzzleX - 100, geo.muzzleX - 88, 0, 0, 48),
    tubeX(26, 40, geo.muzzleX - 12, geo.muzzleX, 0, 0, 48),
    // Feed tray under the feeder window, which the belt passes through.
    boxAt(240, 8, 60, -130, ax - 95, 30),
  ];

  // Barrel shroud for the first 250 mm ahead of the receiver: inside radius clears the barrel's taper.
  const paint = [tubeX(41, 46, x1, x1 + 250, 0, 0, 48)];

  // Gas cylinder under the barrel, from the receiver front to the gas port, with its block on the barrel.
  const gasX = geo.seat + (gun.action?.gas_port_position ?? 1.2) * MM;
  paint.push(tubeX(12, 18, x1, gasX, ax + 0, 0, 32));   // axis at y = -45, the cylinder's bore line
  paint.push(boxAt(40, 40, 40, gasX, -36, 0));           // gas block on the barrel at the port
  const bright = [rodX(6, x1, gasX + 20, ax, 0, 24)];    // slide rod, from the receiver front

  // Belt feed from the right: out of the feeder window, down and across to the right side of the gun.
  const feedPath = [[fx, -200, 260], [fx, -200, fz], [fx, fy, fz]];
  const links = [];
  const plen = pathLength(feedPath);
  for (let s = 30; s < plen; s += 60) {
    const p = pathPoint(feedPath, s);
    links.push(boxAt(40, 14, 26, p[0], p[1] + geo.rimR + 8, p[2]));
  }
  const furniture = [
    ...chuteFrame(geo, feedPath),
    ...links,
    // Electric solenoid on the rear of the receiver, with a short cable.
    boxAt(50, 60, 60, x0 - 25, -20, 0),
    rodX(4, x0 - 70, x0 - 25, -20, 25),
  ];

  // Mount: a cradle with trunnion blocks and a pin on the receiver's sides, and two recoil adapters beside it.
  const xp = xc;
  const mount = [pinZ(12, 125, xp, ax)];
  for (const s of [-1, 1]) {
    mount.push(boxAt(60, 40, 30, xp, ax, 115 * s));          // trunnion block
    mount.push(rodX(12, -340, -200, ax, 115 * s));            // recoil adapter
    mount.push(boxAt(300, 130, 14, xp, ax - 30, 135 * s));   // cradle arm
  }

  // Pedestal: a base on the ground about 700 mm below the rotor axis, and two posts up to the trunnions.
  const floor = ax - 700;
  const pedestal = [
    boxAt(400, 20, 320, xp, floor + 10, 0),
    rodY(18, floor + 20, ax, xp, 150),
    rodY(18, floor + 20, ax, xp, -150),
  ];

  return {
    steel,
    paint,
    furniture,
    bright,
    mount,
    pedestal,
    feedPath,
    layout: {
      recR: 150, buttX: x0 - 70, boltRear: x0, pivot: [xp, ax], cgX: xp,
      camera: { x: (x0 + geo.d.length) / 2, y: ax, width: L + 200 },
    },
  };
}
