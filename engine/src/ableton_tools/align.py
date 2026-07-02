"""Time-alignment primitives: envelope cross-correlation + LSQ refinement."""

import numpy as np
from scipy.signal import fftconvolve

from .audio import envelope


def xcorr_envelope(a, b):
    """Return (lag, normalized_peak) where shifting `b` by `lag` best matches `a`.

    A positive lag means `b` should move right (b lags a); negative means left.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a = a - a.mean()
    b = b - b.mean()
    corr = fftconvolve(a, b[::-1], mode="full")
    idx = int(np.argmax(corr))
    lag = idx - (len(b) - 1)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    peak = float(corr[idx] / norm) if norm > 0 else 0.0
    return lag, peak


def best_offset_lsq_window(ref, sig, center_lag, refine):
    """Refine the integer lag of `sig` relative to `ref` within +/- refine of
    center_lag, minimizing ||ref - alpha*sig|| over the overlap.

    Returns (lag, alpha, resid_ratio) where resid_ratio is residual energy /
    ref energy over the overlap (0 == perfect).
    """
    ref = np.asarray(ref, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    best = (center_lag, 0.0, np.inf)
    for lag in range(center_lag - refine, center_lag + refine + 1):
        if lag >= 0:
            r = ref[lag:]
            s = sig[: len(r)]
        else:
            s = sig[-lag:]
            r = ref[: len(s)]
        m = min(len(r), len(s))
        if m < max(8, min(len(ref), len(sig)) // 4):
            continue
        r = r[:m]
        s = s[:m]
        denom = float(np.dot(s, s))
        if denom == 0:
            continue
        alpha = float(np.dot(s, r) / denom)
        resid = r - alpha * s
        rr = float(np.dot(resid, resid)) / (float(np.dot(r, r)) + 1e-20)
        if rr < best[2]:
            best = (lag, alpha, rr)
    return best


def find_lag(ref, sig, sr, search_s=2.0, refine=128):
    """Two-stage lag finder: coarse via envelope xcorr, fine via sample LSQ."""
    env_sr = 4000
    ref_env, esr = envelope(ref, sr, env_sr)
    sig_env, _ = envelope(sig, sr, env_sr)
    coarse_env_lag, _ = xcorr_envelope(ref_env, sig_env)
    coarse_lag = int(round(coarse_env_lag * sr / esr))
    max_search = int(search_s * sr)
    coarse_lag = max(-max_search, min(max_search, coarse_lag))
    return best_offset_lsq_window(ref, sig, coarse_lag, refine)
