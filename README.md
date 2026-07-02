# ableton-tools

Ableton Live toolkit as a Claude Code plugin: stem verification, tempo/drift
analysis, MIDI transcription and comparison, and safe `.als` editing (rename,
warp-to-grid, and stem import), all driven through a single `ableton`
dispatcher backed by a uv-managed Python engine.

Requires [uv](https://docs.astral.sh/uv/) (the engine runs under it) and
`ffmpeg`/`ffprobe` on PATH for audio decoding.

## Install

This repo is its own plugin marketplace (`.claude-plugin/marketplace.json` at
the root). Add it, then install at user scope:

```
claude plugin marketplace add madisonrickert/ableton-tools
claude plugin install ableton-tools@ableton-tools
```

Verify with `/plugin` (should list `ableton-tools`) or by running
`ableton manifest --json` in a session, which lists every subcommand the
dispatcher supports.

## Skills

| Skill | Invocation | What it does |
|---|---|---|
| als-files | `ableton als inspect \| rename \| move \| import-stems` | Inspect a `.als` project (tempo, tracks, clips, refs) and safely rename/move the audio it references, or import a folder of stems as color-coded clones of a warped master track. |
| als-warp | `ableton als warp-to-grid` | Grid-lock clips to a fixed project tempo with two warp markers each, so stems stay phase-coherent. |
| engine | `ableton <subcommand> [--json]` | Shared dispatcher and library behind all the other skills; use directly for a raw subcommand or when `ableton` cannot be found. |
| midi-compare | `ableton midi compare` | Compare two or three MIDI files by harmonic content (chroma cosine) and timing drift. |
| midi-transcribe | `ableton midi transcribe` | Transcribe an audio stem to MIDI via Spotify basic-pitch, tuned for monophonic/lightly polyphonic leads. |
| stem-verify | `ableton stem-verify` | Verify whether a folder of stems sums back to a given master (a "sibling" check). |
| tempo-drift | `ableton tempo \| drift` | Detect a file's tempo (beat-tracked, precise, and drift) and measure time drift between a master and its stems-sum. |

## Architecture invariants

- **Regex-over-raw-XML patching.** `.als` mutations use targeted regex against
  the decompressed XML to preserve the original file's formatting exactly.
  Never rewrite this to a DOM library (lxml, ElementTree for writes): that
  would reformat the whole file and blow up diffs in Ableton's own history.
  `inspect` (read-only) uses ElementTree, which is fine since it never writes.
- **Dry-run by default.** Every mutating `als` command writes nothing unless
  passed `--commit`. On commit, the engine first writes a backup to
  `<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` (Ableton's own
  auto-backup convention, so it shows up in Live's rollback UI), patches
  refs, then re-verifies every reference resolves, auto-restoring from
  backup if any break.
- **Verdicts belong to the operator, no API calls.** Tools like `stem-verify`
  and `midi compare` emit numbers (`worst_db`, `chroma_cosine`, drift
  stats); the skill's job is to report them and state a verdict, not to call
  out to an LLM API for judgment. No `ANTHROPIC_API_KEY` or equivalent is
  designed into this engine.
- **Structured failures.** Usage problems raise `UsageError` and render as
  `{"error": "...", "hint": "..."}` on stderr with a nonzero exit (2 for
  usage errors, 3 for missing files). An unhandled traceback means an engine
  bug, not a usage mistake.
- **`transcribe` extra installs on demand.** The default environment stays
  light; `ableton midi transcribe` is the only invocation that pulls in
  basic-pitch/TensorFlow, added via `uv run --extra transcribe` only for
  that subcommand.

### Stem import

`als import-stems` refuses to run (structured error, no partial writes)
unless every stem's frame count and sample rate exactly match the master's.
The clones inherit the master's warp markers verbatim, which is only valid
when the audio timelines are identical; Suno stems satisfy this by
construction, but other sources may not. Track coloring follows a default
per-stem convention documented in `skills/als-files/SKILL.md` (override with
`--colors`); the full XML-level mechanics (SampleRef fields, EffectiveName
derivation, color table) live in `engine/references/als-format.md`.

## Maintenance

- Bump `version` in `.claude-plugin/plugin.json` whenever skill or engine
  behavior changes, so the plugin cache refreshes on next install.
- Run `claude plugin validate .` before committing (the repo root is both the
  plugin and its marketplace).
- Dev loop, from the repo root:

  ```
  uv run --project engine --group dev pytest
  uvx ruff check engine
  uvx pyright --project engine engine/src
  ```

  Note the explicit `--project engine` on the pyright invocation:
  `engine/pyproject.toml` sets `venvPath = "."` (relative to the config
  file), and pyright only resolves that correctly once it knows where the
  config lives. Running `uvx pyright engine/src` from the repo root without
  `--project` leaves pyright to auto-discover the config relative to the
  invocation cwd instead, so it can't find `engine/.venv` and reports
  spurious `reportMissingImports` errors on every third-party dependency
  (numpy, scipy, soundfile, mido, librosa).

## License

MIT. See [LICENSE](LICENSE).
