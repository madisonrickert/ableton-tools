import json
import numpy as np
import soundfile as sf
from ableton_tools import cli
from conftest import STEM_ALS


def test_manifest_lists_subcommands(capsys):
    rc = cli.main(["manifest", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    names = {c["name"] for c in data["subcommands"]}
    assert {"stem-verify", "tempo", "drift", "midi", "als"} <= names


def test_stem_verify_json(tmp_path, capsys):
    sr = 48000
    t = np.arange(sr) / sr
    a = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    b = (0.3 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    stems = tmp_path / "stems"
    stems.mkdir()
    sf.write(str(stems / "a.wav"), a, sr)
    sf.write(str(stems / "b.wav"), b, sr)
    master = tmp_path / "m.wav"
    sf.write(str(master), a + b, sr)
    rc = cli.main(["stem-verify", "--stems", str(stems), "--master", str(master),
                   "--win", "0.5", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["worst_db"] < -30


def test_als_inspect_json(als_file, capsys):
    rc = cli.main(["als", "inspect", str(als_file()), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tempo"] == 120.0


def test_als_rename_dry_run_does_not_write(als_file, capsys):
    p = als_file()
    before = p.read_bytes()
    manifest = p.parent / "renames.json"
    manifest.write_text(json.dumps({"Samples/Imported/bass.wav": "Samples/Imported/x.wav"}))
    rc = cli.main(["als", "rename", str(p), "--manifest", str(manifest), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert p.read_bytes() == before  # untouched without --commit


def test_unknown_subcommand_fails_loud(capsys):
    rc = cli.main(["frobnicate"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "manifest" in err.lower()


def test_missing_als_file_emits_structured_error(capsys):
    rc = cli.main(["als", "inspect", "/nonexistent/nope.als", "--json"])
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "error" in err and "hint" in err


def test_unknown_clip_emits_structured_error(als_file, capsys):
    p = als_file()
    rc = cli.main(["als", "move-clip", str(p), "--clip", "no_such_clip",
                   "--to-beat", "4", "--dur-s", "7.5", "--bpm", "120", "--json"])
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "no_such_clip" in err["error"]
    assert "inspect" in err["hint"]


def test_broken_manifest_json_emits_structured_error(als_file, tmp_path, capsys):
    p = als_file()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rc = cli.main(["als", "rename", str(p), "--manifest", str(bad), "--json"])
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "bad.json" in err["error"]


def test_als_import_stems_dry_run(als_file, stem_project, capsys):
    project_dir, stems = stem_project
    p = als_file(name="proj.als", xml=STEM_ALS)
    # relocate the .als into the project dir so relative paths resolve
    target = project_dir / "proj.als"
    target.write_bytes(p.read_bytes())
    before = target.read_bytes()
    rc = cli.main(["als", "import-stems", str(target),
                   "--master-track", "14", "--stems", str(project_dir / "suno-stems"),
                   "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert len(out["diff"]["stems"]) == 2
    assert target.read_bytes() == before  # nothing written


def test_als_import_stems_rejects_mismatched_stems(als_file, stem_project, capsys):
    import numpy as np
    import soundfile as sf
    project_dir, stems = stem_project
    sf.write(str(project_dir / "suno-stems" / "2 Bass.wav"),
             np.zeros(50, dtype=np.float32), 8000)  # wrong length
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p2.als", xml=STEM_ALS).read_bytes())
    rc = cli.main(["als", "import-stems", str(target),
                   "--master-track", "14", "--stems", str(project_dir / "suno-stems"),
                   "--json"])
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "2 Bass.wav" in err["error"] or "2 Bass.wav" in (err["hint"] or "")
