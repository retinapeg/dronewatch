# Synthetic multi-sensor C-UAS data

This directory holds generated scenario data for DroneWatch V0.2. It is a
**required workstream**, not a convenience: we do not own a multi-sensor
counter-UAS dataset, so every fusion, threat, decision and benchmark capability
depends on synthetic data existing first.

Nothing here is real sensor data. Nothing here describes a real site, a real
platform, or a real system's performance.

## Status

**Implemented at M2.** The generator lives in `dronewatch/synthetic/` and covers
eleven scenarios across five modalities. Fusion, classification, threat scoring
and engagement are deliberately absent; M2 produces ground truth and observations
only.

> Every sensor characteristic in this system is an invented simulation
> abstraction. No number here represents the performance of any real sensor,
> product or military system. They exist so that modalities differ from one
> another, giving fusion a reason to exist. They are not claims.

## Generation architecture

| Module | Responsibility |
|---|---|
| `rng.py` | Seed derivation. Named sub-streams, never global random state |
| `motion.py` | `SimState` and composable trajectory segments |
| `sensors.py` | Per-modality observation synthesis |
| `delivery.py` | Latency, delay, loss, duplication, bursts |
| `scenarios.py` | Trajectory families, scenario registry, swarm primitive |
| `generator.py` | Orchestration, `generate_scenario` |
| `serialise.py` | Deterministic JSON and JSONL |
| `stats.py` | Dataset statistics only |
| `generate.py` | Command-line entry point |

Motion is composed from segments rather than one large trajectory function:
constant velocity, constant acceleration, heading change, altitude change,
bounded manoeuvre impulse, and control degradation. A scenario chains them, for
example constant flight, then a manoeuvre, then constant flight again.

## Reproducibility contract

    same scenario name + same seed + same config
        = same ground truth and same observations

Every stochastic decision draws from a `random.Random` derived from the master
seed and a stable name, using blake2b rather than `hash()`, because Python
randomises string hashing per process. Adding a new scenario therefore cannot
disturb the output of an existing one, and generation is unaffected by whatever
else has touched the global random state.

Different seeds change noise, dropout and timing while preserving the scenario's
intended structure.

## Scenario registry

| Scenario | Contains |
|---|---|
| `single_threat` | One controlled UAS |
| `single_decoy` | One passive decoy |
| `straight_flying_threat` | Counterexample: real threat, weak manoeuvre evidence |
| `controlled_decoy` | Counterexample: genuine agency, not hostile |
| `tumbling_decoy` | Counterexample: erratic motion, not controlled |
| `mixed_threat_decoy` | Threats and decoys together, both counterexamples included |
| `sensor_disagreement` | EO confident, IR and radar weak, acoustic silent on class |
| `sensor_dropout` | RF disappears for the middle third |
| `track_reacquisition_fixture` | All sensors quiet for a deliberate gap |
| `false_positive` | Spurious observations with no entity behind them |
| `delayed_out_of_order` | Heavy delay, duplication and bursty arrival |
| `small_swarm` | Parameterised entity set, `--count` |

The swarm primitive is `generate_swarm(count, threat_fraction, decoy_fraction,
seed, ...)`. It produces trajectories only. No ranking, grouping, authorisation
or engagement happens at M2. M9 scales the same primitive to larger counts.

## What is committed and what is not

Generated scenario files are **not** committed. They are reproducible from a
seed, so the seed and the generator are the artefacts worth versioning.

Git stores the generator, the scenario specifications, the seeds, checksums of
any reference scenario, and result summaries. It does not store bulk output.

Add to `.gitignore` when the generator lands:

```
data/synthetic/*.json
data/synthetic/*.jsonl
data/synthetic/runs/
!data/synthetic/README.md
```

## Example CLI

```sh
python -m dronewatch.synthetic.generate \
    --scenario mixed_threat_decoy --seed 42 --output /tmp/dronewatch-scenario

python -m dronewatch.synthetic.generate \
    --scenario small_swarm --seed 42 --count 10 --output /tmp/dronewatch-swarm

python -m dronewatch.synthetic.generate --list
```

Omitting `--output` prints the summary without writing anything.

## Generated file layout

```
<output>/<scenario-name>/seed-<nnnnnn>/
    metadata.json
    observations.jsonl
    ground_truth.json
```

Generated output is untracked. `.gitignore` covers `data/generated/` and bulk
files under `data/synthetic/`, keeping this README.

## The ground-truth rule

This is the single most important property in the whole workstream.

**Ground truth must never reach the algorithm being evaluated.**

A scenario file contains two disjoint namespaces. The pipeline under test is
handed `sensor_observations` only. Evaluation joins observations back to
`ground_truth_entities` afterwards, outside the pipeline.

If ground truth leaks into fusion, threat assessment, decisions or effectors,
every metric produced becomes meaningless while still looking plausible. A test
asserts that no module under evaluation imports the ground-truth types.

Three mechanisms enforce this at M2:

1. `ScenarioResult`, `ScenarioGroundTruth` and the provenance map all live in
   `dronewatch/synthetic/groundtruth.py`, on the protected side of the M1 import
   guard.
2. Which entity produced an observation is held in
   `ground_truth.observation_provenance`, never on the observation.
3. `read_observations_only()` loads a scenario's observations without opening
   `ground_truth.json` at all.

Observations carry no control-mode field and no manoeuvre field. Control
evidence must be derived by the pipeline from trajectory history; supplying it as
an input would be a ground-truth leak wearing a disguise.

Class evidence is present but capped: no observation may place more than 0.70 of
its probability mass on any class, and sensors are only right in proportion to
their configured evidence strength. An observation is informative and fallible,
never an oracle. A test asserts that top-class agreement with truth is strictly
below 100 percent.

## Scenario file shape

Conceptual, subject to refinement in M1 and M2:

```jsonc
{
  "scenario_id": "H-simultaneous-004",
  "seed": 1743,
  "generator_version": "0.2.0",
  "timing_metadata": {
    "t_zero": "2026-09-09T12:00:00Z",
    "duration_s": 180,
    "tick_hz": 10,
    "clock": "simulated"
  },

  "ground_truth_entities": [
    {
      "entity_id": "gt-uas-01",
      "true_class": "THREAT",
      "true_control_mode": "CONTROLLED",
      "intent": "INCURSION",
      "trajectory": [ { "t": 0.0, "x": 0, "y": 0, "z": 60 } ]
    }
  ],

  "sensor_observations": [
    {
      "observation_id": "obs-000001",
      "sensor_id": "radar-north",
      "modality": "RADAR",
      "observed_at": "2026-09-09T12:00:00.100Z",
      "emitted_at":  "2026-09-09T12:00:00.140Z",
      "position": { "kind": "range_bearing", "range_m": 1420, "bearing_deg": 348 },
      "classification": { "THREAT": 0.41, "DECOY": 0.22, "UNKNOWN": 0.37 },
      "confidence": 0.62,
      "quality": { "noise": true, "duplicate": false, "delayed_ms": 40 }
    }
  ],

  "expected_tracks":   [ { "track_hint": "one track for gt-uas-01" } ],
  "expected_outcomes": [ { "entity_id": "gt-uas-01", "should_reach": "DEFEAT_CONFIRMED" } ]
}
```

Notes on the shape:

- `observed_at` and `emitted_at` are separate so that delayed and out-of-order
  delivery are representable. Latency measurement depends on this distinction.
- `confidence` is always 0 to 1, matching both DroneWatch V0.1.1 normalisation
  and the SAPIENT detection confidence convention.
- `classification` is a normalised distribution, not a scalar, so competing
  hypotheses survive fusion. `UNKNOWN` carries the unexplained mass.
- No observation carries a control-mode or manoeuvre field. Control evidence is
  **derived** by the pipeline from trajectory history; supplying it as an input
  would leak ground truth.
- `expected_*` are evaluation hints, not instructions to the pipeline.

## Generation contract

1. Deterministic. Same seed and generator version produce byte-identical output.
2. No wall-clock reads, no unseeded RNG, no dependence on set or dict iteration
   order in serialised output.
3. Every scenario declares which imperfections it injects, so a failing metric
   can be traced to a cause.
4. Generation is offline and side-effect free. It writes files and nothing else.

## Trajectory families and required counterexamples

Two baseline families, useful because they separate cleanly:

```
DECOY:   passive / low-control dynamics + environmental disturbance
THREAT:  controlled dynamics + manoeuvre process + environmental disturbance
```

These families are a starting point, **not the label the classifier should
learn**. A generator that only produces them would teach the system that turning
means threat, which is exactly the failure we need to detect.

The generator must therefore also produce deliberate counterexamples:

| Case | Ground truth | Motion signature |
|---|---|---|
| Q | Genuine threat | Nearly constant route, weak manoeuvre evidence |
| R | Decoy | Irregular or tumbling motion, strong apparent manoeuvre |
| S | Controlled decoy | Genuine active control, not hostile |
| T | Genuine UAS | Sparse or weak manoeuvre evidence |
| U | Any | Sensor noise that mimics manoeuvring |

Case S is the important one conceptually. It separates **agency** from
**hostility**: something can be actively flown and still not be a threat. The
domain model keeps control evidence separate from identity for this reason.

Evaluation must measure **calibration**, not only accuracy. A model that is
confidently wrong on case Q is worse than one that is appropriately uncertain on
case P. Report reliability of the probability estimates, not just a hit rate.

Ground truth therefore records both the entity's true class and its true control
mode as separate fields, so a run can distinguish "misidentified the object" from
"misread the motion".

## Imperfections the generator must be able to inject

Noise on position and confidence, dropped observations, duplicated observations,
delayed delivery, out-of-order delivery, sensors disagreeing on classification,
sensors degrading mid-scenario, false positives with no ground-truth entity, and
confidence that drifts over a track's life.

## Scenario catalogue

The A to O catalogue is defined in
[`../../docs/V0.2_PANOPTES_ROADMAP.md`](../../docs/V0.2_PANOPTES_ROADMAP.md).
Build A to E first; they unblock M4.

## Evaluation metrics

Track association accuracy, classification accuracy, false-positive rate,
missed-track rate, track fragmentation, sensor-to-track latency,
sensor-to-decision latency, sensor-to-simulated-defeat latency, and throughput
as the simultaneous UAS count rises.

Each metric needs a documented definition before it is reported. A latency
number with an unstated start point is not a measurement.
