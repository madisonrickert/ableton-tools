import gzip
import math

import numpy as np
import pytest
import soundfile as sf

from ableton_tools.alsxml import Doc
from ableton_tools.cli import main
from ableton_tools.errors import UsageError
from ableton_tools.split import split
from ableton_tools.timeline import beats_to_seconds, locators, tempo_map


def _set_xml(events: str | None, locs: list[tuple[float, str]], clip_end: float = 16.0,
             manual: float = 120.0) -> str:
    env = (
        "<AutomationEnvelopes><Envelopes><AutomationEnvelope Id=\"0\">"
        "<EnvelopeTarget><PointeeId Value=\"8\" /></EnvelopeTarget>"
        f"<Automation><Events>{events}</Events></Automation>"
        "</AutomationEnvelope></Envelopes></AutomationEnvelopes>"
        if events else ""
    )
    loc_xml = "".join(
        f'<Locator Id="{i}"><Time Value="{b}" /><Name Value="{n}" /></Locator>'
        for i, (b, n) in enumerate(locs)
    )
    return (
        '<Ableton><LiveSet><NextPointeeId Value="100" /><Tracks><AudioTrack Id="1">'
        f'<AudioClip Id="2" Time="0"><CurrentEnd Value="{clip_end}" /></AudioClip>'
        "</AudioTrack></Tracks><MainTrack><DeviceChain><Mixer><Tempo>"
        f'<Manual Value="{manual}" /><AutomationTarget Id="8" /></Tempo></Mixer></DeviceChain>'
        f"{env}</MainTrack><Locators><Locators>{loc_xml}</Locators></Locators>"
        "</LiveSet></Ableton>"
    )


def _write_set(tmp_path, xml: str):
    p = tmp_path / "set.als"
    with gzip.open(p, "wb") as fh:
        fh.write(xml.encode())
    return p


# Live writes the pre-song value at a huge negative time, and a step change as
# two events at the same beat (old tempo, then new). Deliberately list the
# step's events so that sorting by (beat, bpm) would reorder them.
STEP_EVENTS = (
    '<FloatEvent Id="1" Time="-63072000" Value="120" />'
    '<FloatEvent Id="2" Time="4" Value="120" />'
    '<FloatEvent Id="3" Time="4" Value="60" />'
)


def test_constant_tempo_without_automation(tmp_path):
    doc = Doc(_set_xml(None, [], manual=90.0))
    tmap = tempo_map(doc)
    assert tmap == [(0.0, 90.0)]
    assert beats_to_seconds(3.0, tmap) == pytest.approx(2.0)


def test_step_change_keeps_same_beat_event_order():
    tmap = tempo_map(Doc(_set_xml(STEP_EVENTS, [])))
    assert tmap == [(0.0, 120.0), (4.0, 120.0), (4.0, 60.0)]
    # 4 beats at 120 = 2 s, then 2 beats at 60 = 2 s
    assert beats_to_seconds(6.0, tmap) == pytest.approx(4.0)


def test_linear_ramp_integrates_tempo():
    tmap = [(0.0, 60.0), (4.0, 120.0)]
    expected = 60.0 * 4 / (120.0 - 60.0) * math.log(120.0 / 60.0)  # ∫ 60/T(b) db
    assert beats_to_seconds(4.0, tmap) == pytest.approx(expected)
    assert beats_to_seconds(5.0, tmap) == pytest.approx(expected + 0.5)  # holds 120 after


def test_locators_report_beats_seconds_and_end(tmp_path):
    p = _write_set(tmp_path, _set_xml(STEP_EVENTS, [(6.0, "B"), (0.0, "A")], clip_end=8.0))
    out = locators(p)
    assert out["tempo_automated"] is True
    assert [(x["name"], x["beat"], x["seconds"]) for x in out["locators"]] == [
        ("A", 0.0, 0.0), ("B", 6.0, 4.0)]
    assert out["arrangement_end"] == {"beat": 8.0, "seconds": 6.0}


def _render(tmp_path, sections_s: list[tuple[float, float]], total_s: float, sr=48000):
    """16-bit stereo render: tone during each (start, sound_len) window, silence elsewhere."""
    x = np.zeros((int(total_s * sr), 2), dtype=np.int16)
    for start, length in sections_s:
        a, b = int(start * sr), int((start + length) * sr)
        x[a:b] = 8000
    p = tmp_path / "render.wav"
    sf.write(str(p), x, sr, subtype="PCM_16")
    return p, x


def test_split_cuts_at_locators_trims_and_copies_exactly(tmp_path):
    # 120 bpm: locators at beats 0/4/8 -> 0 s / 2 s / 4 s; render is 6 s.
    p_set = _write_set(tmp_path, _set_xml(None, [(0, "one"), (4, "gap"), (8, "three")],
                                          clip_end=12.0))
    render, x = _render(tmp_path, [(0.0, 1.0), (4.0, 1.5)], total_s=6.0)
    out = split(render, p_set, tmp_path / "out", names={"one": "01 - One"}, tail_pad_s=0.25)
    files = {s["locator"]: s for s in out["sections"]}
    assert set(files) == {"one", "three"}
    assert any("'gap' is silent" in w for w in out["warnings"])
    assert files["one"]["duration_s"] == pytest.approx(1.25, abs=1e-3)
    written, sr = sf.read(files["one"]["file"], dtype="int16", always_2d=True)
    assert sr == 48000 and sf.info(files["one"]["file"]).subtype == "PCM_16"
    assert np.array_equal(written, x[: len(written)])  # sample-exact copy
    assert files["one"]["file"].endswith("01 - One.wav")


def test_split_start_locator_offsets_the_render(tmp_path):
    p_set = _write_set(tmp_path, _set_xml(None, [(4, "a"), (8, "b")], clip_end=12.0))
    render, _ = _render(tmp_path, [(0.0, 1.0), (2.0, 1.0)], total_s=4.0)  # export of beats 4..12
    out = split(render, p_set, tmp_path / "out", start="a", dry_run=True)
    assert [s["start_s"] for s in out["sections"]] == [0.0, 2.0]
    assert out["warnings"] == [] and not (tmp_path / "out").exists()


def test_split_warns_when_render_length_does_not_match(tmp_path):
    p_set = _write_set(tmp_path, _set_xml(None, [(0, "a")], clip_end=40.0))
    render, _ = _render(tmp_path, [(0.0, 1.0)], total_s=4.0)
    out = split(render, p_set, tmp_path / "out", dry_run=True)
    assert any("check --start" in w for w in out["warnings"])


def test_split_rejects_unknown_start(tmp_path):
    p_set = _write_set(tmp_path, _set_xml(None, [(0, "a")]))
    render, _ = _render(tmp_path, [(0.0, 1.0)], total_s=8.0)
    with pytest.raises(UsageError, match="neither a locator"):
        split(render, p_set, tmp_path / "out", start="nope")


def test_cli_split_and_locators(tmp_path, capsys):
    p_set = _write_set(tmp_path, _set_xml(None, [(0, "a"), (4, "b")], clip_end=8.0))
    render, _ = _render(tmp_path, [(0.0, 1.0), (2.0, 1.0)], total_s=4.0)
    assert main(["als", "locators", str(p_set), "--json"]) == 0
    assert '"name": "b"' in capsys.readouterr().out
    assert main(["split", str(render), "--als", str(p_set), "--out",
                 str(tmp_path / "o"), "--no-trim", "--json"]) == 0
    assert sorted(f.name for f in (tmp_path / "o").iterdir()) == ["a.wav", "b.wav"]
