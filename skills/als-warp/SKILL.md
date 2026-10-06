---
name: als-warp
description: Grid-lock Ableton clips to a fixed project tempo (two warp markers per clip to preserve inter-clip phase) and reposition clips to exact beats. Use when stems were auto-warped and drift apart, or to snap clips to integer beats. Mutations are dry-run by default and auto-backup before committing.
---

You warp and reposition `.als` clips using the bundled Ableton engine (the
`ableton` command on PATH; see the `engine` skill for the full command
reference and fallback paths). **Close Ableton before committing edits.**

## Warp clips to the grid
1. Get each target clip's audio duration in seconds (e.g. `ffprobe` or
   `als inspect` + the source file). Build `clips.json`:
   `{"clip_name": duration_seconds, ...}`.
2. Dry-run:
   `ableton als warp-to-grid <FILE.als> --tempo 134 --clips clips.json --json`
3. Commit with `--commit` (auto-backup + ref re-verify, as with all mutations).

This sets the project tempo (Live 12 and Live 11 sets) and gives each clip
exactly two warp markers
(sec 0→beat 0, sec duration→end beat), so every clip shares one linear
time→beat map, aiming to keep stems phase-coherent.

**Experimental.** The two-marker strategy is a different approach from
Ableton's auto-warp, not a proven improvement on it: it has not been
benchmarked against auto-warp and is not verified to do better. For aligning
Suno-style stems, the more reliable path is usually to let Ableton auto-warp
the master, then use the `als-files` import-stems feature to clone that warped
master onto each stem. Show the user the dry-run diff and have them check the
result.

## Reposition a single clip to a beat
`ableton als move-clip <FILE.als> --clip NAME --to-beat 7.0 [--dur-s 7.5 --bpm 134] [--commit] --json`

This moves the clip's Arrangement position: the `Time` attribute and
CurrentStart/End. Without `--dur-s` the clip keeps its length. When a Session
clip shares the name, the Arrangement clip is the one moved.

## Snap several clips at once
Write a manifest `snaps.json`:
`{"clip_name": {"beat": 7.0[, "dur_s": 7.5, "bpm": 134]}, ...}`,
then run `ableton als snap <FILE.als> --manifest snaps.json [--commit] --json`.

## Keep stems locked after moving or re-warping the master
Every warped stem carries its own copy of the warp map. So when the master
clip is moved or re-warped in Live, the stems do **not** follow. Fix them with
`ableton als sync-to-master <FILE.als> --master <track> --all-warped [--markers] [--commit]`,
covered in the `als-build` skill.

Then check with `ableton warp-check <FILE.als>` (in the `tempo-drift`
skill), which reports warped clips that don't share the master's map.

Always show the user the dry-run diff before committing.
