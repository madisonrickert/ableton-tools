---
name: tempo-drift
description: Detect the tempo of an audio file (beat-tracked BPM, sub-millisecond precise BPM, and real tempo drift via inter-beat-interval regression), measure time drift between a master and its stems-sum, and check whether a set's warp map sits on the real beats and is shared by all warped stems (warp-check). Use when matching a stem's tempo map to a master, choosing a project BPM (warp-check's warp_map_bpm is the native-speed tempo), diagnosing why warped stems slip out of phase, or confirming arrangement bars line up with the music. Experimental; not benchmarked against Ableton's own tempo/warp analysis.
---

You analyze tempo and drift using the bundled Ableton engine (the `ableton`
command on PATH; see the `engine` skill for the full command reference and
fallback paths).

**Experimental.** This tempo detection has not been benchmarked against
Ableton's own tempo and warp analysis and is not verified to be more accurate.
Use it as a starting estimate to confirm, not as ground truth, and say so when
you report a number.

## Tempo of one file
`ableton tempo <FILE> [--hint-bpm N] --json`
Returns `bpm` (beat-tracked), `precise_bpm` (autocorrelation, sub-ms),
`bpm_start`/`bpm_end`/`bpm_drift_total` (IBI regression). Use `precise_bpm` when
choosing the exact project tempo; use `bpm_drift_total` to tell real drift from
beat-tracker noise (a few hundredths of a BPM = effectively steady).

## Does the set's warp map sit on the real beats? (experimental)
`ableton warp-check <FILE.als> [--track <master>] [--audio <file>] --json`

For the master's warped clip, this reports:
- `warp_map_bpm`: the native-speed tempo of the map. Use it as the project
  tempo to avoid any net stretch.
- marker→beat and marker→onset distances (median/p90 ms).
- the downbeat's nearest onset.
- `sync`: which warped clips share the master's exact map (`shared`) and
  which would drift (`differs`).

Bar lines within ~20 ms of beats mean the grid tracks the music. A `notes`
entry about a sparse intro means the intro's grid can't be verified from the
audio, so check the downbeat by eye in Live.

## Drift between a master and its stems
`ableton drift --master <MASTER> --stems <STEMS_DIR> --json`
Returns a per-window `lag_ms` trace and `total_drift_ms`. A monotonic lag trend
means the master and stems run at slightly different tempos — the case that
motivated warping stems to the master's grid in the original project.
