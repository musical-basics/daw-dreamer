"""IR compiler: SongIR -> master + stems via the Phase 1 render harness.

Usage: daw-compile song.yaml [-o out_dir]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from daw_engine.ir import Clip, SongIR, load_ir
from daw_engine.render import Fx, Note, RenderSpec, Track, render


def _clip_occurrence_bars(clip: Clip, section_start: int, section_bars: int) -> list[int]:
    """Absolute bar numbers at which this clip's pattern plays."""
    first = section_start + clip.start_bar
    if clip.loop_every_bars is None:
        return [first]
    section_end = section_start + section_bars
    return list(range(first, section_end, clip.loop_every_bars))


def ir_to_spec(ir: SongIR) -> RenderSpec:
    bpb = ir.beats_per_bar
    section_bars = {s.name: s.bars for s in ir.sections}

    tracks = []
    for t in ir.tracks:
        notes = []
        for clip in t.clips:
            start = ir.section_start_bar(clip.section)
            for occ_bar in _clip_occurrence_bars(clip, start, section_bars[clip.section]):
                for n in clip.notes:
                    notes.append(
                        Note(
                            pitch=n.pitch,
                            velocity=n.velocity,
                            start_beats=occ_bar * bpb + n.start,
                            duration_beats=n.duration,
                            offset_ms=n.offset_ms,
                        )
                    )
        notes.sort(key=lambda n: (n.start_beats, n.pitch))
        tracks.append(
            Track(
                name=t.name,
                sample_path=str(t.sample_path),
                notes=tuple(notes),
                gain_db=t.gain_db,
                pan=t.pan,
                fx=tuple(Fx(f.type, f.cutoff_hz, f.q, f.gain_db) for f in t.fx),
            )
        )

    return RenderSpec(
        bpm=ir.bpm,
        duration_beats=ir.total_bars * bpb,
        tracks=tuple(tracks),
        sample_rate=ir.sample_rate,
    )


def compile_ir(ir_path: str | Path, out_dir: str | Path) -> dict[str, Path]:
    ir = load_ir(ir_path)
    return render(ir_to_spec(ir), out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a song IR document to WAV")
    parser.add_argument("ir_file", help="path to the IR YAML document")
    parser.add_argument("-o", "--out", default=None, help="output directory (default: renders/<name>)")
    args = parser.parse_args()

    ir_path = Path(args.ir_file)
    out_dir = Path(args.out) if args.out else Path("renders") / ir_path.stem
    paths = compile_ir(ir_path, out_dir)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
