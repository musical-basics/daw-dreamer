"""Phase 1 human test: render an 8-bar 90 BPM loop from the starter samples.

Run:  python scripts/render_demo.py
Then: listen to renders/demo/master.wav and the per-track stems next to it.
"""

from pathlib import Path

from daw_engine import Note, RenderSpec, Track, render

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "assets" / "samples"
BARS = 8


def drum_notes(pattern: dict[float, int]) -> tuple[Note, ...]:
    """pattern maps beat-in-bar -> velocity, repeated every bar."""
    return tuple(
        Note(start_beats=bar * 4.0 + beat, velocity=vel)
        for bar in range(BARS)
        for beat, vel in sorted(pattern.items())
    )


def bass_notes() -> tuple[Note, ...]:
    # C2 sample at center note 60: a i-VI-III-VII minor loop, two bars per chord
    progression = [60, 60, 56, 56, 63, 63, 58, 58]  # C C Ab Ab Eb Eb Bb Bb
    return tuple(
        Note(pitch=p, velocity=100, start_beats=bar * 4.0, duration_beats=3.5)
        for bar, p in enumerate(progression)
    )


def main() -> None:
    spec = RenderSpec(
        bpm=90.0,
        duration_beats=BARS * 4.0,
        tracks=(
            Track(
                name="kick",
                sample_path=str(SAMPLES / "kick.wav"),
                notes=drum_notes({0.0: 127, 1.75: 90, 2.5: 110}),
                gain_db=-6.0,
            ),
            Track(
                name="snare",
                sample_path=str(SAMPLES / "snare.wav"),
                notes=drum_notes({1.0: 112, 3.0: 118}),
                gain_db=-8.0,
            ),
            Track(
                name="hat",
                sample_path=str(SAMPLES / "hat.wav"),
                notes=drum_notes({i / 2: (96 if i % 2 == 0 else 70) for i in range(8)}),
                gain_db=-7.0,
                pan=0.2,
            ),
            Track(
                name="bass",
                sample_path=str(SAMPLES / "bass.wav"),
                notes=bass_notes(),
                gain_db=-7.0,
            ),
        ),
    )
    paths = render(spec, ROOT / "renders" / "demo")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
