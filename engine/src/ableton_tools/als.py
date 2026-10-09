"""Read, inspect, and safely patch Ableton `.als` files (gzipped XML).

Mutating helpers take and return XML text (`(new_xml, diff)`) and never write
to disk; the CLI's commit pipeline (commit.py) handles guard/validate/backup/
write. All addressing goes through `alsxml` (span index, direct-child paths),
and edits are byte splices, so every untouched byte is preserved.
"""

from __future__ import annotations

import gzip
import re
import time
from pathlib import Path
from typing import Any

from .alsxml import Doc, Node, offset_block, set_next_pointee, write_atomic
from .errors import InternalError, UsageError


def read_als(path: str | Path) -> str:
    """Return the decompressed XML text of a .als file."""
    with gzip.open(str(path), "rb") as fh:
        return fh.read().decode("utf-8")


def write_als(path: str | Path, xml: str) -> None:
    """Gzip-write XML text to a .als file, atomically (temp file + rename)."""
    write_atomic(path, xml.encode("utf-8"))


def backup(path: str | Path, op: str) -> str:
    """Copy a .als into the project's `Backup/` folder using Ableton's native
    auto-backup naming: `<basename> [YYYY-MM-DD HHMMSS].als`. The Backup folder
    is created if it does not exist. `op` is accepted for API stability but is
    no longer encoded in the filename — Ableton's UI only recognizes its own
    naming format when offering rollback. If two calls land in the same
    wall-clock second, the collision is deduplicated with a ` (n)` counter
    suffix appended inside the same naming shape: `<stem> [stamp] (2).als`,
    `<stem> [stamp] (3).als`, etc. — the base `<stem> [stamp].als` form (what
    Live's rollback UI recognizes) is used whenever it is free. Returns the
    new path as a string."""
    path = Path(path)
    backup_dir = path.parent / "Backup"
    backup_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H%M%S")
    dest = backup_dir / f"{path.stem} [{stamp}].als"
    if dest.exists():
        n = 2
        while True:
            candidate = backup_dir / f"{path.stem} [{stamp}] ({n}).als"
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    dest.write_bytes(path.read_bytes())
    return str(dest)


TRACK_KIND = {"AudioTrack": "audio", "MidiTrack": "midi", "GroupTrack": "group",
              "ReturnTrack": "return"}


def _f(node: Node | None) -> float | None:
    v = node.value() if node is not None else None
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def warp_markers(clip: Node) -> list[tuple[float, float]]:
    wm = clip.child("WarpMarkers")
    if wm is None:
        return []
    return [(float(m.attrs["SecTime"]), float(m.attrs["BeatTime"]))
            for m in wm.children() if "SecTime" in m.attrs]


def warp_map_bpm(clip: Node) -> float | None:
    """Average tempo implied by a clip's warp map (the native-speed BPM)."""
    mk = warp_markers(clip)
    if len(mk) < 2 or mk[-1][0] <= mk[0][0]:
        return None
    return round((mk[-1][1] - mk[0][1]) / (mk[-1][0] - mk[0][0]) * 60.0, 4)


def _clip_name(clip: Node) -> str | None:
    """The clip's OWN name (direct child), never ScaleInformation/Name."""
    n = clip.child("Name")
    return n.value() if n is not None else None


def _clip_info(doc: Doc, track: Node | None, clip: Node, location: str) -> dict[str, Any]:
    ref = clip.path("SampleRef/FileRef")
    rel = ref.child("RelativePath") if ref is not None else None
    rtype = ref.child("RelativePathType") if ref is not None else None
    warped = clip.child("IsWarped")
    return {
        "name": _clip_name(clip),
        "track": doc.track_name(track) if track is not None else None,
        "location": location,
        "time": _f_attr(clip, "Time"),
        "current_start": _f(clip.child("CurrentStart")),
        "current_end": _f(clip.child("CurrentEnd")),
        "relative_path": rel.value() if rel is not None else None,
        "relative_path_type": rtype.value() if rtype is not None else None,
        "is_warped": (warped.value() == "true") if warped is not None else None,
        "warp_marker_count": len(warp_markers(clip)),
        "warp_map_bpm": warp_map_bpm(clip),
    }


def _f_attr(n: Node, name: str) -> float | None:
    try:
        return float(n.attrs[name]) if name in n.attrs else None
    except ValueError:
        return None


def inspect_xml(xml: str) -> dict[str, Any]:
    """Summary of a set: tempo, tracks (kind, group, output, mute, devices),
    the main track, and every Session/Arrangement clip."""
    doc = Doc(xml)
    info: dict[str, Any] = {"tempo": get_tempo(xml), "tracks": [], "main": None, "clips": []}
    for t in doc.tracks():
        g = t.child("TrackGroupId")
        out = t.path("DeviceChain/AudioOutputRouting/Target")
        speaker = t.path("DeviceChain/Mixer/Speaker/Manual")
        devs = t.path("DeviceChain/DeviceChain/Devices")
        info["tracks"].append({
            "tag": t.tag,
            "id": t.attrs.get("Id"),
            "name": doc.track_name(t),
            "kind": TRACK_KIND.get(t.tag, t.tag),
            "group_id": g.value() if g is not None and g.value() != "-1" else None,
            "output": out.value() if out is not None else None,
            "muted": (speaker.value() == "false") if speaker is not None else False,
            "devices": len(devs.children()) if devs is not None else 0,
        })
        for c in doc.arrangement_clips(t):
            info["clips"].append(_clip_info(doc, t, c, "arrangement"))
        for c in doc.session_clips(t):
            info["clips"].append(_clip_info(doc, t, c, "session"))
    try:
        main = doc.main_track()
        devs = main.path("DeviceChain/DeviceChain/Devices")
        name = main.path("Name/EffectiveName")
        info["main"] = {"tag": main.tag, "name": name.value() if name is not None else "Main",
                        "devices": len(devs.children()) if devs is not None else 0}
    except UsageError:
        pass
    if not info["clips"]:  # legacy/minimal docs: clips outside any <Tracks> track
        for c in doc.nodes("AudioClip"):
            info["clips"].append(_clip_info(doc, None, c, "unknown"))
    return info


def inspect(path: str | Path) -> dict[str, Any]:
    """inspect_xml() applied to a file on disk, with the path attached."""
    info = inspect_xml(read_als(path))
    info["file"] = str(path)
    return info


def _tempo_node(doc: Doc) -> Node:
    main = doc.main_track()
    manual = main.path("DeviceChain/Mixer/Tempo/Manual")
    if manual is None:
        raise UsageError(f"{main.tag} has no <Tempo><Manual> element to set",
                         hint="unexpected main-track layout; inspect the .als")
    return manual


def get_tempo(xml: str) -> float | None:
    """Project tempo from the MainTrack (Live 12) or MasterTrack (Live 11)."""
    try:
        return _f(_tempo_node(Doc(xml)))
    except UsageError:
        return None


def set_tempo(xml: str, bpm: float) -> str:
    """Set the project tempo (MainTrack/MasterTrack Tempo Manual) only."""
    doc = Doc(xml)
    doc.set_value(_tempo_node(doc), _num(bpm))
    return doc.apply().to_str()


def rename_refs(
    xml: str, mapping: dict[str, str], project_dir: Path | None = None
) -> tuple[str, dict[str, Any]]:
    """Re-point file references per `mapping` (old -> new project-relative path).

    Works per <FileRef> so a ref's RelativePath and absolute Path stay consistent.
    A ref matches `old` when its RelativePath equals it, or its absolute Path
    equals `old` (an absolute key) or `project_dir/old`. A match gets
    RelativePath = `new`, RelativePathType 3 (project) and, when `project_dir`
    is known, Path = `project_dir/new`; otherwise only Path's filename changes.
    A relative value is never written into Path.

    Refs under <OriginalFileRef> are left alone: they only record where a sample
    was first imported from, and Live doesn't load audio from them.
    Only <RelativePath>/<Path>/<RelativePathType> leaves are patched."""
    doc = Doc(xml)
    hits: dict[str, int] = {old: 0 for old in mapping}
    for ref in doc.nodes("FileRef"):
        if any(a.tag == "OriginalFileRef" for a in ref.ancestors()):
            continue
        rel, path = ref.child("RelativePath"), ref.child("Path")
        rtype = ref.child("RelativePathType")
        rel_v = rel.value() if rel is not None else None
        path_v = path.value() if path is not None else None
        for old, new in mapping.items():
            abs_old = str(project_dir / old) if project_dir is not None else None
            if not (rel_v == old or (path_v is not None and path_v in (old, abs_old))):
                continue
            if rel is not None:
                doc.set_value(rel, new)
            if rtype is not None and rel is not None:
                doc.set_value(rtype, 3)
            if path is not None and path_v:
                if project_dir is not None:
                    doc.set_value(path, str(project_dir / new))
                elif path_v.endswith("/" + Path(old).name):
                    doc.set_value(path, path_v[: -len(Path(old).name)] + Path(new).name)
            hits[old] += 1
            break
    changed = sum(1 for n in hits.values() if n)
    diff = {"changed": changed, "refs": sum(hits.values()), "mapping": mapping}
    return doc.apply().to_str(), diff


SHADOW_CONTAINERS = frozenset({"FreezeSequencer", "TakeLanes"})


def _all_clips(doc: Doc) -> list[Node]:
    """Every real clip: frozen renders (FreezeSequencer) and comping takes
    (TakeLanes) are copies Live manages itself, never addressed by name."""
    clips = doc.nodes("AudioClip") + doc.nodes("MidiClip")
    return sorted((c for c in clips
                   if not any(a.tag in SHADOW_CONTAINERS for a in c.ancestors())),
                  key=lambda n: n.start)


def find_clip(doc: Doc, clip_name: str, *, arrangement_first: bool = True) -> Node:
    """The unique clip named `clip_name`. With arrangement_first, a name that is
    unique among Arrangement clips wins even if a Session clip shares it
    (arrangement operations ignore Session clips)."""
    named = [c for c in _all_clips(doc) if _clip_name(c) == clip_name]
    if arrangement_first and len(named) > 1:
        arr = [c for t in doc.tracks() for c in doc.arrangement_clips(t) if c in named]
        if len(arr) == 1:
            return arr[0]
    if not named:
        raise UsageError(
            f"Clip named {clip_name!r} not found",
            hint="run `ableton als inspect FILE.als --json` to list clip names",
        )
    if len(named) > 1:
        raise UsageError(
            f"Clip name {clip_name!r} is ambiguous ({len(named)} matches); "
            "rename one clip or address it by a unique name",
            hint="run `ableton als inspect FILE.als --json` to list clip names",
        )
    return named[0]


def _clip_block(xml: str, clip_name: str) -> tuple[int, int]:
    """Back-compat: byte span of the unique clip named clip_name (no
    arrangement preference)."""
    c = find_clip(Doc(xml), clip_name, arrangement_first=False)
    return c.start, c.end


def move_clip_to_beat(
    xml: str, clip_name: str, beat: float, dur_s: float | None = None, bpm: float | None = None
) -> tuple[str, dict[str, Any]]:
    """Move a clip so it starts at `beat`: sets the arrangement `Time` attribute
    and CurrentStart/CurrentEnd. Without dur_s the clip's current length (in
    beats) is preserved; with dur_s and bpm the length is dur_s*bpm/60."""
    doc = Doc(xml)
    c = find_clip(doc, clip_name)
    cs, ce = _f(c.child("CurrentStart")), _f(c.child("CurrentEnd"))
    if dur_s is not None:
        if bpm is None:
            raise UsageError("--dur-s needs --bpm", hint="pass both, or neither to keep length")
        length = dur_s * bpm / 60.0
    else:
        if cs is None or ce is None:
            raise UsageError(f"Clip {clip_name!r} has no CurrentStart/CurrentEnd")
        length = ce - cs
    for tag, val in (("CurrentStart", beat), ("CurrentEnd", beat + length)):
        node = c.child(tag)
        if node is not None:
            doc.set_value(node, _num(val))
    if "Time" in c.attrs:
        doc.set_attr(c, "Time", _num(beat))
    return doc.apply().to_str(), {"clip": clip_name, "to_beat": beat,
                                  "end_beat": round(beat + length, 6)}


def warp_to_grid(
    xml: str, clip_names: list[str], bpm: float, durations: dict[str, float]
) -> tuple[str, dict[str, Any]]:
    """Lock each named clip to the grid with two warp markers (0 and end),
    at the given project bpm. `durations` maps clip_name -> seconds."""
    doc = Doc(xml)
    warped = []
    for name in clip_names:
        c = find_clip(doc, name)
        wm = c.child("WarpMarkers")
        if wm is None:
            raise UsageError(
                f"Clip {name!r} has no <WarpMarkers> block to replace; cannot grid-lock it",
                hint="only previously-warped audio clips can be grid-locked",
            )
        dur_s = durations[name]
        end_beat = dur_s * bpm / 60.0
        doc.replace(wm, (
            "<WarpMarkers>\n"
            '<WarpMarker Id="0" SecTime="0" BeatTime="0" />\n'
            f'<WarpMarker Id="1" SecTime="{dur_s:g}" BeatTime="{end_beat:g}" />\n'
            "</WarpMarkers>"
        ))
        iw = c.child("IsWarped")
        if iw is not None:
            doc.set_value(iw, "true")
        warped.append(name)
    return doc.apply().to_str(), {"warped": warped, "bpm": bpm}


def verify_refs(xml: str, base_dir: str | Path) -> list[str]:
    """Project-relative (RelativePathType 3, or untyped legacy) refs that do not
    resolve under base_dir. Library/built-in refs (types 5/6/7) and external
    absolute refs (type 1) are not project files and are never reported here;
    see validate.ref_report for the full typed report."""
    from .validate import ref_report

    return ref_report(Doc(xml), base_dir)["missing_project"]


def _find_track_block(xml: str, src_track_id: str | int) -> tuple[int, int, str]:
    """Back-compat: (start, end, tag-without-'Track') of the track with this Id."""
    t = Doc(xml).track_by_id(src_track_id)
    return t.start, t.end, t.tag[: -len("Track")]


_DEFAULT_SEND = "0.0003162277571"  # -inf dB: Live's level for a new track's sends
_DEFAULT_MIXER = (("Volume/Manual", "1"), ("Pan/Manual", "0"), ("PanMode", "0"),
                  ("SplitStereoPanL/Manual", "-1"), ("SplitStereoPanR/Manual", "1"),
                  ("CrossFadeState/Manual", "1"))


def reset_copied_state(doc: Doc, track: Node, *, mixer: bool) -> None:
    """Queue the edits that stop a copied track inheriting its source's
    per-track state: frozen audio, take lanes, mute, solo and arm. With
    `mixer`, volume, pan and sends also go back to Live's defaults (a bare new
    track); without it they are kept (stem clones keep the master's gain)."""

    def put(node: Node | None, value: str) -> None:
        if node is not None and node.value() != value:
            doc.set_value(node, value)

    put(track.child("Freeze"), "false")
    for seq in track.find_all("FreezeSequencer"):
        for clip in seq.find_all("AudioClip") + seq.find_all("MidiClip"):
            if clip.parent is not None and clip.parent.tag == "Value":
                doc.replace(clip.parent, "<Value />")
            else:
                doc.remove(clip)
    lanes = track.path("TakeLanes/TakeLanes")
    if lanes is not None and lanes.children():
        doc.replace(lanes, "<TakeLanes />")
    for armed in track.find_all("IsArmed"):
        put(armed, "false")
    m = track.path("DeviceChain/Mixer")
    if m is None:
        return
    put(m.path("Speaker/Manual"), "true")
    put(m.child("SoloSink"), "false")
    if mixer:
        for path, value in _DEFAULT_MIXER:
            put(m.path(path), value)
        for send in m.find_all("Send"):
            put(send.child("Manual"), _DEFAULT_SEND)


def clone_track(
    xml: str,
    src_track_id: str | int,
    new_name: str,
    new_id: int,
    id_offset: int | None = None,
) -> str:
    """PRIMITIVE (not a command): duplicate a track, give every internal
    `Id="N"` (and every automation PointeeId aimed inside the track) a unique
    value via `id_offset` (default: auto-allocate above the
    document's current max Id), set the top-level track Id and EffectiveName,
    insert the clone after the source, and bump `<NextPointeeId>` (Ableton
    refuses to load a .als if any Id is >= NextPointeeId).

    Reusing an explicit `id_offset` that lands a shifted Id or `new_id` on an
    Id already present raises ValueError naming the offset and the colliding
    ids; omit `id_offset` to auto-allocate."""
    doc = Doc(xml)
    src = doc.track_by_id(src_track_id)
    if id_offset is None:
        id_offset = doc.id_base()
    clone = Doc(offset_block(src.text(doc), id_offset))  # ids + self-targeting automation
    croot = clone.root
    clone.set_attr(croot, "Id", new_id)
    eff = croot.path("Name/EffectiveName")
    if eff is not None:
        clone.set_value(eff, new_name)
    clone_bytes = clone.apply().data

    existing = {int(i) for i in re.findall(rb'(?<=\s)Id="(\d+)"', doc.data)}
    clone_ids = {int(i) for i in re.findall(rb'(?<=\s)Id="(\d+)"', clone_bytes)}
    colliding = clone_ids & existing
    if colliding:
        raise InternalError(
            f"clone_track: id_offset={id_offset} (new_id={new_id}) collides "
            f"with existing Id(s) {sorted(colliding)[:10]} already present in the "
            f"document. Pass a distinct id_offset, or omit id_offset to "
            f"auto-allocate above the current document max."
        )
    doc.insert_after(src, b"\n" + clone_bytes)
    return set_next_pointee(doc.apply()).to_str()
