"""Composable session-building commands: set-tempo, mute, add-track, group,
sync-to-master. Each takes and returns XML text plus a diff (no disk writes;
the CLI commits through commit.py). Track arguments resolve via
`Doc.find_track` (exact name, Live's "<index>-" prefix stripped, or Id).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import als
from .alsxml import Doc, Node, offset_block, offset_ids, set_next_pointee
from .errors import UsageError

GROUP_TEMPLATE = Path(__file__).parent / "templates" / "group_track.xml"
GROUP_ROUTING = ("AudioOut/GroupTrack", "Group", "")
MAIN_ROUTING = ("AudioOut/Main", "Main", "")
CLIP_POSITION = (
    "CurrentStart", "CurrentEnd", "Loop/LoopStart", "Loop/LoopEnd",
    "Loop/HiddenLoopStart", "Loop/HiddenLoopEnd", "Loop/StartRelative",
)


def set_tempo_cmd(xml: str, bpm: float) -> tuple[str, dict[str, Any]]:
    previous = als.get_tempo(xml)
    return als.set_tempo(xml, bpm), {"tempo": bpm, "previous": previous}


def mute(xml: str, tracks: list[str], unmute: bool = False) -> tuple[str, dict[str, Any]]:
    doc = Doc(xml)
    names = []
    for name in tracks:
        t = doc.find_track(name)
        speaker = t.path("DeviceChain/Mixer/Speaker/Manual")
        if speaker is None:
            raise UsageError(f"{doc.track_name(t)!r} has no mixer Speaker to (un)mute")
        doc.set_value(speaker, "true" if unmute else "false")
        names.append(doc.track_name(t))
    return doc.apply().to_str(), {"unmuted" if unmute else "muted": names}


def _set_routing(doc: Doc, track: Node, routing: tuple[str, str, str]) -> None:
    target, upper, lower = routing
    r = track.path("DeviceChain/AudioOutputRouting")
    if r is None:
        return
    for tag, val in (("Target", target), ("UpperDisplayString", upper),
                     ("LowerDisplayString", lower)):
        n = r.child(tag)
        if n is not None:
            doc.set_value(n, val)


def _group_end(doc: Doc, track: Node) -> Node:
    """`track` itself, or for a group (or a group member) the group's last member,
    so an insertion after it never splits a group's contiguous members."""
    tracks = doc.tracks()
    gid = track.attrs.get("Id") if track.tag == "GroupTrack" else None
    if gid is None:
        g = track.child("TrackGroupId")
        gid = g.value() if g is not None and g.value() != "-1" else None
    if gid is None:
        return track
    last = track
    for t in tracks[tracks.index(track) + 1 :]:
        g = t.child("TrackGroupId")
        if g is not None and g.value() == gid:
            last = t
        elif t.start > last.end:
            break
    return last


def add_track(
    xml: str, name: str, color: int | None = None, after: str | None = None
) -> tuple[str, dict[str, Any]]:
    """A bare audio track (no clips, devices or automation), shaped like the
    set's first audio track so its mixer/sends match the set."""
    doc = Doc(xml)
    tracks = doc.tracks()
    audio = [t for t in tracks if t.tag == "AudioTrack"]
    if not audio:
        raise UsageError("add-track needs an existing audio track to copy the layout from")
    new_id = doc.id_base()
    clone = Doc(offset_block(audio[0].text(doc), new_id + 1))
    root = clone.root
    clone.set_attr(root, "Id", new_id)
    for path, val in (("Name/EffectiveName", name), ("Name/UserName", name),
                      ("Name/MemorizedFirstClipName", ""), ("TrackGroupId", "-1")):
        n = root.path(path)
        if n is not None:
            clone.set_value(n, val)
    track_color = root.child("Color")
    if color is not None and track_color is not None:
        clone.set_value(track_color, color)
    _set_routing(clone, root, MAIN_ROUTING)
    clone.replace(clone.effects_devices(root), "<Devices />")
    env = root.path("AutomationEnvelopes/Envelopes")
    if env is not None:
        clone.replace(env, "<Envelopes />")
    for c in clone.arrangement_clips(root):
        clone.remove(c)
    for c in clone.session_clips(root):
        if c.parent is not None and c.parent.tag == "Value":
            clone.replace(c.parent, "<Value />")
    clone_bytes = clone.apply().data

    if after is not None:
        anchor = _group_end(doc, doc.find_track(after))
    else:
        non_return = [t for t in tracks if t.tag != "ReturnTrack"]
        anchor = _group_end(doc, non_return[-1]) if non_return else tracks[-1]
    doc.insert_after(anchor, b"\n\t\t\t" + clone_bytes)
    out = set_next_pointee(doc.apply())
    return out.to_str(), {"track": name, "track_id": str(new_id),
                          "after": doc.track_name(anchor)}


def _adapted_group_template(n_returns: int, n_scenes: int) -> bytes:
    tdoc = Doc(GROUP_TEMPLATE.read_bytes())
    root = tdoc.root
    sends = root.path("DeviceChain/Mixer/Sends")
    holders = sends.children() if sends is not None else []
    if sends is not None:
        if n_returns == 0 or not holders:
            tdoc.replace(sends, "<Sends />")
        else:
            pieces = []
            for k in range(n_returns):
                src = holders[min(k, len(holders) - 1)].text(tdoc)
                extra = k - len(holders) + 1
                h = Doc(offset_ids(src, extra * 10000) if extra > 0 else src)
                h.set_attr(h.root, "Id", k)
                pieces.append(h.apply().data)
            tdoc.replace(sends, b"<Sends>\n" + b"\n".join(pieces) + b"\n</Sends>")
    slots = root.child("Slots")
    if slots is not None:
        body = "".join(
            f'\n<GroupTrackSlot Id="{k}">\n<LomId Value="0" />\n</GroupTrackSlot>'
            for k in range(n_scenes)
        )
        tdoc.replace(slots, f"<Slots>{body}\n</Slots>" if n_scenes else "<Slots />")
    return tdoc.apply().data


def group(
    xml: str, name: str, tracks: list[str], color: int | None = None
) -> tuple[str, dict[str, Any]]:
    """Fold contiguous tracks into a new GroupTrack: members get TrackGroupId
    AND output routing to the group bus; the group routes to Main."""
    doc = Doc(xml)
    all_tracks = doc.tracks()
    members: list[Node] = []
    for n in tracks:
        t = doc.find_track(n)
        if t.start not in {m.start for m in members}:
            members.append(t)
    members.sort(key=lambda t: t.start)
    for m in members:
        if m.tag == "ReturnTrack":
            raise UsageError(f"{doc.track_name(m)!r} is a return track and cannot be grouped")
        g = m.child("TrackGroupId")
        if g is not None and g.value() != "-1":
            raise UsageError(f"{doc.track_name(m)!r} is already in a group",
                             hint="nested groups are not supported; ungroup it in Live first")
    positions = [all_tracks.index(m) for m in members]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise UsageError("Tracks to group must be contiguous in the track list",
                         hint="reorder them in Live (or group adjacent runs separately)")

    n_returns = sum(1 for t in all_tracks if t.tag == "ReturnTrack")
    n_scenes = sum(1 for s in doc.nodes("Scene") if s.parent is not None
                   and s.parent.tag == "Scenes")
    gid = doc.id_base()
    gdoc = Doc(offset_ids(_adapted_group_template(n_returns, n_scenes), gid + 1))
    groot = gdoc.root
    gdoc.set_attr(groot, "Id", gid)
    for path in ("Name/EffectiveName", "Name/UserName"):
        n = groot.path(path)
        if n is not None:
            gdoc.set_value(n, name)
    group_color = groot.child("Color")
    if group_color is not None:
        gdoc.set_value(group_color, color if color is not None else 0)
    _set_routing(gdoc, groot, MAIN_ROUTING)

    doc.insert_before(members[0], gdoc.apply().data + b"\n\t\t\t")
    for m in members:
        gnode = m.child("TrackGroupId")
        if gnode is None:
            raise UsageError(f"{doc.track_name(m)!r} has no TrackGroupId; cannot group it")
        doc.set_value(gnode, gid)
        _set_routing(doc, m, GROUP_ROUTING)
    out = set_next_pointee(doc.apply())
    return out.to_str(), {"group": name, "group_id": str(gid),
                          "members": [doc.track_name(m) for m in members],
                          "sends": n_returns, "slots": n_scenes}


def sync_to_master(
    xml: str,
    master: str,
    tracks: list[str] | None = None,
    all_warped: bool = False,
    markers: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Copy the master's Arrangement clip position (Time attr, CurrentStart/End,
    loop bounds) onto the target tracks' warped Arrangement clips. With
    markers=True the master's WarpMarkers are copied too; otherwise targets whose
    markers differ are reported (they would drift)."""
    doc = Doc(xml)
    m = doc.find_track(master)
    mclips = doc.arrangement_clips(m)
    if not mclips:
        raise UsageError(f"{doc.track_name(m)!r} has no Arrangement clip to sync from")
    mc = mclips[0]
    vals: dict[str, str | None] = {}
    for p in CLIP_POSITION:
        node = mc.path(p)
        if node is not None:
            vals[p] = node.value()
    mtime = mc.attrs.get("Time")
    mmarkers = als.warp_markers(mc)
    mwm = mc.child("WarpMarkers")
    if all_warped:
        targets = [t for t in doc.tracks() if t.start != m.start]
    elif tracks:
        targets = [doc.find_track(n) for n in tracks]
    else:
        raise UsageError("sync-to-master needs --tracks or --all-warped")

    synced, mismatch = [], []
    for t in targets:
        for c in doc.arrangement_clips(t):
            iw = c.child("IsWarped")
            if iw is None or iw.value() != "true":
                continue
            if mtime is not None and "Time" in c.attrs:
                doc.set_attr(c, "Time", mtime)
            for path, v in vals.items():
                n = c.path(path)
                if n is not None and v is not None:
                    doc.set_value(n, v)
            cwm = c.child("WarpMarkers")
            if markers and mwm is not None and cwm is not None:
                doc.replace(cwm, mwm.text(doc))
            elif als.warp_markers(c) != mmarkers and doc.track_name(t) not in mismatch:
                mismatch.append(doc.track_name(t))
            name = c.child("Name")
            synced.append({"track": doc.track_name(t),
                           "clip": name.value() if name is not None else None})
    return doc.apply().to_str(), {"master": doc.track_name(m), "synced": synced,
                                  "marker_mismatch": mismatch, "markers_copied": markers}
