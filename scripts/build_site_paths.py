"""Record Monte Carlo path clouds for lost contacts for the static GitHub Pages demo.

For every recorded replay in site/api/tracks__*.json, runs the real get_paths() for each
lost (not 'U') contact once per 2-second bucket of replay time and writes
site/api/paths/<name>__42__<count>__<mode>__<track>__<bucket>.json, where bucket = floor(t / 2).
Coordinates are rounded to whole metres to keep the files small. Run after build_site.py.
Usage: python scripts/build_site_paths.py [worker_index worker_count]
"""
from __future__ import annotations
import json, math, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dronewatch.api import preview as p  # noqa: E402

API = ROOT / "site" / "api"
OUT = API / "paths"
OUT.mkdir(parents=True, exist_ok=True)
BUCKET_S = 2


def _round(v):
    if isinstance(v, float):
        return round(v)
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v


jobs = []
for fn in sorted(API.glob("tracks__*.json")):
    name, seed, count, mode = fn.stem.split("__")[1:]
    d = json.loads(fn.read_text())
    seen = set()
    for f in d["frames"]:
        for t in f["tracks"]:
            if t.get("fresh") == "U":
                continue
            key = (t["id"], math.floor(f["t"] / BUCKET_S))
            if key not in seen:
                seen.add(key)
                jobs.append((name, int(count), mode, t["id"], f["t"], key[1]))

wi, wn = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) == 3 else (0, 1)
n = 0
for i, (name, count, mode, track, t, bucket) in enumerate(jobs):
    if i % wn != wi:
        continue
    out = OUT / f"{name}__42__{count}__{mode}__{track}__{bucket}.json"
    if out.exists():
        continue
    r = p.get_paths(name=name, seed=42, count=count, duration_s=p.OPERATOR_DEMO_DURATION_S, mode=mode,
                    track=track, t=t, paths=140, horizon_s=20.0, max_speed=45.0)
    r["paths"] = _round(r["paths"])
    r["hull95"] = _round(r.get("hull95"))
    out.write_text(json.dumps(r, separators=(",", ":")))
    n += 1
print(f"worker {wi}/{wn}: wrote {n} of {len(jobs)} path clouds to {OUT}")
