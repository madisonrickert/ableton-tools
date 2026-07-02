# Design provenance

This toolkit began as a pile of one-off analysis scripts written to debug a
single project whose exported stems drifted out of phase against their master.
Consolidating those scripts into one library plus a single dispatcher is why the
engine is shaped the way it is: each module is a cohesive slice of that original
exploratory work, and each CLI subcommand is the polished form of a script that
used to be run by hand.

## Module → capability

| Module(s) | Subcommand |
|---|---|
| `cancel.py` + `align.py` | `stem-verify` |
| `align.py` | `drift` |
| `tempo.py` | `tempo` |
| `transcribe.py` | `midi transcribe` |
| `midi.py` | `midi compare` |
| `als.rename_refs` | `als rename` / `als move` |
| `als.warp_to_grid`, `als.move_clip_to_beat` | `als warp-to-grid` / `als snap` |
| `als.clone_track`, `als.move_clip_to_beat` | primitives (not commands) behind `als import-stems` |

The mono-sum `.wav` artifacts the original scripts wrote to disk are now built
in memory by `audio.sum_stems`.
