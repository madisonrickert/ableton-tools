"""Single dispatcher for the Ableton tools engine. Every subcommand supports
--json. `manifest` lists all subcommands. Unknown subcommands fail loudly."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import UsageError


def _arg(
    name: str,
    *,
    required: bool = False,
    default: Any = None,
    help: str = "",
    type: type | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "default": default,
        "help": help,
        "type": type,
        "action": action,
    }


_COMMIT = _arg("--commit", action="store_true", help="write (default: dry-run)")
_FORCE = _arg("--force", action="store_true", help="commit even if Ableton Live is running")
_JSON = _arg("--json", action="store_true", help="JSON output")

# Single source of truth: drives both build_parser() and `manifest --json`, so
# the CLI surface and its self-description can never drift.
SPEC: list[dict[str, Any]] = [
    {"name": "manifest", "desc": "List all subcommands (this command).", "args": [_JSON]},
    {
        "name": "stem-verify",
        "desc": "Measure whether a stems folder sums to a master.",
        "args": [
            _arg("--stems", required=True),
            _arg("--master", required=True),
            _arg("--win", type=float, default=10.0),
            _arg("--max-lag-ms", type=float, default=200.0),
            _arg("--pattern", default="*.wav"),
            _JSON,
        ],
    },
    {
        "name": "tempo",
        "desc": "Detect tempo, sub-ms precision, and drift of an audio file.",
        "args": [_arg("file", required=True), _arg("--hint-bpm", type=float, default=None), _JSON],
    },
    {
        "name": "drift",
        "desc": "Measure time drift between a master and its stems-sum.",
        "args": [
            _arg("--master", required=True),
            _arg("--stems", required=True),
            _arg("--win", type=float, default=10.0),
            _arg("--pattern", default="*.wav"),
            _JSON,
        ],
    },
    {
        "name": "midi",
        "desc": "MIDI tools.",
        "subcommands": [
            {
                "name": "transcribe",
                "desc": "Audio -> MIDI via basic-pitch.",
                "args": [_arg("audio", required=True), _arg("--out", default=None), _JSON],
            },
            {
                "name": "compare",
                "desc": "Chroma similarity + timing drift.",
                "args": [_arg("files", required=True, help="2-3 MIDI files"), _JSON],
            },
        ],
    },
    {
        "name": "als",
        "desc": "Inspect/edit a .als.",
        "subcommands": [
            {
                "name": "inspect",
                "desc": "Tempo, tracks, clips, refs as JSON.",
                "args": [_arg("als", required=True), _JSON],
            },
            {
                "name": "validate",
                "desc": "Structural checks + typed file-ref report (read-only).",
                "args": [_arg("als", required=True), _JSON],
            },
            {
                "name": "rename",
                "desc": "Patch file references per manifest.",
                "args": [
                    _arg("als", required=True),
                    _arg("--manifest", required=True),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "move",
                "desc": "Alias of rename.",
                "args": [
                    _arg("als", required=True),
                    _arg("--manifest", required=True),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "warp-to-grid",
                "desc": "Grid-lock clips at a fixed tempo.",
                "args": [
                    _arg("als", required=True),
                    _arg("--tempo", required=True, type=float),
                    _arg("--clips", required=True),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "move-clip",
                "desc": "Move one clip to an exact beat.",
                "args": [
                    _arg("als", required=True),
                    _arg("--clip", required=True),
                    _arg("--to-beat", required=True, type=float),
                    _arg("--dur-s", type=float, help="new length in seconds (default: keep)"),
                    _arg("--bpm", type=float, help="tempo for --dur-s"),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "snap",
                "desc": "Batch clip repositioning per manifest.",
                "args": [
                    _arg("als", required=True),
                    _arg("--manifest", required=True),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "import-stems",
                "desc": "Clone a warped master track per stem file and relink.",
                "args": [
                    _arg("als", required=True),
                    _arg(
                        "--master-track",
                        required=True,
                        help="master AudioTrack Id or EffectiveName",
                    ),
                    _arg("--stems", required=True),
                    _arg("--pattern", default="*.wav"),
                    _arg(
                        "--colors",
                        default=None,
                        help="JSON {label: color_int} overriding the built-in map",
                    ),
                    _arg(
                        "--keep-session",
                        action="store_true",
                        help="keep each clone's Session copy of the master clip",
                    ),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
        ],
    },
]


def _emit(obj: Any, as_json: bool, human: Callable[[Any], Any]) -> None:
    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        human(obj)


def _manifest_entry(c: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": c["name"], "desc": c.get("desc", "")}
    if "args" in c:
        out["args"] = [
            {k: a[k] for k in ("name", "required", "default", "help")} for a in c["args"]
        ]
    if "subcommands" in c:
        out["subcommands"] = [_manifest_entry(s) for s in c["subcommands"]]
    return out


def _cmd_manifest(args: argparse.Namespace) -> int:
    entries = [_manifest_entry(c) for c in SPEC]
    _emit(
        {"subcommands": entries},
        args.json,
        lambda o: [print(f"{c['name']:14} {c['desc']}") for c in o["subcommands"]],
    )
    return 0


def _cmd_stem_verify(args: argparse.Namespace) -> int:
    from . import cancel

    out = cancel.stem_verify(
        args.master, args.stems, win_s=args.win, max_lag_ms=args.max_lag_ms, pattern=args.pattern
    )
    _emit(
        out,
        args.json,
        lambda o: print(
            f"worst={o['worst_db']:.1f}dB median={o['median_db']:.1f}dB "
            f"lag={o['lag_ms']:.1f}ms r={o['pearson_r']}"
        ),
    )
    return 0


def _cmd_tempo(args: argparse.Namespace) -> int:
    from . import tempo

    out = tempo.analyze(args.file, hint_bpm=args.hint_bpm)
    _emit(
        out,
        args.json,
        lambda o: print(
            f"bpm={o.get('bpm')} precise={o.get('precise_bpm')} drift={o.get('bpm_drift_total')}"
        ),
    )
    return 0


def _cmd_drift(args: argparse.Namespace) -> int:
    from . import align, audio

    master, sr = audio.load_mono(args.master)
    mix, _, names = audio.sum_stems(args.stems, target_sr=sr, pattern=args.pattern)
    # per-window lag trace
    win = int(args.win * sr)
    m = min(len(master), len(mix))
    rows: list[dict[str, Any]] = []
    for start in range(0, m - win + 1, win):
        r = master[start : start + win]
        s = mix[start : start + win]
        lag, alpha, rr = align.find_lag(r, s, sr, search_s=0.2, refine=int(0.05 * sr))
        rows.append(
            {
                "t_s": round(start / sr, 2),
                "lag_ms": round(lag / sr * 1000, 3),
                "resid_ratio": round(rr, 5),
            }
        )
    drift_ms = rows[-1]["lag_ms"] - rows[0]["lag_ms"] if len(rows) >= 2 else 0.0
    out = {
        "master": args.master,
        "stems_dir": args.stems,
        "stem_files": names,
        "windows": rows,
        "total_drift_ms": round(drift_ms, 3),
    }
    _emit(
        out,
        args.json,
        lambda o: print(
            f"total drift over file: {o['total_drift_ms']:.1f} ms across "
            f"{len(o['windows'])} windows"
        ),
    )
    return 0


def _cmd_midi(args: argparse.Namespace) -> int:
    from . import midi, transcribe

    if args.midi_cmd == "transcribe":
        out_path = transcribe.transcribe(args.audio, out_path=args.out)
        _emit({"output": out_path}, args.json, lambda o: print(o["output"]))
        return 0
    if args.midi_cmd == "compare":
        out = midi.compare(args.files)
        _emit(
            out,
            args.json,
            lambda o: [
                print(
                    f"{p['a']} vs {p['b']}: chroma={p['chroma_cosine']} "
                    f"offset={p.get('drift_offset_s')}s slope={p.get('drift_slope_s_per_s')}"
                )
                for p in o["pairs"]
            ],
        )
        return 0
    raise SystemExit("midi requires a subcommand: transcribe | compare")


def _load_manifest(path: str) -> dict[str, Any]:
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise UsageError(
            f"Manifest file not found: {path}", hint="pass an existing JSON file"
        ) from None
    except json.JSONDecodeError as e:
        raise UsageError(
            f"Manifest is not valid JSON: {path} ({e})", hint="fix the JSON syntax"
        ) from None


def _als_commit(
    args: argparse.Namespace, new_xml: str, diff: dict[str, Any], op: str
) -> dict[str, Any]:
    """Shared commit/dry-run logic for mutating als subcommands (see commit.py)."""
    from . import commit

    return commit.run(
        args.als, args._snap, new_xml, diff, op, commit=args.commit, force=args.force
    )


def _cmd_als(args: argparse.Namespace) -> int:
    from . import als

    if args.als_cmd == "inspect":
        _emit(
            als.inspect(args.als),
            args.json,
            lambda o: print(
                f"tempo={o['tempo']} tracks={len(o['tracks'])} clips={len(o['clips'])}"
            ),
        )
        return 0
    if args.als_cmd == "validate":
        from .alsxml import Doc
        from .validate import ref_report, validate

        doc = Doc.read(args.als)
        report = validate(doc)
        report["refs"] = ref_report(doc, Path(args.als).resolve().parent)
        report["file"] = args.als
        _emit(
            report,
            args.json,
            lambda o: print(
                ("OK" if o["ok"] else "INVALID")
                + "".join(f"\n  error: {e}" for e in o["errors"])
                + "".join(f"\n  warning: {w}" for w in o["warnings"])
                + "".join(f"\n  missing project file: {m}" for m in o["refs"]["missing_project"])
            ),
        )
        return 0 if report["ok"] else 1
    from . import commit

    args._snap = commit.snapshot(args.als)  # before reading: guards concurrent saves
    xml = als.read_als(args.als)
    if args.als_cmd == "rename":
        new_xml, diff = als.rename_refs(xml, _load_manifest(args.manifest))
        out = _als_commit(args, new_xml, diff, "rename")
    elif args.als_cmd == "move":
        new_xml, diff = als.rename_refs(xml, _load_manifest(args.manifest))
        out = _als_commit(args, new_xml, diff, "move")
    elif args.als_cmd == "warp-to-grid":
        spec = _load_manifest(args.clips)  # {clip_name: duration_seconds}
        new_xml = als.set_tempo(xml, args.tempo)
        new_xml, diff = als.warp_to_grid(new_xml, list(spec), args.tempo, spec)
        out = _als_commit(args, new_xml, diff, "warp-to-grid")
    elif args.als_cmd == "move-clip":
        new_xml, diff = als.move_clip_to_beat(xml, args.clip, args.to_beat, args.dur_s, args.bpm)
        out = _als_commit(args, new_xml, diff, "move-clip")
    elif args.als_cmd == "snap":
        spec = _load_manifest(args.manifest)  # {clip_name: {beat[, dur_s, bpm]}}
        new_xml = xml
        diffs = []
        for name, v in spec.items():
            new_xml, d = als.move_clip_to_beat(
                new_xml, name, v["beat"], v.get("dur_s"), v.get("bpm")
            )
            diffs.append(d)
        out = _als_commit(args, new_xml, {"snaps": diffs}, "snap")
    elif args.als_cmd == "import-stems":
        from . import import_stems as ist

        stem_paths = sorted(Path(args.stems).glob(args.pattern))
        if not stem_paths:
            raise UsageError(
                f"No files matching {args.pattern!r} in {args.stems}",
                hint="check --stems and --pattern",
            )
        from .alsxml import Doc

        # Id, exact name, or the name without Live's "<index>-" prefix
        master_id = Doc(xml).find_track(args.master_track).attrs["Id"]
        project_dir = Path(args.als).resolve().parent
        master_audio = ist.master_audio_path(xml, master_id, project_dir)
        if not master_audio.exists():
            raise UsageError(
                f"Master audio not found: {master_audio}",
                hint="the .als RelativePath must resolve against the project dir",
            )
        problems = ist.check_stem_invariants(master_audio, stem_paths)
        if problems:
            raise UsageError(
                "Stems do not match the master's frames/samplerate: "
                + ", ".join(p["file"] for p in problems),
                hint="stem import clones the master's warp markers, which is "
                "only valid for identical-length, same-rate audio",
            )
        colors = _load_manifest(args.colors) if args.colors else None
        new_xml, diff = ist.import_stems(
            xml, master_id, stem_paths, project_dir, colors=colors, keep_session=args.keep_session
        )
        out = _als_commit(args, new_xml, diff, "import-stems")
    else:
        raise SystemExit(
            "als requires a subcommand: inspect | validate | rename | move | "
            "warp-to-grid | move-clip | snap | import-stems"
        )
    _emit(out, args.json, lambda o: print(json.dumps(o, indent=2)))
    return 0


def _add_arg(parser: argparse.ArgumentParser, a: dict[str, Any]) -> None:
    """Translate one SPEC arg dict into an argparse add_argument call."""
    name = a["name"]
    kwargs: dict[str, Any] = {}
    if a.get("help"):
        kwargs["help"] = a["help"]
    if a.get("action"):
        kwargs["action"] = a["action"]
    else:
        if a.get("type") is not None:
            kwargs["type"] = a["type"]
        kwargs["default"] = a.get("default")
    if name.startswith("-"):  # optional flag
        if a.get("required") and not a.get("action"):
            kwargs["required"] = True
    elif name == "files":  # variadic positional
        kwargs["nargs"] = "+"
    parser.add_argument(name, **kwargs)


def build_parser() -> argparse.ArgumentParser:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        _v = _pkg_version("ableton-tools")
    except PackageNotFoundError:
        _v = "unknown"
    p = argparse.ArgumentParser(prog="ableton", description="Ableton project tools")
    p.add_argument("--version", action="version", version=f"ableton {_v}")
    sub = p.add_subparsers(dest="cmd", required=True)
    for entry in SPEC:
        sp = sub.add_parser(
            entry["name"], help=entry.get("desc", ""), description=entry.get("desc", "")
        )
        if "subcommands" in entry:
            nsub = sp.add_subparsers(dest=f"{entry['name']}_cmd", required=True)
            for child in entry["subcommands"]:
                csp = nsub.add_parser(
                    child["name"], help=child.get("desc", ""), description=child.get("desc", "")
                )
                for a in child.get("args", []):
                    _add_arg(csp, a)
        else:
            for a in entry.get("args", []):
                _add_arg(sp, a)
    return p


DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "manifest": _cmd_manifest,
    "stem-verify": _cmd_stem_verify,
    "tempo": _cmd_tempo,
    "drift": _cmd_drift,
    "midi": _cmd_midi,
    "als": _cmd_als,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["help"]:
        rest = argv[1:]
        if rest:
            argv = rest + ["--help"]  # argparse prints sub-help, SystemExit(0)
        else:
            build_parser().print_help()
            return 0
    global_json = "--json" in argv
    if global_json:
        argv = [a for a in argv if a != "--json"]
    if argv and not argv[0].startswith("-") and argv[0] not in DISPATCH:
        sys.stderr.write(
            f"Unknown subcommand {argv[0]!r}. Valid: {', '.join(DISPATCH)}. "
            "Run `ableton manifest` for descriptions.\n"
        )
        return 2
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = getattr(args, "json", False) or global_json
    try:
        return DISPATCH[args.cmd](args)
    except UsageError as e:
        payload: dict[str, Any] = {"error": str(e), "hint": e.hint}
        if e.kind:
            payload["kind"] = e.kind
        if getattr(args, "json", False):
            sys.stderr.write(json.dumps(payload) + "\n")
        else:
            sys.stderr.write(f"error: {e}\n")
            if e.hint:
                sys.stderr.write(f"hint: {e.hint}\n")
        return e.exit_code
    except FileNotFoundError as e:
        payload = {"error": str(e), "hint": "check the file path"}
        if getattr(args, "json", False):
            sys.stderr.write(json.dumps(payload) + "\n")
        else:
            sys.stderr.write(f"error: {e}\nhint: check the file path\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
