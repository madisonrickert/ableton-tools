"""Tempo detection (beat-tracking), sub-ms precision (autocorrelation),
and real drift (inter-beat-interval regression)."""

import numpy as np
import librosa


def _onset_env(path):
    y, sr = librosa.load(path, sr=None, mono=True)
    return librosa.onset.onset_strength(y=y, sr=sr), sr


def detect_tempo(path, hint_bpm=None):
    """Beat-tracked BPM plus first-onset time."""
    oenv, sr = _onset_env(path)
    kw = {"start_bpm": float(hint_bpm)} if hint_bpm else {}
    tempo_val, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, **kw)
    bpm = float(np.atleast_1d(tempo_val)[0])
    times = librosa.frames_to_time(beats, sr=sr)
    return {
        "bpm": round(bpm, 4),
        "first_beat_s": float(times[0]) if len(times) else None,
        "n_beats": int(len(times)),
    }


def precise_tempo(path):
    """Sub-millisecond BPM via autocorrelation of the onset envelope with
    parabolic interpolation around the peak."""
    oenv, sr = _onset_env(path)
    hop = 512
    fps = sr / hop
    ac = librosa.autocorrelate(oenv)
    lo, hi = int(fps * 0.3), int(fps * 1.0)  # 60..200 BPM plausible range
    hi = min(hi, len(ac) - 2)
    if hi <= lo:
        return {"precise_bpm": None, "period_s": None}
    k = lo + int(np.argmax(ac[lo:hi]))
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    denom = a - 2 * b + c
    delta = 0.5 * (a - c) / denom if denom != 0 else 0.0
    period_s = (k + delta) / fps
    return {"precise_bpm": round(60.0 / period_s, 4), "period_s": float(period_s)}


def tempo_drift(path, hint_bpm=None):
    """Real tempo drift via inter-beat-interval (IBI) regression."""
    oenv, sr = _onset_env(path)
    kw = {"start_bpm": float(hint_bpm)} if hint_bpm else {}
    _, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, **kw)
    times = librosa.frames_to_time(beats, sr=sr)
    if len(times) < 4:
        return {"error": "too few beats", "n_beats": int(len(times))}
    ibi = np.diff(times)
    med = float(np.median(ibi))
    keep = (ibi > 0.66 * med) & (ibi < 1.5 * med)
    bt = times[:-1][keep]
    iv = ibi[keep]
    slope, intercept = np.polyfit(bt, iv, 1)
    bpm_start = 60.0 / (intercept + slope * bt[0])
    bpm_end = 60.0 / (intercept + slope * bt[-1])
    return {
        "median_bpm": round(60.0 / med, 4),
        "bpm_start": round(float(bpm_start), 4),
        "bpm_end": round(float(bpm_end), 4),
        "bpm_drift_total": round(float(bpm_end - bpm_start), 4),
        "n_beats": int(len(times)),
    }


def analyze(path, hint_bpm=None):
    """Bundle detect_tempo + precise_tempo + tempo_drift into one report."""
    out = {"file": str(path)}
    out.update(detect_tempo(path, hint_bpm))
    out.update(precise_tempo(path))
    out.update(tempo_drift(path, hint_bpm))
    return out
