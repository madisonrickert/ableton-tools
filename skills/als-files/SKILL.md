---
name: als-files
description: Inspect and validate an Ableton .als project (tempo, tracks, groups, routing, Session/Arrangement clips, file references, locators with tempo-map-accurate seconds), split a rendered arrangement into one file per locator section (ableton split) and safely rename or move the audio files it references while patching the .als so links stay intact. Also imports a folder of stems (Suno, MVSEP, remastered vocals…) as color-coded clones of a warped master track that share its warp map (als import-stems), or as un-synced takes in Session view. Use when reorganizing samples, auditing what a .als points to, checking a set is healthy, or loading stems in sync. Mutations are dry-run by default and auto-backup before committing.
---

You inspect, validate, and re-link `.als` projects using the bundled Ableton
engine (the `ableton` command on PATH). **Close Ableton before committing
edits.** The engine refuses to commit while Live is running, because Live
would overwrite the edit the next time it saves.

## Inspect
`ableton als inspect <FILE.als> --json`

Returns:
- tempo, and the main track;
- every track's kind, group, output routing, mute state and device count;
- every clip's location (`session` or `arrangement`), `time` (Arrangement
  position), beat bounds, warp state, warp-marker count, `warp_map_bpm` (the
  native-speed tempo of its warp map), relative path and `relative_path_type`.

Works on Live 12 and Live 11 sets.

## Validate (read-only)
`ableton als validate <FILE.als> --json`

Returns structural errors and warnings, plus a ref report. Run it when a set
won't open or behaves oddly, and after any hand edit.

Errors include:
- duplicate track or pointee ids;
- `NextPointeeId` too low;
- a string in an int node, such as `ScaleInformation/Name` (this is what Live
  reports as "Unexpected value for int node");
- a dangling group.

Warnings include grouped tracks that bypass their group bus.

The ref report:
- `missing_project`: project files that don't resolve;
- `missing_external`: absolute files that aren't found (Live will ask to
  locate them);
- library/built-in counts: these always resolve.

## Locators and splitting a render
`ableton als locators <FILE.als> --json` lists every Arrangement locator with
its beat and its time in seconds, following the tempo automation (steps and
ramps), plus where the arrangement ends.

To cut an exported render into one file per locator section (e.g. a show
track into per-cue files):

1. Export the arrangement; note where the export starts (by default the
   first locator).
2. Dry-run: `ableton split <RENDER.wav> --als <FILE.als> --out <DIR> [--names map.json] --dry-run --json`.
   Check `first_audible_s` is near 0 and there's no length warning; if there
   is, pass `--start <locator name|beat>`.
3. Run without `--dry-run`. Silent sections (gaps between locators) are skipped
   with a warning; trailing silence is trimmed to `--tail-pad` (0.5 s).
   `--names` maps locator names to file names.

## Rename / move referenced files
1. Move or rename the actual audio files on disk yourself, or describe the
   intent.
2. Write a manifest `map.json`: `{"old/rel/path.wav": "new/rel/path.wav", ...}`.
   Keys can also be absolute paths of files outside the project (relinking
   them to a project copy). Each matched FileRef gets the new RelativePath,
   RelativePathType 3 and a matching absolute Path. `<OriginalFileRef>`
   entries are import provenance Live doesn't load from, and are left alone.
   Check `diff.refs` (refs rewritten) as well as `diff.changed` (entries matched).
3. Dry-run: `ableton als rename <FILE.als> --manifest map.json --json`.
   This prints the diff and a validation report, and writes nothing.
4. Commit: add `--commit`. The engine then:
   - refuses if Live is running or the file changed since it was read;
   - validates the result;
   - writes a backup to `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als`
     (it shows up in Live's rollback UI);
   - patches the refs;
   - auto-restores from the backup if any project file ref breaks.

   Built-in and library device presets never trigger a restore.

`als move` is identical to `als rename`; use whichever verb fits. Always show
the user the dry-run diff before committing.

## Import stems aligned to a master
When the user has imported and auto-warped a master in Ableton and wants
matching stems loaded as separate, in-sync tracks:

`ableton als import-stems <FILE.als> --master-track <id|name> --stems <DIR> [--pattern '*.wav'] [--colors colors.json] [--commit] --json`

What it does:
- clones the master track per stem, warp markers and all, so every stem
  shares the master's exact tempo map;
- repoints each clone's sample refs;
- names clips with bare labels (numeric filename prefixes stripped);
- demotes `IsSongTempoLeader`;
- keeps the master's volume, pan and sends, but clears frozen audio, take
  lanes, mute, solo and arm;
- applies the default color convention: Lead Vocals 20, Backing Vocals 7,
  Drums 3, Bass 17, Synth/Keys 14, Other/FX 23. Override with `--colors`.

`--master-track` accepts the Id, the exact name, or the name without Live's
`<index>-` prefix (Live renames tracks to `"4-WORD vocals"` on save). The
master's duplicate Session clip is dropped from the clones unless you pass
`--keep-session`.

**Timeline check.** By default every stem must match the master's frame count
and sample rate, which is guaranteed for Suno stems. Same-timeline files that
differ slightly need `--tolerance-ms 50` instead. Typical cases:
- MP3-decoder padding, around 24 ms;
- a different sample rate;
- stems separated from the master (MVSEP etc.).

That check allows the length difference, measures each stem's start lag
against the master (`diff.timeline[].lag_ms`), and rejects only a correlated
stem that is offset.

**Other placements and levels:**
- `--to session --unwarped`: for un-synced material (raw takes, unplaced
  fragments). It puts each file in the first Session clip slot (scene 1) at native speed. **Don't put
  un-synced audio on the Arrangement timeline.**
- `--skip-below -60` / `--mute-below -60`: drop, or import muted, stems that
  are effectively silent. Check first with `ableton levels DIR`.

**Workflow:**
1. Confirm Ableton is closed.
2. Dry-run, and show the user the diff: new track names, colors, sample refs,
   validation.
3. Run with `--commit`.

To group the result, mute tracks, or align positions afterwards, see the
`als-build` skill. XML-level mechanics live in the engine's
`references/als-format.md`.
