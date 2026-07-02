import re

import numpy as np
import pytest
import soundfile as sf
from conftest import STEM_ALS

from ableton_tools import als
from ableton_tools import import_stems as ist
from ableton_tools.errors import UsageError

# stem_project fixture lives in conftest.py (canonical home; also used by
# test_cli.py's import-stems tests).


def test_bare_label_strips_numeric_prefix():
    assert ist._bare_label("0 Lead Vocals") == "Lead Vocals"
    assert ist._bare_label("12 - Drums") == "Drums"
    assert ist._bare_label("Bass") == "Bass"


def test_color_lookup_exact_substring_default():
    assert ist._color_for("Lead Vocals") == 20
    assert ist._color_for("Synth Lead") == 14  # substring match on "synth"
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


def test_master_audio_path_raises_without_relative_path(stem_project):
    project_dir, _ = stem_project
    xml = re.sub(r"<RelativePath Value=\"[^\"]+\"/>\n?", "", STEM_ALS)
    assert "RelativePath" not in xml
    with pytest.raises(UsageError, match="RelativePath"):
        ist.master_audio_path(xml, "14", project_dir)


def test_import_stems_rejects_stem_outside_project_dir(stem_project, tmp_path_factory):
    """Documented in engine/CLAUDE.md: import-stems refuses a stem outside
    the project directory rather than repointing to it with a path escape.

    stem_project's `tmp_path` and this test's own `tmp_path` would be the
    *same* directory (fixture instances are cached per test), so a sibling
    of `tmp_path` is still inside `project_dir`; a fresh top-level temp dir
    from `tmp_path_factory` is required to land genuinely outside it."""
    project_dir, stems = stem_project
    outside_dir = tmp_path_factory.mktemp("not-the-project")
    outside_stem = outside_dir / stems[0].name
    outside_stem.write_bytes(stems[0].read_bytes())
    with pytest.raises(UsageError, match="outside the project directory"):
        ist.import_stems(STEM_ALS, "14", [outside_stem, stems[1]], project_dir)


def test_import_stems_does_not_touch_device_name_outside_audioclip(stem_project):
    """A device-bearing master track has its own bare <Name Value="..."> on
    a plugin/device descriptor, outside the <AudioClip> block. The clip-Name
    patch must be scoped to AudioClip sub-blocks only, so it must not
    silently overwrite the device's Name with the stem label."""
    project_dir, stems = stem_project
    xml = STEM_ALS.replace(
        "<DeviceChain><MainSequencer>",
        '<DeviceChain><Devices><PluginDevice>'
        '<Name Value="Some Plugin"/>'
        "</PluginDevice></Devices><MainSequencer>",
        1,
    )
    assert '<Name Value="Some Plugin"/>' in xml  # sanity: fixture built correctly

    new_xml, _diff = ist.import_stems(xml, "14", stems, project_dir)

    # The device descriptor's Name must survive untouched on every clone.
    assert new_xml.count('<Name Value="Some Plugin"/>') == 3  # master + 2 clones
    # The AudioClip clip Names must still become the bare stem labels.
    assert '<Name Value="Lead Vocals"' in new_xml
    assert '<Name Value="Drums"' in new_xml


def test_import_stems_orders_numeric_stems_naturally(stem_project, tmp_path_factory):
    """>=10 stems in a folder must sort numerically ('2 B' before '10 C'),
    not lexicographically ('10 C' before '2 B')."""
    project_dir, _ = stem_project
    import numpy as np
    import soundfile as sf

    sr = 8000
    x = (0.1 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
    stems_dir = project_dir / "suno-stems"
    names = ["1 A.wav", "2 B.wav", "10 C.wav"]
    stem_paths = []
    for name in names:
        p = stems_dir / name
        sf.write(str(p), x, sr)
        stem_paths.append(p)
    # Pass in lexicographic (scrambled) order to prove import_stems re-sorts.
    unordered = [stem_paths[2], stem_paths[0], stem_paths[1]]

    _new_xml, diff = ist.import_stems(STEM_ALS, "14", unordered, project_dir)

    labels = [s["label"] for s in diff["stems"]]
    assert labels == ["A", "B", "C"]
