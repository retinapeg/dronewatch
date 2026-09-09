"""M1 domain contracts.

These tests are the reason M1 exists. They pin the invariants that every later
milestone relies on. Each of the twelve required invariants is covered and
labelled with its number.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from dronewatch.domain import (
    AuthorisationRecord,
    AuthorisationScope,
    AuthorityKind,
    ClassificationDistribution,
    ClockKind,
    Decision,
    EngagementLifecycle,
    EngagementState,
    FusedTrack,
    Instant,
    LatencyLedger,
    LatencyStage,
    Modality,
    MotionEvidence,
    ObjectClass,
    Rationale,
    SensorObservation,
    SimulatedClock,
    SystemClock,
    ThreatAssessment,
    ThreatBand,
    ThreatGroup,
    TrackState,
    band_for,
    effective_authorisation,
    elapsed_seconds,
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def _authorisation(track_ids, scope=AuthorisationScope.TRACK, excluded=frozenset(),
                   decision=Decision.AUTHORISED):
    return AuthorisationRecord(
        authorisation_id="auth-1",
        decision=decision,
        scope=scope,
        authority_kind=AuthorityKind.OPERATOR,
        authority_id="operator-7",
        decided_at=NOW,
        covered_track_ids=frozenset(track_ids),
        excluded_track_ids=frozenset(excluded),
        rationale="test",
    )


# --- Invariant 1: classification probabilities are bounded 0..1 -------------

def test_invariant_1_probabilities_are_bounded():
    with pytest.raises(ValueError):
        ClassificationDistribution(entries=((ObjectClass.THREAT, 1.4),))
    with pytest.raises(ValueError):
        ClassificationDistribution(entries=((ObjectClass.THREAT, -0.1),))
    with pytest.raises(ValueError):
        ClassificationDistribution.from_scores({ObjectClass.THREAT: -1.0})


# --- Invariant 2: normalisation is explicit and tested ----------------------

def test_invariant_2_normalisation_is_explicit():
    # The direct constructor validates rather than silently repairing.
    with pytest.raises(ValueError):
        ClassificationDistribution(
            entries=((ObjectClass.THREAT, 0.6), (ObjectClass.DECOY, 0.6))
        )
    # from_scores normalises on purpose, and says so in its name.
    distribution = ClassificationDistribution.from_scores(
        {ObjectClass.THREAT: 3.0, ObjectClass.DECOY: 1.0}
    )
    assert distribution.probability(ObjectClass.THREAT) == pytest.approx(0.75)
    assert sum(distribution.as_dict().values()) == pytest.approx(1.0)


def test_top_class_is_derived_and_does_not_replace_the_distribution():
    distribution = ClassificationDistribution.from_scores(
        {ObjectClass.THREAT: 0.62, ObjectClass.DECOY: 0.27,
         ObjectClass.BENIGN: 0.06, ObjectClass.UNKNOWN: 0.05}
    )
    assert distribution.top_class is ObjectClass.THREAT
    # The losing hypotheses survive; they are not discarded in favour of the top.
    assert distribution.probability(ObjectClass.DECOY) == pytest.approx(0.27)
    assert len(distribution.as_dict()) == 4


# --- Invariant 3: UNKNOWN is available when evidence is insufficient --------

def test_invariant_3_unknown_is_available():
    assert ClassificationDistribution.unknown().probability(ObjectClass.UNKNOWN) == 1.0
    # No evidence must not become a fabricated guess.
    assert ClassificationDistribution.from_scores({}) == ClassificationDistribution.unknown()
    assert ClassificationDistribution.from_scores(
        {ObjectClass.THREAT: 0.0}
    ) == ClassificationDistribution.unknown()
    assert MotionEvidence.insufficient().is_sufficient is False


# --- Invariant 4: manoeuvre evidence does not force THREAT ------------------

def test_invariant_4_motion_evidence_cannot_produce_identity_or_threat():
    """ACTIVE MANOEUVRE != THREAT, enforced structurally."""
    evidence = MotionEvidence(
        active_control_probability=1.0,
        manoeuvre_score=1.0,
        trajectory_confidence=1.0,
        supporting_observations=50,
    )
    assert evidence.is_sufficient is True

    # MotionEvidence exposes no identity and no threat, by construction.
    exposed = {name for name in dir(evidence) if not name.startswith("_")}
    assert "classification" not in exposed
    assert "object_class" not in exposed
    assert "threat" not in exposed

    # A track with maximal control evidence still classifies as UNKNOWN until
    # something explicitly classifies it.
    track = FusedTrack(track_id="t1", first_seen=NOW, last_seen=NOW, motion=evidence)
    assert track.classification == ClassificationDistribution.unknown()
    assert track.threat is None


def test_straight_flight_is_not_decoy():
    """STRAIGHT FLIGHT != DECOY. Absent evidence is not evidence of absence."""
    track = FusedTrack(
        track_id="t2", first_seen=NOW, last_seen=NOW,
        motion=MotionEvidence(active_control_probability=0.0, supporting_observations=50),
    )
    assert track.classification.probability(ObjectClass.DECOY) == 0.0
    assert track.classification.top_class is ObjectClass.UNKNOWN


def test_threat_assessment_requires_stated_reasons():
    with pytest.raises(ValueError):
        ThreatAssessment(score=0.9, band=ThreatBand.HIGH, assessed_at=NOW, rationale=())
    assessment = ThreatAssessment(
        score=0.9, band=band_for(0.9), assessed_at=NOW,
        rationale=(Rationale(reason="entered restricted zone", evidence="obs-3"),),
        consumed_features=("active_control_probability",),
    )
    assert assessment.band is ThreatBand.HIGH


# --- Invariant 5: the two lifecycles are independent ------------------------

def test_invariant_5_lifecycles_are_independent():
    track = FusedTrack(track_id="t3", first_seen=NOW, last_seen=NOW)

    track.lifecycle.advance(TrackState.CONFIRMED)
    assert track.engagement.state is EngagementState.NONE

    track.engagement.advance(EngagementState.RECOMMENDED)
    assert track.lifecycle.state is TrackState.CONFIRMED

    # A track may be lost while an engagement is still pending a decision.
    track.engagement.advance(EngagementState.DECISION_PENDING)
    track.lifecycle.advance(TrackState.LOST)
    assert track.engagement.state is EngagementState.DECISION_PENDING

    # And reacquired without disturbing the engagement.
    track.lifecycle.advance(TrackState.REACQUIRED)
    assert track.engagement.state is EngagementState.DECISION_PENDING


def test_illegal_transitions_are_rejected_on_both_lifecycles():
    track = FusedTrack(track_id="t4", first_seen=NOW, last_seen=NOW)
    with pytest.raises(ValueError):
        track.lifecycle.advance(TrackState.ASSESSED)
    with pytest.raises(ValueError):
        track.engagement.advance(EngagementState.SIMULATED_ENGAGEMENT)


# --- Invariant 6: no simulated engagement without an authorisation record ---

def test_invariant_6_engagement_requires_authorisation():
    lifecycle = EngagementLifecycle("t5")
    lifecycle.advance(EngagementState.RECOMMENDED)
    lifecycle.advance(EngagementState.DECISION_PENDING)

    with pytest.raises(PermissionError):
        lifecycle.advance(EngagementState.AUTHORISED)

    lifecycle.record_authorisation(_authorisation(["t5"]))
    lifecycle.advance(EngagementState.AUTHORISED)
    lifecycle.advance(EngagementState.EFFECTOR_ASSIGNED)
    lifecycle.advance(EngagementState.ENGAGEMENT_PENDING)
    lifecycle.advance(EngagementState.SIMULATED_ENGAGEMENT)
    assert lifecycle.state is EngagementState.SIMULATED_ENGAGEMENT


def test_no_reachable_path_to_simulated_engagement_without_authorisation():
    """Exhaustive: every route into a protected state is blocked."""
    from dronewatch.domain.engagement import AUTHORISATION_REQUIRED_STATES, _ALLOWED

    for source, targets in _ALLOWED.items():
        for target in targets & AUTHORISATION_REQUIRED_STATES:
            lifecycle = EngagementLifecycle("t6")
            lifecycle._state = source  # place the machine directly in the source state
            with pytest.raises(PermissionError):
                lifecycle.advance(target)


def test_a_rejected_decision_does_not_authorise():
    lifecycle = EngagementLifecycle("t7")
    lifecycle.advance(EngagementState.RECOMMENDED)
    lifecycle.advance(EngagementState.DECISION_PENDING)
    lifecycle.record_authorisation(_authorisation(["t7"], decision=Decision.REJECTED))
    with pytest.raises(PermissionError):
        lifecycle.advance(EngagementState.AUTHORISED)


def test_an_authorisation_for_another_track_is_refused():
    lifecycle = EngagementLifecycle("t8")
    with pytest.raises(ValueError):
        lifecycle.record_authorisation(_authorisation(["someone-else"]))


# --- Invariant 7: group authorisation records exactly which tracks ----------

def test_invariant_7_group_authorisation_enumerates_coverage():
    record = _authorisation(["a", "b", "c"], scope=AuthorisationScope.GROUP)
    assert record.covered_track_ids == frozenset({"a", "b", "c"})
    assert record.covers("a") and record.covers("c")
    assert not record.covers("d")

    with pytest.raises(ValueError):
        _authorisation([], scope=AuthorisationScope.GROUP)

    # Coverage is frozen at decision time, not re-derived from membership later.
    group = ThreatGroup(group_id="g1", created_at=NOW)
    group.add("a")
    group.attach_authorisation(record)
    group.add("z")
    assert not group.authorisation.covers("z")


def test_track_scoped_authorisation_covers_exactly_one_track():
    with pytest.raises(ValueError):
        _authorisation(["a", "b"], scope=AuthorisationScope.TRACK)


# --- Invariant 8: a track may be excluded from or override a group decision -

def test_invariant_8_mode_c_group_with_exclusions():
    record = _authorisation(
        ["a", "b", "c"], scope=AuthorisationScope.GROUP, excluded={"b"}
    )
    assert record.covers("a")
    assert not record.covers("b")

    lifecycle = EngagementLifecycle("b")
    with pytest.raises(ValueError):
        lifecycle.record_authorisation(record)


def test_invariant_8_mode_d_per_track_overrides_the_group():
    group_record = AuthorisationRecord(
        authorisation_id="grp-1", decision=Decision.AUTHORISED,
        scope=AuthorisationScope.GROUP, authority_kind=AuthorityKind.OPERATOR,
        authority_id="operator-7", decided_at=NOW,
        covered_track_ids=frozenset({"a", "b"}), rationale="group",
    )
    track_record = AuthorisationRecord(
        authorisation_id="trk-1", decision=Decision.REJECTED,
        scope=AuthorisationScope.TRACK, authority_kind=AuthorityKind.OPERATOR,
        authority_id="operator-9", decided_at=NOW,
        covered_track_ids=frozenset({"b"}), rationale="override",
    )
    # Mode B: the group decision applies where there is no per-track decision.
    assert effective_authorisation("a", None, group_record) is group_record
    # Mode D: the per-track decision wins for track b.
    resolved = effective_authorisation("b", track_record, group_record)
    assert resolved is track_record
    assert resolved.authorises is False
    # Mode A: a per-track decision with no group at all.
    assert effective_authorisation("b", track_record, None) is track_record
    # No decision covering the track resolves to nothing, not to permission.
    assert effective_authorisation("zzz", track_record, group_record) is None


# --- Invariant 9: ground truth cannot enter the evaluated pipeline ----------

EVALUATED_PACKAGES = ("domain", "sensors", "fusion", "tracks", "threats",
                      "decisions", "effectors", "metrics")


def test_invariant_9_ground_truth_never_reaches_evaluated_modules():
    root = pathlib.Path(__file__).resolve().parent.parent / "dronewatch"
    offenders = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if not relative.parts or relative.parts[0] not in EVALUATED_PACKAGES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "groundtruth" in node.module or "synthetic" in node.module:
                    offenders.append(f"{relative}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "groundtruth" in alias.name or "synthetic" in alias.name:
                        offenders.append(f"{relative}: import {alias.name}")
    assert offenders == [], f"ground truth leaked into evaluated modules: {offenders}"


def test_ground_truth_records_class_and_control_mode_separately():
    """So evaluation can tell 'misidentified object' from 'misread motion'."""
    from dronewatch.synthetic.groundtruth import ControlMode, GroundTruthEntity

    controlled_decoy = GroundTruthEntity(
        entity_id="gt-1",
        true_class=ObjectClass.DECOY,
        true_control_mode=ControlMode.CONTROLLED,
    )
    assert controlled_decoy.true_class is ObjectClass.DECOY
    assert controlled_decoy.true_control_mode is ControlMode.CONTROLLED


# --- Invariant 10: latency durations cannot be negative ---------------------

def test_invariant_10_durations_cannot_be_negative():
    clock = SimulatedClock(NOW)
    ledger = LatencyLedger(ClockKind.SIMULATED)

    first = clock.now()
    ledger.stamp(LatencyStage.FIRST_SENSOR_OBSERVATION, first)
    clock.advance(0.25)
    ledger.stamp(LatencyStage.DETECTION_CREATED, clock.now())

    assert ledger.duration(
        LatencyStage.FIRST_SENSOR_OBSERVATION, LatencyStage.DETECTION_CREATED
    ) == pytest.approx(0.25)

    # Stamping a later stage before an earlier one is refused outright.
    earlier = Instant(monotonic_s=first.monotonic_s - 1, wall=NOW, kind=ClockKind.SIMULATED)
    with pytest.raises(ValueError):
        ledger.stamp(LatencyStage.TRACK_ESTABLISHED, earlier)

    with pytest.raises(ValueError):
        elapsed_seconds(clock.now(), first)


def test_a_stage_is_stamped_at_most_once():
    ledger = LatencyLedger(ClockKind.SIMULATED)
    instant = SimulatedClock(NOW).now()
    ledger.stamp(LatencyStage.FIRST_SENSOR_OBSERVATION, instant)
    with pytest.raises(ValueError):
        ledger.stamp(LatencyStage.FIRST_SENSOR_OBSERVATION, instant)


def test_unstamped_stages_report_none_rather_than_zero():
    ledger = LatencyLedger(ClockKind.SIMULATED)
    ledger.stamp(LatencyStage.FIRST_SENSOR_OBSERVATION, SimulatedClock(NOW).now())
    assert ledger.derived()["total_sensor_to_defeat_latency"] is None


def test_derived_metrics_cover_the_documented_chain():
    ledger = LatencyLedger(ClockKind.SIMULATED)
    clock = SimulatedClock(NOW)
    for stage in LatencyStage:
        ledger.stamp(stage, clock.now())
        clock.advance(0.1)
    derived = ledger.derived()
    assert derived["total_sensor_to_defeat_latency"] == pytest.approx(0.9)
    assert all(value is not None and value >= 0 for value in derived.values())


# --- Invariant 11: simulated and real clocks are distinguished --------------

def test_invariant_11_clock_kinds_cannot_be_mixed():
    simulated = SimulatedClock(NOW).now()
    real = SystemClock().now()
    assert simulated.kind is ClockKind.SIMULATED
    assert real.kind is ClockKind.SYSTEM

    with pytest.raises(ValueError):
        elapsed_seconds(simulated, real)

    ledger = LatencyLedger(ClockKind.SIMULATED)
    with pytest.raises(ValueError):
        ledger.stamp(LatencyStage.FIRST_SENSOR_OBSERVATION, real)


def test_simulated_time_cannot_move_backwards():
    clock = SimulatedClock(NOW)
    with pytest.raises(ValueError):
        clock.advance(-1)


# --- SensorObservation contracts -------------------------------------------

def test_observation_confidence_is_bounded_or_absent():
    def build(confidence):
        return SensorObservation(
            observation_id="obs-1", sensor_id="radar-north", modality=Modality.RADAR,
            observed_at=NOW, received_at=NOW, confidence=confidence,
        )

    assert build(None).confidence is None
    assert build(0.62).confidence == 0.62
    with pytest.raises(ValueError):
        build(1.5)


def test_observation_defaults_to_unknown_classification():
    observation = SensorObservation(
        observation_id="obs-2", sensor_id="rf-east", modality=Modality.RF,
        observed_at=NOW, received_at=NOW,
    )
    assert observation.classification == ClassificationDistribution.unknown()


def test_future_dated_observation_is_detectable_and_delay_is_never_negative():
    observation = SensorObservation(
        observation_id="obs-3", sensor_id="eo-1", modality=Modality.EO,
        observed_at=NOW + timedelta(hours=1), received_at=NOW,
    )
    assert observation.is_future_dated is True
    assert observation.transport_delay_s == 0.0


def test_adding_observations_tracks_contributing_sensors():
    track = FusedTrack(track_id="t9", first_seen=NOW, last_seen=NOW)
    for index, sensor in enumerate(("radar-north", "rf-east", "radar-north")):
        track.add_observation(
            SensorObservation(
                observation_id=f"obs-{index}", sensor_id=sensor,
                modality=Modality.RADAR, observed_at=NOW,
                received_at=NOW + timedelta(seconds=index),
            )
        )
    assert track.contributing_sensors == {"radar-north", "rf-east"}
    assert len(track.observations) == 3
    assert track.last_seen == NOW + timedelta(seconds=2)
