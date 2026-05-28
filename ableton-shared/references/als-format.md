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
