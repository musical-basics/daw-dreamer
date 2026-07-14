import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml

from daw_engine import IRError, compile_ir, load_ir
from daw_engine.compiler import ir_to_spec
from daw_engine.ir import parse_ir

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "first_beat.yaml"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def example_raw() -> dict:
    return yaml.safe_load(EXAMPLE.read_text())


# --- parsing and structure ---


def test_example_parses():
    ir = load_ir(EXAMPLE)
    assert ir.title == "First Beat"
    assert ir.total_bars == 12
    assert ir.section_start_bar("main") == 4
    assert ir.sections[1].intent.energy == 0.8


def test_spec_timing():
    spec = ir_to_spec(load_ir(EXAMPLE))
    assert spec.duration_beats == 48.0
    bass = next(t for t in spec.tracks if t.name == "bass")
    # bass clip starts at section 'main' = bar 4 = beat 16
    assert min(n.start_beats for n in bass.notes) == 16.0
    kick = next(t for t in spec.tracks if t.name == "kick")
    # intro pattern loops every bar: hits at beats 0 and 2.5 of each intro bar
    intro_kicks = [n.start_beats for n in kick.notes if n.start_beats < 16]
    assert intro_kicks == [0.0, 2.5, 4.0, 6.5, 8.0, 10.5, 12.0, 14.5]


# --- compilation ---


def test_example_compiles_and_is_deterministic(tmp_path):
    paths_a = compile_ir(EXAMPLE, tmp_path / "a")
    paths_b = compile_ir(EXAMPLE, tmp_path / "b")
    assert set(paths_a) == {"kick", "snare", "hat", "bass", "master"}
    for name in paths_a:
        assert file_hash(paths_a[name]) == file_hash(paths_b[name])
    audio, sr = sf.read(paths_a["master"], always_2d=True)
    # 48 beats at 90 BPM = 32s + 1s tail
    assert audio.shape[0] == pytest.approx(33 * sr, abs=sr // 2)


def test_bass_is_silent_in_intro(tmp_path):
    paths = compile_ir(EXAMPLE, tmp_path)
    bass, sr = sf.read(paths["bass"], always_2d=True)
    intro_seconds = 16 * 60.0 / 90.0  # 4 bars
    intro = bass[: int(intro_seconds * sr) - sr // 10]
    main = bass[int(intro_seconds * sr) :]
    assert np.max(np.abs(intro)) < 1e-6, "bass leaked into the intro"
    assert np.max(np.abs(main)) > 0.01, "bass missing from main"


def test_single_field_change_changes_output(tmp_path):
    base = compile_ir(EXAMPLE, tmp_path / "base")

    raw = example_raw()
    raw["tracks"][3]["fx"][0]["cutoff_hz"] = 300  # darker bass
    edited_path = tmp_path / "edited.yaml"
    edited_path.write_text(yaml.safe_dump(raw))
    # sample paths in the example are relative to examples/, so rewrite them
    raw2 = example_raw()
    for t in raw2["tracks"]:
        t["sample"] = str((EXAMPLE.parent / t["sample"]).resolve())
    raw2["tracks"][3]["fx"][0]["cutoff_hz"] = 300
    edited_path.write_text(yaml.safe_dump(raw2))

    edited = compile_ir(edited_path, tmp_path / "edited")
    assert file_hash(base["bass"]) != file_hash(edited["bass"]), "fx edit had no effect"
    assert file_hash(base["kick"]) == file_hash(edited["kick"]), "unrelated stem changed"


def test_microtiming_changes_output(tmp_path):
    raw = example_raw()
    for t in raw["tracks"]:
        t["sample"] = str((EXAMPLE.parent / t["sample"]).resolve())
    nudged = copy.deepcopy(raw)
    nudged["tracks"][0]["clips"][1]["notes"][1]["offset_ms"] = 20.0

    a_path, b_path = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a_path.write_text(yaml.safe_dump(raw))
    b_path.write_text(yaml.safe_dump(nudged))
    a = compile_ir(a_path, tmp_path / "a")
    b = compile_ir(b_path, tmp_path / "b")
    assert file_hash(a["kick"]) != file_hash(b["kick"])


# --- validation errors carry the field path ---


@pytest.mark.parametrize(
    "mutate, expected_fragment",
    [
        (lambda r: r.pop("tempo"), "missing required field 'tempo'"),
        (lambda r: r["tempo"].pop("bpm"), "tempo: missing required field 'bpm'"),
        (lambda r: r["tempo"].update(bpm=5000), "tempo.bpm"),
        (lambda r: r.update(ir_version=99), "ir_version"),
        (lambda r: r["tracks"][1]["fx"][0].update(type="reverb"), "tracks[1].fx[0].type"),
        (lambda r: r["tracks"][0]["clips"][0].update(section="drop"), "tracks[0].clips[0].section"),
        (lambda r: r["tracks"][0]["clips"][0]["notes"][0].update(pitch=200), "notes[0].pitch"),
        (lambda r: r["tracks"][0].update(pan=2.0), "tracks[0].pan"),
        (lambda r: r["arrangement"]["sections"][0].update(name="main"), "must be unique"),
    ],
)
def test_validation_error_paths(mutate, expected_fragment):
    raw = example_raw()
    for t in raw["tracks"]:
        t["sample"] = str((EXAMPLE.parent / t["sample"]).resolve())
    mutate(raw)
    with pytest.raises(IRError, match=None) as exc:
        parse_ir(raw, base_dir=EXAMPLE.parent)
    assert expected_fragment in str(exc.value)


def test_missing_sample_file_error():
    raw = example_raw()
    raw["tracks"][0]["sample"] = "nope/missing.wav"
    with pytest.raises(IRError) as exc:
        parse_ir(raw, base_dir=EXAMPLE.parent)
    assert "tracks[0].sample" in str(exc.value)
    assert "file not found" in str(exc.value)
