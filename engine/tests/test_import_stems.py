import re

import pytest
import soundfile as sf
import numpy as np

from ableton_tools import als, import_stems as ist
from ableton_tools.errors import UsageError
from conftest import STEM_ALS

# stem_project fixture lives in conftest.py (canonical home; also used by
# test_cli.py's import-stems tests).


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
