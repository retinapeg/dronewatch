#!/usr/bin/env python3
"""Feed synthetic Viso Now deliveries into DroneWatch's authenticated webhook.

Two sources, so a demo cannot fail for want of a credential:

  --source generate      build a realistic incident sequence locally (default)
  --source drive         pull JSON/JSONL from a Google Drive folder or file
  --source local         read JSON/JSONL from a directory on disk

Everything goes through the REAL protected endpoint (/v2/webhook/viso) with the
real shared secret, so what a demo shows is the genuine ingestion path,
including authentication, the provenance rules and quarantine — not a bypass.

Google Drive access, in order of preference:
  1. --drive-folder <id> --drive-key <API key>
     Folder must be shared "Anyone with the link". Uses the public Drive v3 API.
  2. --drive-file <id>
     A single file shared "Anyone with the link"; no API key needed.

Nothing here invents a Viso schema. It emits the two shapes this repository has
evidence for (appId+incidentId, and an incidentUrl on now.viso.ai) and, when
asked, a deliberately unrecognised one so the quarantine path is visible.

    python scripts/viso_feed.py --secret "$DRONEWATCH_WEBHOOK_SECRET"
    python scripts/viso_feed.py --source drive --drive-folder 1AbC... --drive-key AIza...
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

DEFAULT_URL = "http://127.0.0.1:8010/v2/webhook/viso"
DEFAULT_HEADER = "X-DroneWatch-Token"
VISO_HOST = "now.viso.ai"

SITES = ["Site Alpha North Gate", "Site Alpha Perimeter East", "Site Alpha Apron"]
LABELS = ["drone", "drone", "drone", "bird", "unknown"]


# --------------------------------------------------------------------------
# synthetic generation
# --------------------------------------------------------------------------

def synthetic_deliveries(count: int, seed: int, include_unmapped: bool) -> List[Dict[str, Any]]:
    """A plausible sequence of Viso incident notifications.

    Deliberately SYNTHETIC and labelled as such in the payload, so nothing here
    can later be mistaken for a real detection record.
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []

    for i in range(count):
        at = now - timedelta(seconds=(count - i) * rng.randint(20, 90))
        incident = f"INC-{at:%Y%m%d}-{i + 1:04d}"
        label = rng.choice(LABELS)
        confidence = round(rng.uniform(0.61, 0.97), 3)

        if i % 4 == 3:
            # The url-only provenance shape, which the adapter also recognises.
            payload = {
                "incidentUrl": f"https://{VISO_HOST}/incidents/{incident}",
                "detectedAt": at.isoformat().replace("+00:00", "Z"),
                "label": label,
                "confidence": confidence,
                "siteName": rng.choice(SITES),
                "synthetic": True,
            }
        else:
            payload = {
                "appId": f"viso-app-{7000 + (seed % 900)}",
                "incidentId": incident,
                "incidentNumber": i + 1,
                "incidentUrl": f"https://{VISO_HOST}/incidents/{incident}",
                "detectedAt": at.isoformat().replace("+00:00", "Z"),
                "label": label,
                "confidence": confidence,
                "siteName": rng.choice(SITES),
                "mediaUrl": f"https://{VISO_HOST}/media/{incident}.mp4",
                "synthetic": True,
            }
        out.append(payload)

    if include_unmapped:
        # One deliberately unrecognised delivery, so the demo can show that an
        # unknown shape is quarantined rather than becoming a detection.
        out.insert(
            min(2, len(out)),
            {"event": "heartbeat", "source": "unknown-vendor", "value": 1, "synthetic": True},
        )
    return out


def scenario_viso_deliveries(seed: int, count: int, mode_faults: str) -> List[Dict[str, Any]]:
    """The scenario's own Viso camera detections, as webhook payloads.

    These are the SAME synthetic detections the tracker consumes in the
    'radar_off_30s_viso' mode, so what the Connections panel shows arriving is
    what re-localised the tracks on the map. Observation ids become incident
    ids, so the two can be matched by eye.
    """
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from dronewatch.synthetic.generator import FaultSpec, T_ZERO, generate_scenario, VISO_SENSOR_ID
    s = generate_scenario("operator_demo", seed=seed, duration_s=90.0, count=count,
                          faults=FaultSpec.parse(mode_faults))
    out = []
    for o in s.observations:
        if o.sensor_id != VISO_SENSOR_ID or o.position is None:
            continue
        t = (o.observed_at - T_ZERO).total_seconds()
        top = o.classification.top() if o.classification else (None, None)
        out.append({
            "appId": f"viso-app-{7000 + (seed % 900)}",
            "incidentId": o.observation_id,
            "incidentUrl": f"https://{VISO_HOST}/incidents/{o.observation_id}",
            "detectedAt": o.observed_at.isoformat().replace("+00:00", "Z"),
            "simulationTime": round(t, 2),
            "label": str(getattr(top[0], "value", top[0]) or "drone").lower(),
            "confidence": o.confidence,
            "siteName": "Site Alpha — Viso EO, north sector",
            # Geolocated by the camera (calibrated, ground-plane intersection).
            "localPosition": {"x": o.position.latitude, "y": o.position.longitude,
                              "frame": "LOCAL_SIM_METRES"},
            "synthetic": True,
        })
    out.sort(key=lambda d: d["simulationTime"])
    return out


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def _records_from_text(text: str, origin: str) -> List[Dict[str, Any]]:
    """Accept a JSON array, a single JSON object, or JSONL."""
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except json.JSONDecodeError:
            print(f"  ! skipping unparseable line in {origin}", file=sys.stderr)
    return rows


def from_local(directory: str) -> List[Dict[str, Any]]:
    base = Path(directory).expanduser()
    if not base.exists():
        raise SystemExit(f"Local source not found: {base}")
    files = sorted(base.glob("*.json")) + sorted(base.glob("*.jsonl")) if base.is_dir() else [base]
    out: List[Dict[str, Any]] = []
    for f in files:
        out.extend(_records_from_text(f.read_text(encoding="utf-8", errors="replace"), f.name))
    print(f"  read {len(out)} record(s) from {len(files)} file(s) in {base}")
    return out


def _fetch(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "dronewatch-viso-feed/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def from_drive_file(file_id: str) -> List[Dict[str, Any]]:
    """A single Drive file shared 'Anyone with the link'. No API key required."""
    url = f"https://drive.google.com/uc?export=download&id={urllib.parse.quote(file_id)}"
    try:
        text = _fetch(url)
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Google Drive returned HTTP {e.code} for file {file_id}.\n"
            "Check the file is shared with 'Anyone with the link'."
        )
    if text.lstrip().startswith("<"):
        raise SystemExit(
            "Google Drive returned an HTML page rather than the file. That usually\n"
            "means the file is not shared publicly, or it is large enough to hit the\n"
            "virus-scan interstitial. Share it with 'Anyone with the link', or use\n"
            "--source drive --drive-folder with an API key."
        )
    rows = _records_from_text(text, f"drive:{file_id}")
    print(f"  read {len(rows)} record(s) from Drive file {file_id}")
    return rows


def from_drive_folder(folder_id: str, api_key: str) -> List[Dict[str, Any]]:
    """List a publicly shared folder via the Drive v3 API and read each file."""
    query = urllib.parse.quote(f"'{folder_id}' in parents and trashed=false")
    list_url = (
        "https://www.googleapis.com/drive/v3/files"
        f"?q={query}&key={urllib.parse.quote(api_key)}"
        "&fields=files(id,name,mimeType,size)&pageSize=200"
    )
    try:
        listing = json.loads(_fetch(list_url))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise SystemExit(
            f"Drive API returned HTTP {e.code}.\n{detail}\n\n"
            "Check: the folder is shared 'Anyone with the link', the API key is\n"
            "valid, and the Drive API is enabled for that key's project."
        )

    files = [f for f in listing.get("files", [])
             if f.get("name", "").endswith((".json", ".jsonl"))]
    if not files:
        raise SystemExit(f"No .json or .jsonl files found in Drive folder {folder_id}.")

    out: List[Dict[str, Any]] = []
    for f in sorted(files, key=lambda x: x.get("name", "")):
        media = (
            "https://www.googleapis.com/drive/v3/files/"
            f"{f['id']}?alt=media&key={urllib.parse.quote(api_key)}"
        )
        try:
            out.extend(_records_from_text(_fetch(media), f["name"]))
        except urllib.error.HTTPError as e:
            print(f"  ! could not read {f['name']}: HTTP {e.code}", file=sys.stderr)
    print(f"  read {len(out)} record(s) from {len(files)} Drive file(s)")
    return out


# --------------------------------------------------------------------------
# delivery
# --------------------------------------------------------------------------

def post(url: str, header: str, secret: str, payload: Dict[str, Any],
         timeout: float = 15.0) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"content-type": "application/json", header: secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"http": resp.status, **json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "error": e.read().decode("utf-8", errors="replace")[:200]}
    except urllib.error.URLError as e:
        return {"http": 0, "error": f"{e.reason}"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--secret", default=None,
                   help="shared secret; defaults to $DRONEWATCH_WEBHOOK_SECRET")
    p.add_argument("--header", default=DEFAULT_HEADER)
    p.add_argument("--source", choices=["generate", "drive", "local", "scenario"], default="generate")
    p.add_argument("--scenario-faults", default="radar:40-70;backup:viso",
                   help="fault spec whose Viso camera detections to replay (--source scenario)")
    p.add_argument("--from-t", type=float, default=None, help="only detections at/after this sim time")
    p.add_argument("--to-t", type=float, default=None, help="only detections at/before this sim time")
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--interval", type=float, default=2.0,
                   help="seconds between deliveries (0 = as fast as possible)")
    p.add_argument("--include-unmapped", action="store_true",
                   help="also send one unrecognised payload to show quarantine")
    p.add_argument("--drive-folder", default=None)
    p.add_argument("--drive-file", default=None)
    p.add_argument("--drive-key", default=None)
    p.add_argument("--local-dir", default="data/viso_synthetic")
    p.add_argument("--dry-run", action="store_true", help="print payloads, send nothing")
    p.add_argument("--out", default=None,
                   help="write the payloads to this JSON file instead of sending; "
                        "upload it to Google Drive and feed it back with --source drive")
    args = p.parse_args(argv)

    import os
    secret = args.secret or os.getenv("DRONEWATCH_WEBHOOK_SECRET", "").strip()
    # Only sending needs a secret; --out and --dry-run do not touch the network.
    if not secret and not args.dry_run and not args.out:
        raise SystemExit(
            "No secret. Pass --secret or set DRONEWATCH_WEBHOOK_SECRET.\n"
            "It must match what the server was started with."
        )

    print(f"Source: {args.source}")
    if args.source == "generate":
        payloads = synthetic_deliveries(args.count, args.seed, args.include_unmapped)
        print(f"  generated {len(payloads)} synthetic delivery(ies)")
    elif args.source == "local":
        payloads = from_local(args.local_dir)
    elif args.source == "scenario":
        payloads = scenario_viso_deliveries(args.seed, args.count, args.scenario_faults)
        if args.from_t is not None:
            payloads = [p_ for p_ in payloads if p_["simulationTime"] >= args.from_t]
        if args.to_t is not None:
            payloads = [p_ for p_ in payloads if p_["simulationTime"] <= args.to_t]
        print(f"  {len(payloads)} Viso camera detection(s) from the scenario "
              f"({args.scenario_faults})")
    else:
        if args.drive_folder:
            if not args.drive_key:
                raise SystemExit("--drive-folder needs --drive-key (a Google API key).")
            payloads = from_drive_folder(args.drive_folder, args.drive_key)
        elif args.drive_file:
            payloads = from_drive_file(args.drive_file)
        else:
            raise SystemExit("Use --drive-folder <id> --drive-key <key>, or --drive-file <id>.")

    if not payloads:
        raise SystemExit("Nothing to send.")

    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payloads, indent=1), encoding="utf-8")
        print(f"  wrote {len(payloads)} record(s) to {out}")
        print("  Upload this file to Google Drive, share it with 'Anyone with the link',")
        print("  then feed it back with:  --source drive --drive-file <file id>")
        return 0

    if args.dry_run:
        for pl in payloads:
            print(json.dumps(pl, indent=1))
        return 0

    print(f"\nPOSTing to {args.url}\n")
    mapped = quarantined = failed = 0
    for i, pl in enumerate(payloads, 1):
        res = post(args.url, args.header, secret, pl)
        outcome = res.get("outcome") or res.get("error", "")[:60] or res.get("status", "?")
        ident = pl.get("incidentId") or pl.get("incidentUrl", "").rsplit("/", 1)[-1] or pl.get("event", "-")
        marker = {"MAPPED": "+", "UNMAPPED": "~"}.get(res.get("outcome"), "!")
        print(f"  {marker} [{i:>3}/{len(payloads)}] HTTP {res.get('http')} {outcome:<12} {ident}")
        if res.get("outcome") == "MAPPED":
            mapped += 1
        elif res.get("outcome") == "UNMAPPED":
            quarantined += 1
        else:
            failed += 1
        if args.interval and i < len(payloads):
            time.sleep(args.interval)

    print(f"\n  mapped {mapped}   quarantined {quarantined}   failed {failed}")
    print("  Quarantined deliveries are NOT detections; they are held for inspection.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
