"""Deterministic annotated-sequence playback; annotations are never inference."""
from __future__ import annotations

import json
import time
from pathlib import Path

if __package__:
    from .domain import Detection, normalized_box, number
    from .tracking import TrackManager
else:
    from domain import Detection, normalized_box, number
    from tracking import TrackManager


def load_sequence(path):
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Replay manifest exceeds the 10 MB demo limit")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("schema") != "dronewatch.replay.v1":
        raise ValueError("Expected dronewatch.replay.v1; unknown dataset schemas need an explicit adapter")
    width, height, duration = data.get("width"), data.get("height"), data.get("duration")
    if not all(number(v) and v > 0 for v in (width, height, duration)):
        raise ValueError("Replay requires positive width, height and duration")
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("Replay requires a nonempty frames array")
    previous = -1
    for frame in frames:
        if not isinstance(frame, dict) or not number(frame.get("time")) or not previous < frame["time"] <= duration:
            raise ValueError("Replay frame times must be strictly increasing and within duration")
        previous = frame["time"]
        if not isinstance(frame.get("detections"), list):
            raise ValueError("Every replay frame requires detections, including empty frames")
        for item in frame["detections"]:
            if not isinstance(item, dict) or normalized_box(item, width, height) is None:
                raise ValueError("Replay annotation needs a valid, in-bounds bbox with an explicit format")
            if not isinstance(item.get("class_name"), str):
                raise ValueError("Replay annotation requires class_name")
    polygon = data.get("zone")
    if polygon is not None and (not isinstance(polygon, list) or len(polygon) < 3 or any(
        not isinstance(p, list) or len(p) != 2 or not all(number(v) and 0 <= v <= 1 for v in p) for p in polygon
    )):
        raise ValueError("Monitoring zone must be a normalized polygon of at least three points")
    video = data.get("video")
    data["video_path"] = (path.parent / video).resolve() if isinstance(video, str) else None
    if data["video_path"] is not None and not data["video_path"].is_file():
        raise ValueError("Configured replay video does not exist")
    return data


class ReplayEngine:
    def __init__(self, path, config=None, clock=time.monotonic):
        self.data = load_sequence(path)
        self.config = config
        self.clock = clock
        self.loop = True
        self.playing = False
        self.restart(False)

    def restart(self, playing=True):
        camera = self.data.get("camera_id")
        zones = {str(camera): self.data["zone"]} if self.data.get("zone") else {}
        self.manager = TrackManager(self.config, zones)
        self.current_time = 0.0
        self.cursor = 0
        self.anchor = self.clock()
        self.playing = playing
        self.frame = None

    def control(self, action, loop=None):
        if loop is not None:
            self.loop = loop
        if action == "restart":
            self.restart(True)
        elif action == "play":
            if self.current_time >= self.data["duration"]:
                self.restart(True)
            else:
                self.anchor = self.clock() - self.current_time
                self.playing = True
        elif action == "pause":
            self.update()
            self.playing = False
        else:
            raise ValueError("Replay action must be play, pause or restart")

    def update(self):
        if self.playing:
            elapsed = max(0, self.clock() - self.anchor)
            if elapsed >= self.data["duration"] and self.loop:
                self.restart(True)
                return True
            self.current_time = min(elapsed, self.data["duration"])
            if elapsed >= self.data["duration"]:
                self.playing = False
        changed = False
        frames = self.data["frames"]
        while self.cursor < len(frames) and frames[self.cursor]["time"] <= self.current_time:
            frame = frames[self.cursor]
            detections = [Detection(
                detection_id=f"replay:{self.cursor}:{index}", source="BENCHMARK_REPLAY",
                camera_id=self.data.get("camera_id"), timestamp=frame["time"],
                class_name=item["class_name"], confidence=None,
                bbox=normalized_box(item, self.data["width"], self.data["height"]),
                frame_width=self.data["width"], frame_height=self.data["height"],
                source_payload_reference=f"annotation-frame:{self.cursor}",
            ) for index, item in enumerate(frame["detections"])]
            self.manager.update("BENCHMARK_REPLAY", self.data.get("camera_id"), str(self.cursor), frame["time"], detections)
            self.frame = frame
            self.cursor += 1
            changed = True
        self.manager.tick(self.current_time)
        return changed

    def snapshot(self):
        state = self.manager.snapshot()
        state.update({"mode": "BENCHMARK_REPLAY", "spatial_available": True,
            "source": {"online": self.playing, "status": "PLAYING" if self.playing else "PAUSED",
                       "last_event": self.frame["time"] if self.frame else None},
            "replay": {"time": self.current_time, "duration": self.data["duration"],
                       "playing": self.playing, "loop": self.loop, "frame_index": max(0, self.cursor - 1),
                       "width": self.data["width"], "height": self.data["height"],
                       "video_available": self.data["video_path"] is not None,
                       "synthetic": bool(self.data.get("synthetic")), "description": self.data.get("description"),
                       "zone": self.data.get("zone")},
            "sightings": [], "watermark": "RECORDED BENCHMARK REPLAY"})
        return state
