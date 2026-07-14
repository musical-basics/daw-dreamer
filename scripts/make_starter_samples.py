"""Generate the deterministic starter sample pack into assets/samples/.

Synthesized with numpy from fixed seeds so the repo carries no third-party
audio and tests are reproducible on any machine.
"""

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "samples"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds), dtype=np.float64) / SR


def kick() -> np.ndarray:
    t = _t(0.6)
    freq = 45.0 + 105.0 * np.exp(-t * 35.0)  # 150Hz pitch drop into a 45Hz body
    phase = 2.0 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t * 9.0)
    click = np.exp(-t * 400.0) * 0.4
    return np.tanh(1.8 * (body + click)) * 0.9


def snare() -> np.ndarray:
    t = _t(0.35)
    rng = np.random.default_rng(2001)
    noise = rng.standard_normal(t.size)
    noise = np.diff(noise, prepend=0.0)  # brighten
    noise *= np.exp(-t * 22.0)
    tone = np.sin(2.0 * np.pi * 185.0 * t) * np.exp(-t * 30.0)
    x = 0.55 * noise / np.max(np.abs(noise)) + 0.5 * tone
    return x * 0.85


def hat() -> np.ndarray:
    t = _t(0.12)
    rng = np.random.default_rng(2002)
    noise = rng.standard_normal(t.size)
    for _ in range(3):  # crude but deterministic highpass
        noise = np.diff(noise, prepend=0.0)
    noise /= np.max(np.abs(noise))
    return noise * np.exp(-t * 55.0) * 0.5


def bass() -> np.ndarray:
    t = _t(1.2)
    f0 = 261.63 / 4.0  # C2 so sampler center note 60 maps to a playable register
    saw = 2.0 * ((f0 * t) % 1.0) - 1.0
    out = np.zeros_like(saw)
    state = 0.0
    alpha = 0.06  # one-pole lowpass to tame the top end
    for i, s in enumerate(saw):
        state += alpha * (s - state)
        out[i] = state
    env = np.minimum(t * 200.0, 1.0) * np.exp(-t * 1.2)
    return out * env * 0.8


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in [("kick", kick), ("snare", snare), ("hat", hat), ("bass", bass)]:
        path = OUT / f"{name}.wav"
        sf.write(path, fn().astype(np.float32), SR, subtype="FLOAT")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
