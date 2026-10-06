---
name: stem-verify
description: Verify whether a folder of audio stems sums back to a given master (a "sibling" check) by measuring windowed cancellation depth, correlation, and time offset; triage a folder of audio (levels: dBFS, silence, sample rate, and whether a file is just a copy of a reference); and find where a fragment or take occurs inside a longer reference (locate). Use when confirming exported stems and a master are the same render, identifying which master a stems folder belongs to, spotting silent or duplicate stems, or placing a fragment on the timeline.
---

You verify that a folder of stems reconstructs a master, using the bundled
Ableton engine (the `ableton` command on PATH; see the `engine` skill for the
full command reference and fallback paths).

## Invoke
`ableton stem-verify --stems <STEMS_DIR> --master <MASTER_FILE> --json`

Optional: `--win 10` (window seconds), `--max-lag-ms 200`, `--pattern '*.wav'`.

## Interpret the JSON (you state the verdict — the tool only emits numbers)
- `worst_db < -15` → true sibling: the stems ARE this master.
- median `-30..-10` → similar render / partial match (e.g. different bounce).
- median `> -10` → different audio.

Report `worst_db`, `median_db`, `lag_ms`, and `pearson_r`, then your verdict.

## Triage a folder first: `levels`
`ableton levels <DIR> [--ref <FILE>] --json` reports each file's duration,
sample rate, dBFS and a `silent` flag (< −60 dBFS).

With `--ref`, it also reports `r_vs_ref`, the lag-0 correlation. Read the
results like this:
- `r ≈ 1` means the file *is* the reference, e.g. a "vocal bounce" that is
  actually the backing track.
- Silent stems, such as empty guitar or strings separations, can be skipped or
  muted on import (`import-stems --skip-below/--mute-below`).

## Where does a fragment belong? `locate`
`ableton locate --fragment <F> --ref <R> --json` returns the best offsets in
seconds plus `r`, with these bands:

| Band | r | Meaning |
|---|---|---|
| `same` | ≥ 0.8 | same render; trust the offset |
| `likely` | 0.6–0.8 | probable match |
| `different` | < 0.6 | a different performance |

Independent vocal takes score 0.2–0.6 against each other, so their positions
can't be recovered from audio. Place them by ear, or export them full-length
from the source DAW so the position is baked in.
To test a stems folder against several masters, run once per master and compare
`worst_db` (most negative wins).
