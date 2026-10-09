import os
import re
from pathlib import Path

import pytest
from conftest import FIXTURES

from ableton_tools.alsxml import Doc
from ableton_tools.validate import ref_report, validate

LIVE12 = (FIXTURES / "live12_set.xml").read_text(encoding="utf-8")
# Optional local-only check against a real Live-saved set (never committed).
REAL_BUILT = Path(os.environ.get("ABLETON_TOOLS_REAL_SET", "/nonexistent"))


def test_fixture_validates_ok():
    report = validate(Doc(LIVE12))
    assert report["ok"], report["errors"]


@pytest.mark.skipif(not REAL_BUILT.exists(), reason="set ABLETON_TOOLS_REAL_SET to a real .als")
def test_real_live_saved_set_validates_ok():
    report = validate(Doc.read(REAL_BUILT))
    assert report["ok"], report["errors"][:5]


def test_malformed_xml_is_an_error_not_an_exception():
    report = validate(Doc("<A><B></A>"))
    assert not report["ok"] and "well-formed" in report["errors"][0]


def test_duplicate_track_id_fails():
    xml = LIVE12.replace('<ReturnTrack Id="2"', '<ReturnTrack Id="8"', 1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("track Id 8" in e for e in report["errors"])


def test_scaleinformation_name_must_stay_numeric():
    xml = re.sub(r'(<ScaleInformation>\s*<Root Value="0" />\s*<Name Value=")0(")',
                 r"\g<1>WORD vocals\g<2>", LIVE12, count=1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("ScaleInformation/Name" in e for e in report["errors"])


def test_non_numeric_int_node_fails():
    xml = LIVE12.replace('<CurrentStart Value="0" />', '<CurrentStart Value="abc" />', 1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("CurrentStart" in e for e in report["errors"])


def test_dangling_track_group_id_fails():
    xml = LIVE12.replace('<TrackGroupId Value="-1" />', '<TrackGroupId Value="4242" />', 1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("4242" in e for e in report["errors"])


def test_next_pointee_id_too_low_fails():
    xml = re.sub(r'(<NextPointeeId Value=")\d+(")', r"\g<1>5\g<2>", LIVE12, count=1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("NextPointeeId" in e for e in report["errors"])


def test_automation_event_ids_above_next_pointee_are_valid():
    npi = int(re.search(r'<NextPointeeId Value="(\d+)"', LIVE12).group(1))
    xml = LIVE12.replace(
        "<Events>", f'<Events><FloatEvent Id="{npi * 10}" Time="0" Value="120" />', 1
    )
    assert xml != LIVE12
    report = validate(Doc(xml))
    assert not any("NextPointeeId" in e for e in report["errors"])


def test_duplicate_automation_target_id_fails():
    first = re.search(r'<AutomationTarget Id="(\d+)"', LIVE12).group(1)
    second = re.findall(r'<AutomationTarget Id="(\d+)"', LIVE12)[1]
    xml = LIVE12.replace(f'<AutomationTarget Id="{second}"', f'<AutomationTarget Id="{first}"', 1)
    report = validate(Doc(xml))
    assert not report["ok"] and any("AutomationTarget" in e for e in report["errors"])


def test_grouped_track_not_routed_to_group_is_a_warning():
    xml = (
        '<Ableton><LiveSet><NextPointeeId Value="100" /><Tracks>'
        '<GroupTrack Id="5"><Name><EffectiveName Value="G" /></Name>'
        '<TrackGroupId Value="-1" /></GroupTrack>'
        '<AudioTrack Id="6"><Name><EffectiveName Value="1-a" /></Name>'
        '<TrackGroupId Value="5" /><DeviceChain><AudioOutputRouting>'
        '<Target Value="AudioOut/Main" /></AudioOutputRouting></DeviceChain></AudioTrack>'
        "</Tracks><MainTrack /></LiveSet></Ableton>"
    )
    report = validate(Doc(xml))
    assert report["ok"]
    assert any("1-a" in w and "AudioOut/GroupTrack" in w for w in report["warnings"])


def test_ref_report_classifies_by_relative_path_type(live12_project):
    report = ref_report(Doc.read(live12_project), live12_project.parent)
    assert report["missing_project"] == []           # Samples/master.wav exists
    assert "/Reverb Default.adv" in report["missing_external"]  # type 1: warn only
    assert report["library"] >= 1                     # type 5 (Core Library)


def test_ref_report_flags_missing_project_sample(live12_project):
    (live12_project.parent / "Samples" / "master.wav").unlink()
    report = ref_report(Doc.read(live12_project), live12_project.parent)
    assert report["missing_project"] == ["Samples/master.wav"]


def test_ref_without_relative_path_type_is_treated_as_project(tmp_path):
    xml = ('<A><SampleRef><FileRef><RelativePath Value="Samples/x.wav" />'
           '<Path Value="/abs/x.wav" /></FileRef></SampleRef></A>')
    assert ref_report(Doc(xml), tmp_path)["missing_project"] == ["Samples/x.wav"]


def test_device_route_to_a_missing_device_id_is_a_warning():
    from ableton_tools.validate import dangling_device_routes

    xml = (FIXTURES / "chain_src.xml").read_text(encoding="utf-8")
    doc = Doc(xml)
    (route,) = {n.value() for n in doc.track_by_id(8).find_all("Target")
                if "Track.8/Device" in (n.value() or "")}
    broken = xml.replace(route, "AudioIn/Track.8/DeviceOut.999.B0,ChainOut")
    assert dangling_device_routes(Doc(broken)) == [
        "AudioIn/Track.8/DeviceOut.999.B0,ChainOut (track 8 has no device Id 999)"]
    report = validate(Doc(broken))
    assert report["ok"] and any("DeviceOut.999" in w for w in report["warnings"])
