# ableton-tools 1.1.0 — Design

Status: approved in brainstorming (2026-10-06). Ships as plugin **1.1.0** / engine **0.3.0**.

## Why

During a real commission (assembling an Ableton Live 12.4 session from a Suno master, MVSEP
stems, remastered vocals, and GarageBand takes), the plugin failed on Live 12 files or couldn't
do what was needed. Every gap got a throwaway script. Some of those produced files that Live
rejected ("Unexpected value for int node"); others misbehaved silently: stems that didn't move,
groups that weren't routed.

This release:

- fixes the engine bugs, two of which break shipped commands on essentially every real Live 12
  set;
- replaces the regex-based XML editing that caused most of them;
- promotes the proven scratch workflows into tested commands.

**Success criteria**

- The full stems-session workflow can be reproduced with engine commands only — no scratch scripts.
- Every output validates and loads in Live 12.
- The engine installs and runs on Intel Macs.
- Editing stays lossless: no-op edits produce byte-identical files.

The work is four sub-projects in dependency order, shipped as one release.

---

## Sub-project 1 — Live 12 correctness and install

### 1.1 `alsxml`: the expat span index (new `engine/src/ableton_tools/alsxml.py`)

All `.als` reads and edits go through this module; no other code applies regexes to the XML.

**Why this approach.** We benchmarked candidates on a real 8.5 MB Live 12 set:

| Option | Parse time | Lossless? | Notes |
|---|---|---|---|
| stdlib expat | 0.08 s | Yes, via splicing | **Chosen.** No new dependency. |
| lxml | 0.08 s | No | A no-op round-trip rewrote 44 KB. |
| tree-sitter-xml | 0.91 s | Yes | Fallback option. |
| xmlcst | 2.74 s | Yes | Alpha, Python ≥ 3.12. |

The Ableton-specific libraries don't fit:

- buildable uses lxml and re-serializes the file;
- abletoolz is GPL-3.0;
- pyableton is parse-only.

**`Doc`**

- Holds the decompressed **bytes**. It indexes bytes, not str, so UTF-8 and emoji paths are
  handled correctly.
- Builds a lazy span index in one expat pass. Each node records `tag, attrs, start, end,
  parent, depth`, where `start`/`end` bound the whole element.
- **Empty-element quirk:** for `<X … />`, expat reports the end event at the offset of the
  *next* token. A Default/char handler therefore records token boundaries, and an empty
  element's `end` is the next token's start.
- The index is rebuilt after each committed batch of edits.

**Queries.** These return nodes, never strings.

- `doc.tracks()` returns Audio/Midi/Group/Return tracks. `doc.main_track()` returns `MainTrack`
  on Live 12 and falls back to `MasterTrack` on Live 11.
- `track.effects_devices()` follows the structural path `DeviceChain/DeviceChain/Devices`. It is
  rack-safe and valid for every track type.
- `track.session_clips()` and `track.arrangement_clips()`.
- `doc.find_track(name)` is prefix-tolerant: `"X"` matches `"4-X"` (Live rewrites
  `EffectiveName` as `<index>-<clip>`). An ambiguous match raises `UsageError`.
- `node.child(tag)` and `node.path("A/B")` walk **direct children only**. This prevents the
  `ScaleInformation/Name` and rack-inner-chain mix-ups.

**Edits.** Edits are recorded as `(start, end, bytes)` splices and applied atomically by
`commit_edits()`. Overlapping splices raise.

- `set_value(node, v)` rewrites only that node's `Value="…"`.
- `set_attr(node, name, v)`, for example a clip's `Time`.
- `replace(node, b)`, `insert_before(node, b)`, `remove(node)`.

**Id helpers.**

- `max_id()` and `bump_next_pointee()`.
- `offset_ids(fragment, offset)` touches only `Id="N"` attributes. It never touches
  `ParameterId`, `UniqueId`, `LomId` or other `*LomId` attributes.

**Existing modules.** `als.py` keeps its public API and CLI behaviour, reimplemented on
`alsxml`. `import_stems.py` drops `_patch_attr` and `_patch_attr_in_clips`.

**Out of scope:** XPath and full-schema validation.

### 1.2 Bug fixes

| Bug | Fix |
|---|---|
| `inspect` tempo is `null`; `set_tempo` / `warp-to-grid` fail on Live 12 (`MainTrack`; a `LomId` sits between `Tempo` and `Manual`) | `main_track().path("DeviceChain/Mixer/Tempo/Manual")`, falling back to `MasterTrack` |
| `import-stems` overwrites `<ScaleInformation><Name>`, so Live refuses to load the set | Set the name via `clip.child("Name")` only |
| `warp-to-grid` IsWarped regex expects `"/>`, but Live writes `" />` | `set_value(clip.child("IsWarped"), "true")` |
| `[\d.]+` regexes miss negative, exponent and long-float values | Edit by node |
| `move-clip` recomputes length from `dur_s*bpm`, which is wrong on drifting warp maps | Shift `Time`, `CurrentStart` and `CurrentEnd` by one delta; `--dur-s` becomes optional |
| `--master-track NAME` fails after Live renames the track | Resolve with `find_track` (prefix-tolerant) |
| `import-stems` duplicates the master's Session clip into every clone | Empty clone Session slots when the master has an arrangement clip; `--keep-session` opts out |
| `inspect` is thin and lists Main/PreHear with `id: None` | Extend it (below) |

**`inspect` additions.** Existing keys are unchanged.

- Tracks gain: kind, group id, output routing, muted, device count.
- Main is reported separately, and PreHear is omitted.
- Clips gain: track, location (`session` / `arrangement`), `time`, `warp_marker_count`,
  `warp_map_bpm` (the native-speed average), and `relative_path_type`.

### 1.3 Commit safety (`cli._als_commit` + new `validate.py`)

Every mutating command commits through these steps, in order:

1. **Guard.**
   - Refuse if the file's hash or mtime changed since it was read (`file_changed`).
   - Refuse if Live is running: `pgrep -x Live` on macOS, `tasklist` on Windows
     (`live_running`). `--force` overrides the Live check only.
2. **Validate the new XML before writing.**
   - It is well-formed.
   - Track ids and `AutomationTarget` ids are unique. Local ids (ClipSlot, WarpMarker, …) may
     repeat, as in real files.
   - `NextPointeeId > max Id`.
   - The int nodes `Root`, `Current*`, `Color`, `TrackGroupId`, `Time` and `Loop*` are numeric.
   - Every `TrackGroupId` resolves to a GroupTrack.

   Any failure returns `validation_failed` and nothing is written.
3. **Backup** using Live's native naming, as today.
4. **Write**, then check file refs by `RelativePathType`:

   | Type | Meaning | Check | On failure |
   |---|---|---|---|
   | 3 | Project-relative | Must resolve | Restore the backup (`refs_restored`) |
   | 1 | External | Absolute `Path` should exist | Warning only |
   | 5 | Core Library | Reported, not checked | — |
   | 7 | Built-in device | Reported, not checked | — |

   This removes the spurious restore that the template's built-in Reverb/Delay presets caused
   on nearly every set.

**`als validate FILE.als`** is a read-only command that runs the same checks plus the ref report.

`verify_refs` stays as a wrapper over the type-3 check, for compatibility.

Errors keep the existing `{"error","hint"}` shape and exit codes 2/3.

### 1.4 Install

- In `engine/pyproject.toml`, add `[tool.uv] constraint-dependencies` with
  `numba<0.63` and `llvmlite<0.46`. Both carry the marker
  `sys_platform=='darwin' and platform_machine=='x86_64'`.
- Re-run `uv lock`. The lock must fork by marker; every other platform keeps the latest
  versions.
- `engine/bin/ableton`: if `command -v uv` fails, print
  `ableton-tools needs uv: https://docs.astral.sh/uv/` and exit 127.

### 1.5 Fixtures and tests

**Fixtures** — sanitized derivatives of real Live 12.4 sets, approved by the owner. User paths
become `/Users/test/...`, names become generic, plugin blobs are stubbed, and warp markers are
trimmed.

- `live12_set.xml`:
  - `MainTrack`, with `LomId` inside Tempo;
  - an audio track with a Session clip and a warped arrangement clip (`ScaleInformation`,
    `Time`, 4 markers);
  - returns with type 1/5/7 device refs;
  - `NextPointeeId`;
  - 8 scenes.
- `live11_set.xml`: the existing `MasterTrack` shape.
- A conftest factory writes gzipped copies plus wav stubs.

**Tests**

- **alsxml:**
  - exact spans for empty, nested and emoji content;
  - `child()` / `path()` follow direct children only;
  - overlapping splices raise;
  - a no-op round-trip is byte-identical on both fixtures, and on a real Live 12 set (a
    local-only test, skipped if the file is absent).
- **Bug fixes:** one regression test per fix in §1.2, on the Live 12 fixture.
- **Commit safety:**
  - type-1/5/7 refs do not trigger a restore;
  - a changed file is refused;
  - a running Live (monkeypatched) is refused unless `--force`;
  - each validator invariant has a test.
- The existing suite, ruff and pyright stay green.

---

## Sub-project 2 — Session-building commands (composable)

All commands follow the same pattern:

- dry-run by default; `--commit` goes through §1.3;
- track arguments resolve via `find_track`;
- output is a diff of what changed.

### `als set-tempo BPM`

Sets the project tempo (Main/Master).

### `als mute --tracks … [--unmute]`

Sets the mixer `Speaker` `Manual` value.

### `als add-track --name N [--color C] [--after T]`

Creates a bare audio track:

- clone a track in the set, so the mixer and send shape match;
- empty its Session and arrangement clip containers;
- set the name and color.

### `als group --name N --tracks … [--color C]`

**Template.** `engine/src/ableton_tools/templates/group_track.xml`, a sanitized Live 12.4
GroupTrack: empty devices, no clips, 2 sends, 8 slots.

**Adapting the template to the target set**

- Rebuild `TrackSendHolder` entries to match the number of `ReturnTrack`s, by cloning the first
  holder.
- Rebuild `GroupTrackSlot` entries to match the number of `Scene`s.
- Offset ids above `max_id`, then bump `NextPointeeId`.
- Set `EffectiveName` / `UserName` and the color.
- Route the group's output to `AudioOut/Main`.
- Insert it before the first member.

**Members**

- Set `TrackGroupId` to the group's id.
- Set the output routing to `Target="AudioOut/GroupTrack"`, `UpperDisplayString="Group"`, with
  an empty `LowerDisplayString`.

**Errors**

- Members must be contiguous; otherwise error with a hint to reorder.
- A track that is already grouped is an error. Nested groups are out of scope.

### `als sync-to-master --master T (--tracks … | --all-warped) [--markers]`

- Copies from the master's arrangement clip to every warped arrangement clip on the targets:
  the `Time` attribute, `CurrentStart`/`CurrentEnd`, `LoopStart`/`LoopEnd`,
  `HiddenLoopStart`/`HiddenLoopEnd` and `StartRelative`.
- `--markers` also replaces the targets' `WarpMarkers`. Without it, any target whose markers
  differ is reported as a desync warning.
- Session clips and unwarped clips are never touched.

### `import-stems` extensions

**`--tolerance-ms N`**

- Accept a stem when `|Δlength| ≤ N`; any sample rate is allowed.
- Report `lag_ms` per stem, from `align.find_lag` on the first 30 s against the master.
- Reject `|lag| > 1 ms` only when correlation r > 0.3. Otherwise warn: "not mutually
  correlated — verify by ear".
- Clones keep the master's bounds.

**`--to session --unwarped`**

- Empty the arrangement clip and keep the Session slot-0 clip.
- Set `IsWarped=false`.
- `Loop*` / `HiddenLoop*` are in **seconds** (the file duration). This matches what Live itself
  writes for unwarped clips.
- `CurrentEnd = dur·bpm/60`, in beats.
- Drop the stale warp markers.

**`--mute-below DB` / `--skip-below DB`**

Uses per-stem RMS dBFS (`audio.rms`).

### Tests

- One fixture test per command and per flag.
- Every output must pass `validate`.
- A local-only end-to-end test rebuilds a stems session from a real seed set using only
  these commands, then validates it.

---

## Sub-project 3 — `als transplant-devices` (experimental)

```
ableton als transplant-devices TARGET.als --from SRC.als \
  (--src-track NAME | --src-main) (--to-track NAME | --to-main) \
  [--mode replace|append] [--with-automation] [--map-track SRC=DST]... [--commit]
```

### Schema basis

A read-only corpus survey covered **153 Live 11/12 sets** and **2,124 device chains**.

| # | Finding | Design consequence |
|---|---|---|
| 1 | The track-level chain is always at `<track>/DeviceChain/DeviceChain/Devices`, for every track type, including Live 11 Master and Live 12 Main. | Extract via `alsxml`. |
| 2 | 790 chains (37%) contain racks, and each rack branch nests its own `Devices`/`SignalModulations`. | The "first SignalModulations" anchor is wrong in all of them, so it is banned. |
| 3 | No live pointers exist inside chains: the only pointer tag is `<Pointee Value="0">`. `ParameterId`, `UniqueId` and `LomId` are internal. | Offsetting `Id="N"` is safe. |
| 4 | 876 `PointeeId`s outside chains point into them: track-level and clip automation. | Handle explicitly (Algorithm step 4). |
| 5 | Routing targets reference source-project tracks: 73 at top level and 225 inside racks (`AudioIn/Track.N/PostFxOut`, `…DeviceOut…`, `MidiOut/Track.N/…`). **N is the source track's `Id`** (verified in 210 of 211 refs), so a carried-over ref can silently hit an unrelated target track whose Id happens to match. | Reset or remap (Algorithm step 3). |
| 6 | Plugin descriptors: VST3 289, VST2 172, AU 5. Plugin state is embedded in the device block. | Copy bytes verbatim; report plugins. |

### Algorithm

1. **Copy** the source chain bytes verbatim, so plugin state is untouched.
2. **Re-id.** Offset every `Id="N"` in the chain, rack branches included, above the target's
   max id, then bump `NextPointeeId`.
3. **Routing.** (Corpus: 195 of 298 in-chain refs are *self* refs, where N is the source
   track's own Id: rack-internal `DeviceIn`/`DeviceOut` routing. The other 103 point at other
   tracks.)
   - Self refs: rewrite N to the destination track's Id. In `append` mode, shift the first
     `DeviceIn.X` / `DeviceOut.X` index by the number of devices already in the target chain.
   - Cross-track refs: recursively reset to the `…/None` form and update the display strings.
   - List each reset in the diff as "re-assign in Live".
   - `--map-track SRC=DST` remaps instead: SRC names a source-set track and DST a target-set
     track (both resolved via `find_track`), and `N` is substituted with DST's track `Id`.
4. **Automation.**
   - By default, report "N automation lanes not copied".
   - `--with-automation` copies the source track's `AutomationEnvelope`s that target the chain,
     with `PointeeId` remapped by the same offset.
   - Clip envelopes are never copied.
5. **File refs**, by `RelativePathType`:

   | Type | Action |
   |---|---|
   | 5 / 7 | Leave untouched. |
   | 3 | Copy the file into `TARGET/Samples/Imported/` and repoint. |
   | 1 | Warn if the absolute path is missing. |

6. **Plugins.** List each plugin's name and format. Warn if its bundle or component path is
   missing on this machine (Live would show a placeholder).
7. **Placement.**
   - `replace` swaps the target chain's contents.
   - `append` inserts before `</Devices>`, and also handles an empty `<Devices />`.
   - Targets can be tracks, groups, returns or Main.
8. **Validate** with `validate`. An extra rule applies: zero unmapped `Track.N` routing refs.

### Tests

- Sanitized fixtures:
  - a nested rack;
  - a sidechained Compressor inside a rack;
  - a stubbed VST3 device;
  - a type-3 sample ref;
  - an automation envelope.
- `engine/scripts/corpus_check.py` (dev-only, not in CI):
  - transplants every local chain into the Live 12 fixture;
  - requires 100% to validate, with 0 dangling routing refs.
- A manual Live load of a transplanted rack + sidechain chain before release.

---

## Sub-project 4 — Analysis helpers (read-only)

These commands emit raw numbers and threshold bands. Skills state the verdicts.

| Command | Output |
|---|---|
| `ableton levels DIR [--pattern] [--ref FILE]` | Per file: duration, sample rate, channels, RMS dBFS, `silent` (< −60 dBFS). With `--ref`: Pearson r with the reference at lag 0. |
| `ableton locate --fragment F --ref R [--env-hz 100] [--top 3]` | Normalized sliding-Pearson match on amplitude envelopes (FFT): best offset in seconds, `r`, and the top-N alternatives. |
| `ableton warp-check FILE.als [--track T] [--audio A]` *(experimental)* | For the master's warped clip: marker count and spacing; warp-map average BPM; marker→beat and marker→onset distances (median/p90 ms, librosa); a downbeat sanity check; and a sync report of which warped clips share the master's markers exactly. |

**`locate` bands**

- `r ≥ 0.8`: same render.
- `0.6–0.8`: likely match.
- `< 0.6`: not the same performance; place by ear.

**`warp-check` behaviour.** It states explicitly when a region (such as a sparse intro) has no
beats to verify against.

**Implementation reuse**

- `audio.load_mono`, `audio.rms`, `audio.envelope`;
- `alsxml` for reading the set;
- the tempo module's librosa path.

**Tests** use synthetic WAVs:

- a click track for `warp-check`;
- a fragment cut at a known offset from a reference, which `locate` must find within 10 ms with
  r > 0.95;
- silent and duplicate files for `levels`.

---

## Docs, skills, release

**Docs**

- `engine/references/als-format.md` gets a Live 12 section covering:
  - `MainTrack` and the `LomId` inside Tempo;
  - `ScaleInformation`;
  - the `Time` attribute as arrangement position;
  - the `RelativePathType` table (0/1/3/5/7);
  - the effects-chain path;
  - Session `ClipSlot/Value`;
  - group routing XML;
  - local ids vs pointee ids;
  - unwarped `Loop*` values being in seconds;
  - the `EffectiveName` rewrite.
- `engine/CLAUDE.md` documents every new command's arguments, JSON shape and errors.

**Skills**

- Update `als-files`, `als-warp`, `tempo-drift` (`warp-check`), `stem-verify` (`levels`,
  `locate`) and `engine`.
- Add a new `als-build` skill covering group, add-track, mute, set-tempo, sync-to-master,
  transplant-devices and validate, with the "close Live first" rule.

**README**

- New commands.
- Experimental labels for transplant, warp-check and warp-to-grid.
- "Requires uv" with a link.

**Versioning:** `plugin.json` 1.0.1 → 1.1.0; engine 0.2.0 → 0.3.0; regenerate `uv.lock`.

**Release steps**

1. Run ruff, pyright, pytest and `claude plugin validate .`.
2. Merge to main and tag `v1.1.0`.
3. **Pause for the owner's OK.**
4. `git push --follow-tags` and `gh release create v1.1.0`, with notes grouped as Fixes / New /
   Experimental / Behaviour changes.

**Behaviour changes to call out**

- `move-clip` without `--dur-s` preserves the clip's length.
- `import-stems` drops duplicate Session clips by default.
- `inspect` JSON gains fields (additive).
- Commits refuse while Live is running unless `--force` is given.

## Verification (end to end)

1. Run the full test suite on an Intel Mac with no constraint workarounds.
2. Local-only tests against the real project files:
   - byte-identical round-trip;
   - command-only rebuild;
   - `--commit` succeeds with no spurious restore.
3. Run the corpus transplant check.
4. **Manual Live 12 load of the rebuilt session.** Check:
   - groups are routed;
   - stems are at the master's position;
   - transplanted chains are present, and sidechains show "None";
   - RAW clips are in Session with the correct lengths.
5. After release: reinstall the plugin, then run `ableton --version` and
   `ableton manifest --json` from the cache.
