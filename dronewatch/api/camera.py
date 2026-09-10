"""Recorded synthetic camera media and authenticated Viso receipt evidence.

This surface never manufactures detections from the synthetic scene. Webhook
text is sender evidence, including unknown payload shapes; it is not a mapped
classification. The bounded private evidence store exists to inspect actual
Viso schemas without publishing complete webhook payloads to the browser.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import quote
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[2]
MAX_RESULTS = 50
MAX_EVIDENCE_CHARS = 32_768
MEDIA_TYPES = {".png": "image/png", ".mp4": "video/mp4"}
_SENSITIVE_KEY = re.compile(r"token|secret|password|authorization|cookie|apikey", re.I)
_URL_TOKEN = re.compile(r"([?&](?:token|key|secret|signature)=)[^&\s]+", re.I)


def media_directory() -> Path:
    return Path(os.getenv("DRONEWATCH_CAMERA_MEDIA_DIR", str(BASE_DIR / "data/generated/camera-media"))).expanduser().resolve()


def evidence_path() -> Path:
    explicit = os.getenv("DRONEWATCH_CAMERA_EVIDENCE_DB")
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Follow an explicitly isolated app database (including test databases).
    app_database = os.getenv("DRONEWATCH_DB_PATH")
    if app_database:
        path = BASE_DIR / app_database
        return path.with_name(path.stem + "-camera.sqlite3")
    return BASE_DIR / "data/generated/camera-evidence.sqlite3"


def _connect() -> sqlite3.Connection:
    path = evidence_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # The raw, scrubbed evidence is local only and is not an API response.
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS camera_receipts ("
        "sequence INTEGER PRIMARY KEY AUTOINCREMENT, result_json TEXT NOT NULL, "
        "evidence_json TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS camera_totals ("
        "id INTEGER PRIMARY KEY CHECK(id=1), delivery_count INTEGER NOT NULL DEFAULT 0, "
        "mapped_count INTEGER NOT NULL DEFAULT 0, probe_count INTEGER NOT NULL DEFAULT 0, "
        "last_receipt_at TEXT)"
    )
    connection.execute("INSERT OR IGNORE INTO camera_totals (id) VALUES (1)")
    return connection


def _safe_text(value: Any, limit: int = 2000) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    secret = os.getenv("DRONEWATCH_WEBHOOK_SECRET", "").strip()
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = _URL_TOKEN.sub(r"\1[REDACTED]", text)
    return text[:limit]


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[depth limit]"
    if isinstance(value, dict):
        return {
            str(key)[:120]: "[REDACTED]" if _SENSITIVE_KEY.search(re.sub(r"[^a-z]", "", str(key).lower()))
            else _scrub(item, depth + 1)
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value[:80]]
    if isinstance(value, str):
        return _safe_text(value, 4000)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _first_text(payload: Any, keys: tuple[str, ...]) -> str | None:
    queue = [payload]
    examined = 0
    while queue and examined < 200:
        node = queue.pop(0)
        examined += 1
        if isinstance(node, dict):
            for key in keys:
                if text := _safe_text(node.get(key)):
                    return text
            queue.extend(value for value in node.values() if isinstance(value, (dict, list)))
        elif isinstance(node, list):
            queue.extend(node[:80])
    return None


def _has_content(value: Any, depth: int = 0) -> bool:
    if depth > 16:
        return True
    if isinstance(value, dict):
        return any(_has_content(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item, depth + 1) for item in value)
    return value is not None and value != ""


def _source_filename(payload: dict[str, Any]) -> str | None:
    name = _first_text(payload, ("source_filename", "sourceFilename", "fileName", "filename"))
    # A basename must be explicitly supplied. A guessed URL or filename would
    # falsely correlate a result to whatever clip happens to be playing now.
    if not name or Path(name).name != name or "/" in name or "\\" in name or "\x00" in name:
        return None
    return name[:255]


def record_delivery(payload: dict[str, Any], *, outcome: str, received_at: str) -> None:
    """Record only after webhook authentication and successful JSON parsing."""
    probe = not _has_content(payload)
    synthetic_sender = any(payload.get(key) is True for key in ("synthetic", "SIMULATED", "is_simulated", "isSimulated"))
    synthetic_sender = synthetic_sender or str(payload.get("source", "")).upper() in {"SYNTHETIC", "SIMULATED"}
    result = {
        "id": str(uuid.uuid4()),
        "received_at": received_at,
        "outcome": outcome,
        "incident_reference": _first_text(payload, ("incidentId", "incidentNumber", "incidentUrl")),
        "summary": _first_text(payload, ("summary", "description", "message", "result", "output")),
        "source_filename": _source_filename(payload),
        "synthetic_sender": synthetic_sender,
        # No evidenced Viso box/frame schema exists yet. Even plausible x/y
        # fields must not be interpreted as boxes over an unrelated video loop.
        "boxes": [],
        "payload_shape": {"keys": sorted(str(key)[:120] for key in payload)[:40]},
    }
    result.update(_sender_fields(payload))
    connection = _connect()
    try:
        with connection:
            connection.execute(
                "UPDATE camera_totals SET delivery_count=delivery_count+1, "
                "mapped_count=mapped_count+?, probe_count=probe_count+?, last_receipt_at=? WHERE id=1",
                (int(not probe and outcome == "MAPPED" and not synthetic_sender), int(probe), received_at),
            )
            if not probe:
                evidence = json.dumps(_scrub(payload), ensure_ascii=True, allow_nan=False)
                if len(evidence) > MAX_EVIDENCE_CHARS:
                    evidence = json.dumps({"truncated": True, "prefix": evidence[:MAX_EVIDENCE_CHARS // 4]})
                connection.execute(
                    "INSERT INTO camera_receipts (result_json, evidence_json) VALUES (?, ?)",
                    (json.dumps(result, allow_nan=False), evidence),
                )
                connection.execute(
                    "DELETE FROM camera_receipts WHERE sequence NOT IN "
                    "(SELECT sequence FROM camera_receipts ORDER BY sequence DESC LIMIT ?)", (MAX_RESULTS,),
                )
    finally:
        connection.close()


def _media_path(filename: str) -> Path:
    directory = media_directory()
    if not filename or filename != Path(filename).name or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=404, detail="Unknown camera media")
    path = directory / filename
    if path.suffix.lower() not in MEDIA_TYPES or path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
        raise HTTPException(status_code=404, detail="Unknown camera media")
    return path


def _media() -> list[dict[str, Any]]:
    directory = media_directory()
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.iterdir(), key=lambda item: (item.suffix.lower() != ".mp4", item.name)):
        try:
            _media_path(path.name)
        except HTTPException:
            continue
        item = {"id": path.name, "filename": path.name, "url": "/api/camera/media/" + quote(path.name), "synthetic": True}
        if path.suffix.lower() == ".mp4":
            poster = path.with_suffix(".png")
            if poster.is_file() and not poster.is_symlink():
                item["poster_url"] = "/api/camera/media/" + quote(poster.name)
        result.append(item)
        if len(result) >= 50:
            break
    return result


def _feed_state() -> dict[str, Any] | None:
    filename = os.getenv("DRONEWATCH_CAMERA_FEED_STATE")
    if not filename:
        return None
    try:
        path = Path(filename)
        if path.stat().st_size > 65_536:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("transport") != "GOOGLE_DRIVE":
        return None
    state = data.get("state")
    if state not in {"preparing", "uploading", "submitted", "error"}:
        return None
    uploads = data.get("uploads", [])
    if not isinstance(uploads, list):
        uploads = []
    return {
        "transport": "GOOGLE_DRIVE", "state": state,
        "folder_name": _safe_text(data.get("folder_name"), 100),
        "message": _safe_text(data.get("message"), 500),
        "uploads": [{key: _safe_text(item.get(key), 255) for key in ("filename", "drive_file_id", "uploaded_at")}
                    for item in uploads[:50] if isinstance(item, dict)],
    }


def _sender_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """The label schema observed in an actual Viso Now callback, not prose inference."""
    labels = []
    supplied = payload.get("labels", [])
    if isinstance(supplied, list):
        for item in supplied[:20]:
            if not isinstance(item, dict) or not (label := _safe_text(item.get("label"), 100)):
                continue
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                confidence = None
            labels.append({
                "label": label, "confidence": confidence,
                **{key: _safe_text(item.get(key), 200) for key in (
                    "approximate_position", "motion_state", "tracking_status", "zone_state", "zone_intrusion_event",
                )},
            })
    return {"labels": labels, "decision": _safe_text(payload.get("decision"), 200),
            "severity": _safe_text(payload.get("severity"), 100)}


def _scenario_contexts() -> dict[str, dict[str, Any]]:
    """Media-only correlation metadata; never export generator truth or object IDs."""
    path = media_directory() / "manifest.json"
    try:
        if path.stat().st_size > 131_072:
            return {}
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(manifest, dict) or not isinstance(manifest.get("clips"), list):
        return {}
    contexts = {}
    for clip in manifest["clips"][:50]:
        if not isinstance(clip, dict) or clip.get("frame") != "LOCAL_SIM_METRES":
            continue
        scenario, mode = clip.get("scenario"), clip.get("mode")
        seed, count = clip.get("seed"), clip.get("count")
        start, end = clip.get("sim_start_s"), clip.get("sim_end_s")
        if scenario not in {"operator_demo", "operator_demo_signal_loss"} or not isinstance(mode, str) or not re.fullmatch(r"[a-z0-9_]{1,60}", mode):
            continue
        if type(seed) is not int or not 0 <= seed <= 999999 or type(count) is not int or not 3 <= count <= 10:
            continue
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, end)) or not 0 <= start <= end <= 300:
            continue
        context = {"scenario": scenario, "mode": mode, "seed": seed, "count": count,
                   "sim_start_s": start, "sim_end_s": end, "available_at_sim_s": end,
                   "frame": "LOCAL_SIM_METRES"}
        duration = clip.get("duration_seconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and 0 < duration <= 300:
            context["duration_seconds"] = duration
        for key in ("file", "still"):
            name = clip.get(key)
            if not isinstance(name, str):
                continue
            try:
                _media_path(name)
            except HTTPException:
                continue
            item = dict(context)
            if key == "still":
                at = clip.get("still_sim_time_s")
                if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or not start <= at <= end:
                    continue
                item.update(sim_start_s=at, sim_end_s=at, available_at_sim_s=at, duration_seconds=0)
            contexts[name] = item
    return contexts


@router.get("/camera")
def camera_page() -> FileResponse:
    return FileResponse(BASE_DIR / "camera.html")


@router.get("/api/camera/media/{filename}")
def camera_media(filename: str) -> FileResponse:
    path = _media_path(filename)
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix.lower()], headers={"X-Content-Type-Options": "nosniff"})


@router.get("/api/camera/status")
def camera_status() -> dict[str, Any]:
    connection = _connect()
    try:
        with connection:
            totals = connection.execute("SELECT delivery_count, mapped_count, probe_count, last_receipt_at FROM camera_totals WHERE id=1").fetchone()
            rows = connection.execute("SELECT result_json, evidence_json FROM camera_receipts ORDER BY sequence DESC LIMIT ?", (MAX_RESULTS,)).fetchall()
    finally:
        connection.close()
    contexts = _scenario_contexts()
    results = []
    for result_json, evidence_json in rows:
        result = json.loads(result_json)
        evidence = json.loads(evidence_json)
        # New receipts preserve the public sender fields even if private
        # evidence is truncated. Older stored receipts are enriched on read.
        for key, value in _sender_fields(evidence).items():
            result.setdefault(key, value)
        result["scenario_context"] = contexts.get(result.get("source_filename"))
        results.append(result)
    media = _media()
    for item in media:
        item["scenario_context"] = contexts.get(item["filename"])
    return {
        "media": media, "results": results,
        "configured": bool(os.getenv("DRONEWATCH_WEBHOOK_SECRET", "").strip()),
        "delivery_count": totals[0], "mapped_count": totals[1],
        "probe_count": totals[2], "last_receipt_at": totals[3],
        "webhook": {"path": "/v2/webhook/viso", "processing": "RECORDED_FILE"},
        "feed": _feed_state(),
    }


@router.get("/api/preview/viso/evidence")
def preview_evidence(
    name: str = Query("operator_demo"), seed: int = Query(42, ge=0, le=999999),
    count: int = Query(6, ge=3, le=10), mode: str = Query("radar_off_30s_viso"),
    t: float = Query(0, ge=0, le=300),
) -> dict[str, Any]:
    """Non-spatial sender evidence beside the existing operator loss/cue flow.

    Exact file/manifest correlation is required to associate an incident with a
    scenario. A recorded clip's complete result is held until the clip ends in
    replay time, so its later events do not leak into earlier tracker frames.
    """
    status = camera_status()
    matched, uncorrelated, pending = [], [], 0
    for result in status["results"]:
        if result["outcome"] != "MAPPED" or result["synthetic_sender"]:
            continue
        context = result["scenario_context"]
        if context is None:
            uncorrelated.append(result)
        elif (context["scenario"], context["seed"], context["count"], context["mode"]) == (name, seed, count, mode):
            if context["available_at_sim_s"] <= t:
                matched.append(result)
            else:
                pending += 1
    return {"configured": status["configured"], "results": matched[:10],
            "uncorrelated_results": uncorrelated[:3], "pending_count": pending,
            "position_updates": False, "last_receipt_at": status["last_receipt_at"]}
