---
name: als-files
description: Inspect an Ableton .als project (tempo, tracks, clips, file references) and safely rename or move the audio files it references while patching the .als so links stay intact. Use when reorganizing a project's sample files or auditing what a .als points to. Mutations are dry-run by default and auto-backup before committing.
---

You inspect and re-link `.als` projects using the shared Ableton engine
(`ableton-shared`, a sibling skill). **Close Ableton before committing edits.**

## Inspect
`<repo>/ableton-shared/bin/ableton als inspect <FILE.als> --json`
Returns tempo, tracks, and every clip's name, beat bounds, relative path, and
warp state.

## Rename / move referenced files
1. Move/rename the actual audio files on disk yourself (or describe the intent).
2. Write a manifest `map.json`: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
3. Dry-run: `<repo>/ableton-shared/bin/ableton als rename <FILE.als> --manifest map.json --json`
   — prints the diff, writes nothing.
4. Commit: add `--commit`. The engine first saves
   `<name>.als.backup-pre-rename-<timestamp>`, patches refs, then re-verifies
   every reference resolves and auto-restores from backup if any break.

`als move` is identical to `als rename` (same patcher); use whichever verb fits.
Always show Madison the dry-run diff before committing.
