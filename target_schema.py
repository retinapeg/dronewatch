from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


STATUS_BY_EVENT_STATE = {
    "DETECTED": "TRACKED",
    "APPROACHING": "POSSIBLE THREAT",
    "RESTRICTED_ZONE": "THREAT",
    "EXITED": "UNKNOWN",
    "UNKNOWN": "UNKNOWN",
}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _matching_values(payload: Any, keys: Iterable[str]) -> List[Any]:
    wanted = {_compact(key) for key in keys}
    matches: List[Any] = []
    pending = [payload]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and _compact(key) in wanted:
                    matches.append(value)
                pending.append(value)
        elif isinstance(node, list):
            pending.extend(node)
    return matches


def _explicit_target_id(event: Dict[str, Any]) -> str:
    candidates = []
    for value in _matching_values(event.get("raw_payload"), ("tracking_id", "target_id")):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).strip()
            if text and text not in candidates:
                candidates.append(text)
    return candidates[0] if len(candidates) == 1 else event["event_id"]


def _finite_unit(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number


def _explicit_position(payload: Any) -> Optional[Dict[str, Any]]:
    candidates = []
    for value in _matching_values(payload, ("position",)):
        if not isinstance(value, dict) or "x" not in value or "y" not in value:
            continue
        coordinate_system = value.get("coordinate_system")
        if coordinate_system is not None and _compact(str(coordinate_system)) != "normalizedframe":
            continue
        x, y = _finite_unit(value["x"]), _finite_unit(value["y"])
        if x is not None and y is not None:
            candidates.append({"x": x, "y": y, "coordinate_system": "normalized_frame"})
    return candidates[0] if len(candidates) == 1 else None


def event_to_target(event: Dict[str, Any]) -> Dict[str, Any]:
    simulated = bool(event.get("is_simulated"))
    state = event.get("state") if event.get("state") in STATUS_BY_EVENT_STATE else "UNKNOWN"
    status = STATUS_BY_EVENT_STATE[state]
    raw_payload = event.get("raw_payload")
    source = str(event.get("source") or "UNKNOWN")
    raw_simulated = any(
        value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"})
        for value in _matching_values(raw_payload, ("is_simulated", "simulated", "is_synthetic", "synthetic"))
    )
    raw_test = any(
        value is True or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"})
        for value in _matching_values(raw_payload, ("is_test", "test", "test_event"))
    )
    source_marker = _compact(source)
    if simulated or raw_simulated or source_marker in {"simulated", "synthetic"}:
        source_kind = "SYNTHETIC_EVENT"
    elif raw_test or source_marker in {"test", "manualtest", "testevent"}:
        source_kind = "TEST_EVENT"
    else:
        source_kind = "WEBHOOK_EVENT"
    status_basis = "scenario_authored" if simulated else "reported_event"
    has_receipt_provenance = bool(event.get("ingested_at"))
    reported_time = (event.get("received_at") or "") if has_receipt_provenance else ""

    confidence = _finite_unit(event.get("confidence"))
    if simulated:
        evidence = ["Internally generated synthetic scenario event"]
    elif source_kind == "SYNTHETIC_EVENT":
        evidence = ["Source-marked synthetic webhook event"]
    elif source_kind == "TEST_EVENT":
        evidence = ["Source-marked test webhook event"]
    else:
        evidence = ["Stored unauthenticated webhook event reported by the source"]
    if event.get("detection_type"):
        evidence.append(f"Reported detection type: {event['detection_type']}")
    if state != "UNKNOWN":
        evidence.append(f"Reported event state: {state}")

    if state == "RESTRICTED_ZONE":
        alternative = "The reported zone entry may reflect benign, misclassified, or unauthorised activity."
        uncertainty = "Restricted-zone status is source-reported and is not validated evidence of hostile intent."
    else:
        alternative = "The observation may be benign activity or a source classification error."
        uncertainty = "No independent validation of identity, intent, position, or movement is available."
    if len(_matching_values(raw_payload, ("label",))) > 1:
        uncertainty = "Multiple reported objects are ambiguous; no single classification is selected."

    return {
        "target_id": _explicit_target_id(event),
        "event_id": event["event_id"],
        "source_kind": source_kind,
        "status": status,
        "confidence": confidence,
        "position": _explicit_position(event.get("raw_payload")),
        "velocity": None,
        "heading": None,
        "source": source,
        "updated_at": reported_time,
        "timestamp_basis": "reported_event_time" if reported_time else "receipt_time_only",
        "last_received_at": event.get("ingested_at") or "",
        "evidence": evidence,
        "alternative_interpretation": alternative,
        "uncertainty": uncertainty,
        "status_basis": status_basis,
    }


def targets_from_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    targets = []
    seen = set()

    def newest_first(event: Dict[str, Any]) -> tuple[datetime, int]:
        try:
            sort_time = event.get("ingested_at") or event.get("received_at")
            received = datetime.fromisoformat(str(sort_time).replace("Z", "+00:00"))
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            received = received.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            received = datetime.min.replace(tzinfo=timezone.utc)
        return received, int(event.get("id") or 0)

    for event in sorted(events, key=newest_first, reverse=True):
        target = event_to_target(event)
        identity = (target["source_kind"], target["source"], target["target_id"])
        if identity in seen:
            continue
        seen.add(identity)
        targets.append(target)
    return targets
