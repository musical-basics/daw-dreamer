"""Song IR v1: the diffable song document (implementation-plan.md Phase 2).

The IR is the single source of truth — nothing renders audio except the
compiler reading one of these. Validation errors carry the YAML path of the
offending field so an LLM (or human) can fix the document from the message
alone.

Schema future-proofing (reserved now, consumed in later phases):
- note offset_ms is a float (sub-millisecond microtiming for 1/f humanization)
- sections are first-class with explicit bar counts (Foote novelty validates
  the arrangement against these boundaries in Phase 8)
- sections carry optional intent fields: energy (0-1) and color (hex string),
  filled by the Phase 12 control layer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from daw_engine.render import FX_MODES

IR_VERSION = 1


class IRError(ValueError):
    """IR validation failure; message starts with the path of the bad field."""


def _fail(path: str, msg: str) -> None:
    raise IRError(f"{path}: {msg}")


def _get(raw: dict, key: str, path: str, types, required: bool = True, default=None):
    if not isinstance(raw, dict):
        _fail(path, f"expected a mapping, got {type(raw).__name__}")
    if key not in raw:
        if required:
            _fail(path, f"missing required field '{key}'")
        return default
    value = raw[key]
    if types is not None and not isinstance(value, types):
        expected = types.__name__ if isinstance(types, type) else "/".join(t.__name__ for t in types)
        _fail(f"{path}.{key}", f"expected {expected}, got {type(value).__name__} ({value!r})")
    return value


def _num(raw, key, path, lo, hi, required=True, default=None) -> float | None:
    value = _get(raw, key, path, (int, float), required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not lo <= value <= hi:
        _fail(f"{path}.{key}", f"must be a number in [{lo}, {hi}], got {value!r}")
    return float(value)


@dataclass(frozen=True)
class SectionIntent:
    energy: float | None = None  # 0-1 target, consumed by the Phase 12 control layer
    color: str | None = None  # target harmonic color (hex), same


@dataclass(frozen=True)
class Section:
    name: str
    bars: int
    intent: SectionIntent = field(default_factory=SectionIntent)


@dataclass(frozen=True)
class IRNote:
    pitch: int = 60
    velocity: int = 100
    start: float = 0.0  # beats, relative to the clip occurrence
    duration: float | None = None  # beats; None = full sample length
    offset_ms: float = 0.0  # microtiming, float => sub-ms resolution


@dataclass(frozen=True)
class Clip:
    section: str
    notes: tuple[IRNote, ...]
    start_bar: int = 0  # within the section
    loop_every_bars: int | None = None  # None = play once


@dataclass(frozen=True)
class IRFx:
    type: str
    cutoff_hz: float
    q: float = 0.707
    gain_db: float = 0.0


@dataclass(frozen=True)
class IRTrack:
    name: str
    sample_path: Path  # resolved absolute
    clips: tuple[Clip, ...] = ()
    gain_db: float = 0.0
    pan: float = 0.0
    fx: tuple[IRFx, ...] = ()


@dataclass(frozen=True)
class SongIR:
    bpm: float
    sections: tuple[Section, ...]
    tracks: tuple[IRTrack, ...]
    title: str = ""
    key: str = ""
    beats_per_bar: int = 4
    sample_rate: int = 44100

    @property
    def total_bars(self) -> int:
        return sum(s.bars for s in self.sections)

    def section_start_bar(self, name: str) -> int:
        bar = 0
        for s in self.sections:
            if s.name == name:
                return bar
            bar += s.bars
        raise KeyError(name)


def _parse_section(raw, path: str) -> Section:
    name = _get(raw, "name", path, str)
    bars = _get(raw, "bars", path, int)
    if bars < 1:
        _fail(f"{path}.bars", f"must be >= 1, got {bars}")
    intent_raw = _get(raw, "intent", path, dict, required=False, default={})
    intent = SectionIntent(
        energy=_num(intent_raw, "energy", f"{path}.intent", 0.0, 1.0, required=False),
        color=_get(intent_raw, "color", f"{path}.intent", str, required=False),
    )
    return Section(name=name, bars=bars, intent=intent)


def _parse_note(raw, path: str) -> IRNote:
    pitch = _get(raw, "pitch", path, int, required=False, default=60)
    if not 0 <= pitch <= 127:
        _fail(f"{path}.pitch", f"must be a MIDI pitch 0-127, got {pitch}")
    velocity = _get(raw, "velocity", path, int, required=False, default=100)
    if not 1 <= velocity <= 127:
        _fail(f"{path}.velocity", f"must be 1-127, got {velocity}")
    start = _num(raw, "start", path, 0.0, 10_000.0, required=False, default=0.0)
    duration = _num(raw, "duration", path, 1e-4, 10_000.0, required=False)
    offset_ms = _num(raw, "offset_ms", path, -200.0, 200.0, required=False, default=0.0)
    return IRNote(pitch=pitch, velocity=velocity, start=start, duration=duration, offset_ms=offset_ms)


def _parse_clip(raw, path: str, sections: dict[str, Section]) -> Clip:
    section = _get(raw, "section", path, str)
    if section not in sections:
        _fail(f"{path}.section", f"unknown section '{section}' (defined: {', '.join(sections)})")
    start_bar = _get(raw, "start_bar", path, int, required=False, default=0)
    if not 0 <= start_bar < sections[section].bars:
        _fail(f"{path}.start_bar", f"must be within section '{section}' (0-{sections[section].bars - 1})")
    loop = _get(raw, "loop_every_bars", path, int, required=False)
    if loop is not None and loop < 1:
        _fail(f"{path}.loop_every_bars", f"must be >= 1, got {loop}")
    notes_raw = _get(raw, "notes", path, list)
    if not notes_raw:
        _fail(f"{path}.notes", "must contain at least one note")
    notes = tuple(_parse_note(n, f"{path}.notes[{i}]") for i, n in enumerate(notes_raw))
    return Clip(section=section, notes=notes, start_bar=start_bar, loop_every_bars=loop)


def _parse_fx(raw, path: str) -> IRFx:
    fx_type = _get(raw, "type", path, str)
    if fx_type not in FX_MODES:
        _fail(f"{path}.type", f"unknown fx type '{fx_type}' (supported: {', '.join(FX_MODES)})")
    return IRFx(
        type=fx_type,
        cutoff_hz=_num(raw, "cutoff_hz", path, 20.0, 20_000.0),
        q=_num(raw, "q", path, 0.05, 18.0, required=False, default=0.707),
        gain_db=_num(raw, "gain_db", path, -24.0, 24.0, required=False, default=0.0),
    )


def _parse_track(raw, path: str, sections: dict[str, Section], base_dir: Path) -> IRTrack:
    name = _get(raw, "name", path, str)
    sample = _get(raw, "sample", path, str)
    sample_path = Path(sample)
    if not sample_path.is_absolute():
        sample_path = (base_dir / sample_path).resolve()
    if not sample_path.is_file():
        _fail(f"{path}.sample", f"file not found: {sample_path}")
    fx_raw = _get(raw, "fx", path, list, required=False, default=[])
    clips_raw = _get(raw, "clips", path, list, required=False, default=[])
    return IRTrack(
        name=name,
        sample_path=sample_path,
        gain_db=_num(raw, "gain_db", path, -60.0, 12.0, required=False, default=0.0),
        pan=_num(raw, "pan", path, -1.0, 1.0, required=False, default=0.0),
        fx=tuple(_parse_fx(f, f"{path}.fx[{i}]") for i, f in enumerate(fx_raw)),
        clips=tuple(_parse_clip(c, f"{path}.clips[{i}]", sections) for i, c in enumerate(clips_raw)),
    )


def parse_ir(raw: dict, base_dir: Path) -> SongIR:
    if not isinstance(raw, dict):
        raise IRError(f"IR document must be a mapping, got {type(raw).__name__}")
    version = _get(raw, "ir_version", "<root>", int)
    if version != IR_VERSION:
        _fail("ir_version", f"this compiler supports version {IR_VERSION}, got {version}")

    meta = _get(raw, "meta", "<root>", dict, required=False, default={})
    tempo = _get(raw, "tempo", "<root>", dict)
    bpm = _num(tempo, "bpm", "tempo", 20.0, 999.0)

    time_sig = _get(raw, "time_signature", "<root>", str, required=False, default="4/4")
    try:
        beats_per_bar = int(time_sig.split("/")[0])
        assert beats_per_bar >= 1
    except (ValueError, IndexError, AssertionError):
        _fail("time_signature", f"expected 'N/M' like '4/4', got {time_sig!r}")

    arrangement = _get(raw, "arrangement", "<root>", dict)
    sections_raw = _get(arrangement, "sections", "arrangement", list)
    if not sections_raw:
        _fail("arrangement.sections", "must contain at least one section")
    sections = tuple(
        _parse_section(s, f"arrangement.sections[{i}]") for i, s in enumerate(sections_raw)
    )
    names = [s.name for s in sections]
    if len(set(names)) != len(names):
        _fail("arrangement.sections", f"section names must be unique, got {names}")
    section_map = {s.name: s for s in sections}

    tracks_raw = _get(raw, "tracks", "<root>", list)
    if not tracks_raw:
        _fail("tracks", "must contain at least one track")
    tracks = tuple(
        _parse_track(t, f"tracks[{i}]", section_map, base_dir) for i, t in enumerate(tracks_raw)
    )
    track_names = [t.name for t in tracks]
    if len(set(track_names)) != len(track_names):
        _fail("tracks", f"track names must be unique, got {track_names}")

    return SongIR(
        bpm=bpm,
        sections=sections,
        tracks=tracks,
        title=_get(meta, "title", "meta", str, required=False, default=""),
        key=_get(meta, "key", "meta", str, required=False, default=""),
        beats_per_bar=beats_per_bar,
        sample_rate=_get(raw, "sample_rate", "<root>", int, required=False, default=44100),
    )


def load_ir(path: str | Path) -> SongIR:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise IRError(f"{path} is not valid YAML: {e}") from e
    return parse_ir(raw, base_dir=path.parent)
