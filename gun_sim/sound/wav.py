"""Write a synthesised shot to a .wav file (standard library only)."""

from __future__ import annotations

import wave

import numpy as np

from .synth import Sound


def write_wav(sound: Sound, path, full_scale: float | None = None) -> float:
    """Write 16-bit stereo. full_scale is the pressure (Pa) that maps to 0 dBFS;
    None normalises the loudest ear to -1 dBFS. Louder samples are clipped,
    as a real recorder would. Returns the full-scale pressure used."""
    stereo = np.stack((sound.left, sound.right), axis=1)
    if full_scale is None:
        full_scale = float(np.max(np.abs(stereo))) / 10 ** (-1 / 20) or 1.0
    pcm = np.clip(stereo / full_scale, -1.0, 1.0)
    data = np.round(pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sound.sample_rate)
        w.writeframes(data.tobytes())
    return full_scale
