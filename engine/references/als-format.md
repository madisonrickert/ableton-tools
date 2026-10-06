# Ableton `.als` format notes

A `.als` file is gzip-compressed XML. `gzip -dc file.als` (or `als.read_als`)
yields the XML. Re-gzip to save (`als.write_als`). Live reads any gzip level.

## Elements this toolkit touches

- **Tempo:** `MasterTrack > ... > Tempo > Manual[Value]` — the project BPM.
- **Tracks:** `*Track[Id] > Name > EffectiveName[Value]` — track display name.
- **Audio clips:** `AudioClip` blocks contain:
  - `Name[Value]` — clip name.
  - `CurrentStart[Value]` / `CurrentEnd[Value]` — clip bounds in **beats**.
  - `SampleRef > FileRef > RelativePath[Value]` and `Path[Value]` — the audio
    file reference (relative to the project, and absolute).
  - `WarpMarkers > WarpMarker[SecTime, BeatTime]` — map file seconds to beats.
  - `IsWarped[Value]` — whether the clip follows the project tempo.

## Two-marker warp strategy (experimental)

The idea behind `als warp-to-grid`: give each clip exactly two markers,
`(SecTime 0, BeatTime 0)` and `(SecTime file_duration, BeatTime duration*bpm/60)`,
at a single fixed project tempo, so every clip shares one linear time→beat map,
intended to preserve inter-clip phase coherence. This is a different approach
from Ableton's auto-warp (which places many markers per clip); it is
experimental and not verified to outperform auto-warp. The primary
stem-alignment path in this toolkit is instead `als import-stems`, which clones
a master's existing warp (including an Ableton auto-warp) onto each stem.

## Beats vs seconds

Clip bounds are in beats. To place a clip of `dur_s` seconds at beat `b` under
tempo `bpm`: `CurrentStart = b`, `CurrentEnd = b + dur_s*bpm/60`.

## Caveat

All edits go through `alsxml` (span index + byte splices), not regexes, and
every committed edit is structurally validated first (`ableton als validate`).
Still: back up (the toolkit does this automatically on `--commit`), close
Ableton first, and eyeball a dry-run diff on an unfamiliar project.

## Stem import mechanics (import_stems.py)

`als import-stems` clones the master track per stem via the `clone_track`
primitive, then repoints each clone's `<SampleRef>`:
- `<RelativePath Value="...">` → stem's project-relative path
- `<Path Value="...">` → stem's absolute path
- `<OriginalFileSize Value="...">` → stem .wav file size in bytes
- `<OriginalCrc Value="...">` → `0` (Ableton recomputes on load; avoids a
  spurious "file changed" prompt)

### Gotcha: clip Name → EffectiveName auto-derivation
On load, Ableton **rewrites** a track's EffectiveName as
`<track-index>-<first-clip-Name>`. If the stem file is `0 Lead Vocals.wav`
and you set the clip Name to the filename stem `"0 Lead Vocals"`, the master
pattern + your intended EffectiveName `"2-Lead Vocals"` will be silently
overwritten to `"2-0 Lead Vocals"`. To preserve `"<N>-<Stem>"`, set the
clip's `<Name>` to the bare instrument label (`"Lead Vocals"`, not
`"0 Lead Vocals"`) — the clip's display name need not match the filename.

### Default track-color convention (apply to track + both clip `<Color>` tags)
A suggested per-stem color mapping, drawn from real cover and live-set
projects. Values are Ableton's Live 11 color-index integers. Override any of
them via `als import-stems --colors`.

| Stem            | Color |
| --------------- | ----: |
| Lead Vocals     | 20    |
| Backing Vocals  | 7     |
| Drums           | 3     |
| Bass            | 17    |
| Synth / Keys    | 14    |
| Other / FX      | 23    |

Applied to the cloned track's own `<Color>` and each kept clip's direct `<Color>` child.

### NextPointeeId
`clone_track` bumps internal IDs and `<NextPointeeId>` automatically. The
default (omit `id_offset`) auto-allocates a fresh, disjoint offset — rounded
up to the next 10000 — above the document's current max Id on every call, so
chained clones (`import_stems`'s per-stem loop) never collide. Do that unless
you have a specific reason not to.

If you do pass an explicit `id_offset`, small hand-picked values like `100`,
`200`, `300`... are **not** safe: `clone_track` raises if the offset Ids
collide with anything already in the document, and any real master track
spans more than 100 internal Ids (attributes, warp markers, device
parameters...), so an offset that small will collide and traceback. Pick
offsets larger than the document's actual Id span, and keep them distinct
per call — or just omit `id_offset` and let it auto-allocate.

## Live 12 notes (learned on real Live 12.4 sets)

How the engine edits: `alsxml` indexes every element's exact **byte** span with
one stdlib-expat pass (UTF-8/emoji paths are why it indexes bytes). Reads walk
**direct children only**, and writes are byte splices. Every untouched byte is
preserved, so a no-op round-trip is byte-identical. Never address `.als`
content with a free regex: the gotchas below were all regex casualties.

**Main track.** Live 12 calls it `<MainTrack …attrs>`; Live 11 called it
`<MasterTrack>`. Live 12 also puts a `<LomId/>` between `<Tempo>` and
`<Manual>`. The tempo is at `MainTrack/DeviceChain/Mixer/Tempo/Manual`.

**Clip names vs ScaleInformation.** Every Live 12 clip has
`<ScaleInformation><Root/><Name Value="0"/></ScaleInformation>`, an
int-valued node. Writing a string there makes Live refuse the set with
"Unexpected value for int node". Set a clip's name via its *direct child*
`Name` only.

**Clip position.** The Arrangement position is the `Time` attribute of the
`<AudioClip>` tag. It must track `CurrentStart`. If you change only
`CurrentStart`, Live reconciles the clip back to `Time` on its next save.

Clip locations inside a track:

| Kind | Path |
|---|---|
| Arrangement (Live 12) | `DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events` |
| Arrangement (Live 11) | `DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events` |
| Session | `DeviceChain/MainSequencer/ClipSlotList/ClipSlot/ClipSlot/Value` |

Clips under `FreezeSequencer` or `TakeLanes` are not editable clips. An empty
Session slot is `<Value />`.

**Unwarped clips.** `CurrentStart` and `CurrentEnd` are in **beats**, but
`Loop/LoopStart`, `LoopEnd`, `HiddenLoopStart` and `HiddenLoopEnd` are in
**seconds**. This is what Live writes, and Live rewrites it this way on load.

**`RelativePathType`** (in every `FileRef`):

| Type | Meaning | Check |
|---|---|---|
| 0 | empty | — |
| 1 | external / absolute | warn if `Path` is missing |
| 3 | project-relative | must resolve |
| 5 | Core Library | never failed |
| 6 | User Library | never failed |
| 7 | built-in device | never failed |

A `FileRef` with no type (legacy or minimal docs) is treated as type 3.
Live 12 clips also carry a second `FileRef` under
`SampleRef/SourceContext/…/OriginalFileRef`.

**Groups.** A `GroupTrack` precedes its members. Each member needs two things:

- `<TrackGroupId Value="<groupId>"/>`;
- **output routing to the group bus**: `<AudioOutputRouting>` with
  `<Target Value="AudioOut/GroupTrack"/>`,
  `<UpperDisplayString Value="Group"/>` and
  `<LowerDisplayString Value=""/>`.

Without that routing the tracks *look* grouped but bypass the group's devices.
The group itself routes to `AudioOut/Main`. Its `Mixer/Sends` holds one
`TrackSendHolder` per return track, and `Slots` holds one `GroupTrackSlot`
per scene.

**Ids.** Track ids and the ids of `*Target` elements
(AutomationTarget/ModulationTarget) are **pointees**: unique per document,
and they must stay below `NextPointeeId`. Many other `Id`s (ClipSlot,
WarpMarker, TrackSendHolder, GroupTrackSlot, …) are **local** and repeat on
every track; real Live files contain hundreds of such repeats.

Never offset `ParameterId`, `UniqueId` or `LomId`; they are not document ids.
Automation envelopes point at targets via
`<EnvelopeTarget><PointeeId Value="N"/>`. When a block is copied, remap the
pointers that aim inside it (`alsxml.offset_block`).

**Device chains.** The track-level chain is
`<track>/DeviceChain/DeviceChain/Devices` for every track type (Main/Master
too). Racks nest a `Devices` + `SignalModulations` pair per branch (37% of
chains in a 2,124-chain survey), so never locate a chain by "the first
`SignalModulations`".

Routing targets inside chains reference tracks **by Id**
(`AudioIn/Track.<Id>/DeviceOut.6.B0,ChainOut`). In the survey, 195 of 298
were *self* references (rack-internal routing). An unassigned route is
`AudioIn/None` with `UpperDisplayString` set to "No Output", or `MidiOut/None`
with "None".

**Names.** Live rewrites `EffectiveName` to `"<index>-<first clip name>"`
when a track has no `UserName`. Resolve tracks prefix-tolerantly
(`alsxml.Doc.find_track`).
