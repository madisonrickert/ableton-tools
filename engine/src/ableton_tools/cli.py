"""Single dispatcher for the Ableton tools engine. Every subcommand supports
--json. `manifest` lists all subcommands. Unknown subcommands fail loudly."""

import argparse
import json
import sys

from .errors import UsageError

def _arg(name, *, required=False, default=None, help="", type=None,
         action=None):
    return {"name": name, "required": required, "default": default,
            "help": help, "type": type, "action": action}


_COMMIT = _arg("--commit", action="store_true", help="write (default: dry-run)")
_JSON = _arg("--json", action="store_true", help="JSON output")

# Single source of truth: drives both build_parser() and `manifest --json`, so
# the CLI surface and its self-description can never drift.
SPEC = [
    {"name": "manifest", "desc": "List all subcommands (this command).",
     "args": [_JSON]},
    {"name": "stem-verify",
     "desc": "Measure whether a stems folder sums to a master.",
     "args": [_arg("--stems", required=True), _arg("--master", required=True),
              _arg("--win", type=float, default=10.0),
              _arg("--max-lag-ms", type=float, default=200.0),
              _arg("--pattern", default="*.wav"), _JSON]},
    {"name": "tempo",
     "desc": "Detect tempo, sub-ms precision, and drift of an audio file.",
     "args": [_arg("file", required=True),
              _arg("--hint-bpm", type=float, default=None), _JSON]},
    {"name": "drift",
     "desc": "Measure time drift between a master and its stems-sum.",
     "args": [_arg("--master", required=True), _arg("--stems", required=True),
              _arg("--win", type=float, default=10.0),
              _arg("--pattern", default="*.wav"), _JSON]},
    {"name": "midi", "desc": "MIDI tools.", "subcommands": [
        {"name": "transcribe", "desc": "Audio -> MIDI via basic-pitch.",
         "args": [_arg("audio", required=True),
                  _arg("--out", default=None), _JSON]},
        {"name": "compare", "desc": "Chroma similarity + timing drift.",
         "args": [_arg("files", required=True, help="2-3 MIDI files"), _JSON]},
    ]},
    {"name": "als", "desc": "Inspect/edit a .als.", "subcommands": [
        {"name": "inspect", "desc": "Tempo, tracks, clips, refs as JSON.",
         "args": [_arg("als", required=True), _JSON]},
        {"name": "rename", "desc": "Patch file references per manifest.",
         "args": [_arg("als", required=True),
                  _arg("--manifest", required=True), _COMMIT, _JSON]},
        {"name": "move", "desc": "Alias of rename.",
         "args": [_arg("als", required=True),
                  _arg("--manifest", required=True), _COMMIT, _JSON]},
        {"name": "warp-to-grid", "desc": "Grid-lock clips at a fixed tempo.",
         "args": [_arg("als", required=True),
                  _arg("--tempo", required=True, type=float),
                  _arg("--clips", required=True), _COMMIT, _JSON]},
        {"name": "move-clip", "desc": "Move one clip to an exact beat.",
         "args": [_arg("als", required=True), _arg("--clip", required=True),
                  _arg("--to-beat", required=True, type=float),
                  _arg("--dur-s", required=True, type=float),
                  _arg("--bpm", required=True, type=float), _COMMIT, _JSON]},
        {"name": "snap", "desc": "Batch clip repositioning per manifest.",
         "args": [_arg("als", required=True),
                  _arg("--manifest", required=True), _COMMIT, _JSON]},
        {"name": "import-stems",
         "desc": "Clone a warped master track per stem file and relink.",
         "args": [_arg("als", required=True),
                  _arg("--master-track", required=True,
                       help="master AudioTrack Id or EffectiveName"),
                  _arg("--stems", required=True),
                  _arg("--pattern", default="*.wav"),
                  _arg("--colors", default=None,
                       help="JSON {label: color_int} overriding the built-in map"),
                  _COMMIT, _JSON]},
    ]},
]


def _emit(obj, as_json, human):
    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        human(obj)


def _manifest_entry(c):
    out = {"name": c["name"], "desc": c.get("desc", "")}
    if "args" in c:
        out["args"] = [{k: a[k] for k in ("name", "required", "default", "help")}
                       for a in c["args"]]
    if "subcommands" in c:
        out["subcommands"] = [_manifest_entry(s) for s in c["subcommands"]]
    return out


def _cmd_manifest(args):
    entries = [_manifest_entry(c) for c in SPEC]
    _emit({"subcommands": entries}, args.json,
          lambda o: [print(f"{c['name']:14} {c['desc']}") for c in o["subcommands"]])
    return 0


def _cmd_stem_verify(args):
    from . import cancel
    out = cancel.stem_verify(args.master, args.stems, win_s=args.win,
                             max_lag_ms=args.max_lag_ms, pattern=args.pattern)
    _emit(out, args.json, lambda o: print(
        f"worst={o['worst_db']:.1f}dB median={o['median_db']:.1f}dB "
        f"lag={o['lag_ms']:.1f}ms r={o['pearson_r']}"))
    return 0


def _cmd_tempo(args):
    from . import tempo
    out = tempo.analyze(args.file, hint_bpm=args.hint_bpm)
    _emit(out, args.json, lambda o: print(
        f"bpm={o.get('bpm')} precise={o.get('precise_bpm')} drift={o.get('bpm_drift_total')}"))
    return 0


def _cmd_drift(args):
    from . import audio, align, cancel
    master, sr = audio.load_mono(args.master)
    mix, _, names = audio.sum_stems(args.stems, target_sr=sr, pattern=args.pattern)
    # per-window lag trace
    win = int(args.win * sr)
    m = min(len(master), len(mix))
    rows = []
    for start in range(0, m - win + 1, win):
        r = master[start:start + win]
        s = mix[start:start + win]
        lag, alpha, rr = align.find_lag(r, s, sr, search_s=0.2, refine=int(0.05 * sr))
        rows.append({"t_s": round(start / sr, 2), "lag_ms": round(lag / sr * 1000, 3),
                     "resid_ratio": round(rr, 5)})
    drift_ms = rows[-1]["lag_ms"] - rows[0]["lag_ms"] if len(rows) >= 2 else 0.0
    out = {"master": args.master, "stems_dir": args.stems, "stem_files": names,
           "windows": rows, "total_drift_ms": round(drift_ms, 3)}
    _emit(out, args.json, lambda o: print(
        f"total drift over file: {o['total_drift_ms']:.1f} ms across {len(o['windows'])} windows"))
    return 0


def _cmd_midi(args):
    from . import midi, transcribe
    if args.midi_cmd == "transcribe":
        out_path = transcribe.transcribe(args.audio, out_path=args.out)
        _emit({"output": out_path}, args.json, lambda o: print(o["output"]))
        return 0
    if args.midi_cmd == "compare":
        out = midi.compare(args.files)
        _emit(out, args.json, lambda o: [
            print(f"{p['a']} vs {p['b']}: chroma={p['chroma_cosine']} "
                  f"offset={p.get('drift_offset_s')}s slope={p.get('drift_slope_s_per_s')}")
            for p in o["pairs"]])
        return 0
    raise SystemExit("midi requires a subcommand: transcribe | compare")


def _load_manifest(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise UsageError(f"Manifest file not found: {path}",
                         hint="pass an existing JSON file") from None
    except json.JSONDecodeError as e:
        raise UsageError(f"Manifest is not valid JSON: {path} ({e})",
                         hint="fix the JSON syntax") from None


def _als_commit(args, new_xml, diff, op):
    """Shared commit/dry-run logic for mutating als subcommands."""
    from . import als
    if not args.commit:
        return {"dry_run": True, "op": op, "diff": diff,
                "note": "re-run with --commit to write (a timestamped backup is made first)"}
    backup_path = als.backup(args.als, op)
    als.write_als(args.als, new_xml)
    base = str(__import__("pathlib").Path(args.als).parent)
    missing = als.verify_refs(new_xml, base)
    if missing:
        als.write_als(args.als, als.read_als(backup_path))  # restore
        return {"committed": False, "restored_from": backup_path,
                "error": "broken refs after patch", "missing_refs": missing}
    return {"committed": True, "backup": backup_path, "op": op, "diff": diff}


def _cmd_als(args):
    from . import als
    if args.als_cmd == "inspect":
        _emit(als.inspect(args.als), args.json, lambda o: print(
            f"tempo={o['tempo']} tracks={len(o['tracks'])} clips={len(o['clips'])}"))
        return 0
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
        spec = _load_manifest(args.manifest)  # {clip_name: {beat, dur_s, bpm}}
        new_xml = xml
        diffs = []
        for name, v in spec.items():
            new_xml, d = als.move_clip_to_beat(new_xml, name, v["beat"], v["dur_s"], v["bpm"])
            diffs.append(d)
        out = _als_commit(args, new_xml, {"snaps": diffs}, "snap")
    elif args.als_cmd == "import-stems":
        from . import import_stems as ist
        from pathlib import Path
        stem_paths = sorted(Path(args.stems).glob(args.pattern))
        if not stem_paths:
            raise UsageError(
                f"No files matching {args.pattern!r} in {args.stems}",
                hint="check --stems and --pattern")
        master_id = args.master_track
        if not master_id.isdigit():  # resolve EffectiveName -> Id
            tracks = als.inspect_xml(xml)["tracks"]
            hits = [t["id"] for t in tracks if t["name"] == master_id]
            if len(hits) != 1:
                raise UsageError(
                    f"Track name {master_id!r} matched {len(hits)} tracks",
                    hint="pass the numeric track Id from `ableton als inspect`")
            master_id = hits[0]
        project_dir = Path(args.als).resolve().parent
        master_audio = ist.master_audio_path(xml, master_id, project_dir)
        if not master_audio.exists():
            raise UsageError(
                f"Master audio not found: {master_audio}",
                hint="the .als RelativePath must resolve against the project dir")
        problems = ist.check_stem_invariants(master_audio, stem_paths)
        if problems:
            raise UsageError(
                "Stems do not match the master's frames/samplerate: "
                + ", ".join(p["file"] for p in problems),
                hint="stem import clones the master's warp markers, which is "
                     "only valid for identical-length, same-rate audio")
        colors = _load_manifest(args.colors) if args.colors else None
        new_xml, diff = ist.import_stems(xml, master_id, stem_paths,
                                         project_dir, colors=colors)
        out = _als_commit(args, new_xml, diff, "import-stems")
    else:
        raise SystemExit("als requires a subcommand: inspect | rename | move | "
                         "warp-to-grid | move-clip | snap | import-stems")
    _emit(out, args.json, lambda o: print(json.dumps(o, indent=2)))
    return 0


def _add_arg(parser, a):
    """Translate one SPEC arg dict into an argparse add_argument call."""
    name = a["name"]
    kwargs = {}
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


def build_parser():
    from importlib.metadata import PackageNotFoundError, version as _pkg_version
    try:
        _v = _pkg_version("ableton-tools")
    except PackageNotFoundError:
        _v = "unknown"
    p = argparse.ArgumentParser(prog="ableton", description="Ableton project tools")
    p.add_argument("--version", action="version", version=f"ableton {_v}")
    sub = p.add_subparsers(dest="cmd", required=True)
    for entry in SPEC:
        sp = sub.add_parser(entry["name"], help=entry.get("desc", ""),
                            description=entry.get("desc", ""))
        if "subcommands" in entry:
            nsub = sp.add_subparsers(dest=f"{entry['name']}_cmd", required=True)
            for child in entry["subcommands"]:
                csp = nsub.add_parser(child["name"], help=child.get("desc", ""),
                                      description=child.get("desc", ""))
                for a in child.get("args", []):
                    _add_arg(csp, a)
        else:
            for a in entry.get("args", []):
                _add_arg(sp, a)
    return p


DISPATCH = {
    "manifest": _cmd_manifest,
    "stem-verify": _cmd_stem_verify,
    "tempo": _cmd_tempo,
    "drift": _cmd_drift,
    "midi": _cmd_midi,
    "als": _cmd_als,
}


def main(argv=None):
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
        payload = {"error": str(e), "hint": e.hint}
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
