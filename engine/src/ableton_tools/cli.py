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
    nargs: str | None = None,
    choices: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": required,
        "default": default,
        "help": help,
        "type": type,
        "action": action,
        "nargs": nargs,
        "choices": choices,
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
        "name": "levels",
        "desc": "Per-file duration, rate, dBFS, silence flag (and r vs --ref).",
        "args": [_arg("folder", required=True), _arg("--pattern", default="*.wav"),
                 _arg("--ref", help="reference file for lag-0 correlation"), _JSON],
    },
    {
        "name": "locate",
        "desc": "Find where a fragment occurs inside a reference (offset + r).",
        "args": [_arg("--fragment", required=True), _arg("--ref", required=True),
                 _arg("--env-hz", type=float, default=100.0), _arg("--top", type=int, default=3),
                 _JSON],
    },
    {
        "name": "warp-check",
        "desc": "EXPERIMENTAL: do the master's warp markers sit on real beats, and do "
        "warped clips share its map?",
        "args": [_arg("als", required=True), _arg("--track"),
                 _arg("--audio", help="audio to analyze (default: the clip's sample)"), _JSON],
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
                    _arg(
                        "--tolerance-ms",
                        type=float,
                        help="relaxed check: allow length differences up to N ms and any "
                        "sample rate; measure each stem's start lag against the master",
                    ),
                    _arg("--to", default="arrangement", choices=["arrangement", "session"],
                         help="place stems in the Arrangement (default) or Session slot 1"),
                    _arg("--unwarped", action="store_true",
                         help="import unwarped (native speed; for un-synced takes)"),
                    _arg("--mute-below", type=float, help="import stems quieter than N dBFS muted"),
                    _arg("--skip-below", type=float, help="skip stems quieter than N dBFS"),
                    _COMMIT,
                    _FORCE,
                    _JSON,
                ],
            },
            {
                "name": "set-tempo",
                "desc": "Set the project tempo (Main/Master track).",
                "args": [_arg("als", required=True), _arg("bpm", required=True, type=float),
                         _COMMIT, _FORCE, _JSON],
            },
            {
                "name": "mute",
                "desc": "Mute (or --unmute) tracks.",
                "args": [_arg("als", required=True),
                         _arg("--tracks", required=True, nargs="+"),
                         _arg("--unmute", action="store_true"), _COMMIT, _FORCE, _JSON],
            },
            {
                "name": "add-track",
                "desc": "Add a bare audio track (no clips/devices/automation).",
                "args": [_arg("als", required=True), _arg("--name", required=True),
                         _arg("--color", type=int), _arg("--after", help="insert after track"),
                         _COMMIT, _FORCE, _JSON],
            },
            {
                "name": "group",
                "desc": "Fold contiguous tracks into a group (members routed to the group bus).",
                "args": [_arg("als", required=True), _arg("--name", required=True),
                         _arg("--tracks", required=True, nargs="+"), _arg("--color", type=int),
                         _COMMIT, _FORCE, _JSON],
            },
            {
                "name": "sync-to-master",
                "desc": "Copy the master clip's arrangement position (and optionally warp "
                "markers) onto other tracks' warped clips.",
                "args": [_arg("als", required=True), _arg("--master", required=True),
                         _arg("--tracks", nargs="+"), _arg("--all-warped", action="store_true"),
                         _arg("--markers", action="store_true",
                              help="also copy the master's warp markers"),
                         _COMMIT, _FORCE, _JSON],
            },
            {
                "name": "transplant-devices",
                "desc": "EXPERIMENTAL: copy a track's device chain from another set "
                "(plugin state verbatim; ids, routing and file refs fixed up).",
                "args": [_arg("als", required=True, help="target set"),
                         _arg("--from", required=True, help="source set"),
                         _arg("--src-track"), _arg("--src-main", action="store_true"),
                         _arg("--to-track"), _arg("--to-main", action="store_true"),
                         _arg("--mode", default="replace", choices=["replace", "append"]),
                         _arg("--with-automation", action="store_true",
                              help="also copy the source track's automation of these devices"),
                         _arg("--map-track", nargs="*", default=None,
                              help="SRC=DST: point cross-track routing at a target track"),
                         _COMMIT, _FORCE, _JSON],
            },
        ],
    },
]


def _emit(obj: Any, as_json: bool, human: Callable[[Any], Any]) -> None:
    if as_json:
        # allow_nan=False: NaN/Infinity are not JSON; fail loudly rather than emit them
        print(json.dumps(obj, indent=2, allow_nan=False))
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


def _cmd_levels(args: argparse.Namespace) -> int:
    from . import analysis

    out = analysis.levels(args.folder, pattern=args.pattern, ref=args.ref)
    _emit(out, args.json, lambda o: [
        print(f"{Path(f['file']).name:40s} {f['dbfs']:7.1f} dBFS {f['duration_s']:8.2f}s"
              + ("  SILENT" if f["silent"] else "")
              + (f"  r={f['r_vs_ref']}" if "r_vs_ref" in f else ""))
        for f in o["files"]])
    return 0


def _cmd_locate(args: argparse.Namespace) -> int:
    from . import analysis

    out = analysis.locate(args.fragment, args.ref, env_hz=args.env_hz, top=args.top)
    _emit(out, args.json, lambda o: print(
        f"{o['band']}: " + ", ".join(f"{m['offset_s']}s (r={m['r']})" for m in o["matches"])))
    return 0


def _cmd_warp_check(args: argparse.Namespace) -> int:
    from . import analysis

    out = analysis.warp_check(args.als, track=args.track, audio_path=args.audio)
    _emit(out, args.json, lambda o: print(
        f"warp-map bpm={o['warp_map_bpm']} markers={o['marker_count']} "
        f"beat-align median={o['beat_alignment_ms']['median']}ms "
        f"shared={len(o['sync']['shared'])} differs={o['sync']['differs']}"))
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
        timeline = None
        if args.unwarped:
            problems = []  # un-synced takes: no shared warp map, so no timeline to match
        elif args.tolerance_ms is not None:
            problems, timeline = ist.check_timeline(master_audio, stem_paths, args.tolerance_ms)
            if problems:
                raise UsageError(
                    "Stems are not on the master's timeline: "
                    + ", ".join(f"{Path(p['file']).name} (lag {p['lag_ms']} ms, "
                                f"Δlen {p['delta_ms']} ms)" for p in problems),
                    hint="check the stems' start offsets, or raise --tolerance-ms for length",
                    details=timeline,
                )
            problems = []
        else:
            problems = ist.check_stem_invariants(master_audio, stem_paths)
        if problems:
            raise UsageError(
                "Stems do not match the master's frames/samplerate: "
                + ", ".join(p["file"] for p in problems),
                hint="stem import clones the master's warp markers, which is "
                "only valid for identical-length, same-rate audio; for same-timeline "
                "files with padding or a different sample rate, pass --tolerance-ms",
            )
        colors = _load_manifest(args.colors) if args.colors else None
        new_xml, diff = ist.import_stems(
            xml, master_id, stem_paths, project_dir, colors=colors,
            keep_session=args.keep_session, to=args.to, unwarped=args.unwarped,
            mute_below=args.mute_below, skip_below=args.skip_below,
        )
        if timeline is not None:
            diff["timeline"] = timeline
        out = _als_commit(args, new_xml, diff, "import-stems")
    elif args.als_cmd in ("set-tempo", "mute", "add-track", "group", "sync-to-master"):
        from . import session

        if args.als_cmd == "set-tempo":
            new_xml, diff = session.set_tempo_cmd(xml, args.bpm)
        elif args.als_cmd == "mute":
            new_xml, diff = session.mute(xml, args.tracks, unmute=args.unmute)
        elif args.als_cmd == "add-track":
            new_xml, diff = session.add_track(xml, args.name, color=args.color, after=args.after)
        elif args.als_cmd == "group":
            new_xml, diff = session.group(xml, args.name, args.tracks, color=args.color)
        else:
            new_xml, diff = session.sync_to_master(
                xml, args.master, tracks=args.tracks, all_warped=args.all_warped,
                markers=args.markers,
            )
        out = _als_commit(args, new_xml, diff, args.als_cmd)
    elif args.als_cmd == "transplant-devices":
        import shutil

        from . import devices

        mapping = {}
        for pair in args.map_track or []:
            if "=" not in pair:
                raise UsageError(f"--map-track expects SRC=DST, got {pair!r}")
            k, v = pair.split("=", 1)
            mapping[k] = v
        src_path = Path(getattr(args, "from"))
        new_xml, diff = devices.transplant(
            xml, als.read_als(src_path), src_track=args.src_track, src_main=args.src_main,
            to_track=args.to_track, to_main=args.to_main, mode=args.mode,
            with_automation=args.with_automation, map_track=mapping,
            target_dir=Path(args.als).resolve().parent, source_dir=src_path.resolve().parent,
        )
        if args.commit:  # files must exist before the post-write project-ref check
            for f in diff["files_copied"]:
                if not Path(f["from"]).exists():
                    raise UsageError(f"source file for a device ref is missing: {f['from']}")
                Path(f["to"]).parent.mkdir(parents=True, exist_ok=True)
                if not Path(f["to"]).exists():
                    shutil.copy2(f["from"], f["to"])
        out = _als_commit(args, new_xml, diff, "transplant-devices")
    else:
        raise SystemExit("als requires a subcommand; run `ableton manifest` to list them")
    _emit(out, args.json, lambda o: print(json.dumps(o, indent=2)))
    return 0


def _add_arg(parser: argparse.ArgumentParser, a: dict[str, Any]) -> None:
    """Translate one SPEC arg dict into an argparse add_argument call."""
    name = a["name"]
    kwargs: dict[str, Any] = {}
    if a.get("help"):
        kwargs["help"] = a["help"]
    if a.get("choices"):
        kwargs["choices"] = a["choices"]
    if a.get("nargs"):
        kwargs["nargs"] = a["nargs"]
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
    "levels": _cmd_levels,
    "locate": _cmd_locate,
    "warp-check": _cmd_warp_check,
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
