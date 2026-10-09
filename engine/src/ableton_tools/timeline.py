"""Arrangement timeline: tempo map, beat -> seconds, locators.

The tempo map is the main track's Tempo automation envelope. Live stores a step
change as two events at the same beat (old tempo, then new); events between
different beats with different tempos are linear ramps. The value before the
first event is stored at a huge negative time and anchors beat 0.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .alsxml import Doc

TempoMap = list[tuple[float, float]]  # (beat, bpm), sorted by beat, file order kept


def tempo_map(doc: Doc) -> TempoMap:
    """The main track's tempo envelope, or the constant manual tempo."""
    tempo = doc.main_track().path("DeviceChain/Mixer/Tempo")
    manual = tempo.child("Manual") if tempo is not None else None
    bpm = float(manual.value() or 120) if manual is not None else 120.0
    target = tempo.child("AutomationTarget") if tempo is not None else None
    target_id = target.attrs.get("Id") if target is not None else None
    if target_id is not None:
        for env in doc.main_track().find_all("AutomationEnvelope"):
            pointee = env.path("EnvelopeTarget/PointeeId")
            if pointee is None or pointee.value() != target_id:
                continue
            events = [
                (max(float(e.attrs["Time"]), 0.0), float(e.attrs["Value"]))
                for e in env.find_all("FloatEvent")
            ]
            if events:
                # Stable sort by beat only: a step is two same-beat events whose
                # file order (old tempo, then new) must survive.
                return sorted(events, key=lambda ev: ev[0])
    return [(0.0, bpm)]


def beats_to_seconds(beat: float, tmap: TempoMap) -> float:
    """Seconds from beat 0 to `beat`, integrating steps and linear ramps."""
    secs = 0.0
    for (b0, t0), (b1, t1) in zip(tmap, tmap[1:], strict=False):
        if beat <= b0:
            break
        end = min(beat, b1)
        if end <= b0:
            continue
        t_end = t0 + (t1 - t0) * (end - b0) / (b1 - b0) if b1 > b0 else t0
        if math.isclose(t_end, t0):
            secs += 60.0 * (end - b0) / t0
        else:  # linear ramp in beats: integral of 60 / T(b) db
            secs += 60.0 * (end - b0) / (t_end - t0) * math.log(t_end / t0)
    last_beat, last_bpm = tmap[-1]
    if beat > last_beat:
        secs += 60.0 * (beat - max(last_beat, 0.0)) / last_bpm
    return secs


def arrangement_end(doc: Doc) -> float | None:
    """Beat where the last Arrangement clip ends (None if there are none)."""
    ends = []
    for clip in doc.nodes("AudioClip") + doc.nodes("MidiClip"):
        if any(a.tag in ("ClipSlot", "FreezeSequencer", "TakeLanes") for a in clip.ancestors()):
            continue
        end = clip.child("CurrentEnd")
        if end is not None and end.value() is not None:
            ends.append(float(end.value() or 0))
    return max(ends) if ends else None


def locators(path: str | Path) -> dict[str, Any]:
    """Locators with beat and seconds, plus the arrangement end."""
    doc = Doc.read(path)
    tmap = tempo_map(doc)
    locs: list[dict[str, Any]] = sorted(
        ({"name": n.value(), "beat": float(t.value() or 0)}
         for loc in doc.nodes("Locator")
         if (t := loc.child("Time")) is not None and (n := loc.child("Name")) is not None),
        key=lambda d: d["beat"],
    )
    for loc in locs:
        loc["seconds"] = round(beats_to_seconds(loc["beat"], tmap), 6)
    end = arrangement_end(doc)
    return {
        "file": str(path),
        "tempo_automated": len(tmap) > 1,
        "locators": locs,
        "arrangement_end": None if end is None
        else {"beat": end, "seconds": round(beats_to_seconds(end, tmap), 6)},
    }
