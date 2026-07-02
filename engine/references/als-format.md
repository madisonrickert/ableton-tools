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

## Two-marker warp strategy

Ableton's auto-warp scatters many markers per clip, which lets stems drift
relative to each other. Locking each clip to exactly two markers — `(SecTime 0,
BeatTime 0)` and `(SecTime file_duration, BeatTime duration*bpm/60)` — at a
single fixed project tempo keeps every clip on the same linear time→beat map, so
inter-clip phase coherence is preserved. This is what `als warp-to-grid` does.

## Beats vs seconds

Clip bounds are in beats. To place a clip of `dur_s` seconds at beat `b` under
tempo `bpm`: `CurrentStart = b`, `CurrentEnd = b + dur_s*bpm/60`.

## Caveat

Regex patchers assume the formatting Ableton Live 11 emits. Before trusting an
edit on a new project, run `als inspect` and eyeball a dry-run `diff`. Always
back up (the toolkit does this automatically on `--commit`) and close Ableton
first.

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

### Madison's track-color convention (apply to track + both clip `<Color>` tags)
Source: her Jaron Smith Castratikron-cover project and 2021-06 Sonic Sundays
live set.

| Stem            | Color | Source                                 |
| --------------- | ----: | -------------------------------------- |
| Lead Vocals     | 20    | Jaron: Lead Vox group                  |
| Backing Vocals  | 7     | Jaron: Backup Vox group + 6 sub-tracks |
| Drums           | 3     | Jaron: Drums group + MIDI              |
| Bass            | 17    | Jaron: Bass                            |
| Synth / Keys    | 14    | Sonic Sundays: SYNTH                   |
| Other / FX      | 23    | Jaron: Choir/Strings (miscellaneous)   |

Apply by replacing every `<Color Value="N" />` inside each cloned track block
(track-level + the two clip-level Colors). Madison's master has uniform
Color on the track and both clips, so a global replace within the clone is
the right pattern.

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
