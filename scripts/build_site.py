"""Record the tracker's replay output for the static GitHub Pages demo (site/api/).

Runs the real get_tracks() for every operator scenario x contact count x sensor-loss mode at
seed 42 and writes one JSON file per combination. Requires the project's dependencies.
"""
from __future__ import annotations
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from dronewatch.api import preview as p  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "site" / "api"
OUT.mkdir(parents=True, exist_ok=True)
n = 0
for name in p.OPERATOR_SCENARIOS:
    for count in (3, 6, 10):
        for mode in p.SENSOR_LOSS_MODES:
            d = p.get_tracks(name=name, seed=42, count=count, duration_s=p.OPERATOR_DEMO_DURATION_S, mode=mode)
            (OUT / f"tracks__{name}__42__{count}__{mode}.json").write_text(json.dumps(d, separators=(",", ":")))
            n += 1
(OUT / "viso_status.json").write_text(json.dumps({"state": "not_configured", "configured": False, "header_name": None, "static_demo": True}))
(OUT / "camera_status.json").write_text(json.dumps({"delivery_count": 0, "mapped_count": 0, "probe_count": 0, "last_receipt_at": None, "results": [], "static_demo": True}))
print(f"wrote {n} replays to {OUT}")
