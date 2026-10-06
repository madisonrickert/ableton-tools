"""import-stems extensions: relaxed same-timeline check, Session/unwarped placement,
level-based mute/skip (spec sub-project 2)."""

import numpy as np
import soundfile as sf
from conftest import FIXTURES
from scipy.signal import resample_poly

from ableton_tools import import_stems as ist
from ableton_tools.alsxml import Doc
from ableton_tools.validate import validate

LIVE12 = (FIXTURES / "live12_set.xml").read_text(encoding="utf-8")


def _master(project):
    x, sr = sf.read(str(project / "Samples" / "master.wav"), dtype="float32")
    return x, sr


def test_check_timeline_accepts_padding_and_resample_rejects_offset(live12_project):
    proj = live12_project.parent
    x, sr = _master(proj)
    d = proj / "stems"
    d.mkdir()
    sf.write(str(d / "padded.wav"), np.concatenate([x, np.zeros(1152, np.float32)]), sr)
    sf.write(str(d / "resampled.wav"), resample_poly(x, 147, 160).astype(np.float32), 44100)
    sf.write(str(d / "late.wav"),
             np.concatenate([np.zeros(int(0.2 * sr), np.float32), x])[: len(x)], sr)
    problems, reports = ist.check_timeline(proj / "Samples" / "master.wav",
                                           sorted(d.glob("*.wav")), tolerance_ms=50)
    by = {r["file"].split("/")[-1]: r for r in reports}
    assert by["padded.wav"]["ok"] and by["resampled.wav"]["ok"]
    assert not by["late.wav"]["ok"] and abs(by["late.wav"]["lag_ms"]) > 150
    assert [p["file"].split("/")[-1] for p in problems] == ["late.wav"]


def test_session_unwarped_placement_uses_seconds_for_loop(live12_project):
    proj = live12_project.parent
    d = proj / "stems"
    d.mkdir()
    x, sr = _master(proj)
    sf.write(str(d / "0 Take.wav"), x[: sr], sr)  # 1.0 s
    out, diff = ist.import_stems(LIVE12, "8", sorted(d.glob("*.wav")), proj,
                                 to="session", unwarped=True)
    assert validate(Doc(out))["ok"]
    doc = Doc(out)
    t = doc.find_track("Take")
    assert doc.arrangement_clips(t) == []
    (clip,) = doc.session_clips(t)
    assert clip.child("IsWarped").value() == "false"
    assert float(clip.path("Loop/LoopEnd").value()) == 1.0
    assert float(clip.path("Loop/HiddenLoopEnd").value()) == 1.0
    assert abs(float(clip.child("CurrentEnd").value()) - 1.0 * 136 / 60) < 1e-6
    assert len(clip.child("WarpMarkers").children()) == 2
    assert diff["stems"][0]["placement"] == "session"


def test_skip_and_mute_below_threshold(live12_project):
    proj = live12_project.parent
    d = proj / "stems"
    d.mkdir()
    x, sr = _master(proj)
    sf.write(str(d / "0 Loud.wav"), x, sr)
    sf.write(str(d / "1 Silent.wav"), np.zeros_like(x), sr)
    out, diff = ist.import_stems(LIVE12, "8", sorted(d.glob("*.wav")), proj, skip_below=-80)
    assert [s["label"] for s in diff["stems"]] == ["Loud"]
    assert diff["skipped"][0]["label"] == "Silent"
    out2, diff2 = ist.import_stems(LIVE12, "8", sorted(d.glob("*.wav")), proj, mute_below=-80)
    t = Doc(out2).find_track("Silent")
    assert t.path("DeviceChain/Mixer/Speaker/Manual").value() == "false"
    assert next(s for s in diff2["stems"] if s["label"] == "Silent")["muted"] is True


def test_session_placement_when_master_has_no_session_clip(live12_project):
    """Common Live 12 case: master dragged straight to the Arrangement (empty slot)."""
    proj = live12_project.parent
    doc = Doc(LIVE12)
    sess = doc.session_clips(doc.track_by_id(8))[0]
    doc.replace(sess.parent, "<Value />")
    xml = doc.apply().to_str()
    d = proj / "stems"
    d.mkdir()
    x, sr = _master(proj)
    sf.write(str(d / "0 Take.wav"), x[: sr], sr)
    out, _ = ist.import_stems(xml, "8", sorted(d.glob("*.wav")), proj,
                              to="session", unwarped=True)
    assert validate(Doc(out))["ok"]
    t = Doc(out).find_track("Take")
    assert Doc(out).arrangement_clips(t) == []  # nothing un-synced left on the timeline
    (clip,) = Doc(out).session_clips(t)
    assert clip.child("IsWarped").value() == "false"
