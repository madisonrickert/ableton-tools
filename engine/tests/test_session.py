import re

import numpy as np
import pytest
import soundfile as sf
from conftest import FIXTURES

from ableton_tools import als, session
from ableton_tools import import_stems as ist
from ableton_tools.alsxml import Doc, offset_ids
from ableton_tools.errors import UsageError
from ableton_tools.validate import validate

LIVE12 = (FIXTURES / "live12_set.xml").read_text(encoding="utf-8")
CHAIN = (FIXTURES / "chain_src.xml").read_text(encoding="utf-8")


def _ok(xml):
    report = validate(Doc(xml))
    assert report["ok"], report["errors"][:3]
    return report


def _with_stems(project, names=("0 Lead Vocals.wav", "1 Drums.wav")):
    d = project / "stems"
    d.mkdir(exist_ok=True)
    x = 0.01 * np.random.default_rng(1).standard_normal(96000).astype(np.float32)
    for n in names:
        sf.write(str(d / n), x, 48000)
    out, _ = ist.import_stems(LIVE12, "8", sorted(d.glob("*.wav")), project)
    return out


def _names(xml):
    doc = Doc(xml)
    return [doc.track_name(t) for t in doc.tracks()]


def test_set_tempo_cmd_reports_previous():
    out, diff = session.set_tempo_cmd(LIVE12, 133.9)
    assert als.get_tempo(out) == 133.9 and diff == {"tempo": 133.9, "previous": 136.0}


def test_mute_and_unmute():
    out, diff = session.mute(LIVE12, ["master"])
    doc = Doc(out)
    assert doc.track_by_id(8).path("DeviceChain/Mixer/Speaker/Manual").value() == "false"
    assert diff["muted"] == ["1-master"]
    back, _ = session.mute(out, ["master"], unmute=True)
    assert Doc(back).track_by_id(8).path("DeviceChain/Mixer/Speaker/Manual").value() == "true"


def test_add_track_is_bare_and_validates():
    out, diff = session.add_track(LIVE12, "SAX (live layer)", color=25, after="master")
    _ok(out)
    doc = Doc(out)
    assert _names(out)[:2] == ["1-master", "SAX (live layer)"]
    t = doc.find_track("SAX (live layer)")
    assert doc.arrangement_clips(t) == [] and doc.session_clips(t) == []
    assert doc.effects_devices(t).children() == []
    assert t.path("AutomationEnvelopes/Envelopes").children() == []
    assert t.child("TrackGroupId").value() == "-1"
    assert t.path("DeviceChain/AudioOutputRouting/Target").value() == "AudioOut/Main"
    assert t.child("Color").value() == "25" and diff["track_id"] == t.attrs["Id"]


def test_group_routes_members_and_validates(live12_project):
    xml = _with_stems(live12_project.parent)
    out, diff = session.group(xml, "VOX", ["Lead Vocals", "Drums"], color=20)
    report = _ok(out)
    assert report["warnings"] == []
    doc = Doc(out)
    g = doc.find_track("VOX")
    assert g.tag == "GroupTrack" and g.child("Color").value() == "20"
    order = [doc.track_name(t) for t in doc.tracks()]
    assert order.index("VOX") == order.index("2-Lead Vocals") - 1
    for name in ("Lead Vocals", "Drums"):
        m = doc.find_track(name)
        assert m.child("TrackGroupId").value() == g.attrs["Id"]
        assert m.path("DeviceChain/AudioOutputRouting/Target").value() == "AudioOut/GroupTrack"
        assert m.path("DeviceChain/AudioOutputRouting/UpperDisplayString").value() == "Group"
    assert g.path("DeviceChain/AudioOutputRouting/Target").value() == "AudioOut/Main"
    assert diff["group_id"] == g.attrs["Id"]


def _add_returns_and_scenes(xml, extra_returns, scenes):
    for k in range(extra_returns):
        xml = als.clone_track(xml, 2, f"R{k}", 900000 + k)
    doc = Doc(xml)
    scene_nodes = doc.nodes("Scene")
    first = scene_nodes[0]
    blob = first.text(doc)
    extra = range(scenes - len(scene_nodes))
    add = b"".join(b"\n" + offset_ids(blob, 700000 + 1000 * i) for i in extra)
    doc.insert_after(scene_nodes[-1], add)
    return doc.apply().to_str()


def test_group_adapts_sends_and_slots():
    xml = _add_returns_and_scenes(LIVE12, extra_returns=1, scenes=12)
    out, _ = session.group(xml, "G", ["master"])
    _ok(out)
    g = Doc(out).find_track("G")
    assert len(g.path("DeviceChain/Mixer/Sends").children()) == 3
    assert len(g.child("Slots").children()) == 12


def test_group_with_no_returns_has_empty_sends():
    doc = Doc(LIVE12)
    for t in doc.tracks():
        if t.tag == "ReturnTrack":
            doc.remove(t)
    out, _ = session.group(doc.apply().to_str(), "G", ["master"])
    _ok(out)
    assert Doc(out).find_track("G").path("DeviceChain/Mixer/Sends").children() == []


def test_group_rejects_non_contiguous_and_already_grouped(live12_project):
    xml = _with_stems(live12_project.parent, ("0 A.wav", "1 B.wav", "2 C.wav"))
    with pytest.raises(UsageError, match="contiguous"):
        session.group(xml, "G", ["A", "C"])
    grouped, _ = session.group(xml, "G", ["A", "B"])
    with pytest.raises(UsageError, match="already"):
        session.group(grouped, "H", ["B", "C"])


def test_sync_to_master_copies_position_and_reports_marker_drift(live12_project):
    xml = _with_stems(live12_project.parent)
    moved, _ = als.move_clip_to_beat(xml, "master", 2.5)
    out, diff = session.sync_to_master(moved, "master", all_warped=True)
    _ok(out)
    doc = Doc(out)
    m = doc.arrangement_clips(doc.track_by_id(8))[0]
    for name in ("Lead Vocals", "Drums"):
        c = doc.arrangement_clips(doc.find_track(name))[0]
        assert c.attrs["Time"] == m.attrs["Time"] == "2.5"
        for path in ("CurrentStart", "CurrentEnd", "Loop/LoopStart", "Loop/LoopEnd",
                     "Loop/HiddenLoopEnd", "Loop/StartRelative"):
            assert c.path(path).value() == m.path(path).value(), path
    assert len(diff["synced"]) == 2 and diff["marker_mismatch"] == []

    drift_doc = Doc(out)
    wm = drift_doc.arrangement_clips(drift_doc.find_track("Drums"))[0].child("WarpMarkers")
    first = wm.children()[1]
    drift_doc.set_attr(first, "SecTime", 9.99)
    drifted = drift_doc.apply().to_str()
    _, d2 = session.sync_to_master(drifted, "master", all_warped=True)
    assert d2["marker_mismatch"] == ["3-Drums"]
    fixed, d3 = session.sync_to_master(drifted, "master", all_warped=True, markers=True)
    assert d3["markers_copied"] is True
    _, d4 = session.sync_to_master(fixed, "master", all_warped=True)
    assert d4["marker_mismatch"] == []


def test_clone_track_remaps_automation_pointing_inside_the_clone():
    src = Doc(CHAIN).track_by_id(8)
    pointee = src.path("AutomationEnvelopes/Envelopes").find_all("PointeeId")[0].value()
    out = als.clone_track(CHAIN, 8, "copy", 5_000_000, id_offset=5_000_000)
    _ok(out)
    clone = Doc(out).track_by_id(5_000_000)
    new_pointee = clone.path("AutomationEnvelopes/Envelopes").find_all("PointeeId")[0].value()
    assert int(new_pointee) == int(pointee) + 5_000_000
    assert re.search(rf'<AutomationTarget Id="{new_pointee}"', out)


def test_group_clip_slot_lists_match_scene_count():
    xml = _add_returns_and_scenes(LIVE12, extra_returns=0, scenes=12)
    out, _ = session.group(xml, "G", ["master"])
    _ok(out)
    g = Doc(out).find_track("G")
    lists = g.find_all("ClipSlotList")
    assert lists and all(len(lst.children()) == 12 for lst in lists)


def test_group_end_walks_nested_groups_to_the_outermost_group():
    def t(tag, tid, name, gid):
        return (f'<{tag} Id="{tid}"><Name><EffectiveName Value="{name}" /></Name>'
                f'<TrackGroupId Value="{gid}" /></{tag}>')
    doc = Doc("<Ableton><LiveSet><Tracks>"
              + t("GroupTrack", 100, "G", -1) + t("GroupTrack", 101, "H", 100)
              + t("AudioTrack", 1, "h1", 101) + t("AudioTrack", 2, "h2", 101)
              + t("AudioTrack", 3, "g1", 100) + t("AudioTrack", 4, "x", -1)
              + "</Tracks></LiveSet></Ableton>")
    end = session._group_end
    assert doc.track_name(end(doc, doc.find_track("G"))) == "g1"
    assert doc.track_name(end(doc, doc.find_track("h1"))) == "g1"
    assert doc.track_name(end(doc, doc.find_track("H"))) == "g1"
    assert doc.track_name(end(doc, doc.find_track("x"))) == "x"
