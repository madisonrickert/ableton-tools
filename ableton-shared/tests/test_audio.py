import numpy as np
import pytest
from ableton_tools import audio


def test_load_mono_returns_float_and_sr(tone_wav):
    p = tone_wav(dur_s=1.0, sr=48000)
    x, sr = audio.load_mono(p)
    assert sr == 48000
    assert x.dtype == np.float32
    assert len(x) == 48000


def test_load_mono_resamples_to_target(tone_wav):
    p = tone_wav(dur_s=1.0, sr=44100)
    x, sr = audio.load_mono(p, target_sr=48000)
    assert sr == 48000
    assert abs(len(x) - 48000) <= 2


def test_sum_stems_adds_signals(tmp_path, tone_wav):
    a = tone_wav(name="a.wav", freq=220, dur_s=1.0, amp=0.3)
    b = tone_wav(name="b.wav", freq=440, dur_s=1.0, amp=0.3)
    mix, sr, names = audio.sum_stems(tmp_path)
    assert sr == 48000
    assert set(names) == {"a.wav", "b.wav"}
    # summed peak should exceed either single tone's amplitude region
    assert float(np.max(np.abs(mix))) > 0.3


def test_envelope_decimates(tone_wav):
    p = tone_wav(dur_s=1.0, sr=48000)
    x, sr = audio.load_mono(p)
    env, esr = audio.envelope(x, sr, target_sr=4000)
    assert abs(esr - 4000) < 1
    assert len(env) == pytest.approx(4000, abs=5)


def test_to_db_and_rms():
    assert audio.to_db(1.0) == pytest.approx(0.0)
    assert audio.to_db(0.5) == pytest.approx(-6.0206, abs=1e-3)
    x = np.ones(100)
    assert audio.rms(x) == pytest.approx(1.0)
