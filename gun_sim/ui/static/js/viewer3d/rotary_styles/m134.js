// The M134 Minigun: six slim barrels on a rotor, two rotor clamps round the barrels, a stepped housing with
// feed and ejection windows, an electric motor lying along the right side, a delinking feeder under the
// housing with a flexible belt chute from the left, spade grips at the back, a ring sight on top, and a
// door-gun pintle mount. Barrels, bolts, rotor frame and animation are rotary.js's.

import { lathe } from "../lathe.js";
import { translation } from "../mat4.js";
import { boxAt, pinZ, rodX, rodY } from "../meshops.js";
import { TAU, axisRod, axisShell, axisTube, chuteFrame, chutePath, pathLength, pathPoint, tubeX } from "../rotary_kit.js";
import { rodProfile, torusProfile } from "../shapes.js";

export function build(gun, geo) {
  const xRear = geo.rotorRear - 8;     // rear face of the housing (about -145)
  const xWin = 5;                      // the windowed rear section ends just ahead of the bolts' run
  const xFront = 110;                  // the front section, where the barrels exit, ends here
  const xBearing = 118;                // the front bearing ring

  // ---- housing: a larger rear section (round the bolts, with the feed and ejection windows) and a smaller
  // front section where the barrels run out. The front inside radius clears R + barrelR(x) (about 41 mm at x = 5). ----
  const rearRi = geo.rollerR + 3, rearRo = rearRi + 8;
  const frontRi = 43, frontRo = 49;
  const steel = [
    ...axisShell(geo, rearRi, rearRo, xRear, xWin, [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.45 }]),
    axisTube(geo, frontRi, frontRo, xWin, xFront, 0, TAU, 64),
    axisRod(geo, 60, xRear - 8, xRear),                  // rear cap
  ];
  const bright = [
    axisTube(geo, 42.5, 53, xFront, xBearing, 0, TAU, 64),   // front bearing ring
  ];

  // ---- rotor clamps (in the rotor frame): solid discs round the cluster at 85 % and 45 % of the way to the muzzle ----
  const clampR = (x) => geo.R + geo.barrelR(x) + 4;
  const xF = 0.85 * geo.muzzleX, xM = 0.45 * geo.muzzleX;
  const rotorSteel = [
    lathe(rodProfile(clampR(xF), xF - 13, xF + 13), 64),
    lathe(rodProfile(clampR(xM), xM - 13, xM + 13), 64),
  ];

  // ---- electric motor: a fat rod lying parallel to the bore on the right (+z), with a gear cover at its front
  // end and a small gear box joining it to the housing ----
  const mz = 96, my = geo.axisY;
  const paint = [
    tubeX(0, 38, -140, 60, my, mz, 48),                  // motor body
    tubeX(0, 52, 36, 62, my, mz, 48),                    // gear cover (larger, short, at the front)
    boxAt(24, 18, 22, -152, my, mz),                     // terminal box at the rear end
    boxAt(50, 56, 50, -35, my, 65),                      // gear box joining motor and housing
  ];

  // ---- feed: a delinking feeder box under the feed window, and a flexible belt chute from the left ----
  const [fx, fy, fz] = geo.feedPoint, [dy, dz] = geo.feedDir;
  const mid = [fx, fy + dy * 70, fz + dz * 70];
  const feedPath = [
    [fx, -190, -330],        // outside, on the left and low
    [fx, -190, mid[2]],      // along z, under the housing
    [fx, mid[1], mid[2]],    // up along y
    [fx, fy, fz],            // the last leg radially into the feed window (ends at geo.feedPoint)
  ];
  const feedLen = pathLength(feedPath);
  const links = [];
  for (let s = 0; s <= feedLen; s += 3 * geo.linkPitch) {
    const [x, y, z] = pathPoint(feedPath, s);
    links.push(boxAt(8, 8, 8, x, y, z));                 // belt links in the chute
  }
  const furniture = [
    boxAt(70, 50, 60, -82, -100, 14),                    // delinking feeder box
    boxAt(4, 22, 4, 100, 26, 0),                         // ring sight post on the housing front
    ...chutePath(18, 22, feedPath),
    ...chuteFrame(geo, feedPath),
    // spade grips at the back: a bridge from the rear cap with a trigger pad under it
    boxAt(38, 8, 8, -171, -40, 0),
    boxAt(12, 22, 10, -174, -54, 0),
  ];
  steel.push(...links);
  for (const s of [1, -1]) {
    // the arm from the rear cap out to each side, then a vertical grip
    steel.push(rodX(9, -190, -150, -30, s * 66, 24), rodY(11, -75, -5, -190, s * 66, 24));
  }
  bright.push(torusRing());

  // ---- door-gun pintle: a cradle with two cheeks under the housing (the feed passes between them), a pin
  // through them, and a post down to a round base plate about 600 mm below the rotor axis ----
  const pivotX = -40, pivotY = -125;
  const mount = [];
  for (const s of [1, -1]) mount.push(boxAt(140, 76, 10, pivotX, -88, s * 50));
  mount.push(pinZ(8, 60, pivotX, pivotY));
  const pedestal = [
    rodY(14, -630, pivotY, pivotX, 0, 32),               // pintle post
    rodY(110, -642, -630, pivotX, 0, 48),                // round base plate
  ];

  return {
    steel,
    paint,
    furniture,
    bright,
    rotorSteel,
    mount,
    pedestal,
    feedPath,
    returnPath: null,
    layout: {
      recR: 140,                                         // the motor is the widest part, out to z = 138
      buttX: -201,                                       // the back of the spade grips
      boltRear: xRear,
      pivot: [pivotX, pivotY],
      cgX: pivotX,
      camera: { x: -70, y: geo.axisY, width: 360 },
    },
  };
}

// The ring sight: a thin ring in a plane across the bore, on the housing front (its centre is above the bore).
function torusRing() {
  return [lathe(torusProfile(12, 1.6, 24), 32), translation(100, 36, 0)];
}
