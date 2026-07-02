import re

import pytest
import soundfile as sf
import numpy as np

from ableton_tools import als, import_stems as ist
from ableton_tools.errors import UsageError

# Master-track fixture with the full set of tags import-stems must repoint.
STEM_ALS = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="3" Creator="Ableton Live 11.3">
<LiveSet>
<NextPointeeId Value="100"/>
<Tracks>
<AudioTrack Id="14" SelectedToolPanel="3">
<Name><EffectiveName Value="1-Master"/><MemorizedFirstClipName Value="master_clip"/></Name>
<Color Value="5"/>
<DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events>
<AudioClip Id="1" Time="0">
<Name Value="master_clip"/>
<Color Value="5"/>
<CurrentStart Value="0"/>
<CurrentEnd Value="16"/>
<SampleRef><FileRef>
<RelativePath Value="Samples/Imported/master.wav"/>
<Path Value="/abs/Samples/Imported/master.wav"/>
<OriginalFileSize Value="123456"/>
<OriginalCrc Value="9999"/>
</FileRef></SampleRef>
<WarpMarkers>
<WarpMarker Id="0" SecTime="0" BeatTime="0"/>
<WarpMarker Id="2" SecTime="7.5" BeatTime="16"/>
</WarpMarkers>
<IsWarped Value="true"/>
<IsSongTempoLeader Value="true"/>
</AudioClip>
</Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain>
</AudioTrack>
</Tracks>
<MasterTrack><DeviceChain><Mixer><Tempo>
<Manual Value="120"/>
</Tempo></Mixer></DeviceChain></MasterTrack>
</LiveSet>
</Ableton>
"""


@pytest.fixture
def stem_project(tmp_path):
    """Project dir with master + two stems, all identical frames/samplerate."""
    sr = 8000
    x = (0.1 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
    d = tmp_path / "Samples" / "Imported"
    d.mkdir(parents=True)
    sf.write(str(d / "master.wav"), x, sr)
    stems = tmp_path / "suno-stems"
    stems.mkdir()
    sf.write(str(stems / "0 Lead Vocals.wav"), x, sr)
    sf.write(str(stems / "1 Drums.wav"), x, sr)
    return tmp_path, [stems / "0 Lead Vocals.wav", stems / "1 Drums.wav"]


def test_bare_label_strips_numeric_prefix():
    assert ist._bare_label("0 Lead Vocals") == "Lead Vocals"
    assert ist._bare_label("12 - Drums") == "Drums"
    assert ist._bare_label("Bass") == "Bass"


def test_color_lookup_exact_substring_default():
    assert ist._color_for("Lead Vocals") == 20
    assert ist._color_for("Synth Lead") == 14      # substring match on "synth"
    assert ist._color_for("Weird Noises") == ist.DEFAULT_COLOR
    assert ist._color_for("Drums", colors={"drums": 9}) == 9  # override wins


def test_import_stems_clones_repoints_and_demotes(stem_project):
    project_dir, stems = stem_project
    new_xml, diff = ist.import_stems(STEM_ALS, "14", stems, project_dir)
    info = als.inspect_xml(new_xml)
    names = [t["name"] for t in info["tracks"]]
    assert len(names) == 3 and names[0] == "1-Master"
    # Stems appear in filename order after the master
    assert "Lead Vocals" in names[1] and "Drums" in names[2]
    # SampleRefs repointed per stem
    assert 'RelativePath Value="suno-stems/0 Lead Vocals.wav"' in new_xml
    assert 'RelativePath Value="suno-stems/1 Drums.wav"' in new_xml
    # CRC reset so Live recomputes; file size updated
    assert new_xml.count('<OriginalCrc Value="0"') == 2
    # Only the master keeps the tempo lead
    assert new_xml.count('<IsSongTempoLeader Value="true"') == 1
    # Clip names are bare labels (gotcha: no numeric filename prefix)
    assert '<Name Value="Lead Vocals"' in new_xml
    assert '<Name Value="0 Lead Vocals"' not in new_xml
    # Colors follow the convention
    lead = next(s for s in diff["stems"] if s["label"] == "Lead Vocals")
    assert lead["color"] == 20
    # NextPointeeId still exceeds every Id
    npi = int(re.search(r'<NextPointeeId Value="(\d+)"', new_xml).group(1))
    assert npi > max(int(x) for x in re.findall(r'Id="(\d+)"', new_xml))


def test_import_stems_unknown_track_raises(stem_project):
    project_dir, stems = stem_project
    with pytest.raises(UsageError):
        ist.import_stems(STEM_ALS, "999", stems, project_dir)


def test_check_stem_invariants_flags_mismatch(stem_project, tmp_path):
    project_dir, stems = stem_project
    short = tmp_path / "short.wav"
    sf.write(str(short), np.zeros(100, dtype=np.float32), 8000)
    master = project_dir / "Samples" / "Imported" / "master.wav"
    problems = ist.check_stem_invariants(master, [stems[0], short])
    assert len(problems) == 1 and problems[0]["file"].endswith("short.wav")


def test_master_audio_path_resolves_from_xml(stem_project):
    project_dir, _ = stem_project
    p = ist.master_audio_path(STEM_ALS, "14", project_dir)
    assert p == project_dir / "Samples" / "Imported" / "master.wav"
