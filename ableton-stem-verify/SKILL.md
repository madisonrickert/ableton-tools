---
name: ableton-stem-verify
description: Verify whether a folder of audio stems sums back to a given master (a "sibling" check) by measuring windowed cancellation depth, correlation, and time offset. Use when confirming that exported stems and a master are the same render, or identifying which master a stems folder belongs to.
---

You verify that a folder of stems reconstructs a master, using the shared
Ableton engine.

## Invoke
The engine is the sibling skill `ableton-shared`. Run:

`<repo>/ableton-shared/bin/ableton stem-verify --stems <STEMS_DIR> --master <MASTER_FILE> --json`

Optional: `--win 10` (window seconds), `--max-lag-ms 200`, `--pattern '*.wav'`.

## Interpret the JSON (you state the verdict — the tool only emits numbers)
- `worst_db < -15` → true sibling: the stems ARE this master.
- median `-30..-10` → similar render / partial match (e.g. different bounce).
- median `> -10` → different audio.

Report `worst_db`, `median_db`, `lag_ms`, and `pearson_r`, then your verdict.
To test a stems folder against several masters, run once per master and compare
`worst_db` (most negative wins).
