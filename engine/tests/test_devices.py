import re

import pytest
from conftest import FIXTURES

from ableton_tools import devices, session
from ableton_tools.alsxml import Doc
from ableton_tools.errors import UsageError
from ableton_tools.validate import dangling_device_routes, validate

LIVE12 = (FIXTURES / "live12_set.xml").read_text(encoding="utf-8")
CHAIN = (FIXTURES / "chain_src.xml").read_text(encoding="utf-8")


def _ok(xml):
    r = validate(Doc(xml))
    assert r["ok"], r["errors"][:3]


def _chain(xml, track=None, main=False):
    doc = Doc(xml)
    t = doc.main_track() if main else doc.find_track(track)
    devs = doc.effects_devices(t)
    kids = devs.children()
    return doc, t, (doc.data[kids[0].start : kids[-1].end] if kids else b"")


def _norm_ids(b):
    return re.sub(rb'(?<=\s)Id="\d+"', b'Id="N"', b)


def _target_with_sax():
    xml, diff = session.add_track(LIVE12, "SAX", after="master")
    return xml, diff["track_id"]


def test_transplant_preserves_chain_bytes_except_ids_and_validates():
    target, sax_id = _target_with_sax()
    out, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    _ok(out)
    _, _, src_chain = _chain(CHAIN, "master")
    _, t, new_chain = _chain(out, "SAX")
    assert [d.tag for d in Doc(out).effects_devices(t).children()] == diff["devices"]
    assert diff["devices"][:4] == ["Gate", "Saturator", "Compressor2", "AudioEffectGroupDevice"]
    # Only Ids and the rewritten routing targets may differ.
    def strip(b):  # ids, and the route numbers that name ids, move together
        b = re.sub(rb'(Device(?:In|Out)\.)\d+\.([BR])\d+', rb"\1N.\2N", _norm_ids(b))
        return re.sub(rb'Track\.\d+/', b"Track.X/", b)

    src_n, new_n = strip(src_chain), strip(new_chain)
    src_n = src_n.replace(b'"AudioIn/Track.X/PostFxOut"', b'"AudioIn/None"')
    type3 = (rb'<RelativePath Value="Samples/(?:Imported/)?ir\.wav" />\s*'
             rb'<Path Value="[^"]*ir\.wav" />')
    new_n, src_n = re.sub(type3, b"<TYPE3/>", new_n), re.sub(type3, b"<TYPE3/>", src_n)
    shown = rb'(<(?:Upper|Lower)DisplayString Value=")[^"]*(")'  # cosmetic; Live recomputes
    new_n, src_n = re.sub(shown, rb"\1\2", new_n), re.sub(shown, rb"\1\2", src_n)
    assert new_n == src_n
    old_max = Doc(target).max_id()
    new_ids = [int(i) for i in re.findall(rb'(?<=\s)Id="(\d+)"', new_chain)]
    assert min(new_ids) > old_max


def test_parameter_ids_untouched():
    target, _ = _target_with_sax()
    out, _ = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    _, _, src_chain = _chain(CHAIN, "master")
    _, _, new_chain = _chain(out, "SAX")
    pid = rb'<ParameterId Value="(-?\d+)"'
    assert re.findall(pid, src_chain) == re.findall(pid, new_chain)


def test_self_routing_follows_the_chain_and_cross_routing_resets():
    target, sax_id = _target_with_sax()
    out, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    doc, sax, new_chain = _chain(out, "SAX")
    (rack,) = [d for d in doc.effects_devices(sax).children()
               if d.tag == "AudioEffectGroupDevice"]
    branch = rack.child("Branches").children()[0]
    route = f"AudioIn/Track.{sax_id}/DeviceOut.{rack.attrs['Id']}.B{branch.attrs['Id']},ChainOut"
    assert route.encode() in new_chain
    assert b"Track.14/" not in new_chain and b"Track.8/" not in new_chain
    assert re.search(rb'"AudioIn/None" />\s*<UpperDisplayString Value="No Output" />'
                     rb'\s*<LowerDisplayString Value="" />', new_chain)
    assert diff["routing_self_remapped"] and diff["routing_reset"]


def test_map_track_remaps_cross_routing_to_target_track_id():
    target, _ = _target_with_sax()
    out, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX",
                                   map_track={"source": "A-Reverb"})
    _, _, new_chain = _chain(out, "SAX")
    assert b"AudioIn/Track.2/PostFxOut" in new_chain  # A-Reverb is Id 2 in the target
    assert diff["routing_mapped"] and not diff["routing_reset"]
    _ok(out)


def test_automation_dropped_by_default_and_copied_on_request():
    target, _ = _target_with_sax()
    _, d1 = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    assert d1["automation_dropped"] == 1 and d1["automation_copied"] == 0
    out, d2 = devices.transplant(target, CHAIN, src_track="master", to_track="SAX",
                                 with_automation=True)
    _ok(out)
    assert d2["automation_copied"] == 1
    doc = Doc(out)
    sax = doc.find_track("SAX")
    (pointee,) = [n.value() for n in sax.find_all("PointeeId")]
    assert re.search(rf'<AutomationTarget Id="{pointee}"'.encode(), doc.effects_devices(sax)
                     .text(doc))


def test_type3_ref_is_planned_for_copy_and_repointed(tmp_path):
    target, _ = _target_with_sax()
    out, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX",
                                   target_dir=tmp_path / "proj", source_dir=tmp_path / "src")
    assert diff["files_copied"] == [{"from": str(tmp_path / "src" / "Samples/ir.wav"),
                                     "to": str(tmp_path / "proj" / "Samples/Imported/ir.wav"),
                                     "existing": False}]
    assert b'<RelativePath Value="Samples/Imported/ir.wav" />' in _chain(out, "SAX")[2]


def test_transplant_to_main_track():
    out, diff = devices.transplant(LIVE12, CHAIN, src_track="master", to_main=True)
    _ok(out)
    doc = Doc(out)
    assert len(doc.effects_devices(doc.main_track()).children()) == len(diff["devices"])
    assert b"Track.8/" not in _chain(out, main=True)[2]  # self refs reset: Main has no Id


def test_transplant_append_nonempty():
    target, sax_id = _target_with_sax()
    once, d1 = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    twice, d2 = devices.transplant(once, CHAIN, src_track="master", to_track="SAX",
                                   mode="append")
    _ok(twice)
    doc = Doc(twice)
    n = len(d1["devices"])
    assert len(doc.effects_devices(doc.find_track("SAX")).children()) == 2 * n
    chain = _chain(twice, "SAX")[2]
    assert chain.count(f"Track.{sax_id}/DeviceOut.".encode()) == 2
    assert dangling_device_routes(doc) == []  # both copies route to their own rack


def test_self_routes_follow_the_transplanted_device_ids():
    target, sax_id = _target_with_sax()
    out, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    doc = Doc(out)
    assert diff["routing_self_remapped"]
    assert all(r["to"].startswith(f"AudioIn/Track.{sax_id}/DeviceOut.")
               for r in diff["routing_self_remapped"])
    assert dangling_device_routes(doc) == []


def test_plugins_are_reported():
    target, _ = _target_with_sax()
    _, diff = devices.transplant(target, CHAIN, src_track="master", to_track="SAX")
    assert {"name": "Ozone Imager 2", "format": "VST3"}.items() <= diff["plugins"][0].items()


def test_empty_source_chain_raises():
    with pytest.raises(UsageError, match="no devices"):
        devices.transplant(LIVE12, CHAIN, src_track="source", to_track="master")


def test_replace_drops_target_automation_of_replaced_devices():
    target, _ = _target_with_sax()
    automated, _ = devices.transplant(target, CHAIN, src_track="master", to_track="SAX",
                                      with_automation=True)
    out, diff = devices.transplant(automated, CHAIN, src_track="master", to_track="SAX")
    _ok(out)
    assert diff["target_automation_removed"] == 1
    doc = Doc(out)
    sax = doc.find_track("SAX")
    targets = {n.attrs["Id"] for n in doc.nodes() if n.tag.endswith("Target") and "Id" in n.attrs}
    pointees = [n.value() for n in sax.path("AutomationEnvelopes/Envelopes").find_all("PointeeId")]
    assert all(p in targets for p in pointees)
