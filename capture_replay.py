"""Bounded local recordings. Replay time is relative to the original capture clock."""
import bisect
import copy
import json
import math
import time
import uuid
from pathlib import Path

if __package__:
    from .adsb_provider import normalize_response
else:
    from adsb_provider import normalize_response

SCHEMA = "dronewatch.capture.v1"


class CaptureStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.active = None
        self.frames_written = 0
        self.error = None

    def append(self, snapshot):
        if snapshot.get("provenance") != "LIVE_PUBLIC_ADSB":
            raise ValueError("Only genuine live provider snapshots may be captured")
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.active is None or self.active.stat().st_size > 20_000_000:
            self.active = self.directory / (time.strftime("adsb-%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6] + ".jsonl")
            self.active.touch()
        record = {"schema": SCHEMA, "captured_epoch": snapshot["received_epoch"], "snapshot": snapshot}
        with self.active.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
        self.frames_written += 1
        self.error = None

    def listing(self):
        if not self.directory.exists():
            return []
        files = sorted(self.directory.glob("adsb-*.jsonl"), key=lambda p: p.name, reverse=True)[:30]
        return [{"name": p.name, "bytes": p.stat().st_size, "provenance": "RECORDED_LIVE_DATA"} for p in files if p.is_file() and not p.is_symlink()]

    def load(self, name=None):
        listing = self.listing()
        name = name or (listing[0]["name"] if listing else None)
        if not name or Path(name).name != name or not name.startswith("adsb-") or not name.endswith(".jsonl"):
            raise ValueError("Choose an available local ADS-B capture")
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory.resolve() or not path.is_file():
            raise ValueError("Capture not found")
        if path.stat().st_size > 32_000_000:
            raise ValueError("Capture exceeds the 32 MB replay limit")
        frames = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if len(frames) >= 2000:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A currently recording file can have an incomplete final line.
                epoch = record.get("captured_epoch") if isinstance(record, dict) else None
                snap = record.get("snapshot", {}) if isinstance(record, dict) else {}
                if record.get("schema") != SCHEMA or not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
                    continue
                if snap.get("provenance") != "LIVE_PUBLIC_ADSB" or not isinstance(snap.get("tracks"), list):
                    continue
                if frames and epoch <= frames[-1]["captured_epoch"]:
                    continue
                frames.append(record)
        if not frames:
            raise ValueError("Capture has no complete, valid frames")
        return name, frames


class ReplaySession:
    def __init__(self, name, frames, clock=time.monotonic, synthetic=False):
        self.name, self.frames, self.clock = name, copy.deepcopy(frames), clock
        self.synthetic = synthetic
        self.started = clock()
        self.first_epoch = frames[0]["captured_epoch"]
        self.offsets = [f["captured_epoch"] - self.first_epoch for f in frames]
        self.duration = max(10.0, self.offsets[-1] + 10.0)

    def current(self):
        elapsed = max(0.0, self.clock() - self.started)
        position = elapsed % self.duration
        index = max(0, bisect.bisect_right(self.offsets, position) - 1)
        return copy.deepcopy(self.frames[index]["snapshot"]), self.first_epoch + position, {
            "name": self.name, "frame": index + 1, "frames": len(self.frames),
            "position_s": round(position, 1), "duration_s": self.duration,
            "loop": int(elapsed // self.duration), "original_timing": True,
        }


def synthetic_frames(origin=None):
    """Small offline fixture, never described as captured or live aircraft."""
    frames = []
    epoch = 1_788_480_000.0
    for second in range(0, 121, 10):
        aircraft = []
        for index in range(6):
            angle = index * math.pi / 3 + second * 0.0015
            radius = 0.12 + index * 0.026
            aircraft.append({"hex": "%06x" % (0xF00001 + index), "flight": "SYN%02d" % (index + 1),
                             "lat": 51.4995 + radius * math.cos(angle),
                             "lon": -0.1248 + radius * math.sin(angle) / math.cos(math.radians(51.4995)),
                             "alt_geom": 8000 + index * 1200, "gs": 180 + index * 20,
                             "track": (math.degrees(angle) + 90) % 360, "seen_pos": 0,
                             "type": "synthetic"})
        snap = normalize_response({"ac": aircraft, "now": (epoch + second) * 1000}, received_at=epoch + second, origin=origin)
        snap["provenance"] = "SYNTHETIC_FALLBACK"
        for track in snap["tracks"]:
            track.update(source="SYNTHETIC", provenance="SYNTHETIC_FALLBACK", synthetic=True)
        frames.append({"schema": SCHEMA, "captured_epoch": epoch + second, "snapshot": snap})
    return frames
