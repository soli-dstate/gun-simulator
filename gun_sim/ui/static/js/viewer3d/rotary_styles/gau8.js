// The GAU-8/A Avenger: seven 2.3 m barrels in a cluster, clamped at the muzzle and middle, in a round housing
// with two hydraulic motors on its lower sides, a cradle clamp fore and aft, and behind it the big ammunition
// drum (860 mm across, 1.8 m long) on the rotor's axis. The rounds come up a linkless conveyor from the
// drum's lower front; the cases go back to the drum along a return chute. Barrels, bolts and the rotor are
// rotary.js's; the drum, housing and conveyor are dressed here.

import { lathe } from "../lathe.js";
import { boxAt, pinZ, rodX, rodY } from "../meshops.js";
import { rodProfile } from "../shapes.js";
import { axisRod, axisShell, axisTube, chuteFrame, chutePath, pathLength, pathPoint } from "../rotary_kit.js";

export function build(gun, geo) {
  const axisY = geo.axisY;

  // ---- housing: a round receiver round the rotor, clear of the rollers, with the feed and eject windows ----
  const hri = geo.rollerR + 9, hro = hri + 40;
  const hx0 = geo.rotorRear - 8, hx1 = geo.rearX + geo.plateT + 8;
  const steel = [
    ...axisShell(geo, hri, hro, hx0, hx1, [{ theta: geo.ang.feed, half: 0.5 }, { theta: geo.ang.eject, half: 0.45 }]),
  ];

  // ---- hydraulic drive motors on the housing's sides, lower: right (+z) at 240 deg, left (-z) at 150 deg ----
  const rho = hro + 50, motorR = 60;
  const onRing = (deg) => {
    const t = (deg * Math.PI) / 180;
    return [axisY + rho * Math.cos(t), -rho * Math.sin(t)];
  };
  const paint = [];
  for (const deg of [240, 150]) {
    const [my, mz] = onRing(deg);
    paint.push(rodX(motorR, -400, -130, my, mz, 32));                 // the motor: a cylinder along x
    steel.push(boxAt(100, 130, 130, -80, my, mz));                    // its gear box at the front
    steel.push(boxAt(60, 2 * motorR * 0.8, 2 * motorR * 0.8, -395, my, mz)); // a flange at the rear
  }

  // ---- the ammunition drum behind the gun: a shell on the rotor's axis, end walls, ribs, a hatch ----
  const drumR = 430, drumX0 = geo.rotorRear - 1800, drumX1 = geo.rotorRear;
  paint.push(
    axisTube(geo, drumR - 4, drumR, drumX0, drumX1, 0, 2 * Math.PI, 64),   // the shell, a few mm thick
    axisRod(geo, drumR - 2, drumX0, drumX0 + 8, 64),                        // rear end cap
    axisTube(geo, hro, drumR, drumX1 - 6, drumX1, 0, 2 * Math.PI, 64),     // front wall, round the housing
  );
  for (const x of [-2100, -1700, -1300, -900, -600]) {
    paint.push(axisTube(geo, drumR - 2, drumR + 7, x, x + 30, 0, 2 * Math.PI, 64)); // raised rings
  }
  paint.push(boxAt(320, 80, 260, -1150, axisY + drumR - 20, 0));           // the hatch box on top

  // ---- the conveyor: the rounds come up from the drum's lower front, under the housing, and into the feeder ----
  const [fx, fy, fz] = geo.feedPoint;
  const lowY = axisY - 535;
  const feedPath = [
    [-600, axisY - drumR, fz],    // on the drum's lower surface, in front of the drum
    [-600, lowY, fz],             // down and clear of the drum
    [fx, lowY, fz],               // forward under the housing
    [fx, fy, fz],                 // up through the feeder window: the end is geo.feedPoint
  ];

  // ---- the return: the cases come out of the ejection port, out and back to the drum's surface ----
  const [ex, ey, ez] = geo.ejectPoint;
  const zDrum = -Math.sqrt(drumR * drumR - (ey - axisY) ** 2);
  const returnPath = [
    [ex, ey, ez],                 // the ejection port: geo.ejectPoint
    [ex, ey, -460],               // out along -z, past the housing, clear of the drum
    [-600, ey, -460],             // back along -x
    [-600, ey, zDrum],            // onto the drum's surface
  ];

  // Chute walls and end plates for both conveyor legs, and the carriers along the feed.
  const furniture = [
    ...chuteFrame(geo, feedPath), ...chutePath(16, 40, feedPath),
    ...chuteFrame(geo, returnPath), ...chutePath(16, 40, returnPath),
  ];
  const L = pathLength(feedPath);
  for (let s = geo.linkPitch / 2; s < L; s += geo.linkPitch) {
    const [x, y, z] = pathPoint(feedPath, s);
    steel.push(boxAt(40, 40, 40, x, y, z));
  }

  // ---- mount: a front and a rear cradle ring round the housing, the front on trunnions ----
  const xF = -5, pivotY = axisY - (hro + 28) - 30;
  const mount = [
    axisTube(geo, hro - 2, hro + 28, -30, 20, 0, 2 * Math.PI, 64),        // front cradle
    axisTube(geo, hro - 2, hro + 28, -440, -412, 0, 2 * Math.PI, 64),     // rear cradle
    pinZ(14, 260, xF, pivotY),                                             // the trunnion pin
  ];
  const lugTop = -170;
  for (const s of [1, -1]) {
    mount.push(boxAt(40, lugTop - pivotY, 40, xF, (pivotY + lugTop) / 2, s * 225));   // lugs from the cradle to the pin
  }

  // ---- test stand: two posts on a base 1.2 m below the rotor axis, with two rails under the gun ----
  const floor = axisY - 1200;
  const pedestal = [
    boxAt(900, 40, 700, -160, floor + 20, 0),
    rodY(22, floor + 40, pivotY, xF, -260),
    rodY(22, floor + 40, pivotY, xF, 260),
    rodX(18, -440, 120, -430, -260),
    rodX(18, -440, 120, -430, 260),
  ];

  // ---- rotor parts: solid clamps round the barrels at the middle, the rear and the muzzle ----
  const clampAt = (x0, x1, Ro) => lathe(rodProfile(Ro, x0, x1), 64);
  const rotorSteel = [
    clampAt(120, 175, geo.R + geo.barrelR(150) + 14),
    clampAt(880, 950, geo.R + geo.barrelR(915) + 14),
    clampAt(2170, 2280, geo.R + geo.barrelR(2230) + 45),                  // the big muzzle clamp
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
      recR: drumR + 15,
      buttX: drumX0,
      boltRear: hx0,
      pivot: [xF, pivotY],
      cgX: -700,
      camera: { x: -250, y: -250, width: 1150 },
    },
  };
}
