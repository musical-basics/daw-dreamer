# daw-dreamer

Deterministic music production engine: an LLM writes a song as a diffable document, a headless DAW (DawDreamer) compiles it to audio, and an analysis suite reports back — render, analyze, revise, like code and tests.

- [prd.md](prd.md) — the original brainstorm
- [extended-ideas.md](extended-ideas.md) — second-order dynamics and expectation-based extensions
- [implementation-plan.md](implementation-plan.md) — the 12-phase build plan

## Status: Phase 1 (render harness)

Sample-based, deterministic rendering to master + per-stem WAVs via DawDreamer.

### Setup

```bash
python3.12 -m venv .venv          # DawDreamer ships wheels up to Python 3.12
.venv/bin/pip install -e ".[dev]"
```

### Phase 1 human test

```bash
.venv/bin/python scripts/render_demo.py   # writes renders/demo/master.wav + stems
.venv/bin/pytest                          # includes the bit-identical determinism check
```

Listen to `renders/demo/master.wav` — an 8-bar 90 BPM loop built entirely from the
synthesized starter pack in `assets/samples/` (regenerate it with
`scripts/make_starter_samples.py`).
