"""Where the shot is heard from, and in what air.

Coordinates: the muzzle is the origin, x points downrange along the bore,
y to the shooter's left and z up. Angles are in degrees, lengths in metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

R_AIR = 287.05     # J/(kg K)
GAMMA_AIR = 1.4

# Effective flow resistivity of the ground (Pa s/m^2), for the Delany-Bazley
# impedance model. "none" removes the ground (free field).
GROUNDS = {
    "concrete": 2e7,
    "dirt": 5e5,
    "grass": 2e5,
    "forest floor": 4e4,
    "snow": 2e4,
    "none": None,
}


@dataclass
class SoundSettings:
    # Listener
    distance: float = 0.0         # m, muzzle to the listener's head; 0 = the shooter's ear
    angle: float = 175.0          # deg from the bore axis: 0 downrange, 90 right, 180 behind (negative = left)
    facing: float = 0.0           # deg, the way the listener looks: 0 downrange, 90 to the right
    listener_height: float = 1.5  # m above the ground
    muzzle_height: float = 1.45   # m above the ground
    ground: str = "grass"
    # Atmosphere
    temperature: float = 15.0     # deg C
    humidity: float = 50.0        # % relative
    pressure: float = 101325.0    # Pa
    # Model
    sample_rate: int = 48000
    blast_time: float = 0.025     # s of muzzle blast/blowdown simulated after exit
    blast_cells: int = 400        # cells in the spherical blast solver
    blast_radius: float = 2.0     # m, outer edge of the blast solver
    # Empirical: the muzzle gas cloud is thrown forward, which makes the blast
    # louder and sharper ahead of the muzzle than behind it. This is its initial
    # speed as a fraction of the speed of sound.
    convection_mach: float = 0.35
    # Mechanical sounds of the action (hammer, bolt, the case landing), from gun_sim.action.
    action_sounds: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> SoundSettings:
        data = dict(data or {})
        preset = data.pop("preset", None)
        base = dict(PRESETS[preset]) if preset else {}
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown sound settings: {', '.join(sorted(unknown))}")
        base.update(data)
        s = cls(**base)
        s.validate()
        return s

    def validate(self) -> None:
        if self.ground not in GROUNDS:
            raise ValueError(f"unknown ground {self.ground!r}; choose from {', '.join(GROUNDS)}")
        if self.distance != 0 and not 0.05 <= self.distance <= 2000:
            raise ValueError("listener distance must be between 0.05 m and 2 km (0 = at the shooter's ear)")
        if self.listener_height < 0 or self.muzzle_height < 0:
            raise ValueError("heights must not be negative")
        if not -60 <= self.temperature <= 60:
            raise ValueError("temperature must be between -60 and 60 °C")
        if not 0 <= self.humidity <= 100:
            raise ValueError("humidity must be between 0 and 100 %")
        if not 30e3 <= self.pressure <= 120e3:
            raise ValueError("air pressure must be between 30 and 120 kPa")
        if not 8000 <= self.sample_rate <= 192000:
            raise ValueError("sample rate must be between 8 and 192 kHz")
        if not 100 <= self.blast_cells <= 5000:
            raise ValueError("blast cells must be between 100 and 5000")
        if not 0.3 <= self.blast_radius <= 20:
            raise ValueError("blast radius must be between 0.3 and 20 m")
        if not 0.002 <= self.blast_time <= 0.2:
            raise ValueError("blast time must be between 2 and 200 ms")
        if not 0 <= self.convection_mach < 0.9:
            raise ValueError("convection Mach must be between 0 and 0.9")

    # --- air ---
    @property
    def temperature_k(self) -> float:
        return self.temperature + 273.15

    @property
    def air_density(self) -> float:
        return self.pressure / (R_AIR * self.temperature_k)

    @property
    def sound_speed(self) -> float:
        return math.sqrt(GAMMA_AIR * R_AIR * self.temperature_k)

    # --- geometry ---
    def resolved(self, travel: float) -> SoundSettings:
        """A copy with distance 0 replaced by the shooter's ear for a barrel of this travel."""
        return self if self.distance > 0 else replace(self, distance=shooter_distance(travel))

    def listener_position(self) -> tuple[float, float, float]:
        """(x, y, z) of the listener's head relative to the muzzle."""
        a = math.radians(self.angle)
        horiz = self.distance  # the angle is measured in the horizontal plane
        dz = self.listener_height - self.muzzle_height
        if abs(dz) < horiz:
            horiz = math.sqrt(horiz**2 - dz**2)
        return horiz * math.cos(a), -horiz * math.sin(a), dz


# Listener presets. The shooter's ear is a little behind and beside the muzzle;
# "distance" for it is filled in from the barrel length (see shooter_distance).
PRESETS: dict[str, dict] = {
    "shooter": dict(distance=0.0, angle=172.0, facing=0.0, listener_height=1.5, muzzle_height=1.45),
    "spotter": dict(distance=1.5, angle=-135.0, facing=0.0, listener_height=1.5, muzzle_height=1.45),
    "bystander": dict(distance=10.0, angle=90.0, facing=-90.0, listener_height=1.7, muzzle_height=1.45),
    "downrange": dict(distance=100.0, angle=1.5, facing=180.0, listener_height=1.7, muzzle_height=1.45),
    "far": dict(distance=400.0, angle=60.0, facing=-120.0, listener_height=1.7, muzzle_height=1.45),
}

PRESET_LABELS = {
    "shooter": "Shooter (cheek on stock)",
    "spotter": "Spotter, 1.5 m behind-left",
    "bystander": "Bystander, 10 m to the side",
    "downrange": "Downrange, 100 m, 2.6 m off the path",
    "far": "Far away, 400 m",
}


def shooter_distance(travel: float) -> float:
    """Muzzle-to-ear distance for a shooter: the barrel plus the action/receiver and stock to the cheek."""
    return travel + 0.25
