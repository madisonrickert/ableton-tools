import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from conftest import STEM_ALS

from ableton_tools import als, cli


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
    rc = cli.main(
        ["stem-verify", "--stems", str(stems), "--master", str(master), "--win", "0.5", "--json"]
    )
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
    rc = cli.main(
        [
            "als",
            "move-clip",
            str(p),
            "--clip",
            "no_such_clip",
            "--to-beat",
            "4",
            "--dur-s",
            "7.5",
            "--bpm",
            "120",
            "--json",
        ]
    )
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
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "14",
            "--stems",
            str(project_dir / "suno-stems"),
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert len(out["diff"]["stems"]) == 2
    assert target.read_bytes() == before  # nothing written


def test_als_import_stems_rejects_mismatched_stems(als_file, stem_project, capsys):
    import numpy as np
    import soundfile as sf

    project_dir, stems = stem_project
    sf.write(
        str(project_dir / "suno-stems" / "2 Bass.wav"), np.zeros(50, dtype=np.float32), 8000
    )  # wrong length
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p2.als", xml=STEM_ALS).read_bytes())
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "14",
            "--stems",
            str(project_dir / "suno-stems"),
            "--json",
        ]
    )
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "2 Bass.wav" in err["error"] or "2 Bass.wav" in (err["hint"] or "")


def test_manifest_includes_nested_subcommands_and_args(capsys):
    rc = cli.main(["manifest", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    als_entry = next(c for c in data["subcommands"] if c["name"] == "als")
    subs = {s["name"] for s in als_entry["subcommands"]}
    assert {
        "inspect",
        "rename",
        "move",
        "warp-to-grid",
        "move-clip",
        "snap",
        "import-stems",
    } <= subs
    ims = next(s for s in als_entry["subcommands"] if s["name"] == "import-stems")
    argnames = {a["name"] for a in ims["args"]}
    assert {"--master-track", "--stems", "--commit"} <= argnames


def test_global_json_flag_position(als_file, capsys):
    rc = cli.main(["--json", "als", "inspect", str(als_file())])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["tempo"] == 120.0


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["--version"])
    assert ex.value.code == 0
    assert "0.2" in capsys.readouterr().out


def test_help_subcommand(capsys):
    rc = cli.main(["help"])
    assert rc == 0
    assert "manifest" in capsys.readouterr().out


def test_help_subcommand_with_name_shows_subhelp(capsys):
    with pytest.raises(SystemExit) as ex:
        cli.main(["help", "als"])
    assert ex.value.code == 0
    assert "als" in capsys.readouterr().out.lower()


def test_cmd_tempo_json(click_wav, capsys):
    p = click_wav(bpm=120.0, bars=8)
    rc = cli.main(["tempo", str(p), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert abs(out["bpm"] - 120.0) < 5.0
    assert "precise_bpm" in out and "bpm_drift_total" in out


def test_cmd_drift_json(tmp_path, capsys):
    sr = 48000
    t = np.arange(sr * 2) / sr
    a = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    stems = tmp_path / "stems"
    stems.mkdir()
    sf.write(str(stems / "a.wav"), a, sr)
    master = tmp_path / "m.wav"
    sf.write(str(master), a, sr)
    rc = cli.main(
        ["drift", "--master", str(master), "--stems", str(stems), "--win", "0.5", "--json"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stem_files"] == ["a.wav"]
    assert "total_drift_ms" in out
    assert len(out["windows"]) >= 2


def test_cmd_midi_compare_json(midi_file, capsys):
    a = midi_file(name="a.mid", notes=[(0.0, 60, 0.4), (0.5, 64, 0.4)])
    b = midi_file(name="b.mid", notes=[(0.0, 60, 0.4), (0.5, 64, 0.4)])
    rc = cli.main(["midi", "compare", str(a), str(b), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pairs"][0]["chroma_cosine"] > 0.99


def test_cmd_midi_transcribe_json(tmp_path, tone_wav, monkeypatch, capsys):
    """basic-pitch's own body is skipped (heavy on-demand dependency, tested
    in test_transcribe.py); this covers the CLI's argument-handling/dispatch
    via the same sys.modules fake used there."""
    captured = {}

    def fake_predict_and_save(
        audio_paths,
        output_directory,
        save_midi,
        sonify_midi,
        save_model_outputs,
        save_notes,
        model_or_model_path,
        onset_threshold,
        frame_threshold,
        minimum_note_length,
        **kw,
    ):
        captured["out"] = str(output_directory)
        stem = Path(audio_paths[0]).stem
        (Path(output_directory) / f"{stem}_basic_pitch.mid").write_bytes(b"MThd")

    fake_inference = types.ModuleType("basic_pitch.inference")
    fake_inference.predict_and_save = fake_predict_and_save
    fake_pkg = types.ModuleType("basic_pitch")
    fake_pkg.ICASSP_2022_MODEL_PATH = "fake-model"
    monkeypatch.setitem(sys.modules, "basic_pitch", fake_pkg)
    monkeypatch.setitem(sys.modules, "basic_pitch.inference", fake_inference)

    audio_path = tone_wav(name="sax.wav", dur_s=0.5)
    out_mid = tmp_path / "sax.mid"
    rc = cli.main(["midi", "transcribe", str(audio_path), "--out", str(out_mid), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output"] == str(out_mid)
    assert out_mid.exists()


def test_als_inspect_human_output(als_file, capsys):
    rc = cli.main(["als", "inspect", str(als_file())])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tempo=120.0" in out


def test_manifest_file_not_found_emits_structured_error(als_file, capsys):
    p = als_file()
    rc = cli.main(
        ["als", "rename", str(p), "--manifest", str(p.parent / "nope.json"), "--json"]
    )
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "not found" in err["error"].lower()


def test_missing_als_file_emits_plain_error_without_json(capsys):
    rc = cli.main(["als", "inspect", "/nonexistent/nope.als"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "error:" in err
    assert "check the file path" in err


def test_broken_manifest_plain_error_without_json(als_file, tmp_path, capsys):
    p = als_file()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rc = cli.main(["als", "rename", str(p), "--manifest", str(bad)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "hint:" in err


def test_version_flag_falls_back_when_package_metadata_missing(monkeypatch, capsys):
    import importlib.metadata as im

    def raise_not_found(name):
        raise im.PackageNotFoundError(name)

    monkeypatch.setattr(im, "version", raise_not_found)
    with pytest.raises(SystemExit) as ex:
        cli.main(["--version"])
    assert ex.value.code == 0
    assert "unknown" in capsys.readouterr().out


def test_als_rename_commit_writes_backup_and_file(als_file, tmp_path, capsys):
    p = als_file()
    target_dir = tmp_path / "Samples" / "Imported"
    target_dir.mkdir(parents=True)
    (target_dir / "bass_renamed.wav").write_bytes(b"RIFF")
    manifest = p.parent / "renames.json"
    manifest.write_text(
        json.dumps({"Samples/Imported/bass.wav": "Samples/Imported/bass_renamed.wav"})
    )
    rc = cli.main(["als", "rename", str(p), "--manifest", str(manifest), "--commit", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["committed"] is True
    assert Path(out["backup"]).exists()
    new_xml = als.read_als(str(p))
    assert "bass_renamed.wav" in new_xml


def test_als_rename_commit_restores_on_broken_refs(als_file, tmp_path, capsys):
    p = als_file()
    manifest = p.parent / "renames.json"
    manifest.write_text(
        json.dumps({"Samples/Imported/bass.wav": "Samples/Imported/missing.wav"})
    )
    # als.write_als's gzip output embeds the write-time mtime, so a faithful
    # restore does not reproduce the original bytes; compare gunzipped XML.
    before_xml = als.read_als(str(p))
    rc = cli.main(["als", "rename", str(p), "--manifest", str(manifest), "--commit", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["committed"] is False
    assert any("missing.wav" in ref for ref in out["missing_refs"])
    assert als.read_als(str(p)) == before_xml  # restored


def test_als_move_alias_dry_run(als_file, capsys):
    p = als_file()
    manifest = p.parent / "renames.json"
    manifest.write_text(json.dumps({"Samples/Imported/bass.wav": "Samples/Imported/x.wav"}))
    rc = cli.main(["als", "move", str(p), "--manifest", str(manifest), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["op"] == "move"


def test_als_warp_to_grid_dry_run(als_file, tmp_path, capsys):
    p = als_file()
    clips = tmp_path / "clips.json"
    clips.write_text(json.dumps({"bass_clip": 8.0}))
    rc = cli.main(
        ["als", "warp-to-grid", str(p), "--tempo", "128", "--clips", str(clips), "--json"]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["diff"]["warped"] == ["bass_clip"]


def test_als_move_clip_dry_run(als_file, capsys):
    p = als_file()
    rc = cli.main(
        [
            "als",
            "move-clip",
            str(p),
            "--clip",
            "bass_clip",
            "--to-beat",
            "8",
            "--dur-s",
            "7.5",
            "--bpm",
            "120",
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["diff"]["clip"] == "bass_clip"


def test_als_snap_dry_run(als_file, tmp_path, capsys):
    p = als_file()
    manifest = tmp_path / "snaps.json"
    manifest.write_text(json.dumps({"bass_clip": {"beat": 8.0, "dur_s": 7.5, "bpm": 120.0}}))
    rc = cli.main(["als", "snap", str(p), "--manifest", str(manifest), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["diff"]["snaps"][0]["clip"] == "bass_clip"


def test_als_import_stems_no_files_matching_pattern(als_file, stem_project, capsys):
    project_dir, _ = stem_project
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p3.als", xml=STEM_ALS).read_bytes())
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "14",
            "--stems",
            str(project_dir / "suno-stems"),
            "--pattern",
            "*.flac",
            "--json",
        ]
    )
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "*.flac" in err["error"]


def test_als_import_stems_master_track_resolved_by_name(als_file, stem_project, capsys):
    project_dir, _ = stem_project
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p4.als", xml=STEM_ALS).read_bytes())
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "1-Master",
            "--stems",
            str(project_dir / "suno-stems"),
            "--json",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["diff"]["master_track_id"] == "14"


def test_als_import_stems_master_track_name_not_found(als_file, stem_project, capsys):
    project_dir, _ = stem_project
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p5.als", xml=STEM_ALS).read_bytes())
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "NoSuchTrack",
            "--stems",
            str(project_dir / "suno-stems"),
            "--json",
        ]
    )
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "NoSuchTrack" in err["error"]


def test_als_import_stems_master_audio_not_found(als_file, tmp_path, capsys):
    project_dir = tmp_path / "proj"
    stems_dir = project_dir / "suno-stems"
    stems_dir.mkdir(parents=True)
    sf.write(str(stems_dir / "0 Lead Vocals.wav"), np.zeros(100, dtype=np.float32), 8000)
    target = project_dir / "proj.als"
    target.write_bytes(als_file(name="p6.als", xml=STEM_ALS).read_bytes())
    # deliberately no Samples/Imported/master.wav under project_dir
    rc = cli.main(
        [
            "als",
            "import-stems",
            str(target),
            "--master-track",
            "14",
            "--stems",
            str(stems_dir),
            "--json",
        ]
    )
    assert rc != 0
    err = json.loads(capsys.readouterr().err)
    assert "Master audio not found" in err["error"]
