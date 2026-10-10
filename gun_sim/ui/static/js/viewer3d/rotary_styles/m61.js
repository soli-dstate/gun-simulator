// The M61A1 Vulcan: six 20 mm barrels on a rotor in an olive housing, a hydraulic drive motor and gearbox
// beside the breech on the right, a linkless feed chute from the rear into the bottom feeder, a return chute for
// the empty cases, a cradle clamp on trunnions, and an aircraft-style pedestal frame below.

import { lathe, } from "../lathe.js";
import { chain, rotationY, translation } from "../mat4.js";
import { boxAt, rodY } from "../meshops.js";
import { axisRod, axisShell, axisTube, chuteFrame, segment, tubePath } from "../rotary_kit.js";
import { rodProfile, sphereProfile } from "../shapes.js";

// A lathe part built along x (from 0 to its length) turned to run along +z and placed at (x, y, z0).
const zPart = (profile, x, y, z0, seg = 48) => [lathe(profile, seg), chain(translation(x, y, z0), rotationY(-Math.PI / 2))];

// Round carriers along a chute: a spine tube, a ball joint at each vertex, and the channel plates.
const chuteParts = (geo, path) => [
  ...chuteFrame(geo, path),
  ...tubePath(9, path),
  ...path.map((p) => [lathe(sphereProfile(9), 16), translation(...p)]),
];

export function build(gun, geo) {
  const R = geo.R, ax = geo.axisY;
  const ri = geo.rollerR + 3;                 // inner radius clears the rollers
  const xRear = geo.rotorRear - 8;            // rear face of the housing
  const xStep = -150;                         // the rear section (wider) ends here
  const xFront = 50;                          // front of the housing, past the barrel plate
  const roMain = ri + 8, roRear = roMain + 6;
  const windows = [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.5 }];
  const xp = -100;                            // trunnion x (the pivot)
  const zPost = roRear + 62;                  // pedestal posts, outside the trunnion ends
  const floor = ax - 800;

  // The feed: from the rear and the left, above, down and under the housing, then up radially into the feeder.
  const [fx, fy, fz] = geo.feedPoint, [dy, dz] = geo.feedDir;
  const feedPath = [
    [-430, 40, -250],
    [-430, -200, -250],
    [-430, -200, 10],
    [fx, -200, 10],
    [fx, fy + dy * 90, fz + dz * 90],
    [fx, fy, fz],
  ];
  // The return: out radially through the ejection window, back (-x) and down.
  const [ex, ey, ez] = geo.ejectPoint, [ody, odz] = geo.ejectDir;
  const outY = ey + ody * 60, outZ = ez + odz * 60;
  const returnPath = [[ex, ey, ez], [ex, outY, outZ], [-260, outY, outZ], [-260, -300, outZ]];

  // Housing: a rear section, the main body and a closed front bearing collar, with the feed and eject windows.
  const paint = [
    ...axisShell(geo, ri, roRear, xRear, xStep, windows),
    ...axisShell(geo, ri, roMain, xStep, xFront, windows),
    axisTube(geo, ri, roMain + 10, 30, xFront),
  ];

  // Steel: the rear mounting flange, the hydraulic motor, its gearbox and the two hose stubs.
  const mx = -165;
  const steel = [
    axisRod(geo, roRear + 10, xRear - 10, xRear),
    zPart(rodProfile(40, 0, 70, 8), mx, ax, 120),
    zPart(rodProfile(46, 0, 12, 3), mx, ax, 150),
    boxAt(70, 60, 28, mx, ax, 108),
  ];
  const furniture = [
    segment(6, [mx - 25, ax + 30, 190], [mx - 25, ax + 30, 230]),
    segment(6, [mx + 25, ax - 30, 190], [mx + 25, ax - 30, 230]),
    ...chuteParts(geo, feedPath),
    ...chuteParts(geo, returnPath),
  ];

  // Rotor clamps, in the rotor frame: a mid-length clamp at half the barrel length and a heavy muzzle ring.
  const xMid = geo.rearX + 0.5 * (geo.muzzleX - geo.rearX);
  const rotorSteel = [
    lathe(rodProfile(R + geo.barrelR(xMid) + 6, xMid - 20, xMid + 20), 64),
    lathe(rodProfile(R + geo.barrelR(geo.muzzleX - 90) + 14, geo.muzzleX - 92, geo.muzzleX - 2), 64),
  ];

  // Mount: a cradle clamp round the top of the housing, trunnion ears at the sides and the trunnion pins.
  const cradle = axisTube(geo, roRear + 12, roRear + 22, -170, -40, -Math.PI / 3, Math.PI / 3, 64);
  const mount = [
    cradle,
    boxAt(60, 70, 26, xp, ax, roRear + 16),
    boxAt(60, 70, 26, xp, ax, -(roRear + 16)),
    segment(9, [xp, ax, roRear - 10], [xp, ax, zPost]),
    segment(9, [xp, ax, -(roRear - 10)], [xp, ax, -zPost]),
  ];

  // Pedestal: a base and two vertical posts down to 800 mm below the rotor axis.
  const pedestal = [
    rodY(14, floor, ax, xp, zPost),
    rodY(14, floor, ax, xp, -zPost),
    boxAt(320, 16, 2 * zPost + 60, xp, floor + 8, 0),
  ];

  return {
    steel,
    furniture,
    paint,
    rotorSteel,
    mount,
    pedestal,
    feedPath,
    returnPath,
    layout: {
      recR: R + roRear + 20,
      buttX: xRear - 10,
      boltRear: geo.rotorRear,
      pivot: [xp, ax],
      cgX: xp,
      camera: { x: (geo.rotorRear + xFront) / 2, y: ax, width: xFront - geo.rotorRear + 260 },
    },
  };
}
