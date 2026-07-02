---
name: als-files
description: Inspect an Ableton .als project (tempo, tracks, clips, file references) and safely rename or move the audio files it references while patching the .als so links stay intact. Use when reorganizing a project's sample files or auditing what a .als points to. Mutations are dry-run by default and auto-backup before committing. Also imports a folder of Suno stems as color-coded, tempo-follower clones of a warped master track (als import-stems).
---

You inspect and re-link `.als` projects using the bundled Ableton engine
(the `ableton` command on PATH). **Close Ableton before committing edits.**

## Inspect
`ableton als inspect <FILE.als> --json`
Returns tempo, tracks, and every clip's name, beat bounds, relative path, and
warp state.

## Rename / move referenced files
1. Move/rename the actual audio files on disk yourself (or describe the intent).
2. Write a manifest `map.json`: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
3. Dry-run: `ableton als rename <FILE.als> --manifest map.json --json`
   — prints the diff, writes nothing.
4. Commit: add `--commit`. The engine first writes a backup into
   `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` (Ableton's native
   auto-backup convention, so it shows up in Live's rollback UI), patches
   refs, then re-verifies every reference resolves and auto-restores from
   backup if any break.

`als move` is identical to `als rename` (same patcher); use whichever verb fits.
Always show the user the dry-run diff before committing.

## Import Suno stems aligned to a master
When the user has imported and warped a master in Ableton and wants the
matching Suno stems loaded as separate, in-sync tracks:

`ableton als import-stems <FILE.als> --master-track <id|name> --stems <DIR> [--pattern '*.wav'] [--colors colors.json] [--commit] --json`

The command clones the master track per stem (warp markers and all), repoints
each clone's sample refs, names clips with bare labels (numeric filename
prefixes stripped, so Live's `<track-index>-<clip-name>` auto-naming stays
clean), demotes `IsSongTempoLeader` on every clone, and applies the default
track-color convention (Lead Vocals 20, Backing Vocals 7, Drums 3, Bass 17,
Synth/Keys 14, Other/FX 23 — override with `--colors`).

It refuses to run unless every stem matches the master's frame count and
sample rate — the clones inherit the master's warp markers verbatim, which is
only valid for identical audio timelines. Suno stems satisfy this by
construction; other sources may not.

Workflow: confirm Ableton is closed, dry-run, show the user the diff (new
track names, colors, sample refs), then `--commit`. XML-level mechanics live
in the engine's `references/als-format.md`.
