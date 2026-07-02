"""Audio-to-MIDI transcription via Spotify basic-pitch.

basic-pitch is imported lazily so the rest of the pack never pays its
TensorFlow import cost. It is installed only via the `transcribe` extra.
"""

import shutil
from pathlib import Path


def transcribe(
    audio_path,
    out_path=None,
    onset_threshold=0.5,
    frame_threshold=0.3,
    minimum_note_length_ms=58.0,
    melodia_trick=True,
):
    """Transcribe an audio file to a MIDI file; return the output path."""
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict_and_save
    except ImportError as exc:  # pragma: no cover - exercised only without extra
        raise RuntimeError(
            "basic-pitch is not installed. Run via "
            "`uv run --extra transcribe ...` or `ableton midi transcribe ...` "
            "(the dispatcher adds the extra automatically)."
        ) from exc

    audio_path = Path(audio_path)
    work = Path(out_path).parent if out_path else audio_path.parent
    work.mkdir(parents=True, exist_ok=True)

    predict_and_save(
        audio_paths=[str(audio_path)],
        output_directory=str(work),
        save_midi=True,
        sonify_midi=False,
        save_model_outputs=False,
        save_notes=False,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length_ms,
        melodia_trick=melodia_trick,
    )

    produced = work / f"{audio_path.stem}_basic_pitch.mid"
    if out_path and str(produced) != str(out_path):
        shutil.move(str(produced), str(out_path))
        return str(out_path)
    return str(produced)
