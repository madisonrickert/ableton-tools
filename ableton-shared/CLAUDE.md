# ableton-shared — harness reference

Single entrypoint: `bin/ableton <subcommand> [...] [--json]` (runs under `uv`).
`bin/ableton manifest --json` enumerates subcommands. All examples assume the
working file paths are absolute or relative to the invocation cwd.

## stem-verify
`bin/ableton stem-verify --stems STEMS_DIR --master MASTER.wav [--win 10] [--max-lag-ms 200] [--pattern '*.wav'] --json`
Returns: `{master, stems_dir, stem_files[], sample_rate, lag_samples, lag_ms,
alpha, pearson_r, median_db, worst_db, best_db, n_windows, bands{}}`.
Interpret: `worst_db < -15` → true sibling; `-30..-10` median → similar render;
`> -10` median → different audio.

## tempo
`bin/ableton tempo FILE.wav [--hint-bpm 134] --json`
Returns: `{file, bpm, first_beat_s, n_beats, precise_bpm, period_s,
median_bpm, bpm_start, bpm_end, bpm_drift_total}`.

## drift
`bin/ableton drift --master MASTER.wav --stems STEMS_DIR [--win 10] --json`
Returns: `{master, stems_dir, stem_files[], windows:[{t_s, lag_ms, resid_ratio}],
total_drift_ms}`. A nonzero, monotonic `lag_ms` trend = tempo drift between
master and stems.

## midi transcribe
`bin/ableton midi transcribe AUDIO.wav [--out OUT.mid] --json`
Returns: `{output: "<path>.mid"}`. Installs basic-pitch on demand.

## midi compare
`bin/ableton midi compare A.mid B.mid [C.mid] --json`
Returns: `{files:[{path, n_notes}], pairs:[{a, b, chroma_cosine,
drift_offset_s, drift_slope_s_per_s, drift_n_anchors, drift_residual_ms}]}`.

## als inspect
`bin/ableton als inspect FILE.als --json`
Returns: `{file, tempo, tracks:[{tag,id,name}], clips:[{name, current_start,
current_end, relative_path, is_warped}]}`.

## als rename | move
`bin/ableton als rename FILE.als --manifest MAP.json [--commit] --json`
MAP.json: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
Dry-run returns `{dry_run:true, op, diff:{changed, mapping}}`. With `--commit`:
`{committed:true, backup, op, diff}` or a restore report if refs break.

## als warp-to-grid
`bin/ableton als warp-to-grid FILE.als --tempo 134 --clips CLIPS.json [--commit] --json`
CLIPS.json: `{"clip_name": duration_seconds, ...}`. Sets project tempo, then
gives each clip two warp markers (sec 0→beat 0, sec dur→end beat) so inter-clip
phase is preserved.

## als move-clip
`bin/ableton als move-clip FILE.als --clip NAME --to-beat 7.0 --dur-s 7.5 --bpm 134 [--commit] --json`.

## als snap
`bin/ableton als snap FILE.als --manifest SNAPS.json [--commit] --json`
SNAPS.json: `{"clip_name": {"beat": 7.0, "dur_s": 7.5, "bpm": 134}, ...}`.

## Conventions
- `uv` only. Never pip.
- Every mutating `als` command: dry-run by default, timestamped backup on
  commit, ref re-verify with auto-restore on breakage.
- `ffmpeg`/`ffprobe` are detected at runtime; a missing binary fails with a hint.
- Close Ableton before committing `.als` edits.
