"""Import a folder of stems (e.g. Suno's) into a .als as clones of an
already-warped master track. Owns the stem-import policy: label derivation,
the default track-color convention, SampleRef repointing, tempo-leader
demotion. The generic XML primitives live in als.py.

Default invariant: every stem must match the master's frame count and sample
rate; the clones inherit the master's warp markers verbatim, which is only
correct when the audio timelines are identical. check_stem_invariants() gates
this. check_timeline() is the relaxed alternative (--tolerance-ms): lengths
within a tolerance, any sample rate, and a measured start lag against the
master (rejected only when the files are correlated enough to measure it).
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


def check_timeline(
    master_audio: str | Path, stem_paths: list[Path], tolerance_ms: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Relaxed same-timeline check. Returns (problems, per-stem reports)."""
    import numpy as np
    import soundfile as sf

    from . import align, audio

    sr = 48000
    master, _ = audio.load_mono(master_audio, target_sr=sr)
    head = master[: 30 * sr]
    master_dur = len(master) / sr
    reports: list[dict[str, Any]] = []
    for p in stem_paths:
        info = sf.info(str(p))
        delta_ms = abs(info.duration - master_dur) * 1000.0
        sig, _ = audio.load_mono(p, target_sr=sr)
        sig = sig[: 30 * sr]
        lag, _alpha, _resid = align.find_lag(head, sig, sr, search_s=1.0, refine=256)
        a, b = (head[lag:], sig) if lag >= 0 else (head, sig[-lag:])
        n = min(len(a), len(b))
        r = float(np.corrcoef(a[:n], b[:n])[0, 1]) if n > 1 else 0.0
        lag_ms = lag / sr * 1000.0
        correlated = r > 0.3
        ok = delta_ms <= tolerance_ms and not (correlated and abs(lag_ms) > 1.0)
        note = None if correlated else "not correlated with the master; verify by ear"
        reports.append({"file": str(p), "duration_s": round(info.duration, 4),
                        "sample_rate": info.samplerate, "delta_ms": round(delta_ms, 2),
                        "lag_ms": round(lag_ms, 3), "r": round(r, 4), "ok": ok, "note": note})
    return [r for r in reports if not r["ok"]], reports


def _dbfs(path: Path) -> float:
    from . import audio

    x, _ = audio.load_mono(path)
    return round(float(audio.to_db(audio.rms(x))), 2)  # plain float: JSON-safe


def _two_markers(dur_s: float, bpm: float) -> str:
    return ("<WarpMarkers>\n"
            '<WarpMarker Id="0" SecTime="0" BeatTime="0" />\n'
            f'<WarpMarker Id="1" SecTime="{dur_s:g}" BeatTime="{dur_s * bpm / 60:g}" />\n'
            "</WarpMarkers>")


def _place(doc: Doc, track: Node, to: str, unwarped: bool, dur_s: float, bpm: float) -> Doc:
    """Move the clone's clip into Session slot 0 (to='session') and/or make it
    unwarped. Unwarped clips keep CurrentStart/End in beats but Loop/HiddenLoop
    bounds in SECONDS, as Live itself writes them."""
    if to == "session":
        arr = doc.arrangement_clips(track)
        sess = doc.session_clips(track)
        if not sess:
            slot = track.path("DeviceChain/MainSequencer/ClipSlotList")
            value = None
            if slot is not None and slot.children():
                value = slot.children()[0].path("ClipSlot/Value")
            if value is None or not arr:
                raise UsageError("cannot place in Session: master has no clip slot / clip")
            doc.replace(value, b"<Value>" + arr[0].text(doc) + b"</Value>")
            for c in arr[1:]:
                doc.remove(c)
        else:
            for c in arr:
                doc.remove(c)
        doc = doc.apply()
        track = doc.track_by_id(track.attrs["Id"])
        for c in doc.session_clips(track):
            if "Time" in c.attrs:
                doc.set_attr(c, "Time", 0)
        doc = doc.apply()
        track = doc.track_by_id(track.attrs["Id"])
    if not unwarped:
        return doc
    clips = doc.session_clips(track) if to == "session" else doc.arrangement_clips(track)
    for c in clips:
        cs = c.child("CurrentStart")
        start = float(cs.value() or 0) if cs is not None else 0.0
        if to == "session":
            start = 0.0
        edits = {"IsWarped": "false", "CurrentStart": als._num(start),
                 "CurrentEnd": als._num(start + dur_s * bpm / 60.0),
                 "Loop/LoopStart": "0", "Loop/LoopEnd": als._num(dur_s),
                 "Loop/HiddenLoopStart": "0", "Loop/HiddenLoopEnd": als._num(dur_s),
                 "Loop/StartRelative": "0"}
        for path, val in edits.items():
            n = c.path(path)
            if n is not None:
                doc.set_value(n, val)
        wm = c.child("WarpMarkers")
        if wm is not None:
            doc.replace(wm, _two_markers(dur_s, bpm))
    return doc.apply()


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
    to: str = "arrangement",
    unwarped: bool = False,
    mute_below: float | None = None,
    skip_below: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """Clone the master track once per stem file (sorted naturally by
    filename: numeric prefixes ordered as integers, so '10 C.wav' sorts
    after '2 B.wav' rather than before it), repoint each clone's SampleRef,
    set bare-label clip names, demote the tempo lead, and apply the color
    convention. When the master has an Arrangement clip, each clone's Session
    copy of it is dropped (keep_session=True keeps it). to='session' places
    each stem in Session slot 0 instead of the Arrangement; unwarped=True plays
    it at native speed; stems below skip_below dBFS are not imported and those
    below mute_below are imported muted. Returns (new_xml, diff).

    Pure XML transform: no disk writes. The CLI layer owns dry-run/commit."""
    project_dir = Path(project_dir)
    if to not in ("arrangement", "session"):
        raise UsageError(f"--to must be 'arrangement' or 'session', not {to!r}")
    sorted_stem_files = sorted((Path(p) for p in stem_files), key=_natural_stem_key)
    doc0 = Doc(xml)
    master = doc0.track_by_id(master_track_id)
    drop_session = bool(doc0.arrangement_clips(master)) and not keep_session and to != "session"
    base = doc0.id_base()
    bpm = als.get_tempo(xml) or 120.0

    levels: dict[Path, float] = {}
    if mute_below is not None or skip_below is not None:
        levels = {p: _dbfs(p) for p in sorted_stem_files}
    skipped = [{"file": str(p), "label": _bare_label(p.stem), "dbfs": levels[p]}
               for p in sorted_stem_files if skip_below is not None and levels[p] < skip_below]
    skipped_files = {s["file"] for s in skipped}
    sorted_stem_files = [p for p in sorted_stem_files if str(p) not in skipped_files]

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
        doc = doc.apply()
        if to == "session" or unwarped:
            import soundfile as sf

            dur_s = sf.info(str(stem)).duration
            doc = _place(doc, doc.track_by_id(new_id), to, unwarped, dur_s, bpm)
        muted = bool(mute_below is not None and levels.get(stem, 0.0) < mute_below)
        if muted:
            speaker = doc.track_by_id(new_id).path("DeviceChain/Mixer/Speaker/Manual")
            if speaker is not None:
                doc.set_value(speaker, "false")
                doc = doc.apply()
        out = doc.to_str()
        meta: dict[str, Any] = {
            "file": str(stem),
            "label": label,
            "effective_name": effective_name,
            "color": color,
            "relative_path": str(rel),
            "placement": to,
            "unwarped": unwarped,
            "muted": muted,
        }
        if stem in levels:
            meta["dbfs"] = levels[stem]
        stems_meta.append(meta)

    stems_meta.reverse()  # report in filename order
    diff: dict[str, Any] = {"master_track_id": str(master_track_id), "stems": stems_meta}
    if skipped:
        diff["skipped"] = skipped
    return out, diff
