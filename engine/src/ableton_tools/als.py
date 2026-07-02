"""Read, inspect, and safely patch Ableton `.als` files (gzipped XML).

Mutating helpers return (new_xml, diff) and never write to disk themselves;
the CLI handles backup + commit. inspect() uses ElementTree; patchers use
targeted regex to preserve the original file's formatting.
"""

import gzip
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def read_als(path):
    """Return the decompressed XML text of a .als file."""
    with gzip.open(str(path), "rb") as fh:
        return fh.read().decode("utf-8")


def write_als(path, xml):
    """Gzip-write XML text to a .als file."""
    with gzip.open(str(path), "wb") as fh:
        fh.write(xml.encode("utf-8"))


def backup(path, op):
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


def _attr(elem, child_tag, attr="Value", default=None):
    c = elem.find(child_tag)
    return c.get(attr) if c is not None else default


def inspect_xml(xml):
    """Parse XML text into a summary dict (tempo, tracks, clips, refs)."""
    root = ET.fromstring(xml)
    info = {"tempo": None, "tracks": [], "clips": []}

    manual = root.find(".//MasterTrack//Tempo/Manual")
    if manual is not None:
        info["tempo"] = float(manual.get("Value"))

    for track in root.iter():
        if not track.tag.endswith("Track") or track.tag in ("MasterTrack", "Tracks"):
            continue
        name_el = track.find("./Name/EffectiveName")
        if name_el is not None:
            info["tracks"].append({"tag": track.tag, "id": track.get("Id"),
                                   "name": name_el.get("Value")})

    for clip in root.iter("AudioClip"):
        name = _attr(clip, "Name", default=None)
        start = clip.find("CurrentStart")
        end = clip.find("CurrentEnd")
        rel = clip.find(".//SampleRef/FileRef/RelativePath")
        warped = clip.find("IsWarped")
        info["clips"].append({
            "name": name,
            "current_start": float(start.get("Value")) if start is not None else None,
            "current_end": float(end.get("Value")) if end is not None else None,
            "relative_path": rel.get("Value") if rel is not None else None,
            "is_warped": (warped.get("Value") == "true") if warped is not None else None,
        })
    return info


def inspect(path):
    """inspect_xml() applied to a file on disk, with the path attached."""
    info = inspect_xml(read_als(path))
    info["file"] = str(path)
    return info


def set_tempo(xml, bpm):
    """Set the master tempo Manual Value."""
    return re.sub(
        r'(<Tempo>\s*<Manual Value=")[\d.]+(")',
        rf"\g<1>{bpm:g}\g<2>",
        xml,
        count=1,
    )


def rename_refs(xml, mapping):
    """Replace RelativePath/Path values per `mapping` (old_rel -> new_rel).
    Only <RelativePath> and <Path> leaves are patched; any other attribute
    whose value happens to equal an old path is left alone."""
    changed = 0
    out = xml
    for old, new in mapping.items():
        old_name = Path(old).name
        new_name = Path(new).name
        before = out
        out = re.sub(
            rf'(<(?:RelativePath|Path) Value="){re.escape(old)}(")',
            lambda m: m.group(1) + new + m.group(2),
            out,
        )
        # also patch absolute Path leaves that end with the old filename
        out = re.sub(
            rf'(<Path Value="[^"]*/){re.escape(old_name)}(")',
            lambda m: m.group(1) + new_name + m.group(2),
            out,
        )
        if out != before:
            changed += 1
    return out, {"changed": changed, "mapping": mapping}


def _clip_block(xml, clip_name):
    """Return (start_idx, end_idx) of the <AudioClip>...</AudioClip> block whose
    <Name Value="clip_name"/> matches, or raise."""
    for m in re.finditer(r"<AudioClip\b.*?</AudioClip>", xml, re.DOTALL):
        block = m.group(0)
        if re.search(rf'<Name Value="{re.escape(clip_name)}"', block):
            return m.start(), m.end()
    raise KeyError(f"AudioClip named {clip_name!r} not found")


def move_clip_to_beat(xml, clip_name, beat, dur_s, bpm):
    """Set a clip's CurrentStart to `beat` and CurrentEnd to beat + length."""
    s, e = _clip_block(xml, clip_name)
    block = xml[s:e]
    length_beats = dur_s * bpm / 60.0
    block = re.sub(r'(<CurrentStart Value=")[\d.]+(")', rf"\g<1>{beat:g}\g<2>", block)
    block = re.sub(r'(<CurrentEnd Value=")[\d.]+(")',
                   rf"\g<1>{beat + length_beats:g}\g<2>", block)
    new_xml = xml[:s] + block + xml[e:]
    return new_xml, {"clip": clip_name, "to_beat": beat,
                     "end_beat": round(beat + length_beats, 6)}


def warp_to_grid(xml, clip_names, bpm, durations):
    """Lock each named clip to the grid with two warp markers (0 and end),
    at the given project bpm. `durations` maps clip_name -> seconds."""
    warped = []
    out = xml
    for name in clip_names:
        s, e = _clip_block(out, name)
        block = out[s:e]
        dur_s = durations[name]
        end_beat = dur_s * bpm / 60.0
        markers = (
            "<WarpMarkers>\n"
            '<WarpMarker Id="0" SecTime="0" BeatTime="0"/>\n'
            f'<WarpMarker Id="1" SecTime="{dur_s:g}" BeatTime="{end_beat:g}"/>\n'
            "</WarpMarkers>"
        )
        block = re.sub(r"<WarpMarkers>.*?</WarpMarkers>", markers, block, flags=re.DOTALL)
        if "<IsWarped" in block:
            block = re.sub(r'<IsWarped Value="(true|false)"/>',
                           '<IsWarped Value="true"/>', block)
        out = out[:s] + block + out[e:]
        warped.append(name)
    return out, {"warped": warped, "bpm": bpm}


def verify_refs(xml, base_dir):
    """Return RelativePath values that do not resolve under base_dir."""
    base = Path(base_dir)
    missing = []
    for rel in re.findall(r'<RelativePath Value="([^"]+)"', xml):
        if not (base / rel).exists():
            missing.append(rel)
    return missing


def _find_track_block(xml, src_track_id):
    """Locate `<{Tag}Track Id="src_track_id" ...>...</{Tag}Track>` in `xml`.
    Returns (start, end, tag) where (start, end) bound the full block and tag
    is e.g. "Audio" or "Midi". Tolerates extra attributes after Id
    (`SelectedToolPanel`, `SelectedTransformationName`, ...) which the original
    regex did not. Assumes tracks do not nest (Ableton's invariant)."""
    open_re = re.compile(rf'<(\w+)Track\s+Id="{src_track_id}"[^>]*>')
    m = open_re.search(xml)
    if not m:
        raise KeyError(f"Track Id {src_track_id} not found")
    tag = m.group(1)
    end = xml.find(f"</{tag}Track>", m.end())
    if end < 0:
        raise RuntimeError(f"Closing </{tag}Track> not found for Id={src_track_id}")
    return m.start(), end + len(f"</{tag}Track>"), tag


def clone_track(xml, src_track_id, new_name, new_id, id_offset=None):
    """PRIMITIVE (not a command): duplicate a track block, give every internal
    `Id="N"` a unique value via `id_offset` (default: auto-allocate above the
    document's current max Id), set the top-level track Id and EffectiveName,
    insert the clone after the source, and bump `<NextPointeeId>` to cover the
    new IDs (Ableton refuses to load a .als if any Id is >= NextPointeeId).

    `id_offset` is added to every `Id="N"` inside the cloned block before the
    top-level Id is then overwritten with `new_id`. Two calling patterns are
    collision-free: (1) chain calls, omitting `id_offset` each time so it is
    re-derived from the growing document's current max Id, or (2) pass
    distinct explicit `id_offset` values per call. Reusing the same explicit
    `id_offset` across calls (or any other choice that lands a shifted Id or
    `new_id` on an Id already present) is NOT silently safe: this function
    checks the clone's resulting Ids against `xml`'s existing Ids before
    inserting and raises ValueError, naming the offset and the colliding
    ids, on overlap."""
    s, e, _tag = _find_track_block(xml, src_track_id)
    block = xml[s:e]

    all_ids = [int(x) for x in re.findall(r'Id="(\d+)"', xml)]
    doc_max = max(all_ids) if all_ids else 0
    if id_offset is None:
        id_offset = ((doc_max // 10000) + 1) * 10000

    clone = re.sub(
        r'Id="(\d+)"',
        lambda g: f'Id="{int(g.group(1)) + id_offset}"',
        block,
    )
    clone = re.sub(
        rf'(<\w+Track Id=")\d+(")',
        rf"\g<1>{new_id}\g<2>",
        clone,
        count=1,
    )
    clone = re.sub(
        r'(<EffectiveName Value=")[^"]*(")',
        rf"\g<1>{new_name}\g<2>",
        clone,
        count=1,
    )

    clone_ids = {int(x) for x in re.findall(r'Id="(\d+)"', clone)}
    colliding = clone_ids & set(all_ids)
    if colliding:
        raise ValueError(
            f"clone_track: id_offset={id_offset} (new_id={new_id}) collides "
            f"with existing Id(s) {sorted(colliding)} already present in the "
            f"document. Pass a distinct id_offset, or omit id_offset to "
            f"auto-allocate above the current document max."
        )

    new_xml = xml[:e] + "\n" + clone + xml[e:]

    # Bump NextPointeeId past every Id we now have in the document. Required
    # for Ableton to accept the file — without this, load fails with:
    # "NextPointeeId is too low: <stored> must be bigger than <max-id>".
    max_id = max(int(x) for x in re.findall(r'Id="(\d+)"', new_xml))
    new_xml, n = re.subn(
        r'(<NextPointeeId Value=")\d+(")',
        rf'\g<1>{max_id + 1}\g<2>',
        new_xml,
        count=1,
    )
    if n == 0:
        # No NextPointeeId in this document (older format or minimal fixture).
        # Caller should add one if writing a Live 11+ file.
        pass
    return new_xml
