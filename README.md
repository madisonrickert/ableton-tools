# ableton-tools

Give Claude Code a set of Ableton Live tools it can run for you: check whether
a folder of stems really sums back to a master, find a project's true tempo and
drift, transcribe an audio part to MIDI, and edit `.als` files safely (repoint
samples, grid-lock warps, import stems in sync). Everything runs through one
`ableton` dispatcher backed by a local, uv-managed Python engine.

It started as a pile of one-off scripts for a single problem: exported stems
that drifted out of phase against their master. It grew into a small toolkit
for the fiddly, error-prone parts of working with `.als` projects, wrapped so
Claude can drive it in plain language.

Requires [uv](https://docs.astral.sh/uv/) (the engine runs under it) and
`ffmpeg`/`ffprobe` on PATH for audio decoding.

## Status

The mainstay is **stem alignment**: let Ableton auto-warp a master (a Suno
render, say), then have `als import-stems` clone that warped master onto each
stem so they all line up with it. That, plus `.als` re-linking and stem
verification, is the solid core, and it complements Ableton rather than
replacing it.

`midi-transcribe` and the tempo/grid-warp features (`tempo-drift`, `als-warp`)
are **experimental**: they overlap with Ableton's own audio-to-MIDI and
auto-warp, have not been benchmarked against those built-ins, and are not
verified to do better. Treat their output as a starting point to check by ear
or eye, not a replacement.

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

Every `.als` edit is previewed before anything is written. Close Ableton while
committing one.

## Skills

Each row is a skill Claude invokes for you; the command is what it runs under
the hood.

| Skill | Runs | What it does |
|---|---|---|
| als-files | `ableton als inspect \| rename \| move \| import-stems` | Inspect a `.als` project (tempo, tracks, clips, refs) and safely rename/move the audio it references, or import a folder of stems as color-coded clones of a warped master track. |
| als-warp | `ableton als warp-to-grid` | Grid-lock clips to a fixed project tempo with two warp markers each, so stems stay phase-coherent. |
| midi-compare | `ableton midi compare` | Compare two or three MIDI files by harmonic content (chroma cosine) and timing drift. |
| midi-transcribe | `ableton midi transcribe` | Transcribe an audio stem to MIDI via Spotify basic-pitch, tuned for monophonic/lightly polyphonic leads. |
| stem-verify | `ableton stem-verify` | Verify whether a folder of stems sums back to a given master (a "sibling" check). |
| tempo-drift | `ableton tempo \| drift` | Detect a file's tempo (beat-tracked, precise, and drift) and measure time drift between a master and its stems-sum. |
| engine | `ableton <subcommand> [--json]` | The shared dispatcher and library behind the others; use directly for a raw subcommand or when `ableton` cannot be found. |

## Safety

`.als` files are your projects, so the engine treats them carefully.

- **Nothing is written without a preview.** Every mutating `als` command is
  dry-run by default and only writes with `--commit`. On commit it first saves
  a backup to `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` (Ableton's
  own auto-backup convention, so it appears in Live's rollback UI), then
  re-verifies every sample reference and auto-restores from the backup if any
  break.
- **Edits preserve your file's formatting.** Mutations patch the decompressed
  XML in place with targeted regex rather than re-serializing through a DOM, so
  diffs stay small and Ableton's own version history is not disturbed.
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

`als import-stems` refuses to run (structured error, no partial writes) unless
every stem's frame count and sample rate exactly match the master's: the clones
inherit the master's warp markers verbatim, which is only valid when the audio
timelines are identical. Suno stems satisfy this by construction; other sources
may not. Track coloring follows a default per-stem convention (override with
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
