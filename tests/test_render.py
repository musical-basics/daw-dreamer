import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from daw_engine import Note, RenderSpec, Track, render

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "assets" / "samples"


def make_spec() -> RenderSpec:
    return RenderSpec(
        bpm=120.0,
        duration_beats=8.0,
        tracks=(
            Track(
                name="kick",
                sample_path=str(SAMPLES / "kick.wav"),
                notes=tuple(Note(start_beats=float(b), velocity=110) for b in range(8)),
                gain_db=-6.0,
            ),
            Track(
                name="bass",
                sample_path=str(SAMPLES / "bass.wav"),
                notes=(Note(pitch=58, start_beats=0.0, duration_beats=4.0),),
                gain_db=-9.0,
                pan=-0.3,
            ),
        ),
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_produces_audio(tmp_path):
    paths = render(make_spec(), tmp_path)
    assert set(paths) == {"kick", "bass", "master"}
    audio, sr = sf.read(paths["master"], always_2d=True)
    assert sr == 44100
    # 8 beats at 120 BPM = 4s, plus the 1s tail
    assert audio.shape[0] == pytest.approx(5 * 44100, abs=44100 // 2)
    assert np.max(np.abs(audio)) > 0.05, "render is silent"
    assert np.max(np.abs(audio)) <= 1.0, "render clips"


def test_render_is_deterministic(tmp_path):
    paths_a = render(make_spec(), tmp_path / "a")
    paths_b = render(make_spec(), tmp_path / "b")
    for name in paths_a:
        assert file_hash(paths_a[name]) == file_hash(paths_b[name]), (
            f"{name} differs between identical renders"
        )


def test_stems_sum_to_master(tmp_path):
    paths = render(make_spec(), tmp_path)
    master, _ = sf.read(paths["master"], always_2d=True, dtype="float32")
    total = np.zeros_like(master)
    for name, path in paths.items():
        if name == "master":
            continue
        stem, _ = sf.read(path, always_2d=True, dtype="float32")
        total[: stem.shape[0]] += stem
    np.testing.assert_allclose(total, master, atol=1e-6)


def test_gain_change_changes_output(tmp_path):
    spec = make_spec()
    quieter = RenderSpec(
        bpm=spec.bpm,
        duration_beats=spec.duration_beats,
        tracks=(
            Track(
                name=spec.tracks[0].name,
                sample_path=spec.tracks[0].sample_path,
                notes=spec.tracks[0].notes,
                gain_db=-12.0,
            ),
        )
        + spec.tracks[1:],
    )
    loud = render(spec, tmp_path / "loud")
    quiet = render(quieter, tmp_path / "quiet")
    assert file_hash(loud["master"]) != file_hash(quiet["master"])
