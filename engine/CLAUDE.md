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

## levels
`ableton levels DIR [--pattern '*.wav'] [--ref FILE] --json`
Returns: `{folder, ref, silent_threshold_dbfs, files:[{file, duration_s,
sample_rate, channels, dbfs, silent, r_vs_ref?}]}`. `r_vs_ref` ≈ 1 means the
file is a copy of the reference (e.g. a "bounce" that is just the backing track).

## locate
`ableton locate --fragment F --ref R [--env-hz 100] [--top 3] --json`
Returns: `{fragment, ref, env_hz, matches:[{offset_s, r}], band}`. Band:
`same` (r ≥ 0.8), `likely` (0.6–0.8), `different` (< 0.6 = not the same
performance; place by ear).

## warp-check (experimental)
`ableton warp-check FILE.als [--track NAME] [--audio FILE] --json`
Returns: `{track, clip, audio, marker_count, marker_spacing_beats,
warp_map_bpm, beat_alignment_ms:{median,p90}, onset_alignment_ms:{median,p90},
downbeat:{time_s, nearest_onset_ms}, first_detected_beat_s,
sync:{shared:[track], differs:[track]}, notes:[...]}`. `warp_map_bpm` is the
native-speed tempo. `sync.differs` lists warped clips whose warp map differs
from the master's (they will drift).

## midi transcribe
`ableton midi transcribe AUDIO.wav [--out OUT.mid] --json`
Returns: `{output: "<path>.mid"}`. Installs basic-pitch on demand.

## midi compare
`ableton midi compare A.mid B.mid [C.mid] --json`
Returns: `{files:[{path, n_notes}], pairs:[{a, b, chroma_cosine,
drift_offset_s, drift_slope_s_per_s, drift_n_anchors, drift_residual_ms}]}`.

## als inspect
`ableton als inspect FILE.als --json`
Returns: `{file, tempo, main:{tag,name,devices}, tracks:[{tag, id, name, kind,
group_id, output, muted, devices}], clips:[{name, track, location
("arrangement"|"session"), time, current_start, current_end, relative_path,
relative_path_type, is_warped, warp_marker_count, warp_map_bpm}]}`. Works on
Live 12 (`MainTrack`) and Live 11 (`MasterTrack`).

## als validate (read-only)
`ableton als validate FILE.als --json` → `{file, ok, errors[], warnings[],
refs:{missing_project[], missing_external[], library, user_library, builtin}}`;
exit 1 when invalid. Checks: well-formed; unique track and pointee
(AutomationTarget/ModulationTarget) ids; NextPointeeId > max Id (automation-envelope event Ids excluded: Live numbers those separately); numeric int
nodes (incl. ScaleInformation/Name); TrackGroupIds resolve; grouped tracks
route to their group (warning).

## als rename | move
`ableton als rename FILE.als --manifest MAP.json [--commit] --json`
MAP.json: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
Keys are project-relative paths, or absolute paths for files outside the
project. Matching is per `<FileRef>`: a match sets RelativePath to the new
path, RelativePathType to 3 and Path to `<project>/<new>`, so the two stay
consistent. Refs under `<OriginalFileRef>` (import provenance, not loaded by
Live) are never touched.
Dry-run returns `{dry_run:true, op, diff:{changed, refs, mapping}}`
(`changed` = manifest entries that matched, `refs` = FileRefs rewritten). With `--commit`:
`{committed:true, backup, op, diff}` or a restore report if refs break.

## als warp-to-grid
`ableton als warp-to-grid FILE.als --tempo 134 --clips CLIPS.json [--commit] --json`
CLIPS.json: `{"clip_name": duration_seconds, ...}`. Sets project tempo, then
gives each clip two warp markers (sec 0→beat 0, sec dur→end beat) so inter-clip
phase is preserved.

## als move-clip
`ableton als move-clip FILE.als --clip NAME --to-beat 7.0 [--dur-s 7.5 --bpm 134] [--commit] --json`.
Sets the Arrangement `Time` attribute and CurrentStart/End. Without `--dur-s`
the clip keeps its length.

## als snap
`ableton als snap FILE.als --manifest SNAPS.json [--commit] --json`
SNAPS.json: `{"clip_name": {"beat": 7.0[, "dur_s": 7.5, "bpm": 134]}, ...}`.

## als import-stems
`ableton als import-stems FILE.als --master-track <id|name> --stems DIR [--pattern '*.wav'] [--colors colors.json] [--keep-session] [--tolerance-ms N] [--to arrangement|session] [--unwarped] [--mute-below DB] [--skip-below DB] [--commit] --json`
Dry-run returns `{dry_run:true, op:"import-stems", validation, diff:{master_track_id,
stems:[{file,label,effective_name,color,relative_path,placement,unwarped,muted,dbfs?}],
skipped?, timeline?}}`. `--master-track` accepts an Id, an exact name, or the
name without Live's `<index>-` prefix. By default every stem must match the
master's frames and sample rate (clones inherit its warp markers verbatim);
`--tolerance-ms N` relaxes that to "same timeline": length within N ms, any
sample rate, and a measured start lag (`diff.timeline[].lag_ms`, rejected
only when correlated with the master). The master's duplicated Session clip
is dropped from clones unless `--keep-session`. `--to session --unwarped`
puts un-synced takes in the first Session clip slot (scene 1) at native speed.
Clones keep the master's volume, pan and sends, but never its frozen audio,
take lanes, mute, solo or arm state.

## Session-building commands (all dry-run unless --commit)
- `ableton als set-tempo FILE.als BPM` → `{tempo, previous}`.
- `ableton als mute FILE.als --tracks A B [--unmute]`.
- `ableton als add-track FILE.als --name N [--color C] [--after TRACK]` → a
  bare audio track (no clips/devices/automation/frozen audio/take lanes,
  default volume/pan/sends, unmuted), placed after TRACK (never splitting a
  group).
- `ableton als group FILE.als --name N --tracks A B C [--color C]` → a
  GroupTrack (from a Live 12 template, so Live 12 sets only) before the first
  member; members get TrackGroupId **and** output routing to the group bus. Members must be contiguous and ungrouped.
- `ableton als sync-to-master FILE.als --master M (--tracks … | --all-warped) [--markers]`
  → copies the master clip's Time/CurrentStart/End/loop bounds to the targets'
  warped clips; `--markers` also copies its warp map, otherwise
  `diff.marker_mismatch` lists tracks that would drift.

## als transplant-devices (experimental)
`ableton als transplant-devices TARGET.als --from SRC.als (--src-track N | --src-main) (--to-track N | --to-main) [--mode replace|append] [--with-automation] [--map-track SRC=DST …] [--commit] --json`
Copies a device chain verbatim (plugin state included); offsets ids; remaps
the chain's self routing to the destination track; resets cross-track routing
to None (`diff.routing_reset`, re-assign in Live) unless `--map-track`;
drops source automation (`diff.automation_dropped`) unless
`--with-automation`; copies project-relative files into `Samples/Imported/`
on commit, after the commit guards pass (`diff.files_copied:[{from, to,
existing}]`: an identical file already there is reused, a different file with
the same name gets `<name> (2).<ext>`); lists plugins with `found`
(installed?) in `diff.plugins`. Sources may be Live 11 or 12; targets are
tested on Live 12.

## Errors
Usage failures: exit code 2 (3 for missing files), stderr
`{"error": "...", "hint": "...", "kind"?: "..."}` in JSON mode. Commit-path
kinds: `live_running` (close Ableton or `--force`), `file_changed` (the set
was saved since it was read; re-run), `validation_failed` (nothing written;
likely an engine bug). A commit whose project-relative refs break is restored
from its backup and reported as `{committed:false, kind:"refs_restored"}`.
Engine invariant failures (overlapping edits, id collisions) exit 4 with
`kind: "internal"`; nothing is written. Any other traceback is an engine bug.

## Conventions
- `uv` only. Never pip.
- Every mutating `als` command: dry-run by default (the dry-run includes a
  `validation` report). On `--commit`: refuse if Live is running (`--force`
  overrides) or the file changed since read; validate; backup to
  `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` (Ableton's native
  auto-backup convention, visible in Live's rollback UI); write atomically
  (temp file + rename, so a crash never leaves a half-written set); re-check
  project-relative (type 3) refs and auto-restore on breakage. Library and
  built-in device refs (types 5/6/7) never trigger a restore.
- All `.als` reads/edits go through `alsxml` (lossless byte splices).
- `ffmpeg`/`ffprobe` are detected at runtime; a missing binary fails with a hint.
- Close Ableton before committing `.als` edits.

## Development
Dev loop from the repo root: `uv run --project engine --group dev pytest`,
`uvx ruff check engine`, `uvx pyright --project engine engine/src`.
Fixtures are sanitized real Live 12.4 sets (`engine/tests/fixtures/README.md`).
Dev-only `engine/scripts/corpus_check.py` transplants every device chain of
your local Live 11/12 sets into the fixture and validates the results (run it
after touching `devices.py` or `alsxml.py`).

The `--project engine` on pyright is load-bearing. `engine/pyproject.toml`
sets `venvPath = "."` relative to the config file, and pyright resolves that
only once it knows where the config lives. Running `uvx pyright engine/src`
without `--project` makes pyright auto-discover the config relative to the
invocation cwd, so it cannot find `engine/.venv` and reports spurious
`reportMissingImports` errors on every third-party dependency (numpy, scipy,
soundfile, mido, librosa).
