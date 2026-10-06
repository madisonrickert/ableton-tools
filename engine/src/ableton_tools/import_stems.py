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
from .alsxml import Doc, Node
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


def _sample_rel(clip: Node) -> str | None:
    rel = clip.path("SampleRef/FileRef/RelativePath")
    return rel.value() if rel is not None else None


def master_audio_path(
    xml: str, master_track_id: str | int, project_dir: str | Path
) -> Path:
    """Resolve the master track's clip RelativePath against project_dir
    (its Arrangement clip, else its Session clip)."""
    doc = Doc(xml)
    t = doc.track_by_id(master_track_id)
    for clip in doc.arrangement_clips(t) + doc.session_clips(t) + t.find_all("AudioClip"):
        rel = _sample_rel(clip)
        if rel:
            return Path(project_dir) / rel
    raise UsageError(
        f"Track {master_track_id} has no sample RelativePath",
        hint="pick the audio track that holds the warped master clip",
    )


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


def _retarget_clone(
    doc: Doc, track: Node, stem: Path, rel: Path, label: str, color: int, drop_session: bool
) -> None:
    """Queue the edits that turn a cloned master track into the stem's track."""
    clips = doc.arrangement_clips(track)
    if not drop_session:
        clips = clips + doc.session_clips(track)
    for clip in clips:
        sample = clip.child("SampleRef")
        for ref in sample.find_all("FileRef") if sample is not None else []:
            for tag, val in (("RelativePath", str(rel)), ("Path", str(stem.resolve())),
                             ("OriginalFileSize", stem.stat().st_size), ("OriginalCrc", 0)):
                node = ref.child(tag)
                if node is not None:
                    doc.set_value(node, val)
        name = clip.child("Name")  # the clip's own name: never ScaleInformation/Name
        if name is not None:
            doc.set_value(name, label)
        cc = clip.child("Color")
        if cc is not None:
            doc.set_value(cc, color)
    dropped = {c.start for c in doc.session_clips(track)} if drop_session else set()
    for leader in track.find_all("IsSongTempoLeader"):
        if not any(a.start in dropped for a in leader.ancestors()):
            doc.set_value(leader, "false")
    memo = track.path("Name/MemorizedFirstClipName")
    if memo is not None:
        doc.set_value(memo, label)
    tc = track.child("Color")
    if tc is not None:
        doc.set_value(tc, color)
    if drop_session:
        for clip in doc.session_clips(track):
            if clip.parent is not None and clip.parent.tag == "Value":
                doc.replace(clip.parent, "<Value />")


def import_stems(
    xml: str,
    master_track_id: str | int,
    stem_files: list[Path] | list[str],
    project_dir: str | Path,
    colors: dict[str, int] | None = None,
    keep_session: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Clone the master track once per stem file (sorted naturally by
    filename: numeric prefixes ordered as integers, so '10 C.wav' sorts
    after '2 B.wav' rather than before it), repoint each clone's SampleRef,
    set bare-label clip names, demote the tempo lead, and apply the color
    convention. When the master has an Arrangement clip, each clone's Session
    copy of it is dropped (keep_session=True keeps it). Returns (new_xml, diff).

    Pure XML transform: no disk writes. The CLI layer owns dry-run/commit."""
    project_dir = Path(project_dir)
    sorted_stem_files = sorted((Path(p) for p in stem_files), key=_natural_stem_key)
    doc0 = Doc(xml)
    master = doc0.track_by_id(master_track_id)
    drop_session = bool(doc0.arrangement_clips(master)) and not keep_session
    base = doc0.id_base()

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
        try:
            rel = stem.resolve().relative_to(project_dir.resolve())
        except ValueError as err:
            raise UsageError(
                f"Stem {stem} is outside the project directory {project_dir}",
                hint="move or copy the stems into the Ableton project folder first",
            ) from err
        out = als.clone_track(out, master_track_id, effective_name, new_id, id_offset=offset)
        doc = Doc(out)
        _retarget_clone(doc, doc.track_by_id(new_id), stem, rel, label, color, drop_session)
        out = doc.apply().to_str()
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
