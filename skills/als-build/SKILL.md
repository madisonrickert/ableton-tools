---
name: als-build
description: Build and organize an Ableton Live session from the command line — set the tempo, add bare tracks, fold tracks into real group folders (routed to the group bus), mute tracks, snap every warped stem to the master's position and warp map (sync-to-master), and copy proven device chains from other projects (transplant-devices, experimental). Use when assembling a project from stems, organizing tracks into groups, fixing stems that are offset from the master clip, or giving a new session a head start with device chains from past sets. All edits are validated, dry-run by default, and auto-backup before committing.
---

You assemble and organize `.als` sessions with the bundled engine (the
`ableton` command on PATH; see the `engine` skill). Every command is a dry-run
until `--commit`, and its JSON includes a `validation` report. **Close Ableton
before committing.** The commit refuses while Live is running, because Live's
next save would silently discard the edit.

Typical order when building from stems:
1. `als import-stems` (see the `als-files` skill);
2. `group`, `add-track`, `mute`;
3. `sync-to-master` if the user moved the master clip in Live;
4. `transplant-devices`;
5. `als validate`.

## Commands
| Need | Command |
|---|---|
| Project tempo | `ableton als set-tempo FILE.als 133.9 [--commit]` |
| Bare track for a new recording | `ableton als add-track FILE.als --name "SAX (live layer)" [--color 25] [--after master]` |
| Group folder | `ableton als group FILE.als --name WORDS --tracks "vocals" "lead v1" … [--color 20]` |
| Mute / unmute | `ableton als mute FILE.als --tracks "guitar" "strings" [--unmute]` |
| Stems out of position | `ableton als sync-to-master FILE.als --master master --all-warped [--markers]` |
| Reuse a device chain | `ableton als transplant-devices FILE.als --from OTHER.als --src-track Sax --to-track "SAX (live layer)"` |

Notes:
- **Track names** accept the exact name, the name without Live's `<index>-`
  prefix, or the Id.
- **group** members must be contiguous and not already grouped. It inserts a
  Live 12 group-track template: use it on Live 12 sets only.
  - The group gets `TrackGroupId`, and every member is **routed to the group
    bus**. Without that routing they would only *look* grouped.
  - Sends and slots adapt to the set's returns and scenes.
- **add-track** creates a track with no clips, devices, automation, frozen
  audio or take lanes, at default volume, pan and sends. It is never inserted
  inside a group.
- **sync-to-master** copies the master clip's Arrangement position (the `Time`
  attribute, CurrentStart/End and loop bounds) onto every warped stem clip.
  - Without `--markers`, `diff.marker_mismatch` lists stems whose warp map
    differs from the master's, i.e. stems that would drift.
  - `--markers` copies the master's warp map too.
  - Never re-warp just the master in Live and leave the stems; run this
    afterwards.
- **transplant-devices** is **experimental**. It copies a chain, plugin state
  included, from another set:
  - it fixes ids;
  - it remaps the chain's own internal routing;
  - it resets sidechains that pointed at other tracks to None
    (`diff.routing_reset`). Tell the user to re-assign them, or pass
    `--map-track SourceTrack=TargetTrack`;
  - it drops the source's automation of those devices
    (`--with-automation` keeps it);
  - it copies any project sample the chain uses into `Samples/Imported/`
    (only once the commit is allowed; a different file with the same name
    gets `<name> (2).<ext>`);
  - it reports plugins and whether each one is installed (`diff.plugins`).

  Use `--to-main` for mastering chains and `--mode append` to add to an
  existing chain. It has been verified on 2,108 real chains, but tell the user
  to check the result in Live.

## Verify
- Run `ableton als validate FILE.als --json` after a sequence of commits.
- Run `ableton warp-check FILE.als` (experimental) to confirm warped clips
  share the master's map and that its markers sit on the beats.
- Ask the user to open the set in Live. If Live reports an error, paste it
  back. Structural errors also show up in `als validate`.
