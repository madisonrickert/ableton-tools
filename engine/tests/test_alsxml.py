import gzip
import os
from pathlib import Path

import pytest
from conftest import FIXTURES, MINIMAL_ALS

from ableton_tools.alsxml import Doc, offset_ids, set_next_pointee
from ableton_tools.errors import UsageError

LIVE12 = (FIXTURES / "live12_set.xml").read_bytes()
# Optional local-only check against a real Live 12 set you own (never committed).
REAL_SEED = Path(os.environ.get("ABLETON_TOOLS_REAL_SET", "/nonexistent"))


def _span(doc, node):
    return doc.data[node.start : node.end].decode()


def test_spans_are_exact_for_empty_nested_and_utf8_elements():
    doc = Doc('<A><B Value="é🦄" /><C>\n<D x="1"/></C></A>')
    by_tag = {n.tag: n for n in doc.nodes()}
    assert _span(doc, by_tag["B"]) == '<B Value="é🦄" />'
    assert _span(doc, by_tag["D"]) == '<D x="1"/>'
    assert _span(doc, by_tag["C"]) == '<C>\n<D x="1"/></C>'
    assert _span(doc, by_tag["A"]) == doc.data.decode()


def test_gt_inside_attribute_value_does_not_end_the_tag():
    doc = Doc('<A><B v="a>b"/><C/></A>')
    b = doc.nodes("B")[0]
    assert _span(doc, b) == '<B v="a>b"/>'
    assert doc.nodes("C")[0].parent.tag == "A"


def test_child_and_path_only_follow_direct_children():
    doc = Doc(LIVE12)
    track = doc.track_by_id(8)
    clip = doc.arrangement_clips(track)[0]
    assert clip.child("Name").value() == "master"
    # ScaleInformation/Name is a grandchild of the clip, never returned by child()
    assert clip.path("ScaleInformation/Name").value() == "0"
    assert clip.path("Name/ScaleInformation") is None


def test_noop_roundtrip_is_byte_identical():
    doc = Doc(LIVE12)
    assert doc.apply().data == LIVE12


@pytest.mark.skipif(not REAL_SEED.exists(), reason="set ABLETON_TOOLS_REAL_SET to a real .als")
def test_noop_roundtrip_is_byte_identical_on_real_set():
    with gzip.open(REAL_SEED, "rb") as fh:
        raw = fh.read()
    assert Doc(raw).apply().data == raw


def test_set_value_changes_only_that_value():
    doc = Doc(LIVE12)
    manual = doc.main_track().path("DeviceChain/Mixer/Tempo/Manual")
    doc.set_value(manual, "133.9")
    new = doc.apply()
    assert new.main_track().path("DeviceChain/Mixer/Tempo/Manual").value() == "133.9"
    tail = len(LIVE12) - manual.end
    assert new.data[: manual.start] == LIVE12[: manual.start]
    assert new.data[-tail:] == LIVE12[-tail:]
    assert new.data[manual.start : len(new.data) - tail] == b'<Manual Value="133.9" />'


def test_set_attr_rewrites_attribute_and_escapes():
    doc = Doc('<A><B Time="0" Name="x" /></A>')
    doc.set_attr(doc.nodes("B")[0], "Time", 1.5)
    doc.set_attr(doc.nodes("B")[0], "Name", 'a"&<b')
    assert doc.apply().data == b'<A><B Time="1.5" Name="a&quot;&amp;&lt;b" /></A>'


def test_overlapping_edits_raise():
    doc = Doc("<A><B/><C/></A>")
    a = doc.nodes("A")[0]
    doc.replace(doc.nodes("B")[0], "<X/>")
    doc.remove(a)
    with pytest.raises(ValueError):
        doc.apply()


def test_insertions_at_same_point_keep_submission_order():
    doc = Doc("<A><B/></A>")
    b = doc.nodes("B")[0]
    doc.insert_before(b, "<X/>")
    doc.insert_before(b, "<Y/>")
    assert doc.apply().data == b"<A><X/><Y/><B/></A>"


def test_offset_ids_only_touches_id_attributes():
    frag = b'<D Id="5"><ParameterId Value="5" /><W LomId="0" Id="7"/></D>'
    out = offset_ids(frag, 100)
    assert out == b'<D Id="105"><ParameterId Value="5" /><W LomId="0" Id="107"/></D>'


def test_max_id_id_base_and_next_pointee():
    doc = Doc('<A><NextPointeeId Value="3" /><B Id="12345"/><P LomId="99999"/></A>')
    assert doc.max_id() == 12345 and doc.id_base() == 20000
    assert set_next_pointee(doc).nodes("NextPointeeId")[0].value() == "12346"


def test_automation_event_ids_do_not_count_toward_next_pointee():
    # Live numbers envelope points in their own space; real sets have event
    # Ids far above NextPointeeId (e.g. FloatEvent 214973 vs NextPointeeId 25443).
    doc = Doc(
        '<A><NextPointeeId Value="3" /><B Id="12345"/>'
        '<Events><FloatEvent Id="99999" Time="0" Value="1" />'
        '<BoolEvent Id="12345" Time="1" Value="true" /></Events></A>'
    )
    assert doc.max_id() == 99999
    assert doc.max_pointee_id() == 12345  # B keeps 12345 even though an event shares it
    assert set_next_pointee(doc).nodes("NextPointeeId")[0].value() == "12346"


def test_main_track_live12_and_live11():
    assert Doc(LIVE12).main_track().tag == "MainTrack"
    assert Doc(MINIMAL_ALS).main_track().tag == "MasterTrack"


def test_main_track_missing_raises():
    with pytest.raises(UsageError):
        Doc("<Ableton><LiveSet><Tracks/></LiveSet></Ableton>").main_track()


def _named_tracks(*names):
    tracks = "".join(
        f'<AudioTrack Id="{i}"><Name><EffectiveName Value="{n}" /></Name></AudioTrack>'
        for i, n in enumerate(names, start=1)
    )
    return Doc(f"<Ableton><LiveSet><Tracks>{tracks}</Tracks></LiveSet></Ableton>")


def test_find_track_exact_and_live_index_prefix():
    doc = _named_tracks("4-WORD vocals", "A-Reverb")
    assert doc.track_name(doc.find_track("4-WORD vocals")) == "4-WORD vocals"
    assert doc.track_name(doc.find_track("WORD vocals")) == "4-WORD vocals"
    assert doc.track_name(doc.find_track("WORD")) == "4-WORD vocals"


def test_find_track_prefers_exact():
    doc = _named_tracks("1-Bass", "2-Bass FX")
    assert doc.track_name(doc.find_track("Bass")) == "1-Bass"


def test_find_track_tie_or_missing_raises():
    doc = _named_tracks("1-Bass A", "2-Bass B")
    with pytest.raises(UsageError):
        doc.find_track("Bass")
    with pytest.raises(UsageError):
        doc.find_track("Drums")


def test_freeze_sequencer_clips_ignored():
    clip = '<AudioClip Id="{}" Time="0"><Name Value="c" /></AudioClip>'
    xml = (
        '<Ableton><LiveSet><Tracks><AudioTrack Id="1"><Name><EffectiveName Value="1-a" /></Name>'
        "<DeviceChain><MainSequencer><Sample><ArrangerAutomation><Events>"
        + clip.format(1)
        + "</Events></ArrangerAutomation></Sample></MainSequencer>"
        "<FreezeSequencer><Sample><ArrangerAutomation><Events>"
        + clip.format(2)
        + "</Events></ArrangerAutomation></Sample></FreezeSequencer>"
        "</DeviceChain></AudioTrack></Tracks></LiveSet></Ableton>"
    )
    doc = Doc(xml)
    clips = doc.arrangement_clips(doc.track_by_id(1))
    assert [c.attrs["Id"] for c in clips] == ["1"]


def test_session_and_arrangement_clips_on_live12_fixture():
    doc = Doc(LIVE12)
    t = doc.track_by_id(8)
    assert len(doc.session_clips(t)) == 1
    assert len(doc.arrangement_clips(t)) == 1
    assert doc.effects_devices(t).tag == "Devices"


def test_tracks_lists_audio_and_return_tracks_in_order():
    doc = Doc(LIVE12)
    assert [doc.track_name(t) for t in doc.tracks()] == ["1-master", "A-Reverb", "B-Delay"]


def test_overlapping_edits_raise_a_structured_internal_error():
    from ableton_tools.errors import InternalError

    doc = Doc("<A><B/><C/></A>")
    doc.replace(doc.nodes("B")[0], "<X/>")
    doc.remove(doc.nodes("A")[0])
    with pytest.raises(InternalError) as e:
        doc.apply()
    assert e.value.kind == "internal" and "report" in (e.value.hint or "")


def test_offset_block_leaves_outside_pointers_that_collide_with_local_ids():
    from ableton_tools.alsxml import offset_block

    # PointeeId 3 points OUTSIDE (e.g. the song tempo's AutomationTarget 3); the
    # block's WarpMarker Id="3" is a local id that happens to share the number.
    block = (b'<AudioTrack Id="5"><WarpMarker Id="3" /><AutomationTarget Id="7" />'
             b'<PointeeId Value="3" /><PointeeId Value="7" /></AudioTrack>')
    out = offset_block(block, 100)
    assert b'<WarpMarker Id="103" />' in out and b'<AutomationTarget Id="107" />' in out
    assert b'<PointeeId Value="3" />' in out and b'<PointeeId Value="107" />' in out
