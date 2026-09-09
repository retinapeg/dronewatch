"""Minimal Viso Now delivery adapter.

WHAT THIS DOES NOT DO
---------------------
It does not guess Viso's payload schema. `DATA_SOURCES.md` records that the
public documentation defines no canonical schema, no signature scheme, no
idempotency key and no delivery guarantees, and that those must be captured from
a real account and a redacted test delivery. We have neither, so this adapter
recognises only shapes already evidenced inside this repository:

  * `appId` together with `incidentId` or `incidentNumber`
  * an `incidentUrl` whose host is `now.viso.ai`

Both come from the V0.1 dashboard's own provenance test (index.html) and the
existing webhook test fixture. Nothing else is invented.

Anything unrecognised is QUARANTINED as UNMAPPED. It is never silently turned
into a detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from ..domain.classification import ClassificationDistribution
from ..domain.enums import Modality
from ..domain.observation import SensorObservation

VISO_HOST = "now.viso.ai"


class MappingOutcome(str, Enum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"


def _text(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def looks_like_viso(payload: Mapping[str, Any]) -> bool:
    """The only provenance rule this repository has evidence for."""
    if not isinstance(payload, Mapping):
        return False
    app_id = _text(payload.get("appId"))
    incident = _text(payload.get("incidentId")) or _text(payload.get("incidentNumber"))
    if app_id and incident:
        return True
    incident_url = _text(payload.get("incidentUrl"))
    if incident_url:
        try:
            return urlsplit(incident_url).hostname == VISO_HOST
        except ValueError:
            return False
    return False


def _parse_time(value: Any) -> Optional[datetime]:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def redact(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """A summary safe to show in a browser: shape only, never values.

    Raw payloads may contain site names, media URLs and account identifiers, so
    the connection panel gets key names and sizes and nothing else.
    """
    if not isinstance(payload, Mapping):
        return {"type": type(payload).__name__, "keys": []}
    return {
        "type": "object",
        "keys": sorted(str(key) for key in payload)[:40],
        "key_count": len(payload),
    }


@dataclass(frozen=True)
class VisoDelivery:
    outcome: MappingOutcome
    reason: str
    observation: Optional[SensorObservation]
    observed_at_supplied: bool
    position_supplied: bool


def adapt(
    payload: Mapping[str, Any],
    *,
    received_at: datetime,
    delivery_id: str,
) -> VisoDelivery:
    """Map one delivery into the observation contract, or quarantine it.

    Deliberate omissions, each one a place where inventing data would be worse
    than admitting ignorance:

      * No classification is derived. Narrative text such as "No drone intrusion
        event emitted" must never become a positive result, so the distribution
        stays UNKNOWN and the caller is told nothing about what was seen.
      * No position is fabricated. Viso Now processes recorded media files; it
        does not publish a spatial frame we can trust, so position stays None
        and the observation appears in the non-spatial evidence list.
      * A missing timestamp stays missing. We fall back to our own receipt time
        and flag that we did so, rather than presenting it as an observation time.
    """
    if not looks_like_viso(payload):
        return VisoDelivery(
            outcome=MappingOutcome.UNMAPPED,
            reason=(
                "No recognised Viso provenance. Expected appId with "
                "incidentId/incidentNumber, or an incidentUrl on now.viso.ai."
            ),
            observation=None,
            observed_at_supplied=False,
            position_supplied=False,
        )

    supplied_time = None
    for key in ("timestamp", "eventTime", "createdAt", "created_at", "time"):
        supplied_time = _parse_time(payload.get(key))
        if supplied_time is not None:
            break

    observed_at = supplied_time or received_at
    if observed_at > received_at:
        # A sender cannot date a delivery in the future; V0.1.1 rule, applied here too.
        observed_at = received_at

    incident = (
        _text(payload.get("incidentId"))
        or _text(payload.get("incidentNumber"))
        or _text(payload.get("incidentUrl"))
        or delivery_id
    )
    app_id = _text(payload.get("appId")) or "viso"

    observation = SensorObservation(
        observation_id=f"viso-{delivery_id}",
        sensor_id=f"viso:{app_id}",
        modality=Modality.VISUAL_FILE,
        observed_at=observed_at,
        received_at=received_at,
        position=None,
        classification=ClassificationDistribution.unknown(),
        confidence=None,
        raw={
            "source": "VISO_NOW",
            "incident_reference": incident,
            "observed_at_supplied": supplied_time is not None,
            "processing": "RECORDED_FILE",
        },
    )
    return VisoDelivery(
        outcome=MappingOutcome.MAPPED,
        reason="Recognised Viso provenance; incident reference mapped.",
        observation=observation,
        observed_at_supplied=supplied_time is not None,
        position_supplied=False,
    )
