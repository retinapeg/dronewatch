"""Linking a camera clip to a replay moment writes a manifest the camera API accepts."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "link_camera_clip.py"
spec = importlib.util.spec_from_file_location("link_camera_clip", SCRIPT)
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


def test_cue_windows_are_unbroken_spells_on_one_contact():
    windows = link.cue_windows("operator_demo", 42, 6, "radar_off_30s_viso")
    assert windows[0] == {"target": "DW-001", "start": 43.0, "end": 47.0}
    assert all(w["start"] < w["end"] for w in windows)
    assert all(a["end"] <= b["start"] for a, b in zip(windows, windows[1:]))


def test_linking_by_cue_copies_the_clip_and_replaces_its_manifest_entry(tmp_path, monkeypatch):
    clip = tmp_path / "source" / "fx05.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"video")
    media = tmp_path / "media"
    monkeypatch.setattr(link, "clip_duration", lambda path: 10.0)
    assert link.main([str(clip), "--start", "1", "--end", "2", "--media-dir", str(media)]) == 0
    assert link.main([str(clip), "--cue", "DW-001", "--recorded", "Recorded test footage", "--media-dir", str(media)]) == 0
    assert (media / "fx05.mp4").read_bytes() == b"video"
    clips = json.loads((media / "manifest.json").read_text())["clips"]
    assert clips == [{
        "file": "fx05.mp4", "scenario": "operator_demo", "seed": 42, "count": 6,
        "mode": "radar_off_30s_viso", "sim_start_s": 43.0, "sim_end_s": 47.0,
        "frame": "LOCAL_SIM_METRES", "playback": "realtime", "synthetic": False,
        "provenance": "Recorded test footage", "duration_seconds": 10.0,
    }]

    monkeypatch.setenv("DRONEWATCH_CAMERA_MEDIA_DIR", str(media))
    from dronewatch.api import camera
    context = camera._scenario_contexts()["fx05.mp4"]
    assert (context["sim_start_s"], context["sim_end_s"], context["playback"], context["synthetic"]) == (43.0, 47.0, "realtime", False)


def test_a_contact_the_camera_never_looks_at_is_refused(tmp_path):
    clip = tmp_path / "fx05.mp4"
    clip.write_bytes(b"video")
    with pytest.raises(SystemExit):
        link.main([str(clip), "--cue", "DW-999", "--media-dir", str(tmp_path / "media")])
    assert not (tmp_path / "media").exists()
