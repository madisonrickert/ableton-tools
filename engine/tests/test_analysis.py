import gzip
import json
import re

import numpy as np
import soundfile as sf
from conftest import FIXTURES

from ableton_tools import analysis, cli
from ableton_tools import import_stems as ist

SR = 48000


def _noise(seconds, seed=0):
    return (0.1 * np.random.default_rng(seed).standard_normal(int(seconds * SR))).astype(
        np.float32)


def test_locate_finds_fragment_offset(tmp_path):
    ref = _noise(20)
    sf.write(str(tmp_path / "ref.wav"), ref, SR)
    sf.write(str(tmp_path / "frag.wav"), ref[int(7.25 * SR) : int(10.25 * SR)], SR)
    out = analysis.locate(tmp_path / "frag.wav", tmp_path / "ref.wav")
    best = out["matches"][0]
    assert abs(best["offset_s"] - 7.25) < 0.01 and best["r"] > 0.95
    assert out["band"] == "same"


def test_locate_unrelated_fragment_is_banded_different(tmp_path):
    sf.write(str(tmp_path / "ref.wav"), _noise(20, seed=1), SR)
    sf.write(str(tmp_path / "frag.wav"), _noise(3, seed=2), SR)
    assert analysis.locate(tmp_path / "frag.wav", tmp_path / "ref.wav")["band"] == "different"


def test_levels_flags_silence_and_duplicates(tmp_path):
    loud = _noise(2)
    sf.write(str(tmp_path / "a_loud.wav"), loud, SR)
    sf.write(str(tmp_path / "b_copy.wav"), loud, SR)
    sf.write(str(tmp_path / "c_silent.wav"), np.zeros_like(loud), SR)
    out = analysis.levels(tmp_path, ref=tmp_path / "a_loud.wav")
    by = {f["file"].split("/")[-1]: f for f in out["files"]}
    assert by["c_silent.wav"]["silent"] is True and by["a_loud.wav"]["silent"] is False
    assert by["b_copy.wav"]["r_vs_ref"] > 0.999
    assert by["a_loud.wav"]["duration_s"] == 2.0 and by["a_loud.wav"]["sample_rate"] == SR
    json.dumps(out)  # JSON-safe


def _click_project(tmp_path, bpm=120.0, bars=16):
    """A Live 12 set whose master clip is warped to a click track, plus a clone."""
    proj = tmp_path / "proj"
    (proj / "Samples").mkdir(parents=True)
    period = 60.0 / bpm
    n = int(period * 4 * bars * SR)
    x = np.zeros(n, np.float32)
    for i in range(0, n, int(period * SR)):
        x[i : i + 200] = 0.9
    sf.write(str(proj / "Samples" / "master.wav"), x, SR)
    xml = (FIXTURES / "live12_set.xml").read_text()
    markers = "\n".join(
        f'<WarpMarker Id="{k}" SecTime="{b * period:g}" BeatTime="{b}" />'
        for k, b in enumerate(range(0, 4 * bars + 1, 4))
    )
    xml = re.sub(r"<WarpMarkers>.*?</WarpMarkers>",
                 f"<WarpMarkers>\n{markers}\n</WarpMarkers>", xml, flags=re.DOTALL)
    d = proj / "stems"
    d.mkdir()
    sf.write(str(d / "0 Copy.wav"), x, SR)
    xml, _ = ist.import_stems(xml, "8", [d / "0 Copy.wav"], proj)
    als_path = proj / "Set.als"
    with gzip.open(als_path, "wb") as fh:
        fh.write(xml.encode())
    return als_path


def test_warp_check_reports_bpm_alignment_and_sync(tmp_path):
    out = analysis.warp_check(_click_project(tmp_path), track="master")
    assert out["warp_map_bpm"] == 120.0
    assert out["marker_spacing_beats"] == 4.0
    assert out["beat_alignment_ms"]["median"] < 25
    assert out["sync"]["shared"] == ["2-Copy"] and out["sync"]["differs"] == []
    json.dumps(out)


def test_cli_analysis_commands(tmp_path, capsys):
    ref = _noise(10)
    sf.write(str(tmp_path / "ref.wav"), ref, SR)
    sf.write(str(tmp_path / "frag.wav"), ref[SR * 2 : SR * 4], SR)
    assert cli.main(["locate", "--fragment", str(tmp_path / "frag.wav"),
                     "--ref", str(tmp_path / "ref.wav"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["band"] == "same"
    assert cli.main(["levels", str(tmp_path), "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["files"]) == 2
    assert cli.main(["warp-check", str(_click_project(tmp_path)), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warp_map_bpm"] == 120.0


def test_warp_check_on_beatless_audio_is_json_safe(tmp_path):
    als_path = _click_project(tmp_path)
    silent = tmp_path / "silent.wav"
    sf.write(str(silent), np.zeros(SR * 4, np.float32), SR)
    out = analysis.warp_check(als_path, track="master", audio_path=silent)
    json.dumps(out, allow_nan=False)
