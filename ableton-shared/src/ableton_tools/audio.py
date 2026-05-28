"""Audio I/O and signal-prep primitives shared by the analysis commands."""

import shutil
import subprocess
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


def require_binary(name):
    """Raise a helpful error if a required system binary is missing."""
    if shutil.which(name) is None:
        raise RuntimeError(
            f"'{name}' not found on PATH. Install it (e.g. `brew install {name}`) and retry."
        )


def _ffmpeg_load(path, target_sr):
    """Decode any format ffmpeg understands to mono float32 at target_sr."""
    require_binary("ffmpeg")
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(path),
        "-ac", "1", "-ar", str(target_sr), "-f", "f32le", "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype="<f4").astype(np.float32), target_sr


def resample(x, sr_in, sr_out):
    """Resample a 1-D signal from sr_in to sr_out (polyphase, high quality)."""
    if sr_in == sr_out:
        return x
    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def load_mono(path, target_sr=48000):
    """Load an audio file as a mono float32 array at target_sr."""
    path = Path(path)
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
    except Exception:
        mono, sr = _ffmpeg_load(path, target_sr)
    if sr != target_sr:
        mono = resample(mono, sr, target_sr)
        sr = target_sr
    return mono.astype(np.float32), sr


def sum_stems(folder, target_sr=48000, pattern="*.wav"):
    """Float-sum every file matching `pattern` in `folder` (no clipping)."""
    folder = Path(folder)
    files = sorted(folder.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern!r} in {folder}")
    parts = [load_mono(f, target_sr)[0] for f in files]
    n = max(len(p) for p in parts)
    acc = np.zeros(n, dtype=np.float64)
    for p in parts:
        acc[: len(p)] += p
    return acc.astype(np.float32), target_sr, [f.name for f in files]


def envelope(x, sr, target_sr=4000):
    """Rectified, block-averaged amplitude envelope decimated toward target_sr."""
    rect = np.abs(x).astype(np.float64)
    factor = max(1, int(round(sr / target_sr)))
    n = (len(rect) // factor) * factor
    env = rect[:n].reshape(-1, factor).mean(axis=1)
    return env, sr / factor


def rms(x):
    """Root-mean-square of a signal."""
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def to_db(ratio):
    """Convert an amplitude ratio to decibels (floored at -120 dB)."""
    ratio = max(float(ratio), 1e-6)
    return 20.0 * np.log10(ratio)
