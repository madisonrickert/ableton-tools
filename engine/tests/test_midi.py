import numpy as np
from ableton_tools import midi


def test_load_notes_recovers_onsets(midi_file):
    p = midi_file(notes=[(0.0, 60, 0.4), (0.5, 62, 0.4), (1.0, 64, 0.4)], bpm=120)
    notes = midi.load_notes(str(p))
    assert len(notes) == 3
    assert abs(notes[0]["onset_s"] - 0.0) < 1e-3
    assert abs(notes[1]["onset_s"] - 0.5) < 1e-3
    assert notes[2]["pitch"] == 64


def test_align_onsets_matches_by_pitch_class(midi_file):
    a = midi.load_notes(str(midi_file(name="a.mid", notes=[(0.0, 60, 0.3), (0.5, 67, 0.3)])))
    b = midi.load_notes(str(midi_file(name="b.mid", notes=[(0.02, 72, 0.3), (0.52, 55, 0.3)])))
    pairs = midi.align_onsets(a, b, tol_s=0.05, pitch_class=True)
    assert len(pairs) == 2  # 60~72 (C), 67~55 (G) within tolerance


def test_chroma_cosine_identical_is_one(midi_file):
    a = midi.load_notes(str(midi_file(name="a.mid", notes=[(0.0, 60, 0.4), (0.5, 64, 0.4)])))
    assert abs(midi.chroma_cosine(a, a) - 1.0) < 1e-9


def test_drift_fit_recovers_offset(midi_file):
    base = [(i * 0.5, 60 + (i % 5), 0.3) for i in range(12)]
    shifted = [(t + 0.03, p, d) for (t, p, d) in base]
    a = midi.load_notes(str(midi_file(name="a.mid", notes=base)))
    b = midi.load_notes(str(midi_file(name="b.mid", notes=shifted)))
    out = midi.drift_fit(a, b, tol_s=0.1)
    assert abs(out["offset_s"] - 0.03) < 0.01
    assert abs(out["slope_s_per_s"]) < 0.005


def test_compare_two_files(midi_file):
    a = midi_file(name="a.mid", notes=[(0.0, 60, 0.4), (0.5, 64, 0.4)])
    b = midi_file(name="b.mid", notes=[(0.0, 60, 0.4), (0.5, 64, 0.4)])
    out = midi.compare([str(a), str(b)])
    assert out["pairs"][0]["chroma_cosine"] > 0.99
