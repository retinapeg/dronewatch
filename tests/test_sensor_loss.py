"""Loss, delay, duplicates and recovery at the tracker level.

Layer B: the multi-contact tracker with association and policy. These tests
say what the tracker does when information goes missing or arrives late; the
filter arithmetic itself is covered in tests/test_kalman.py.
"""
from __future__ import annotations

import copy
import math

from dronewatch.synthetic.generator import FaultSpec, T_ZERO, generate_scenario
from dronewatch.tracks import kalman as K
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.tracker import (
    Freshness, Lifecycle, SourceState, Tracker, TrackerConfig, TrackState,
)


def obs(i, t, x, y, **extra):
    return {"observation_id": f"o{i}", "t": t, "x": x, "y": y, **extra}


def straight_line(n, dt=0.5, vx=20.0, vy=0.0, start=0):
    return [obs(start + i, i * dt, vx * i * dt, vy * i * dt) for i in range(n)]


def confirmed_tracker(n=8):
    tr = Tracker()
    ms = straight_line(n)
    tr.process(ms, now=ms[-1]["t"])
    assert len(tr.visible_tracks()) == 1
    return tr, ms


# --- duplicates -----------------------------------------------------------------

def test_a_retry_does_not_shrink_covariance_or_add_a_hit():
    tr, ms = confirmed_tracker()
    track = tr.visible_tracks()[0]
    before_p = copy.deepcopy(track.covariance)
    before_hits = track.hits
    tr.process([ms[-1]], now=ms[-1]["t"] + 0.1)           # same observation_id again
    assert tr.duplicate_count == 1
    assert track.covariance == before_p
    assert track.hits == before_hits


# --- missing data ---------------------------------------------------------------

def test_no_measurement_means_prediction_only():
    """During a gap the state moves along its velocity and covariance grows.
    No pseudo-measurement is inserted: the posterior itself is untouched."""
    tr, ms = confirmed_tracker()
    track = tr.visible_tracks()[0]
    x_post, p_post, t_post = list(track.state), copy.deepcopy(track.covariance), track.state_time
    tr.advance_to(t_post + 6.0)
    assert track.state == x_post and track.covariance == p_post
    assert track.state_time == t_post
    assert track.last_measurement.t == t_post
    # Display state is the prediction, and its covariance is larger.
    assert track.display_state[0] > x_post[0]
    assert track.display_cov[0][0] > p_post[0][0]
    assert track.freshness is Freshness.PREDICTED
    # Analytic check of the displayed covariance.
    pxx, _ = K.position_variance_after_gap(p_post, 6.0, tr.config.process_noise_w)
    assert abs(track.display_cov[0][0] - pxx) < 1e-6


def test_stale_display_is_frozen_but_uncertainty_keeps_growing():
    tr, ms = confirmed_tracker()
    track = tr.visible_tracks()[0]
    t_last = track.state_time
    tr.advance_to(t_last + tr.config.stale_after_s + 1.0)
    assert track.status is TrackState.STALE
    frozen = (track.x, track.y)
    assert frozen == (track.last_measurement.x, track.last_measurement.y)
    cov_a = track.display_cov[0][0]
    tr.advance_to(t_last + tr.config.stale_after_s + 8.0)
    assert (track.x, track.y) == frozen, "the marker holds the last measured position"
    assert track.display_cov[0][0] > cov_a, "the covariance does not freeze with it"
    assert track.display_state[0] != frozen[0], "the prediction itself keeps moving"


def test_lifecycle_freshness_and_source_health_are_independent():
    tr = Tracker()
    tr.declare_source("radar", interval_s=0.5)
    ms = straight_line(8)
    for m in ms:
        tr.heartbeat("radar", m["t"])
    tr.process(ms, now=ms[-1]["t"])
    track = tr.visible_tracks()[0]
    assert track.lifecycle is Lifecycle.CONFIRMED
    assert tr.sources["radar"].state is SourceState.REPORTING
    # Heartbeats stop and no detections: source unavailable, estimate stale,
    # track still confirmed and retained.
    tr.advance_to(ms[-1]["t"] + 10.0)
    assert track.lifecycle is Lifecycle.CONFIRMED
    assert track.freshness is Freshness.STALE
    assert tr.sources["radar"].state is SourceState.UNAVAILABLE


def test_source_health_comes_from_heartbeats_not_from_detections():
    tr = Tracker()
    tr.declare_source("radar", interval_s=0.5)
    ms = straight_line(8)
    tr.process(ms, now=ms[-1]["t"])
    # No heartbeat was ever declared: health is unknown, not inferred.
    assert tr.sources["radar"].state is SourceState.UNKNOWN
    # Heartbeats continue while detections stop: the sensor is fine, the
    # contact is merely unobserved.
    t = ms[-1]["t"]
    for k in range(1, 13):
        tr.heartbeat("radar", t + 0.5 * k)
    tr.advance_to(t + 6.0)
    assert tr.sources["radar"].state is SourceState.REPORTING
    assert tr.visible_tracks()[0].freshness is Freshness.PREDICTED


def test_degraded_source_is_reported_from_its_own_declaration():
    tr = Tracker()
    tr.declare_source("radar", interval_s=0.5, nominal_sigma_m=10.0)
    tr.heartbeat("radar", 1.0, reported_sigma_m=40.0)
    tr.advance_to(1.2)
    assert tr.sources["radar"].state is SourceState.DEGRADED


# --- late data --------------------------------------------------------------------

def test_late_report_inside_the_window_gives_the_in_order_posterior():
    ms = straight_line(10)
    in_order = Tracker()
    in_order.process(ms, now=ms[-1]["t"])
    late = Tracker()
    shuffled = ms[:6] + [ms[7], ms[6]] + ms[8:]          # ms[6] arrives one report late
    late.process(shuffled, now=ms[-1]["t"])
    assert late.late_applied_count == 1
    a, b = in_order.visible_tracks()[0], late.visible_tracks()[0]
    assert all(abs(a.state[i] - b.state[i]) < 1e-9 for i in range(4))
    assert all(abs(a.covariance[i][j] - b.covariance[i][j]) < 1e-9 for i in range(4) for j in range(4))
    assert a.hits == b.hits


def test_late_report_outside_the_window_is_rejected_not_applied():
    tr, ms = confirmed_tracker(n=10)
    track = tr.visible_tracks()[0]
    before = list(track.state)
    ancient = obs(99, ms[-1]["t"] - tr.config.reorder_window_s - 1.0, -50.0, 0.0)
    tr.process([ancient], now=ms[-1]["t"] + 0.1)
    assert tr.late_rejected_count == 1
    assert track.state == before
    assert len(tr.tracks) == 1, "a rejected late report must not spawn a phantom"


def test_duplicate_of_a_late_report_is_still_applied_once():
    ms = straight_line(10)
    tr = Tracker()
    tr.process(ms[:6] + [ms[7], ms[6], ms[6]] + ms[8:], now=ms[-1]["t"])
    assert tr.late_applied_count == 1 and tr.duplicate_count == 1


def test_changing_future_reports_cannot_change_earlier_frames():
    """Causality of the precomputed replay."""
    scenario = generate_scenario("operator_demo", seed=42, duration_s=60.0, count=3)
    base = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=60.0, scans=scenario.scans)
    cut = [o for o in scenario.observations if (o.received_at - T_ZERO).total_seconds() <= 30.0]
    cut_tl = build_timeline(cut, t_zero=T_ZERO, duration_s=60.0, scans=scenario.scans)
    for fa, fb in zip(base["frames"], cut_tl["frames"]):
        if fa["t"] > 30.0:
            break
        assert fa["tracks"] == fb["tracks"]


# --- measurements ------------------------------------------------------------------

def test_zero_coordinates_are_a_real_measurement():
    tr = Tracker()
    ms = [obs(0, 0.0, 10.0, 0.0), obs(1, 0.5, 5.0, 0.0), obs(2, 1.0, 0.0, 0.0)]
    tr.process(ms, now=1.0)
    track = tr.visible_tracks()[0]
    assert track.hits == 3 and abs(track.x) < 5.0


def test_invalid_measurement_covariance_is_rejected_and_counted():
    tr, ms = confirmed_tracker()
    bad = obs(50, ms[-1]["t"] + 0.5, 90.0, 0.0, r=[[-1.0, 0.0], [0.0, 1.0]])
    nan = obs(51, ms[-1]["t"] + 1.0, float("nan"), 0.0)
    tr.process([bad, nan], now=ms[-1]["t"] + 1.0)
    assert tr.rejected_invalid_count == 2
    assert tr.visible_tracks()[0].hits == len(ms)


def test_outlier_outside_the_gate_starts_a_candidate_not_an_update():
    tr, ms = confirmed_tracker()
    track = tr.visible_tracks()[0]
    before = list(track.state)
    far = obs(60, ms[-1]["t"] + 0.5, track.state[0] + 400.0, 400.0)
    tr.process([far], now=ms[-1]["t"] + 0.5)
    assert track.state == before
    assert len(tr.tracks) == 2 and len(tr.visible_tracks()) == 1


def test_bearing_cannot_start_a_track_but_can_update_one():
    tr, ms = confirmed_tracker()
    track = tr.visible_tracks()[0]
    t = ms[-1]["t"] + 0.5
    x_pred, _ = track.predicted_at(t, tr.config.process_noise_w)
    sensor = (x_pred[0], x_pred[1] - 1000.0)                    # due south of the contact
    bearing = math.atan2(x_pred[1] - sensor[1], x_pred[0] - sensor[0])
    _, p_pred = track.predicted_at(t, tr.config.process_noise_w)
    tr.process([{"observation_id": "b1", "t": t, "kind": "bearing", "bearing": bearing,
                 "sensor_xy": sensor, "source_id": "bearing"}], now=t)
    assert len(tr.tracks) == 1
    assert "bearing" in track.sources
    # Against the prediction at the same time: cross-range (x here) tightened,
    # range (y) did not; positional freshness untouched.
    assert track.covariance[0][0] < p_pred[0][0]
    assert abs(track.covariance[1][1] - p_pred[1][1]) < 1e-6
    assert track.last_measurement.t == ms[-1]["t"]
    lone = Tracker()
    lone.process([{"observation_id": "b2", "t": 0.0, "kind": "bearing", "bearing": 0.3,
                   "sensor_xy": (0.0, 0.0)}], now=0.0)
    assert not lone.tracks and lone.unassigned_nonpositional_count == 1


# --- association -------------------------------------------------------------------

def test_covariance_volume_penalises_a_vague_track():
    """Two tracks gate the same report with equal normalised distance; the
    tighter one should win, because the likelihood includes |S|."""
    tr = Tracker(TrackerConfig(process_noise_w=4.0))
    tight = straight_line(8, vx=0.0, start=0)                  # hovering at origin
    tr.process(tight, now=tight[-1]["t"])
    t0 = tight[-1]["t"]
    # A second track spawned far away, then made vague by hand: same mean as
    # the tight one, forty times the position variance.
    tr.process([obs(100, t0 + 0.1, 600.0, 0.0)], now=t0 + 0.1)
    vague = [tk for tk in tr.tracks.values() if tk.hits == 1][0]
    vague.lifecycle = Lifecycle.CONFIRMED
    vague.covariance = [[4000.0, 0, 0, 0], [0, 4000.0, 0, 0], [0, 0, 900.0, 0], [0, 0, 0, 900.0]]
    vague.state = [0.0, 0.0, 0.0, 0.0]
    vague.state_time = t0 + 0.1
    tight_track = [tk for tk in tr.tracks.values() if tk is not vague][0]
    tr.process([obs(101, t0 + 0.5, 12.0, 0.0)], now=t0 + 0.5)
    assert tight_track.hits == len(tight) + 1
    assert vague.hits == 1


def test_ambiguity_is_recorded_when_two_tracks_compete():
    tr = Tracker()
    # 80 m apart: separable by a 10 m radar (initial NIS 32 > 25), yet a report
    # midway (40 m from each) gates into both.
    a = [obs(i, i * 0.5, 0.0, 0.0) for i in range(6)]
    b = [obs(100 + i, i * 0.5, 80.0, 0.0) for i in range(6)]
    tr.process(sorted(a + b, key=lambda m: (m["t"], m["observation_id"])), now=2.5)
    assert len(tr.visible_tracks()) == 2
    tr.process([obs(200, 3.0, 40.0, 0.0)], now=3.0)            # exactly between them
    assert tr.ambiguous_association_count >= 1


# --- the six-contact pipeline under faults ----------------------------------------------

def run_mode(faults, admit=("radar-north",), count=6, seed=42):
    scenario = generate_scenario("operator_demo", seed=seed, duration_s=90.0, count=count,
                                 faults=FaultSpec.parse(faults) if faults else None)
    return build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0,
                          scans=scenario.scans, admit=admit)


def ids_at(tl, t):
    return sorted(tr["id"] for tr in tl["frames"][int(t * 5)]["tracks"])


def test_radar_blackout_preserves_identity_and_shows_growth_then_recovery():
    tl = run_mode("radar:40-55")
    assert tl["tracks_confirmed"] == 6 and tl["tracks_spawned"] == 6
    before, during, after = ids_at(tl, 38), ids_at(tl, 52), ids_at(tl, 60)
    assert before == during == after
    f38, f45, f52, f56 = (tl["frames"][int(t * 5)]["tracks"] for t in (38, 45, 52, 56))
    assert {t["fresh"] for t in f38} == {"U"} and {t["fresh"] for t in f45} == {"P"}
    assert {t["fresh"] for t in f52} == {"S"} and {t["fresh"] for t in f56} == {"U"}
    assert tl["frames"][int(45 * 5)]["sources"]["radar-north"] == "UNAVAILABLE"
    assert tl["frames"][int(56 * 5)]["sources"]["radar-north"] == "REPORTING"
    major = lambda frame: sum(t["ell"][0] for t in frame) / len(frame)
    assert major(f38) < major(f45) < major(f52) and major(f56) < major(f45)
    assert {t["basis"] for t in f52} == {"s"} and {t["basis"] for t in f45} == {"p"}


def test_long_blackout_archives_and_reacquires_as_new_identities():
    """Beyond retention the honest outcome is a new track, not a 'recovery'."""
    tl = run_mode("radar:30-62")
    assert tl["tracks_archived"] == 6
    assert tl["tracks_confirmed"] == 12
    assert set(ids_at(tl, 25)).isdisjoint(ids_at(tl, 70))


def test_single_contact_loss_is_not_a_source_outage():
    tl = run_mode("loss:2@40-55")
    f48 = tl["frames"][int(48 * 5)]
    assert f48["sources"]["radar-north"] == "REPORTING"
    fresh = sorted(t["fresh"] for t in f48["tracks"])
    assert fresh.count("U") == 5 and (fresh.count("P") + fresh.count("S")) == 1


def test_position_backup_keeps_estimates_fresh_through_radar_loss():
    tl = run_mode("radar:40-55;backup:position", admit=("radar-north", "eo-south"))
    f50 = tl["frames"][int(50 * 5)]
    assert f50["sources"] == {"radar-north": "UNAVAILABLE", "eo-south": "REPORTING"}
    assert all(t["fresh"] != "S" for t in f50["tracks"])
    assert all("eo-south" in t["src"] for t in f50["tracks"])
    assert tl["tracks_confirmed"] == 6


def test_bearing_backup_constrains_cross_range_only():
    plain = run_mode("radar:40-55")
    bearing = run_mode("radar:40-55;backup:bearing", admit=("radar-north", "bearing-west"))
    fp, fb = plain["frames"][int(52 * 5)]["tracks"], bearing["frames"][int(52 * 5)]["tracks"]
    minor_plain = sum(t["ell"][1] for t in fp) / len(fp)
    minor_bearing = sum(t["ell"][1] for t in fb) / len(fb)
    major_bearing = sum(t["ell"][0] for t in fb) / len(fb)
    # A 2 degree bearing at ~1.8 km is a ~63 m cross-range constraint against
    # ~65 m of blackout growth: roughly a 20% reduction of that axis, no more.
    assert minor_bearing < 0.9 * minor_plain, "the axis across the line of sight tightens"
    assert major_bearing > 0.9 * minor_plain, "range stays unobservable"
    assert all(t["fresh"] == "S" for t in fb), "a bearing does not refresh positional information"


# --- stochastic containment for a lost contact -------------------------------------

def test_monte_carlo_agrees_with_the_closed_form():
    """The SDE is linear-Gaussian, so the sampled ensemble must reproduce the
    analytic containment radius. This is the check that the simulation is
    right, not merely plausible."""
    from dronewatch.tracks import uncertainty as U
    for tau in (5.0, 20.0, 40.0):
        v = U.validate(w=4.0, tau=tau, n_paths=3000, seed=3)
        assert 0.96 <= v["ratio"] <= 1.04, v
        assert 0.93 <= v["empirical_containment"] <= 0.97, v


def test_containment_radius_is_the_major_axis():
    from dronewatch.tracks import uncertainty as U
    r = U.containment_radius([[400.0, 0.0], [0.0, 100.0]], 0.95)
    assert abs(r - math.sqrt(5.9914645471 * 400.0)) < 1e-6, "must use the larger axis"


def test_containment_grows_monotonically_after_loss():
    from dronewatch.tracks import uncertainty as U
    x0 = [0.0, 0.0, 20.0, 0.0]
    p0 = [[100.0, 0, 0, 0], [0, 100.0, 0, 0], [0, 0, 64.0, 0], [0, 0, 0, 64.0]]
    last = -1.0
    for tau in (0, 1, 2, 5, 10, 20, 40):
        _, cov = U.analytic_state(x0, p0, tau, 4.0)
        r = U.containment_radius([[cov[0][0], cov[0][1]], [cov[1][0], cov[1][1]]])
        assert r > last
        last = r


def test_cue_feasibility_fails_closed_as_uncertainty_grows():
    """A track that is cueable at loss must become un-cueable, and the reason
    must say so. The negative result is the point of the assessment."""
    from dronewatch.tracks import uncertainty as U
    x0 = [0.0, 0.0, 22.0, -8.0]
    p0 = [[100, 0, 20, 0], [0, 100, 0, 20], [20, 0, 64, 0], [0, 20, 0, 64]]
    _, c0 = U.analytic_state(x0, p0, 0.0, 4.0)
    a0 = U.cue_feasibility(c0, 1200.0, 0.0, growth_probe=(x0, p0, 4.0))
    assert a0.feasible and a0.seconds_until_infeasible is not None
    _, c5 = U.analytic_state(x0, p0, 5.0, 4.0)
    a5 = U.cue_feasibility(c5, 1200.0, 5.0)
    assert not a5.feasible and "exceeds" in a5.reason  # the Python object keeps the sentence
    assert a5.excess > 1.0


def test_speed_bound_rejects_implausible_paths_and_reports_it():
    from dronewatch.tracks import uncertainty as U
    x0 = [0.0, 0.0, 40.0, 0.0]
    p0 = [[25.0, 0, 0, 0], [0, 25.0, 0, 0], [0, 0, 100.0, 0], [0, 0, 0, 100.0]]
    ens = U.sample_paths(x0, p0, 20.0, 4.0, n_paths=200, steps=16, seed=5, max_speed_m_s=45.0)
    assert ens.rejected > 0, "starting at 40 m/s with a 45 m/s bound, some draws must be refused"
    assert ens.n_paths == 200
    assert all(len(p) == 17 for p in ens.paths)


def test_projection_carries_velocity_containment_and_cue():
    tl = run_mode("radar:40-55")
    f = tl["frames"][int(50 * 5)]
    for tr in f["tracks"]:
        assert "vel" in tr and len(tr["vel"]) == 2
        assert tr["r95"] > 0
        assert tr["cue"] in ("ok", "range", "unc")
        assert tr["fresh"] == "S" and tr["cue"] == "unc", \
            "a stale track inside effective range fails on UNCERTAINTY, and must say so"
    before = tl["frames"][int(38 * 5)]["tracks"]
    assert all(t["r95"] < f["tracks"][0]["r95"] for t in before), "containment grows through the blackout"


# --- behaviour-adaptive containment ---------------------------------------------------

def _turning_history(turn_deg_s, speed=25.0, n=13, dt=0.5):
    import math as _m
    h = _m.radians(270.0); x = y = 0.0; out = []
    for i in range(n):
        out.append((i * dt, x, y))
        h += _m.radians(turn_deg_s) * dt
        x += speed * _m.cos(h) * dt; y += speed * _m.sin(h) * dt
    return out


def test_behaviour_estimator_recovers_a_known_turn_rate():
    from dronewatch.tracks import uncertainty as U
    b = U.behaviour_from_history(_turning_history(3.0))
    assert abs(math.degrees(b.turn_rate_rad_s) - 3.0) < 0.15
    assert abs(b.speed_m_s - 25.0) < 0.5
    assert b.fit_quality == "good"
    s = U.behaviour_from_history(_turning_history(0.0))
    assert abs(math.degrees(s.turn_rate_rad_s)) < 0.05


def test_behaviour_estimator_unwraps_heading_through_pi():
    """A turn that crosses the ±180° seam must not read as a reversal."""
    from dronewatch.tracks import uncertainty as U
    import math as _m
    h = _m.radians(175.0); x = y = 0.0; hist = []
    for i in range(13):
        hist.append((i * 0.5, x, y)); h += _m.radians(4.0) * 0.5
        x += 25 * _m.cos(h) * 0.5; y += 25 * _m.sin(h) * 0.5
    b = U.behaviour_from_history(hist)
    assert abs(_m.degrees(b.turn_rate_rad_s) - 4.0) < 0.3


def test_regimes_follow_behaviour():
    from dronewatch.tracks import uncertainty as U
    turning = U.regimes_for(U.behaviour_from_history(_turning_history(3.0)))
    straight = U.regimes_for(U.behaviour_from_history(_turning_history(0.0)))
    assert turning[0].name == "continue-turn" and turning[0].weight > 0.5
    assert straight[0].name == "straight" and straight[0].weight > 0.5
    assert abs(sum(r.weight for r in turning) - 1.0) < 1e-9
    assert abs(sum(r.weight for r in straight) - 1.0) < 1e-9


def test_adaptive_region_is_shaped_by_prior_movement():
    """A turning contact's region must be displaced toward the inside of its
    turn relative to a straight contact's, and both must be non-circular."""
    from dronewatch.tracks import uncertainty as U
    p0 = [[100, 0, 0, 0], [0, 100, 0, 0], [0, 0, 25, 0], [0, 0, 0, 25]]
    left = _turning_history(+4.0); right = _turning_history(-4.0)
    tl, tr_ = left[-1], right[-1]
    el = U.sample_paths_adaptive([tl[1], tl[2], 0, -25], p0, 25.0, left, n_paths=300, seed=2)
    er = U.sample_paths_adaptive([tr_[1], tr_[2], 0, -25], p0, 25.0, right, n_paths=300, seed=2)
    cxl = sum(p[0] for p in el.hull95) / len(el.hull95)
    cxr = sum(p[0] for p in er.hull95) / len(er.hull95)
    # Heading south, a left (anticlockwise) turn curls toward +x, right toward -x.
    assert cxl > tl[1] + 50 and cxr < tr_[1] - 50, (cxl, cxr)
    assert len(el.hull95) >= 5 and len(er.hull95) >= 5


def test_adaptive_ensemble_respects_airspeed_bound():
    from dronewatch.tracks import uncertainty as U
    hist = _turning_history(0.0, speed=40.0)
    e = U.sample_paths_adaptive([0, 0, 0, -40], [[25, 0, 0, 0], [0, 25, 0, 0], [0, 0, 9, 0], [0, 0, 0, 9]],
                                20.0, hist, n_paths=200, seed=4, max_speed_m_s=45.0)
    assert e.n_paths == 200 and e.rejected > 0


def test_cued_camera_only_sees_its_sector():
    from dronewatch.synthetic.sensors import SensorModel
    from dronewatch.domain.enums import Modality
    cam = SensorModel(sensor_id="cam", modality=Modality.EO, location=(0.0, 560.0),
                      fov_centre_deg=90.0, fov_half_deg=32.0, max_range_m=1500.0)
    assert cam.can_see(0.0, 1500.0)            # straight ahead, in range
    assert not cam.can_see(0.0, 2200.0)        # too far
    assert not cam.can_see(1500.0, 560.0)      # 90 deg off axis
    assert not cam.can_see(0.0, 0.0)           # behind the camera


def test_viso_camera_relocalises_only_what_it_can_see():
    """Radar off for 30 s; the camera keeps SOME contacts fresh and cueable
    while others go stale. That difference is the point."""
    from dronewatch.tracks.tracker import TrackerConfig
    scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6,
                                 faults=FaultSpec.parse("radar:40-70;backup:viso"))
    assert any(o.sensor_id == "viso-eo" for o in scenario.observations)
    tl = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0,
                        scans=scenario.scans, admit=("radar-north", "viso-eo"),
                        config=TrackerConfig(drop_after_s=45.0))
    f = tl["frames"][int(52 * 5)]
    fresh = [t["fresh"] for t in f["tracks"]]
    assert "U" in fresh and "S" in fresh, fresh
    assert f["sources"]["radar-north"] == "UNAVAILABLE"
    assert f["sources"]["viso-eo"] == "REPORTING"
    seen = [t for t in f["tracks"] if "viso-eo" in t["src"]]
    assert seen, "the camera must have contributed to at least one track"
    assert tl["tracks_archived"] == 0, "a 45 s retention must carry tracks across a 30 s outage"


def test_thirty_second_outage_without_backup_stays_lost_until_radar_returns():
    from dronewatch.tracks.tracker import TrackerConfig
    scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6,
                                 faults=FaultSpec.parse("radar:40-70"))
    tl = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0,
                        scans=scenario.scans, config=TrackerConfig(drop_after_s=45.0))
    r95 = lambda t: sorted(x["r95"] for x in tl["frames"][int(t * 5)]["tracks"])
    assert all(x["fresh"] == "S" for x in tl["frames"][int(68 * 5)]["tracks"])
    assert r95(68)[0] > r95(52)[0] > r95(45)[0] > r95(38)[-1]
    assert all(x["fresh"] == "U" for x in tl["frames"][int(74 * 5)]["tracks"])
    assert tl["tracks_confirmed"] == 6 and tl["tracks_archived"] == 0
