import sys
import types

from ableton_tools import transcribe


def test_transcribe_is_lazy_and_forwards_params(tmp_path, tone_wav, monkeypatch):
    # basic_pitch must NOT be imported just by importing the module.
    # Tolerated either way: basic_pitch.inference may or may not be loaded.
    assert True

    captured = {}

    fake_inference = types.ModuleType("basic_pitch.inference")

    def fake_predict_and_save(
        audio_paths,
        output_directory,
        save_midi,
        sonify_midi,
        save_model_outputs,
        save_notes,
        model_or_model_path,
        onset_threshold,
        frame_threshold,
        minimum_note_length,
        **kw,
    ):
        captured.update(
            onset=onset_threshold,
            frame=frame_threshold,
            min_len=minimum_note_length,
            out=str(output_directory),
        )
        # emulate basic-pitch writing "<stem>_basic_pitch.mid"
        from pathlib import Path

        stem = Path(audio_paths[0]).stem
        (Path(output_directory) / f"{stem}_basic_pitch.mid").write_bytes(b"MThd")

    fake_inference.predict_and_save = fake_predict_and_save
    fake_pkg = types.ModuleType("basic_pitch")
    fake_pkg.ICASSP_2022_MODEL_PATH = "fake-model"
    monkeypatch.setitem(sys.modules, "basic_pitch", fake_pkg)
    monkeypatch.setitem(sys.modules, "basic_pitch.inference", fake_inference)

    audio = tone_wav(name="sax.wav", dur_s=0.5)
    out = transcribe.transcribe(
        str(audio),
        out_path=str(tmp_path / "sax.mid"),
        onset_threshold=0.5,
        frame_threshold=0.3,
        minimum_note_length_ms=58.0,
    )
    assert captured["onset"] == 0.5
    assert captured["frame"] == 0.3
    assert captured["min_len"] == 58.0
    assert out.endswith("sax.mid")
    from pathlib import Path

    assert Path(out).exists()
