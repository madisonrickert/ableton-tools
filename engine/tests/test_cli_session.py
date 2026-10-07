import json

import numpy as np
import soundfile as sf

from ableton_tools import cli
from ableton_tools.alsxml import Doc


def _run(capsys, *argv):
    rc = cli.main([*argv, "--json"])
    return rc, json.loads(capsys.readouterr().out)


def _stems(proj, n=2):
    d = proj / "stems"
    d.mkdir(exist_ok=True)
    x, sr = sf.read(str(proj / "Samples" / "master.wav"), dtype="float32")
    for i in range(n):
        sf.write(str(d / f"{i} S{i}.wav"), x, sr)
    return d


def test_cli_session_commands_commit_end_to_end(live12_project, capsys):
    p = str(live12_project)
    d = _stems(live12_project.parent)
    assert _run(capsys, "als", "import-stems", p, "--master-track", "master",
                "--stems", str(d), "--commit")[1]["committed"]
    assert _run(capsys, "als", "set-tempo", p, "133.9", "--commit")[1]["committed"]
    assert _run(capsys, "als", "group", p, "--name", "STEMS", "--tracks", "S0", "S1",
                "--color", "20", "--commit")[1]["committed"]
    assert _run(capsys, "als", "add-track", p, "--name", "SAX", "--after", "master",
                "--commit")[1]["committed"]
    assert _run(capsys, "als", "mute", p, "--tracks", "S1", "--commit")[1]["committed"]
    assert _run(capsys, "als", "move-clip", p, "--clip", "master", "--to-beat", "2",
                "--commit")[1]["committed"]
    rc, out = _run(capsys, "als", "sync-to-master", p, "--master", "master",
                   "--all-warped", "--commit")
    assert out["committed"] and len(out["diff"]["synced"]) == 2
    rc, report = _run(capsys, "als", "validate", p)
    assert rc == 0 and report["ok"] and report["warnings"] == []
    doc = Doc.read(live12_project)
    names = [doc.track_name(t) for t in doc.tracks()]
    assert names[:3] == ["1-master", "SAX", "STEMS"]


def test_cli_import_stems_tolerance_reports_lags(live12_project, capsys):
    proj = live12_project.parent
    d = proj / "stems"
    d.mkdir()
    x, sr = sf.read(str(proj / "Samples" / "master.wav"), dtype="float32")
    sf.write(str(d / "0 Padded.wav"), np.concatenate([x, np.zeros(1152, np.float32)]), sr)
    rc = cli.main(["als", "import-stems", str(live12_project), "--master-track", "master",
                   "--stems", str(d), "--json"])
    err = json.loads(capsys.readouterr().err)
    assert rc == 2 and "--tolerance-ms" in err["hint"]  # exact invariant rejects padding
    rc, out = _run(capsys, "als", "import-stems", str(live12_project), "--master-track",
                   "master", "--stems", str(d), "--tolerance-ms", "50")
    assert rc == 0 and out["diff"]["timeline"][0]["ok"] is True


def test_cli_import_stems_session_unwarped_flags(live12_project, capsys):
    d = _stems(live12_project.parent, 1)
    rc, out = _run(capsys, "als", "import-stems", str(live12_project), "--master-track",
                   "master", "--stems", str(d), "--to", "session", "--unwarped")
    assert rc == 0 and out["diff"]["stems"][0]["placement"] == "session"
    assert out["validation"]["ok"]


def test_cli_transplant_devices_commit_copies_files(live12_project, chain_src_als, capsys):
    p = str(live12_project)
    rc, dry = _run(capsys, "als", "transplant-devices", p, "--from", str(chain_src_als),
                   "--src-track", "master", "--to-main", "--map-track", "source=A-Reverb")
    assert rc == 0 and dry["dry_run"] and dry["validation"]["ok"]
    assert not (live12_project.parent / "Samples/Imported/ir.wav").exists()
    rc, out = _run(capsys, "als", "transplant-devices", p, "--from", str(chain_src_als),
                   "--src-track", "master", "--to-main", "--map-track", "source=A-Reverb",
                   "--commit")
    assert rc == 0 and out["committed"], out
    assert (live12_project.parent / "Samples/Imported/ir.wav").exists()
    assert out["diff"]["routing_mapped"]


def test_cli_unwarped_takes_skip_timeline_check(live12_project, capsys):
    d = live12_project.parent / "takes"
    d.mkdir()
    sf.write(str(d / "0 Take.wav"), np.zeros(4800, np.float32), 48000)  # 0.1 s, any length
    rc, out = _run(capsys, "als", "import-stems", str(live12_project), "--master-track",
                   "master", "--stems", str(d), "--to", "session", "--unwarped")
    assert rc == 0 and out["validation"]["ok"]


def _strict(text):
    def reject(c):
        raise ValueError(f"non-JSON constant {c}")
    return json.loads(text, parse_constant=reject)


def test_cli_output_is_strict_json_with_silent_stems(live12_project, capsys):
    proj = live12_project.parent
    d = proj / "stems"
    d.mkdir()
    x, sr = sf.read(str(proj / "Samples" / "master.wav"), dtype="float32")
    sf.write(str(d / "0 Silent.wav"), np.zeros_like(x), sr)
    rc = cli.main(["als", "import-stems", str(live12_project), "--master-track", "master",
                   "--stems", str(d), "--tolerance-ms", "50", "--json"])
    out = _strict(capsys.readouterr().out)
    assert rc == 0 and out["diff"]["timeline"][0]["r"] is None


def test_internal_error_is_rendered_as_json_not_a_traceback(live12_project, capsys, monkeypatch):
    from ableton_tools import als
    from ableton_tools.alsxml import Doc

    def overlapping(path):
        doc = Doc("<A><B/></A>")
        doc.remove(doc.nodes("B")[0])
        doc.remove(doc.nodes("A")[0])
        return doc.apply()

    monkeypatch.setattr(als, "inspect", overlapping)
    rc = cli.main(["als", "inspect", str(live12_project), "--json"])
    err = json.loads(capsys.readouterr().err)
    assert rc == 4 and err["kind"] == "internal" and "overlapping edits" in err["error"]


def _transplant(capsys, proj, src, *extra):
    return _run(capsys, "als", "transplant-devices", str(proj), "--from", str(src),
                "--src-track", "master", "--to-main", "--map-track", "source=A-Reverb", *extra)


def test_cli_transplant_refused_commit_copies_no_files(live12_project, chain_src_als, capsys,
                                                      monkeypatch):
    from ableton_tools import commit

    monkeypatch.setattr(commit, "live_running", lambda: True)
    rc = cli.main(["als", "transplant-devices", str(live12_project), "--from",
                   str(chain_src_als), "--src-track", "master", "--to-main", "--commit", "--json"])
    assert rc == 2 and json.loads(capsys.readouterr().err)["kind"] == "live_running"
    assert not (live12_project.parent / "Samples/Imported").exists()


def test_cli_transplant_renames_on_a_name_clash(live12_project, chain_src_als, capsys):
    imported = live12_project.parent / "Samples/Imported"
    imported.mkdir(parents=True)
    (imported / "ir.wav").write_bytes(b"someone else's ir")
    rc, out = _transplant(capsys, live12_project, chain_src_als, "--commit")
    assert rc == 0 and out["committed"], out
    assert (imported / "ir.wav").read_bytes() == b"someone else's ir"
    src = chain_src_als.parent / "Samples/ir.wav"
    assert (imported / "ir (2).wav").read_bytes() == src.read_bytes()
    assert out["diff"]["files_copied"][0]["to"].endswith("ir (2).wav")
    xml = Doc.read(live12_project).to_str()
    assert '<RelativePath Value="Samples/Imported/ir (2).wav" />' in xml


def test_cli_transplant_reuses_an_identical_existing_file(live12_project, chain_src_als, capsys):
    imported = live12_project.parent / "Samples/Imported"
    imported.mkdir(parents=True)
    (imported / "ir.wav").write_bytes((chain_src_als.parent / "Samples/ir.wav").read_bytes())
    rc, out = _transplant(capsys, live12_project, chain_src_als, "--commit")
    assert rc == 0 and out["committed"], out
    assert sorted(p.name for p in imported.iterdir()) == ["ir.wav"]
    assert out["diff"]["files_copied"][0]["existing"] is True
