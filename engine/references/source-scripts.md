# Source-script provenance

Where the logic of the original `_analysis/*.py` scripts from the
"Come With Me to Polar Palooza" project landed in this toolkit.

| Original script(s) | Landed in |
|---|---|
| sibling_verify.py, sibling_verify_v2.py, sibling_verify_v3.py, cancel_test.py, cancel_demucs.py, per_window_corr.py, sanity.py | `cancel.py` + `align.py` → `stem-verify` |
| drift_check.py, drift_fine.py, xcorr.py | `align.py` → `drift` |
| tempo.py, tempo_drift.py, tempo_precise.py, audio_truth.py | `tempo.py` → `tempo` |
| sax_to_midi.py | `transcribe.py` → `midi transcribe` |
| midi_compare.py, midi_three_way.py, midi_chroma_xcorr.py, midi_anchors.py, midi_anchor_ableton.py, midi_diag.py | `midi.py` → `midi compare` |
| rename.py, move_to_imported.py | `als.rename_refs` → `als rename` / `als move` |
| warp_to_grid.py, grid_snap.py | `als.warp_to_grid`, `als.move_clip_to_beat` → `als warp-to-grid` / `als snap` |
| add_track_and_rename.py, patch_timeline.py | `als.clone_track`, `als.move_clip_to_beat` primitives (not commands) |

The mono-sum `.wav` artifacts those scripts produced are now built in memory by
`audio.sum_stems`; process-management scripts (cancel_demucs/cancel_test) are
covered by `stem-verify`.
