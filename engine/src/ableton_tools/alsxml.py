"""Lossless, span-indexed access to Ableton `.als` XML.

One stdlib-expat pass indexes every element by its exact byte span in the
decompressed document. Reads walk that index (direct children only, so a
nested `<ScaleInformation><Name>` is never mistaken for a clip's `<Name>`);
writes are queued as byte splices and applied together, so every byte outside
an edited span is preserved. A no-op `Doc(x).apply().data == x`.

Spans index BYTES, not str: Live sets contain UTF-8 (and emoji) paths.
"""

from __future__ import annotations

import gzip
import re
import xml.parsers.expat
from pathlib import Path
from xml.sax.saxutils import escape

from .errors import UsageError

TRACK_TAGS = frozenset({"AudioTrack", "MidiTrack", "GroupTrack", "ReturnTrack"})
CLIP_TAGS = frozenset({"AudioClip", "MidiClip"})

# A start tag up to and including its closing `>` (quote-aware, so `>` inside
# an attribute value does not end it).
_START_TAG = re.compile(rb"""<[^\s/>]+(?:\s+[^\s=/>]+\s*=\s*(?:"[^"]*"|'[^']*'))*\s*/?>""")
_ID_ATTR = re.compile(rb'(?<=\s)Id="(\d+)"')
_LIVE_INDEX_PREFIX = re.compile(r"^\d+-")


class Node:
    """An element: tag, attributes, exact byte span [start, end), tree links."""

    __slots__ = ("tag", "attrs", "start", "end", "tag_end", "parent", "depth", "index",
                 "_children")

    def __init__(self, tag: str, attrs: dict[str, str], start: int, parent: Node | None,
                 depth: int, index: int) -> None:
        self.tag = tag
        self.attrs = attrs
        self.start = start
        self.end = start
        self.tag_end = start
        self.parent = parent
        self.depth = depth
        self.index = index
        self._children: list[Node] = []

    def __repr__(self) -> str:
        return f"<Node {self.tag} [{self.start}:{self.end}]>"

    def children(self) -> list[Node]:
        return list(self._children)

    def child(self, tag: str) -> Node | None:
        """First DIRECT child with this tag."""
        for c in self._children:
            if c.tag == tag:
                return c
        return None

    def path(self, p: str) -> Node | None:
        """Follow 'A/B/C' through direct children only."""
        node: Node | None = self
        for part in p.split("/"):
            if node is None:
                return None
            node = node.child(part)
        return node

    def find_all(self, tag: str) -> list[Node]:
        """All descendants with this tag, in document order."""
        out: list[Node] = []
        stack = list(reversed(self._children))
        while stack:
            n = stack.pop()
            if n.tag == tag:
                out.append(n)
            stack.extend(reversed(n._children))
        return out

    def value(self) -> str | None:
        return self.attrs.get("Value")

    def ancestors(self) -> list[Node]:
        out: list[Node] = []
        p = self.parent
        while p is not None:
            out.append(p)
            p = p.parent
        return out

    def text(self, doc: Doc) -> bytes:
        return doc.data[self.start : self.end]


class Doc:
    """A decompressed .als document plus its span index and pending edits."""

    def __init__(self, data: bytes | str) -> None:
        self.data: bytes = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._nodes: list[Node] | None = None
        self._edits: list[tuple[int, int, bytes, int]] = []

    # ---------- io ----------
    @classmethod
    def read(cls, path: str | Path) -> Doc:
        with gzip.open(str(path), "rb") as fh:
            return cls(fh.read())

    def to_str(self) -> str:
        return self.data.decode("utf-8")

    def write(self, path: str | Path) -> None:
        with gzip.open(str(path), "wb") as fh:
            fh.write(self.data)

    # ---------- index ----------
    def _index(self) -> list[Node]:
        if self._nodes is not None:
            return self._nodes
        data = self.data
        nodes: list[Node] = []
        stack: list[Node] = []
        parser = xml.parsers.expat.ParserCreate("utf-8")
        parser.buffer_text = True

        def start(tag: str, attrs: dict[str, str]) -> None:
            pos = parser.CurrentByteIndex
            parent = stack[-1] if stack else None
            node = Node(tag, attrs, pos, parent, len(stack), len(nodes))
            m = _START_TAG.match(data, pos)
            if m is None:  # pragma: no cover - expat accepted it, so it is well-formed
                raise ValueError(f"cannot delimit start tag at byte {pos}")
            node.tag_end = m.end()
            nodes.append(node)
            if parent is not None:
                parent._children.append(node)
            stack.append(node)

        def end(tag: str) -> None:
            node = stack.pop()
            if data[node.tag_end - 2 : node.tag_end] == b"/>":
                node.end = node.tag_end  # empty element: <X ... />
            else:
                close = data.index(b">", parser.CurrentByteIndex)
                node.end = close + 1

        parser.StartElementHandler = start
        parser.EndElementHandler = end
        parser.Parse(data, True)
        self._nodes = nodes
        return nodes

    @property
    def root(self) -> Node:
        return self._index()[0]

    def nodes(self, tag: str | None = None) -> list[Node]:
        idx = self._index()
        return [n for n in idx if n.tag == tag] if tag else list(idx)

    # ---------- tracks & clips ----------
    def tracks(self) -> list[Node]:
        """Audio/Midi/Group/Return tracks (children of <Tracks>), document order."""
        return [n for n in self._index() if n.tag in TRACK_TAGS
                and n.parent is not None and n.parent.tag == "Tracks"]

    def main_track(self) -> Node:
        """Live 12 <MainTrack>, else Live 11 <MasterTrack>."""
        for tag in ("MainTrack", "MasterTrack"):
            for n in self._index():
                if n.tag == tag and n.parent is not None and n.parent.tag == "LiveSet":
                    return n
        raise UsageError("No <MainTrack>/<MasterTrack> in this set",
                         hint="is this an Ableton Live set (.als)?")

    def track_by_id(self, tid: str | int) -> Node:
        for t in self.tracks():
            if t.attrs.get("Id") == str(tid):
                return t
        raise UsageError(f"Track Id {tid} not found",
                         hint="run `ableton als inspect FILE.als --json` to list track ids")

    def track_name(self, t: Node) -> str:
        n = t.path("Name/EffectiveName")
        return (n.value() if n is not None else None) or ""

    def find_track(self, name: str) -> Node:
        """Resolve a track by name. Exact EffectiveName wins; then the name with
        Live's '<index>-' prefix stripped; then a unique prefix. Numeric names
        also match a track Id. Ambiguity or no match raises UsageError."""
        tracks = self.tracks()
        if name.isdigit():
            for t in tracks:
                if t.attrs.get("Id") == name:
                    return t
        names = [(t, self.track_name(t)) for t in tracks]
        stripped = [(t, _LIVE_INDEX_PREFIX.sub("", n)) for t, n in names]
        for candidates in (
            [t for t, n in names if n == name],
            [t for t, n in stripped if n == name],
            [t for t, n in stripped if n.startswith(name)],
        ):
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                listed = ", ".join(self.track_name(t) for t in candidates)
                raise UsageError(f"Track name {name!r} is ambiguous ({listed})",
                                 hint="pass the full track name or its numeric Id")
        raise UsageError(f"No track named {name!r}",
                         hint="run `ableton als inspect FILE.als --json` to list track names")

    def _clips_under(self, t: Node, container: str) -> list[Node]:
        out = []
        for n in t.find_all("AudioClip") + t.find_all("MidiClip"):
            tags = [a.tag for a in n.ancestors() if a.depth > t.depth]
            if (container in tags and "MainSequencer" in tags
                    and "FreezeSequencer" not in tags and "TakeLanes" not in tags):
                out.append(n)
        return sorted(out, key=lambda n: n.start)

    def arrangement_clips(self, t: Node) -> list[Node]:
        return self._clips_under(t, "ArrangerAutomation")

    def session_clips(self, t: Node) -> list[Node]:
        return self._clips_under(t, "ClipSlotList")

    def effects_devices(self, t: Node) -> Node:
        """The track-level device chain: <track>/DeviceChain/DeviceChain/Devices
        (rack-safe: rack branches nest their own chains deeper)."""
        devs = t.path("DeviceChain/DeviceChain/Devices")
        if devs is None:
            raise UsageError(f"{t.tag} has no DeviceChain/DeviceChain/Devices",
                             hint="unexpected track layout; inspect the .als")
        return devs

    # ---------- edits ----------
    def _queue(self, start: int, end: int, data: bytes | str) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self._edits.append((start, end, payload, len(self._edits)))

    def set_attr(self, n: Node, name: str, value: object) -> None:
        """Rewrite one attribute's value inside n's start tag."""
        tag = self.data[n.start : n.tag_end]
        m = re.search(rb"(?<=\s)" + re.escape(name.encode()) + rb'\s*=\s*("[^"]*"|\'[^\']*\')',
                      tag)
        if m is None:
            raise UsageError(f"<{n.tag}> has no {name}= attribute to set")
        start = n.start + m.start(1)
        quoted = '"' + escape(_fmt(value), {'"': "&quot;"}) + '"'
        self._queue(start, start + len(m.group(1)), quoted)

    def set_value(self, n: Node, value: object) -> None:
        self.set_attr(n, "Value", value)

    def replace(self, n: Node, data: bytes | str) -> None:
        self._queue(n.start, n.end, data)

    def insert_before(self, n: Node, data: bytes | str) -> None:
        self._queue(n.start, n.start, data)

    def insert_after(self, n: Node, data: bytes | str) -> None:
        self._queue(n.end, n.end, data)

    def remove(self, n: Node) -> None:
        self._queue(n.start, n.end, b"")

    def splice(self, start: int, end: int, data: bytes | str) -> None:
        """Raw splice for callers that computed a span themselves."""
        self._queue(start, end, data)

    def apply(self) -> Doc:
        """Apply queued edits atomically; returns a NEW Doc (re-indexed lazily)."""
        edits = sorted(self._edits, key=lambda e: (e[0], e[1], e[3]))
        out = bytearray()
        pos = 0
        prev_end = -1
        for start, end, payload, _ in edits:
            if start < prev_end:
                raise ValueError(f"overlapping edits at byte {start} (previous ends {prev_end})")
            out += self.data[pos:start]
            out += payload
            pos = end
            prev_end = max(prev_end, end) if end > start else prev_end
        out += self.data[pos:]
        self._edits = []
        return Doc(bytes(out))

    # ---------- ids ----------
    def max_id(self) -> int:
        ids = [int(m) for m in _ID_ATTR.findall(self.data)]
        return max(ids) if ids else 0

    def id_base(self) -> int:
        return ((self.max_id() // 10000) + 1) * 10000


def offset_ids(fragment: bytes | str, offset: int) -> bytes:
    """Add `offset` to every `Id="N"` attribute. Never touches ParameterId,
    UniqueId, LomId or other *Id-named elements/attributes."""
    data = fragment.encode("utf-8") if isinstance(fragment, str) else fragment
    return _ID_ATTR.sub(lambda m: b'Id="%d"' % (int(m.group(1)) + offset), data)


def set_next_pointee(doc: Doc) -> Doc:
    """NextPointeeId = max Id + 1 (Live refuses sets where any Id >= it)."""
    nodes = doc.nodes("NextPointeeId")
    if not nodes:
        return doc
    doc.set_value(nodes[0], doc.max_id() + 1)
    return doc.apply()


def _fmt(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)
