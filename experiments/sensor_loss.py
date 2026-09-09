"""Reproducible sensor-loss experiments.

Two layers, evaluated separately because a correct filter can still be
embedded in a tracker that associates the wrong measurements:

  Layer A  known-association linear-Gaussian simulation: NEES and NIS against
           chi-squared expectations, ellipse coverage, dropout behaviour.
  Layer B  the actual 3/6/10-contact pipeline with association, delivery
           effects, faults and recovery, scored against the ground truth the
           tracker never sees.

    python -m experiments.sensor_loss              # bounded quick run (~1 min)
    python -m experiments.sensor_loss --full       # larger Monte Carlo

Seeds: development seeds (42, 7, 1234) were used while tuning the tracker and
scenario. The report uses held-out seeds only.

Every metric is defined in the METRICS block below with its denominator.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dronewatch.synthetic.generator import FaultSpec, T_ZERO, generate_scenario
from dronewatch.tracks import kalman as K
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.tracker import Tracker

DEV_SEEDS = (42, 7, 1234)
HELD_OUT_SEEDS = (2024, 31337, 99, 555)
FULL_SEEDS = tuple(range(10_000, 10_020))
SETTLE_S = 15.0        # frames before this are excluded (tracks still confirming)

METRICS = """
pos_rmse_m        sqrt(mean |p_est - p_true|^2) over (frame, matched track) pairs in the phase.
                  Estimate = predicted state (est) even when the marker is frozen.
vel_rmse_m_s      same for velocity.
coverage95        fraction of (frame, matched track) pairs whose true position lies inside
                  the model-based 95% ellipse of the displayed covariance.
nees2_mean        mean of (p_true - p_est)^T P_pos^-1 (p_true - p_est) over the same pairs,
                  2 dof. Frames are temporally correlated: a diagnostic, not a formal test.
missing           fraction of (frame, entity) pairs with no matched confirmed track,
                  frames after SETTLE_S. Denominator: entities x frames.
fragments         confirmed tracks minus entities (extra identities created), per run.
id_switches       per entity, number of times its matched track id changes after the first
                  assignment (summed over entities).
impure_tracks     tracks whose frame-wise nearest entity is not their majority entity for
                  more than 10% of their frames (an incorrect reacquisition or swap).
recovery_s        seconds from the end of the last fault window until every entity has a
                  matched track with fresh == U (positional information < coast_after_s old).
                  None if not achieved by the end of the run.
nis_mean          mean of accepted-update NIS in the pipeline, 2-dof updates only. These are
                  gated, nearest-neighbour-selected residuals: a diagnostic of tuning drift,
                  not an unbiased sample of the innovation distribution.
cost_ms           wall-clock milliseconds for generation + tracking of the run.
""".strip()

PHASES = ("before", "during", "after")

#: name -> (faults, admit, count, phase windows)
EXPERIMENTS: Dict[str, Tuple[str, Tuple[str, ...], int, Tuple[float, float]]] = {
    "normal":                ("",                                ("radar-north",),                 6, (40.0, 55.0)),
    "radar_off_5s":          ("radar:40-45",                     ("radar-north",),                 6, (40.0, 45.0)),
    "radar_off_15s":         ("radar:40-55",                     ("radar-north",),                 6, (40.0, 55.0)),
    "radar_off_30s":         ("radar:30-60",                     ("radar-north",),                 6, (30.0, 60.0)),
    "single_contact_loss":   ("loss:2@40-55",                    ("radar-north",),                 6, (40.0, 55.0)),
    "all_positional_off":    ("all:40-55",                       ("radar-north", "eo-south"),      6, (40.0, 55.0)),
    "radar_off_backup_eo":   ("radar:40-55;backup:position",     ("radar-north", "eo-south"),      6, (40.0, 55.0)),
    "radar_off_backup_brg":  ("radar:40-55;backup:bearing",      ("radar-north", "bearing-west"),  6, (40.0, 55.0)),
    "radar_off_rf_evidence": ("radar:40-55",                     ("radar-north", "rf-east:evidence"), 6, (40.0, 55.0)),
    "sparse_radar_0p5hz":    ("sparse:0.5",                      ("radar-north",),                 6, (40.0, 55.0)),
    "radar_degraded_x4":     ("degrade:40-55x4",                 ("radar-north",),                 6, (40.0, 55.0)),
    "delayed_duplicates":    ("radar:40-55;delivery:delayed",    ("radar-north",),                 6, (40.0, 55.0)),
    "crossing_blackout":     ("radar:30-45;crossing",            ("radar-north",),                 6, (30.0, 45.0)),
    "ten_contacts_off_15s":  ("radar:40-55",                     ("radar-north",),                10, (40.0, 55.0)),
    "three_contacts_off_15s": ("radar:40-55",                    ("radar-north",),                 3, (40.0, 55.0)),
}


# --------------------------------------------------------------------------
# Layer A
# --------------------------------------------------------------------------

def layer_a(n_runs: int, seed0: int = 20_000) -> Dict[str, object]:
    """Matched-model consistency: NEES(4), NIS(2), ellipse coverage, dropout."""
    w, dt, sigma = 4.0, 0.5, 10.0
    r = [[sigma ** 2, 0.0], [0.0, sigma ** 2]]
    model = K.position_model()
    l_q = K.cholesky(K.process_noise(dt, w))
    steps = 80
    gap = range(40, 60)                                   # 10 s blackout
    nees_at, nis_at = {20: [], 39: [], 79: []}, {20: [], 39: [], 79: []}
    inside_end_of_gap, inside_normal = 0, 0
    for i in range(n_runs):
        rng = random.Random(seed0 + i)
        x_true = [0.0, 0.0, 15.0, -5.0]
        z0 = [x_true[0] + rng.gauss(0, sigma), x_true[1] + rng.gauss(0, sigma)]
        x, p = [0.0] * 4, [[100.0, 0, 0, 0], [0, 100.0, 0, 0], [0, 0, 900.0, 0], [0, 0, 0, 900.0]]
        x, p, _ = K.update(x, p, z0, r, model)
        for k in range(steps):
            noise = K.matvec(l_q, [rng.gauss(0, 1) for _ in range(4)])
            x_true = [v + noise[j] for j, v in enumerate(K.matvec(K.transition(dt), x_true))]
            x, p = K.predict(x, p, dt, w)
            if k not in gap:
                z = [x_true[0] + rng.gauss(0, sigma), x_true[1] + rng.gauss(0, sigma)]
                inn = K.innovation(x, p, z, r, model)
                x, p, _ = K.update(x, p, z, r, model, precomputed=inn)
                if k in nis_at:
                    nis_at[k].append(inn.nis)
            if k in nees_at:
                nees_at[k].append(K.nees(x_true, x, p))
            if k == 59 or k == 30:
                d = [x_true[0] - x[0], x_true[1] - x[1]]
                pos = [[p[0][0], p[0][1]], [p[1][0], p[1][1]]]
                s = K.cholesky_solve(K.cholesky(pos), d)
                hit = d[0] * s[0] + d[1] * s[1] <= K.CHI2_2DOF_95
                if k == 59:
                    inside_end_of_gap += hit
                else:
                    inside_normal += hit
    def band(dof, n):
        sd = math.sqrt(2.0 * dof / n)
        return [round(dof - 1.96 * sd, 2), round(dof + 1.96 * sd, 2)]
    return {
        "runs": n_runs,
        "nees4_mean_by_step": {str(k): round(statistics.mean(v), 3) for k, v in nees_at.items()},
        "nees4_95pct_band_for_mean": band(4, n_runs),
        "nis2_mean_by_step": {str(k): round(statistics.mean(v), 3) for k, v in nis_at.items() if v},
        "nis2_95pct_band_for_mean": band(2, n_runs),
        "coverage95_normal": round(inside_normal / n_runs, 3),
        "coverage95_end_of_10s_gap": round(inside_end_of_gap / n_runs, 3),
        "note": ("Truth generated by the filter's own model; NEES/NIS at fixed steps across "
                 "independent runs. Step 59 is the last blackout step (prediction only)."),
    }


# --------------------------------------------------------------------------
# Layer B
# --------------------------------------------------------------------------

def _truth_at(entities, t: float) -> Dict[str, Tuple[float, float, float, float]]:
    out = {}
    for e in entities:
        if t < e.spawn_time or (e.end_time is not None and t > e.end_time):
            continue
        s = e.state_at(t)
        out[e.entity_id] = (s.x, s.y, s.vx, s.vy)
    return out


def _run(name: str, seed: int) -> Dict[str, object]:
    faults_text, admit, count, window = EXPERIMENTS[name]
    faults = FaultSpec.parse(faults_text) if faults_text else None
    t0 = time.perf_counter()
    scenario = generate_scenario("operator_demo", seed=seed, duration_s=90.0, count=count, faults=faults)
    tl = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0,
                        scans=scenario.scans, admit=admit)
    cost_ms = (time.perf_counter() - t0) * 1000.0
    entities = scenario.ground_truth.entities
    frames = tl["frames"]

    # Frame-wise matching: each confirmed track to its nearest entity using the
    # predicted estimate. Evaluation only; the tracker never saw entity ids.
    per_track_votes: Dict[str, Dict[str, int]] = {}
    per_entity_track: Dict[str, List[Tuple[float, Optional[str]]]] = {e.entity_id: [] for e in entities}
    rows = []
    for f in frames:
        t = f["t"]
        truth = _truth_at(entities, t)
        taken = set()
        matched_entity_for = {}
        for tr in sorted(f["tracks"], key=lambda k: k["id"]):
            est = tr.get("est") or [tr["x"], tr["y"]]
            best, best_d = None, 1e12
            for eid, (x, y, vx, vy) in truth.items():
                d = math.hypot(est[0] - x, est[1] - y)
                if d < best_d:
                    best, best_d = eid, d
            if best is None:
                continue
            per_track_votes.setdefault(tr["id"], {}).setdefault(best, 0)
            per_track_votes[tr["id"]][best] += 1
            matched_entity_for[tr["id"]] = (best, best_d)
            if best in taken:
                continue
            taken.add(best)
            x, y, vx, vy = truth[best]
            hr = math.radians(tr["heading"])
            evx, evy = tr["speed"] * math.cos(hr), tr["speed"] * math.sin(hr)
            cov = tr["cov"]
            pos = [[float(cov[0]), float(cov[1])], [float(cov[1]), float(cov[2])]]
            d = [x - est[0], y - est[1]]
            l = K.cholesky(pos)
            nees2 = None
            if l is not None:
                s = K.cholesky_solve(l, d)
                nees2 = d[0] * s[0] + d[1] * s[1]
            rows.append({
                "t": t, "track": tr["id"], "entity": best, "fresh": tr["fresh"],
                "pos_err2": d[0] ** 2 + d[1] ** 2,
                "vel_err2": (evx - vx) ** 2 + (evy - vy) ** 2,
                "nees2": nees2, "inside": (nees2 is not None and nees2 <= K.CHI2_2DOF_95),
            })
        for eid in truth:
            mine = [tid for tid, (e, _) in matched_entity_for.items() if e == eid]
            per_entity_track[eid].append((t, sorted(mine)[0] if mine else None))

    def phase_of(t):
        a, b = window
        return "before" if t < a else "during" if t <= b else "after"

    out: Dict[str, object] = {"experiment": name, "seed": seed, "count": count,
                               "faults": faults.label() if faults else "no faults",
                               "admit": list(admit), "cost_ms": round(cost_ms, 1)}
    for ph in PHASES:
        sel = [r for r in rows if r["t"] >= SETTLE_S and phase_of(r["t"]) == ph]
        if not sel:
            out[ph] = None
            continue
        out[ph] = {
            "pairs": len(sel),
            "pos_rmse_m": round(math.sqrt(statistics.mean(r["pos_err2"] for r in sel)), 1),
            "vel_rmse_m_s": round(math.sqrt(statistics.mean(r["vel_err2"] for r in sel)), 2),
            "coverage95": round(sum(r["inside"] for r in sel) / len(sel), 3),
            "nees2_mean": round(statistics.mean(r["nees2"] for r in sel if r["nees2"] is not None), 2),
            "fresh_mix": {k: round(sum(1 for r in sel if r["fresh"] == k) / len(sel), 2) for k in "UPS"},
        }
    # Missing-track coverage.
    ent_frames = [(t, tid) for lst in per_entity_track.values() for (t, tid) in lst if t >= SETTLE_S]
    out["missing"] = round(sum(1 for _, tid in ent_frames if tid is None) / max(1, len(ent_frames)), 3)
    # Fragmentation and identity.
    out["fragments"] = tl["tracks_confirmed"] - count
    switches = 0
    for eid, lst in per_entity_track.items():
        seen = [tid for t, tid in lst if tid is not None and t >= SETTLE_S]
        switches += sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    out["id_switches"] = switches
    impure = 0
    for tid, votes in per_track_votes.items():
        total = sum(votes.values())
        if total and max(votes.values()) / total < 0.9:
            impure += 1
    out["impure_tracks"] = impure
    out["tracks_confirmed"] = tl["tracks_confirmed"]
    out["tracks_archived"] = tl["tracks_archived"]
    out["late_applied"], out["late_rejected"] = tl["late_applied"], tl["late_rejected"]
    out["duplicates_ignored"] = tl["duplicates_ignored"]
    out["ambiguous_associations"] = tl["ambiguous_associations"]
    # Recovery time.
    end = window[1]
    recovery = None
    for f in frames:
        if f["t"] <= end:
            continue
        truth = _truth_at(entities, f["t"])
        fresh_ids = {tr["id"] for tr in f["tracks"] if tr["fresh"] == "U"}
        covered = all(any(tid in fresh_ids for (tt, tid) in per_entity_track[eid] if tt == f["t"])
                      for eid in truth)
        if covered:
            recovery = round(f["t"] - end, 1)
            break
    out["recovery_s"] = recovery
    # Pipeline NIS (diagnostic only) is not in the timeline; rerun the tracker
    # cheaply on the same measurements to read its log.
    out["nis_mean_2dof"] = _pipeline_nis(scenario, admit)
    return out


def _pipeline_nis(scenario, admit) -> Optional[float]:
    from dronewatch.tracks.frames import _as_measurement
    tracker = Tracker()
    ms = [m for m in (_as_measurement(o, T_ZERO) for o in scenario.observations
                      if o.sensor_id in tuple(a.split(":")[0] for a in admit)) if m]
    ms.sort(key=lambda m: (m["received_t"], m["observation_id"]))
    tracker.process(ms, now=90.0)
    vals = [nis for (_, nis, dof, _) in tracker.nis_log if dof == 2]
    return round(statistics.mean(vals), 2) if vals else None


def aggregate(runs: List[Dict[str, object]]) -> Dict[str, object]:
    """Mean over seeds of the scalar metrics; None-aware."""
    agg: Dict[str, object] = {"experiment": runs[0]["experiment"], "count": runs[0]["count"],
                              "faults": runs[0]["faults"], "seeds": [r["seed"] for r in runs]}
    for ph in PHASES:
        vals = [r[ph] for r in runs if r[ph]]
        if not vals:
            agg[ph] = None
            continue
        agg[ph] = {k: round(statistics.mean(v[k] for v in vals), 2)
                   for k in ("pos_rmse_m", "vel_rmse_m_s", "coverage95", "nees2_mean")}
    for k in ("missing", "fragments", "id_switches", "impure_tracks", "ambiguous_associations",
              "late_applied", "late_rejected", "duplicates_ignored", "cost_ms", "tracks_archived"):
        agg[k] = round(statistics.mean(r[k] for r in runs), 2)
    rec = [r["recovery_s"] for r in runs if r["recovery_s"] is not None]
    agg["recovery_s"] = round(statistics.mean(rec), 1) if rec else None
    agg["recovery_achieved"] = f"{len(rec)}/{len(runs)}"
    nis = [r["nis_mean_2dof"] for r in runs if r["nis_mean_2dof"] is not None]
    agg["nis_mean_2dof"] = round(statistics.mean(nis), 2) if nis else None
    return agg


def markdown(layer_a_result, aggregates) -> str:
    lines = ["# Sensor-loss experiments", "",
             f"Held-out seeds: {aggregates[0]['seeds']}. Development seeds {DEV_SEEDS} excluded.", "",
             "## Layer A: matched-model filter consistency", "",
             "| statistic | value | 95% band for the mean |", "|---|---|---|"]
    la = layer_a_result
    for k, v in la["nees4_mean_by_step"].items():
        lines.append(f"| NEES(4) mean, step {k} | {v} | {la['nees4_95pct_band_for_mean']} |")
    for k, v in la["nis2_mean_by_step"].items():
        lines.append(f"| NIS(2) mean, step {k} | {v} | {la['nis2_95pct_band_for_mean']} |")
    lines += [f"| 95% ellipse coverage, normal | {la['coverage95_normal']} | nominal 0.95 |",
              f"| 95% ellipse coverage, end of 10 s gap | {la['coverage95_end_of_10s_gap']} | nominal 0.95 |",
              "", f"_{la['note']}_", "",
              "## Layer B: the multi-contact pipeline", "",
              "Position RMSE in metres, velocity RMSE in m/s, coverage of the model-based 95% ellipse, "
              "NEES(2) diagnostic. Phases are relative to the fault window.", "",
              "| experiment | n | before RMSE / cov | during RMSE / cov | after RMSE / cov | missing | frag | id sw | impure | recov s | ambig | NIS2 | ms |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in aggregates:
        def cell(ph):
            v = a[ph]
            return "—" if not v else f"{v['pos_rmse_m']} / {v['coverage95']}"
        lines.append(f"| {a['experiment']} | {a['count']} | {cell('before')} | {cell('during')} | {cell('after')} | "
                     f"{a['missing']} | {a['fragments']} | {a['id_switches']} | {a['impure_tracks']} | "
                     f"{a['recovery_s']} ({a['recovery_achieved']}) | {a['ambiguous_associations']} | "
                     f"{a['nis_mean_2dof']} | {a['cost_ms']:.0f} |")
    lines += ["", "## Metric definitions", "", "```", METRICS, "```"]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="20 held-out seeds, 2000 Layer A runs")
    ap.add_argument("--out", default="docs/results")
    ap.add_argument("--only", default=None, help="comma-separated experiment names")
    args = ap.parse_args(argv)
    seeds = FULL_SEEDS if args.full else HELD_OUT_SEEDS
    names = args.only.split(",") if args.only else list(EXPERIMENTS)
    t0 = time.perf_counter()
    la = layer_a(2000 if args.full else 400)
    print(f"Layer A done in {time.perf_counter() - t0:.1f}s: NEES {la['nees4_mean_by_step']} "
          f"band {la['nees4_95pct_band_for_mean']}; coverage {la['coverage95_normal']}/{la['coverage95_end_of_10s_gap']}")
    runs, aggregates = [], []
    for name in names:
        group = []
        for seed in seeds:
            r = _run(name, seed)
            runs.append(r)
            group.append(r)
        a = aggregate(group)
        aggregates.append(a)
        d = a["during"] or {}
        print(f"{name:24} during RMSE {d.get('pos_rmse_m', '—'):>6} cov {d.get('coverage95', '—'):>5} "
              f"missing {a['missing']:.3f} frag {a['fragments']:.1f} sw {a['id_switches']:.1f} "
              f"impure {a['impure_tracks']:.1f} recov {a['recovery_s']} ({a['recovery_achieved']})")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = "full" if args.full else "quick"
    (out / f"sensor_loss_{tag}.json").write_text(json.dumps(
        {"layer_a": la, "aggregates": aggregates, "runs": runs, "metrics": METRICS}, indent=1))
    (out / f"sensor_loss_{tag}.md").write_text(markdown(la, aggregates))
    print(f"wrote {out}/sensor_loss_{tag}.json and .md in {time.perf_counter() - t0:.1f}s total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
