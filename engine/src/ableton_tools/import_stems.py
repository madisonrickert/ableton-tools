"""Import a folder of stems (e.g. Suno's) into a .als as clones of an
already-warped master track. Owns the stem-import policy: label derivation,
the default track-color convention, SampleRef repointing, tempo-leader
demotion. The generic XML primitives live in als.py.

Invariant: every stem must match the master's frame count and sample rate;
the clones inherit the master's warp markers verbatim, which is only correct
when the audio timelines are identical. check_stem_invariants() gates this.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import als
from .errors import UsageError

# Default per-stem track-color convention (Ableton Live 11 color indices),
# drawn from real cover and live-set projects. Override via --colors. Keys are
# lowercase; lookup is exact match first, then substring, then DEFAULT_COLOR.
STEM_COLORS = {
    "lead vocals": 20,
    "backing vocals": 7,
    "drums": 3,
    "bass": 17,
    "synth": 14,
    "keys": 14,
    "other": 23,
    "fx": 23,
}
DEFAULT_COLOR = 23  # Other / FX


def _bare_label(filename_stem: str) -> str:
    """'0 Lead Vocals' -> 'Lead Vocals'. Live rewrites EffectiveName as
    '<track-index>-<first-clip-Name>' on load, so a numeric filename prefix
    left in the clip Name would produce '2-0 Lead Vocals'."""
    label = re.sub(r"^\d+\s*[-_.]?\s*", "", filename_stem).strip()
    return label or filename_stem


_LEADING_INT_RE = re.compile(r"^(\d+)")


def _natural_stem_key(p: Path) -> tuple[int, int, str]:
    """Sort key for stem filenames: a leading integer prefix (e.g. '10' in
    '10 C.wav') sorts numerically, not lexicographically, so a folder with
    >=10 stems ('10 C.wav' vs '2 B.wav') keeps arrangement/EffectiveName
    order sane. Filenames without a numeric prefix fall back to sorting by
    name, after every prefixed file, keeping the order stable and total."""
    m = _LEADING_INT_RE.match(p.stem)
    if m:
        return (0, int(m.group(1)), p.stem)
    return (1, 0, p.stem)


def _color_for(label: str, colors: dict[str, int] | None = None) -> int:
    table = dict(STEM_COLORS)
    if colors:
        table.update({k.lower(): v for k, v in colors.items()})
    key = label.lower()
    if key in table:
        return table[key]
    for k, v in table.items():
        if k in key:
            return v
    return DEFAULT_COLOR


def _patch_attr(block: str, tag: str, value: str | int, required: bool = True) -> str:
    """Set every `<tag Value="...">` inside block to `value`."""
    out, n = re.subn(
        rf'(<{tag} Value=")[^"]*(")',
        lambda m: m.group(1) + str(value) + m.group(2),
        block,
    )
    if required and n == 0:
        raise UsageError(
            f"Cloned track block has no <{tag}> element to patch",
            hint="the master track layout is unexpected; inspect the .als",
        )
    return out


_AUDIO_CLIP_RE = re.compile(r"<AudioClip\b.*?</AudioClip>", re.DOTALL)


def _patch_attr_in_clips(block: str, tag: str, value: str | int, required: bool = True) -> str:
    """Set every `<tag Value="...">` inside each <AudioClip>...</AudioClip>
    sub-block of `block`, leaving any same-named tag elsewhere in the block
    (e.g. a device/plugin descriptor's bare <Name Value="..."> living in the
    track's DeviceChain, outside any clip) untouched. Mirrors how
    `als._clip_block` scopes edits to a single named clip, but here patches
    every clip sub-block found (session + arrangement clips of the clone)."""
    parts: list[str] = []
    last = 0
    n = 0
    for m in _AUDIO_CLIP_RE.finditer(block):
        parts.append(block[last : m.start()])
        clip, count = re.subn(
            rf'(<{tag} Value=")[^"]*(")',
            lambda mm: mm.group(1) + str(value) + mm.group(2),
            m.group(0),
        )
        n += count
        parts.append(clip)
        last = m.end()
    parts.append(block[last:])
    out = "".join(parts)
    if required and n == 0:
        raise UsageError(
            f"Cloned track block has no <AudioClip> with a <{tag}> element to patch",
            hint="the master track layout is unexpected; inspect the .als",
        )
    return out


def master_audio_path(
    xml: str, master_track_id: str | int, project_dir: str | Path
) -> Path:
    """Resolve the master track's clip RelativePath against project_dir."""
    s, e, _ = als._find_track_block(xml, master_track_id)
    m = re.search(r'<RelativePath Value="([^"]+)"', xml[s:e])
    if not m:
        raise UsageError(
            f"Track {master_track_id} has no sample RelativePath",
            hint="pick the audio track that holds the warped master clip",
        )
    return Path(project_dir) / m.group(1)


def check_stem_invariants(
    master_audio: str | Path, stem_paths: list[Path]
) -> list[dict[str, Any]]:
    """Every stem must match the master's frames and samplerate. Returns a
    list of problem dicts; empty means safe to import."""
    import soundfile as sf

    ref = sf.info(str(master_audio))
    problems: list[dict[str, Any]] = []
    for p in stem_paths:
        i = sf.info(str(p))
        if i.frames != ref.frames or i.samplerate != ref.samplerate:
            problems.append(
                {
                    "file": str(p),
                    "frames": i.frames,
                    "samplerate": i.samplerate,
                    "expected_frames": ref.frames,
                    "expected_samplerate": ref.samplerate,
                }
            )
    return problems


def import_stems(
    xml: str,
    master_track_id: str | int,
    stem_files: list[Path] | list[str],
    project_dir: str | Path,
    colors: dict[str, int] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Clone the master track once per stem file (sorted naturally by
    filename: numeric prefixes ordered as integers, so '10 C.wav' sorts
    after '2 B.wav' rather than before it),
    repoint each clone's SampleRef, set bare-label clip names, demote the
    tempo lead, and apply the color convention. Returns (new_xml, diff).

    Pure XML transform: no disk writes. The CLI layer owns dry-run/commit."""
    project_dir = Path(project_dir)
    sorted_stem_files = sorted((Path(p) for p in stem_files), key=_natural_stem_key)

    all_ids = [int(x) for x in re.findall(r'Id="(\d+)"', xml)]
    base = ((max(all_ids) // 10000) + 1) * 10000 if all_ids else 10000

    stems_meta: list[dict[str, Any]] = []
    out = xml
    # clone_track inserts each clone immediately after the SOURCE block, so
    # iterate in reverse filename order to end with filename order in the doc.
    for i, stem in reversed(list(enumerate(sorted_stem_files))):
        label = _bare_label(stem.stem)
        color = _color_for(label, colors)
        offset = base * (i + 1)
        new_id = int(master_track_id) + offset
        effective_name = f"{i + 2}-{label}"  # master is track 1
        out = als.clone_track(out, master_track_id, effective_name, new_id, id_offset=offset)
        s, e, _ = als._find_track_block(out, str(new_id))
        block = out[s:e]

        try:
            rel = stem.resolve().relative_to(project_dir.resolve())
        except ValueError as err:
            raise UsageError(
                f"Stem {stem} is outside the project directory {project_dir}",
                hint="move or copy the stems into the Ableton project folder first",
            ) from err
        block = _patch_attr(block, "RelativePath", str(rel))
        block = _patch_attr(block, "Path", str(stem.resolve()))
        block = _patch_attr(block, "OriginalFileSize", stem.stat().st_size, required=False)
        block = _patch_attr(block, "OriginalCrc", 0, required=False)
        block = _patch_attr(block, "IsSongTempoLeader", "false", required=False)
        # Scoped to AudioClip sub-blocks only: a device-bearing master track
        # can have a plugin/device descriptor's own bare <Name Value="...">
        # in the DeviceChain, outside any clip, which must not be clobbered.
        block = _patch_attr_in_clips(block, "Name", label)  # session + arrangement clips
        block = _patch_attr(block, "MemorizedFirstClipName", label, required=False)
        block = _patch_attr(block, "Color", color, required=False)

        out = out[:s] + block + out[e:]
        stems_meta.append(
            {
                "file": str(stem),
                "label": label,
                "effective_name": effective_name,
                "color": color,
                "relative_path": str(rel),
            }
        )

    stems_meta.reverse()  # report in filename order
    return out, {"master_track_id": str(master_track_id), "stems": stems_meta}
