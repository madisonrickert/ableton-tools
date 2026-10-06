"""Read-only analysis helpers: levels, locate, warp-check.

Each returns raw numbers plus threshold bands; the skills state the verdict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

from . import als, audio
from .alsxml import Doc, Node
from .errors import UsageError

SILENT_DBFS = -60.0


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a = a[:n].astype(np.float64) - a[:n].mean()
    b = b[:n].astype(np.float64) - b[:n].mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / d) if d > 0 else 0.0


def levels(folder: str | Path, pattern: str = "*.wav", ref: str | Path | None = None
           ) -> dict[str, Any]:
    """Per file: duration, sample rate, channels, RMS dBFS, silent flag, and
    (with ref) Pearson r against the reference at lag 0."""
    files = sorted(Path(folder).glob(pattern))
    if not files:
        raise UsageError(f"No files matching {pattern!r} in {folder}")
    ref_x = audio.load_mono(ref)[0] if ref else None
    rows = []
    for p in files:
        info = sf.info(str(p))
        x, _ = audio.load_mono(p)
        db = float(audio.to_db(audio.rms(x)))
        row: dict[str, Any] = {
            "file": str(p), "duration_s": round(float(info.duration), 4),
            "sample_rate": int(info.samplerate), "channels": int(info.channels),
            "dbfs": round(db, 2), "silent": bool(db < SILENT_DBFS),
        }
        if ref_x is not None:
            row["r_vs_ref"] = round(_pearson(ref_x, x), 4)
        rows.append(row)
    return {"folder": str(folder), "ref": str(ref) if ref else None,
            "silent_threshold_dbfs": SILENT_DBFS, "files": rows}


def _env(path: str | Path, env_hz: float) -> np.ndarray:
    x, sr = audio.load_mono(path)
    e, _ = audio.envelope(x, sr, int(env_hz))
    return e


def locate(fragment: str | Path, ref: str | Path, env_hz: float = 100.0, top: int = 3
           ) -> dict[str, Any]:
    """Where does `fragment` occur inside `ref`? Normalized sliding Pearson on
    amplitude envelopes (FFT). Bands: r >= 0.8 same render, 0.6-0.8 likely,
    < 0.6 not the same performance (place by ear)."""
    r_env, f_env = _env(ref, env_hz), _env(fragment, env_hz)
    m = len(f_env)
    if m < 2 or m > len(r_env):
        raise UsageError("fragment must be shorter than the reference")
    ones = np.ones(m)
    sx = fftconvolve(r_env, ones, mode="valid")
    sxx = fftconvolve(r_env * r_env, ones, mode="valid")
    sxy = fftconvolve(r_env, f_env[::-1], mode="valid")
    sy, syy = float(f_env.sum()), float((f_env * f_env).sum())
    den = np.sqrt(np.maximum(m * sxx - sx * sx, 1e-12) * max(m * syy - sy * sy, 1e-12))
    r = (m * sxy - sx * sy) / den
    order = np.argsort(r)[::-1]
    picks: list[int] = []
    min_sep = int(env_hz)  # alternatives at least 1 s apart
    for i in order:
        if all(abs(int(i) - j) >= min_sep for j in picks):
            picks.append(int(i))
        if len(picks) >= top:
            break
    matches = [{"offset_s": round(i / env_hz, 3), "r": round(float(r[i]), 4)} for i in picks]
    best = matches[0]["r"]
    band = "same" if best >= 0.8 else ("likely" if best >= 0.6 else "different")
    return {"fragment": str(fragment), "ref": str(ref), "env_hz": env_hz,
            "matches": matches, "band": band}


def _master_clip(doc: Doc, track: str | None) -> tuple[Node, Node]:
    tracks = [doc.find_track(track)] if track else doc.tracks()
    for t in tracks:
        for c in doc.arrangement_clips(t):
            iw = c.child("IsWarped")
            if iw is not None and iw.value() == "true" and len(als.warp_markers(c)) >= 2:
                return t, c
    raise UsageError("no warped Arrangement clip with a warp map found",
                     hint="pass --track NAME for the auto-warped master")


def _nearest_ms(points: np.ndarray, t: float) -> float:
    return float(np.min(np.abs(points - t)) * 1000.0) if len(points) else float("nan")


def warp_check(als_path: str | Path, track: str | None = None, audio_path: str | Path | None = None
               ) -> dict[str, Any]:
    """EXPERIMENTAL. Do the master's warp markers sit on the audio's real beats,
    and do all warped clips share the master's exact warp map?"""
    import librosa

    als_path = Path(als_path)
    doc = Doc.read(als_path)
    t, clip = _master_clip(doc, track)
    markers = als.warp_markers(clip)
    if audio_path is None:
        rel = clip.path("SampleRef/FileRef/RelativePath")
        if rel is None or not rel.value():
            raise UsageError("master clip has no sample path; pass --audio")
        audio_path = als_path.parent / (rel.value() or "")
    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    oenv = librosa.onset.onset_strength(y=y, sr=sr)
    _, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, units="time")
    onsets = librosa.onset.onset_detect(onset_envelope=oenv, sr=sr, units="time")
    secs = np.array([s for s, _ in markers])
    beat_err = [_nearest_ms(np.asarray(beats), s) for s in secs]
    onset_err = [_nearest_ms(np.asarray(onsets), s) for s in secs]
    spacing = np.diff([b for _, b in markers])
    shared, differs = [], []
    for other in doc.tracks():
        if other.start == t.start:
            continue
        for c in doc.arrangement_clips(other):
            iw = c.child("IsWarped")
            if iw is None or iw.value() != "true":
                continue
            (shared if als.warp_markers(c) == markers else differs).append(doc.track_name(other))
    notes = []
    first_beat = float(beats[0]) if len(beats) else None
    if first_beat is not None and first_beat > secs[0] + 2.0:
        notes.append(f"no steady beat detected before {first_beat:.1f} s: markers in the intro "
                     "cannot be verified against the audio (sparse/ambient intro?)")

    def stats(v: list[float]) -> dict[str, float]:
        a = np.array([x for x in v if not np.isnan(x)])
        if not len(a):
            return {"median": float("nan"), "p90": float("nan")}
        return {"median": round(float(np.median(a)), 1),
                "p90": round(float(np.percentile(a, 90)), 1)}

    name = clip.child("Name")
    return {
        "track": doc.track_name(t),
        "clip": name.value() if name is not None else None,
        "audio": str(audio_path),
        "marker_count": len(markers),
        "marker_spacing_beats": float(np.median(spacing)) if len(spacing) else None,
        "warp_map_bpm": als.warp_map_bpm(clip),
        "beat_alignment_ms": stats(beat_err),
        "onset_alignment_ms": stats(onset_err),
        "downbeat": {"time_s": round(float(secs[0]), 4),
                     "nearest_onset_ms": round(onset_err[0], 1)},
        "first_detected_beat_s": round(first_beat, 3) if first_beat is not None else None,
        "sync": {"shared": shared, "differs": differs},
        "notes": notes,
    }
