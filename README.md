# ableton-tools

Give Claude Code a set of Ableton Live tools it can run for you: check whether
a folder of stems really sums back to a master, find a project's true tempo and
drift, transcribe an audio part to MIDI, and edit `.als` files safely (repoint
samples, import stems in sync, group and organize tracks, copy device chains
between sets). Everything runs through one `ableton` dispatcher backed by a
local, uv-managed Python engine. Works with Ableton Live 12 and Live 11 sets.

It started as a pile of one-off scripts for a single problem: exported stems
that drifted out of phase against their master. It grew into a small toolkit
for the fiddly, error-prone parts of working with `.als` projects, wrapped so
Claude can drive it in plain language.

Requires [uv](https://docs.astral.sh/uv/) (the engine runs under it; Intel
Macs are supported) and
`ffmpeg`/`ffprobe` on PATH for audio decoding.

## Status

The mainstay is **stem alignment**: let Ableton auto-warp a master (a Suno
render, say), then have `als import-stems` clone that warped master onto each
stem so they all share its warp map. Around it sit session building (groups
routed to their bus, bare tracks, mutes, re-syncing stems to a moved master),
`.als` re-linking and validation, and stem/level/fragment analysis. That is the
solid core, and it complements Ableton rather than replacing it.

**Experimental**, so treat their output as a starting point to check by ear or
eye, not a replacement:

- `midi-transcribe`, and the tempo/grid-warp features (`tempo`, `drift`,
  `warp-check`, `als warp-to-grid`). These overlap with Ableton's own
  audio-to-MIDI and auto-warp, and have not been benchmarked against those
  built-ins.
- `als transplant-devices`. It is verified on 2,053 real device chains, but
  you should still listen to the result in Live.

## Install

This repo is its own plugin marketplace. Add it, then install at user scope:

```
claude plugin marketplace add madisonrickert/ableton-tools
claude plugin install ableton-tools@ableton-tools
```

Verify with `/plugin` (it should list `ableton-tools`) or by asking Claude to
run `ableton manifest --json`, which lists every subcommand.

## In practice

You work in Claude Code, not the terminal. Ask in plain language and the right
skill runs the engine for you:

- "I auto-warped the Suno master in Ableton; align the matching stems to it,
  color-coded." runs als import-stems: one clone of the warped master per stem,
  samples repointed, only the master kept as tempo leader.
- "Do these stems sum back to master.wav?" runs stem-verify: windowed
  cancellation depth, correlation, and a sibling verdict.
- "This project points at the old sample folder; repoint it to Samples/Imported."
  dry-runs the als rename diff, then commits with an automatic backup.
- "Group the vocal stems into a VOX folder, mute the silent stems, and put my
  usual sax chain from the last project on a new SAX track." runs als group,
  als mute, als add-track and als transplant-devices.
- "I moved the master clip in Live; fix the other tracks." runs als
  sync-to-master, which snaps every warped stem to the master's position.

Every `.als` edit is previewed before anything is written. Close Ableton while
committing one.

## Skills

Each row is a skill Claude invokes for you; the command is what it runs under
the hood.

| Skill | Runs | What it does |
|---|---|---|
| als-files | `ableton als inspect \| validate \| rename \| move \| import-stems` | Inspect and validate a `.als` (tempo, tracks, groups, routing, clips, refs). Safely rename or move the audio it references. Import stems as color-coded clones of a warped master: same-timeline tolerance, Session/unwarped placement, silent-stem skip/mute. |
| als-build | `ableton als set-tempo \| add-track \| group \| mute \| sync-to-master \| transplant-devices` | Build and organize a session: real group folders routed to their bus, bare tracks, mutes, stems re-synced to a moved master. Also copies device chains between sets (experimental). |
| als-warp | `ableton als warp-to-grid \| move-clip \| snap` | Grid-lock clips to a fixed project tempo with two warp markers each, and reposition clips to exact beats. |
| midi-compare | `ableton midi compare` | Compare two or three MIDI files by harmonic content (chroma cosine) and timing drift. |
| midi-transcribe | `ableton midi transcribe` | Transcribe an audio stem to MIDI via Spotify basic-pitch, tuned for monophonic/lightly polyphonic leads. |
| stem-verify | `ableton stem-verify \| levels \| locate` | Verify whether a folder of stems sums back to a master (a "sibling" check). Triage files by level and silence, and spot duplicates. Find where a fragment occurs in a reference. |
| tempo-drift | `ableton tempo \| drift \| warp-check` | Detect a file's tempo (beat-tracked, precise, and drift). Measure time drift between a master and its stems-sum. Check that a set's warp map sits on the real beats and is shared by every warped stem. |
| engine | `ableton <subcommand> [--json]` | The shared dispatcher and library behind the others; use directly for a raw subcommand or when `ableton` cannot be found. |

## Safety

`.als` files are your projects, so the engine treats them carefully.

- **Nothing is written without a preview.** Every mutating `als` command is
  dry-run by default, and its preview includes a structural validation report.
  It only writes with `--commit`, which works like this:
  - It refuses while Ableton Live is running, because Live would silently
    overwrite the edit on its next save. `--force` overrides.
  - It refuses if the file changed since it was read.
  - It validates the result, and refuses to write a set Live would reject.
  - It saves a backup to `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als`
    (Ableton's own auto-backup convention, so it appears in Live's rollback
    UI).
  - It re-verifies every project sample reference after writing, and
    auto-restores from the backup if any break.
- **Edits are lossless.** The engine indexes the decompressed XML's exact byte
  spans and patches only the bytes it changes. A no-op round-trip is
  byte-identical, so diffs stay small and Ableton's own version history is not
  disturbed.
- **It runs locally, with no API keys.** Analysis commands emit raw numbers and
  threshold bands (`worst_db`, `chroma_cosine`, drift stats); reading them and
  stating a verdict is the skill's job, not an external service's.
- **Failures are legible.** Usage problems exit nonzero with
  `{"error": "...", "hint": "..."}`; a traceback means a bug, not a mistake you
  made.
- **The heavy transcription dependency is opt-in.** Only `ableton midi
  transcribe` pulls in basic-pitch/TensorFlow, added on demand so the default
  environment stays light.

## Stem import

By default, `als import-stems` refuses to run (structured error, no partial
writes) unless every stem's frame count and sample rate exactly match the
master's. The clones inherit the master's warp markers verbatim, which is only
valid when the audio timelines are identical. Suno stems satisfy this by
construction.

For same-timeline files that differ slightly, pass `--tolerance-ms N` to relax
the check. Typical cases are MP3 decoder padding, a different sample rate, or
stems separated from the master. With the relaxed check, lengths may differ by
up to N ms. Each stem's start lag against the master is measured and reported,
and a correlated stem that is offset is still rejected.

Un-synced material can go to Session view instead, at native speed, with
`--to session --unwarped`. Track coloring follows a default per-stem convention (override with
`--colors`); the full XML mechanics (SampleRef fields, EffectiveName
derivation, color table) live in `engine/references/als-format.md`.

## Development

From the repo root:

```
uv run --project engine --group dev pytest
uvx ruff check engine
uvx pyright --project engine engine/src
```

The `--project engine` on pyright is required so it resolves `engine/.venv`
(`engine/CLAUDE.md` explains why). Run `claude plugin validate .` before
committing, and bump `version` in `.claude-plugin/plugin.json` when behavior
changes so the plugin cache refreshes.

## More Ableton tools

Other Ableton Live extensions I've built (native panels on the [Live Extensions
SDK](https://www.ableton.com/en/live/extensions), separate from this Claude Code
plugin):

- **[AbleVSEP](https://github.com/madisonrickert/ablevsep):** Separate any audio
  clip into stems with any of MVSEP's 100+ models, right inside Ableton Live. It
  mirrors Live's built-in Stem Separation, but exposes MVSEP's full model catalog
  instead of one fixed algorithm.
- **[AbleTab](https://github.com/madisonrickert/abletab):** View any MIDI clip in
  Ableton Live as stringed-instrument tablature. Pick an instrument preset or dial
  in a custom tuning, then export PDF or ASCII tab.
- **[Ableton Sheet Music Extension](https://github.com/madisonrickert/ableton-sheet-music-extension):**
  View any MIDI clip in Ableton Live as readable sheet music. Transpose it for any
  instrument and export MusicXML, PDF, or PNG.
