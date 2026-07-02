---
name: midi-compare
description: Compare two or three MIDI files by harmonic content (duration-weighted chroma cosine similarity) and timing drift (onset alignment + linear drift fit). Use when checking whether two transcriptions agree, or whether a MIDI part drifts in time against a trusted reference (e.g. Ableton's clock).
---

You compare MIDI timelines using the bundled Ableton engine (the `ableton`
command on PATH; see the `engine` skill for the full command reference and
fallback paths).

## Invoke
`ableton midi compare <A.mid> <B.mid> [<C.mid>] --json`

Returns, for each pair: `chroma_cosine` (1.0 = identical pitch-class content),
`drift_offset_s` (constant timing offset), `drift_slope_s_per_s` (tempo drift —
nonzero means the two run at different rates), `drift_n_anchors`, and
`drift_residual_ms`.

## Interpret
- `chroma_cosine > 0.95` → same harmonic content; `< 0.8` → different parts.
- `drift_slope` near 0 with small `offset` → aligned; growing offset → drift.
Put the most trusted file first (e.g. the Ableton export) so offsets read as
"how much the other drifts relative to truth."
