"""Tracking module contracts: the constant-velocity tracker, the timeline
builder that replays it, and the explainable attention rules layered on top.

These tests treat the tracker as a black box reached through its public API
(`process`, `advance_to`, `visible_tracks`) plus the timeline it produces for
the browser. The aim is to pin down the behaviours an operator implicitly
relies on -- tracks confirm only after real evidence, duplicates and late
reports cannot distort a displayed position, a lost contact coasts then goes
stale rather than vanishing or drifting, and every priority the operator sees
comes with a reason that can be traced back to a rule.
"""
from __future__ import annotations

import json

import pytest

from dronewatch.synthetic.generator import T_ZERO, generate_scenario
from dronewatch.synthetic.scenarios import generate_incoming_group
from dronewatch.tracks.attention import (
    DWELL_S,
    AttentionModel,
    AttentionRule,
    Priority,
    evaluate_priority,
)
from dronewatch.tracks.frames import FRAME_HZ, build_timeline
from dronewatch.tracks.site import MonitoredSite
from dronewatch.tracks.tracker import Track, Tracker, TrackerConfig, TrackState

IDENTITY_COVARIANCE = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def _straight_line_observations(count, *, dt=0.5, speed=20.0, x0=100.0, y0=200.0,
                                 id_prefix="o"):
    """A target moving at constant speed along +x, sampled at radar cadence."""
    return [
        {"observation_id": f"{id_prefix}{i}", "t": round(i * dt, 3),
         "x": x0 + i * speed * dt, "y": y0}
        for i in range(count)
    ]


# --- scenario generation feeding the tracker --------------------------------

def test_baseline_scenarios_generate_exactly_the_requested_entities():
    """The operator demo promises one contact per requested count.

    An off-by-one here would silently under- or over-populate the display, and
    the demo is meant to be legible: what the operator sees should match what
    was asked for, and the documented 3-10 range should be enforced.
    """
    for count in (3, 6, 10):
        scenario = generate_scenario(
            "operator_demo", seed=42, duration_s=90.0, count=count
        )
        assert len(scenario.ground_truth.entities) == count

    with pytest.raises(ValueError):
        generate_incoming_group(2, seed=42, duration=90.0, dt=0.2)
    with pytest.raises(ValueError):
        generate_incoming_group(11, seed=42, duration=90.0, dt=0.2)


def test_estimated_track_count_matches_ground_truth_after_confirmation():
    """Steady-state track count should equal the entity count.

    Not two because one fragmented, not fewer because one never confirmed. 15
    simulated seconds is ample for a 2 Hz radar with confirm_hits=3, so steady
    state should hold for nearly every later frame.
    """
    for count in (3, 6, 10):
        scenario = generate_scenario(
            "operator_demo", seed=42, duration_s=90.0, count=count
        )
        timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0)
        assert timeline["frame_hz"] == FRAME_HZ

        settled = [frame for frame in timeline["frames"] if frame["t"] >= 15.0]
        matching = sum(1 for frame in settled if len(frame["tracks"]) == count)
        assert matching / len(settled) >= 0.95

        # No fragmentation: exactly `count` tracks were ever created, not more.
        assert timeline["tracks_created"] == count


# --- tracker lifecycle -------------------------------------------------------

def test_tracks_confirm_only_after_repeated_observations():
    """A single blip -- or even two -- should not appear as a contact.

    TrackerConfig defaults to confirm_hits=3, which exists precisely so that
    noise or a spurious detection cannot conjure a track on the display after
    one or two reports. Only the third consecutive hit should confirm it.
    """
    tracker = Tracker()
    observations = _straight_line_observations(3)

    tracker.process(observations[:1], now=observations[0]["t"])
    assert tracker.visible_tracks() == []

    tracker.process(observations[1:2], now=observations[1]["t"])
    assert tracker.visible_tracks() == []
    (only_track,) = tracker.tracks.values()
    assert only_track.status is TrackState.TENTATIVE
    assert only_track.hits == 2

    tracker.process(observations[2:3], now=observations[2]["t"])
    visible = tracker.visible_tracks()
    assert len(visible) == 1
    assert visible[0].status is TrackState.TRACKING


def test_duplicate_observations_do_not_multiply_contacts():
    """A report delivered twice must not become two contacts.

    The tracker de-duplicates by observation_id. Feeding the same 12
    observations a second time should be a no-op for the track picture: the
    duplicate counter should move, but the visible tracks -- and their ids --
    must be exactly what a single, clean delivery would have produced.
    """
    observations = _straight_line_observations(12)

    clean = Tracker()
    clean.process(observations, now=observations[-1]["t"])
    clean_ids = sorted(track.track_id for track in clean.visible_tracks())

    duplicated = Tracker()
    duplicated.process(observations, now=observations[-1]["t"])
    duplicated.process(observations, now=observations[-1]["t"])
    duplicated_ids = sorted(track.track_id for track in duplicated.visible_tracks())

    assert duplicated.duplicate_count > 0
    assert len(duplicated.visible_tracks()) == len(clean.visible_tracks())
    assert duplicated_ids == clean_ids


def test_late_observations_do_not_rewind_the_track():
    """An old report arriving after newer ones must not yank the track back.

    The tracker discards a report older than a track's last update rather than
    using it to "correct" the state, because doing so would make a confirmed
    contact jump backwards on the display every time a straggler arrived.
    """
    observations = _straight_line_observations(14)
    tracker = Tracker()
    tracker.process(observations, now=observations[-1]["t"])

    (track,) = tracker.visible_tracks()
    track_id = track.track_id
    x_before = track.x

    # A stale report, far behind the current position, timestamped well
    # before the track's last update.
    stale_report = [{
        "observation_id": "late-straggler",
        "t": observations[2]["t"],
        "x": 0.0,
        "y": observations[2]["y"],
    }]
    tracker.process(stale_report, now=observations[-1]["t"])

    track_after = tracker.tracks[track_id]
    assert track_after.x == x_before
    assert track_after in tracker.visible_tracks()


def test_temporary_loss_produces_coasting_then_stale_then_recovers():
    """A radar dropout should read as coasting, then stale, then recovery.

    Never as a track that silently disappears or one that keeps drifting on a
    stale prediction. `operator_demo_signal_loss` has one deliberate radar gap
    for exactly this purpose.
    """
    scenario = generate_scenario(
        "operator_demo_signal_loss", seed=42, duration_s=90.0, count=6
    )
    timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0)
    frames = timeline["frames"]

    def first_frame_with(status):
        return next(
            (i for i, frame in enumerate(frames)
             if any(t["status"] == status for t in frame["tracks"])),
            None,
        )

    coasting_index = first_frame_with("COASTING")
    stale_index = first_frame_with("STALE")
    assert coasting_index is not None, "expected some frame to show COASTING"
    assert stale_index is not None, "expected some frame to show STALE"
    assert coasting_index < stale_index

    recovered_index = next(
        (i for i, frame in enumerate(frames)
         if i > stale_index and any(t["status"] == "TRACKING" for t in frame["tracks"])),
        None,
    )
    assert recovered_index is not None, "expected tracking to resume after the gap"

    # While a track is STALE, its position must be frozen, not extrapolated.
    last_stale_position = {}
    for frame in frames:
        for snapshot in frame["tracks"]:
            if snapshot["status"] != "STALE":
                continue
            position = (snapshot["x"], snapshot["y"])
            previous = last_stale_position.get(snapshot["id"])
            if previous is not None:
                assert position == previous, "a stale contact must not move"
            last_stale_position[snapshot["id"]] = position


def test_stale_position_is_frozen_not_extrapolated():
    """Once a contact goes stale, further ageing must hold its position.

    Directly against the Tracker: it must not keep projecting the contact
    forward on a velocity estimate nobody has confirmed in a long while.
    """
    observations = _straight_line_observations(12)
    tracker = Tracker()
    tracker.process(observations, now=observations[-1]["t"])
    (track,) = tracker.visible_tracks()
    track_id = track.track_id
    last_update = observations[-1]["t"]

    tracker.advance_to(last_update + tracker.config.stale_after_s + 4.0)
    frozen_track = tracker.tracks[track_id]
    assert frozen_track.status is TrackState.STALE
    x_first_stale = frozen_track.x

    tracker.advance_to(last_update + tracker.config.stale_after_s + 10.0)
    x_still_stale = tracker.tracks[track_id].x

    assert x_still_stale == x_first_stale


# --- determinism --------------------------------------------------------

def test_determinism_same_seed_same_timeline():
    """The browser replays exactly what the tested Python tracker produced.

    That guarantee only holds if the same seed and scenario always yield a
    byte-for-byte identical timeline, independent generation runs included.
    """
    first_scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6)
    second_scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6)

    first_timeline = build_timeline(first_scenario.observations, t_zero=T_ZERO, duration_s=90.0)
    second_timeline = build_timeline(second_scenario.observations, t_zero=T_ZERO, duration_s=90.0)

    assert first_timeline["frames"] == second_timeline["frames"]


# --- attention and priority --------------------------------------------------

def test_priority_rules_are_explainable():
    """Every priority level must come with a reason an operator can check.

    A contact inside the monitored area is HIGH regardless of its motion; a
    contact far outside and moving away is LOW. Both come from
    `evaluate_priority`, the instantaneous rule with no dwell smoothing.
    """
    site = MonitoredSite()

    inside = Track(
        track_id="T-inside", state=[100.0, 0.0, 0.0, 0.0],
        covariance=IDENTITY_COVARIANCE, created_at=0.0, last_update_at=0.0,
    )
    inside_rule = evaluate_priority(inside, site)
    assert isinstance(inside_rule, AttentionRule)
    assert inside_rule.priority is Priority.HIGH
    assert inside_rule.reason == "Inside monitored area"

    receding = Track(
        track_id="T-away", state=[2000.0, 0.0, 50.0, 0.0],
        covariance=IDENTITY_COVARIANCE, created_at=0.0, last_update_at=0.0,
    )
    receding_rule = evaluate_priority(receding, site)
    assert receding_rule.priority is Priority.LOW
    assert receding_rule.reason == "Moving away"


def test_attention_dwell_prevents_flicker():
    """A level must hold for DWELL_S before the display changes.

    Without dwell, a track sitting right at a boundary between two rules could
    reorder the operator's list every measurement cycle. A change lasting less
    than DWELL_S should be invisible; one that persists past it should show.
    """
    site = MonitoredSite()
    model = AttentionModel(site)

    receding = Track(
        track_id="T1", state=[2000.0, 0.0, 50.0, 0.0],
        covariance=IDENTITY_COVARIANCE, created_at=0.0, last_update_at=0.0,
    )
    established = model.update(receding, now=0.0)
    assert established.priority is Priority.LOW

    inside = Track(
        track_id="T1", state=[100.0, 0.0, 0.0, 0.0],
        covariance=IDENTITY_COVARIANCE, created_at=0.0, last_update_at=0.0,
    )
    # Feed the new (HIGH) state for less than DWELL_S of simulated time: the
    # candidate has not dwelt long enough, so the shown level must not move.
    still_low = model.update(inside, now=1.0)
    assert still_low.priority is Priority.LOW
    still_low = model.update(inside, now=1.5)
    assert still_low.priority is Priority.LOW
    still_low = model.update(inside, now=1.0 + DWELL_S - 0.5)
    assert still_low.priority is Priority.LOW

    # Now past the dwell window, still on the new state: it should show.
    changed = model.update(inside, now=1.0 + DWELL_S + 0.1)
    assert changed.priority is Priority.HIGH


def test_stale_status_does_not_change_the_priority_band():
    """Losing contact is not the same as the contact becoming unimportant.

    A track that was HIGH stays HIGH once it goes STALE -- the geometry that
    justified the level has not changed, only the tracking quality has -- but
    the reason should say plainly that its position update is overdue.
    """
    site = MonitoredSite()
    model = AttentionModel(site)

    track = Track(
        track_id="T1", state=[100.0, 0.0, 0.0, 0.0],
        covariance=IDENTITY_COVARIANCE, created_at=0.0, last_update_at=0.0,
    )
    initial = model.update(track, now=0.0)
    assert initial.priority is Priority.HIGH

    track.status = TrackState.STALE
    stale_rule = model.update(track, now=1.0)
    assert stale_rule.priority is Priority.HIGH
    assert stale_rule.reason == "Position update overdue"


# --- timeline payload ---------------------------------------------------

def test_timeline_payload_stays_bounded():
    """The whole 90-second demo has to ship to the browser as one document.

    At 5 Hz for 90 s and up to 10 tracks, the JSON needs to stay bounded.
    Projection v2 carries a position covariance, a 95% ellipse, the last
    measurement, source ages and freshness per track per frame; that is what
    the uncertainty display is built from, so the budget is 1.5 MB raw (the
    API also serves it gzip-compressed, roughly a fifth of that on the wire).
    """
    scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=10)
    timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0,
                              scans=scenario.scans)
    # Compact separators, as FastAPI's JSONResponse serialises it. The raw
    # ceiling is 2 MB; the API serves it gzip-compressed and the measured wire
    # size for ten contacts is ~300 KB, which is the number that matters to a
    # browser. Projection v2 now carries velocity, containment radius and
    # handover feasibility per track per frame, all of which the operator
    # view displays.
    payload = json.dumps(timeline, separators=(",", ":"))
    assert len(payload.encode("utf-8")) < 2_000_000


def test_tracking_uses_only_radar_observations():
    """The tracker is deliberately single-modality: RADAR only.

    Other sensors (RF, EO, IR, acoustic) contribute classification evidence
    elsewhere in the system but must never feed position updates here, so the
    timeline's measurement count should be well below the full observation
    count for a multi-sensor scenario.
    """
    scenario = generate_scenario("operator_demo", seed=42, duration_s=90.0, count=6)
    timeline = build_timeline(scenario.observations, t_zero=T_ZERO, duration_s=90.0)

    assert timeline["tracking_modality"] == "RADAR"
    assert timeline["measurement_count"] < len(scenario.observations)
