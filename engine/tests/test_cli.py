import json
import numpy as np
import soundfile as sf
from ableton_tools import cli


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
