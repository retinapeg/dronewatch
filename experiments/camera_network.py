"""Reproducible camera-network experiments.

The camera-network mode of the operator preview, run on seeds it was not
developed on and scored against the ground truth the tracker never sees:

    python -m experiments.camera_network            # held-out seeds (~1 min)
    python -m experiments.camera_network --out /tmp/dw

Seeds: the camera layout and the pairing rules were worked out on seed 42 and
checked on seeds 1 to 10. The four held-out seeds of experiments/sensor_loss.py
(2024, 31337, 99, 555) were then run once, and what they showed (contacts on
the flanks of the approach held by one camera only) led to four cameras being
added, so here they count as development seeds too. The report uses eight
seeds that were not run until the layout and the code were finished: the first
eight of the larger held-out set of experiments/sensor_loss.py. Seed 42, the
one the hosted demo replays, is listed separately.

Every metric is defined in the METRICS block below with its denominator.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Dict, List, Optional

from dronewatch.api.preview import SENSOR_LOSS_MODES
from dronewatch.synthetic import cameras
from dronewatch.synthetic.generator import FaultSpec, T_ZERO, generate_scenario
from dronewatch.tracks.crossfix import FIX_SOURCE
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.tracker import TrackerConfig

MODE = SENSOR_LOSS_MODES["camera_network"]
DEMO_SEED = 42
DEV_SEEDS = (42, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 2024, 31337, 99, 555)
HELD_OUT_SEEDS = tuple(range(10_000, 10_008))
COUNTS = (3, 6, 10)
RADAR = "radar-north"
FAR_M = 150.0

METRICS = f"""
contacts          true contacts in the run.
tracks            distinct track identities ever shown (confirmed), whole run.
untracked         true contacts that are never the nearest contact, within {FAR_M:.0f} m, of any
                  freshly positioned track. A contact no two cameras ever saw together.
extra             tracks - (contacts - untracked): identities beyond one per tracked contact
                  (a duplicate on a real contact, or a track restarted after a loss).
far_fresh_frames  (frame, track) pairs where a freshly positioned track (fresh == U) is more
                  than {FAR_M:.0f} m from every true contact: a track that is not on anything.
                  Denominator fresh_frames.
rmse_m            sqrt(mean |p_est - p_true|^2) over fresh (frame, track) pairs before the
                  radar has contributed to the track, p_true being the nearest true contact.
first_fix_km      range from the site centre at which the first track of the run is first
                  shown, and first_fix_s when.
radar_km          range at which the radar first contributes to any track, and radar_s when.
lead_s            radar_s - first_fix_s: how long the cameras had a position on something
                  before the radar had seen anything.
gain_s            per track the radar ever saw: seconds between the track first being shown
                  and the radar first contributing to it. Minimum and median over those tracks.
custody           per track the radar ever saw: share of frames, from first shown until the
                  radar contributes, in which the track is freshly positioned. Minimum over
                  those tracks.
merged            duplicate tracks retired by the tracker.
ghosts_refused    crossings of two known objects' directions that were not believed, and
                  vetoed: new crossings a third camera should have seen and did not.
"""


def run(name: str, count: int, seed: int) -> Dict[str, object]:
    duration = MODE["duration_s"]
    scenario = generate_scenario(name, seed=seed, duration_s=duration, count=count,
                                 faults=FaultSpec.parse(MODE["faults"]))
    timeline = build_timeline(
        scenario.observations, t_zero=T_ZERO, duration_s=duration, scans=scenario.scans,
        admit=MODE["admit"], cameras=cameras.views(),
        config=TrackerConfig(drop_after_s=MODE["retain_s"], merge_after_s=MODE["merge_after_s"]))
    entities = scenario.ground_truth.entities

    first: Dict[str, tuple] = {}
    radar: Dict[str, tuple] = {}
    fresh_before_radar: Dict[str, List[bool]] = {}
    matched = set()
    fresh_frames = far = 0
    squared: List[float] = []
    for frame in timeline["frames"]:
        t = frame["t"]
        truth = [(e.entity_id, e.state_at(t)) for e in entities]
        for track in frame["tracks"]:
            tid = track["id"]
            if FIX_SOURCE in track["src"]:
                first.setdefault(tid, (t, track["range_m"]))
            if RADAR in track["src"]:
                radar.setdefault(tid, (t, track["range_m"]))
            if tid not in radar:
                fresh_before_radar.setdefault(tid, []).append(track["fresh"] == "U")
            if track["fresh"] != "U":
                continue
            x, y = track.get("est") or (track["x"], track["y"])
            distance, entity_id = min((math.hypot(x - s.x, y - s.y), eid) for eid, s in truth)
            fresh_frames += 1
            if distance > FAR_M:
                far += 1
            else:
                matched.add(entity_id)
                if tid not in radar:
                    squared.append(distance * distance)

    ever = {t["id"] for f in timeline["frames"] for t in f["tracks"]}
    handed = [tid for tid in radar if tid in first]
    gains = sorted(radar[tid][0] - first[tid][0] for tid in handed)
    custody = [sum(fresh_before_radar[tid]) / len(fresh_before_radar[tid]) for tid in handed
               if fresh_before_radar.get(tid)]
    first_fix = min(first.values()) if first else None
    first_radar = min(radar.values()) if radar else None
    untracked = len(entities) - len(matched)
    return {
        "scenario": name, "seed": seed, "contacts": len(entities), "tracks": len(ever),
        "untracked": untracked, "extra": len(ever) - (len(entities) - untracked),
        "fresh_frames": fresh_frames, "far_fresh_frames": far,
        "rmse_m": round(math.sqrt(statistics.fmean(squared)), 1) if squared else None,
        "first_fix_s": first_fix[0] if first_fix else None,
        "first_fix_km": round(first_fix[1] / 1000.0, 2) if first_fix else None,
        "radar_s": first_radar[0] if first_radar else None,
        "radar_km": round(first_radar[1] / 1000.0, 2) if first_radar else None,
        "lead_s": round(first_radar[0] - first_fix[0], 1) if first_fix and first_radar else None,
        "gain_s_min": round(gains[0], 1) if gains else None,
        "gain_s_median": round(statistics.median(gains), 1) if gains else None,
        "handed_over": len(handed),
        "custody_min": round(min(custody), 2) if custody else None,
        "merged": timeline["tracks_merged"], "ghosts_refused": timeline["camera_fixes_ghost"],
        "vetoed": timeline["camera_fixes_vetoed"], "camera_fixes": timeline["camera_fixes"],
    }


def _row(r: Dict[str, object]) -> str:
    show = lambda v: "—" if v is None else str(v)
    return (f"| {r['contacts']} | {r['seed']} | {r['tracks']} | {r['untracked']} | {r['extra']} | "
            f"{r['far_fresh_frames']} / {r['fresh_frames']} | {show(r['rmse_m'])} | "
            f"{show(r['first_fix_km'])} at T+{show(r['first_fix_s'])} | {show(r['radar_km'])} at T+{show(r['radar_s'])} | "
            f"{show(r['lead_s'])} | {show(r['gain_s_min'])} / {show(r['gain_s_median'])} ({r['handed_over']}) | "
            f"{show(r['custody_min'])} | {r['merged']} | {r['ghosts_refused']} + {r['vetoed']} |")


HEADER = ("| contacts | seed | tracks | untracked | extra | far / fresh frames | RMSE m | first fix km | "
          "radar km | lead s | gain s min / median (tracks) | custody min | merged | ghosts refused + vetoed |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def markdown(held_out: List[Dict[str, object]], demo: List[Dict[str, object]]) -> str:
    lines = ["# Camera-network experiments", "",
             f"Mode `camera_network`: faults `{MODE['faults']}`, {len(cameras.CAMERA_NETWORK)} cameras, "
             f"run length {MODE['duration_s']:g} s, scenario `operator_demo`.",
             f"Held-out seeds: {list(HELD_OUT_SEEDS)}, not run until the layout and the code were finished. "
             f"Development seeds {list(DEV_SEEDS)} are excluded from the first table.", "",
             "## Held-out seeds", "", HEADER]
    lines += [_row(r) for r in held_out]
    lines += ["", "Per contact count, over the held-out seeds:", "",
              "| contacts | runs with one track per contact and no far frame | untracked contacts | extra tracks | "
              "far fresh frames | lead s, min to max | custody, min |",
              "|---|---|---|---|---|---|---|"]
    for count in COUNTS:
        group = [r for r in held_out if r["contacts"] == count]
        clean = sum(1 for r in group if r["tracks"] == r["contacts"] and r["untracked"] == 0 and r["far_fresh_frames"] == 0)
        leads = [r["lead_s"] for r in group if r["lead_s"] is not None]
        custody = [r["custody_min"] for r in group if r["custody_min"] is not None]
        lines.append(f"| {count} | {clean} of {len(group)} | {sum(r['untracked'] for r in group)} | "
                     f"{sum(r['extra'] for r in group)} | {sum(r['far_fresh_frames'] for r in group)} of "
                     f"{sum(r['fresh_frames'] for r in group)} | {min(leads):g} to {max(leads):g} | {min(custody):g} |")
    lines += ["", f"## Seed {DEMO_SEED}, the one the demo replays (a development seed)", "", HEADER]
    lines += [_row(r) for r in demo]
    lines += ["", "## Metric definitions", "", "```", METRICS.strip("\n"), "```", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/results")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    held_out, demo = [], []
    for count in COUNTS:
        for seed in HELD_OUT_SEEDS:
            held_out.append(run("operator_demo", count, seed))
            r = held_out[-1]
            print(f"n={count:2} seed={seed:5}: tracks {r['tracks']:2} untracked {r['untracked']} extra {r['extra']} "
                  f"far {r['far_fresh_frames']}/{r['fresh_frames']} rmse {r['rmse_m']} lead {r['lead_s']} custody {r['custody_min']}")
        demo.append(run("operator_demo", count, DEMO_SEED))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "camera_network.json").write_text(json.dumps(
        {"mode": {k: v for k, v in MODE.items()}, "held_out": held_out, "demo_seed": demo, "metrics": METRICS}, indent=1))
    (out / "camera_network.md").write_text(markdown(held_out, demo))
    print(f"wrote {out}/camera_network.json and .md in {time.perf_counter() - t0:.1f}s total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
