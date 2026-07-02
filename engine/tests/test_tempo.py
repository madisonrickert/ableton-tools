from ableton_tools import tempo


def test_detect_tempo_on_click(click_wav):
    p = click_wav(bpm=120.0, bars=8)
    out = tempo.detect_tempo(str(p))
    assert abs(out["bpm"] - 120.0) < 3.0


def test_precise_tempo_on_click(click_wav):
    p = click_wav(bpm=134.0, bars=8)
    out = tempo.precise_tempo(str(p))
    assert abs(out["precise_bpm"] - 134.0) < 3.0


def test_tempo_drift_steady_click_has_small_drift(click_wav):
    p = click_wav(bpm=120.0, bars=12)
    out = tempo.tempo_drift(str(p))
    assert abs(out["bpm_drift_total"]) < 4.0
    assert out["n_beats"] > 10


def test_analyze_bundles_all(click_wav):
    p = click_wav(bpm=120.0, bars=8)
    out = tempo.analyze(str(p))
    assert "bpm" in out and "precise_bpm" in out and "bpm_drift_total" in out


def test_analyze_with_hint_bpm_uses_start_bpm(click_wav):
    """--hint-bpm (engine/CLAUDE.md's `ableton tempo FILE --hint-bpm 134`)
    steers librosa's beat_track via start_bpm in both detect_tempo and
    tempo_drift; exercise that branch explicitly."""
    p = click_wav(bpm=120.0, bars=8)
    out = tempo.analyze(str(p), hint_bpm=120.0)
    assert abs(out["bpm"] - 120.0) < 5.0
    assert isinstance(out["bpm_drift_total"], float)
