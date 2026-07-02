---
name: tempo-drift
description: Detect the tempo of an audio file (beat-tracked BPM, sub-millisecond precise BPM, and real tempo drift via inter-beat-interval regression), and measure time drift between a master and its stems-sum. Use when matching a stem's tempo map to a master, choosing a project BPM, or diagnosing why warped stems slip out of phase.
---

You analyze tempo and drift using the bundled Ableton engine (the `ableton`
command on PATH; see the `engine` skill for the full command reference and
fallback paths).

## Tempo of one file
`ableton tempo <FILE> [--hint-bpm N] --json`
Returns `bpm` (beat-tracked), `precise_bpm` (autocorrelation, sub-ms),
`bpm_start`/`bpm_end`/`bpm_drift_total` (IBI regression). Use `precise_bpm` when
choosing the exact project tempo; use `bpm_drift_total` to tell real drift from
beat-tracker noise (a few hundredths of a BPM = effectively steady).

## Drift between a master and its stems
`ableton drift --master <MASTER> --stems <STEMS_DIR> --json`
Returns a per-window `lag_ms` trace and `total_drift_ms`. A monotonic lag trend
means the master and stems run at slightly different tempos — the case that
motivated warping stems to the master's grid in the original project.
