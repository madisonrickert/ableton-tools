import numpy as np
from ableton_tools import align


def test_xcorr_envelope_recovers_positive_lag():
    rng = np.random.default_rng(0)
    a = rng.standard_normal(2000)
    shift = 37
    b = np.concatenate([np.zeros(shift), a])[: len(a)]
    lag, peak = align.xcorr_envelope(a, b)
    # b is a delayed by `shift`, so b must shift left by `shift` to match a
    assert lag == -shift
    assert peak > 0.8


def test_find_lag_recovers_sample_offset():
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(48000).astype(np.float32)
    shift = 120
    sig = np.concatenate([np.zeros(shift, dtype=np.float32), ref])[: len(ref)]
    lag, alpha, rr = align.find_lag(ref, sig, sr=48000, search_s=0.1, refine=200)
    assert lag == -shift
    assert abs(alpha - 1.0) < 1e-3
    assert rr < 1e-6


def test_best_offset_lsq_window_finds_alpha():
    rng = np.random.default_rng(2)
    ref = rng.standard_normal(5000)
    sig = 0.5 * ref  # same signal, half amplitude, zero lag
    lag, alpha, rr = align.best_offset_lsq_window(ref, sig, center_lag=0, refine=5)
    assert lag == 0
    assert abs(alpha - 2.0) < 1e-6  # ref ~= alpha * sig -> alpha = 2
    assert rr < 1e-9
