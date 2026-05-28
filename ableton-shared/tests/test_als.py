import gzip
from ableton_tools import als


def test_read_write_roundtrip(als_file):
    p = als_file()
    xml = als.read_als(str(p))
    assert "<Ableton" in xml
    out = p.parent / "out.als"
    als.write_als(str(out), xml)
    assert als.read_als(str(out)) == xml


def test_inspect_reports_tempo_tracks_clips(als_file):
    p = als_file()
    info = als.inspect(str(p))
    assert info["tempo"] == 120.0
    assert any(t["name"] == "Bass" for t in info["tracks"])
    clip = info["clips"][0]
    assert clip["name"] == "bass_clip"
    assert clip["relative_path"] == "Samples/Imported/bass.wav"


def test_set_tempo_changes_value(als_file):
    xml = als.read_als(str(als_file()))
    out = als.set_tempo(xml, 134.0)
    assert 'Manual Value="134' in out
    assert als.inspect_xml(out)["tempo"] == 134.0


def test_rename_refs_updates_paths_and_reports_diff(als_file):
    xml = als.read_als(str(als_file()))
    mapping = {"Samples/Imported/bass.wav": "Samples/Imported/bass_renamed.wav"}
    out, diff = als.rename_refs(xml, mapping)
    assert "bass_renamed.wav" in out
    assert diff["changed"] == 1


def test_move_clip_to_beat_updates_start(als_file):
    xml = als.read_als(str(als_file()))
    out, diff = als.move_clip_to_beat(xml, "bass_clip", beat=8.0, dur_s=7.5, bpm=120.0)
    info = als.inspect_xml(out)
    assert info["clips"][0]["current_start"] == 8.0
    assert diff["clip"] == "bass_clip"


def test_warp_to_grid_sets_two_markers(als_file):
    xml = als.read_als(str(als_file()))
    out, diff = als.warp_to_grid(xml, ["bass_clip"], bpm=120.0, durations={"bass_clip": 8.0})
    assert 'IsWarped Value="true"' in out
    assert diff["warped"] == ["bass_clip"]


def test_verify_refs_flags_missing(als_file, tmp_path):
    xml = als.read_als(str(als_file()))
    missing = als.verify_refs(xml, base_dir=str(tmp_path))
    assert "Samples/Imported/bass.wav" in missing


def test_backup_writes_timestamped_copy(als_file):
    p = als_file()
    b = als.backup(str(p), op="test")
    assert "backup-pre-test" in b
    assert gzip.open(b, "rb").read() == gzip.open(str(p), "rb").read()
