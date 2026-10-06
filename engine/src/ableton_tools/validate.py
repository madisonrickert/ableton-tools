"""Structural validation and typed file-ref checks for .als documents.

`validate()` catches the classes of damage that make Live refuse a set or
mis-route it: duplicate track / pointee ids, NextPointeeId too low, strings in
int-typed nodes (e.g. a track name written into ScaleInformation/Name), and
dangling TrackGroupIds. Local ids (ClipSlot, WarpMarker, ...) legitimately
repeat on every track and are not checked.

`ref_report()` checks file references by RelativePathType: only type 3
(project-relative) is resolved against the project directory. Type 1 refs
are absolute/external, 5 (Core Library), 6 (User Library) and 7 (built-in
device) resolve from Live's own libraries, so they are reported, never failed.
"""

from __future__ import annotations

import xml.parsers.expat
from collections import Counter
from pathlib import Path
from typing import Any

from .alsxml import Doc, Node

INT_TAGS = (
    "Root", "CurrentStart", "CurrentEnd", "Color", "TrackGroupId", "LoopStart", "LoopEnd",
    "HiddenLoopStart", "HiddenLoopEnd", "StartRelative",
)
GROUP_ROUTING_TARGET = "AudioOut/GroupTrack"


def _numeric(v: str | None) -> bool:
    if v is None:
        return False
    try:
        float(v)
    except ValueError:
        return False
    return True


def validate(doc: Doc) -> dict[str, Any]:
    """{"ok": bool, "errors": [...], "warnings": [...]}."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        nodes = doc.nodes()
    except xml.parsers.expat.ExpatError as e:
        return {"ok": False, "errors": [f"XML is not well-formed: {e}"], "warnings": []}

    tracks = doc.tracks()
    for tid, n in Counter(t.attrs.get("Id") for t in tracks).items():
        if n > 1:
            errors.append(f"duplicate track Id {tid} ({n} tracks)")

    target_ids = Counter(
        n.attrs["Id"] for n in nodes if n.tag.endswith("Target") and "Id" in n.attrs
    )
    for tid, n in target_ids.items():
        if n > 1:
            errors.append(f"duplicate AutomationTarget/ModulationTarget Id {tid} ({n}x)")

    npi = doc.nodes("NextPointeeId")
    if npi:
        max_id = doc.max_id()
        if not _numeric(npi[0].value()) or float(npi[0].value() or 0) <= max_id:
            errors.append(f"NextPointeeId {npi[0].value()} must exceed the max Id {max_id}")

    for n in nodes:
        if n.tag in INT_TAGS and "Value" in n.attrs and not _numeric(n.value()):
            errors.append(f"<{n.tag}> holds non-numeric {n.value()!r} at byte {n.start}")
        elif (n.tag == "Name" and n.parent is not None and n.parent.tag == "ScaleInformation"
              and not _numeric(n.value())):
            errors.append(f"ScaleInformation/Name holds non-numeric {n.value()!r} "
                          f"at byte {n.start} (Live rejects the set)")
        elif n.tag in ("AudioClip", "MidiClip") and "Time" in n.attrs \
                and not _numeric(n.attrs["Time"]):
            errors.append(f"<{n.tag}> Time={n.attrs['Time']!r} is not numeric")

    group_ids = {t.attrs.get("Id") for t in tracks if t.tag == "GroupTrack"}
    for t in tracks:
        g = t.child("TrackGroupId")
        gid = g.value() if g is not None else None
        if gid in (None, "-1"):
            continue
        if gid not in group_ids:
            errors.append(f"{doc.track_name(t)!r} has TrackGroupId {gid} but no such GroupTrack")
            continue
        target = _output_target(t)
        if target is not None and target != GROUP_ROUTING_TARGET:
            warnings.append(f"{doc.track_name(t)!r} is grouped but outputs to {target!r}, "
                            f"not {GROUP_ROUTING_TARGET!r} (it bypasses its group bus)")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _output_target(t: Node) -> str | None:
    routing = t.path("DeviceChain/AudioOutputRouting/Target")
    return routing.value() if routing is not None else None


def ref_report(doc: Doc, base_dir: str | Path) -> dict[str, Any]:
    base = Path(base_dir)
    report: dict[str, Any] = {
        "missing_project": [], "missing_external": [],
        "library": 0, "user_library": 0, "builtin": 0,
    }
    for ref in doc.nodes("FileRef"):
        kind = ref.child("RelativePathType")
        rel = ref.child("RelativePath")
        path = ref.child("Path")
        k = kind.value() if kind is not None else None
        relv = rel.value() if rel is not None else ""
        pathv = path.value() if path is not None else ""
        if k == "3":
            if relv and not (base / relv).exists() and relv not in report["missing_project"]:
                report["missing_project"].append(relv)
        elif k == "1":
            if pathv and not Path(pathv).exists() and pathv not in report["missing_external"]:
                report["missing_external"].append(pathv)
        elif k == "5":
            report["library"] += 1
        elif k == "6":
            report["user_library"] += 1
        elif k == "7":
            report["builtin"] += 1
    return report
