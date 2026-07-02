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

This sets the project tempo and gives each clip exactly two warp markers
(sec 0→beat 0, sec duration→end beat), so every clip shares one linear
time→beat map and stems stay phase-coherent — unlike Ableton's auto-warp.

## Reposition a single clip to a beat
`ableton als move-clip <FILE.als> --clip NAME --to-beat 7.0 --dur-s 7.5 --bpm 134 [--commit] --json`

## Snap several clips at once
Manifest `snaps.json`: `{"clip_name": {"beat": 7.0, "dur_s": 7.5, "bpm": 134}, ...}`,
then `ableton als snap <FILE.als> --manifest snaps.json [--commit] --json`.

Always show Madison the dry-run diff before committing.
