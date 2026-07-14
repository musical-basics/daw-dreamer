"""Phase 1 render harness: deterministic sample-based rendering via DawDreamer.

Design constraints (see implementation-plan.md, "Architectural invariants"):
- render() is a pure function of RenderSpec: same spec -> bit-identical WAVs.
- Per-stem WAVs are rendered alongside the master from day one.
- Each track renders through its own DawDreamer sampler; gain/pan/summing
  happen in numpy so stems and master are exact and reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import dawdreamer as daw
import numpy as np
import soundfile as sf

BLOCK_SIZE = 512
# DawDreamer's sampler plays the raw sample when triggered at this MIDI note
# and repitches for other notes.
SAMPLER_CENTER_NOTE = 60


@dataclass(frozen=True)
class Note:
    pitch: int = SAMPLER_CENTER_NOTE
    velocity: int = 100
    start_beats: float = 0.0
    # None -> hold for the full sample length (one-shot drum behavior)
    duration_beats: float | None = None


@dataclass(frozen=True)
class Track:
    name: str
    sample_path: str
    notes: tuple[Note, ...] = ()
    gain_db: float = 0.0
    pan: float = 0.0  # -1 (hard left) .. +1 (hard right)


@dataclass(frozen=True)
class RenderSpec:
    bpm: float
    duration_beats: float
    tracks: tuple[Track, ...] = ()
    sample_rate: int = 44100
    tail_seconds: float = 1.0


def _load_sample(path: str, sample_rate: int) -> np.ndarray:
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    if file_sr != sample_rate:
        raise ValueError(
            f"{path} is {file_sr}Hz but the spec renders at {sample_rate}Hz; "
            "resample the file (Phase 1 does not resample, to stay bit-exact)"
        )
    data = np.ascontiguousarray(data.T)  # (channels, samples)
    if data.shape[0] == 1:
        data = np.vstack([data, data])
    return data


def _gain_pan(audio: np.ndarray, gain_db: float, pan: float) -> np.ndarray:
    gain = 10.0 ** (gain_db / 20.0)
    theta = (pan + 1.0) * math.pi / 4.0  # constant-power pan law
    left = gain * math.cos(theta) * math.sqrt(2.0)
    right = gain * math.sin(theta) * math.sqrt(2.0)
    return audio * np.array([[left], [right]], dtype=np.float32)


def _render_track(
    engine: daw.RenderEngine, track: Track, spec: RenderSpec, total_seconds: float
) -> np.ndarray:
    data = _load_sample(track.sample_path, spec.sample_rate)
    sample_seconds = data.shape[1] / spec.sample_rate
    seconds_per_beat = 60.0 / spec.bpm

    sampler = engine.make_sampler_processor(track.name, data)
    for note in track.notes:
        start = note.start_beats * seconds_per_beat
        if note.duration_beats is None:
            duration = sample_seconds
        else:
            duration = note.duration_beats * seconds_per_beat
        sampler.add_midi_note(note.pitch, note.velocity, start, duration)

    engine.load_graph([(sampler, [])])
    engine.render(total_seconds)
    audio = engine.get_audio().astype(np.float32)
    return _gain_pan(audio, track.gain_db, track.pan)


def render(spec: RenderSpec, out_dir: str | Path) -> dict[str, Path]:
    """Render spec to out_dir. Returns {'master': path, '<track>': stem path, ...}."""
    out_dir = Path(out_dir)
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    engine = daw.RenderEngine(spec.sample_rate, BLOCK_SIZE)
    engine.set_bpm(spec.bpm)
    total_seconds = spec.duration_beats * (60.0 / spec.bpm) + spec.tail_seconds

    paths: dict[str, Path] = {}
    stems: list[np.ndarray] = []
    for track in spec.tracks:
        audio = _render_track(engine, track, spec, total_seconds)
        stems.append(audio)
        stem_path = stems_dir / f"{track.name}.wav"
        sf.write(stem_path, audio.T, spec.sample_rate, subtype="FLOAT")
        paths[track.name] = stem_path

    length = max((s.shape[1] for s in stems), default=int(total_seconds * spec.sample_rate))
    master = np.zeros((2, length), dtype=np.float32)
    for stem in stems:
        master[:, : stem.shape[1]] += stem

    peak = float(np.max(np.abs(master))) if stems else 0.0
    if peak > 1.0:
        raise ValueError(
            f"master peaks at {peak:.2f} (>1.0); lower track gain_db values — "
            "Phase 1 refuses to clip or silently normalize"
        )

    master_path = out_dir / "master.wav"
    sf.write(master_path, master.T, spec.sample_rate, subtype="FLOAT")
    paths["master"] = master_path
    return paths
