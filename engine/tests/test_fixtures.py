import gzip
import re
import xml.etree.ElementTree as ET


def test_live12_project_fixture_is_a_real_live12_shape(live12_project):
    xml = gzip.open(live12_project, "rb").read().decode()
    root = ET.fromstring(xml)
    assert root.get("MinorVersion", "").startswith("12.")
    assert root.find(".//MainTrack/DeviceChain/Mixer/Tempo/LomId") is not None
    assert len(root.findall(".//AudioClip/ScaleInformation/Name")) >= 2
    assert re.search(r'<RelativePathType Value="3" />\s*<RelativePath Value="Samples/master.wav"', xml)
    assert (live12_project.parent / "Samples" / "master.wav").exists()


def test_chain_src_fixture_has_rack_routing_plugin_and_automation(chain_src_als):
    xml = gzip.open(chain_src_als, "rb").read().decode()
    root = ET.fromstring(xml)
    devs = root.find(".//AudioTrack[@Id='8']/DeviceChain/DeviceChain/Devices")
    tags = [d.tag for d in devs]
    assert "AudioEffectGroupDevice" in tags and "PluginDevice" in tags
    assert "AudioIn/Track.8/DeviceOut" in xml and "AudioIn/Track.14/PostFxOut" in xml
    assert '<RelativePathType Value="3" />' in xml
    assert (chain_src_als.parent / "Samples" / "ir.wav").exists()


def test_both_project_fixtures_coexist_in_one_test(live12_project, chain_src_als):
    assert live12_project.parent != chain_src_als.parent
    assert live12_project.exists() and chain_src_als.exists()
