"""Dev-only: build engine/tests/fixtures/chain_src.xml, the device-transplant source set.

    python3 engine/scripts/build_chain_fixture.py

Starts from the sanitized Live 12 fixture (live12_set.xml) and gives track "1-master"
(Id 8) a realistic, schema-hard device chain assembled from real Live 12 sets:

  * a rack chain whose Compressor sidechain is routed from the track's OWN device output
    (self ref, `AudioIn/Track.<own id>/DeviceOut...`)
  * a Compressor2 sidechained from ANOTHER track (cross ref, `AudioIn/Track.14/PostFxOut`);
    track 14 ("2-source") is added so the ref resolves inside the fixture
  * a VST3 PluginDevice (plugin state replaced by a stub)
  * one project-relative (RelativePathType 3) file ref -> Samples/ir.wav
  * one track-level AutomationEnvelope whose PointeeId targets a param inside the chain

All inserted Ids are offset above the base document's max Id; NextPointeeId is bumped.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests/fixtures/live12_set.xml"
OUT = ROOT / "tests/fixtures/chain_src.xml"

RACK_SRC = ("/path/to/donor-rack/"
            "donor-rack.als", "120")
COMP_SRC = ("/path/to/donor-comp/"
            "donor-comp.als", "21")
VST3_SRC = ("/path/to/donor-vst3/"
            "donor-vst3.als", "45")
ENVELOPE = """<AutomationEnvelope Id="0">
\t\t\t\t\t\t\t<EnvelopeTarget>
\t\t\t\t\t\t\t\t<PointeeId Value="{pointee}" />
\t\t\t\t\t\t\t</EnvelopeTarget>
\t\t\t\t\t\t\t<Automation>
\t\t\t\t\t\t\t\t<Events>
\t\t\t\t\t\t\t\t\t<FloatEvent Id="1" Time="-63072000" Value="0.5" />
\t\t\t\t\t\t\t\t\t<FloatEvent Id="2" Time="16" Value="0.25" />
\t\t\t\t\t\t\t\t</Events>
\t\t\t\t\t\t\t\t<AutomationTransformViewState>
\t\t\t\t\t\t\t\t\t<IsTransformPending Value="false" />
\t\t\t\t\t\t\t\t\t<TimeAndValueTransforms />
\t\t\t\t\t\t\t\t</AutomationTransformViewState>
\t\t\t\t\t\t\t</Automation>
\t\t\t\t\t\t</AutomationEnvelope>"""


def track_block(xml: str, tid: str) -> str:
    m = re.search(rf'<(\w+Track) Id="{tid}"[^>]*>', xml)
    assert m, tid
    end = xml.find(f"</{m.group(1)}>", m.end())
    return xml[m.start(): end + len(m.group(1)) + 3]


def effects_inner(track: str) -> str:
    """Inner bytes of <track>/DeviceChain/DeviceChain/Devices (depth-aware)."""
    # Walk DeviceChain nesting: the track-level chain is the 2nd-level DeviceChain's Devices.
    depth = 0
    pos = 0
    tok = re.compile(r"<(/?)(DeviceChain|Devices)\b[^>]*?(/?)>")
    dc_depth = 0
    start = None
    for m in tok.finditer(track):
        closing, tag, selfclose = m.group(1), m.group(2), m.group(3)
        if tag == "DeviceChain":
            if selfclose:
                continue
            dc_depth += -1 if closing else 1
        elif tag == "Devices" and dc_depth == 2 and not closing and not selfclose and start is None:
            start = m.end()
            depth = 1
            pos = m.end()
            break
    assert start is not None, "no track-level Devices"
    for m in re.finditer(r"<(/?)Devices\b[^>]*?(/?)>", track[pos:]):
        if m.group(2):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return track[start: pos + m.start()]
    raise AssertionError("unbalanced Devices")


def top_level_device(inner: str, tag: str) -> str:
    m = re.search(rf"<{tag} Id=\"\d+\"[^>]*>", inner)
    assert m, tag
    depth = 0
    for t in re.finditer(rf"<(/?){tag}\b[^>]*?(/?)>", inner[m.start():]):
        if t.group(2):
            continue
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return inner[m.start(): m.start() + t.end()]
    raise AssertionError("unbalanced " + tag)


def load(path: str) -> str:
    return gzip.open(path, "rb").read().decode("utf-8")


def offset_ids(fragment: str, off: int) -> str:
    return re.sub(r'(?<=\s)Id="(\d+)"', lambda m: f'Id="{int(m.group(1)) + off}"', fragment)


def main() -> None:
    base = BASE.read_text(encoding="utf-8")
    base_max = max(int(i) for i in re.findall(r'(?<=\s)Id="(\d+)"', base))

    rack = effects_inner(track_block(load(RACK_SRC[0]), RACK_SRC[1]))
    rack = rack.replace(f"Track.{RACK_SRC[1]}/", "Track.8/")          # self ref -> our track
    comp = top_level_device(effects_inner(track_block(load(COMP_SRC[0]), COMP_SRC[1])),
                            "Compressor2")
    comp = re.sub(r"Track\.\d+/PostFxOut", "Track.14/PostFxOut", comp)   # cross ref -> track 14
    comp = re.sub(r'(Track\.14/PostFxOut" />\s*<UpperDisplayString Value=")[^"]*(")',
                  r"\g<1>2-source\g<2>", comp)
    vst3 = top_level_device(effects_inner(track_block(load(VST3_SRC[0]), VST3_SRC[1])),
                            "PluginDevice")
    # Stub plugin state blobs (long hex/base64 text content).
    vst3 = re.sub(r">([0-9A-Fa-f\s]{64,}|[A-Za-z0-9+/=\s]{256,})<", ">00<", vst3)

    chain = "\n".join([rack.strip("\n"), comp, vst3])
    # One project-relative file ref (RelativePathType 1 -> 3).
    chain = re.sub(r'<RelativePathType Value="1" />(\s*)<RelativePath Value="[^"]*" />'
                   r'(\s*)<Path Value="[^"]*" />',
                   r'<RelativePathType Value="3" />\1<RelativePath Value="Samples/ir.wav" />'
                   r'\2<Path Value="/Users/test/Project/Samples/ir.wav" />', chain, count=1)
    chain = re.sub(r"/Users/[^/\"]+/", "/Users/test/", chain)
    chain = re.sub(r"/Volumes/[^\"]*?/(?=[^/\"]*\")", "/Users/test/", chain)

    off = ((base_max // 100000) + 1) * 100000
    chain = offset_ids(chain, off)

    master = track_block(base, "8")
    first_target = re.search(r'<AutomationTarget Id="(\d+)"', chain).group(1)
    new_master = master.replace("<Devices />", "<Devices>\n" + chain + "\n</Devices>", 1)
    new_master = new_master.replace("<Envelopes />", "<Envelopes>\n"
                                    + ENVELOPE.format(pointee=first_target) + "\n</Envelopes>", 1)
    assert new_master != master

    # Track 14: a bare clone of the master (cross-ref sidechain source).
    src_track = offset_ids(master, off * 3)
    src_track = re.sub(r'(<AudioTrack Id=")\d+(")', r"\g<1>14\g<2>", src_track, count=1)
    src_track = re.sub(r'(<(?:EffectiveName|UserName) Value=")[^"]*(")', r"\g<1>2-source\g<2>",
                       src_track)
    src_track = re.sub(r"<Value>\s*<AudioClip\b.*?</AudioClip>\s*</Value>", "<Value />",
                       src_track, flags=re.DOTALL)
    src_track = re.sub(r"<Events>\s*<AudioClip\b.*?</AudioClip>\s*</Events>", "<Events />",
                       src_track, flags=re.DOTALL)

    out = base.replace(master, new_master + "\n\t\t\t" + src_track, 1)
    new_max = max(int(i) for i in re.findall(r'(?<=\s)Id="(\d+)"', out))
    out = re.sub(r'(<NextPointeeId Value=")\d+(")', rf"\g<1>{new_max + 1}\g<2>", out, count=1)
    leaks = re.findall(r"(?:/Volumes/)", out)
    assert not leaks, sorted(set(leaks))
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} ({len(out.encode())} bytes); chain targets first AutomationTarget "
          f"{first_target}")


if __name__ == "__main__":
    main()
