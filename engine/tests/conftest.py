import gzip
import numpy as np
import soundfile as sf
import mido
import pytest


@pytest.fixture
def tone_wav(tmp_path):
    """Factory: write a sine tone to a wav, return its path."""
    def _make(name="tone.wav", freq=220.0, dur_s=4.0, sr=48000, amp=0.5, phase=0.0):
        t = np.arange(int(dur_s * sr)) / sr
        x = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
        p = tmp_path / name
        sf.write(str(p), x, sr)
        return p
    return _make


@pytest.fixture
def click_wav(tmp_path):
    """Factory: write a click track at a known BPM, return its path."""
    def _make(name="click.wav", bpm=120.0, bars=8, sr=48000):
        period = 60.0 / bpm
        n = int(period * 4 * bars * sr)
        x = np.zeros(n, dtype=np.float32)
        step = int(period * sr)
        for i in range(0, n, step):
            end = min(i + 200, n)
            x[i:end] = 0.9  # short impulse
        p = tmp_path / name
        sf.write(str(p), x, sr)
        return p
    return _make


@pytest.fixture
def midi_file(tmp_path):
    """Factory: write a single-track MIDI from (onset_s, pitch, dur_s) tuples."""
    def _make(name="m.mid", notes=((0.0, 60, 0.4), (0.5, 62, 0.4)), bpm=120.0):
        mid = mido.MidiFile()
        tpb = mid.ticks_per_beat
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
        spb = 60.0 / bpm  # seconds per beat
        events = []
        for onset, pitch, dur in notes:
            events.append((onset, "note_on", pitch))
            events.append((onset + dur, "note_off", pitch))
        events.sort(key=lambda e: e[0])
        prev_tick = 0
        for t_sec, kind, pitch in events:
            tick = int(round((t_sec / spb) * tpb))
            delta = tick - prev_tick
            prev_tick = tick
            vel = 80 if kind == "note_on" else 0
            track.append(mido.Message(kind, note=pitch, velocity=vel, time=delta))
        p = tmp_path / name
        mid.save(str(p))
        return p
    return _make


MINIMAL_ALS = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="3" Creator="Ableton Live 11.3">
<LiveSet>
<Tracks>
<AudioTrack Id="0">
<Name><EffectiveName Value="Bass"/></Name>
<DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events>
<AudioClip Id="0" Time="0">
<Name Value="bass_clip"/>
<CurrentStart Value="0"/>
<CurrentEnd Value="16"/>
<SampleRef><FileRef>
<RelativePath Value="Samples/Imported/bass.wav"/>
<Path Value="/abs/Samples/Imported/bass.wav"/>
</FileRef></SampleRef>
<WarpMarkers>
<WarpMarker Id="0" SecTime="0" BeatTime="0"/>
<WarpMarker Id="1" SecTime="7.5" BeatTime="16"/>
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


@pytest.fixture
def als_file(tmp_path):
    """Factory: write a minimal gzipped .als, return its path."""
    def _make(name="test.als", xml=MINIMAL_ALS):
        p = tmp_path / name
        with gzip.open(str(p), "wb") as fh:
            fh.write(xml.encode("utf-8"))
        return p
    return _make


# Master-track fixture with the full set of tags import-stems must repoint.
STEM_ALS = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="3" Creator="Ableton Live 11.3">
<LiveSet>
<NextPointeeId Value="100"/>
<Tracks>
<AudioTrack Id="14" SelectedToolPanel="3">
<Name><EffectiveName Value="1-Master"/><MemorizedFirstClipName Value="master_clip"/></Name>
<Color Value="5"/>
<DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events>
<AudioClip Id="1" Time="0">
<Name Value="master_clip"/>
<Color Value="5"/>
<CurrentStart Value="0"/>
<CurrentEnd Value="16"/>
<SampleRef><FileRef>
<RelativePath Value="Samples/Imported/master.wav"/>
<Path Value="/abs/Samples/Imported/master.wav"/>
<OriginalFileSize Value="123456"/>
<OriginalCrc Value="9999"/>
</FileRef></SampleRef>
<WarpMarkers>
<WarpMarker Id="0" SecTime="0" BeatTime="0"/>
<WarpMarker Id="2" SecTime="7.5" BeatTime="16"/>
</WarpMarkers>
<IsWarped Value="true"/>
<IsSongTempoLeader Value="true"/>
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


@pytest.fixture
def stem_project(tmp_path):
    """Project dir with master + two stems, all identical frames/samplerate."""
    sr = 8000
    x = (0.1 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
    d = tmp_path / "Samples" / "Imported"
    d.mkdir(parents=True)
    sf.write(str(d / "master.wav"), x, sr)
    stems = tmp_path / "suno-stems"
    stems.mkdir()
    sf.write(str(stems / "0 Lead Vocals.wav"), x, sr)
    sf.write(str(stems / "1 Drums.wav"), x, sr)
    return tmp_path, [stems / "0 Lead Vocals.wav", stems / "1 Drums.wav"]
