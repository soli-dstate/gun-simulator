# Gun Simulator

A customisable gun simulator whose interior ballistics are computed with
**fluid dynamics**. The propellant gas is solved with the compressible Euler
equations instead of a single "average pressure". Every part of the gun
(barrel, chamber, projectile, propellant chemistry and grain geometry) is a
parameter you can change.

> Status: early prototype. A shot can be simulated end to end from a config
> file. Everything else is on the roadmap below.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"

python -m gun_sim configs/example_rifle.toml --plot
pytest
```

Example output:

```
[fluid] left muzzle
  muzzle velocity          835.0 m/s
  time in barrel           1.377 ms
  peak breech pressure     274.9 MPa
  charge burnt at exit      98.2 %
  heat to the barrel      1516.1 J (+1.74 K bulk, +58 K at the throat surface)
  spin at the muzzle      179311 rpm (11.5 J), stability Sg 2.28, peak rifling torque 1.87 N m
  recoil impulse           11.96 N s; free recoil 2.99 m/s, 17.9 J
  with the shooter          17.1 mm back at up to 1.15 m/s, muzzle rise 1.25 deg, peak shoulder force 508 N
```

and for the gas-operated preset, `configs/example_gas_rifle.toml`:

```
  gas action           cycled in 36.1 ms (1664 rounds/min), bolt at 6.8 m/s into the rear stop
```

### Desktop app

```bash
python -m gun_sim.ui          # or: gun-sim-ui
```

This opens the simulator in its own window. It uses
[pywebview](https://pywebview.flowrl.com/), which on Windows hosts the UI in
Edge WebView2 (already part of Windows 10 and 11). **Open…** and **Save…**
load and save gun `.toml` files, and **Preset** picks one from `configs/`
(the example rifle, the same cartridge in a gas-operated rifle, that rifle
with a suppressor, a 7-perforated-grain load, and a hollow-point round).
The window has two tabs.

**Editor.** Everything about the gun and the shot, one section at a time:
barrel, cartridge case, projectile, propellant, ignition, action and recoil,
muzzle device, shooter, listener and air, plus the solver and sound-model settings under
*Advanced*. Every value has a
slider, a number box in friendly units, and a line explaining what it does.
Next to the form is a live WebGL 2 preview of either the **Cartridge** or the
whole **Rifle** (drag to rotate, wheel to zoom, double-click to reset;
**Cutaway** shows a half-section). *At a glance* lists numbers derived from
the inputs: case capacity, the space under the projectile, how full the
chamber is, loading density, expansion ratio and barrel length. If the space
under the projectile differs from the solver's `chamber_volume` by more than
10%, **Use case space as chamber volume** copies it across. Setting
**Chamber shape** to *case* makes the fluid solver use the case's inside
directly, and *At a glance* follows it.

Choices that aren't numbers are drop-downs: the chamber shape, the
propellant **Composition** and **Grain shape** from the library (with a grain
chosen, χ, λ and μ are worked out from its size and greyed out), the
projectile's drag model and core material. *Wall friction and heat loss in
the bore* under *Solver* is a tick box. The projectile can be a
secant-ogive, hollow-point, cannelured or jacketed round; **Cutaway** shows
the copper jacket and the lead, steel or copper core as separate materials,
with the hollow-point cavity cut open.

**Firing range.** The rifle in 3D: a barrel with its chamber, throat, bore
and crown cut to fit the case, a receiver with an ejection port, a
two-lug rotating bolt with extractor, handle and firing pin, and a stock whose
butt sits where `[action]` puts the shoulder. A gas-operated rifle has a bolt
carrier instead, with a charging handle and an op rod running forward to a
piston in the gas cylinder over the gas block (at the gas port), and a
six-lug bolt head that turns in the carrier as it unlocks. A brake or
suppressor on the muzzle is turned from the same dimensions the 2D solver
uses; **Cutaway** shows its baffles. **Fire** runs the simulation,
then animates the shot from its results. All the while the whole rifle
recoils as the [recoil simulation](#recoil-and-action-cycling-gun_simactionpy)
says: back into the shoulder, pitching muzzle-up about it, and settling again.

1. The firing pin falls.
2. The projectile moves down the bore along the solver's travel-vs-time
   curve, in slow motion (the **Slow motion** slider sets how many seconds one
   simulated millisecond takes). The propellant gas behind it glows with the
   breech pressure, which you can see with **Cutaway** on. The readout shows
   time, travel, velocity and breech and base pressure as it goes.
3. At muzzle exit, the volumetric (ray-marched) muzzle flash appears: the
   under-expanded jet's shock bottle, the Mach disk (placed from the muzzle
   exit pressure), and the turbulent secondary flash. The flash lights the
   barrel and the smoke. The sound plays at this moment.
4. The clock ramps up to real time and the smoke rolls out, slows, rises and
   thins.
5. A manual bolt is worked: it turns up, draws back extracting the spent
   case, which is flung out of the port, then strips a new round from the
   magazine and chambers it. A wisp of smoke leaves the open breech. Turn off
   **Auto-cycle bolt** to do this yourself with **Cycle bolt**. An automatic
   action (gas, blowback, short recoil) instead cycles itself from the action
   simulation, a few milliseconds after exit while the clock is still slowed:
   the bolt unlocks, flies back, throws the case out, hits the rear stop,
   strips the next round and slams home. The readout names each step and shows
   the recoil, muzzle rise and bolt travel. If the action short-strokes, the
   case stays put (or the bolt closes on an empty chamber) and, with
   **Auto-cycle bolt** on, the bolt is worked by hand to clear it.
   **Burst** fires several shots per trigger pull from a self-loading action:
   each fires when the simulation has the bolt back in battery, with its own
   projectile, flash, smoke and ejected case, while the recoil and muzzle climb
   build up. The sound plays at the simulated shot times.

The **Camera** menu chooses between the *Director*, which follows the action,
and fixed views of the whole rifle, the breech, the projectile or the muzzle.
**Replay** shows the last shot again without re-simulating. Below the 3D view
are the result cards for both models (with the recoil impulse, free recoil,
travel into the shoulder, muzzle rise and, for an automatic action, whether
it cycled, its cyclic rate, the gas port's discharge coefficient, any warnings,
and with a muzzle device its push on the gun, peak pressure and the heat it
took), the sound player, the **Trajectory**
panel (drop and velocity against range and a range table, for a zero range,
sight height and crosswind you choose, in the air set in the Sound panel)
and the charts, including the gun's recoil, bolt travel and muzzle rise, the
force on the shooter's shoulder and, with a muzzle device, the 2D pressure
field inside it (a slider steps through the snapshots) and its push on the
gun. A muzzle device takes a few seconds to solve; the shot and its sound
share one run.

Options: `--debug` enables the web inspector (right-click › Inspect), and
`--browser` serves the same UI to your web browser from a local server
(127.0.0.1 only) instead of opening a window.

### Sound

With **sound** ticked, pressing **Fire** also synthesises what the shot sounds
like and plays it. There are no recordings or samples: the audio is the
pressure that the fluid simulation predicts at your ears (see
[How the sound is made](#how-the-sound-is-made)). In the **Sound** panel you can:

- choose where you stand: at the shooter's cheek, as a spotter, as a bystander,
  downrange beside the bullet's path, or far away. You can also set any
  distance, angle, facing, ear and muzzle height and ground type, plus the air
  temperature, humidity and pressure.
- choose the surroundings (open field, forest, indoor range, street, valley),
  hearing protection (plugs, muffs, both), and the number of shots and rate of
  fire for a burst.
- pick **Normalised** level (loudest ear at -1 dBFS), or **Calibrated** level
  (0 dBFS = a fixed dB SPL, so guns and distances compare honestly). A
  limiter protects your speakers either way.
- press **Play** or the space bar to hear the shot again.

Changing the listener re-renders in a fraction of a second. The blast
simulation is cached, and only a change to the gun or the air reruns it
(about 1.5 s).

From the command line, `--sound shot.wav` writes a 48 kHz stereo file:

```bash
python -m gun_sim configs/example_rifle.toml --sound shot.wav --listener downrange
```

### Building a Windows exe

```powershell
.\build_exe.ps1
```

This installs the build dependencies, runs the tests, and uses PyInstaller
(configured in [gun_sim.spec](gun_sim.spec)) to produce a single
`dist\GunSimulator.exe`. The exe needs no Python installation, opens
straight into the app window (no console), and includes the UI and the
presets in `configs/`. To build manually, run
`pip install -e ".[build]"` and then `pyinstaller gun_sim.spec`.

### Command line

CLI options for `python -m gun_sim <config.toml>`:

| Option | Meaning |
| --- | --- |
| `--model fluid\|lumped\|both` | which ballistics model(s) to run (default: both) |
| `--cells N` | override the fluid solver's resolution |
| `--no-recoil` | skip the 25 ms of bore blowdown (and the muzzle device), the recoil and the action cycle (faster) |
| `--plot` / `--save-plot FILE` | show or save pressure and velocity plots |
| `--range METRES` | print a trajectory table (drop, windage, velocity, energy, time of flight) out to this range, from the muzzle velocity of the fluid model (or the lumped one if fluid wasn't run) |
| `--zero METRES` / `--sight-height METRES` / `--wind M/S` | with `--range`: zero range (default 100), sight height above the bore (default 0.04) and crosswind from left to right (default 0) |

## Customising a gun

A gun is a TOML file in `configs/`. All units are SI. See
[configs/example_rifle.toml](configs/example_rifle.toml) for a commented
example.

| Section | Parameters |
| --- | --- |
| `[barrel]` | bore diameter, projectile travel, chamber volume; `chamber_shape` (`"cylinder"`, or `"case"` to solve inside the real case); outside diameter at the breech and muzzle (3D view only); rifling: `twist` (m per turn, negative for left-hand, 0 for a smooth bore), `groove_depth`, `freebore` (travel before the lands), `leade_angle` (forcing-cone half-angle, degrees) |
| `[case]` | case length, overall length, rim, extractor groove, base and shoulder diameters, shoulder position and angle, neck and body wall, head thickness, primer pocket (the solver uses it with `chamber_shape = "case"`) |
| `[projectile]` | mass, shot-start pressure, bore resistance, `engraving_pressure` (peak extra resistance while the rifling is cut, 0 = none); `drag_model` (G1 or G7) and `ballistic_coefficient` (kg/m²; estimated from the shape if missing); shape: length, ogive length and `ogive_radius_ratio` (1 = tangent, >1 = secant), meplat diameter, boat-tail length and angle; optional variants (3D view only): hollow-point diameter/depth, cannelure position/width/depth, `jacket_thickness` with `core_material` (`"lead"`, `"steel"` or `"copper"`) and `exposed_core_length` (soft point) |
| `[propellant]` | charge mass, force (impetus), covolume, γ, solid density, web thickness, burn-rate law `r = a·pⁿ`, form function `ψ(z) = χz(1+λz+μz²)`, gas molar mass (sets the gas temperature; used by the sound model). `composition` (`single_base`, `double_base`, `triple_base`) fills in the thermochemistry and burn law; `grain` (`tube`, `sphere`, `flake`, `7-perf`, `19-perf`) with `web`, `grain_length`, `grain_diameter`, `perforation_diameter` sets the form function. Explicit values always win |
| `[ignition]` | igniter pressure |
| `[action]` | `type` (`"bolt"`, `"gas"`, `"blowback"` or `"short_recoil"`); gun mass and the mass that cycles (bolt and carrier, or slide); bolt stroke, return spring rate and preload, unlock travel, barrel mass (short recoil), feeding drag, restitution at the rear stop and in battery; gas port position and diameter, piston diameter, cylinder volume and piston stroke before it vents; bore height above the shoulder, butt to centre of mass, radius of gyration (muzzle rise) |
| `[shooter]` | `stance` (`"shoulder"`, or `"free"` for free recoil); body mass moving with the gun, shoulder stiffness and damping, how hard the hold resists muzzle rise (stiffness and damping) |
| `[muzzle_device]` | `type` (`"none"`, `"brake"` or `"suppressor"`); length, outer diameter, number of baffles, baffle hole clearance over the bore, wall thickness, blast chamber length (suppressor), baffle cone angle, vent opening round the circumference (brake), mass. Missing sizes are scaled from the bore |
| `[solver]` | cell count, CFL number, time limits; `wall_losses` (friction and heat loss in the bore); `device_resolution` (2D cells across the bore), `device_time` (how long the muzzle device is solved in 2D), `gas_port_2d` (find the gas port's discharge coefficient in 2D) |

You can leave out any geometry value (the barrel's outside diameters, twist
and groove depth, `[case]`, or the projectile shape). Missing values come from a reference 7.62 mm rifle
scaled to the bore diameter, so older configs still load and show a sensible
cartridge and rifle.

The same data can be built in code:

```python
from gun_sim import Gun
from gun_sim import fluid

gun = Gun.load("configs/example_rifle.toml")
gun.barrel.travel = 0.40          # shorten the barrel
result = fluid.simulate(gun)
print(result.summary())
```

## How it works

### Fluid model (`gun_sim/fluid.py`)

- **Domain**: the gas column between the breech face and the projectile base.
- **Moving mesh (ALE)**: N finite-volume cells that stretch as the projectile
  moves down the bore.
- **Equations**: quasi-1D compressible Euler equations (mass, momentum,
  energy) with a cross-section A(x) that may change along the axis. The walls
  push on the gas with `p dA/dx`.
- **Chamber** (`gun_sim/chamber.py`): either a bore-sized cylinder of
  `chamber_volume` (the default), or, with `chamber_shape = "case"`, the inside
  of the cartridge case from the top of its web, up the body, through the
  shoulder and into the neck to the projectile base. The inner wall is the
  same one the 3D view draws, so the solver and *At a glance* agree.
- **Scheme**: HLLC flux sampled at each moving face, MUSCL reconstruction
  with the van Leer limiter, and two-stage SSP Runge-Kutta time stepping, with
  the projectile advanced in the same stages. It is second order: 50 and 200
  cells agree on muzzle velocity to about 0.1%.
- **Equation of state**: Noble-Abel, `p = (γ-1)ρe / (1 - bρ)`. This is the
  standard real-gas correction at gun pressures.
- **Propellant**: grains are spread through the chamber. Each slice of the
  charge burns at its own local pressure (Vieille's law with a geometric form
  function) and adds gas mass and energy where it lies. In a cylindrical
  chamber the grains move with the mesh, as the lumped model's Lagrange
  gradient assumes. In a case-shaped chamber they stay put, since grains that
  followed the stretching mesh would be squeezed through the shoulder (a
  moving grain bed is the two-phase item on the roadmap). The flux treats the
  gas per unit of cell volume, grains included, as the density, so its sound
  speed is the gas's divided by the square root of the gas fraction.
- **Projectile**: a moving wall pushed by the gas pressure at its base (the
  HLLC pressure at the wall). It starts moving once the base pressure exceeds
  the shot-start pressure.
- **Recoil**: the gun is pushed by the pressure on the breech face and the
  chamber walls (a shoulder is pushed forwards) and pulled forwards by the
  projectile's drag on the bore. The force is recorded over time, split into
  the push on the bolt face (pressure over the inside of the case head) and
  the rest, together with the gas at the gas port, for the
  [action model](#recoil-and-action-cycling-gun_simactionpy). Grains that move
  with the mesh are carried rather than pushed, so the momentum they gain (and
  give their gas as it is born) is added to the push on the breech. Before the
  projectile leaves, the gun has given it `m v` and the gas about `ω v / 2`, as
  momentum conservation says.
- **Muzzle device**: during blowdown a brake or suppressor is solved in 2D
  alongside the bore and coupled to it (see the
  [2D solver](#2d-axisymmetric-solver-muzzle-devices-and-gas-ports-gun_simaxisympy-gun_simdevicespy)).
- **Wall losses and barrel heating**: with `[solver] wall_losses = true`, the
  gas in the bore feels turbulent friction (Darcy factor 0.03, rough because
  of the rifling) and loses heat to the cold steel. Heat transfer uses
  Colburn's correlation `St = 0.023 Re^-0.2 Pr^-2/3` rather than the Reynolds
  analogy, which overstates heat transfer on a rough wall. The result reports
  the heat put into the barrel, the barrel's mean temperature rise, and the
  peak bore surface temperature rise at the throat (the heat flux history
  there, conducted into a semi-infinite steel wall). For the example rifle
  this costs about 6% of muzzle velocity, and with blowdown puts about 2.5 kJ
  (about 20% of the charge's energy, +3 K in bulk) into the barrel per shot.
  It is off by default so the fluid and lumped models stay comparable.

### Lumped-parameter model (`gun_sim/lumped.py`)

This is the classic 0-D textbook model: one uniform gas state, with the
Lagrange gradient used to estimate breech and base pressures. For recoil it
records the breech force and the Lagrange pressure at the gas port, and after
exit adds the gas jet as the classic exponentially decaying after-effect
force. Its impulse is the momentum of the remaining gas emptying like a vessel
through a choked nozzle (a mean jet speed of about 1.5 times the exit sound
speed), less the forward momentum the gas already had. Including the jet, its
recoil impulse is within about 4% of the fluid model's. It runs in
milliseconds and is the reference the fluid solver is checked against. The
two agree on muzzle velocity to within about 2% (with a case-shaped chamber
the lumped model uses its volume).

### Rifling, engraving and spin (`gun_sim/rifling.py`)

- **Engraving**: the projectile first moves through the `freebore` with only
  the bore resistance. Its bearing surface then meets the leade and is squeezed
  into the rifling. The extra resistance rises linearly to
  `engraving_pressure` over the length of forcing cone it takes to cut a groove
  to full depth (`groove_depth / tan(leade_angle)`, about 3.8 mm for the
  example rifle), then dies away exponentially over the bearing length. Both
  solvers use this profile. Holding the projectile back raises the pressure
  and so the burn rate. In the fluid model, with 60 MPa of engraving and a 15 MPa shot start, the
  example rifle peaks at 326 MPa seated against the lands and at 301 MPa with
  1.5 mm of freebore: the jump lets the gas expand before the resistance
  arrives. This is why freebore is used to tame pressure.
- **Spin-up**: the spin rate is `2π v / twist`, so the gas drives an effective
  mass `m + I_x (2π / twist)²` (0.34% above the mass for the example). `I_x`
  comes from the projectile's shape (boat tail, shank, tangent or secant ogive,
  meplat, hollow point) with its mass spread uniformly. A dense core under a
  jacket would lower it by a few per cent. The shot reports the spin rate and
  energy, the peak reaction torque on the barrel and the angular momentum
  given to the gun.
- **Stability**: Miller's twist rule gives the gyroscopic stability factor
  `Sg` at the muzzle, corrected for velocity, temperature and pressure (below
  1 the bullet tumbles; above about 1.5 it is stable).
- **Spin drift**: the trajectory adds Litz's fit to 6-DoF results,
  `1.25 (Sg + 1.2) t^1.83` inches after a time of flight `t` (s), to the windage.
  It drifts right for a right-hand twist. The range table shows how much of the
  windage is spin drift (about 43 cm at 1000 m for the example).
- Not modelled: friction on the driving side of the lands, gain twist,
  and the small change in gas area through the freebore and forcing cone.

### Recoil and action cycling (`gun_sim/action.py`)

The forces each interior-ballistics model records drive a rigid-body model of
the gun, solved for 300 ms with small fixed steps (2 µs while the gas acts):

- **Bodies.** The gun recoils along the bore and pitches. The bolt group
  (bolt and carrier, or a pistol's slide) slides inside it against the return
  spring. With `stance = "shoulder"`, part of the shooter's body moves with the
  butt, the shoulder is a spring and damper, and the hold resists pitch with a
  torsional spring and damper. With `"free"`, nothing holds the gun, which gives
  the standard free-recoil velocity and energy.
- **Which body the shot pushes** depends on the action.
  - *bolt*: always locked, so the whole gun takes it.
  - *gas*: locked until the carrier has moved `unlock_travel`. Gas flows from
    the port into the cylinder as through an orifice (choked or subsonic
    compressible flow, either way, with the port's pressure and temperature
    from the solver). The cylinder pressure drives the piston and carrier until
    the piston has moved `gas_stroke`, when the cylinder vents. The reaction
    pushes the gas block forwards.
  - *blowback*: never locked. The breech pressure on the case head pushes the
    bolt from the start.
  - *short_recoil*: the barrel and slide recoil locked together until the
    barrel has moved `unlock_travel` and stops against the frame. The slide
    carries on, and picks the barrel up again on the way home.
- **Cycle.** The bolt ejects the case once it has come back a case length
  (plus 3 mm). It can pick up the next round once it has come back past a whole
  round, and drags `feed_force` while it chambers it. Impacts at the rear stop
  and in battery are instantaneous, with a coefficient of restitution, shared
  between the bolt and the gun by their masses.
- **Muzzle rise.** Every force along the bore acts `bore_height` above the
  shoulder, so the shot lifts the muzzle, and the bolt hitting the rear stop
  kicks it again.
- **Results**: recoil impulse, free-recoil velocity and energy, travel into
  the shoulder and peak shoulder force, muzzle rise, and for an automatic
  action its events (unlock, ejection, rear stop, feeding, back in battery),
  cycle time and cyclic rate. It reports when the action fails:
  - short stroking: the case is not ejected, or no round is picked up;
  - battering: the bolt reaches the rear stop above 8 m/s;
  - unlocking with more than 20 MPa in the chamber;
  - a case backing more than 1 mm out of the chamber while it is still above
    30 MPa, as in a blowback with too light a bolt.

  The cyclic rate counts only the bolt's own travel, with no hammer or sear
  time, so real guns fire more slowly.

For the example rifle (4 kg) this gives 12.0 N·s of recoil, of which 2.5 N·s is
the gas jet. Free, the rifle recoils at 3.0 m/s with 18 J. Held, it goes about
17 mm into the shoulder with 1.25° of muzzle rise. The gas-operated preset
unlocks with 8.6 MPa left in the chamber and cycles in 36 ms, the bolt
reaching the rear stop at 6.8 m/s.

- **Bursts.** A self-loading action can fire several shots per trigger pull.
  Each fires 3 ms (sear, hammer, primer) after the bolt is back in battery on
  the one before, with the gun's motion and the gas cylinder carried over, so
  recoil and muzzle climb build up. The burst stops if a cycle fails. The
  example gas rifle fires at about 1,300 rounds a minute, its muzzle climbing
  about 0.9° a shot.
- **Gas port** and **muzzle device**: the port's discharge coefficient comes
  from a 2D solution of the port, and a device's mass is added to the gun
  (see below).

Not modelled: the carrier's free travel before it picks up the bolt (they move
as one), friction other than feeding, hammer cocking, extraction force (the
case leaves the chamber freely), heat loss in the gas cylinder, delayed
blowback (roller, lever, gas-delayed), and a non-linear shooter.

### 2D axisymmetric solver: muzzle devices and gas ports (`gun_sim/axisym.py`, `gun_sim/devices.py`)

Where the geometry really is two-dimensional, a 2D solver takes over from the
1D bore solver, coupled to it at their shared boundary.

- **Solver.** The compressible Euler equations in (x, r) for a mixture of air
  and propellant gas (a conserved mass fraction tracks the propellant). Finite
  volumes on a uniform grid of square cells (rings and cylinders, with the hoop
  term so gas at rest stays at rest). It uses HLL fluxes, MUSCL reconstruction
  (minmod) and SSP-RK2 time stepping, in float32 NumPy.
- **Walls** are face apertures, the share of each face that is open. Solid cells
  have every face shut. A partly open face is a perforated plate: flux passes
  through the open part, and each side pushes on the shut part with its own
  pressure. That pressure is the gas's force on the steel. Gas next to a wall
  loses heat to it at a rough-wall Stanton number.
- **Muzzle devices.** The grid holds the end of the barrel, the device and the
  air round it.
  - A *brake* is plates along a tube, with each chamber venting sideways through
    slots that open `vent_fraction` of the circumference.
  - A *suppressor* is a closed can with a blast chamber, flat or cone baffles,
    and a front cap.
  - During the bore's blowdown, the bore and the device overlap by a cell, each
    seeing the other's neighbouring gas, so waves pass both ways. A
    suppressor's back-pressure therefore slows the bore's emptying and raises
    the pressure at the gas port.
  - The device is solved in 2D for `device_time` (2.5 ms) after exit. It then
    becomes a 0-D vessel that the bore keeps feeding and that vents through its
    exit hole and slots, so mass, energy and momentum balance to the end of the
    blowdown.
  - What comes out:
    - the force on the device, added to the gun's loads, so a brake cuts recoil;
    - the propellant gas and its energy leaving the device, which become the
      source of the muzzle blast, with its directivity scaled by how much of
      the jet's forward momentum survives;
    - the heat to the walls;
    - pressure snapshots for the UI.
  - The lumped model has no device of its own. After exit it takes the fluid
    model's coupled blowdown (breech, barrel with the device's push, gas port).
- **Gas port.** A port is a hole in the side of the barrel, which an
  axisymmetric grid can only draw as a ring. The ring is one cell wide with
  faces open by port area / ring area, so it passes the port's true area. Over
  it sits a ring chamber with the gas cylinder's volume. The bore gas recorded
  at the port flows past for about a millisecond, and the port's discharge
  coefficient is the one for which the action model's orifice fills a
  cylinder with the same mass. It comes out at about 0.3 to 0.8 depending on
  the port (the crossflow and the turn into the hole), against the 0.8 assumed
  without it.

For the example rifle (2 mm cells, 4 to 6 s each):

| Device | Recoil impulse | Blast at 1 m | Other |
| --- | --- | --- | --- |
| None | 12.0 N·s | 170 dB | |
| Brake | 9.2 N·s | 169 dB | 2.5 dB louder at the shooter's ear |
| Suppressor | about 11.4 N·s | 152 dB | gives about 1.2 kJ to its steel; the gas leaves over tens of ms |

The suppressor's recoil saving is small because the gas it holds back pushes
the gun when it finally vents forwards. On the gas rifle, the suppressor's
back-pressure drives the bolt into the rear stop at 14 m/s instead of 5 m/s,
the familiar over-gassing of suppressed rifles. The suppressed preset has its
gas port turned down to suit.

Not modelled: anything off the axis (brake ports are slots all round, side
vents and asymmetric brakes average out), boundary layers (the grid is a few
cells across the bore), the projectile passing through the device, first-round
pop and secondary flash, and erosion. The suppressor's sound reduction comes
out smaller than real cans manage, likely because of the coarse grid and the
short 2D window.

### Propellant library (`gun_sim/propellants.py`)

Propellant can be described two ways. A composition gives a propellant family
(single, double or triple base) with its force, covolume, γ, density,
burn-rate law and molar mass. A grain gives the shape of each grain, which
sets the form function ψ(z): the fraction of the charge burnt once a fraction z
of the web has gone. Tubes, spheres and flakes burn out at z = 1.
Multi-perforated grains (7-perf, 19-perf) leave thin slivers that burn on
after the web has gone, so they have a second phase up to z_k > 1. Explicit
numbers in the config always override the library. The values in the library
are illustrative textbook-range figures, not data for any real powder. See
`configs/example_7perf.toml`.

### External ballistics (`gun_sim/exterior.py`)

After muzzle exit the projectile is a point mass (3 degrees of freedom) under
gravity and air drag, integrated with RK4.

- **Drag**: the standard G1 and G7 drag functions (Cd against Mach, published
  tables). A projectile is described by its ballistic coefficient,
  `a = -(π/8) ρ Cd(M) |v_rel| v_rel / BC`, with `BC = m / (i d²)` in kg/m²
  (1 lb/in² = 703.07 kg/m²) and `v_rel` the velocity relative to the air.
  If `[projectile]` gives no `ballistic_coefficient`, it is estimated from the
  mass, bore diameter and shape: sectional density divided by a G7 form factor
  from a simple heuristic (a longer ogive, a smaller meplat and a boat tail
  lower it; about 1.1 for the reference match shape and 1.17 for a flat base).
- **Atmosphere**: temperature, pressure and humidity give air density and speed
  of sound (default ICAO standard air: 15 °C, 101325 Pa, dry). Density is held
  constant along the path, which is fine for small-arms ranges.
- **Wind and zeroing**: head/tail wind and crosswind act through the relative
  velocity. The gun is zeroed in still air by finding the bore elevation that
  puts the path through the line of sight (a given height above the bore) at
  the zero range.
- **Output**: drop relative to the line of sight, drift, velocity, Mach, energy
  and time, as a `Trajectory`, with a `table(step)` of drop (m, MOA, mil),
  windage, velocity, energy and time of flight.
- **Spin drift** for a rifled barrel (see above) is added to the windage.
- Not modelled: Coriolis, yaw and lift, and density change with height along
  the path. The sound model's drag curve in `sound/ballistic.py`
  is still its own rough G7-shaped curve.

### How the sound is made (`gun_sim/sound/`)

The approach is the same as an engine-sound simulator: solve the gas
dynamics, then listen to the pressure. A shot is built from these parts:

1. **Bore blowdown** (`fluid.py`). After the projectile leaves, the 1D solver
   keeps running with the muzzle open to the atmosphere. Gas at ~65 MPa
   empties out in a few milliseconds, then the bore rings as a closed-open
   pipe. In this phase the gas always feels the wall: turbulent friction and
   heat loss to the cold steel (see the fluid model). These damp the ringing and
   let the cooling gas draw air back into the bore. The mass and energy flux
   through the muzzle are recorded, and so is the recoil impulse including
   the gas jet.
2. **Precursor** (`ballistic.py`). Before the projectile exits, it drives a
   shock through the air column in the bore ahead of it, and that air leaves
   the muzzle first.
3. **Muzzle blast** (`blast.py`). Both flows are injected at the centre of a
   1D *spherical* compressible Euler solver. It is second order (MUSCL +
   Rusanov + SSP-RK2), tracks two gases (air and propellant gas, with a
   conserved mass fraction), and has a non-reflecting far-field boundary. The
   blast wave forms by itself: a shock that outruns sound near the muzzle, the
   Friedlander decay, and a negative phase from the gas cloud over-expanding.
   Probes record it at 14 radii from 0.1 m to 1.8 m. The coarse grid smears
   the shock, so the front is restored by shock fitting (extrapolating the
   decay back to the shock), as in blast measurements.
4. **Supersonic crack** (`ballistic.py`). The projectile flies with a G7-shaped
   drag curve. The heard part of the Mach cone is found as the stationary
   point of arrival time along the trajectory. Its N-wave follows Whitham's
   theory (amplitude ∝ b^-3/4, length ∝ b^1/4). Listeners behind the cone,
   such as the shooter, hear no crack, as in reality. Downrange, the crack
   arrives before the boom.
5. **Propagation** (`propagation.py`):
   - directivity: the gas cloud is thrown forward, so the blast acts as a
     convecting source. It is louder and sharper ahead of the muzzle and
     duller behind, and the effect fades as the cloud slows.
   - weak-shock lengthening beyond the solver's domain.
   - ISO 9613-1 air absorption (temperature, humidity, pressure), applied as
     a minimum-phase filter.
   - a ground reflection with a Delany-Bazley impedance (concrete to snow).
6. **Listener**. A rigid-sphere head model (Woodworth delay, Brown-Duda head
   shadow) is applied to every arrival separately. A crack from one direction
   and a muzzle blast from another are therefore placed correctly in stereo.
7. **Muzzle devices.** With a brake or suppressor, the blast is fed by what
   leaves the device (from its 2D solution) rather than by the bore's jet. It
   comes from the device's exit, and it is thrown forwards only as much as the
   jet's forward momentum survives the device.
8. **The action** (`mechanical.py`). The impacts the action simulation reports
   become bursts of ringing steel or brass at the place they happen: the hammer
   falling, the bolt unlocking, hitting the rear stop and slamming home at the
   receiver, and the spent case landing on the ground beside the shooter after
   its fall. Their timing and impact energy come from the simulation. How much
   of that energy becomes sound (1e-4) is an assumption.
9. **Playback** (`ui/static/js/audio.js`). This adds what depends on the
   surroundings rather than the gun. Each environment is a set of reflecting
   surfaces (a treeline, valley walls, facades), cut into patches. Every patch
   returns the blast at 1 m as thrown in its direction (front, side or rear
   reference, so a treeline downrange gets the louder forward blast), and the
   supersonic crack: the Mach cone reaches each patch from the point on the
   trajectory that gets there first, and weakens on the way back by Whitham's
   law. Long surfaces therefore give a rolling echo, the crack's echo arriving
   before the blast's. Levels keep their real proportion to the direct sound.
   Hearing protection, level and bursts are also applied here. The default
   level, "Recorded", overdrives a tanh stage like a microphone preamp: the
   peak flattens and the body and echoes come up by the drive (36 dB), which is
   how shots sound on recordings. "Normalised" and "Calibrated" keep the true
   dynamic range. A burst from a self-loading action plays at the shot times
   the action simulation gives.

For the example rifle this gives about 169 dB at 1 m (omnidirectional), 166 dB
at the shooter's ear, 145 dB for a bystander at 10 m, and a 148 dB crack
followed 160 ms later by a 128 dB boom at 100 m downrange. These are in line
with published measurements for 7.62 mm rifles.

**Approximations and gaps.**

- The near field is treated as spherical. The real jet, the gun and the
  shooter's body make it 3D, and the directivity strength (`convection_mach`)
  is empirical.
- The ground is a mirror image with a plane-wave reflection coefficient, with
  no ground wave at grazing angles.
- Not modelled:
  - secondary flash (afterburning of fuel-rich muzzle gas).
  - subsonic bullet flight noise and impact sounds.
  - barrel ring.
- Each shot in a burst is the same round.

### Why 1D and not 2D?

A rifle barrel is about 70 calibres long. The gas flow inside it is almost
entirely along the axis, so a 1D model captures the physics that sets muzzle
velocity and chamber pressure: pressure waves, the breech-to-base pressure
gradient, and local burning. This is why most interior ballistics codes are
1D. A 2D axisymmetric solver costs 100–1000× more compute and barely changes
those results.

2D matters where the geometry really is multi-dimensional. The fast 1D solver
keeps the bore, and a 2D axisymmetric solver handles muzzle devices and the
gas port, coupled at their boundaries (see above). Still on the roadmap:

- bottlenecked cartridge cases, shoulders and the forcing cone, in 2D
- the free muzzle blast after exit in 2D (it is spherical now)

## Project layout

```
gun_sim/
  config.py      gun definition dataclasses + TOML loading
  fluid.py       1D finite-volume interior ballistics solver
  chamber.py     chamber cross-section along the axis (cylinder, or the inside of the case)
  lumped.py      0-D reference model
  action.py      recoil and action cycling: gun, bolt, gas system, shooter, bursts
  axisym.py      2D axisymmetric compressible flow solver (face apertures for walls and ports)
  devices.py     muzzle brake/suppressor and gas port geometry, coupling to the bore, discharge coefficient
  propellants.py propellant compositions and grain shapes -> form function
  exterior.py    point-mass trajectory solver: G1/G7 drag, atmosphere, zeroing, range tables
  rifling.py     engraving resistance vs travel, spin-up, moment of inertia, stability, spin drift
  results.py     ShotResult (and MuzzleFlow) containers
  sound/
    settings.py    listener position, atmosphere, presets
    mechanical.py  hammer, bolt and case sounds from the action simulation
    blast.py       spherical two-gas Euler solver for the muzzle blast
    ballistic.py   supersonic crack (Whitham N-wave), drag, precursor
    propagation.py directivity, weak shocks, air absorption, ground, head model
    synth.py       puts it together: physics -> both ears, in pascals
    wav.py         .wav export
  plotting.py    matplotlib plots
  __main__.py    command-line interface
  ui/
    app.py       desktop window (pywebview) + the Python bridge the page calls
    api.py       backend calls shared by the window and the browser fallback
    server.py    --browser fallback: local HTTP server + JSON API
    static/      the HTML UI (self-contained, works offline)
      js/app.js          editor and firing-range tabs, results, charts wiring
      js/fields.js       editor sections, slider ranges and help text
      js/backend.js      pywebview bridge or HTTP, whichever is present
      js/audio.js        Web Audio playback: reverb, hearing protection, limiter, bursts
      js/viewer3d/       WebGL 2 renderer, lathe (surface of revolution) mesher,
                         procedural case/primer/projectile profiles, cartridge viewer,
                         gun.js (barrel, receiver, bolt, stock), range.js (the animated shot and recoil),
                         volume.js (ray-marched muzzle flash, smoke and bore gas)
configs/         example gun definitions (shown as presets in the UI)
tests/           pytest suite (physics checks + UI server API)
launcher.py      entry script for the exe build
gun_sim.spec     PyInstaller configuration
build_exe.ps1    one-command Windows build
```

## Why Python?

- NumPy makes the vectorised solver short and readable. A shot takes about
  0.5 s at 100 cells.
- The scientific tooling (plotting, SciPy, notebooks for experiments) is
  hard to beat for a physics project still being worked out.
- If performance becomes a limit (2D solvers, many shots for optimisation),
  the solver kernels can move to Numba or to a Rust/C++ extension without
  changing the rest of the code.

## Roadmap

- [x] Higher-order solver (MUSCL reconstruction, HLLC flux, SSP-RK time stepping)
- [x] Real chamber geometry: area that varies along the axis (bottleneck case); freebore and forcing cone set where engraving happens
- [ ] Two-phase grain bed: grains that move, interphase drag, flame spread from the primer
- [x] Propellant library (single, double and triple base; multi-perforated grain geometries)
- [x] Heat loss to the barrel wall and barrel heating
- [x] Rifling and engraving forces, projectile spin, gyroscopic stability and spin drift
- [x] Sound synthesis from the fluid simulation (blowdown, muzzle blast, crack, propagation, binaural)
- [x] Sound of muzzle devices and suppressors
- [x] 2D axisymmetric solver for muzzle devices, suppressors and gas ports, coupled to the bore
- [x] Action cycling (gas, recoil, blowback) and recoil impulse; the gun recoils and pitches in the 3D view
- [x] Mechanical sounds from the action cycle; burst fire from the action simulation
- [ ] Delayed blowback; gas-port flow in full 3D; a finer 2D grid (compiled kernels)
- [x] External ballistics (drag models, trajectory)
- [x] Procedural 3D cartridge (case, primer, projectile) with cutaway
- [x] Use the case geometry in the solver (chamber volume and area profile from `[case]`)
- [x] 3D barrel, chamber and bolt action; animate the projectile, gas, flash, smoke and bolt cycle from a shot
- [x] Projectile variants: secant ogive, hollow point, cannelure, jacket/core section
- [ ] Richer GUI: side-by-side gun comparison, parameter sweeps, live animation of the bore flow

## Disclaimer

This is a physics and education project. The example values are generic and
illustrative. Do not use this software to develop ammunition loads.
