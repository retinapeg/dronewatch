"""Optional detector adapter and bounded small-object strategies. Lazy dependencies."""
from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path

if __package__:
    from .domain import Detection
    from .tracking import iou
else:
    from domain import Detection
    from tracking import iou


class ModelUnavailable(RuntimeError):
    pass


class FullFrameStrategy:
    def regions(self, width, height, frame_index, tracks):
        return [(0, 0, width, height)]


class SlicedStrategy:
    def __init__(self, tile=640, overlap=0.2, max_tiles=16):
        self.tile, self.overlap, self.max_tiles = tile, overlap, max_tiles

    def regions(self, width, height, frame_index, tracks):
        if width <= self.tile and height <= self.tile:
            return [(0, 0, width, height)]
        step = max(1, int(self.tile * (1 - self.overlap)))
        xs = sorted(set([min(x, max(0, width - self.tile)) for x in range(0, width, step)]))
        ys = sorted(set([min(y, max(0, height - self.tile)) for y in range(0, height, step)]))
        regions = [(x, y, min(x + self.tile, width), min(y + self.tile, height)) for y in ys for x in xs]
        # Never silently scan only the top-left portion of a large image.
        return regions if len(regions) <= self.max_tiles else [(0, 0, width, height)]


class CandidateRegionStrategy:
    def __init__(self, full_frame_every=10):
        self.full_frame_every = full_frame_every

    def regions(self, width, height, frame_index, tracks):
        if frame_index % self.full_frame_every == 0 or not tracks:
            return [(0, 0, width, height)]
        result = []
        for track in tracks[:8]:
            x1, y1, x2, y2 = track["bbox"]
            padding_x, padding_y = max(128, (x2 - x1) * width), max(128, (y2 - y1) * height)
            result.append((max(0, int(x1 * width - padding_x)), max(0, int(y1 * height - padding_y)),
                           min(width, int(x2 * width + padding_x)), min(height, int(y2 * height + padding_y))))
        return result or [(0, 0, width, height)]


def availability():
    model = os.getenv("DRONEWATCH_MODEL_PATH")
    if not model or not Path(model).expanduser().is_file():
        return {"available": False, "reason": "Supply an existing DRONEWATCH_MODEL_PATH; no weights are downloaded automatically."}
    if not all(importlib.util.find_spec(name) for name in ("ultralytics", "cv2")):
        return {"available": False, "reason": "Install requirements-inference.txt in an optional inference environment."}
    return {"available": True, "reason": None}


class UltralyticsAdapter:
    def __init__(self):
        status = availability()
        if not status["available"]:
            raise ModelUnavailable(status["reason"])
        from ultralytics import YOLO
        self.model = YOLO(str(Path(os.environ["DRONEWATCH_MODEL_PATH"]).expanduser()))
        strategies = {"full": FullFrameStrategy, "sliced": SlicedStrategy, "candidate": CandidateRegionStrategy}
        name = os.getenv("DRONEWATCH_INFERENCE_STRATEGY", "full")
        if name not in strategies:
            raise ModelUnavailable("Strategy must be full, sliced or candidate")
        self.strategy = strategies[name]()
        self.classes = {label.strip().lower() for label in os.getenv("DRONEWATCH_CLASSES", "drone,uav,quadcopter").split(",")}

    def detect(self, frame, frame_index, timestamp, tracks):
        height, width = frame.shape[:2]
        observations = []
        for left, top, right, bottom in self.strategy.regions(width, height, frame_index, tracks):
            for result in self.model.predict(frame[top:bottom, left:right], verbose=False):
                if result.boxes is None:
                    continue
                for box, score, class_id in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist()):
                    label = result.names[int(class_id)]
                    if label.lower() not in self.classes:
                        continue
                    x1, y1, x2, y2 = box
                    bbox = (max(0, (x1 + left) / width), max(0, (y1 + top) / height),
                            min(1, (x2 + left) / width), min(1, (y2 + top) / height))
                    if bbox[0] < bbox[2] and bbox[1] < bbox[3]:
                        observations.append(Detection(f"local:{frame_index}:{len(observations)}", "LOCAL_INFERENCE", "local-01",
                            timestamp, label, float(score), bbox, width, height, f"local-frame:{frame_index}"))
        kept = []
        for detection in sorted(observations, key=lambda d: d.confidence, reverse=True):
            if not any(d.class_name == detection.class_name and iou(d.bbox, detection.bbox) > 0.5 for d in kept):
                kept.append(detection)
        return kept


class LocalRunner:
    def __init__(self, on_frame, get_tracks, on_restart):
        self.on_frame, self.get_tracks, self.on_restart = on_frame, get_tracks, on_restart
        self.thread = None
        self.stop_flag = threading.Event()
        self.jpeg = None
        self.status = "STOPPED"
        self.error = None
        self.fps = None
        self.last_event = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        status = availability()
        if not status["available"]:
            raise ModelUnavailable(status["reason"])
        self.stop_flag.clear()
        self.error = None
        self.status = "STARTING"
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.status = "STOPPED"

    def run(self):
        capture = None
        try:
            import cv2
            detector = UltralyticsAdapter()
            source = os.getenv("DRONEWATCH_LOCAL_SOURCE", "0")
            capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
            if not capture.isOpened():
                raise RuntimeError("Source could not be opened")
            video_file = not source.isdigit() and not source.lower().startswith("rtsp:")
            frame_rate = capture.get(cv2.CAP_PROP_FPS) or 25
            frame_index = 0
            self.status = "ONLINE"
            while not self.stop_flag.is_set():
                started = time.monotonic()
                success, frame = capture.read()
                if not success:
                    if video_file and os.getenv("DRONEWATCH_LOCAL_LOOP", "1") == "1":
                        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self.on_restart()
                        frame_index = 0
                        self.stop_flag.wait(0.05)
                        continue
                    break
                timestamp = time.time()
                detections = detector.detect(frame, frame_index, timestamp, self.get_tracks())
                encoded, jpeg = cv2.imencode(".jpg", frame)
                if encoded:
                    self.jpeg = jpeg.tobytes()
                self.on_frame(str(frame_index), timestamp, detections)
                self.last_event = timestamp
                elapsed = max(time.monotonic() - started, 0.0001)
                self.fps = 1 / elapsed
                frame_index += 1
                if video_file:
                    self.stop_flag.wait(max(0, 1 / frame_rate - elapsed))
        except Exception:
            # Do not echo RTSP credentials, local model paths or provider tracebacks.
            self.error = "Local inference unavailable. Check optional dependencies, model compatibility and source configuration."
            self.status = "ERROR"
        finally:
            if capture is not None:
                capture.release()
            if self.status != "ERROR":
                self.status = "STOPPED"
