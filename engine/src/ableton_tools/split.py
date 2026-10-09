"""Split a rendered arrangement into one file per locator section.

Each section runs from its locator to the next one (the last runs to the end
of the render). Times come from the set's tempo map, so per-bar tempo changes
are handled. Output keeps the render's sample rate, channels and subtype;
16- and 24-bit PCM are copied sample-exact.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .alsxml import Doc
from .errors import UsageError
from .timeline import arrangement_end, beats_to_seconds, tempo_map

_UNSAFE = re.compile(r'[/\\:*?"<>|]')


def _read_exact(path: Path) -> tuple[np.ndarray, sf._SoundFileInfo]:
    info = sf.info(str(path))
    dtype = {"PCM_16": "int16", "PCM_24": "int32", "PCM_32": "int32"}.get(info.subtype, "float64")
    data, _ = sf.read(str(path), dtype=dtype, always_2d=True)
    return data, info


def split(
    render: str | Path,
    als_path: str | Path,
    out_dir: str | Path,
    *,
    start: str | None = None,
    names: dict[str, str] | None = None,
    skip: list[str] | None = None,
    trim_db: float | None = -60.0,
    tail_pad_s: float = 0.5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cut `render` at the set's locators into `out_dir`.

    `start` is where the render begins: a locator name or a beat number
    (default: the first locator, i.e. an export of the locator span).
    `names` maps locator name -> output stem; `skip` lists locators whose
    section is not written (e.g. a silent gap). Trailing audio below `trim_db`
    dBFS is trimmed, keeping `tail_pad_s` of tail (None disables trimming).
    """
    render, out_dir = Path(render), Path(out_dir)
    doc = Doc.read(als_path)
    tmap = tempo_map(doc)
    locs = sorted(
        ((float(t.value() or 0), n.value() or "")
         for loc in doc.nodes("Locator")
         if (t := loc.child("Time")) is not None and (n := loc.child("Name")) is not None),
        key=lambda x: x[0],
    )
    if not locs:
        raise UsageError(f"{als_path} has no locators", hint="add Arrangement locators in Live")

    if start is None:
        start_beat = locs[0][0]
    else:
        by_name = {name: beat for beat, name in locs}
        try:
            start_beat = by_name[start] if start in by_name else float(start)
        except ValueError:
            raise UsageError(f"--start {start!r} is neither a locator name nor a beat",
                             hint=f"locators: {', '.join(by_name)}") from None
    offset_s = beats_to_seconds(start_beat, tmap)

    data, info = _read_exact(render)
    sr, n = info.samplerate, len(data)
    full_scale = float(np.iinfo(data.dtype).max) + 1 if data.dtype.kind == "i" else 1.0
    peak = np.abs(data.astype(np.float64)).max(axis=1) / full_scale
    audible = np.nonzero(peak > 1e-3)[0]  # -60 dBFS
    first_audible_s = float(audible[0] / sr) if len(audible) else None

    warnings: list[str] = []
    end_beat = arrangement_end(doc)
    if end_beat is not None:
        expected = beats_to_seconds(end_beat, tmap) - offset_s
        if abs(expected - n / sr) > 0.5:
            warnings.append(
                f"render is {n / sr:.2f}s but start..arrangement end is {expected:.2f}s; "
                "check --start (the render may not begin where you think)")

    thresh = None if trim_db is None else 10 ** (trim_db / 20)
    names, skip_set = names or {}, set(skip or [])
    sections: list[dict[str, Any]] = []
    bounds = [round((beats_to_seconds(b, tmap) - offset_s) * sr) for b, _ in locs]
    for i, (beat, loc_name) in enumerate(locs):
        s0, s1 = bounds[i], bounds[i + 1] if i + 1 < len(locs) else n
        if beat < start_beat or s0 >= n or loc_name in skip_set:
            continue
        s1 = min(s1, n)
        if thresh is not None:
            loud = np.nonzero(peak[s0:s1] > thresh)[0]
            if not len(loud):
                warnings.append(f"section {loc_name!r} is silent; not written")
                continue
            s1 = min(s1, s0 + int(loud[-1]) + int(tail_pad_s * sr))
        stem = _UNSAFE.sub("-", names.get(loc_name, loc_name)).strip() or f"section {i + 1}"
        out = out_dir / f"{stem}.wav"
        sections.append({"locator": loc_name, "beat": beat, "start_s": round(s0 / sr, 6),
                         "duration_s": round((s1 - s0) / sr, 6), "file": str(out)})
        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            sf.write(str(out), data[s0:s1], sr, subtype=info.subtype)

    return {"render": str(render), "als": str(als_path), "dry_run": dry_run,
            "start_beat": start_beat, "offset_s": round(offset_s, 6),
            "first_audible_s": first_audible_s, "sections": sections, "warnings": warnings}
