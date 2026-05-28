---
name: ableton-midi-transcribe
description: Transcribe an audio stem (e.g. an isolated sax or synth line) to a MIDI file using Spotify basic-pitch with tuned parameters. Use when you need a MIDI version of a monophonic or lightly polyphonic audio part to edit in Ableton.
---

You transcribe audio to MIDI using the shared Ableton engine
(`ableton-shared`, a sibling skill). The heavy basic-pitch dependency is
installed on demand by the dispatcher — no setup needed.

## Invoke
`<repo>/ableton-shared/bin/ableton midi transcribe <AUDIO> [--out <OUT.mid>] --json`
Returns `{output: "<path>.mid"}`. Default output is alongside the input as
`<stem>_basic_pitch.mid`.

Tuned defaults (from the source project's sax transcription): onset_threshold
0.5, frame_threshold 0.3, minimum note 58 ms, melodia_trick on. These suit a
monophonic lead; for denser material, mention it and we can expose overrides.

First run installs basic-pitch/TensorFlow (can take a minute). To sanity-check a
transcription, follow up with `ableton-midi-compare` against a reference MIDI.
