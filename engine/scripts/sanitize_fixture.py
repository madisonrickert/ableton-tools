"""Dev-only: derive the Live 12 test fixture from a real Live 12.4 set.

    uv run --project engine python engine/scripts/sanitize_fixture.py SRC.als \
        engine/tests/fixtures/live12_set.xml

Set FIXTURE_LEAK_TERMS="name1,name2" to fail if any client/project name survives.
Strips user paths and names, repoints the one sample to `Samples/master.wav`
(project-relative, RelativePathType 3), and trims each clip's warp map to four
markers so the fixture stays small. Everything structural that Live 12 writes
(MainTrack Tempo with LomId, ScaleInformation, Session + Arrangement clips,
return-track device refs of types 1/5/7, scenes, NextPointeeId) is kept as-is.
"""

from __future__ import annotations

import gzip
import os
import re
import sys
from pathlib import Path


def sanitize(xml: str) -> str:
    # The one sample the seed references -> a project-relative stub.
    xml = re.sub(r'(<RelativePath Value=")[^"]*\.(?:mp3|wav|aif|aiff)(")',
                 r"\g<1>Samples/master.wav\g<2>", xml)
    xml = re.sub(r'(<Path Value=")/[^"]*\.(?:mp3|wav|aif|aiff)(")',
                 r"\g<1>/Users/test/Project/Samples/master.wav\g<2>", xml)
    # Browser hints that spell out the sample's project path.
    xml = re.sub(r'(<BrowserContentPath Value="query:CurrentProject#)'
                 r'[^"]*\.(?:mp3|wav|aif|aiff)(")',
                 r"\g<1>Samples:master.wav\g<2>", xml)
    # Any remaining absolute user / volume paths.
    xml = re.sub(r"/Users/[^/\"]+/", "/Users/test/", xml)
    xml = re.sub(r"/Volumes/[^\"]*?/(?=[^/\"]*\")", "/Users/test/", xml)
    xml = xml.replace("Users/nsh/", "Users/test/")
    # Names.
    xml = re.sub(r'(<(?:EffectiveName|UserName) Value=")1-[^"]*(")', r"\g<1>1-master\g<2>", xml)
    xml = re.sub(r'(<MemorizedFirstClipName Value=")[^"]+(")', r"\g<1>master\g<2>", xml)
    xml = re.sub(r'(<AudioClip Id="\d+" Time="[^"]*">\s*<LomId Value="0" />\s*'
                 r'<LomIdView Value="0" />\s*<CurrentStart Value="[^"]*" />\s*'
                 r'<CurrentEnd Value="[^"]*" />\s*<Loop>.*?</Loop>\s*<Name Value=")[^"]*(")',
                 r"\g<1>master\g<2>", xml, flags=re.DOTALL)
    xml = re.sub(r'(<OriginalCrc Value=")\d+(")', r"\g<1>0\g<2>", xml)

    # Trim each warp map to markers 0,1,2 and the last one.
    def trim(m: re.Match[str]) -> str:
        markers = re.findall(r"[ \t]*<WarpMarker [^>]*/>\n", m.group(2))
        if len(markers) <= 4:
            return m.group(0)
        keep = markers[:3] + markers[-1:]
        return m.group(1) + "".join(keep) + m.group(3)

    xml = re.sub(r"(<WarpMarkers>\n)(.*?)([ \t]*</WarpMarkers>)", trim, xml, flags=re.DOTALL)
    return xml


def main() -> None:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    with gzip.open(src, "rb") as fh:
        xml = fh.read().decode("utf-8")
    out = sanitize(xml)
    extra = [re.escape(t.strip()) for t in os.environ.get("FIXTURE_LEAK_TERMS", "").split(",")
             if t.strip()]
    leaks = re.findall("|".join([r"/Volumes/", r"/Users/(?!test/)"] + extra), out)
    if leaks:
        raise SystemExit(f"sanitize left identifying strings: {sorted(set(leaks))}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out, encoding="utf-8")
    print(f"wrote {dst} ({len(out.encode())} bytes)")


if __name__ == "__main__":
    main()
