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
    """Copy a .als to `<name>.als.backup-pre-<op>-<timestamp>`; return its path."""
    path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.backup-pre-{op}-{stamp}")
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
    """Replace RelativePath/Path values per `mapping` (old_rel -> new_rel)."""
    changed = 0
    out = xml
    for old, new in mapping.items():
        old_name = Path(old).name
        new_name = Path(new).name
        before = out
        out = out.replace(f'Value="{old}"', f'Value="{new}"')
        # also patch absolute Path leaves that end with the old filename
        out = re.sub(
            rf'(<Path Value="[^"]*/){re.escape(old_name)}(")',
            rf"\g<1>{new_name}\g<2>",
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


def clone_track(xml, src_track_id, new_name, new_id):
    """PRIMITIVE (not a command): duplicate a track block, bump its Id and
    sub-component Ids by a large offset, and set a new EffectiveName. Returns
    the new XML with the cloned track inserted after the source track."""
    pattern = rf'(<\w+Track Id="{src_track_id}">.*?</\w+Track>)'
    m = re.search(pattern, xml, re.DOTALL)
    if not m:
        raise KeyError(f"Track Id {src_track_id} not found")
    block = m.group(1)
    clone = re.sub(r'Id="(\d+)"', lambda g: f'Id="{int(g.group(1)) + 30000}"', block)
    clone = re.sub(rf'(<\w+Track Id=")\d+("', rf"\g<1>{new_id}\g<2>", clone, count=1)
    clone = re.sub(r'(<EffectiveName Value=")[^"]*(")', rf"\g<1>{new_name}\g<2>", clone, count=1)
    return xml[: m.end()] + "\n" + clone + xml[m.end():]
