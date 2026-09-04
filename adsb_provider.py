"""One provider, read-only HTTP GETs, no aircraft transmission or control."""
import datetime
import json
import re
import time

import httpx

if __package__:
    from .geometry import Origin, finite_number, geodetic_to_enu
else:
    from geometry import Origin, finite_number, geodetic_to_enu


PROVIDER = "ADSB.LOL"
PROVENANCE = "LIVE_PUBLIC_ADSB"
FEET_TO_METRES = 0.3048
KNOTS_TO_MPS = 1852/3600
FPM_TO_MPS = 0.3048/60


def iso(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).isoformat()


def text_field(value, maximum=80):
    return value.strip()[:maximum] or None if isinstance(value, str) else None


def bounded(value, lower, upper):
    value = finite_number(value)
    return value if value is not None and lower <= value <= upper else None


def normalize_aircraft(raw, received_at, provider_epoch=None, origin=None):
    if not isinstance(raw, dict):
        return None
    identity = raw.get("hex")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", identity):
        return None
    latitude, longitude = bounded(raw.get("lat"), -90, 90), bounded(raw.get("lon"), -180, 180)
    if latitude is None or longitude is None:
        return None
    geometric, barometric = bounded(raw.get("alt_geom"), -2000, 100000), bounded(raw.get("alt_baro"), -2000, 100000)
    altitude = geometric if geometric is not None else barometric
    basis = "GEOMETRIC / PROVIDER GNSS HEIGHT" if geometric is not None else "BAROMETRIC / PRESSURE ALTITUDE APPROXIMATION" if barometric is not None else "NOT PROVIDED"
    altitude_m = altitude*FEET_TO_METRES if altitude is not None else None
    speed, course = bounded(raw.get("gs"), 0, 1500), bounded(raw.get("track"), 0, 360)
    true_heading = bounded(raw.get("true_heading"), 0, 360)
    heading = true_heading if true_heading is not None else course
    rate, rate_basis = bounded(raw.get("geom_rate"), -30000, 30000), "GEOMETRIC"
    if rate is None:
        rate, rate_basis = bounded(raw.get("baro_rate"), -30000, 30000), "BAROMETRIC"
    age = bounded(raw.get("seen_pos"), 0, 86400)
    observed_at = (provider_epoch if provider_epoch is not None else received_at)-age if age is not None else None
    geometry = geodetic_to_enu(latitude, longitude, altitude_m, origin)
    return {"track_id": "DW-"+identity.upper(), "icao24": identity.lower(),
        "callsign": text_field(raw.get("flight")), "registration": text_field(raw.get("r")),
        "aircraft_type": text_field(raw.get("t")), "message_type": text_field(raw.get("type")),
        "latitude": latitude, "longitude": longitude, "altitude_m": altitude_m,
        "altitude_basis": basis, "ground_speed_mps": speed*KNOTS_TO_MPS if speed is not None else None,
        "heading_deg": heading % 360 if heading is not None else None,
        "heading_basis": "TRUE HEADING" if true_heading is not None else "GROUND TRACK / COURSE" if course is not None else "NOT PROVIDED",
        "course_deg": course % 360 if course is not None else None,
        "vertical_rate_mps": rate*FPM_TO_MPS if rate is not None else None,
        "vertical_rate_basis": rate_basis if rate is not None else "NOT PROVIDED",
        "on_ground": raw.get("alt_baro")=="ground", "position_observed_at": observed_at,
        "position_age_known": age is not None, "last_seen": iso(observed_at) if observed_at is not None else None,
        "received_at": iso(received_at), "received_epoch": received_at,
        "source": PROVIDER, "provenance": PROVENANCE, "synthetic": False, **geometry}


def normalize_response(payload, received_at=None, origin=None, limit=60, max_range_m=50000):
    if not isinstance(payload, dict) or not isinstance(payload.get("ac"), list):
        raise ValueError("Provider response has no valid aircraft array")
    if len(payload["ac"]) > 10000:
        raise ValueError("Provider response exceeds the bounded aircraft limit")
    received_at = time.time() if received_at is None else received_at
    epoch = finite_number(payload.get("now"))
    if epoch is not None:
        epoch = epoch/1000 if epoch > 1e12 else epoch
        if not 946684800 <= epoch <= received_at+30:
            epoch = None
    by_identity = {}
    for raw in payload["ac"]:
        track = normalize_aircraft(raw, received_at, epoch, origin)
        if track is None or track["on_ground"] or track["horizontal_range_m"] > max_range_m:
            continue
        age = received_at-(track["position_observed_at"] or received_at)
        if age > 180:
            continue
        by_identity[track["track_id"]] = track
    tracks = sorted(by_identity.values(), key=lambda item:(item["horizontal_range_m"], item["track_id"]))[:limit]
    return {"provider": PROVIDER, "provenance": PROVENANCE, "provider_time": iso(epoch) if epoch else None,
            "received_at": iso(received_at), "received_epoch": received_at, "origin": (origin or Origin()).snapshot(),
            "tracks": tracks, "reported_aircraft": len(payload["ac"])}


class ADSBLolProvider:
    def __init__(self, origin=None):
        self.origin = origin or Origin()
        self.url = "https://api.adsb.lol/v2/lat/%s/lon/%s/dist/50" % (self.origin.latitude, self.origin.longitude)

    async def fetch(self, client):
        async with client.stream("GET", self.url, headers={"Accept":"application/json", "User-Agent":"DroneWatch-Integrity-Demo/1.0"}) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 2_000_000:
                    raise ValueError("Provider response exceeded 2 MB")
                chunks.append(chunk)
        return normalize_response(json.loads(b"".join(chunks)), origin=self.origin)
