"""Transplant a track's device chain from one Live set into another (experimental).

Grounded in a survey of 153 real Live 11/12 sets / 2,124 chains:

* The track-level chain is always <track>/DeviceChain/DeviceChain/Devices; racks
  nest their own chains deeper (37% of chains), so it is located structurally.
* No live pointers exist inside a chain (only <Pointee Value="0">), so offsetting
  every Id="N" (rack branches included) above the target's max Id is safe.
  ParameterId/UniqueId/LomId are device-internal and never touched.
* Routing targets reference tracks by Id: "AudioIn/Track.<Id>/...". Most
  (195/298) are SELF refs (rack-internal DeviceIn/DeviceOut routing) and are
  remapped to the destination track; their device/branch numbers are the
  chain's own Id attributes, so they move by the same offset as the Ids;
  cross-track refs are reset to None unless --map-track says where they go.
* Automation lives outside the chain (track envelopes pointing in): dropped by
  default (reported), copied with with_automation (PointeeIds remapped).
* File refs by RelativePathType: 5/6/7 resolve from Live's libraries; 3 (source
  project) is copied into the target's Samples/Imported/ and repointed; 1 is
  warned when missing.

Plugin state is copied byte-for-byte.
"""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any

from .alsxml import Doc, Node, offset_block, offset_ids, set_next_pointee
from .errors import InternalError, UsageError
from .validate import dangling_device_routes

_ROUTE = re.compile(r"^(AudioIn|AudioOut|MidiIn|MidiOut)/Track\.(\d+)/(.*)$")
_NONE_DISPLAY = {"AudioIn": "No Output", "AudioOut": "No Output", "MidiIn": "No Output",
                 "MidiOut": "None"}
_WRAP_OPEN, _WRAP_CLOSE = b"<Devices>", b"</Devices>"


def shift_device_path(rest: str, off: int) -> str:
    """"DeviceOut.6.B0,3.B1,ChainOut" -> every device and branch number + off.
    Those numbers are the Id attributes of the devices and branches inside the
    chain (verified on 195/195 real self routes), which the transplant offsets
    by `off`, so the route must move with them."""
    head, _, path = rest.partition(".")
    if not head.startswith("Device") or not path:
        return rest
    steps = [re.sub(r"^\d+|(?<=[BR])\d+", lambda m: str(int(m.group(0)) + off), step)
             for step in path.split(",")]
    return f"{head}.{','.join(steps)}"


def _track(doc: Doc, name: str | None, main: bool, role: str) -> Node:
    if main:
        return doc.main_track()
    if not name:
        raise UsageError(f"pass --{role}-track NAME or --{role}-main")
    return doc.find_track(name)


def _plugin_report(chain: Doc) -> list[dict[str, Any]]:
    out = []
    for dev in chain.nodes("PluginDevice") + chain.nodes("AuPluginDevice"):
        desc = dev.child("PluginDesc")
        info = desc.children()[0] if desc is not None and desc.children() else None
        if info is None:
            continue
        fmt = {"Vst3PluginInfo": "VST3", "VstPluginInfo": "VST2",
               "AuPluginInfo": "AU"}.get(info.tag, info.tag)
        name_node = info.child("Name") or info.child("PlugName")
        name = name_node.value() if name_node is not None else ""
        out.append({"name": name, "format": fmt, "found": _plugin_found(fmt, name, info)})
    return out


def _plugin_found(fmt: str, name: str | None, info: Node) -> bool | None:
    if platform.system() != "Darwin" or not name:
        return None
    path = info.child("Path")
    if fmt == "VST2" and path is not None and path.value():
        return Path(path.value() or "").exists()
    sub, ext = {"VST3": ("VST3", ".vst3"), "AU": ("Components", ".component"),
                "VST2": ("VST", ".vst")}.get(fmt, ("", ""))
    if not sub:
        return None
    roots = [Path("/Library/Audio/Plug-Ins") / sub, Path.home() / "Library/Audio/Plug-Ins" / sub]
    return any((r / f"{name}{ext}").exists() for r in roots)


def _plan_copy(rel: str, source_dir: str | Path | None, target_dir: str | Path | None,
               taken: set[str]) -> dict[str, Any]:
    """Where a project-relative file lands in the target: Samples/Imported/<name>.
    An identical file already there is reused (`existing`); a different one
    keeps its name and the copy becomes "<stem> (2)<ext>", "(3)", ..."""
    import filecmp

    name = Path(rel)
    src = Path(source_dir) / rel if source_dir else None
    n = 1
    while True:
        cand = name.name if n == 1 else f"{name.stem} ({n}){name.suffix}"
        dest_rel = f"Samples/Imported/{cand}"
        dest = Path(target_dir) / dest_rel if target_dir else None
        if dest_rel in taken:
            n += 1
            continue
        if dest is None or not dest.exists():
            existing = False
            break
        if src is not None and src.exists() and filecmp.cmp(src, dest, shallow=False):
            existing = True
            break
        n += 1
    return {"from": str(src) if src else rel, "to": str(dest) if dest else dest_rel,
            "rel": dest_rel, "existing": existing}


def transplant(
    target_xml: str,
    source_xml: str | Doc,
    *,
    src_track: str | None = None,
    src_main: bool = False,
    to_track: str | None = None,
    to_main: bool = False,
    mode: str = "replace",
    with_automation: bool = False,
    map_track: dict[str, str] | None = None,
    target_dir: str | Path | None = None,
    source_dir: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Copy the source track's device chain onto the target track. Returns
    (new_target_xml, diff). `diff["files_copied"]` is a copy plan
    ({from, to, existing}); the caller copies the files that are not
    `existing`, only when committing, after the commit guards pass."""
    if mode not in ("replace", "append"):
        raise UsageError(f"--mode must be 'replace' or 'append', not {mode!r}")
    sdoc = source_xml if isinstance(source_xml, Doc) else Doc(source_xml)
    tdoc = Doc(target_xml)
    src = _track(sdoc, src_track, src_main, "src")
    dst = _track(tdoc, to_track, to_main, "to")
    sdevs = sdoc.effects_devices(src)
    kids = sdevs.children()
    if not kids:
        raise UsageError(f"source track {sdoc.track_name(src) or src.tag!r} has no devices")
    raw_chain = sdoc.data[kids[0].start : kids[-1].end]
    tdevs = tdoc.effects_devices(dst)
    existing = tdevs.children() if mode == "append" else []
    off = tdoc.id_base()

    # ---- ids ----
    chain_target_ids = {n.attrs["Id"] for k in kids for n in _descendants(k)
                        if n.tag.endswith("Target") and "Id" in n.attrs}
    chain = offset_block(raw_chain, off)

    # ---- routing ----
    src_id = src.attrs.get("Id")
    dst_id = dst.attrs.get("Id")
    mapped_ids: dict[str, str] = {}
    for s_name, t_name in (map_track or {}).items():
        mapped_ids[sdoc.find_track(s_name).attrs["Id"]] = tdoc.find_track(t_name).attrs["Id"]
    wrapped = Doc(_WRAP_OPEN + chain + _WRAP_CLOSE)
    self_remapped, reset, mapped = [], [], []
    for tnode in wrapped.nodes("Target"):
        m = _ROUTE.match(tnode.value() or "")
        if m is None:
            continue
        kind, tid, rest = m.groups()
        parent = tnode.parent
        upper = parent.child("UpperDisplayString") if parent is not None else None
        lower = parent.child("LowerDisplayString") if parent is not None else None
        if tid == src_id and dst_id is not None:
            new = f"{kind}/Track.{dst_id}/{shift_device_path(rest, off)}"
            wrapped.set_value(tnode, new)
            if upper is not None:
                wrapped.set_value(upper, tdoc.track_name(dst))
            self_remapped.append({"from": tnode.value(), "to": new})
        elif tid in mapped_ids:
            new = f"{kind}/Track.{mapped_ids[tid]}/{rest}"
            wrapped.set_value(tnode, new)
            if upper is not None:
                wrapped.set_value(upper, tdoc.track_name(tdoc.track_by_id(mapped_ids[tid])))
            mapped.append({"from": tnode.value(), "to": new})
        else:
            wrapped.set_value(tnode, f"{kind}/None")
            if upper is not None:
                wrapped.set_value(upper, _NONE_DISPLAY[kind])
            if lower is not None:
                wrapped.set_value(lower, "")
            reset.append({"from": tnode.value(), "note": "re-assign in Live"})
    wrapped = wrapped.apply()

    # ---- file refs ----
    warnings: list[str] = []
    files: list[dict[str, Any]] = []
    dest_for: dict[str, str] = {}  # source rel -> target rel
    for ref in wrapped.nodes("FileRef"):
        kind_n = ref.child("RelativePathType")
        k = kind_n.value() if kind_n is not None else None
        rel_n, path_n = ref.child("RelativePath"), ref.child("Path")
        if k == "3" and rel_n is not None and rel_n.value():
            rel = rel_n.value() or ""
            if rel not in dest_for:
                plan = _plan_copy(rel, source_dir, target_dir, set(dest_for.values()))
                dest_for[rel] = plan.pop("rel")
                files.append(plan)
            dest_rel = dest_for[rel]
            wrapped.set_value(rel_n, dest_rel)
            if path_n is not None:
                wrapped.set_value(path_n, str(Path(target_dir) / dest_rel) if target_dir
                                  else dest_rel)
        elif k == "1" and path_n is not None and path_n.value() \
                and not Path(path_n.value() or "").exists():
            warnings.append(f"external file not found: {path_n.value()}")
    wrapped = wrapped.apply()
    plugins = _plugin_report(wrapped)
    for p in plugins:
        if p["found"] is False:
            warnings.append(f"{p['format']} plugin {p['name']!r} not found on this machine "
                            "(Live will show a placeholder)")
    chain = wrapped.data[len(_WRAP_OPEN) : -len(_WRAP_CLOSE)]

    target_ids = {t.attrs.get("Id") for t in tdoc.tracks()}
    for tid in re.findall(rb"Track\.(\d+)/", chain):
        if tid.decode() not in target_ids:
            raise UsageError(f"internal: routing still points at missing track {tid.decode()}")

    # ---- place ----
    if existing:
        tdoc.insert_after(existing[-1], b"\n" + chain)
    else:
        tdoc.replace(tdevs, b"<Devices>\n" + chain + b"\n</Devices>")

    # ---- automation ----
    envs = src.path("AutomationEnvelopes/Envelopes")
    pointing = []
    for env in envs.children() if envs is not None else []:
        p = env.path("EnvelopeTarget/PointeeId")
        if p is not None and p.value() in chain_target_ids:
            pointing.append(env)
    # In replace mode the target's own devices disappear: drop its automation of
    # them, or those lanes would point at targets that no longer exist.
    replaced_ids = set() if mode == "append" else {
        n.attrs["Id"] for d in tdevs.children() for n in _descendants(d)
        if n.tag.endswith("Target") and "Id" in n.attrs}
    tenv = dst.path("AutomationEnvelopes/Envelopes")
    kept, removed = [], 0
    for env in tenv.children() if tenv is not None else []:
        p = env.path("EnvelopeTarget/PointeeId")
        if p is not None and p.value() in replaced_ids:
            removed += 1
        else:
            kept.append(env)
    copied = 0
    pieces: list[bytes] = []
    if with_automation and pointing:
        if tenv is None:
            warnings.append("target has no AutomationEnvelopes; automation not copied")
        else:
            next_id = max((int(e.attrs.get("Id", "0")) for e in kept), default=-1) + 1
            for i, env in enumerate(pointing):
                e = Doc(offset_ids(env.text(sdoc), off))
                e.set_attr(e.root, "Id", next_id + i)
                pt = e.root.path("EnvelopeTarget/PointeeId")
                if pt is not None:
                    e.set_value(pt, int(pt.value() or 0) + off)
                pieces.append(e.apply().data)
            copied = len(pieces)
    if tenv is not None and (removed or pieces):
        body = [e.text(tdoc) for e in kept] + pieces
        tdoc.replace(tenv, b"<Envelopes>\n" + b"\n".join(body) + b"\n</Envelopes>"
                     if body else b"<Envelopes />")

    out = set_next_pointee(tdoc.apply())
    broken = [r for r in dangling_device_routes(out)
              if dst_id is not None and f"/Track.{dst_id}/" in r]
    if broken:
        raise InternalError(f"transplanted routing does not resolve: {broken[:3]}")
    return out.to_str(), {
        "source_track": sdoc.track_name(src) or src.tag,
        "target_track": tdoc.track_name(dst) or dst.tag,
        "mode": mode,
        "devices": [k.tag for k in kids],
        "plugins": plugins,
        "routing_self_remapped": self_remapped,
        "routing_mapped": mapped,
        "routing_reset": reset,
        "automation_dropped": len(pointing) - copied,
        "automation_copied": copied,
        "target_automation_removed": removed,
        "files_copied": files,
        "warnings": warnings,
    }


def _descendants(n: Node) -> list[Node]:
    out = [n]
    stack = list(n.children())
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(c.children())
    return out
