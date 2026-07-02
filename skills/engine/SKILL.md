---
name: engine
description: Shared engine for the ableton-suite skills — a uv-managed Python library behind the single 'ableton' dispatcher (stem verification, tempo/drift analysis, MIDI transcription/comparison, safe .als editing, stem import). Invoke a specific ableton-suite skill for a task; use this directly to run a raw subcommand, extend the library, or when the 'ableton' command cannot be found.
---

This skill is the engine behind the ableton-suite command skills. It bundles
the reusable signal-processing and `.als`-editing logic distilled from the
"Come With Me to Polar Palooza" project's analysis scripts.

## Running the dispatcher

The plugin puts `ableton` on the Bash PATH:

`ableton <subcommand> [args] [--json]`

`ableton manifest --json` lists every subcommand with its arguments,
including nested ones. The shim runs under uv and adds the heavy
`transcribe` extra only for `ableton midi transcribe`.

If `ableton` is not on PATH (plugin disabled, headless quirk), call the
dispatcher directly: `<plugin-root>/engine/bin/ableton`, where
`<plugin-root>` is this skill's grandparent directory — the plugin cache
copy (`~/.claude/plugins/cache/claude-custom-skills/ableton-suite/<version>`)
or the repo checkout (`~/Developer/claude-custom-skills/ableton-suite`).

## Subcommands

- `stem-verify --stems <dir> --master <file>` — does a stems folder sum to a master?
- `tempo <file> [--hint-bpm N]` — detected BPM, sub-ms precise BPM, and drift.
- `drift --master <file> --stems <dir>` — per-window time-drift trace.
- `midi transcribe <audio> [--out file.mid]` — audio → MIDI (basic-pitch).
- `midi compare <a.mid> <b.mid> [c.mid]` — chroma similarity + timing drift.
- `als inspect <file.als>` — tempo, tracks, clips, file refs as JSON.
- `als rename|move <file.als> --manifest map.json` — patch file references.
- `als warp-to-grid <file.als> --tempo BPM --clips clips.json` — grid-lock clips.
- `als move-clip <file.als> --clip NAME --to-beat B --dur-s S --bpm BPM`.
- `als snap <file.als> --manifest snaps.json` — batch clip repositioning.
- `als import-stems <file.als> --master-track <id|name> --stems <dir>` —
  clone a warped master per stem and relink (see the als-files skill).

## Verdicts are yours, not the tool's

Per Madison's no-Anthropic-API rule, commands emit raw numbers plus threshold
bands (e.g. `stem-verify` returns `worst_db`, `median_db`, and `bands`). Read
the JSON and state the verdict yourself — no API call is built in.

## Errors are structured

Operator-correctable failures exit nonzero with `{"error": ..., "hint": ...}`
on stderr (JSON mode) or `error:`/`hint:` lines (human mode). A traceback
means an engine bug, not a usage problem.

## Safety for `.als` edits

Every mutating `als` subcommand defaults to a dry-run JSON diff. Pass
`--commit` to write; on commit it first backs up to
`<project>/Backup/<basename> [YYYY-MM-DD HHMMSS].als` (Ableton's native
convention — visible in Live's rollback UI), then re-verifies all file refs
and restores from the backup if any break. Always close Ableton before
committing edits to a `.als`.

## Library API (for extension)

`engine/src/ableton_tools/`: `audio` (I/O, mono-sum, envelope), `align`
(xcorr + LSQ lag), `cancel` (cancellation dB, stem_verify), `tempo`, `midi`,
`transcribe`, `als` (inspect + patchers + `clone_track`), `import_stems`
(stem-import policy + color convention), `errors` (`UsageError`). See
`engine/CLAUDE.md` for JSON shapes and `engine/references/` for the `.als`
format notes and source-script lineage. Dev loop: `uv run --project
<engine> --group dev pytest`, `uvx ruff check`, `uvx pyright src`.
