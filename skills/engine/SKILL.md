---
name: engine
description: Shared engine for the ableton-tools skills — a uv-managed Python library behind the single 'ableton' dispatcher (stem verification, levels/locate, tempo/drift/warp analysis, MIDI transcription/comparison, safe lossless .als editing, stem import, session building, device transplant). Invoke a specific ableton-tools skill for a task; use this directly to run a raw subcommand, extend the library, or when the 'ableton' command cannot be found.
---

This skill is the engine behind the ableton-tools command skills. It bundles
reusable signal-processing and `.als`-editing logic distilled from a set of
one-off analysis scripts (see `engine/references/source-scripts.md`).

## Running the dispatcher

The plugin puts `ableton` on the Bash PATH:

`ableton <subcommand> [args] [--json]`

`ableton manifest --json` lists every subcommand with its arguments,
including nested ones. The shim runs under uv and adds the heavy
`transcribe` extra only for `ableton midi transcribe`.

If `ableton` is not on PATH (plugin disabled, headless quirk), call the
dispatcher directly: `<plugin-root>/engine/bin/ableton`, where
`<plugin-root>` is this skill's grandparent directory — the plugin cache
copy (`~/.claude/plugins/cache/ableton-tools/ableton-tools/<version>`) or a
local checkout of the repo.

## Subcommands

- `stem-verify --stems <dir> --master <file>` — does a stems folder sum to a master?
- `levels <dir> [--ref FILE]` — dBFS, silence, duration/rate, r vs a reference.
- `locate --fragment F --ref R` — where a fragment occurs in a reference.
- `warp-check <file.als>` — warp markers vs real beats; clips sharing the map.
- `tempo <file> [--hint-bpm N]` — detected BPM, sub-ms precise BPM, and drift.
- `drift --master <file> --stems <dir>` — per-window time-drift trace.
- `midi transcribe <audio> [--out file.mid]` — audio → MIDI (basic-pitch).
- `midi compare <a.mid> <b.mid> [c.mid]` — chroma similarity + timing drift.
- `als inspect <file.als>` — tempo, tracks (group/routing/mute), clips
  (session/arrangement, Time, warp-map BPM), file refs as JSON.
- `als validate <file.als>` — structural checks + typed ref report (read-only).
- `als rename|move <file.als> --manifest map.json` — patch file references.
- `als warp-to-grid <file.als> --tempo BPM --clips clips.json` — grid-lock clips.
- `als move-clip <file.als> --clip NAME --to-beat B [--dur-s S --bpm BPM]`.
- `als snap <file.als> --manifest snaps.json` — batch clip repositioning.
- `als import-stems <file.als> --master-track <id|name> --stems <dir>` —
  clone a warped master per stem and relink (see the als-files skill).
- `als set-tempo | mute | add-track | group | sync-to-master` — session
  building (see the als-build skill).
- `als transplant-devices <target.als> --from <src.als> …` — copy a device
  chain between sets (experimental; see the als-build skill).

## Verdicts are yours, not the tool's

By design, commands emit raw numbers plus threshold bands (e.g. `stem-verify`
returns `worst_db`, `median_db`, and `bands`). Read the JSON and state the
verdict yourself — no LLM/API call is built in.

## Errors are structured

Operator-correctable failures exit nonzero with `{"error": ..., "hint": ...}`
on stderr (JSON mode) or `error:`/`hint:` lines (human mode), plus a `kind`
where one applies. `kind: "internal"` (exit code 4) is an engine invariant
that failed: nothing was written, and it is a bug to report. Any other
traceback is also an engine bug, not a usage problem.

## Safety for `.als` edits

Every mutating `als` subcommand defaults to a dry-run JSON diff (with a
`validation` report). Pass `--commit` to write. The commit refuses while
Ableton Live is running (`--force` overrides; Live would overwrite the edit
on its next save) and when the file changed since it was read; it validates
the result first, backs up to `<project>/Backup/<basename> [YYYY-MM-DD
HHMMSS].als` (Ableton's native convention — visible in Live's rollback UI),
writes, then re-verifies project-relative file refs and restores from the
backup if any break. Edits are lossless byte splices (`alsxml`). Always close
Ableton before committing edits to a `.als`.

## Library API (for extension)

`engine/src/ableton_tools/`: `audio` (I/O, mono-sum, envelope), `align`
(xcorr + LSQ lag), `cancel` (cancellation dB, stem_verify), `tempo`, `midi`,
`transcribe`, `alsxml` (lossless span-indexed .als access + byte-splice
edits), `als` (inspect + patchers + `clone_track`), `validate` (structural
checks + typed refs), `commit` (guarded commit pipeline), `import_stems`
(stem-import policy + color convention), `session` (tempo/mute/add-track/
group/sync), `devices` (chain transplant), `analysis` (levels/locate/
warp-check), `errors` (`UsageError`, `InternalError`). See
`engine/CLAUDE.md` for JSON shapes and `engine/references/` for the `.als`
format notes and source-script lineage. Dev loop, from the repo root:
`uv run --project engine --group dev pytest`, `uvx ruff check engine`,
`uvx pyright --project engine engine/src` (the `--project` is required; see
`engine/CLAUDE.md`).
