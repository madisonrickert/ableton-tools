# ableton-tools engine — harness reference

Single entrypoint: `ableton <subcommand> [...] [--json]` (the plugin puts this
on the Bash PATH; runs under `uv`). If `ableton` is not on PATH, call
`<plugin-root>/engine/bin/ableton` directly. `ableton manifest --json`
enumerates subcommands, including nested ones. All examples assume the
working file paths are absolute or relative to the invocation cwd.

## stem-verify
`ableton stem-verify --stems STEMS_DIR --master MASTER.wav [--win 10] [--max-lag-ms 200] [--pattern '*.wav'] --json`
Returns: `{master, stems_dir, stem_files[], sample_rate, lag_samples, lag_ms,
alpha, pearson_r, median_db, worst_db, best_db, n_windows, bands{}}`.
Interpret: `worst_db < -15` → true sibling; `-30..-10` median → similar render;
`> -10` median → different audio.

## tempo
`ableton tempo FILE.wav [--hint-bpm 134] --json`
Returns: `{file, bpm, first_beat_s, n_beats, precise_bpm, period_s,
median_bpm, bpm_start, bpm_end, bpm_drift_total}`.

## drift
`ableton drift --master MASTER.wav --stems STEMS_DIR [--win 10] --json`
Returns: `{master, stems_dir, stem_files[], windows:[{t_s, lag_ms, resid_ratio}],
total_drift_ms}`. A nonzero, monotonic `lag_ms` trend = tempo drift between
master and stems.

## midi transcribe
`ableton midi transcribe AUDIO.wav [--out OUT.mid] --json`
Returns: `{output: "<path>.mid"}`. Installs basic-pitch on demand.

## midi compare
`ableton midi compare A.mid B.mid [C.mid] --json`
Returns: `{files:[{path, n_notes}], pairs:[{a, b, chroma_cosine,
drift_offset_s, drift_slope_s_per_s, drift_n_anchors, drift_residual_ms}]}`.

## als inspect
`ableton als inspect FILE.als --json`
Returns: `{file, tempo, tracks:[{tag,id,name}], clips:[{name, current_start,
current_end, relative_path, is_warped}]}`.

## als rename | move
`ableton als rename FILE.als --manifest MAP.json [--commit] --json`
MAP.json: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
Dry-run returns `{dry_run:true, op, diff:{changed, mapping}}`. With `--commit`:
`{committed:true, backup, op, diff}` or a restore report if refs break.

## als warp-to-grid
`ableton als warp-to-grid FILE.als --tempo 134 --clips CLIPS.json [--commit] --json`
CLIPS.json: `{"clip_name": duration_seconds, ...}`. Sets project tempo, then
gives each clip two warp markers (sec 0→beat 0, sec dur→end beat) so inter-clip
phase is preserved.

## als move-clip
`ableton als move-clip FILE.als --clip NAME --to-beat 7.0 --dur-s 7.5 --bpm 134 [--commit] --json`.

## als snap
`ableton als snap FILE.als --manifest SNAPS.json [--commit] --json`
SNAPS.json: `{"clip_name": {"beat": 7.0, "dur_s": 7.5, "bpm": 134}, ...}`.

## als import-stems
`ableton als import-stems FILE.als --master-track <id|name> --stems DIR [--pattern '*.wav'] [--colors colors.json] [--commit] --json`
Dry-run returns `{dry_run:true, op:"import-stems", diff:{master_track_id,
stems:[{file,label,effective_name,color,relative_path}]}}`. Refuses (exit 2,
structured error) when any stem's frames/samplerate differ from the master's
audio, when a stem lies outside the project directory, or when
--master-track does not resolve to exactly one track.

## Errors
Usage failures: exit code 2 (3 for missing files), stderr
`{"error": "...", "hint": "..."}` in JSON mode. Tracebacks = engine bugs.

## Conventions
- `uv` only. Never pip.
- Every mutating `als` command: dry-run by default, backup to
  `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` on commit (Ableton's
  native auto-backup convention, visible in Live's rollback UI), ref
  re-verify with auto-restore on breakage.
- `ffmpeg`/`ffprobe` are detected at runtime; a missing binary fails with a hint.
- Close Ableton before committing `.als` edits.

## Development
Dev loop from the repo root: `uv run --project engine --group dev pytest`,
`uvx ruff check engine`, `uvx pyright --project engine engine/src`.

The `--project engine` on pyright is load-bearing. `engine/pyproject.toml`
sets `venvPath = "."` relative to the config file, and pyright resolves that
only once it knows where the config lives. Running `uvx pyright engine/src`
without `--project` makes pyright auto-discover the config relative to the
invocation cwd, so it cannot find `engine/.venv` and reports spurious
`reportMissingImports` errors on every third-party dependency (numpy, scipy,
soundfile, mido, librosa).
