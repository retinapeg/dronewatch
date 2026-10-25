"""Provider-independent observations. No coordinates are inferred from prose."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


def scalar(value):
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def find(data, names):
    names = {name.replace("_", "").lower() for name in names}
    queue = [data]
    for _ in range(1000):
        if not queue:
            break
        node = queue.pop(0)
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).replace("_", "").lower() in names and value is not None:
                    return value
            queue.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            queue.extend(node)
    return None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def confidence(value):
    if number(value) and 0 <= value <= 1:
        return float(value)
    return None


def epoch(value):
    if number(value):
        return float(value) / 1000 if value > 1e12 else float(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Never interpret a timezone-less provider date using the machine timezone.
            if parsed.tzinfo is not None:
                return parsed.timestamp()
        except ValueError:
            pass
    return None


def provenance(event):
    raw = event.get("raw_payload") or {}
    raw = raw if isinstance(raw, dict) else {}
    source = str(event.get("source") or "").lower()
    if event.get("is_simulated") or raw.get("SIMULATED") is True or "simulat" in source:
        return "SIMULATED"
    if "manual" in source or "test" in source or raw.get("_dronewatch_check"):
        return "TEST"
    if raw.get("appId") and (raw.get("incidentId") or raw.get("incidentNumber")):
        return "VISO"
    return "WEBHOOK"


def normalized_box(item, width=None, height=None):
    """Return normalized xyxy only for explicitly understood, valid coordinates."""
    box = item.get("bbox", item.get("bounding_box"))
    if isinstance(box, dict):
        x1 = box.get("xmin", box.get("x_min", box.get("left", box.get("x", box.get("x1")))))
        y1 = box.get("ymin", box.get("y_min", box.get("top", box.get("y", box.get("y1")))))
        x2 = box.get("xmax", box.get("x_max", box.get("right", box.get("x2"))))
        y2 = box.get("ymax", box.get("y_max", box.get("bottom", box.get("y2"))))
        if x2 is None and number(x1) and number(box.get("width")):
            x2 = x1 + box["width"]
        if y2 is None and number(y1) and number(box.get("height")):
            y2 = y1 + box["height"]
    elif isinstance(box, (list, tuple)) and len(box) == 4:
        fmt = item.get("bbox_format")
        if fmt not in {"xyxy", "xywh"}:
            return None
        x1, y1, x2, y2 = box
        if fmt == "xywh" and all(number(x) for x in box):
            x2, y2 = x1 + x2, y1 + y2
    else:
        return None
    if not all(number(v) for v in (x1, y1, x2, y2)):
        return None
    units = item.get("bbox_units", "pixels")
    if units == "normalized":
        scale_x = scale_y = 1
    elif number(width) and number(height) and width > 0 and height > 0:
        scale_x, scale_y = width, height
    else:
        return None
    values = (x1 / scale_x, y1 / scale_y, x2 / scale_x, y2 / scale_y)
    if not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
        return None
    return values


@dataclass
class Detection:
    detection_id: str
    source: str
    camera_id: Optional[str]
    timestamp: Optional[float]
    class_name: Optional[str]
    confidence: Optional[float] = None
    bbox: Optional[tuple] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    source_payload_reference: Optional[str] = None
    zone_state: Optional[str] = None
    confidence_label: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Track:
    track_id: str
    camera_id: Optional[str]
    source: str
    class_name: Optional[str]
    state: str
    first_seen: float
    last_seen: float
    observations: int = 1
    smoothed_confidence: Optional[float] = None
    bbox: Optional[tuple] = None
    centroid_history: list = field(default_factory=list)
    zone_state: Optional[str] = None
    confirmed: bool = False
    hits: list = field(default_factory=lambda: [True], repr=False)
    velocity: tuple = field(default=(0.0, 0.0), repr=False)

    def to_dict(self):
        data = asdict(self)
        data.pop("hits")
        data.pop("velocity")
        data["duration"] = max(0, self.last_seen - self.first_seen)
        return data


@dataclass
class Alert:
    alert_id: str
    track_id: Optional[str]
    alert_type: str
    severity: str
    opened_at: float
    updated_at: float
    explanation: str
    source: str
    closed_at: Optional[float] = None

    def to_dict(self):
        return asdict(self)


def detections_from_event(event):
    raw = event.get("raw_payload") or {}
    if not isinstance(raw, dict):
        raw = {}
    origin = provenance(event)
    camera = find(raw, ["camera_id", "connectionId"])
    if not scalar(camera):
        camera = None
    stamp = epoch(event.get("received_at"))
    width, height = find(raw, ["frame_width", "image_width"]), find(raw, ["frame_height", "image_height"])
    width = int(width) if number(width) and width > 0 else None
    height = int(height) if number(height) and height > 0 else None
    items = raw.get("detections", raw.get("labels"))
    if not isinstance(items, list):
        items = [raw] if event.get("drone_detected") or event.get("detection_type") else []
    result = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        label = item.get("class_name", item.get("label", event.get("detection_type")))
        label = str(label) if scalar(label) else None
        value = item.get("confidence", event.get("confidence"))
        qualitative = value if isinstance(value, str) and value.lower() in {"high", "medium", "low"} else None
        item_width = item.get("frame_width", width)
        item_height = item.get("frame_height", height)
        result.append(Detection(
            detection_id=f"event:{event.get('id', event.get('event_id'))}:{index}",
            source=origin, camera_id=str(camera) if camera is not None else None,
            timestamp=stamp, class_name=label, confidence=confidence(value),
            bbox=normalized_box(item, item_width, item_height),
            frame_width=item_width if number(item_width) else None,
            frame_height=item_height if number(item_height) else None,
            source_payload_reference=str(event.get("id", event.get("event_id"))),
            zone_state=item.get("zone_state") if isinstance(item.get("zone_state"), str) else None,
            confidence_label=qualitative,
        ))
    return result
