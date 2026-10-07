import gzip
import re

import pytest

from ableton_tools import commit
from ableton_tools.alsxml import Doc
from ableton_tools.errors import UsageError


def _xml(path):
    with gzip.open(path, "rb") as fh:
        return fh.read().decode()


def _retempo(xml, bpm="140"):
    return re.sub(r'(<Tempo>\s*<LomId Value="0" />\s*<Manual Value=")[^"]*(")',
                  rf"\g<1>{bpm}\g<2>", xml, count=1)


def test_dry_run_writes_nothing_and_reports_validation(live12_project):
    before = live12_project.read_bytes()
    snap = commit.snapshot(live12_project)
    out = commit.run(live12_project, snap, _retempo(_xml(live12_project)), {"x": 1}, "t",
                     commit=False, force=False)
    assert out["dry_run"] and out["validation"]["ok"]
    assert live12_project.read_bytes() == before


def test_type1_external_ref_no_longer_triggers_restore(live12_project):
    snap = commit.snapshot(live12_project)
    out = commit.run(live12_project, snap, _retempo(_xml(live12_project)), {}, "t",
                     commit=True, force=False)
    assert out["committed"] is True
    assert "140" in Doc.read(live12_project).main_track().path(
        "DeviceChain/Mixer/Tempo/Manual").value()
    assert any("Reverb Default.adv" in w for w in out["warnings"])


def test_file_changed_since_read_is_refused(live12_project):
    snap = commit.snapshot(live12_project)
    xml = _xml(live12_project)
    with gzip.open(live12_project, "wb") as fh:  # Live (or anyone) saved meanwhile
        fh.write(_retempo(xml, "99").encode())
    after = live12_project.read_bytes()
    with pytest.raises(UsageError) as e:
        commit.run(live12_project, snap, _retempo(xml), {}, "t", commit=True, force=True)
    assert e.value.kind == "file_changed"
    assert live12_project.read_bytes() == after


def test_live_running_is_refused_unless_forced(live12_project, monkeypatch):
    monkeypatch.setattr(commit, "live_running", lambda: True)
    snap = commit.snapshot(live12_project)
    new = _retempo(_xml(live12_project))
    with pytest.raises(UsageError) as e:
        commit.run(live12_project, snap, new, {}, "t", commit=True, force=False)
    assert e.value.kind == "live_running"
    out = commit.run(live12_project, snap, new, {}, "t", commit=True, force=True)
    assert out["committed"] is True


def test_validation_failure_writes_nothing(live12_project):
    before = live12_project.read_bytes()
    snap = commit.snapshot(live12_project)
    bad = _xml(live12_project).replace('<ReturnTrack Id="2"', '<ReturnTrack Id="8"', 1)
    with pytest.raises(UsageError) as e:
        commit.run(live12_project, snap, bad, {}, "t", commit=True, force=False)
    assert e.value.kind == "validation_failed"
    assert live12_project.read_bytes() == before
    assert not (live12_project.parent / "Backup").exists()


def test_missing_project_ref_restores_from_backup(live12_project):
    before = live12_project.read_bytes()
    snap = commit.snapshot(live12_project)
    broken = _xml(live12_project).replace("Samples/master.wav", "Samples/gone.wav")
    out = commit.run(live12_project, snap, broken, {}, "t", commit=True, force=False)
    assert out["committed"] is False and out["kind"] == "refs_restored"
    assert out["missing_refs"] == ["Samples/gone.wav"]
    assert live12_project.read_bytes() == before


def test_commit_twice_same_second(live12_project):
    snap = commit.snapshot(live12_project)
    first = commit.run(live12_project, snap, _retempo(_xml(live12_project), "141"), {}, "t",
                       commit=True, force=False)
    snap2 = commit.snapshot(live12_project)
    second = commit.run(live12_project, snap2, _retempo(_xml(live12_project), "142"), {}, "t",
                        commit=True, force=False)
    assert first["committed"] and second["committed"]
    assert first["backup"] != second["backup"]


def test_preexisting_missing_ref_does_not_block_unrelated_commits(live12_project):
    (live12_project.parent / "Samples" / "master.wav").unlink()  # stale ref already in the set
    snap = commit.snapshot(live12_project)
    out = commit.run(live12_project, snap, _retempo(_xml(live12_project)), {}, "t",
                     commit=True, force=False)
    assert out["committed"] is True
    assert any("Samples/master.wav" in w for w in out["warnings"])


def test_write_als_is_atomic_when_the_write_fails(tmp_path, monkeypatch):
    from ableton_tools import als

    p = tmp_path / "Song.als"
    als.write_als(p, "<Ableton>original</Ableton>")
    before = p.read_bytes()

    def boom(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(gzip.GzipFile, "write", boom)
    with pytest.raises(OSError):
        als.write_als(p, "<Ableton>new</Ableton>")
    assert p.read_bytes() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["Song.als"]
