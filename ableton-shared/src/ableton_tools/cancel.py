"""Cancellation-based stem verification: does a stems-sum equal a master?

All functions return raw numbers. Verdicts are stated by the operating
Claude Code instance from these numbers + CANCEL_BANDS; no LLM call here.
"""

import numpy as np

from .audio import load_mono, sum_stems, to_db, rms
from .align import find_lag

CANCEL_BANDS = {
    "sibling": "worst_db < -15  -> stems are this master (true sibling)",
    "similar": "-30 <= median_db <= -10  -> similar render / partial match",
    "different": "median_db > -10  -> different audio",
}


def optimal_alpha(ref, sig):
    """Least-squares gain alpha minimizing ||ref - alpha*sig||."""
    ref = np.asarray(ref, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    denom = float(np.dot(sig, sig))
    return float(np.dot(sig, ref) / denom) if denom else 0.0


def pearson_r(a, b):
    """Pearson correlation coefficient over the common length."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    m = min(len(a), len(b))
    a = a[:m] - a[:m].mean()
    b = b[:m] - b[:m].mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def windowed_cancellation(ref, sig, sr, win_s=10.0):
    """Per-window residual after subtracting the best-gain `sig` from `ref`.

    Returns median/worst/best cancellation in dB across windows and the count.
    """
    ref = np.asarray(ref, dtype=np.float64)
    sig = np.asarray(sig, dtype=np.float64)
    m = min(len(ref), len(sig))
    ref, sig = ref[:m], sig[:m]
    win = int(win_s * sr)
    dbs = []
    for start in range(0, m - win + 1, win):
        r = ref[start : start + win]
        s = sig[start : start + win]
        alpha = optimal_alpha(r, s)
        resid = r - alpha * s
        ref_rms = rms(r)
        if ref_rms == 0:
            continue
        dbs.append(to_db(rms(resid) / ref_rms))
    if not dbs:
        return {"median_db": 0.0, "worst_db": 0.0, "best_db": 0.0, "n_windows": 0}
    return {
        "median_db": float(np.median(dbs)),
        "worst_db": float(np.max(dbs)),  # worst cancellation = least negative
        "best_db": float(np.min(dbs)),
        "n_windows": len(dbs),
    }


def stem_verify(master_path, stems_dir, win_s=10.0, max_lag_ms=200.0, pattern="*.wav"):
    """High-level: sum a stems folder, align to a master, measure cancellation."""
    master, sr = load_mono(master_path)
    mix, _, names = sum_stems(stems_dir, target_sr=sr, pattern=pattern)
    refine = int(max_lag_ms / 1000.0 * sr)
    lag, alpha, rr = find_lag(master, mix, sr, search_s=max(2.0, max_lag_ms / 1000.0), refine=refine)
    # apply lag so the two line up before windowed measurement
    if lag >= 0:
        ref = master[lag:]
        sig = mix[: len(ref)]
    else:
        sig = mix[-lag:]
        ref = master[: len(sig)]
    win = windowed_cancellation(ref, sig, sr, win_s=win_s)
    return {
        "master": str(master_path),
        "stems_dir": str(stems_dir),
        "stem_files": names,
        "sample_rate": sr,
        "lag_samples": lag,
        "lag_ms": round(lag / sr * 1000.0, 3),
        "alpha": round(alpha, 4),
        "pearson_r": round(pearson_r(ref, alpha * sig), 4),
        **win,
        "bands": CANCEL_BANDS,
    }
