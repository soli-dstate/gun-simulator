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
  recoil impulse           11.87 N s; free recoil 2.97 m/s, 17.6 J
  with the shooter          16.9 mm back at up to 1.14 m/s, muzzle rise 1.24 deg, peak shoulder force 504 N
```

and for the gas-operated preset, `configs/example_gas_rifle.toml`:

```
  gas action           cycled in 41.0 ms (1364 rounds/min), bolt at 5.0 m/s into the rear stop
```

### Desktop app

```bash
python -m gun_sim.ui          # or: gun-sim-ui
```

This opens the simulator in its own window. It uses
[pywebview](https://pywebview.flowrl.com/), which on Windows hosts the UI in
Edge WebView2 (already part of Windows 10 and 11). **Open…** and **Save…**
load and save gun `.toml` files, and in Expert mode **Start from a preset** picks one from `configs/`
(the example rifle, the same cartridge in a gas-operated rifle, that rifle
with a suppressor, a roller-delayed rifle, a two-phase grain bed, a
7-perforated-grain load, a hollow-point round, and three real rifles: the
M4A1, AKM and AK-74; two cannon, the Mk44 Bushmaster II 30 mm chain gun and the
Rheinmetall Rh-120 L/55 120 mm smoothbore tank gun; and five handguns: the Colt
M1911A1, the Beretta M9, the Glock 17, the Colt Anaconda and the Colt Single
Action Army).

The bar along the top has four tabs (**Workshop**, **Range**, **Target**,
**Analysis**), an **Easy / Expert** mode switch and a **Metric / Imperial**
units switch. Imperial shows inches, grains, ft/s, ft·lbf, psi, yards and
pounds everywhere, the expert form included (typed values are read in the units
shown); the simulator itself stays in SI.

**Workshop, Easy mode.** Build a gun without knowing any interior ballistics,
in four steps: pick a **cartridge** (search by either name: *7.62×51mm NATO*
or *.308 Winchester*, *9×19mm Parabellum* or *9mm Luger*; filter by pistol,
revolver, intermediate, full-power, magnum, heavy or cannon), a **load**
(ball, AP, soft point, hollow point, match; the bullet weight in grains and
grams), a **gun** (striker-fired, 1911-style or DA/SA pistol, pistol-calibre
carbine, submachine gun, double- or single-action revolver, bolt action,
AR-style semi or select fire, AK, gas-piston battle rifle, roller-delayed,
belt-fed machine gun, chain gun, tank gun; only the ones that take the
cartridge are offered), and a **barrel length** and muzzle device. The computer
does the rest (`gun_sim/designer.py`): the case, bullet and bore come from the
cartridge library (`gun_sim/cartridges.py`, 24 cartridges with their
published dimensions and service loads); the chamber volume is the case's
powder space under the seated bullet; the powder's burn rate is tuned so the
load makes its published velocity from its published barrel, so your barrel
gives what it physically would; the twist is the standard one unless the
bullet would be under-stabilised, when a faster one is worked out; and the
action, feed, trigger and stock come from a preset of that kind of gun scaled
to the cartridge's recoil, with its gas port (or a blowback's bolt mass, or a
pistol's recoil spring) tuned until it cycles cleanly. **Performance** shows a
quick estimate (velocity, energy, chamber pressure against the SAAMI / CIP /
NATO maximum, recoil, stability, rate of fire) and **What the computer worked
out** says each of those decisions in plain words. **Fine-tune in Expert mode**
opens the same gun with every parameter.

**Target.** A steel plate downrange (AR500 for now): its thickness (the
standard 1/4″ to 1″ plates, or any), distance and angle. The last shot's
muzzle velocity is flown out to it, and `gun_sim/terminal.py` works out what
the hit does: **stopped**, **cratered**, **perforated** (with the exit
velocity and the ballistic limit) or a **ricochet**. A hard core (hardened
steel, tungsten carbide) penetrates as a rigid body (Forrestal's
cavity-expansion law), a softer one or a long rod erodes (Alekseevskii–Tate),
and a lead-core bullet splashes on the face and leaves a crater. Every
depth is also given in **RHAe**: how much rolled homogeneous armour the round
gets through, and how much RHA the plate is worth against it. A to-scale
cross-section shows the hit, and a chart shows penetration against range, so
you can read off how far out the round gets through the plate, and how far
out it still craters it (the distance to stay beyond for target longevity).

**Workshop, Expert mode.** Everything about the gun and the shot, one section at a time:
barrel, cartridge case, projectile, propellant, ignition, action and recoil,
muzzle device, appearance, shooter, listener and air, plus the solver and sound-model settings under
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

**Analysis** holds the trajectory (drop, velocity, a range table in MOA and
mil) and every chart: pressure, velocity, the pressure along the bore, recoil,
the force on the shooter, the muzzle device's 2D field, and the sound.

**Range.** The gun in 3D: a barrel with its chamber, throat, bore
and crown cut to fit the case, a receiver with an ejection port, the parts of
the action, and a stock whose butt sits where `[action]` puts the shoulder.
Every action type has its own moving parts:

- *bolt*: a two-lug rotating bolt with extractor, handle and firing pin;
- *gas*: a bolt carrier with an op rod running forward to a piston in the gas
  cylinder over the gas block (at the gas port), and a bolt head that turns in
  the carrier as it unlocks (two lugs in an AK, six or seven otherwise);
- *direct_impingement*: no piston. A gas tube runs from the gas block back to a
  key on top of the carrier, and a seven-lug bolt head turns in it;
- *blowback*: a plain heavy bolt with a charging knob;
- *chain*: a four-lug bolt head turning in a carrier, whose arm reaches out
  through the receiver's side to a T-slot. The master link of the drive chain
  rides in it round a track of four sprockets, the motor on the rear one, so
  the chain going round the track carries the bolt back and forth;
- *sliding_wedge*: a breech block that drops in the breech ring, with the
  crank on the ring's side turning as it does;
- *short_recoil*: the barrel and its extension recoil with the bolt until the
  barrel stops, and a locking block drops out from under the bolt as it does;
- *roller_delayed* and *lever_delayed*: a light bolt head with the carrier
  running ahead of it while the delay lasts. Two rollers come in from the
  head's sides, or a lever on top of it tips back;
- *gas_delayed*: a sleeve round the barrel, tied to the bolt by two rods, whose
  front closes on a piston ring on the barrel just ahead of the port;
- *revolver*: a cylinder of chambers (fluted between them) that turns a
  chamber on as the hammer is cocked, the fired cases staying in their
  chambers; the gas out of the cylinder gap flashes and smokes beside the frame.

With `hammer = true`, a hammer on its pivot pin stands behind the bolt group.
It falls on the firing pin when you fire, is pushed down and back as the
carrier rides over it, and in a burst falls again as the simulation has it.

Handguns. A pistol (*1911*, *beretta* and *polymer* styles) is a slide over the
barrel with its breech face, ejection port, sights and serrations, on a frame
whose grip rakes back round the magazine. With *short_recoil* the barrel goes
back with the slide until it unlocks: a Browning barrel (`locking = "tilt"`: the
1911, the Glock) drops its breech about the bushing, a Beretta's locking block
(`"block"`) drops out of the slide. The recoil spring's coils bunch on the guide
rod as the slide comes back, the trigger moves as it is pulled, a spur hammer
turns at the frame's rear (a striker-fired pistol's striker sits back in the
slide), and the slide locks back on an empty magazine. **Rack slide** works it
by hand. A revolver (*revolver* and *single_action*) has a frame round its
cylinder, a recoil shield, a top strap and the barrel across the gap; the
double action's cylinder swings out on its crane, the ejector star throws every
case out and a speedloader puts six rounds in; the single action is reloaded
through its loading gate, turned a chamber at a time while the ejector rod
punches each case out. **Cock hammer** draws the hammer back (the trigger's
double-action pull, or the thumb) while the hand turns the next chamber up.

`[appearance] style` dresses the gun: *rifle* is a sporting stock round a
turned receiver; *ar15* an aluminium upper and lower with a rail, A-frame
front sight, round handguard, pistol grip, buffer tube and collapsible stock;
*ak* a stamped receiver and dust cover, rear sight block, gas tube with
wooden handguards, curved magazine and wooden stock; *1911* a blued slide and
steel frame with a grip safety, spur hammer and walnut grips; *beretta* an
open-top black slide over the bare barrel on an aluminium frame; *polymer* a
squared-off slide on a polymer frame; *revolver* a stainless double-action
frame with a full-length underlug and ventilated rib; *single_action* the
army's blued frame, ejector rod housing and one-piece walnut grip. The moving
parts follow the action type whatever the style. A brake,
suppressor or flash hider on the muzzle is turned from the same dimensions the
2D solver uses; **Cutaway** shows its baffles. **Fire** runs the simulation,
then animates the shot from its results. All the while the whole rifle
recoils as the [recoil simulation](#recoil-and-action-cycling-gun_simactionpy)
says: back into the shoulder, pitching muzzle-up about it, and settling again.

1. The firing pin falls.
2. The projectile moves down the bore along the solver's travel-vs-time
   curve, in slow motion (the **Slow motion** slider sets how many seconds one
   simulated millisecond takes). The propellant gas behind it glows as hot as
   the fluid model says it is (and fades as the bore empties and cools after
   exit), which you can see with **Cutaway** on. The readout shows time,
   travel, velocity and breech and base pressure as it goes.
3. At muzzle exit, the muzzle flash and smoke appear as the 2D plume solution
   has them (see *Muzzle flash and smoke* below): the gas glows where it is
   hot, so the primary flash, the jet's shock cell and Mach disk, and the
   afterburning fireball come out of the flow rather than being drawn. A
   brake throws them sideways; a suppressor holds them in (look inside with
   **Cutaway**); a flash hider lets the jet expand before it meets the air. The flash lights the barrel and the smoke, and the readout
   shows the heat afterburning released. The sound plays at this moment. The
   **Fire** button waits for the plume (a few seconds) before the shot plays.
4. The clock ramps up to real time and the smoke cloud carries on from the
   solution: it grows and thins as a puff, rises with its warmth, and whatever
   gas was left in the bore or the device seeps out of the exit.
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
   **Shots** fires several shots per press of **Fire** from a self-loading
   action or a revolver: an automatic fires them as a burst, each when the
   simulation has the bolt back in battery; a semi-automatic or a revolver
   fires each with a pull of its own, the trigger's `split` apart. Each has its
   own projectile, flash, smoke and ejected case, while the recoil and muzzle
   climb build up. The sound plays at the simulated shot times.

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
| `[barrel]` | bore diameter, projectile travel, chamber volume; `chamber_shape` (`"cylinder"`, or `"case"` to solve inside the real case); outside diameter at the breech and muzzle (3D view only); rifling: `twist` (m per turn, negative for left-hand, 0 for a smooth bore), `groove_depth`, `freebore` (travel before the lands), `leade_angle` (forcing-cone half-angle, degrees); a bore evacuator: `evacuator_position` (travel from the seat to its nozzles, 0 = none), `evacuator_volume`, `evacuator_nozzles`, `evacuator_nozzle_diameter`, `evacuator_angle`; a revolver's `cylinder_gap` (to the barrel, 0 = none) and `cylinder_length` (case head to the cylinder's front) |
| `[case]` | case length, overall length, rim, extractor groove, base and shoulder diameters, shoulder position and angle, neck and body wall, head thickness, primer pocket (the solver uses it with `chamber_shape = "case"`); `material` (`"brass"` or `"steel"`); `combustible` (a felt body that burns with the charge, on a metal stub base `stub_length` long, which is all that is extracted) |
| `[projectile]` | mass, shot-start pressure, bore resistance, `engraving_pressure` (peak extra resistance while the rifling is cut, 0 = none); `drag_model` (G1, G7, or LR for a fin-stabilised long rod) and `ballistic_coefficient` (kg/m²; estimated from the shape if missing); shape: length, ogive length and `ogive_radius_ratio` (1 = tangent, >1 = secant), meplat diameter, boat-tail length and angle; optional variants (3D view only): hollow-point diameter/depth, cannelure position/width/depth, `jacket_thickness` with `core_material` (`"lead"`, `"steel"`, `"copper"` or `"tungsten"`; a solid steel or tungsten projectile is drawn in it) and `exposed_core_length` (soft point). `type = "apfsds"`: a long rod (`length` tail to tip) in a discarding sabot; `mass` is the launch package, and `penetrator_mass`, `penetrator_diameter`, `fin_span`, `fin_length`, `sabot_length` and `sabot_offset` (rod tail to the sabot's rear face, where the gas pushes) describe it |
| `[propellant]` | charge mass, force (impetus), covolume, γ, solid density, web thickness, burn-rate law `r = a·pⁿ`, form function `ψ(z) = χz(1+λz+μz²)`, gas molar mass (sets the gas temperature; used by the sound model). `composition` (`single_base`, `double_base`, `triple_base`) fills in the thermochemistry and burn law; `grain` (`tube`, `sphere`, `flake`, `7-perf`, `19-perf`) with `web`, `grain_length`, `grain_diameter`, `perforation_diameter` sets the form function. Explicit values always win. `flash_suppressant` (`potassium_sulfate`, `potassium_nitrate`, `potassium_cryolite`) with `suppressant_fraction` (share of the charge mass) puts out the secondary flash, at some impetus and more smoke |
| `[ignition]` | igniter pressure; `strike_energy` (what the firing pin has to hit the primer with: 0.15 J a rifle's, 0.06 to 0.08 J a pistol's); with the two-phase grain bed, the primer flash's `duration` and the `grain_ignition_temperature` |
| `[action]` | `type` (`"bolt"`, `"gas"`, `"direct_impingement"`, `"blowback"`, `"short_recoil"`, `"roller_delayed"`, `"lever_delayed"`, `"gas_delayed"`, `"chain"`, `"sliding_wedge"` or `"revolver"`); short recoil's `locking` (`"block"` or `"tilt"`, 3D view only); a striker's `striker_mass`, `striker_spring_preload`, `striker_spring_rate`, `striker_travel` and `striker_precock`; a revolver's `cylinder_mass` and `cylinder_radius`; gun mass and the mass that cycles (bolt and carrier, or slide); bolt stroke, return spring rate and preload, unlock travel, barrel mass (short recoil), `delay_ratio` and `bolt_head_mass` (roller/lever delayed), feeding drag, `friction` on the bolt group, restitution at the rear stop and in battery; `hammer` (on/off) with its `hammer_inertia`, `hammer_spring_torque` and `hammer_spring_rate`, `hammer_angle` (swing to the sear), `hammer_cock_travel`, `hammer_trip_travel` and `hammer_friction`, and a rate reducer's `rate_reducer_inertia` and `rate_reducer_angle`; gas port position and diameter, piston diameter, cylinder volume and piston stroke before it vents (gas, direct impingement and gas-delayed; for
direct impingement the "piston" is the bolt's tail in the carrier); `gas_tube_length` and `gas_tube_diameter` (direct impingement); chain gun: `chain_rate` (rounds/min with no load), `motor_power`, `drive_mass`, `chain_width`, `sprocket_radius`; sliding wedge: `cam_travel`, `extractor_ratio` (the block is `bolt_mass`, its drop `bolt_travel`, its closing spring `spring_rate` and `spring_preload`); bore height above the shoulder (or trunnions), butt to centre of mass, radius of gyration (muzzle rise) |
| `[trigger]` | `type` (`"single_action"`, `"double_action"`, `"double_action_only"` or `"striker"`), `mode` (`"auto"` for an automatic's burst, `"semi"` for a pull a shot), the single-action (or striker) `pull` and `travel`, the double-action `da_pull` and `da_travel`, `pull_time` (over a double-action pull, or to thumb-cock a hammer) and `split` (between shots fired as fast as the shooter can) |
| `[feed]` | `type` (`"single_stack"`, `"double_stack"`, `"quad_stack"`, `"drum"`, `"belt"`, `"dual_belt"`, `"hand"` for a loader's rack, or `"cylinder"` for a revolver's), `capacity`, the magazine spring and follower, feed angle and ramp, `hold_open`; a belt's links, hang and feed cam; a dual feed's `select`; a cylinder's `loading` (`"swing_out"` or `"gate"`) |
| `[shooter]` | `stance` (`"shoulder"`, `"hands"` for a handgun, `"free"` for free recoil, or `"mount"` for a mount's recoil system); body mass moving with the gun, shoulder (or arms') stiffness and damping, how hard the hold resists muzzle rise (stiffness and damping) |
| `[muzzle_device]` | `type` (`"none"`, `"brake"`, `"suppressor"` or `"flash_hider"`); length, outer diameter, number of baffles (prongs for a flash hider), baffle hole clearance over the bore, wall thickness, blast chamber length (suppressor), baffle cone angle, vent opening round the circumference (brake, flash hider), `flare_angle` (flash hider bore), mass. Missing sizes are scaled from the bore |
| `[mount]` | a mount's recoil system: `stroke` to the recoil stop, a spring (`spring_rate`, `spring_preload`), linear `damping`, `friction`, a hydropneumatic recuperator (`recuperator_pressure`, `recuperator_volume`, `recuperator_area`), a hydraulic buffer (`buffer_area`, `buffer_orifice` closing to `buffer_orifice_end` along the stroke, `counter_orifice` for the run-out, `oil_density`), the `counter_buffer` length, `stop_restitution`, and the elevation gear's `elevation_stiffness` and `elevation_damping` |
| `[appearance]` | `style` (`"rifle"`, `"ar15"`, `"ak"`, `"autocannon"`, `"tank"`, or the handguns' `"1911"`, `"beretta"`, `"polymer"`, `"revolver"` and `"single_action"`): how the 3D view dresses the gun; the solvers ignore it |
| `[solver]` | cell count, CFL number, time limits; `wall_losses` (friction and heat loss in the bore); `two_phase` (a moving grain bed lit by the primer's flame); `device_resolution` (2D cells across the bore), `device_time` (how long the muzzle device is solved in 2D), `gas_port_2d` (find the gas port's discharge coefficient in 2D) |

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
  followed the stretching mesh would be squeezed through the shoulder. The
  igniter's gas fills the chamber at the start, and every grain is alight.
  With `[solver] two_phase = true` the grains are a moving bed instead (see
  [Two-phase grain bed](#two-phase-grain-bed-gun_simgrainbedpy)). The flux treats the
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
  give their gas as it is born) is added to the push on the breech. Until shot
  start the case neck holds the projectile, so the gas's push on it comes back
  to the barrel (a sealed case doesn't recoil). Before the projectile leaves,
  the gun has given it `m v` and the gas about `ω v / 2`, as momentum
  conservation says.
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

### Two-phase grain bed (`gun_sim/grainbed.py`)

With `[solver] two_phase = true`, the grains are a second phase on the same
moving mesh as the gas, as in the two-fluid interior ballistics codes (Gough's
NOVA and its successors).

- **Grains that move.** Each cell's grains have their own velocity and cross
  the cell faces with it (a donor-cell flux, with Rusanov dissipation where
  the bed is packed). They can't pass the breech or the projectile; after
  exit they can be blown out of the muzzle unburnt. Lit and unlit grains are
  kept apart, so a few burning grains drifting into a cell don't light it.
- **Forces.** The gas pressure's push on a cell's contents is shared between
  gas and grains by the volume each takes up. A packed bed resists being
  squeezed further with an intergranular stress, zero below the packing it
  was loaded at and stiffening towards 85% solid, with compression waves at
  280 m/s in a just-packed bed. The bed pushes on the breech, the chamber
  shoulder and the projectile.
- **Interphase drag.** Gidaspow's law: Ergun's packed-bed drag below a gas
  fraction of 0.8, Wen and Yu's for a dilute cloud above. It is applied
  implicitly, so a dense bed locks gas and grains together without a tiny
  time step. It keeps momentum, and the energy it removes heats the gas. The
  grain size it needs comes from the form function: the grains' surface per
  unit volume is `2 ψ'(z) / (web (1 - ψ))`, which is 6/d for a sphere.
- **Flame spread from the primer.** The chamber starts full of cold gas at
  ambient pressure. The primer jets its hot gas (as much as
  `ignition.pressure` gives when it fills the space round the grains) through
  the flash hole into the first cell over `ignition.duration`. A grain lights
  when its surface reaches `ignition.grain_ignition_temperature`. The gas heats
  it with the packed-bed correlation `Nu = 2 + 0.4 Re^(2/3) Pr^(1/3)`, and its
  surface temperature follows from the heat it has absorbed (an integral
  solution for a semi-infinite solid). So the flame runs as fast as the hot
  gas is driven into the bed, and stagnant corners light late. Lit grains
  burn at their local pressure, and their gas joins the gas at the grain's
  velocity.

For the example rifle the flame runs from the flash hole to the projectile in
about 0.2 ms (0.23 ms in the cylinder chamber, 0.17 ms in the case, where the
hot gas is funnelled through the shoulder). Waiting for it costs about 0.1 ms
in the barrel and 1–1.5% of muzzle velocity (822 against 835 m/s in the
cylinder, 873 against 881 m/s in the case). Grains are carried down the bore
at a few hundred m/s, lagging the projectile, and about 1 mg is blown out of
the muzzle unburnt. A 2 MPa primer takes 0.31 ms to light everything, a
10 MPa one 0.19 ms. 50 and 200 cells agree on muzzle velocity to 0.25%. The
preset `configs/example_two_phase.toml` is the example rifle with the case
chamber and the bed turned on.

Not modelled: the grains' gravity (they lie on the bottom of a horizontal
case), their spread of burnt web within a cell (grains that mix share the mean
z), radiation from the primer, and heat lost into the grains after they
light. The thermal and ignition properties are generic figures for
nitrocellulose.

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
  - *direct_impingement*: locked like *gas*, but there is no piston. The port
    feeds a long thin gas tube, solved as a volume of its own. Its outlet's
    discharge coefficient falls with the tube's friction (0.8 / √(1 + f L/D),
    f = 0.03), and it loses heat to its wall at the Dittus–Boelter rate for the
    flow through it, so the gas arrives late and cooled. The tube empties into
    an expansion chamber between the carrier and the bolt's tail: the carrier
    is the cylinder and the locked bolt the piston, so the chamber pushes the
    carrier back and, through the bolt's lugs, the barrel forwards. Once the
    bolt unlocks it rides with the carrier and the chamber's pressure is
    internal to the bolt group, so it pushes nothing more; it vents through the
    carrier's holes after `gas_stroke`.
  - *blowback*: never locked. The breech pressure on the case head pushes the
    bolt from the start.
  - *short_recoil*: the barrel and slide recoil locked together until the
    barrel has moved `unlock_travel` and stops against the frame. The slide
    carries on, and picks the barrel up again on the way home.
  - *roller_delayed* and *lever_delayed*: delayed blowback with a two-part
    bolt. The breech pressure pushes a light bolt head from the start, but
    rollers (or a lever) bearing on the receiver make the heavy carrier move
    `delay_ratio` (K) times as fast. The head therefore feels the carrier as
    K² times its mass and opens slowly, and the receiver takes the rest of the
    push. Once the carrier has moved `unlock_travel` the rollers are in, the
    carrier pulls the head along (they share their momentum) and it runs on as
    a plain blowback. Head, carrier and gun are solved together from their
    kinetic energy, so momentum is kept exactly. K = 1 is a plain blowback.
  - *gas_delayed*: blowback held shut by gas. A port just ahead of the chamber
    (10% of the travel unless given) feeds a cylinder whose piston pushes the
    slide forwards. Opening the slide drives the piston in and compresses the
    gas, so the slide stays nearly shut until the bore pressure falls and the
    gas runs back out of the port.
- **Cycle.** The bolt ejects the case once it has come back a case length
  (plus 3 mm). It can pick up the next round once it has come back past a whole
  round, and drags `feed_force` while it chambers it, and `friction` (rails, a
  carrier tilted by its piston's off-axis push) all the way. Impacts at the
  rear stop and in battery are instantaneous, with a coefficient of
  restitution, shared between the bolt and the gun by their masses.
- **Hammer** (`hammer = true`). A hammer on a pivot in the receiver, with its
  own inertia and a spring (torque with it down, plus a rate per radian). It
  rests on the firing pin. Once the carrier has come back `hammer_trip_travel`
  its underside cams the hammer down, as a straight ramp over
  `hammer_cock_travel`, to 15% past the sear angle (`hammer_angle`). While they
  touch, the carrier carries the hammer's inertia (J (dφ/ds)²), feels its spring
  through the cam (dφ/ds × torque) and rubs on its face (`hammer_friction`). If
  the carrier pulls away faster than the spring can follow (at the rear stop)
  the hammer flies free, and going home it rides the carrier back up onto the
  sear. In a burst the closing carrier trips the auto sear in its last
  `hammer_trip_travel`. The hammer falls on its spring and the next shot fires
  0.3 ms after it reaches the firing pin, if it still has 0.15 J. If the
  carrier has bounced back out of battery, the hammer lands on it and rides it
  home: a light strike, and the burst stops.
  - A **rate reducer** (`rate_reducer_inertia`, the AKM's) is a weighted lever
    the hammer has to swing with it over the first `rate_reducer_angle` of its
    fall. It slows the fall by a few milliseconds, so the carrier's bounce has
    died before the hammer arrives.
  - Without a hammer, each shot of a burst fires 3 ms after the bolt is home.
- **Muzzle rise.** Every force along the bore acts `bore_height` above the
  shoulder, so the shot lifts the muzzle, and the bolt hitting the rear stop
  kicks it again.
- **Results**: recoil impulse, free-recoil velocity and energy, travel into
  the shoulder and peak shoulder force, muzzle rise, and for an automatic
  action its events (unlock, ejection, rear stop, feeding, back in battery),
  cycle time and cyclic rate. It reports when the action fails:
  - short stroking: the case is not ejected, no round is picked up, or the
    hammer is not cocked;
  - a light strike: the hammer reaches the firing pin with under 0.15 J;
  - battering: the bolt reaches the rear stop above 8 m/s;
  - unlocking with more than 20 MPa in the chamber;
  - a case backing more than 1 mm out of the chamber while it is still above
    30 MPa, as in a blowback with too light a bolt.

  The cyclic rate counts the bolt's travel and, with a hammer, its fall from
  the sear to the firing pin (otherwise a fixed 3 ms).

For the example rifle (4 kg) this gives 11.9 N·s of recoil, of which 2.5 N·s is
the gas jet. Free, the rifle recoils at 3.0 m/s with 18 J. Held, it goes about
17 mm into the shoulder with 1.24° of muzzle rise. The gas-operated preset
unlocks with 5.8 MPa left in the chamber and cycles in 41 ms, the bolt
reaching the rear stop at 5.0 m/s.

The M4A1 preset (`configs/m4a1.toml`: M855 from a 14.5" barrel, a carbine-length
gas system) leaves the muzzle at 885 m/s with a 408 MPa peak. The bolt unlocks
2.8 ms after ignition, well after the bullet has gone, with about 8 MPa left in
the chamber, and the carrier reaches the buffer at 6.5 m/s. The AKM (`configs/akm.toml`, M43 ball) gives
741 m/s at 313 MPa and the AK-74 (`configs/ak74.toml`, 7N6, with its brake)
901 m/s at 351 MPa; their long-stroke pistons bring the carrier to the rear
trunnion at 4.2 and 6.4 m/s. With their hammers, the AKs' rate reducers and
friction on the carriers (22 N, from the piston's push 30 mm over the bore
tilting them onto their rails; 12 N for the M4's buffer in its tube), the AKM
fires at about 620 rounds a minute (real: 600), the AK-74 at about 770 (real:
600 to 650) and the M4A1 at about 850 (real: 700 to 950). Without its rate
reducer the AK-74's hammer arrives while the carrier is still bouncing in
battery, and a burst stops on a light strike.

The roller-delayed preset, `configs/example_roller_delayed.toml` (the same
cartridge, a 1 kg bolt with a 0.15 kg head, K = 4), unlocks about 0.9 ms after
the projectile leaves with 28 MPa left in the chamber, and the bolt reaches the
rear stop at 5.4 m/s. The same bolt as a plain blowback reaches it at 23 m/s,
having let the case 28 mm out of the chamber above 30 MPa. A delayed blowback's case
always starts to move under pressure, which is why such rifles flute the
chamber; the warnings say so.

- **Bursts.** A self-loading action can fire several shots per trigger pull.
  Each fires when the tripped hammer reaches the firing pin (or 3 ms after the
  bolt is back in battery, without a hammer) on the one before, with the gun's
  motion and the gas cylinder carried over, so
  recoil and muzzle climb build up. The burst stops if a cycle fails. The
  example gas rifle fires at about 1,300 rounds a minute, its muzzle climbing
  about 0.9° a shot.
- **Gas port** and **muzzle device**: the port's discharge coefficient comes
  from a 2D solution of the port, and a device's mass is added to the gun
  (see below).

Not modelled: the carrier's free travel before it picks up the bolt (they move
as one), friction that changes along the stroke (it is a constant drag), a
hammer cam that isn't a straight ramp, the disconnector (the sear catches the
hammer as soon as it passes), extraction force (the
case leaves the chamber freely), heat loss in the gas cylinder, a delay ratio
that changes over the stroke (real roller and lever angles vary it a little),
and a non-linear shooter.

### 2D axisymmetric solver: muzzle devices and gas ports (`gun_sim/axisym.py`, `gun_sim/devices.py`)

Where the geometry really is two-dimensional, a 2D solver takes over from the
1D bore solver, coupled to it at their shared boundary.

- **Solver.** The compressible Euler equations in (x, r) for a mixture of air
  and propellant gas (a conserved mass fraction tracks the propellant). Finite
  volumes on a uniform grid of square cells (rings and cylinders, with the hoop
  term so gas at rest stays at rest). It uses HLL fluxes, MUSCL reconstruction
  (minmod) and SSP-RK2 time stepping, in float32 (the fluxes compiled with
  Numba, on several threads for the larger grids).
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
  - A *flash hider* is a solid collar on the muzzle, then prongs to an open
    front, with slots between them (cut through the wall, open by
    `vent_fraction`) and a bore that opens at `flare_angle`. It barely
    changes the recoil (it pushes the gun forwards by 0.04 N·s); its job is
    the flash (see *Muzzle flash and smoke* below).
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
cells across the bore), the projectile passing through the device, and
erosion. Afterburning (first-round pop, secondary flash) is solved in the
plume (below), not in the coupled device run, so it doesn't change the recoil
or the sound. The suppressor's sound reduction comes
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
numbers in the config always override the library. A flash suppressant (a
potassium salt, a percent or two of the charge) is added on top of the
composition. See the plume section. The values in the library
are illustrative textbook-range figures, not data for any real powder. See
`configs/example_7perf.toml`.

### Cannon: chain gun, sliding wedge, mount, evacuator and APFSDS

Two presets are cannon, and bring the systems they need.

**Mk44 Bushmaster II** (`configs/mk44_bushmaster_ii.toml`): 30x173 mm HEI-T, 0.363 kg at
1,086 m/s and 409 MPa from a 2.41 m barrel, dual-fed from two belts, on a soft mount.

- **Chain action** (`action.type = "chain"`). The motor, not the shot, works the bolt.
  The bolt carrier rides the master link of a chain that a DC motor drives round a
  rectangular track. Its force falls linearly with the chain's speed (`motor_power`
  peak, `chain_rate` with no load). Across the front of the track the bolt dwells
  locked in battery, and the shot is fired in the middle of that dwell. It is drawn
  back along one side, dwells open across the back while the feeder (driven off the
  same chain) draws the belt a link, and rams the next round along the other side.
  The bolt's travel is the track's s(q), so the gun, the bolt and the drive (rotor,
  gears and chain as `drive_mass`) are solved together from their kinetic energy.
  The bolt's mass going round the corners and the belt's weight slow the chain, so
  the gun fires a little under its no-load rate (about 199 rounds/min against 216).
  The drive is heard too: the motor's whine (`motor_rpm` with no load, geared down to
  the sprocket), its first pinion's mesh (`pinion_teeth`), the drive chain's links
  ticking onto the sprocket (`drive_chain_pitch`) and the brushes' hiss, all at the
  speed and load the simulation has the chain at, so the whine sags as the bolt loads
  the motor and surges as it lets go.
  While the bolt is locked, dS/dq = 0, so the shot pushes only the gun. The breech
  stays shut through the dwell, about 45 ms after exit (the bore is down to under
  5 MPa when it unlocks), which is the chain gun's protection against a hangfire.
  A motor too weak for the load stalls the drive.
- **Dual feed** (`feed.type = "dual_belt"`, `select = "left"` or `"right"`). A belt
  comes in from each side; the selected one feeds and the other waits a link out.
  Cases leave forwards, out of the bottom of the receiver.
- **Soft mount** (`shooter.stance = "mount"`, `[mount]`). A recoil adapter, a spring
  pack and damper with 35 mm of travel, takes the 160 kg gun back 24 mm at 41 kN
  peak, and returns it to battery in 34 ms.

**Rheinmetall Rh-120 L/55** (`configs/rh120_l55.toml`): a DM53-like APFSDS-T, an 8.35 kg
launch package with a 4.9 kg tungsten rod, at 1,756 m/s and 598 MPa from a 6.6 m smoothbore.

- **APFSDS** (`projectile.type = "apfsds"`). The gas drives the whole launch package and
  pushes on the sabot's rear face (`gun.seat`); the rod's fins reach back behind it into
  the propellant. At the muzzle the air strips the three sabot petals off (the 3D view
  throws them out and back), and the trajectory flies the rod alone: its mass and
  diameter, against `LR`, a long-rod drag curve with BC = m / d² (an illustrative curve:
  the rod loses about 59 m/s per km). The sound's crack is the rod's too. A smoothbore
  has no spin, so the rod is fin-stabilised and has no spin drift.
- **Combustible case** (`case.combustible`). The felt body burns with the charge (count
  its mass in the charge); only the steel stub base is extracted.
- **Recoil system** (`[mount]`). The 3.5 t of recoiling parts slide back in the cradle
  against a hydraulic buffer and a hydropneumatic recuperator. The buffer forces oil
  through an orifice (force rho A³ v² / (2 (Cd a)²)) that a throttling rod closes down
  along the stroke, so its force stays nearly level as the gun slows. The recuperator's
  gas is compressed polytropically (n = 1.3) as the gun recoils, and then runs it out
  again. The return oil goes through `counter_orifice`, and the counter-recoil buffer
  closes it to a tenth over the last `counter_buffer` before battery. The gun recoils
  307 mm (the stop is at 340) at up to 395 kN, and is back in battery after 0.52 s. The
  elevation gear holds the cradle's pitch: the jump is 0.2 mrad. A missing buffer hits
  the stop, and a weak recuperator leaves the gun out of battery; both are reported.
- **Semi-automatic sliding wedge** (`action.type = "sliding_wedge"`). The block stays
  locked while the gun recoils. As the gun runs out, the opening cam on the cradle
  catches the crank over the last `cam_travel` (120 mm) and drives the block down. The
  gun carries the block's inertia through the cam (the block's mass times the cam
  ratio squared), and its closing spring and friction, less its weight. In battery the
  block strikes the extractors, which throw the stub out backwards at `extractor_ratio`
  times its speed (3.9 m/s) and hold the block open for the loader. A run-out too weak
  for the cam leaves the breech part open.
- **Loader** (`feed.type = "hand"`). A ready rack of 15 rounds. On the range the loader
  takes each round from the rack, lines it up behind the breech and rams it; its rim
  trips the extractors and the block springs shut.
- **Bore evacuator** (`gun_sim/evacuator.py`, `barrel.evacuator_*`). A reservoir two-thirds
  of the way along the barrel, joined to the bore by six nozzles that lean 30° towards
  the muzzle. Once the projectile has passed them, the bore gas charges it through
  them (an orifice, from the gas the solvers record at the nozzles), to 4.1 MPa with
  182 g of gas. When the bore has blown down, the reservoir empties back through the
  same nozzles as jets up the bore. With the breech open, the jets' forward momentum
  flux J = mdot v cos(angle) draws air in at the breech and up the bore at the speed
  U where J = rho A U² (1 + K_entry + f L/D). It blows for 0.8 s. When the breech
  opens at 0.52 s it draws air at 38 m/s and sweeps the breech end clear in 0.12 s.
  If it had stopped by then, the fumes would come back into the turret, which is
  reported. The lumped model only records the bore gas at the nozzles while the
  projectile is in the bore, not in its blowdown, so its evacuator charges less and
  it reports the fumes coming back.

Bigger parts ring lower and longer in the mechanical sounds (their modes are divided by
(mass / 1 kg)^(1/3)), so the 3.5 t gun running out into battery is a deep clank.

Not modelled: the motor's electrical side and its start-up (the chain is already turning
at its free speed when the first shot fires), the feeder's own mechanism (its draw is a
straight ramp over the rear dwell), the stub's flight inside the turret, the turret's
own motion, the gas the evacuator takes from the bore during the shot, and the sabot's
aerodynamics (the petals' flight is drawn, not solved).

### Handguns: triggers, strikers and revolvers (`gun_sim/action.py`, `gun_sim/revolver.py`)

Five presets: the Colt M1911A1 (.45 ACP M1911 ball), the Beretta M9 (9x19 mm M882), the
Glock 17 (9x19 mm 124 gr), the Colt Anaconda (.44 Magnum 240 gr, 6") and the Colt Single
Action Army (.45 Colt 255 gr lead, 7½"). Each burn law is tuned to its published muzzle
velocity under its cartridge's maximum pressure; the masses, springs, travels and trigger
pulls are the published ones where there are any.

- **Trigger** (`[trigger]`). `type` is what a pull does: `single_action` only lets a
  cocked hammer go (the slide cocks it; a single-action revolver's is cocked by the
  thumb); `double_action` cocks it on the first pull and lets it go, after which the
  slide leaves it cocked (DA/SA, as the M9), while a double-action revolver's every pull
  cocks it; `double_action_only` cocks it every pull (nothing leaves it on the sear);
  `striker` finishes cocking a part-cocked striker and lets it go. `mode = "semi"` fires
  each shot with a pull of its own: once the slide is back in battery on a round (the
  disconnector holds the trigger off until then) and `split` after the last shot, the
  shooter pulls again. A double-action pull takes `pull_time` to draw the hammer back
  before it falls. `"auto"` is an automatic's burst, as before. The work of the pulls
  (pull weight times travel, double action and single) is reported.
- **Striker** (`trigger.type = "striker"`, `[action] striker_*`). The striker is a mass on
  a spring in the slide. Let go from `striker_travel` back, it hits the primer with the
  spring's energy, F0 L + k L^2 / 2, after the time the spring takes to drive it there
  (the lock time). As the slide closes, the trigger bar catches the striker's lug the last
  `striker_precock` of its travel from battery, so the slide compresses the striker
  spring that far against it, and comes home slower for it.
- **Primer** (`ignition.strike_energy`). A light strike is now measured against the
  primer's own: a rifle primer's 0.15 J, a pistol primer's softer cup 0.06 to 0.08 J. A
  weak striker spring fails to fire it.
- **Revolver** (`action.type = "revolver"`, `feed.type = "cylinder"`). Nothing moves under
  the shot: it pushes the whole gun. Between shots the hammer is cocked over `pull_time`
  (by the trigger, or the single action's thumb), and the hand turns the cylinder a
  chamber on over the middle of its swing (20 % to 85 % of it). The cylinder stop then
  locks it, taking its spin: half the cylinder's moment of inertia (with its rounds and
  cases, `cylinder_mass` and the chambers `cylinder_radius` out) times the hand's speed
  squared, so a quicker double-action pull slams it onto the stop harder. The hammer
  then falls on the round now under it, or, if the cylinder has run dry, on a fired case.
  The cases stay in their chambers.
- **Cylinder gap** (`barrel.cylinder_gap`, `cylinder_length`). While the bullet is in its
  chamber it seals the gas in; once its base has left the cylinder's front face, gas
  escapes through the gap between it and the barrel all round: an annular slot of the
  bore's circumference, as an orifice (choked, almost always) at the gas's pressure and
  temperature there. Both solvers take out its mass and the enthalpy it carries (the fluid
  model from the cell at the gap, in the bore and during blowdown; the lumped model at the
  Lagrange pressure there). The jet goes out sideways, so it doesn't push the gun along the
  bore, but the bullet loses some speed: the Anaconda's 0.15 mm gap lets out about 7 % of
  its gas, the single action army's, behind a slow bullet in a long barrel, nearly a
  fifth. The sound model feeds that gas to a second spherical blast solution beside the
  shooter's hands, heard without the muzzle jet's forward throw, a little before the
  muzzle blast; the 3D view flashes and smokes it over the frame. The bullet's jump from
  its chamber across the gap into the forcing cone is the barrel's `freebore` and
  `leade_angle`.
- **Hands** (`shooter.stance = "hands"`). As a shoulder: a spring and damper to the body,
  the hands and forearms moving with the gun, and the wrists resisting the muzzle flip.
  `bore_height` is the bore over the web of the hand, and a handgun's is high for its
  mass, so the shot turns more of its recoil into muzzle flip: a 1911's flips about 8°,
  an Anaconda's about 12°, a single action army's, over its plow-handle grip, about 14°.
- **Slide and barrel** (`short_recoil`, `locking`). The pistols are short recoil: the
  barrel and slide recoil locked together for `unlock_travel` (by then the bullet has gone
  and the chamber is down to 15 MPa or less), the barrel stops, and the slide runs on, cocking
  the hammer (or the striker) and stripping the next round from a magazine that rakes back
  in the grip. `locking` only changes the 3D view.

Between a semi-automatic's or revolver's shots the action rests, so the simulation steps
coarsely there; a revolver's six-shot string solves in well under a second.

Not modelled: the trigger's own mechanism (its pull is a weight over a travel; the
disconnector is the rule that a pull fires only with the slide home); the shooter's
pull disturbing the aim; the cylinder's timing (it always carries up to lock); the gas
cutting the top strap; lead and powder fouling.

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
  - the secondary flash's pop (the flash itself is solved, in gun_sim/plume.py, but not its sound).
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

### Muzzle flash and smoke (`gun_sim/plume.py`)

The firing range's flash and smoke are solved, not drawn. After the shot, the
bore's blowdown history (the gas at the muzzle, moment by moment) is fed into
the 2D solver on a grid that holds the end of the barrel, the muzzle device
(drawn exactly as `devices.py` draws it) and the air out to some 85 bores in
front and 30 around.

- **Stretched grid.** Cells are fine round the muzzle and device and grow by
  7 % per cell away from them, up to 8 fine cells across, so the grid reaches
  the fireball at little cost. `solver.plume_resolution` (cells across the
  bore at the muzzle, default 2) and `solver.plume_time` (default 2 ms after
  exit) set it; 2 runs in a few seconds, 4 matches the device grid and takes
  4 to 5 times as long.
- **Afterburning.** Gun propellant gas is fuel-rich: a third or more of it is
  CO and H2 (`propellants.PRODUCTS`, by family). A sixth conserved scalar
  carries the unburnt fuel. Where the gas has mixed with air and is hot
  enough, it burns with the air's oxygen at a one-step Arrhenius rate (CO
  oxidation's activation temperature; lights within tens of microseconds at
  about 1100 K, hardly at all below 900 K) and releases its heat. Burning
  stops at 2600 K, where the products come apart as fast as they form.
- **What comes out.** Frames of the temperature and the propellant gas's
  density (48 of them, densest just after exit). The 3D view spins them about
  the bore axis and ray-marches them: gas glows by Wien's law with a blackbody
  colour, and carries the smoke, which shows once it has mixed and cooled.
  The flash's light on the scene is the total glow. Noise breaks up the
  axisymmetry.
- **After the window**, the cloud is a momentum puff (size ~ t^1/4,
  Richards 1965): the view scales the last frame up about the exit at the rate
  it was growing, thins and cools it as it takes in air, and lifts it by its
  warmth. Gas still in the bore or the device then seeps out of the exit with
  the time constant of the bore's (or the device's) outflow.

For the example rifle (2 cells across the bore, 2 ms):

| Device | Afterburning | Brightest glow | Smoke |
| --- | --- | --- | --- |
| None | 12 kJ, fireball 0.2 to 0.4 m out | 1 | thrown forwards, 0.6 g seeps out after |
| Brake | 12 kJ, a ring sheet out of the vents | about 3 | spreads sideways, not forwards |
| Suppressor | 0.3 kJ (the can's air burns away) | about 1/100 | 2.5 g seeps out of the front over ~8 ms |
| Flash hider | 11.8 kJ | 0.95 | thrown forwards a little further, 0.6 g seeps out after |

A flash hider's effect needs a finer grid to show. At 4 cells across the bore
the bare muzzle's jet ends in a Mach disk that shocks the gas to about
2840 K, hotter than burning can make it (2600 K, where the products come
apart): that is the intermediate flash. In the flash hider the jet expands
before it meets the air, and nothing in the plume gets hotter than burning
makes it. The fireball shrinks less: afterburning falls by 6% (12% with a 10°
flare) and the brightest glow by 12% (29%), because this rifle's gas leaves the
muzzle hot enough to reignite on mixing with air, shock or no shock. That is
the job of flash-suppressant additives.

**Flash suppressants.** `[propellant] flash_suppressant` names a potassium
salt (`potassium_sulfate`, `potassium_nitrate`, `potassium_cryolite`;
`propellants.SUPPRESSANTS`) making up `suppressant_fraction` of the charge
mass. The potassium it frees into the gas recombines the radicals that carry
the CO/H2 flame, which in the one-step chemistry divides the burning rate by
`1 + I·Y`. Here `Y` is the share of propellant gas in the cell (it carries the
potassium, so the inhibitor thins out as the gas mixes with air) and `I` is
proportional to the kg of potassium per kg of gas. The salt makes no gas and
takes heat from the flame, so the impetus and the flame temperature drop
(`Propellant.impetus`). Its particles go with the gas without adding pressure,
so R is per kg of gas plus particles. The particles also thicken the smoke.
Potassium nitrate is an oxidizer instead. It gives heat, costs almost no
impetus, and burns some of the CO in the bore. `force`, `molar_mass` and the
composition stay those of the powder without the salt.

The example rifle (2 cells across the bore, 2 ms):

| Suppressant | Muzzle velocity | Afterburning | Brightest glow | Smoke |
| --- | --- | --- | --- | --- |
| None | 835 m/s | 12 kJ | 1 | 1 |
| 0.5% potassium sulfate | 830 m/s | 8.1 kJ | about 2.5 | ×2.3 |
| 1% potassium sulfate | 824 m/s | 0.4 kJ | about 1/40 | ×3.5 |
| 2% potassium sulfate | 813 m/s | 0.1 kJ | about 1/45 | ×6 |
| 1% potassium nitrate | 832 m/s | 5.1 kJ | 0.8 | ×2.7 |
| 1% potassium cryolite | 824 m/s | 0.3 kJ | about 1/40 | ×3.5 |

Reignition is all or nothing. Strength `I` (`propellants.INHIBITION`) was set
so that about 1% of sulfate puts this rifle's flash out, as a percent or two
does in practice. Half that delays ignition until more air has mixed in, and
the late fireball comes out brighter. That result is the model's and is not
checked against data. With a suppressant the remaining glow is the primary
flash, the hot gas itself.

The fireball's size and timing look like high-speed footage of unsuppressed
rifles, but the numbers are only as good as the one-step chemistry and a grid
a couple of cells across the bore. The smoke's density (how much of the gas
is particles and condensate) and the glow's brightness are scale factors in
`volume.js`, not physics.

## Project layout

```
gun_sim/
  config.py      gun definition dataclasses + TOML loading
  fluid.py       1D finite-volume interior ballistics solver
  grainbed.py    two-phase grain bed: moving grains, interphase drag, flame spread from the primer
  chamber.py     chamber cross-section along the axis (cylinder, or the inside of the case)
  lumped.py      0-D reference model
  action.py      recoil and action cycling: gun, bolt, gas system, shooter, triggers, strikers, bursts
  revolver.py    a revolver's cylinder (geometry, inertia) and the gas lost through its gap
  feed.py        magazines, belts, a loader's rack and a revolver's cylinder; feed angle and jams
  axisym.py      2D axisymmetric compressible flow solver (face apertures for walls and ports)
  kernels.py     the two flow solvers' inner loops, compiled with Numba
  parallel.py    worker processes, so a shot's separate solves run at the same time
  devices.py     muzzle brake/suppressor/flash hider and gas port geometry, coupling to the bore, discharge coefficient
  evacuator.py   bore evacuator: charging from the bore, the jets, and how they sweep the fumes out
  plume.py       muzzle flash and smoke: the bore's outflow solved in 2D into the air, with afterburning
  propellants.py propellant compositions and grain shapes -> form function
  exterior.py    point-mass trajectory solver: G1/G7 drag, atmosphere, zeroing, range tables
  rifling.py     engraving resistance vs travel, spin-up, moment of inertia, stability, spin drift
  terminal.py    terminal ballistics: penetration into AR500 and RHA (rigid, eroding, cratering), RHAe
  cartridges.py  library of cartridges (metric and imperial names), their dimensions and loads
  designer.py    easy mode: builds and tunes a whole gun from a cartridge, a load and a kind of gun
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
      js/app.js          workshop, range and analysis tabs, results, charts wiring
      js/easy.js         easy mode: cartridge, load, gun and barrel pickers, performance and notes
      js/target.js       target tab: steel plate, verdict, cross-section, penetration against range
      js/units.js        metric and imperial display units
      js/fields.js       editor sections, slider ranges and help text
      js/backend.js      pywebview bridge or HTTP, whichever is present
      js/audio.js        Web Audio playback: reverb, hearing protection, limiter, bursts
      js/viewer3d/       WebGL 2 renderer, lathe (surface of revolution) mesher,
                         procedural case/primer/projectile profiles, cartridge viewer,
                         gun.js (barrel, receiver, bolt, stock), handgun.js (pistol slides and frames,
                         revolver frames and cylinders), feed.js (magazines, belts, racks), meshops.js,
                         range.js (the animated shot and recoil),
                         volume.js (ray-marched plume field, smoke and bore gas)
configs/         example gun definitions (shown as presets in the UI)
tests/           pytest suite (physics checks + UI server API)
launcher.py      entry script for the exe build
gun_sim.spec     PyInstaller configuration
build_exe.ps1    one-command Windows build
```

## Why Python?

- NumPy makes the solver short and readable. The steps are small (a few
  hundred cells), so in NumPy the time goes on the calls rather than the
  arithmetic: the inner loops (fluxes, cell states, wall losses, and the 2D
  solver's step) are compiled with Numba in [kernels.py](gun_sim/kernels.py),
  which makes a shot 3 to 4 times faster (an AKM: 2.5 s down to 0.6 s for the
  bore). The first run compiles them, which takes several seconds (once per
  install or build: they are cached). `GUN_SIM_JIT=0` runs the NumPy versions,
  which the tests hold the compiled ones to.
- The scientific tooling (plotting, SciPy, notebooks for experiments) is
  hard to beat for a physics project still being worked out.

## Roadmap

- [x] Higher-order solver (MUSCL reconstruction, HLLC flux, SSP-RK time stepping)
- [x] Real chamber geometry: area that varies along the axis (bottleneck case); freebore and forcing cone set where engraving happens
- [x] Two-phase grain bed: grains that move, interphase drag, flame spread from the primer
- [x] Propellant library (single, double and triple base; multi-perforated grain geometries)
- [x] Heat loss to the barrel wall and barrel heating
- [x] Rifling and engraving forces, projectile spin, gyroscopic stability and spin drift
- [x] Sound synthesis from the fluid simulation (blowdown, muzzle blast, crack, propagation, binaural)
- [x] Sound of muzzle devices and suppressors
- [x] 2D axisymmetric solver for muzzle devices, suppressors and gas ports, coupled to the bore
- [x] Action cycling (gas, recoil, blowback) and recoil impulse; the gun recoils and pitches in the 3D view
- [x] Mechanical sounds from the action cycle; burst fire from the action simulation
- [x] Delayed blowback: roller, lever and gas-delayed
- [ ] Gas-port flow in full 3D; a finer 2D grid (compiled kernels)
- [x] External ballistics (drag models, trajectory)
- [x] Procedural 3D cartridge (case, primer, projectile) with cutaway
- [x] Use the case geometry in the solver (chamber volume and area profile from `[case]`)
- [x] 3D barrel, chamber and bolt action; animate the projectile, gas, flash, smoke and bolt cycle from a shot
- [x] Muzzle flash and smoke solved in 2D from the bore's outflow, with afterburning, through brakes and suppressors
- [x] Flash hiders
- [ ] Flash-suppressant propellant additives; afterburning in the coupled device run (sound, recoil)
- [x] Projectile variants: secant ogive, hollow point, cannelure, jacket/core section
- [x] Cannon: chain gun, sliding-wedge breech, mount recoil systems, bore evacuator, APFSDS, combustible cases
- [x] Handguns: single action, DA/SA, double action only and striker-fired triggers, semi-automatic strings, revolvers with cylinder indexing and gap leakage, the hands stance
- [ ] Richer GUI: side-by-side gun comparison, parameter sweeps, live animation of the bore flow

## Disclaimer

This is a physics and education project. The example values are generic and
illustrative. Do not use this software to develop ammunition loads.
