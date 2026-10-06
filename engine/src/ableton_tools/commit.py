"""The single commit path for every mutating `als` command.

guard -> validate -> backup -> write -> typed ref check. Dry-run (the default)
stops after validation and writes nothing.

Guards: refuse when the .als changed on disk since it was read (someone, e.g.
Live, saved it meanwhile; our write would silently discard that save) and when
Ableton Live is running (its next save would silently discard ours; `--force`
overrides this one only).
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import als
from .alsxml import Doc
from .errors import UsageError
from .validate import ref_report, validate


@dataclass(frozen=True)
class Snapshot:
    path: Path
    sha256: str
    mtime: float


def snapshot(path: str | Path) -> Snapshot:
    p = Path(path)
    return Snapshot(p, hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime)


def live_running() -> bool:
    """True when an Ableton Live process is running (macOS / Windows)."""
    system = platform.system()
    try:
        if system == "Darwin":
            return subprocess.run(["pgrep", "-x", "Live"], capture_output=True).returncode == 0
        if system == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout
            return "Ableton Live" in out
    except OSError:
        return False
    return False


def run(
    path: str | Path,
    snap: Snapshot,
    new_xml: str,
    diff: dict[str, Any],
    op: str,
    *,
    commit: bool,
    force: bool,
) -> dict[str, Any]:
    path = Path(path)
    doc = Doc(new_xml)
    report = validate(doc)
    if not commit:
        return {
            "dry_run": True,
            "op": op,
            "diff": diff,
            "validation": report,
            "note": "re-run with --commit to write (a timestamped backup is made first)",
        }
    if live_running() and not force:
        raise UsageError(
            "Ableton Live is running; it would overwrite this edit the next time the set is saved",
            hint="close Ableton (or pass --force if this set is not open in Live)",
            kind="live_running",
        )
    if snapshot(path).sha256 != snap.sha256:
        raise UsageError(
            f"{path.name} changed on disk since it was read (another save happened)",
            hint="re-run the command so it starts from the current file",
            kind="file_changed",
        )
    if not report["ok"]:
        raise UsageError(
            "the edited set fails structural validation; nothing was written: "
            + "; ".join(report["errors"][:5]),
            hint="this is likely an engine bug; please report it with the command you ran",
            kind="validation_failed",
            details=report,
        )
    backup_path = als.backup(path, op)
    als.write_als(path, new_xml)  # single write seam for every commit
    refs = ref_report(doc, path.parent)
    if refs["missing_project"]:
        als.write_als(path, als.read_als(backup_path))
        return {
            "committed": False,
            "kind": "refs_restored",
            "restored_from": backup_path,
            "error": "broken project refs after patch",
            "missing_refs": refs["missing_project"],
        }
    warnings = list(report["warnings"]) + [
        f"external file not found (Live will ask to locate it): {p}"
        for p in refs["missing_external"]
    ]
    return {"committed": True, "backup": backup_path, "op": op, "diff": diff,
            "warnings": warnings}
