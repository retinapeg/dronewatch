"""Fixed cameras as a drone sensor, and tracks made from their bearings.

Three things are checked here. The optics: how far a camera can see is
arithmetic on pixels, and the layout must not claim more than that arithmetic
allows. The geometry: one camera gives a direction, two give a position, and
with several objects in view the wrong pairs of directions cross too. And the
whole run against ground truth: every track the cameras start must be a real
contact, and it must be there before the radar could have seen it.

Ground truth is used in this file to score the result. It never reaches the
tracker; the tracker is handed observations only, as everywhere else.
"""
from __future__ import annotations

import importlib
import math

import pytest
from fastapi.testclient import TestClient

from dronewatch.synthetic import cameras as C
from dronewatch.synthetic.generator import FaultSpec, T_ZERO, _tuned_sensors, generate_scenario
from dronewatch.synthetic.scenarios import generate_incoming_group, hold_altitude
from dronewatch.tracks import crossfix as X
from dronewatch.tracks import kalman as K
from dronewatch.tracks.frames import build_timeline
from dronewatch.tracks.tracker import Freshness, Tracker, TrackerConfig

MODE_FAULTS = "cameras:on;reach:1400;runin:72;hold:15"
DURATION_S = 162.0


# --- optics ---------------------------------------------------------------------

def test_reach_is_the_range_at_which_the_drone_still_covers_eight_pixels():
    for lens, expected in ((40.0, 825.0), (20.0, 1650.0), (16.0, 2063.0), (12.0, 2750.0)):
        reach = C.reach_m(lens, 3840)
        assert reach == pytest.approx(expected, abs=1.0)
        assert C.pixels_on_target(C.TARGET_SIZE_M, reach, lens, 3840) == pytest.approx(C.MIN_PIXELS)


def test_whatever_the_lens_the_strip_a_camera_covers_at_its_reach_is_the_same_width():
    """A longer lens sees further over a narrower angle; the two cancel exactly."""
    for lens in (8.0, 12.0, 20.0, 40.0, 90.0):
        assert C.reach_m(lens, 3840) * math.radians(lens) == pytest.approx(3840 * C.TARGET_SIZE_M / C.MIN_PIXELS)


def test_a_small_camera_drone_is_seen_at_under_a_third_of_the_distance():
    assert C.reach_m(40.0, 3840, size_m=0.35) == pytest.approx(C.reach_m(40.0, 3840) * 0.35 / 1.2)
    assert C.reach_m(40.0, 3840, size_m=0.35) < 250.0


def test_a_drone_that_passes_close_and_high_is_above_the_picture():
    camera = C.FixedCamera("c", "PLACE", 0.0, 0.0, 90.0, 12.0, height_m=6.0)
    assert camera.vfov_deg == pytest.approx(6.75)
    assert camera.near_m(95.0) == pytest.approx(89.0 / math.tan(math.radians(6.75)))
    wide = C.FixedCamera("w", "PLACE", 0.0, 0.0, 90.0, 40.0, height_m=6.0)
    assert wide.near_m(95.0) < camera.near_m(95.0), "a wide lens has a taller picture"


# --- the network ----------------------------------------------------------------

def test_the_network_is_thirty_two_cameras_at_fourteen_places_each_named_once():
    assert len(C.CAMERA_NETWORK) == 32
    assert len(set(C.CAMERA_IDS)) == 32
    assert len({camera.place for camera in C.CAMERA_NETWORK}) == 14
    assert set(C.views()) == set(C.CAMERA_IDS)


def test_an_ordinary_wide_lens_on_the_fence_sees_no_further_than_the_radar():
    """The honest baseline: a common security lens gives no early warning."""
    wide = [camera for camera in C.CAMERA_NETWORK if camera.hfov_deg >= 40.0]
    assert len(wide) == 4
    for camera in wide:
        furthest_from_centre = math.hypot(camera.x, camera.y) + camera.reach_m
        assert furthest_from_centre <= C.SHORT_RANGE_RADAR_REACH_M * 1.02


def _viewpoints_on(x, y, z, sensors):
    return {sensor.location for sensor in sensors if sensor.can_see(x, y, 0.0, z)}


def test_the_northern_approach_is_seen_from_two_places_all_the_way_to_the_radar():
    """Custody: from 3 km out down to inside the radar's reach there is no gap
    on the approach axis where fewer than two places see a drone at 95 m."""
    sensors = [s for s in _tuned_sensors("operator_demo", DURATION_S, FaultSpec.parse(MODE_FAULTS))
               if s.sensor_id in C.CAMERA_IDS]
    for y in range(1300, 3050, 50):
        assert len(_viewpoints_on(0.0, float(y), C.NOMINAL_ALTITUDE_M, sensors)) >= 2, y


def test_a_camera_sees_nothing_beyond_its_reach_outside_its_view_or_above_its_picture():
    sensors = {s.sensor_id: s for s in _tuned_sensors("operator_demo", DURATION_S, FaultSpec.parse(MODE_FAULTS))}
    gate = sensors["cam-gate-n"]                     # at (0, 1500), looking north through a 12 degree lens
    assert gate.can_see(0.0, 3500.0, 0.0, 95.0)
    assert not gate.can_see(0.0, 4400.0, 0.0, 95.0), "2.9 km away: fewer than 8 pixels"
    assert not gate.can_see(900.0, 3500.0, 0.0, 95.0), "24 degrees off the axis of a 12 degree lens"
    assert not gate.can_see(0.0, 1900.0, 0.0, 95.0), "400 m away and 89 m up: above the top of the picture"
    assert not gate.can_see(0.0, 3500.0, 0.0, 2.0), "below the camera: under the bottom of the picture"


# --- what the simulation generates -----------------------------------------------

def test_the_mode_is_spelt_out_in_the_fault_specification():
    faults = FaultSpec.parse(MODE_FAULTS)
    assert faults.camera_network and faults.radar_reach_m == 1400.0
    assert faults.run_in_s == 72.0 and faults.altitude_band_m == 15.0
    assert faults.label() == ("fixed cameras on, radar reach 1.4 km, group starts 72 s further out, "
                              "height held within 15 m")
    assert FaultSpec.parse("").camera_network is False and FaultSpec.parse("").radar_reach_m is None


def test_a_camera_reports_a_direction_an_elevation_and_a_rough_range_and_no_position():
    scenario = generate_scenario("operator_demo", seed=42, duration_s=DURATION_S, count=3,
                                 faults=FaultSpec.parse(MODE_FAULTS))
    reports = [o for o in scenario.observations if o.sensor_id in C.CAMERA_IDS]
    assert len(reports) > 500
    for report in reports[:200]:
        assert report.position is None
        raw = report.raw
        assert raw["kind"] == "bearing"
        assert raw["sigma_rad"] == pytest.approx(math.radians(C.BEARING_SIGMA_DEG), abs=1e-6)
        assert 0.0 <= raw["elevation_rad"] < math.radians(12.0)
        assert raw["range_m"] <= raw["reach_m"] * 4.0 and raw["range_log_sigma"] == C.RANGE_LOG_SIGMA


def test_the_short_range_radar_sees_nothing_beyond_its_reach():
    scenario = generate_scenario("operator_demo", seed=42, duration_s=DURATION_S, count=6,
                                 faults=FaultSpec.parse(MODE_FAULTS))
    radar = [o for o in scenario.observations if o.sensor_id == "radar-north"]
    assert radar, "the group does come inside the radar's reach"
    # The limit applies to where the object is; the report carries 10 m of noise on top.
    assert max(math.hypot(o.position.latitude, o.position.longitude) for o in radar) < 1400.0 + 60.0
    first = min((o.observed_at - T_ZERO).total_seconds() for o in radar)
    assert first > 90.0, "nothing is inside 1.4 km for the first minute and a half"


def test_the_group_starts_further_out_along_the_same_approach():
    near = generate_incoming_group(6, seed=42, duration=90.0, dt=0.1)
    far = generate_incoming_group(6, seed=42, duration=DURATION_S, dt=0.1, run_in_s=72.0)
    for a, b in zip(near, far):
        start_near, start_far = a.trajectory[0], b.trajectory[0]
        moved = math.hypot(start_far.x - start_near.x, start_far.y - start_near.y)
        assert moved == pytest.approx(72.0 * 25.0, rel=0.02), "72 s at 25 m/s further back"
        assert math.hypot(start_far.x, start_far.y) > math.hypot(start_near.x, start_near.y) + 1500.0


def test_holding_height_bounds_the_wander_and_leaves_the_path_alone():
    free = generate_incoming_group(10, seed=42, duration=DURATION_S, dt=0.1, run_in_s=72.0)
    held = generate_incoming_group(10, seed=42, duration=DURATION_S, dt=0.1, run_in_s=72.0, altitude_band_m=15.0)
    assert min(p.z for e in free for p in e.trajectory) < 0.0, "without it a contact ends up below the ground"
    for a, b in zip(free, held):
        z0 = a.trajectory[0].z
        assert [(p.t, p.x, p.y) for p in a.trajectory] == [(p.t, p.x, p.y) for p in b.trajectory]
        assert all(abs(p.z - z0) <= 15.0 for p in b.trajectory)
    assert hold_altitude(free[0], 15.0).trajectory == held[0].trajectory


def test_the_signal_loss_gap_falls_while_the_group_is_in_front_of_the_radar():
    scenario = generate_scenario("operator_demo_signal_loss", seed=42, duration_s=DURATION_S, count=6,
                                 faults=FaultSpec.parse(MODE_FAULTS))
    times = sorted((o.observed_at - T_ZERO).total_seconds() for o in scenario.observations
                   if o.sensor_id == "radar-north")
    assert any(100.0 <= t < 112.0 for t in times), "the radar has contacts before the gap"
    assert not any(112.5 <= t <= 123.5 for t in times), "and none during it"
    assert any(t > 124.0 for t in times)


# --- crossing two bearings --------------------------------------------------------

def sighting(camera_id, camera, target, t=0.0, *, height=6.0, reach=3500.0, tag=""):
    """What a camera at `camera` reports of an object at `target`, without noise."""
    (cx, cy), (x, y, z) = camera, target
    distance = math.hypot(x - cx, y - cy)
    return {"observation_id": f"{camera_id}@{t}{tag}", "t": t, "received_t": t + 0.3, "source_id": camera_id,
            "kind": "bearing", "bearing": math.atan2(y - cy, x - cx), "sensor_xy": (cx, cy),
            "sigma_rad": math.radians(0.1), "elevation": math.atan2(z - height, distance),
            "sigma_el": math.radians(0.1), "sensor_z": height, "range_m": distance,
            "range_log_sigma": 0.35, "reach_m": reach}


WEST, EAST, NORTH = (-425.0, 425.0), (425.0, 425.0), (0.0, 1500.0)


def test_two_bearings_cross_at_the_object_and_parallel_ones_do_not_cross():
    target = (150.0, 2400.0, 95.0)
    a = X.Sighting.from_measurement(sighting("cam-a", WEST, target))
    b = X.Sighting.from_measurement(sighting("cam-b", EAST, target))
    x, y, along_a, along_b = X.cross(a, b)
    assert (x, y) == pytest.approx((150.0, 2400.0), abs=1e-6)
    assert along_a == pytest.approx(math.hypot(575.0, 1975.0)) and along_b == pytest.approx(math.hypot(275.0, 1975.0))
    far = X.Sighting.from_measurement(sighting("cam-b", EAST, (850.0 + 150.0, 2400.0, 95.0)))
    assert X.cross(a, far) is None, "the same direction from two places never crosses"


def test_a_fix_is_long_along_the_view_and_short_across_it():
    """Two corners 850 m apart looking 2 km north cross at about 24 degrees: the
    position is known to a few metres across the view and tens along it."""
    target = (0.0, 2400.0, 95.0)
    fix = X.fit([X.Sighting.from_measurement(sighting("cam-a", WEST, target)),
                 X.Sighting.from_measurement(sighting("cam-b", EAST, target))])
    assert (fix.x, fix.y) == pytest.approx((0.0, 2400.0), abs=1e-3)
    assert fix.z == pytest.approx(95.0, abs=0.01)
    sigma_east, sigma_north = math.sqrt(fix.covariance[0][0]), math.sqrt(fix.covariance[1][1])
    assert 2.0 < sigma_east < 5.0
    assert 10.0 < sigma_north < 20.0
    assert sigma_north > 3.0 * sigma_east


def test_two_lenses_on_one_pole_cannot_fix_a_position_between_them():
    target = (150.0, 2400.0, 95.0)
    a = X.Sighting.from_measurement(sighting("cam-a1", WEST, target))
    b = X.Sighting.from_measurement(sighting("cam-a2", WEST, target))
    assert X.pair_cost(a, b) is None


def test_a_crossing_beyond_what_either_camera_can_see_is_not_a_pair():
    target = (0.0, 2400.0, 95.0)
    a = X.Sighting.from_measurement(sighting("cam-a", WEST, target, reach=1500.0))
    b = X.Sighting.from_measurement(sighting("cam-b", EAST, target))
    assert X.pair_cost(a, b) is None


def test_with_two_objects_in_view_height_tells_the_true_pairs_from_the_ghosts():
    """Two cameras and two objects give four crossings. Only at the two true
    ones do both cameras agree about how high the object is."""
    one, two = (-250.0, 2300.0, 80.0), (300.0, 2600.0, 110.0)
    reports = [sighting("cam-a", WEST, one, tag="1"), sighting("cam-a", WEST, two, tag="2"),
               sighting("cam-b", EAST, one, tag="1"), sighting("cam-b", EAST, two, tag="2")]
    fixes, leftover = X.pair_new([X.Sighting.from_measurement(m) for m in reports])
    assert not leftover
    assert sorted((round(f.x), round(f.y), round(f.z)) for f in fixes) == [(-250, 2300, 80), (300, 2600, 110)]


def _held(tracker, track_id_hint, x, y, z, *, start=0.0):
    """A confirmed track on a stationary object."""
    reports = [{"observation_id": f"{track_id_hint}-{i}", "t": start + 0.5 * i, "x": x, "y": y, "z": z, "sigma_m": 3.0}
               for i in range(5)]
    before = set(tracker.tracks)
    tracker.process(reports, now=start + 2.0)
    (track_id,) = set(tracker.tracks) - before
    return track_id


def test_one_camera_gives_a_direction_and_two_give_a_position():
    fixer, tracker = X.CrossFixer(["cam-a", "cam-b"]), Tracker()
    target = (150.0, 2400.0, 95.0)
    out = fixer.feed([sighting("cam-a", WEST, target, 0.0)], now=1.0, tracker=tracker)
    assert [m["kind"] for m in out] == ["bearing"] and out[0]["track"] is None
    tracker.process(out, now=1.0)
    assert not tracker.tracks, "a direction alone never starts a track"
    assert len(tracker.unassigned_bearings) == 1, "it is kept so it can be shown"

    out = fixer.feed([sighting("cam-a", WEST, target, 1.0), sighting("cam-b", EAST, target, 1.0)],
                     now=2.0, tracker=tracker)
    (fix,) = out
    assert fix["kind"] == "position" and fix["spawn"] is True and fix["cameras"] == ["cam-a", "cam-b"]
    assert (fix["x"], fix["y"]) == pytest.approx((150.0, 2400.0), abs=1e-3)
    tracker.process(out, now=2.0)
    assert len(tracker.tracks) == 1
    assert (fixer.fix_count, fixer.paired_sightings, fixer.single_sightings) == (1, 2, 1)


def test_sightings_of_an_instant_wait_until_every_camera_has_had_time_to_report():
    fixer, tracker = X.CrossFixer(["cam-a", "cam-b"]), Tracker()
    target = (150.0, 2400.0, 95.0)
    assert fixer.feed([sighting("cam-a", WEST, target, 5.0)], now=5.3, tracker=tracker) == []
    late = fixer.feed([sighting("cam-b", EAST, target, 5.0)], now=5.0 + X.HOLD_S, tracker=tracker)
    assert [m["kind"] for m in late] == ["position"]


def test_a_report_delivered_twice_is_used_once_and_other_sensors_pass_straight_through():
    fixer, tracker = X.CrossFixer(["cam-a", "cam-b"]), Tracker()
    target = (150.0, 2400.0, 95.0)
    radar = {"observation_id": "r1", "t": 0.0, "received_t": 0.1, "source_id": "radar-north", "x": 1.0, "y": 2.0}
    first = fixer.feed([radar, sighting("cam-a", WEST, target, 0.0)], now=0.2, tracker=tracker)
    assert first == [radar]
    out = fixer.feed([sighting("cam-a", WEST, target, 0.0), sighting("cam-b", EAST, target, 0.0)],
                     now=1.0, tracker=tracker)
    assert [m["kind"] for m in out] == ["position"] and fixer.paired_sightings == 2


def test_two_known_objects_seen_from_two_places_do_not_make_a_third():
    """The ghost case. Each camera's sighting lies close to tracks already held,
    but to different ones. Where the two directions cross there is nothing."""
    ghost = (0.0, 2400.0, 95.0)

    def on_ray(camera, share):
        """A point on the line from the camera through the ghost, at the height that line has there."""
        (cx, cy), (gx, gy, gz) = camera, ghost
        return (cx + (gx - cx) * share, cy + (gy - cy) * share, 6.0 + (gz - 6.0) * share)

    tracker = Tracker()
    # Two objects on each camera's line of sight, so each sighting could be either of them.
    for i, (camera, share) in enumerate(((WEST, 0.78), (WEST, 0.80), (EAST, 1.20), (EAST, 1.22))):
        _held(tracker, f"k{i}", *on_ray(camera, share))
    assert len(tracker.visible_tracks()) == 4
    reports = [sighting("cam-a", WEST, ghost, 3.0), sighting("cam-b", EAST, ghost, 3.0)]

    fixer = X.CrossFixer(["cam-a", "cam-b"])
    out = fixer.feed(reports, now=4.0, tracker=tracker)
    assert [m["kind"] for m in out] == ["bearing", "bearing"], "no position is made of it"
    assert all(m["track"] is None for m in out) and fixer.ghost_fixes == 1
    tracker.process(out, now=4.0)
    assert len(tracker.tracks) == 4

    # The same two sightings with nothing held are a new object, and are believed.
    alone = X.CrossFixer(["cam-a", "cam-b"])
    (fix,) = alone.feed(reports, now=4.0, tracker=Tracker())
    assert fix["spawn"] is True and (fix["x"], fix["y"]) == pytest.approx((0.0, 2400.0), abs=1e-3)


def test_a_camera_that_ought_to_see_a_new_object_and_does_not_vetoes_it():
    views = {"cam-a": None, "cam-b": None,
             "cam-c": {"x": 0.0, "y": 600.0, "z": 8.0, "heading_deg": 90.0, "hfov_deg": 12.0,
                       "reach_m": 2750.0, "max_elevation_deg": 6.75}}
    target = (0.0, 2400.0, 95.0)
    pair = [sighting("cam-a", WEST, target, 0.0), sighting("cam-b", EAST, target, 0.0)]

    silent = X.CrossFixer(views)
    out = silent.feed(pair, now=1.0, tracker=Tracker())
    assert [m["kind"] for m in out] == ["bearing", "bearing"] and silent.vetoed_fixes == 1

    agreeing = X.CrossFixer(views)
    (fix,) = agreeing.feed(pair + [sighting("cam-c", (0.0, 600.0), target, 0.0, height=8.0)], now=1.0, tracker=Tracker())
    assert fix["kind"] == "position" and len(fix["cameras"]) == 3 and agreeing.vetoed_fixes == 0


def test_a_lone_bearing_is_matched_to_a_well_placed_track_and_never_to_a_lost_one():
    tracker = Tracker(TrackerConfig(drop_after_s=120.0))
    track_id = _held(tracker, "k", 0.0, 2400.0, 95.0)
    fixer = X.CrossFixer(["cam-a", "cam-b"])
    (soon,) = fixer.feed([sighting("cam-a", WEST, (0.0, 2400.0, 95.0), 3.0)], now=4.0, tracker=tracker)
    assert soon["kind"] == "bearing" and soon["track"] == track_id

    # Forty seconds on with nothing accepted, the track's position is a guess hundreds of metres wide.
    (later,) = fixer.feed([sighting("cam-a", WEST, (0.0, 2400.0, 95.0), 42.0)], now=43.0, tracker=tracker)
    assert later["track"] is None, "a bearing must not steer a track that has been lost"


# --- what the tracker does with them ------------------------------------------------

def test_a_cameras_bearing_moves_the_estimate_across_the_line_of_sight_and_not_along_it():
    x_minus = [40.0, 2000.0, 3.0, -25.0]
    p_minus = [[400.0, 150.0, 30.0, 10.0], [150.0, 900.0, 12.0, 60.0],
               [30.0, 12.0, 16.0, 2.0], [10.0, 60.0, 2.0, 25.0]]
    sensor = (40.0, 0.0)                                  # due south: the line of sight is the y axis
    model, r = K.bearing_model(*sensor), [[math.radians(0.1) ** 2]]
    z = [math.atan2(2000.0, -15.0)]                       # the object is 15 m west of the estimate
    x_plus, p_plus, _ = K.update_across_sight_line(x_minus, p_minus, z, r, model, sensor)
    assert x_plus[0] == pytest.approx(25.0, abs=0.5), "across the line: taken from the bearing"
    assert x_plus[1] == pytest.approx(2000.0, abs=1e-9), "range: untouched"
    assert x_plus[3] == pytest.approx(-25.0, abs=1e-9), "range rate: untouched"
    assert p_plus[1][1] == pytest.approx(900.0, abs=1e-6), "and no more certain along the line than before"
    assert p_plus[0][0] < 20.0

    # The ordinary update does move range, through the correlation between the two.
    x_plain, _, _ = K.update(x_minus, p_minus, z, r, model)
    assert abs(x_plain[1] - 2000.0) > 1.0


def test_a_camera_that_still_has_the_object_keeps_its_track_from_going_stale():
    tracker = Tracker()
    track_id = _held(tracker, "k", 0.0, 2400.0, 95.0)
    for i in range(1, 25):                               # twelve seconds of bearings from one camera
        t = 2.0 + 0.5 * i
        report = sighting("cam-a", WEST, (0.0, 2400.0, 95.0), t)
        tracker.process([{**report, "camera": True, "track": track_id}], now=t)
    track = tracker.tracks[track_id]
    assert track.freshness is Freshness.PREDICTED, "coasting: direction known, range not"
    assert track.last_measurement.t == 2.0, "a bearing is not a position"

    tracker.advance_to(14.0 + tracker.config.stale_after_s + 3.0)
    assert tracker.tracks[track_id].freshness is Freshness.STALE, "once the camera loses it too, it goes stale"


def test_a_fix_matched_to_one_track_that_the_track_refuses_starts_nothing():
    tracker = Tracker()
    track_id = _held(tracker, "k", 0.0, 2400.0, 95.0)
    stray = {"observation_id": "fix-1", "t": 3.0, "source_id": X.FIX_SOURCE, "kind": "position",
             "x": 900.0, "y": 2400.0, "z": 95.0, "r": [[25.0, 0.0], [0.0, 25.0]], "cameras": ["cam-a", "cam-b"],
             "track": track_id}
    tracker.process([stray], now=3.0)
    assert set(tracker.tracks) == {track_id} and tracker.unmatched_fix_count == 1
    tracker.process([{**stray, "observation_id": "fix-2", "x": 2.0, "t": 3.5}], now=3.5)
    assert tracker.tracks[track_id].sources["cam-a"] == 3.5, "an accepted fix credits each camera in it"


def test_two_tracks_on_one_object_are_merged_only_when_asked_and_the_older_is_kept():
    def run(config):
        tracker = Tracker(config)
        first = _held(tracker, "a", 0.0, 2400.0, 95.0)
        # A second track started on the same object by a report tied to no existing track.
        tracker.process([{"observation_id": f"dup-{i}", "t": 2.5 + 0.5 * i, "x": 6.0, "y": 2404.0, "z": 95.0,
                          "sigma_m": 3.0, **({"spawn": True} if i == 0 else {})} for i in range(1)], now=2.5)
        (second,) = set(tracker.tracks) - {first}
        for i in range(1, 14):
            t = 2.5 + 0.5 * i
            tracker.process([{"observation_id": f"a-{i}", "t": t, "x": 0.0, "y": 2400.0, "z": 95.0, "sigma_m": 3.0, "track": first},
                             {"observation_id": f"b-{i}", "t": t, "x": 6.0, "y": 2404.0, "z": 95.0, "sigma_m": 3.0, "track": second}],
                            now=t)
        return tracker, first, second

    plain, first, second = run(TrackerConfig())
    assert set(plain.tracks) == {first, second} and plain.merged_count == 0

    merging, first, second = run(TrackerConfig(merge_after_s=3.0))
    assert set(merging.tracks) == {first}, "the newer one is retired"
    assert merging.merged_count == 1 and second in merging.archived


# --- the whole run, scored against ground truth ---------------------------------------

def _run(name, count, seed=42):
    scenario = generate_scenario(name, seed=seed, duration_s=DURATION_S, count=count,
                                 faults=FaultSpec.parse(MODE_FAULTS))
    timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=DURATION_S, scans=scenario.scans,
                              admit=("radar-north",) + C.CAMERA_IDS, cameras=C.views(),
                              config=TrackerConfig(drop_after_s=60.0, merge_after_s=3.0))
    return scenario, timeline


def _nearest_truth(scenario, t, x, y):
    return min(math.hypot(x - e.state_at(t).x, y - e.state_at(t).y) for e in scenario.ground_truth.entities)


@pytest.mark.parametrize("name", ["operator_demo", "operator_demo_signal_loss"])
@pytest.mark.parametrize("count", [3, 6])
def test_every_track_the_cameras_start_is_a_real_contact_and_there_is_one_each(name, count):
    scenario, timeline = _run(name, count)
    ever = {t["id"] for f in timeline["frames"] for t in f["tracks"]}
    assert len(ever) == count, "one track per contact: no ghosts, no duplicates, none missed"
    for frame in timeline["frames"]:
        for track in frame["tracks"]:
            if track["fresh"] == "U":
                assert _nearest_truth(scenario, frame["t"], track["x"], track["y"]) < 150.0, (frame["t"], track["id"])
    assert timeline["camera_fixes"] > 300 and timeline["tracks_merged"] == 0


@pytest.mark.parametrize("count", [3, 6])
def test_the_cameras_place_the_group_over_a_minute_before_the_radar_sees_it(count):
    _, timeline = _run("operator_demo", count)
    first, radar = {}, {}
    for frame in timeline["frames"]:
        for track in frame["tracks"]:
            if X.FIX_SOURCE in track["src"]:
                first.setdefault(track["id"], (frame["t"], track["range_m"]))
            if "radar-north" in track["src"]:
                radar.setdefault(track["id"], (frame["t"], track["range_m"]))
    assert radar, "the inbound contacts do reach the radar"
    assert min(r for _, r in first.values()) > 2900.0, "every first position is about 3 km out or more"
    for track_id, (seen_at, seen_range) in radar.items():
        fixed_at, _ = first[track_id]
        assert seen_range <= 1400.0 + 30.0
        assert seen_at - fixed_at > 55.0, track_id
    assert min(t for t, _ in radar.values()) - min(t for t, _ in first.values()) > 70.0


@pytest.mark.parametrize("count", [3, 6])
def test_a_contact_that_reaches_the_radar_was_held_by_cameras_all_the_way_in(count):
    """Custody: from the first fix to the radar picking it up, the track is
    freshly positioned in at least nine frames out of ten."""
    _, timeline = _run("operator_demo", count)
    handed_over = {t["id"] for f in timeline["frames"] for t in f["tracks"] if "radar-north" in t["src"]}
    assert handed_over
    for track_id in handed_over:
        states = []
        for frame in timeline["frames"]:
            snap = next((t for t in frame["tracks"] if t["id"] == track_id), None)
            if snap is None:
                continue
            if "radar-north" in snap["src"]:
                break
            states.append(snap["fresh"])
        assert states.count("U") / len(states) > 0.9, (track_id, states.count("U"), len(states))


def test_the_camera_mode_gives_the_same_answer_every_time():
    _, one = _run("operator_demo", 3)
    _, two = _run("operator_demo", 3)
    assert one["frames"] == two["frames"]


def test_other_modes_are_untouched_by_the_camera_machinery():
    """No cameras admitted: no fixer, no camera fields, and the radar unlimited."""
    scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6)
    assert not any(o.sensor_id in C.CAMERA_IDS for o in scenario.observations)
    timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0, scans=scenario.scans)
    assert "cams" not in timeline["frames"][0] and "sightings" not in timeline["frames"][0]
    assert "camera_fixes" not in timeline and "tracks_merged" not in timeline
    assert min(o.position.latitude ** 2 + o.position.longitude ** 2 for o in scenario.observations
               if o.sensor_id == "radar-north") ** 0.5 < 1400.0 < max(
        math.hypot(o.position.latitude, o.position.longitude) for o in scenario.observations
        if o.sensor_id == "radar-north")


# --- the mode as the server offers it ---------------------------------------------------

@pytest.fixture
def preview(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONEWATCH_DB_PATH", str(tmp_path / "camera_network_test.db"))
    monkeypatch.delenv("DRONEWATCH_WEBHOOK_SECRET", raising=False)
    import main as app_module
    import dronewatch.api.preview as preview_module
    importlib.reload(app_module)
    importlib.reload(preview_module)
    app_module.app.include_router(preview_module.router)
    with TestClient(app_module.app) as client:
        yield client, preview_module


def test_the_mode_is_offered_with_its_own_length_and_the_browser_cannot_shorten_it(preview):
    client, module = preview
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=3&mode=camera_network&duration_s=30").json()
    assert body["duration_s"] == 162.0 and len(body["frames"]) == 811
    assert body["mode"] == "camera_network" and "camera_network" in [m["id"] for m in body["modes"]]
    assert body["faults"].startswith("fixed cameras on, radar reach 1.4 km")
    assert module.SENSOR_LOSS_MODES["camera_network"]["admit"] == ["radar-north", *C.CAMERA_IDS]


def test_the_map_is_told_where_every_camera_stands_and_how_far_the_radar_reaches(preview):
    client, _ = preview
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=3&mode=camera_network").json()
    cameras = [s for s in body["sensors"] if s["kind"] == "fixed-camera"]
    assert [c["id"] for c in cameras] == list(C.CAMERA_IDS)
    gate = next(c for c in cameras if c["id"] == "cam-gate-n")
    assert gate == {"id": "cam-gate-n", "kind": "fixed-camera", "place": "N GATE", "x": 0.0, "y": 1500.0,
                    "heading_deg": 90.0, "hfov_deg": 12.0, "height_m": 6.0, "reach_m": 2750, "near_m": 752}
    (radar,) = [s for s in body["sensors"] if s["kind"] == "radar"]
    assert radar["reach_m"] == 1400.0 and (radar["x"], radar["y"]) == (0.0, 0.0)
    network = body["camera_network"]
    assert (network["cameras"], network["places"], network["radar_reach_m"]) == (32, 14, 1400.0)
    assert (network["target_size_m"], network["min_pixels"], network["bearing_sigma_deg"]) == (1.2, 8.0, 0.1)


def test_the_warning_gained_is_read_off_the_replay_itself(preview):
    client, module = preview
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6&mode=camera_network").json()
    warning = body["camera_network"]["early_warning"]
    assert warning == module.early_warning(body["frames"])
    assert [row["id"] for row in warning["tracks"]] == sorted(row["id"] for row in warning["tracks"])
    assert warning["first_fix"]["fix_range_m"] > 3000 and warning["first_radar"]["radar_range_m"] <= 1430
    assert warning["lead_s"] == pytest.approx(warning["first_radar"]["radar_t"] - warning["first_fix"]["fix_t"], abs=0.05)
    assert warning["lead_s"] > 70.0
    for row in warning["tracks"]:
        shown = [f["t"] for f in body["frames"] if any(t["id"] == row["id"] for t in f["tracks"])]
        assert row["fix_t"] == shown[0], "a track counts from the first frame it is shown in"
        if row["radar_t"] is None:
            assert row["gain_s"] is None, "never inside the radar's reach: no figure is invented"
        else:
            assert row["gain_s"] == pytest.approx(row["radar_t"] - row["fix_t"], abs=0.05) and row["gain_s"] > 55.0
    assert sum(1 for row in warning["tracks"] if row["radar_t"] is None) == 2, "the two wings turn away"


def test_a_frame_counts_the_cameras_and_lists_directions_nothing_could_be_made_of(preview):
    client, _ = preview
    body = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6&mode=camera_network").json()
    assert all(f["cams"] == [32, 32] for f in body["frames"][10:])
    assert all(set(f["sources"]) == {"radar-north"} for f in body["frames"]), "cameras are counted, not listed"
    rays = [ray for f in body["frames"] for ray in f["sightings"]]
    assert rays and all(ray[0] in C.CAMERA_IDS and -180.0 <= ray[1] <= 180.0 for ray in rays)
    # Before any position exists, the first camera already has a direction.
    first_track = next(f["t"] for f in body["frames"] if f["tracks"])
    assert any(f["sightings"] for f in body["frames"] if f["t"] < first_track)
    # A camera is listed on a track only while it is on it.
    for frame in body["frames"]:
        for track in frame["tracks"]:
            assert all(age <= 3.0 for source, age in track["src"].items() if source in C.CAMERA_IDS)


def test_the_camera_mode_response_contains_no_ground_truth(preview):
    client, _ = preview
    raw = client.get("/api/preview/tracks?name=operator_demo&seed=42&count=6&mode=camera_network").text.lower()
    for token in ("true_class", "true_control_mode", "control_mode", "entity_id", "ground_truth", "provenance",
                  "intent", "gt-contact", "latitude", "longitude"):
        assert token not in raw, f"{token} leaked into the camera-network response"
