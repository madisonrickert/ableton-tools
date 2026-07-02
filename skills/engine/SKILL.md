---
name: engine
description: Shared engine for working with Ableton Live projects — a uv-managed Python library plus a single `bin/ableton` dispatcher used by the ableton-* command skills (stem verification, tempo/drift analysis, MIDI transcription/comparison, and safe .als editing). Invoke a specific ableton-* skill for a task; use this directly only to run a raw subcommand or extend the library.
---

This skill is the engine behind the `ableton-*` command skills. It bundles the
reusable signal-processing and `.als`-editing logic distilled from the
"Come With Me to Polar Palooza" project's analysis scripts.

## Running the dispatcher

All capability is exposed through one entrypoint, run under uv:

`<this-skill-dir>/bin/ableton <subcommand> [args] [--json]`

`ableton manifest --json` lists every subcommand. The shim adds the heavy
`transcribe` extra only for `ableton midi transcribe`.

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

## Verdicts are yours, not the tool's

Per Madison's no-Anthropic-API rule, commands emit raw numbers plus threshold
bands (e.g. `stem-verify` returns `worst_db`, `median_db`, and `bands`). Read
the JSON and state the verdict yourself — no API call is built in.

## Safety for `.als` edits

Every mutating `als` subcommand defaults to a dry-run JSON diff. Pass `--commit`
to write; on commit it first saves `<name>.als.backup-pre-<op>-<timestamp>`,
then re-verifies all file refs and restores from backup if any break. Always
close Ableton before committing edits to a `.als`.

## Library API (for extension)

`src/ableton_tools/`: `audio` (I/O, mono-sum, envelope), `align` (xcorr + LSQ
lag), `cancel` (cancellation dB, stem_verify), `tempo`, `midi`, `transcribe`,
`als` (inspect + patchers + `clone_track` primitive). See `CLAUDE.md` for JSON
shapes and `references/` for the `.als` format notes and source-script lineage.
