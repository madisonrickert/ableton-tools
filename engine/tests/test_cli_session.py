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
