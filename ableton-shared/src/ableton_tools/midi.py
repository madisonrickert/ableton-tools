"""MIDI timeline analysis: parse to absolute seconds, align onsets, compare
chroma profiles, and fit timing drift between transcriptions."""

import itertools

import numpy as np
import mido


def load_notes(path):
    """Parse a MIDI file into a sorted list of {onset_s, pitch, dur_s},
    honoring tempo changes across all tracks."""
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat

    # Build a global tempo map of (abs_tick, tempo_us_per_beat).
    tempo_map = [(0, 500000)]
    for track in mid.tracks:
        t = 0
        for msg in track:
            t += msg.time
            if msg.type == "set_tempo":
                tempo_map.append((t, msg.tempo))
    tempo_map = sorted(set(tempo_map))

    def tick_to_sec(tick):
        sec = 0.0
        prev_tick = 0
        cur = 500000
        for at, tp in tempo_map:
            if at >= tick:
                break
            sec += mido.tick2second(at - prev_tick, tpb, cur)
            prev_tick, cur = at, tp
        sec += mido.tick2second(tick - prev_tick, tpb, cur)
        return sec

    notes = []
    for track in mid.tracks:
        t = 0
        on = {}
        for msg in track:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                on.setdefault(msg.note, []).append(t)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if on.get(msg.note):
                    start = on[msg.note].pop(0)
                    notes.append(
                        {
                            "onset_s": tick_to_sec(start),
                            "pitch": msg.note,
                            "dur_s": tick_to_sec(t) - tick_to_sec(start),
                        }
                    )
    notes.sort(key=lambda n: n["onset_s"])
    return notes


def align_onsets(a, b, tol_s=0.05, pitch_class=True):
    """Greedy nearest-onset matching within tol_s; optionally pitch-class aware.
    Returns a list of (note_a, note_b) pairs."""
    bs = sorted(b, key=lambda n: n["onset_s"])
    used = set()
    pairs = []
    for na in sorted(a, key=lambda n: n["onset_s"]):
        best_j = None
        best_d = tol_s + 1e-9
        for j, nb in enumerate(bs):
            if j in used:
                continue
            d = abs(nb["onset_s"] - na["onset_s"])
            if d > tol_s:
                continue
            if pitch_class and (na["pitch"] % 12) != (nb["pitch"] % 12):
                continue
            if not pitch_class and na["pitch"] != nb["pitch"]:
                continue
            if d < best_d:
                best_d, best_j = d, j
        if best_j is not None:
            used.add(best_j)
            pairs.append((na, bs[best_j]))
    return pairs


def chroma_profile(notes):
    """Duration-weighted 12-bin pitch-class histogram, normalized to sum 1."""
    v = np.zeros(12)
    for n in notes:
        v[n["pitch"] % 12] += max(n["dur_s"], 1e-6)
    s = v.sum()
    return v / s if s > 0 else v


def chroma_cosine(a, b):
    """Cosine similarity of two note lists' chroma profiles."""
    pa, pb = chroma_profile(a), chroma_profile(b)
    na, nb = np.linalg.norm(pa), np.linalg.norm(pb)
    return float(pa @ pb / (na * nb)) if na > 0 and nb > 0 else 0.0


def drift_fit(a, b, tol_s=0.1):
    """Fit dt = offset + slope*t over aligned anchors (b relative to a)."""
    pairs = align_onsets(a, b, tol_s=tol_s, pitch_class=True)
    if len(pairs) < 3:
        return {"error": "too few anchors", "n_anchors": len(pairs)}
    t = np.array([p[0]["onset_s"] for p in pairs])
    dt = np.array([p[1]["onset_s"] - p[0]["onset_s"] for p in pairs])
    slope, intercept = np.polyfit(t, dt, 1)
    resid = dt - (slope * t + intercept)
    return {
        "offset_s": round(float(intercept), 5),
        "slope_s_per_s": round(float(slope), 7),
        "n_anchors": len(pairs),
        "residual_ms": round(float(np.std(resid) * 1000), 3),
    }


def compare(paths):
    """Pairwise comparison of 2+ MIDI files: chroma cosine + drift fit."""
    loaded = [(p, load_notes(p)) for p in paths]
    out = {"files": [{"path": p, "n_notes": len(n)} for p, n in loaded], "pairs": []}
    for (pa, na), (pb, nb) in itertools.combinations(loaded, 2):
        entry = {"a": pa, "b": pb, "chroma_cosine": round(chroma_cosine(na, nb), 4)}
        entry.update({f"drift_{k}": v for k, v in drift_fit(na, nb).items()})
        out["pairs"].append(entry)
    return out
