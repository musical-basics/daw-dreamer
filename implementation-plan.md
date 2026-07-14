# Implementation Plan: Deterministic Music Production Engine

Ten phases, each ending in something a human can test by ear or eye before the next phase begins. The ordering follows one rule: **the things everything else depends on (the renderer, the song IR, the machine-readable analysis report) come first, and every analysis feature ships in the same report format from day one** — so later phases (linter, quality loop, agents) consume existing infrastructure instead of forcing rewrites.

## Architectural invariants (decided now, enforced from Phase 1)

These are the decisions that prevent long-term structural problems:

1. **The song IR is the single source of truth.** Nothing renders audio except the compiler reading an IR document. No phase adds a side-channel way to make sound. Version the schema (`"ir_version": 1`) from the first file.
2. **Every analysis emits one JSON report + optional images.** The report card is a single schema that grows fields; the linter, the diff tool, and the LLM loop all read the same report. No analysis tool prints ad-hoc text.
3. **Determinism is a test, not a hope.** Same IR + same seed = bit-identical WAV. This gets a CI check in Phase 1 and stays green forever; it's what makes regression diffs (Phase 9) meaningful.
4. **Loudness-match before any comparison.** Every A/B tool normalizes to matched LUFS first. Built into the comparison library once, in Phase 4, and reused everywhere.
5. **Thresholds live in config, not code.** Lexicon boundaries, linter limits, genre targets are all data files, because Phases 4, 6, and 10 recalibrate them against human ears.

---

## Phase 1 — Render harness: DawDreamer makes sound deterministically

**Build:** Python project scaffold (uv/poetry, tests, CI-able). DawDreamer wrapper that can: load a sample, place it at a time offset, play MIDI into a sampler/synth, set gain/pan, render N bars at a given BPM to WAV, and render per-stem WAVs alongside the master. A tiny starter sample pack (kick, snare, hat, one bass patch) checked into the repo so tests are reproducible.

**Why first:** It's the compiler backend. If DawDreamer has platform or plugin-hosting quirks on this Mac, we need to know before designing anything on top of it.

**Human test:** Run `render_demo.py`, get an 8-bar drum loop WAV, listen to it. Run it twice and verify the two files are bit-identical (`shasum`). Change the BPM, hear it change.

## Phase 2 — Song IR v1 + compiler

**Build:** The textual intermediate representation (JSON or YAML): tempo map, key, arrangement grid (sections → bars), tracks (sample refs or synth patch parameter sets), note events with velocity and microtiming offsets, per-track gain/pan, and a basic FX slot list (start with just gain, EQ, and a lowpass — enough to prove the shape). A `compile(ir) -> {master.wav, stems/*.wav}` function built on Phase 1. Schema validation with clear error messages.

**Why now:** This is the highest-risk structural decision in the whole project. Getting the IR shape right early — sections, tracks, events, FX chains as data — is what lets every later phase (linter fixes, groove templates, agent edits) be "edit the document, recompile." Retrofitting an IR under a pile of analysis code would be the classic long-term structural failure.

**Human test:** Hand-write `first_beat.yaml` for an 8-bar beat, compile, listen. Edit one field (swap the kick sample, nudge a snare 20ms late, change a section length), recompile, and hear exactly that change and nothing else. Break the schema on purpose and confirm the error message tells you what's wrong.

## Phase 3 — Report card v1: single-signal analysis + contact sheets

**Build:** The analysis suite skeleton (librosa + Essentia + MoSQITo) producing one `report.json` per render, covering per-stem and master: integrated/short-term LUFS, crest factor, spectral tilt and centroid, sub ratio (30–90Hz vs total), attack/decay envelope stats, detected fundamental pitch, stereo width and mono-fold correlation, and the Zwicker/Fastl psychoacoustic set (sharpness, roughness, fluctuation strength). Plus the first visual contact sheets as PNGs: multi-resolution mel spectrogram sheet (transient / bar / song zoom levels) and the onset raster (all stems' onsets stacked piano-roll style).

**Why now:** The report is the second pillar of the architecture (invariant 2). Everything from Phase 4 onward is a consumer or refinement of this report.

**Human test:** Run it on three renders from Phase 2 and on two commercial reference tracks. Sanity-check the numbers against your ears: the 808-heavy render shows a high sub ratio, the clap shows high crest factor, a mono bass shows correlation ≈ 1. Open the spectrogram sheet and confirm you can visually spot the hi-hats, the kick fundamentals, and the section change.

## Phase 4 — Adjective lexicon + differential A/B comparison

**Build:** The loudness-matched comparison library (invariant 4). The producer-adjective lexicon as a config file compiling adjectives to feature math over report-card fields: fat, punchy, boxy, harsh, warm, hollow, muddy, bright. A `compare(a.wav, b.wav)` tool that outputs the delta vector ("Kick A: +5dB at 50Hz, 12ms slower attack, 2× harmonic distortion") and the lexicon translation ("A is fatter; B is punchier"). HPSS transient/sustain decomposition feeding the attack/decay features.

**Why now:** It's the first *judgment* layer, and it only needs Phase 3's report. Calibrating it is a human-in-the-loop activity, so it should mature while later phases are built.

**Human test:** The original kick question. Assemble ~20 kick pairs where you already know which is fatter/punchier/boxier, run the tool blind, and score its agreement with your ears. Spend the calibration session adjusting lexicon thresholds in config (not code) until agreement is solid. Disagreements are findings, not failures — they tell you which feature the lexicon is missing.

## Phase 5 — Interaction analysis: masking, collision, phase, dissonance

**Build:** The between-stems layer, all appended to the same report.json: Bark-band collision matrices per stem pair, the repurposed psychoacoustic masking model ("bass masks kick by 7dB in Bark band 4, bars 5–8"), the stem-masking heatmap PNG, phase/polarity cross-correlation for layered samples with auto-align suggestion, envelope cross-correlation for ducking detection, and Plomp–Levelt/Sethares spectral dissonance for simultaneous pitched material.

**Why now:** This is the PRD's biggest bet (the mixing problem) and it needs multi-stem renders (Phase 2) and the analysis skeleton (Phase 3). It must exist before the linter, because the linter's most valuable rules are interaction rules.

**Human test:** Author two IRs: one with a deliberate kick/bass fight at 60–90Hz, one with the bass sidechained/carved. Confirm the heatmap shows the red blob in the first and not the second — and that you can *hear* the difference the numbers claim. Layer two kicks with flipped polarity, confirm the tool flags it and its suggested alignment audibly fattens the layer.

## Phase 6 — Mix linter with named rules

**Build:** The linter as a pure consumer of report.json: `MONO_LOW_END`, `KICK_BASS_MASKING`, `MUD_BUDGET`, `HARSHNESS_CEILING`, `CREST_FACTOR_RANGE` (per bus), `TUNED_KICK`, `PHASE_CANCELLATION`. Deterministic pass/warn/fail, every message phrased as a fix ("high-pass the pad at 180Hz or shorten its release"), thresholds in a config file with a default profile and named genre-preset stubs. Exit codes so it works in scripts.

**Why now:** It's a thin rule layer over Phases 3+5 — cheap to build once the analysis exists, and it's the "compiler errors for mixes" artifact that makes the Phase 9 loop converge instead of wander.

**Human test:** Lint five mixes: two of your finished tracks (should mostly pass), two deliberately broken IRs from Phase 5 (should fail with the right named rules), one commercial reference (should pass — if it doesn't, the threshold is wrong, so fix the config). Then fix a failing mix *by following only the linter's fix messages* and confirm the lint clears and the mix genuinely sounds better.

## Phase 7 — Musical intelligence: theory solver, kick tuning, groove templates

**Build:** The composition-correctness layer that writes *into* the IR: an OR-tools-style constraint solver for chord voicings and voice leading (no parallel fifths, range limits, smoothness objective) taking intent as input ("gospel-ish reharm, soprano under E5"); deterministic kick-tuned-to-key transposition using Phase 3's fundamental detection; groove template extraction (microtiming + velocity deviations from a played MIDI performance) stored as reusable data and applied to quantized IR events.

**Why now:** Independent of the mixing stack, but it must land before the quality loop so the LLM composes through the solver instead of emitting raw note lists — otherwise Phase 9 spends its iterations fixing theory errors the solver eliminates for free.

**Human test:** Give the solver a progression request and render it — check by ear and by eye (no voice-leading clams, voicings playable). Render the same drum pattern three ways: quantized, with a groove template extracted from your own playing, and with the template at 50% strength. The grooved version should feel obviously more alive in a blind A/B.

## Phase 8 — Reference profiles, structure analysis, genre style sheets

**Build:** The reference decompiler-analyzer: run any commercial track through the pipeline to extract a **reference profile** (spectral tilt curve, dynamics, width-by-band, onset density per section, section lengths) plus structure visuals — self-similarity matrix PNG, spectral-flux novelty curve (audio scene cuts), tension curve (dissonance + loudness + density + register composite). Genre style sheets as machine-readable specs (BPM range, swing %, arrangement template, spectral targets, density curves) that reference profiles can be averaged into. A `distance(report, profile)` scorer.

**Why now:** This defines the objective function before the loop runs. Correctness (linter) says "not broken"; reference distance says "close to good." Both must exist before Phase 9 or the loop has nothing to optimize.

**Human test:** Run three reference tracks you know intimately through the analyzer. Verify the self-similarity matrix shows the choruses where you know they are, the novelty curve spikes at the real transitions, and the tension curve matches your felt sense of the song's arc. Build one genre sheet from them and confirm one of your own tracks in that genre scores closer to it than a track from a different genre does.

## Phase 9 — The closed quality loop + musical regression tests

**Build:** The render→analyze→revise harness Claude Code can drive: given a genre sheet + references + a brief, the LLM edits the IR, the pipeline compiles and emits report + lint results + reference distance, and the LLM patches the IR for the next iteration. Plus musical regression tests: fixed seed, snapshot the report, and a `report-diff` tool ("this EQ move cut masking 4dB and moved reference distance −0.03") so every change is reviewable like a code diff. Iteration artifacts (IR, WAV, report, diff) archived per step.

**Why now:** This is the integration phase — deliberately late, because a loop is only as good as its error messages, and Phases 3–8 are the error messages.

**Human test:** The big one. Give the loop a brief ("90 BPM boom-bap, dark, 16 bars") and let it run 5–10 iterations. Listen to every iteration in order: lint errors should trend to zero, reference distance should trend down, and — the real test — iteration N should sound better to you than iteration 1. Read the report-diffs and check the loop's stated reasons match what you hear.

## Phase 10 — Critic ensemble, human preference calibration, specialist agents

**Build:** The taste layer on top of the working floor: critic rubrics as separate scored axes (hook memorability via melodic n-gram self-similarity + interval distribution + singable range; arrangement contrast — drop vs build measured in energy/density/width; genre fit via embedding distance with a CLAP/MERT anchor library). The A/B preference pipeline: generate 15-second paired clips, collect votes (audience polls at your subscriber scale), and feed results back into lexicon thresholds, linter limits, and critic weights. Then split the loop into specialist agents (Drummer, Bassist, Harmony, Arranger, MixEngineer, Mastering, Critic) negotiating over the shared IR.

**Why last:** Calibration needs a pipeline that already produces competent output — polling humans on lint-failing audio wastes the audience. And the agent fleet is an organizational refactor of a loop that must already work single-agent.

**Human test:** Produce one full song end-to-end with the agent fleet. Run a real A/B poll (fleet output vs a Phase 9 single-loop output, and vs one of your own productions). Verify critic axis scores correlate with poll results — where they don't, you've found the next calibration target. Success criterion from the PRD: output that clears "professionally competent," with taste riding on a measured floor.

---

## Dependency summary

```
1 Render harness
└─ 2 Song IR + compiler
   ├─ 3 Report card (single-signal)
   │  ├─ 4 Lexicon + A/B compare      (human calibration starts)
   │  └─ 5 Interaction analysis
   │     └─ 6 Mix linter
   ├─ 7 Theory solver + grooves
   └─ 8 Reference profiles + genre sheets
      └─ 9 Quality loop + regression tests   (needs 6, 7, 8)
         └─ 10 Critics + preference calibration + agent fleet
```

Phases 4, 5, and 7 are mutually independent and can be reordered or parallelized if needed; everything else is a hard ordering.
