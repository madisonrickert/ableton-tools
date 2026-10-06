# Test fixtures

Sanitized derivatives of real Ableton Live 12.4 sets (user paths, names and plugin
state removed). Regenerate with the dev scripts in `engine/scripts/`:

- `live12_set.xml` ← `sanitize_fixture.py SRC.als fixtures/live12_set.xml`
  MainTrack (Tempo with LomId), one audio track with a Session clip and a warped
  Arrangement clip (ScaleInformation, Time, 4 warp markers), return tracks with
  RelativePathType 1/5 device refs, 8 scenes, NextPointeeId.
- `chain_src.xml` ← `build_chain_fixture.py` (needs the original donor sets)
  `live12_set.xml` plus a device chain on track `1-master` (Id 8): a self-routed rack
  (`AudioIn/Track.8/DeviceOut…`), a Compressor sidechained from track 14 (`2-source`),
  a stubbed VST3 device, a RelativePathType 3 ref (`Samples/ir.wav`), and a track
  AutomationEnvelope targeting a chain parameter.
