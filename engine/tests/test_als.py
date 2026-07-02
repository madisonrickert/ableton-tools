import gzip
from ableton_tools import als


def test_read_write_roundtrip(als_file):
    p = als_file()
    xml = als.read_als(str(p))
    assert "<Ableton" in xml
    out = p.parent / "out.als"
    als.write_als(str(out), xml)
    assert als.read_als(str(out)) == xml


def test_inspect_reports_tempo_tracks_clips(als_file):
    p = als_file()
    info = als.inspect(str(p))
    assert info["tempo"] == 120.0
    assert any(t["name"] == "Bass" for t in info["tracks"])
    clip = info["clips"][0]
    assert clip["name"] == "bass_clip"
    assert clip["relative_path"] == "Samples/Imported/bass.wav"


def test_set_tempo_changes_value(als_file):
    xml = als.read_als(str(als_file()))
    out = als.set_tempo(xml, 134.0)
    assert 'Manual Value="134' in out
    assert als.inspect_xml(out)["tempo"] == 134.0


def test_rename_refs_updates_paths_and_reports_diff(als_file):
    xml = als.read_als(str(als_file()))
    mapping = {"Samples/Imported/bass.wav": "Samples/Imported/bass_renamed.wav"}
    out, diff = als.rename_refs(xml, mapping)
    assert "bass_renamed.wav" in out
    assert diff["changed"] == 1


def test_move_clip_to_beat_updates_start(als_file):
    xml = als.read_als(str(als_file()))
    out, diff = als.move_clip_to_beat(xml, "bass_clip", beat=8.0, dur_s=7.5, bpm=120.0)
    info = als.inspect_xml(out)
    assert info["clips"][0]["current_start"] == 8.0
    assert diff["clip"] == "bass_clip"


def test_warp_to_grid_sets_two_markers(als_file):
    xml = als.read_als(str(als_file()))
    out, diff = als.warp_to_grid(xml, ["bass_clip"], bpm=120.0, durations={"bass_clip": 8.0})
    assert 'IsWarped Value="true"' in out
    assert diff["warped"] == ["bass_clip"]


def test_verify_refs_flags_missing(als_file, tmp_path):
    xml = als.read_als(str(als_file()))
    missing = als.verify_refs(xml, base_dir=str(tmp_path))
    assert "Samples/Imported/bass.wav" in missing


_REALISTIC_ALS = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="3" Creator="Ableton Live 11.3">
<LiveSet>
<NextPointeeId Value="100"/>
<Tracks>
<AudioTrack Id="14" SelectedToolPanel="3" SelectedTransformationName="" SelectedGeneratorName="">
<Name><EffectiveName Value="Master"/></Name>
<DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events>
<AudioClip Id="1" Time="0">
<Name Value="master_clip"/>
<CurrentStart Value="0"/>
<CurrentEnd Value="16"/>
<SampleRef><FileRef>
<RelativePath Value="Samples/Imported/master.wav"/>
<Path Value="/abs/Samples/Imported/master.wav"/>
</FileRef></SampleRef>
<WarpMarkers>
<WarpMarker Id="0" SecTime="0" BeatTime="0"/>
<WarpMarker Id="2" SecTime="7.5" BeatTime="16"/>
</WarpMarkers>
<IsWarped Value="true"/>
</AudioClip>
</Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain>
</AudioTrack>
</Tracks>
<MasterTrack><DeviceChain><Mixer><Tempo>
<Manual Value="120"/>
</Tempo></Mixer></DeviceChain></MasterTrack>
</LiveSet>
</Ableton>
"""


def test_clone_track_handles_extra_attributes_on_track_tag(als_file):
    """Live 11+ AudioTracks have extra attributes (SelectedToolPanel, ...)
    between Id and `>`. The pre-fix regex required `>` immediately after
    Id="N" and failed silently on real-world files."""
    p = als_file(xml=_REALISTIC_ALS)
    xml = als.read_als(str(p))
    out = als.clone_track(xml, src_track_id="14", new_name="Stem 1", new_id=100)
    info = als.inspect_xml(out)
    names = [t["name"] for t in info["tracks"]]
    assert names == ["Master", "Stem 1"]


def test_clone_track_bumps_next_pointee_id(als_file):
    """Without bumping NextPointeeId, Ableton refuses to load the .als with
    'NextPointeeId is too low: X must be bigger than Y'."""
    p = als_file(xml=_REALISTIC_ALS)
    xml = als.read_als(str(p))
    out = als.clone_track(xml, src_track_id="14", new_name="Stem 1", new_id=100)
    import re
    npi = int(re.search(r'<NextPointeeId Value="(\d+)"', out).group(1))
    max_id = max(int(x) for x in re.findall(r'Id="(\d+)"', out))
    assert npi > max_id, f"NextPointeeId={npi} must exceed max Id={max_id}"


def test_clone_track_multiple_calls_do_not_collide_ids(als_file):
    """Two clones of the same source must produce disjoint internal Id ranges.
    The pre-fix hardcoded +30000 offset made repeat calls collide."""
    p = als_file(xml=_REALISTIC_ALS)
    xml = als.read_als(str(p))
    once = als.clone_track(xml, src_track_id="14", new_name="Stem 1", new_id=100)
    twice = als.clone_track(once, src_track_id="14", new_name="Stem 2", new_id=101)
    import re
    # Three tracks in the resulting document (order: source then clones in
    # reverse insertion order, since each clone inserts immediately after the
    # source block — fine for a primitive; callers that care about order can
    # build all clones from one read and join them).
    info = als.inspect_xml(twice)
    assert sorted(t["name"] for t in info["tracks"]) == ["Master", "Stem 1", "Stem 2"]
    # The two clones' internal warp marker Ids (cloned from master Id=0 + Id=2)
    # should have been offset into disjoint ranges. Find each clone's offset by
    # scanning WarpMarker Ids per track block.
    track_blocks = re.findall(
        r'<AudioTrack\s+Id="\d+"[^>]*>.*?</AudioTrack>', twice, re.DOTALL
    )
    assert len(track_blocks) == 3
    warp_ids_per_track = [
        [int(x) for x in re.findall(r'<WarpMarker Id="(\d+)"', b)]
        for b in track_blocks
    ]
    # No overlap between any two tracks' warp marker Id sets
    for i in range(len(warp_ids_per_track)):
        for j in range(i + 1, len(warp_ids_per_track)):
            overlap = set(warp_ids_per_track[i]) & set(warp_ids_per_track[j])
            assert not overlap, (
                f"Tracks {i} and {j} share WarpMarker Ids {overlap}"
            )


def test_backup_writes_timestamped_copy(als_file):
    p = als_file()
    b = als.backup(str(p), op="test")
    # Ableton-native backup convention: <project>/Backup/<stem> [YYYY-MM-DD HHMMSS].als
    from pathlib import Path
    bp = Path(b)
    assert bp.parent.name == "Backup"
    assert bp.parent.parent == Path(p).parent
    assert bp.name.startswith(Path(p).stem + " [")
    assert bp.suffix == ".als"
    assert gzip.open(b, "rb").read() == gzip.open(str(p), "rb").read()
