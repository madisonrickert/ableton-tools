"""Regression tests for the Live 12 bugs (spec §1.2), on the sanitized Live 12.4 fixture."""

import json
import re

import numpy as np
import soundfile as sf
from conftest import FIXTURES

from ableton_tools import als, cli
from ableton_tools import import_stems as ist
from ableton_tools.alsxml import Doc
from ableton_tools.validate import validate

LIVE12 = (FIXTURES / "live12_set.xml").read_text(encoding="utf-8")


def _arr_clip(xml):
    doc = Doc(xml)
    return doc, doc.arrangement_clips(doc.track_by_id(8))[0]


def test_inspect_reports_live12_tempo():
    assert als.inspect_xml(LIVE12)["tempo"] == 136.0


def test_set_tempo_works_on_live12_main_track():
    out = als.set_tempo(LIVE12, 133.9)
    assert als.get_tempo(out) == 133.9
    assert validate(Doc(out))["ok"]


def test_warp_to_grid_sets_iswarped_on_live_formatting():
    xml = LIVE12.replace('<IsWarped Value="true" />', '<IsWarped Value="false" />')
    doc = Doc(xml)
    # Disambiguate: only the arrangement clip keeps the name "master".
    sess = doc.session_clips(doc.track_by_id(8))[0]
    doc.set_value(sess.child("Name"), "session-copy")
    xml = doc.apply().to_str()
    out, diff = als.warp_to_grid(xml, ["master"], bpm=136.0, durations={"master": 10.0})
    _, clip = _arr_clip(out)
    assert clip.child("IsWarped").value() == "true"
    assert len(clip.child("WarpMarkers").children()) == 2
    assert diff["warped"] == ["master"]


def test_move_clip_without_duration_preserves_length():
    doc, clip = _arr_clip(LIVE12)
    length = float(clip.child("CurrentEnd").value()) - float(clip.child("CurrentStart").value())
    out, diff = als.move_clip_to_beat(LIVE12, "master", 4.0)
    _, moved = _arr_clip(out)
    assert float(moved.child("CurrentStart").value()) == 4.0
    assert moved.attrs["Time"] == "4"
    assert abs(float(moved.child("CurrentEnd").value()) - (4.0 + length)) < 1e-9


def _stem_dir(project):
    d = project / "stems"
    d.mkdir()
    x = 0.01 * np.random.default_rng(1).standard_normal(96000).astype(np.float32)
    for name in ("0 Lead Vocals.wav", "1 Drums.wav"):
        sf.write(str(d / name), x, 48000)
    return sorted(d.glob("*.wav"))


def test_import_stems_keeps_scaleinformation_and_validates(live12_project):
    stems = _stem_dir(live12_project.parent)
    out, diff = ist.import_stems(LIVE12, "8", stems, live12_project.parent)
    doc = Doc(out)
    assert validate(doc)["ok"], validate(doc)["errors"]
    names = {n.value() for n in doc.nodes("Name")
             if n.parent is not None and n.parent.tag == "ScaleInformation"}
    assert names == {"0"}
    clips = [c for t in doc.tracks() for c in doc.arrangement_clips(t)]
    assert {c.child("Name").value() for c in clips} >= {"Lead Vocals", "Drums"}


def test_import_stems_clones_have_no_duplicate_session_clip(live12_project):
    stems = _stem_dir(live12_project.parent)
    out, _ = ist.import_stems(LIVE12, "8", stems, live12_project.parent)
    doc = Doc(out)
    master, *clones = [t for t in doc.tracks() if t.tag == "AudioTrack"]
    assert len(doc.session_clips(master)) == 1  # master untouched
    assert all(doc.session_clips(c) == [] for c in clones)
    out_keep, _ = ist.import_stems(LIVE12, "8", stems, live12_project.parent, keep_session=True)
    d2 = Doc(out_keep)
    assert all(len(d2.session_clips(t)) == 1 for t in d2.tracks() if t.tag == "AudioTrack")


def test_cli_master_track_resolves_live_renamed_name(live12_project, capsys):
    _stem_dir(live12_project.parent)
    rc = cli.main(["als", "import-stems", str(live12_project), "--master-track", "master",
                   "--stems", str(live12_project.parent / "stems"), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] and out["diff"]["master_track_id"] == "8"
    assert out["validation"]["ok"]


def test_cli_validate_command(live12_project, capsys):
    rc = cli.main(["als", "validate", str(live12_project), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["refs"]["missing_project"] == []


def test_inspect_reports_locations_warp_bpm_and_main():
    info = als.inspect_xml(LIVE12)
    assert info["main"]["name"] == "Main"
    assert [t["name"] for t in info["tracks"]] == ["1-master", "A-Reverb", "B-Delay"]
    master = info["tracks"][0]
    assert master["kind"] == "audio" and master["group_id"] is None
    assert master["output"] == "AudioOut/Main" and master["muted"] is False
    locs = sorted(c["location"] for c in info["clips"])
    assert locs == ["arrangement", "session"]
    arr = next(c for c in info["clips"] if c["location"] == "arrangement")
    assert arr["track"] == "1-master" and arr["relative_path_type"] == "3"
    assert arr["warp_marker_count"] == 4 and 100 < arr["warp_map_bpm"] < 160
    assert re.fullmatch(r"[\d.]+", str(arr["time"]))
