import numpy as np

from ableton_tools import cancel


def test_optimal_alpha_recovers_gain():
    rng = np.random.default_rng(3)
    sig = rng.standard_normal(1000)
    ref = 1.7 * sig
    assert abs(cancel.optimal_alpha(ref, sig) - 1.7) < 1e-9


def test_pearson_r_identical_is_one():
    rng = np.random.default_rng(4)
    a = rng.standard_normal(1000)
    assert abs(cancel.pearson_r(a, a) - 1.0) < 1e-9


def test_windowed_cancellation_deep_for_identical():
    rng = np.random.default_rng(5)
    ref = rng.standard_normal(48000 * 3)
    sig = ref.copy()
    out = cancel.windowed_cancellation(ref, sig, sr=48000, win_s=1.0)
    assert out["worst_db"] < -60  # identical signals cancel to near silence
    assert out["n_windows"] >= 2


def test_windowed_cancellation_shallow_for_unrelated():
    rng = np.random.default_rng(6)
    ref = rng.standard_normal(48000 * 3)
    sig = rng.standard_normal(48000 * 3)
    out = cancel.windowed_cancellation(ref, sig, sr=48000, win_s=1.0)
    assert out["median_db"] > -6  # unrelated audio barely cancels


def test_windowed_cancellation_returns_zeros_for_silent_reference():
    """A silent master would otherwise divide by ref_rms==0 per window; the
    degenerate case must short-circuit to an explicit zeroed report instead."""
    ref = np.zeros(48000 * 2)
    rng = np.random.default_rng(7)
    sig = rng.standard_normal(48000 * 2)
    out = cancel.windowed_cancellation(ref, sig, sr=48000, win_s=1.0)
    assert out == {"median_db": 0.0, "worst_db": 0.0, "best_db": 0.0, "n_windows": 0}


def test_stem_verify_true_sibling(tmp_path, tone_wav):
    import soundfile as sf

    sr = 48000
    t = np.arange(sr * 2) / sr
    a = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    b = (0.3 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    stems = tmp_path / "stems"
    stems.mkdir()
    sf.write(str(stems / "a.wav"), a, sr)
    sf.write(str(stems / "b.wav"), b, sr)
    master = tmp_path / "master.wav"
    sf.write(str(master), a + b, sr)
    out = cancel.stem_verify(str(master), str(stems), win_s=0.5)
    assert out["worst_db"] < -40
    assert out["bands"]["sibling"].startswith("worst")
