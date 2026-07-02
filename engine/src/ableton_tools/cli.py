"""Single dispatcher for the Ableton tools engine. Every subcommand supports
--json. `manifest` lists all subcommands. Unknown subcommands fail loudly."""

import argparse
import json
import sys

from .errors import UsageError

SUBCOMMANDS = [
    {"name": "stem-verify", "desc": "Measure whether a stems folder sums to a master."},
    {"name": "tempo", "desc": "Detect tempo, sub-ms precision, and drift of an audio file."},
    {"name": "drift", "desc": "Measure time drift between a master and its stems-sum."},
    {"name": "midi", "desc": "MIDI tools: `transcribe` audio->MIDI, `compare` MIDI files."},
    {"name": "als", "desc": "Inspect/edit a .als: inspect, rename, move, warp-to-grid, move-clip, snap, import-stems."},
    {"name": "manifest", "desc": "List all subcommands (this command)."},
]


def _emit(obj, as_json, human):
    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        human(obj)


def _cmd_manifest(args):
    _emit({"subcommands": SUBCOMMANDS}, args.json,
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


def build_parser():
    p = argparse.ArgumentParser(prog="ableton", description="Ableton project tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("manifest").add_argument("--json", action="store_true")

    sv = sub.add_parser("stem-verify")
    sv.add_argument("--stems", required=True)
    sv.add_argument("--master", required=True)
    sv.add_argument("--win", type=float, default=10.0)
    sv.add_argument("--max-lag-ms", type=float, default=200.0)
    sv.add_argument("--pattern", default="*.wav")
    sv.add_argument("--json", action="store_true")

    tp = sub.add_parser("tempo")
    tp.add_argument("file")
    tp.add_argument("--hint-bpm", type=float, default=None)
    tp.add_argument("--json", action="store_true")

    dr = sub.add_parser("drift")
    dr.add_argument("--master", required=True)
    dr.add_argument("--stems", required=True)
    dr.add_argument("--win", type=float, default=10.0)
    dr.add_argument("--pattern", default="*.wav")
    dr.add_argument("--json", action="store_true")

    md = sub.add_parser("midi")
    mdsub = md.add_subparsers(dest="midi_cmd", required=True)
    tr = mdsub.add_parser("transcribe")
    tr.add_argument("audio")
    tr.add_argument("--out", default=None)
    tr.add_argument("--json", action="store_true")
    cmp = mdsub.add_parser("compare")
    cmp.add_argument("files", nargs="+")
    cmp.add_argument("--json", action="store_true")

    al = sub.add_parser("als")
    alsub = al.add_subparsers(dest="als_cmd", required=True)
    insp = alsub.add_parser("inspect"); insp.add_argument("als"); insp.add_argument("--json", action="store_true")
    for nm in ("rename", "move"):
        sp = alsub.add_parser(nm)
        sp.add_argument("als"); sp.add_argument("--manifest", required=True)
        sp.add_argument("--commit", action="store_true"); sp.add_argument("--json", action="store_true")
    w = alsub.add_parser("warp-to-grid")
    w.add_argument("als"); w.add_argument("--tempo", type=float, required=True)
    w.add_argument("--clips", required=True)
    w.add_argument("--commit", action="store_true"); w.add_argument("--json", action="store_true")
    mc = alsub.add_parser("move-clip")
    mc.add_argument("als"); mc.add_argument("--clip", required=True)
    mc.add_argument("--to-beat", type=float, required=True); mc.add_argument("--dur-s", type=float, required=True)
    mc.add_argument("--bpm", type=float, required=True)
    mc.add_argument("--commit", action="store_true"); mc.add_argument("--json", action="store_true")
    sn = alsub.add_parser("snap")
    sn.add_argument("als"); sn.add_argument("--manifest", required=True)
    sn.add_argument("--commit", action="store_true"); sn.add_argument("--json", action="store_true")
    ims = alsub.add_parser("import-stems")
    ims.add_argument("als")
    ims.add_argument("--master-track", required=True,
                     help="master AudioTrack Id, or its EffectiveName")
    ims.add_argument("--stems", required=True, help="directory of stem files")
    ims.add_argument("--pattern", default="*.wav")
    ims.add_argument("--colors", default=None,
                     help="JSON file {label: color_int} overriding the built-in map")
    ims.add_argument("--commit", action="store_true")
    ims.add_argument("--json", action="store_true")
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
    parser = build_parser()
    if argv and argv[0] not in DISPATCH:
        sys.stderr.write(
            f"Unknown subcommand {argv[0]!r}. Valid: {', '.join(DISPATCH)}. "
            "Run `ableton manifest` for descriptions.\n"
        )
        return 2
    args = parser.parse_args(argv)
    # default args.json to False if a subcommand lacked the flag path
    if not hasattr(args, "json"):
        args.json = False
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
