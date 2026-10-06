# ableton-tools 1.1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every engine command correct on real Live 12 sets. Then add composable
session-building, device-transplant and analysis commands, and ship plugin 1.1.0 / engine 0.3.0.

**Architecture:** A new `alsxml` module indexes the decompressed `.als` bytes with stdlib expat
(exact element spans, direct-child navigation). It applies edits as byte splices, so untouched
bytes stay identical. Every mutating command goes through one commit pipeline:
guard → validate → backup → write → typed ref check. Each feature lives in its own module:
- `session.py`
- `devices.py`
- `analysis.py`
- `validate.py`
- `commit.py`

`cli.SPEC` stays the single source of truth for the command surface.

**Tech Stack:** Python 3.11–3.12 · stdlib `xml.parsers.expat` · numpy / scipy / soundfile /
librosa (existing) · pytest · uv · ruff · pyright.

**Spec:** `docs/superpowers/specs/2026-10-06-ableton-tools-1.1-design.md`

## Global Constraints

- Lossless editing: a no-op parse+commit must be byte-identical. Only spliced spans change.
- Index **bytes**, not `str` (UTF-8 / emoji paths).
- `Id="N"` offsets never touch `ParameterId`, `UniqueId`, `LomId` or `*LomId`.
- Mutators are dry-run by default; `--commit` runs guard → validate → backup → write → ref check.
- Ref check by `RelativePathType`:

  | Type | Meaning | On a missing ref |
  |---|---|---|
  | 3 | project | Restore the backup |
  | 1 | external | Warn |
  | 5 | Core Library | Report only |
  | 7 | built-in | Report only |

- Error shape `{"error","hint"}`; exit 2 for usage errors, 3 for a missing file. New kinds:
  - `live_running`
  - `file_changed`
  - `validation_failed`
  - `refs_restored`
- Group member routing: `Target="AudioOut/GroupTrack"`, `UpperDisplayString="Group"`, empty lower string.
- Unwarped clips: `Loop*` / `HiddenLoop*` in **seconds**; `CurrentStart` / `CurrentEnd` in **beats**.
- In routing `Track.N`, N is the source track's `Id`.
- Intel constraints apply only on `sys_platform=='darwin' and platform_machine=='x86_64'`:
  `numba<0.63`, `llvmlite<0.46`.
- Missing uv: print `ableton-tools needs uv: https://docs.astral.sh/uv/` and exit 127.
- Versions: plugin 1.1.0, engine 0.3.0.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

| Input | Expected behaviour | Pinned in |
|---|---|---|
| Arrangement clips under `FreezeSequencer` (frozen tracks) | Not treated as editable clips | Task 2 test `test_freeze_sequencer_clips_ignored` |
| Ambiguous prefix match (`"Bass"` vs `"1-Bass"` and `"2-Bass FX"`) | Exact (prefix-stripped) match wins; a true tie raises | Task 2 `test_find_track_prefers_exact` |
| `group` on a set with 0 or 3 returns, or 12 scenes | Sends and slots adapt; output validates | Task 6 `test_group_adapts_sends_and_slots` |
| `transplant-devices` into a track whose `Devices` is already non-empty, with `--mode append` | Appends after existing devices; ids stay unique | Task 7 `test_transplant_append_nonempty` |
| `--commit` run twice in one second | Distinct backups (existing behaviour) and the file guard passes on the fresh read | Task 4 `test_commit_twice_same_second` |

---

## File map

| File | Responsibility |
|---|---|
| `engine/src/ableton_tools/alsxml.py` (new) | `Doc`/`Node` span index, queries, splices, id helpers |
| `engine/src/ableton_tools/validate.py` (new) | Structural invariants + typed ref report |
| `engine/src/ableton_tools/commit.py` (new) | Guard + commit pipeline (used by the CLI) |
| `engine/src/ableton_tools/als.py` (rewrite internals) | Same public API on `alsxml`; extended `inspect` |
| `engine/src/ableton_tools/import_stems.py` (modify) | Scoped naming; tolerance / session / level flags |
| `engine/src/ableton_tools/session.py` (new) | `set_tempo`, `mute`, `add_track`, `group`, `sync_to_master` |
| `engine/src/ableton_tools/templates/group_track.xml` (new) | Sanitized Live 12 GroupTrack |
| `engine/src/ableton_tools/devices.py` (new) | `transplant` |
| `engine/src/ableton_tools/analysis.py` (new) | `levels`, `locate`, `warp_check` |
| `engine/src/ableton_tools/cli.py` (modify) | SPEC + dispatch for every command |
| `engine/tests/fixtures/` (new) | `live12_set.xml`, `chain_src.xml` (sanitized) |
| `engine/scripts/corpus_check.py` (new, dev-only) | Transplant every local chain and validate |
| docs, skills, README, manifests | Updated per spec |

---

### Task 0: Install fixes (Intel lock, uv hint)

**Files:**
- Modify: `engine/pyproject.toml`
- Modify: `engine/uv.lock` (regenerated)
- Modify: `engine/bin/ableton`

- [ ] **Step 1: Add the marker-scoped constraints to `engine/pyproject.toml`.**

  ```toml
  [tool.uv]
  constraint-dependencies = [
      "numba<0.63; sys_platform == 'darwin' and platform_machine == 'x86_64'",
      "llvmlite<0.46; sys_platform == 'darwin' and platform_machine == 'x86_64'",
  ]
  ```

- [ ] **Step 2: Regenerate the lock.** Run `uv lock` in `engine/`. Expected: `uv.lock` holds
  two numba entries, with resolution markers for darwin/x86_64 and for everything else.
- [ ] **Step 3: Add the uv check to the shim.** At the top of `engine/bin/ableton`:

  ```bash
  command -v uv >/dev/null 2>&1 || { echo "ableton-tools needs uv: https://docs.astral.sh/uv/" >&2; exit 127; }
  ```

- [ ] **Step 4: Check the shim works.** Run `bin/ableton manifest --json` from the repo root.
  Expected: it succeeds on this Intel Mac with no workaround. Then run
  `uv run --project engine --group dev pytest -q`. Expected: the existing suite passes.
- [ ] **Step 5: Commit** (`build: install on Intel macOS; clear uv-missing message`).

### Task 1: Live 12 fixtures

**Files:**
- Create: `engine/tests/fixtures/live12_set.xml`
- Create: `engine/tests/fixtures/chain_src.xml`
- Create: `engine/tests/fixtures/README.md`
- Modify: `engine/tests/conftest.py`

**Produces:**
- conftest fixture `live12_project(tmp_path) -> Path`: writes `p/proj/Set.als` (gzipped
  `live12_set.xml`) plus `p/proj/Samples/master.wav` (2 s, 48 kHz) and returns the `.als` path.
- conftest fixture `chain_src_als(tmp_path) -> Path`.

- [ ] **Step 1: Build `live12_set.xml`** from a real Live 12.4 seed set
  with a sanitizer script run once. The sanitizer:
  - maps user paths to `/Users/test/...`;
  - sets the sample ref to `Samples/master.wav` (RelativePathType 3);
  - keeps the warp markers at indices 0, 1, 2 and the last;
  - keeps the `MainTrack` Tempo with its `LomId`, one AudioTrack (session clip + arrangement clip
    with `ScaleInformation`), the two returns with their type 1/5/7 device refs, the 8 scenes and
    `NextPointeeId`.

  The script lives at `engine/scripts/sanitize_fixture.py` so the fixture is reproducible.
- [ ] **Step 2: Build `chain_src.xml`.** Source it from the corpus: a Live 12 set whose track
  holds an `AudioEffectGroupDevice` containing a `Compressor2` with a sidechain
  `AudioIn/Track.N/PostFxOut`, plus one `PluginDevice` (VST3) with its blob replaced by a
  short stub buffer.
  - Add a type-3 `FileRef` and one track-level `AutomationEnvelope` whose `PointeeId` targets a
    chain `AutomationTarget`.
  - Sanitize names and paths.
  - The donor tracks must keep their real `Id`s so `Track.N` resolves inside the fixture.
- [ ] **Step 3: Write the conftest factories.**
- [ ] **Step 4: Sanity test.** Add `test_fixtures_load` in `tests/test_fixtures.py`: both
  fixtures parse with `xml.etree` and contain the elements listed in Steps 1–2.
- [ ] **Step 5: Run the test, then commit.**

### Task 2: `alsxml` core

**Files:**
- Create: `engine/src/ableton_tools/alsxml.py`
- Test: `engine/tests/test_alsxml.py`

**Produces:**

```python
class Node:            # immutable view
    tag: str; attrs: dict[str, str]; start: int; end: int
    parent: "Node | None"; depth: int; index: int
    def children(self) -> list["Node"]
    def child(self, tag: str) -> "Node | None"           # direct child
    def path(self, p: str) -> "Node | None"              # "A/B/C", direct children only
    def find_all(self, tag: str) -> list["Node"]         # descendants
    def value(self) -> str | None                        # attrs.get("Value")
    def ancestors(self) -> list["Node"]
    def text(self, doc: "Doc") -> bytes                  # raw span bytes

class Doc:
    def __init__(self, data: bytes | str)
    @classmethod
    def read(cls, path) -> "Doc"                         # gunzip
    data: bytes
    root: Node
    def nodes(self, tag: str | None = None) -> list[Node]
    def tracks(self) -> list[Node]                       # Audio/Midi/Group/Return, doc order
    def main_track(self) -> Node                         # MainTrack | MasterTrack; UsageError if absent
    def track_by_id(self, tid: str | int) -> Node
    def find_track(self, name: str) -> Node              # exact, then prefix-stripped "<n>-", then startswith; tie -> UsageError
    def track_name(self, t: Node) -> str
    def arrangement_clips(self, t: Node) -> list[Node]   # AudioClip/MidiClip under MainSequencer/../ArrangerAutomation
    def session_clips(self, t: Node) -> list[Node]       # under MainSequencer/ClipSlotList
    def effects_devices(self, t: Node) -> Node           # t/DeviceChain/DeviceChain/Devices
    # edits (queued; applied by apply())
    def set_value(self, n: Node, value) -> None
    def set_attr(self, n: Node, name: str, value) -> None
    def replace(self, n: Node, data: bytes | str) -> None
    def insert_before(self, n: Node, data: bytes | str) -> None
    def insert_after(self, n: Node, data: bytes | str) -> None
    def remove(self, n: Node) -> None
    def apply(self) -> "Doc"                             # returns new Doc; overlapping edits -> ValueError
    def to_str(self) -> str; def write(self, path) -> None
    def max_id(self) -> int                              # max Id="N"
    def id_base(self) -> int                             # ((max_id // 10000) + 1) * 10000
def offset_ids(fragment: bytes, offset: int) -> bytes    # only ' Id="N"' attributes
def set_next_pointee(doc: Doc) -> Doc                    # NextPointeeId = max_id + 1, returns applied doc
```

**Span algorithm.**
- Use `ParserCreate()` and set `parser.buffer_text`.
- Record `CurrentByteIndex` in every handler: Start, End, CharacterData, Default, Comment and
  ProcessingInstruction.
- Element start = the index at its StartElement event.
- Element end:
  - if the bytes at the EndElement index start with `</`, the end is the index of the next `>`
    plus 1;
  - otherwise it is an empty element: the end is the first index of `>` scanning forward from
    start, while skipping quoted attribute values.

  Build `_tag_end(data, start)` as a quote-aware scanner.

- [ ] **Step 1: Failing tests.**
  - Exact spans for `<A><B Value="é🦄" /><C>\n<D x="1"/></C></A>`: each span's bytes equal the
    expected element text, including D.
  - `>` inside an attribute value: `<A v="a>b"/>`.
  - `path` ignores grandchildren: a `ScaleInformation/Name` is not returned by
    `clip.child("Name")` when it isn't first.
  - Overlapping edits raise `ValueError`.
  - A no-op `Doc(x).apply().data == x` on `live12_set.xml`.
  - A local-only round-trip on the real seed set (`pytest.skip` if absent).
  - `set_value` on `<Manual Value="120" />` changes only those bytes.
  - `offset_ids` leaves `ParameterId Value="5"` and `LomId Value="0"` alone.
  - `find_track`:
    - exact name;
    - `"WORD"` resolves `"4-WORD"`;
    - `test_find_track_prefers_exact`: `"Bass"` with tracks `"1-Bass"` and `"2-Bass FX"` returns
      `"1-Bass"`;
    - a tie raises `UsageError`.
  - `test_freeze_sequencer_clips_ignored`.
  - `main_track` returns `MainTrack` on the Live 12 fixture and `MasterTrack` on the existing
    `MINIMAL_ALS`.
- [ ] **Step 2: Run the tests.** Expected: FAIL with an import error.
- [ ] **Step 3: Implement `alsxml.py`** per the interface above.
- [ ] **Step 4: Run the tests until they pass.**
- [ ] **Step 5: Commit** (`feat: alsxml lossless span-indexed .als editing`).

### Task 3: `validate` + typed refs

**Files:**
- Create: `engine/src/ableton_tools/validate.py`
- Test: `engine/tests/test_validate.py`

**Produces:**

```python
INT_TAGS = ("Root","CurrentStart","CurrentEnd","Color","TrackGroupId","LoopStart","LoopEnd",
            "HiddenLoopStart","HiddenLoopEnd","StartRelative")
def validate(doc: Doc) -> dict   # {"ok": bool, "errors": [str], "warnings": [str]}
def ref_report(doc: Doc, base_dir) -> dict
# {"missing_project": [rel], "missing_external": [abs], "library": n, "builtin": n}
```

**Checks.**
- Track ids (`Audio/Midi/Group/ReturnTrack Id`) are unique.
- `AutomationTarget` and `ModulationTarget` ids are unique.
- `NextPointeeId` > `max_id`, when `NextPointeeId` is present.
- Each `INT_TAGS` node's `Value` parses as a float. The clip `Time` attribute is numeric.
- Every non-`-1` `TrackGroupId` matches a `GroupTrack Id`.
- **Warning:** a grouped track whose output `Target` isn't `AudioOut/GroupTrack`.

**`ref_report`.**
- Read each `FileRef`'s `RelativePathType`, `RelativePath` and `Path`.
- Type 3 → resolve against `base_dir`.
- Type 1 → check that `Path` exists.
- Type 5 → library count; type 7 → built-in count.
- Type 0 / empty → skip.

- [ ] **Step 1: Failing tests.**
  - The fixture validates ok.
  - A duplicate track id fails.
  - A ScaleInformation `Name` set to `"x"` fails the int check, since `Name` under
    `ScaleInformation` is checked as an int.
  - A `TrackGroupId` pointing at a missing group fails.
  - A low `NextPointeeId` fails.
  - `ref_report` on the fixture: the type-1 Reverb preset lands in `missing_external`, not in
    `missing_project`.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 4: Commit pipeline

**Files:**
- Create: `engine/src/ableton_tools/commit.py`
- Modify: `engine/src/ableton_tools/cli.py` (`_als_commit` → `commit.run`; add `--force` to `_COMMIT`)
- Modify: `engine/src/ableton_tools/als.py` (`verify_refs` becomes a wrapper)
- Test: `engine/tests/test_commit.py`

**Produces:**

```python
class Snapshot: path: Path; sha256: str; mtime: float
def snapshot(path) -> Snapshot
def live_running() -> bool   # macOS: pgrep -x Live; Windows: tasklist; else False
def run(path, snap: Snapshot, new_xml: str, diff: dict, op: str, *, commit: bool, force: bool) -> dict
```

**Behaviour of `run`.**
- **Dry-run:** returns `{dry_run: True, op, diff, validation, note}`.
- **Commit:**
  1. Live is running and `not force` → `UsageError("Ableton Live is running…", kind=live_running)`.
  2. The file's sha256 differs from the snapshot → `UsageError(kind=file_changed)`.
  3. Validation fails → `UsageError(kind=validation_failed)`.
  4. Back up the file.
  5. Write.
  6. Run the ref report. Any missing type-3 ref → restore and return
     `{committed: False, kind: refs_restored, …}`.
  7. Otherwise return `{committed: True, backup, op, diff, warnings}`.

Extend `UsageError` with an optional `kind` and emit it in the error payload.

- [ ] **Step 1: Failing tests.**
  - A type-1 ref (the fixture's Reverb preset) no longer causes a restore.
  - A file modified after the snapshot is refused with `file_changed`.
  - `monkeypatch commit.live_running = lambda: True` → refused; `force=True` → succeeds.
  - A validation failure writes nothing.
  - `test_commit_twice_same_second`.
  - The existing CLI commit tests still pass.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Wire `cli._als_commit` to `commit.run` with
  `snap = commit.snapshot(args.als)` taken before reading.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 5: `als.py` on `alsxml` + Live 12 bug fixes + `inspect` + `validate` command

**Files:**
- Modify: `engine/src/ableton_tools/als.py`
- Modify: `engine/src/ableton_tools/import_stems.py` (naming via `child("Name")`; drop `_patch_attr*`)
- Modify: `engine/src/ableton_tools/cli.py` (`als validate`; `move-clip --dur-s` optional;
  `import-stems --master-track` via `find_track`; `--keep-session`)
- Test: `engine/tests/test_als.py`, `engine/tests/test_import_stems.py`, `engine/tests/test_cli.py`

**Functions** (signatures unchanged unless noted):

| Function | Change |
|---|---|
| `inspect_xml(xml)` | Adds the spec's fields. |
| `set_tempo(xml, bpm)` | Uses `main_track().path("DeviceChain/Mixer/Tempo/Manual")`. |
| `get_tempo(xml) -> float \| None` | New. |
| `move_clip_to_beat(xml, clip, beat, dur_s=None, bpm=None)` | Preserves length when `dur_s` is None. |
| `warp_to_grid` | Edits by node. |
| `clone_track(xml, src_id, new_name, new_id, id_offset=None)` | Uses `alsxml` + `offset_ids`. |
| `rename_refs` | Edits `RelativePath` / `Path` nodes. |
| `verify_refs(xml, base)` | Returns `ref_report(...)["missing_project"]`. |

`import_stems.import_stems(..., keep_session: bool = False)` empties the clones' Session slots
unless `keep_session` is set or the master has no arrangement clip.

- [ ] **Step 1: Failing regression tests** on the Live 12 fixture, one per bug:
  - `inspect` tempo == fixture tempo;
  - `set_tempo` round-trips;
  - `warp_to_grid` on the fixture sets IsWarped true (the existing `" />` form);
  - `move_clip_to_beat` without `dur_s` preserves `CurrentEnd - CurrentStart`;
  - `import_stems` leaves `ScaleInformation/Name` untouched and the output validates;
  - the `--master-track "Master"` style name resolves after a `"1-"` prefix;
  - clones have empty session slots;
  - `als validate` CLI returns `ok: true` on the fixture;
  - `inspect` reports `warp_map_bpm` and `location`.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Update only the existing tests that asserted Live 11-only
  quirks.
- [ ] **Step 5: Commit** (`fix: Live 12 correctness …`).

### Task 6: Session commands + `import-stems` extensions

**Files:**
- Create: `engine/src/ableton_tools/session.py`
- Create: `engine/src/ableton_tools/templates/group_track.xml`
- Modify: `engine/src/ableton_tools/import_stems.py`
- Modify: `engine/src/ableton_tools/cli.py`
- Test: `engine/tests/test_session.py`, `engine/tests/test_import_stems.py`

**Produces:**

```python
def set_tempo_cmd(xml, bpm) -> tuple[str, dict]
def mute(xml, tracks: list[str], unmute=False) -> tuple[str, dict]
def add_track(xml, name: str, color: int | None = None, after: str | None = None) -> tuple[str, dict]
def group(xml, name: str, tracks: list[str], color: int | None = None) -> tuple[str, dict]
def sync_to_master(xml, master: str, tracks: list[str] | None, all_warped=False,
                   markers=False) -> tuple[str, dict]
# import_stems(..., tolerance_ms=None, to="arrangement"|"session", unwarped=False,
#              mute_below=None, skip_below=None, keep_session=False)
```

**Template.** `group_track.xml` is sanitized from a clean group from a real Live 12.4 set:
- name `"Group"`, color 0;
- empty Devices;
- Id-bearing nodes left as-is (offset at use).

**Group adaptation.**
- Regenerate the `<Sends>` children by cloning the first `TrackSendHolder` once per
  `ReturnTrack`, with `Id` values 0..n-1.
- Regenerate `<Slots>` with one `GroupTrackSlot` per `Scene`.
- When there are 0 returns, emit `<Sends />`.

**Relaxed check (`check_timeline`).**
- `|frames/sr - master_dur| ≤ tol`.
- `find_lag` on the first 30 s, computed on mono at 48 kHz.
- Compute r. Reject when `r > 0.3` and `|lag| > 1 ms`; otherwise warn.

**Session/unwarped placement.**
- Remove the arrangement clip.
- On the session clip: `IsWarped=false`; `Loop*`, `HiddenLoop*` = duration in seconds;
  `CurrentStart=0`; `CurrentEnd = dur*bpm/60`.
- Replace `WarpMarkers` with the two default markers.

- [ ] **Step 1: Failing tests**, one per command and flag:
  - `test_group_adapts_sends_and_slots` (3 returns, 12 scenes);
  - grouping routes members (`Target`/`Upper`);
  - non-contiguous members raise;
  - `sync_to_master` sets `Time` + bounds on targets and reports a marker mismatch;
  - `mute` flips `Speaker`;
  - `add_track` has no clips;
  - tolerance accepts a stem padded by 1152 frames and a 44.1 kHz copy, and rejects a 200 ms
    offset copy;
  - `--to session --unwarped` puts `LoopEnd` in seconds;
  - `--skip-below` drops a silent stem;
  - every output passes `validate`.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 7: `transplant-devices`

**Files:**
- Create: `engine/src/ableton_tools/devices.py`
- Create: `engine/scripts/corpus_check.py`
- Modify: `engine/src/ableton_tools/cli.py`
- Test: `engine/tests/test_devices.py`

**Produces:**

```python
def transplant(target_xml: str, source_xml: str, *, src_track: str | None, src_main: bool,
               to_track: str | None, to_main: bool, mode: str = "replace",
               with_automation=False, map_track: dict[str, str] | None = None,
               target_dir=None, source_dir=None) -> tuple[str, dict]
# diff: {devices:[tag], plugins:[{name,format,found}], routing_reset:[...], routing_mapped:[...],
#        automation_dropped:int, automation_copied:int, files_copied:[...], warnings:[...]}
```

`files_copied` is a plan for the CLI. The CLI copies the files only on `--commit`.

**Algorithm:** as in spec §3.

**Routing regex,** applied inside the chain bytes only:
`(Value=")(AudioIn|AudioOut|MidiIn|MidiOut)/Track\.(\d+)/[^"]*(")` → `\2/None`.
- The sibling `UpperDisplayString` becomes `"No Output"` / `"No Input"`, and
  `LowerDisplayString` becomes `""`.

- [ ] **Step 1: Failing tests** on `chain_src.xml` → Live 12 fixture:
  - the rack is preserved byte-identical apart from `Id`s;
  - all ids land above the target's max and are unique; `validate` is ok;
  - `Track.N` is reset, and with `--map-track` it's remapped to the destination track's `Id`;
  - `ParameterId` is untouched;
  - automation is dropped by default and copied with `--with-automation`, with remapped
    `PointeeId`s that resolve;
  - the type-3 ref is copied and repointed;
  - `--to-main` works;
  - `test_transplant_append_nonempty`.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.** Also write `corpus_check.py`: for each local Live 11/12 set and each
  non-empty chain, transplant into the fixture, run `validate`, and assert no `Track.\d+`
  remains. Print a pass/fail tally.
- [ ] **Step 4: Run the tests, then the corpus check.** Expected: 100% pass.
- [ ] **Step 5: Commit.**

### Task 8: Analysis helpers

**Files:**
- Create: `engine/src/ableton_tools/analysis.py`
- Modify: `engine/src/ableton_tools/cli.py`
- Test: `engine/tests/test_analysis.py`

**Produces:**

```python
def levels(folder, pattern="*.wav", ref=None) -> dict
def locate(fragment, ref, env_hz=100.0, top=3) -> dict   # {matches:[{offset_s, r}], band}
def warp_check(als_path, track=None, audio=None) -> dict
```

**Algorithm:** the session's `locate.py` / `verify_warp.py`, ported onto `alsxml` + `audio`.

- [ ] **Step 1: Failing tests.**
  - `locate` finds a 3 s noise fragment at 7.25 s within 10 ms with `r > 0.95`.
  - `levels` flags a zero file as silent, and a duplicate shows `r ≈ 1`.
  - `warp_check` on a click-track fixture `.als` reports the warp-map BPM and identical
    markers across clones.
- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 9: Docs, skills, versions, release

**Files:**
- `engine/references/als-format.md`
- `engine/CLAUDE.md`
- `skills/*/SKILL.md`, plus new `skills/als-build/SKILL.md`
- `README.md`
- `.claude-plugin/plugin.json`
- `engine/pyproject.toml`

- [ ] **Step 1: Write the docs and skills** per the spec's "Docs, skills, release" section.
- [ ] **Step 2: Bump versions** to 1.1.0 / 0.3.0, then run `uv lock`.
- [ ] **Step 3: Verify.** Run:
  - `uv run --project engine --group dev pytest`
  - `uvx ruff check engine`
  - `uvx pyright --project engine engine/src`
  - `claude plugin validate .`
- [ ] **Step 4: End-to-end check** on copies of the real set:
  - rebuild the session with commands only;
  - `validate`;
  - `--commit` succeeds.
- [ ] **Step 5: Commit, merge to main, tag `v1.1.0`.** Pause for the owner's OK before
  `git push --follow-tags` and `gh release create`.
