"""Dev-only acceptance check for `als transplant-devices`.

    uv run --project engine python engine/scripts/corpus_check.py [ROOT ...]

Finds every Live 11/12 set under the given roots (default: macOS Spotlight over
~/Music and /Volumes), and transplants EVERY non-empty track/main device chain
into the sanitized Live 12 fixture. Each result must pass `validate` and contain
no routing ref to a track that does not exist in the target. Prints a tally and
the first failures. Not part of CI: the corpus is the developer's private sets.
"""

from __future__ import annotations

import contextlib
import gzip
import re
import subprocess
import sys
import time
from pathlib import Path

from ableton_tools import devices
from ableton_tools.alsxml import Doc
from ableton_tools.errors import UsageError
from ableton_tools.validate import validate

FIXTURE = (Path(__file__).resolve().parents[1] / "tests/fixtures/live12_set.xml").read_text()


def find_sets(roots: list[str]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        res = subprocess.run(["mdfind", "-name", ".als", "-onlyin", root],
                             capture_output=True, text=True)
        out += [Path(p) for p in res.stdout.splitlines()
                if p.endswith(".als") and "/Backup/" not in p]
    return sorted(set(out))


def main() -> int:
    roots = sys.argv[1:] or [str(Path.home() / "Music"), "/Volumes"]
    sets = find_sets(roots)
    t0 = time.time()
    n_sets = n_chains = passed = 0
    failures: list[str] = []
    for path in sets:
        try:
            with gzip.open(path, "rb") as fh:
                raw = fh.read()
        except (OSError, EOFError):
            continue
        if not re.search(rb'MinorVersion="1[12]', raw[:400]):
            continue
        n_sets += 1
        sdoc = Doc(raw)
        sources = [("track", t) for t in sdoc.tracks()]
        with contextlib.suppress(UsageError):
            sources.append(("main", sdoc.main_track()))
        for kind, t in sources:
            devs = t.path("DeviceChain/DeviceChain/Devices")
            if devs is None or not devs.children():
                continue
            n_chains += 1
            label = f"{path.name} :: {sdoc.track_name(t) or t.tag}"
            try:
                if kind == "main":
                    out, _ = devices.transplant(FIXTURE, sdoc, src_main=True, to_track="master")
                else:
                    out, _ = devices.transplant(FIXTURE, sdoc, src_track=t.attrs["Id"],
                                                to_track="master")
            except Exception as e:  # noqa: BLE001 - tally every failure kind
                failures.append(f"{label}: {type(e).__name__}: {e}")
                continue
            report = validate(Doc(out))
            target_ids = {x.attrs.get("Id") for x in Doc(out).tracks()}
            dangling = [i for i in re.findall(r"Track\.(\d+)/", out) if i not in target_ids]
            if report["ok"] and not dangling:
                passed += 1
            else:
                failures.append(f"{label}: {report['errors'][:2]} dangling={dangling[:3]}")
    print(f"sets={n_sets} chains={n_chains} passed={passed} failed={len(failures)} "
          f"({time.time() - t0:.0f}s)")
    for f in failures[:20]:
        print("  FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
