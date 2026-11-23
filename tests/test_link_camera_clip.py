"""Linking a camera clip to a replay moment writes a manifest the camera API accepts."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "link_camera_clip.py"
spec = importlib.util.spec_from_file_location("link_camera_clip", SCRIPT)
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


def test_looks_are_unbroken_spells_of_the_camera_settled_on_one_group():
    windows = link.cue_windows("operator_demo", 42, 6, "radar_off_30s_viso")
    # Far out, the six contacts fall into a west three and an east three, one look each.
    assert windows[0] == {"target": "DW-001", "targets": ["DW-002", "DW-005", "DW-001"], "start": 12.6, "end": 18.2}
    assert (sorted(windows[1]["targets"]), windows[1]["start"], windows[1]["end"]) == (["DW-003", "DW-004", "DW-006"], 19.0, 24.2)
    assert all(w["start"] < w["end"] for w in windows)
    assert all(a["end"] <= b["start"] for a, b in zip(windows, windows[1:]))


def test_time_spent_turning_and_members_dropping_out_do_not_make_new_looks():
    cue = lambda t, targets, settled=True: {"t": t, "target": targets[0] if targets else None, "targets": targets, "settled": settled}
    cues = [cue(0.0, []), cue(0.2, ["A", "B"], False), cue(0.4, ["A", "B"]), cue(0.6, ["A", "B"]), cue(0.8, ["B"]),
            cue(1.0, ["C"], False), cue(1.2, ["C"]), cue(1.4, [])]
    assert link.looks_from(cues) == [
        {"target": "A", "targets": ["A", "B"], "start": 0.4, "end": 1.0},
        {"target": "C", "targets": ["C"], "start": 1.2, "end": 1.4},
    ]
    # Older schedules have one target per cue and no "settled" flag.
    assert link.looks_from([{"t": 43.0, "target": "DW-001"}, {"t": 44.0, "target": "DW-001"}, {"t": 45.0, "target": None}]) == [
        {"target": "DW-001", "targets": ["DW-001"], "start": 43.0, "end": 45.0}]


def test_linking_by_cue_copies_the_clip_and_replaces_its_manifest_entry(tmp_path, monkeypatch):
    clip = tmp_path / "source" / "fx05.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"video")
    media = tmp_path / "media"
    monkeypatch.setattr(link, "clip_duration", lambda path: 10.0)
    assert link.main([str(clip), "--start", "1", "--end", "2", "--media-dir", str(media)]) == 0
    assert link.main([str(clip), "--cue", "DW-003", "--media-dir", str(media)]) == 0      # the first look with DW-003 in it
    assert json.loads((media / "manifest.json").read_text())["clips"][0]["sim_start_s"] == 19.0
    assert link.main([str(clip), "--look", "1", "--recorded", "Recorded test footage", "--media-dir", str(media)]) == 0
    assert (media / "fx05.mp4").read_bytes() == b"video"
    clips = json.loads((media / "manifest.json").read_text())["clips"]
    assert clips == [{
        "file": "fx05.mp4", "scenario": "operator_demo", "seed": 42, "count": 6,
        "mode": "radar_off_30s_viso", "sim_start_s": 12.6, "sim_end_s": 18.2,
        "frame": "LOCAL_SIM_METRES", "playback": "realtime", "synthetic": False, "result_after_s": 3.0,
        "provenance": "Recorded test footage", "duration_seconds": 10.0,
    }]

    monkeypatch.setenv("DRONEWATCH_CAMERA_MEDIA_DIR", str(media))
    from dronewatch.api import camera
    context = camera._scenario_contexts()["fx05.mp4"]
    assert (context["sim_start_s"], context["sim_end_s"], context["playback"], context["synthetic"]) == (12.6, 18.2, "realtime", False)
    # The result is released three seconds into the look, while the camera is still on the group.
    assert context["available_at_sim_s"] == 15.6


def test_a_contact_or_look_the_camera_never_has_is_refused(tmp_path):
    clip = tmp_path / "fx05.mp4"
    clip.write_bytes(b"video")
    for choice in (["--cue", "DW-999"], ["--look", "0"], ["--look", "99"]):
        with pytest.raises(SystemExit):
            link.main([str(clip), *choice, "--media-dir", str(tmp_path / "media")])
    assert not (tmp_path / "media").exists()
