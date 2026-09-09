# Sensor loss, uncertainty and recovery: the mathematics behind the code

This document explains the estimation code actually delivered in
`dronewatch/tracks/kalman.py`, `dronewatch/tracks/tracker.py` and
`dronewatch/tracks/frames.py`, the tests that pin each equation, and the
experiments that measure the behaviour. Where a statement is a mathematical
result under stated assumptions, an empirical finding, or an engineering policy
choice, it is labelled as such.

Scope: passive tracking and incident awareness, in a local planar simulation
frame. No engagement, no intent classification.

---

## 1. Conventions

| symbol | meaning | units |
|---|---|---|
| `x = [p_x, p_y, v_x, v_y]^T` | state: position and velocity, x east, y north | m, m, m/s, m/s |
| `t` | simulation time of an event (`observed_at`) | s |
| `dt` | elapsed time between two event times | s |
| `w` | power spectral density of white acceleration, per axis | m²/s³ |
| `R` | measurement covariance | m² (position), rad² (bearing) |
| `P` | state covariance, 4×4 | mixed, m², m²/s, m²/s² |

Altitude is **not** a state. The sensors in this project do not support a
vertical-velocity estimate, so the last measured altitude is carried beside the
track (`Track.last_altitude_m`) and left `None` when absent
(`test_missing_altitude_never_becomes_zero_altitude`).

Four times are kept distinct (`tracker.py` module docstring):
`observed_at` (event time), `received_at` (delivery), `state_time` (the time
the stored posterior refers to, always the last accepted positional
measurement), and display time (the `now` most recently passed to
`advance_to`). Playback time in the browser is presentation only.

---

## 2. Motion model and time-correct prediction

**Assumption (model).** Between measurements the contact's velocity is a
Wiener process: `dp = v dt`, `dv = dW`, `E[dW dW^T] = W dt`, with
`W = w I₂`. This is the nearly-constant-velocity model with *continuous* white
acceleration noise.

**Derivation.** Write the SDE as `dx = A x dt + G dW` with

```
A = [[0, I],[0, 0]],   G = [[0],[I]].
```

Since `A² = 0`, `Φ(dt) = exp(A dt) = I + A dt`, giving

```
F(dt) = [[I, dt I],
         [0,    I]].
```

The process-noise covariance over the interval is
`Q(dt) = ∫₀^dt Φ(dt−s) G W Gᵀ Φ(dt−s)ᵀ ds`. With `Φ(τ) G = [[τ I],[I]]`,

```
Q(dt) = ∫₀^dt [[τ² W, τ W],[τ W, W]] dτ = [[dt³/3 W, dt²/2 W],
                                          [dt²/2 W,    dt W]].
```

For the state ordering `[p_x, p_y, v_x, v_y]` the blocks interleave: the
`(p_x, v_x)` and `(p_y, v_y)` pairs each carry the 2×2 block above and there
is no cross-axis coupling. That is what `kalman.process_noise` builds
(`test_process_noise_matches_hand_calculation`).

**Distinction that matters.** The discrete white-noise-acceleration (DWNA)
model, "a random constant acceleration `a ~ N(0, σ_a²)` held over one
interval", gives `Q_d(dt) = σ_a² [[dt⁴/4, dt³/2],[dt³/2, dt²]]` with `σ_a` in
m/s². Its parameter has different units and, more importantly, it is **not**
the discretisation of any continuous-time process: cutting an interval in two
gives a different total covariance. The continuous model composes exactly:

```
Q(a+b) = F(b) Q(a) F(b)ᵀ + Q(b).
```

Both facts are tested: `test_continuous_process_noise_composes_over_adjacent_intervals`
and the deliberate negative `test_discrete_acceleration_model_does_not_compose`.
The previous implementation used DWNA (`process_accel_sigma = 2.2 m/s²`); it was
replaced, not re-parameterised, because irregular gaps are the whole point here.

**Prediction.** `x⁻ = F x⁺`, `P⁻ = F P⁺ Fᵀ + Q(dt)` with the *actual elapsed
event time* (`kalman.predict`). `dt = 0` is the identity
(`test_zero_time_prediction_is_the_identity`); negative `dt` is an error.
Predicting over a gap in one step or in many gives the same distribution
(`test_partitioned_prediction_matches_one_step`,
`test_time_step_invariance_of_prediction_only`). Nothing in the browser
touches `Q`: the tracker stores the posterior at `state_time` and evaluates the
prediction on demand (`Track.predicted_at`), so playback speed and render rate
cannot change the estimated distribution.

**Initialisation** (`Tracker._spawn`). From one position measurement:
`x = [z_x, z_y, 0, 0]`, `P = diag(R, σ_v² I)` with `σ_v = 30 m/s`. The
velocity prior is centred on zero and wide; three hits at 2 Hz are required
before the track is shown, by which time the velocity has been learned.

---

## 3. What "no measurement" means

**Policy and mathematics together.** When no valid measurement arrives, the
posterior is left exactly as it was and only the prediction is evaluated
(`test_no_measurement_means_prediction_only`). Nothing is inserted: not the
previous position, not the predicted position, not zero. Covariance is never
reset.

**Uncertainty over a blackout.** From `P⁻ = F P Fᵀ + Q` with `dt = τ`,

```
P_pp(τ) = P_pp + τ (P_pv + P_vp) + τ² P_vv + (w τ³/3) I
P_pv(τ) = P_pv + τ P_vv + (w τ²/2) I
P_vv(τ) = P_vv + (w τ) I
```

The cross term `2τ P_pv` is why position uncertainty grows faster than the
process-noise term alone suggests when the velocity estimate is correlated with
position (`kalman.position_variance_after_gap`,
`test_blackout_growth_matches_analytic_including_cross_terms`).

Which quantities grow: velocity variance grows linearly and position variance
at least cubically, both monotonically; the position-velocity covariance can
briefly *decrease* if it starts negative. A test demanding that every entry
increase at every step would be wrong and is not written.

**Ordering under dropout.** For a linear-Gaussian model with known
association, `P` does not depend on measurement *values*, only on the
schedule, so removing measurements gives `P_gap − P_full ⪰ 0`
(`test_dropping_measurements_can_only_increase_covariance`, checked as
positive semidefiniteness of the difference).

**Three separate states** (`tracker.py`): lifecycle (TENTATIVE / CONFIRMED /
ARCHIVED), freshness (UPDATED / PREDICTED / STALE), and source health
(REPORTING / DEGRADED / UNAVAILABLE / UNKNOWN). They coexist
(`test_lifecycle_freshness_and_source_health_are_independent`). A STALE marker
is held at the *last measured* position for the operator, while the internal
prediction keeps moving and its covariance keeps growing
(`test_stale_display_is_frozen_but_uncertainty_keeps_growing`). Retention
(`drop_after_s = 25`) is a display policy, not a probability.

---

## 4. Measurement update

For `z = h(x) + v`, `v ~ N(0, R)`, with `H` the Jacobian of `h` at `x⁻`:

```
ν = z − h(x⁻)
S = H P⁻ Hᵀ + R
K = P⁻ Hᵀ S⁻¹
x⁺ = x⁻ + K ν
P⁺ = (I − K H) P⁻ (I − K H)ᵀ + K R Kᵀ        (Joseph form)
```

`K` is obtained by solving `S Kᵀ = H P⁻` with a Cholesky factorisation
(`kalman.solve_spd`); no inverse is formed. The Joseph form equals the
standard `(I − K H) P⁻` for the optimal gain and stays symmetric
positive-semidefinite under rounding
(`test_joseph_form_equals_standard_form_for_the_optimal_gain`).

Validation before any update: finite measurement, covariance of the right
dimension, symmetric, positive definite (`kalman.validate_covariance`,
`test_invalid_measurement_covariance_is_rejected`). The only numerical hygiene
is symmetrisation, `(A + Aᵀ)/2`, after predict and update; the PSD check used
by diagnostics adds a relative jitter of `1e-9` on the diagonal and is never
used for a solve.

**Position model** (`kalman.position_model`): `H = [I₂ 0]`, `R = σ² I₂`. A
partial measurement uses the corresponding rows of `H` and the submatrix of
`R`; the unmeasured axis is untouched
(`test_partial_measurement_uses_the_measurement_subspace`). A measurement of
exactly `(0, 0)` is a measurement (`test_zero_coordinates_are_a_real_measurement`).

**Bearing model** (`kalman.bearing_model`), from a sensor at known `s`:

```
h(x) = atan2(p_y − s_y, p_x − s_x)
H    = [ −d_y / r²,  d_x / r²,  0, 0 ],   d = p − s, r² = |d|²
```

The innovation is wrapped to `(−π, π]` (`test_bearing_innovation_wraps_across_pi`),
the Jacobian is checked against finite differences, and the update is refused
within `min_range_m` of the sensor where the bearing is undefined
(`test_bearing_is_singular_at_the_sensor`).

**Observability.** Linearised, one bearing at range `r` is a cross-range
measurement with standard deviation `r σ_b`. It constrains the axis across the
line of sight and says nothing about range
(`test_bearing_update_tightens_across_the_line_of_sight_only`). With a single
fixed bearing sensor and a constant-velocity target, range is unobservable
without target manoeuvre or sensor motion; the filter returns a number for it
because the prior does, not because the measurement informs it. That is why a
bearing does not refresh positional freshness (§3) and cannot start a track
(`test_bearing_cannot_start_a_track_but_can_update_one`).

Class confidence from a detector is never converted to positional covariance;
there is no calibration model that would justify it.

---

## 5. Kinds of loss

| case | what reaches the estimator | what the tracker does | experiment |
|---|---|---|---|
| A. one contact unobserved | radar heartbeats continue, that contact's returns stop | that track goes PREDICTED → STALE; source REPORTING | `single_contact_loss` |
| B. radar source stops | no returns, no heartbeats | all tracks PREDICTED → STALE; source UNAVAILABLE | `radar_off_*` |
| C. sparse sampling | radar at 0.5 Hz | larger `dt` per prediction, correct `Q` | `sparse_radar_0p5hz` |
| D. degraded quality | radar reports σ×4 in its heartbeat; returns carry `sigma_m` | `R` follows the report; source DEGRADED | `radar_degraded_x4` |
| E. radar lost, positional backup | EO positions (25 m, 1 Hz) admitted | tracks stay UPDATED on EO | `radar_off_backup_eo` |
| E′. radar lost, bearing backup | bearing-only sensor at (−900, −300) | cross-range tightens, range grows; freshness STALE | `radar_off_backup_brg` |
| F. only non-positional evidence | RF reports admitted as evidence | counted per source, no state change | `radar_off_rf_evidence` |
| G. everything positional lost | all positional sensors off | as B | `all_positional_off` |

Source health is derived from **heartbeats** (`SensorScan` records generated
with the observations), never from the absence of detections
(`test_source_health_comes_from_heartbeats_not_from_detections`). Without a
heartbeat the health is UNKNOWN. No packet is not a negative detection; no
detection-probability model is used to pretend otherwise.

The backup sources are synthetic and clearly labelled. They are generated with
their own RNG streams (`stream(seed, "noise", scenario, sensor, entity)`), so
they are not radar returns renamed (verified in the generator: injecting a radar
fault leaves every non-radar report byte-identical). What each measures is
stated in `SensorModel`: EO measures position with 25 m noise; the bearing
sensor measures angle with 2° noise and nothing else.

---

## 6. Delay, duplicates and returning inputs

**Causality.** `build_timeline` feeds the tracker in delivery order and, at
frame time `now`, only reports with `received_at ≤ now`
(`test_changing_future_reports_cannot_change_earlier_frames`).

**Late-data policy** (engineering choice; `Tracker._reference_state`,
`_apply_late`). Each track keeps a bounded deque of checkpoints: the state
before each accepted measurement inside the last `reorder_window_s = 1.5 s`.
A report older than `state_time` but inside the window is handled by rolling
back to the checkpoint preceding the first newer measurement, applying the late
report, and replaying the newer ones. For a linear-Gaussian model this is
exactly the posterior in-order delivery would have produced
(`test_late_report_inside_the_window_gives_the_in_order_posterior`, to 1e-9).
Reports older than the window are rejected with a count and never applied as
if current (`test_late_report_outside_the_window_is_rejected_not_applied`).

Trade-off: a longer window tolerates larger transport delays at the cost of
more replay work per late report and longer checkpoint deques. The window is
set from the synthetic transport delay (≤ 0.2 s) with a wide margin. The
alternative — holding all sources until the slowest has reported — was
rejected because a silent source must not stall the others.

**Deduplication** happens before any update, by `observation_id`; a retry
neither shrinks covariance nor adds a hit
(`test_a_retry_does_not_shrink_covariance_or_add_a_hit`,
`test_duplicate_of_a_late_report_is_still_applied_once`).

After restoration, current reports update normally; a backlog of stale packets
is late data (applied inside the window, rejected outside); duplicates are
dropped. A changed source identity appears as a new `source_id` in the track's
`sources` map with its own age.

---

## 7. Association and recovery

Gating uses the innovation covariance:

```
d² = νᵀ S⁻¹ ν ≤ γ,   γ = 25 (2 dof, position), 13 (1 dof, bearing)
```

`γ = 25` is beyond the 99.99 % point of χ²(2). Statistically it is loose; it
is chosen so a constant-velocity filter's lag through a gentle turn does not
spawn a phantom, and it is still far tighter than the ≥ 450 m spacing between
contacts in the demonstration. Both numbers are in `TrackerConfig` with that
origin stated.

Among gated candidates the tracker minimises `d² + ln|S|`, the negative
log-likelihood up to a constant, so a track with an enormous covariance does
not look like an excellent match for everything
(`test_covariance_volume_penalises_a_vague_track`). The margin to the runner-up
is recorded; a margin below 2 (likelihood ratio < e) is counted as an
ambiguous association (`test_ambiguity_is_recorded_when_two_tracks_compete`)
and exposed per track. Unmatched position reports start tentative tracks;
unmatched bearings are counted and cannot start anything (§4).

**Recovery honesty.** A track keeps its ID only if a returning report gates
into it and wins the likelihood comparison. Beyond retention it is archived and
a returning contact becomes a *new* identity — the count returning to six is
not called recovery (`test_long_blackout_archives_and_reacquires_as_new_identities`).
The experiments report identity switches and impure tracks against ground truth
the tracker never saw; the crossing-pair and ten-contact cases fail visibly
(§9). The nearest-neighbour baseline is retained as the baseline; no competing
architectures were added.

---

## 8. Uncertainty as an output

Per track and frame (`frames.py`, projection version 2): displayed position,
predicted position when the marker is held (`est`), position covariance
(`cov = [P_xx, P_xy, P_yy]`), 95 % ellipse (`ell`), last accepted positional
measurement and its time (`meas`), age of positional information (`age_s`),
freshness (`fresh`), contributing sources with their ages (`src`), association
margin (`amb`) and ambiguous-update count (`ambn`), priority with its basis
(`basis` ∈ measured / predicted / stale). Per frame: source health.

**Ellipse.** For the 2×2 position block `P_pp` with eigenvalues `λ₁ ≥ λ₂` and
major-axis angle `θ = ½ atan2(2 P_xy, P_xx − P_yy)`, the region
`{d : dᵀ P_pp⁻¹ d ≤ c}` with `c = χ²₂(0.95) = 5.991` has semi-axes
`√(c λ₁), √(c λ₂)` (`kalman.position_ellipse`,
`test_ellipse_axes_from_diagonal_covariance`). This is *not* `1.96 σ` per
axis; the test asserts the difference. It is a model-based region: it has the
stated coverage when the model is right, and its empirical coverage is measured
separately (§9). No scalar "confidence" replaces it.

**Attention under loss.** While PREDICTED, priority is evaluated from the
predicted state and labelled so. Once STALE, the last justified band is held
with the reason "Position update overdue" and basis `stale`; no new "moving
away" is manufactured from frozen geometry
(`attention.AttentionModel.update`, `test_radar_blackout_preserves_identity_and_shows_growth_then_recovery`).

---

## 9. Verification

**Layer A** (`tests/test_kalman.py`, `experiments.sensor_loss.layer_a`):
truth generated by the filter's own model, known association. NEES
`(x_true − x̂)ᵀ P⁻¹ (x_true − x̂)` has 4 dof, NIS `νᵀ S⁻¹ ν` has 2 dof. Trials
are independent runs evaluated at fixed step indices, and the bound on the mean
uses the normal approximation to `χ²(N·dof)/N`. Result (400 runs, held-out
seed base): NEES means 4.18 / 3.95 / 3.98 against a 95 % band [3.72, 4.28];
ellipse coverage 0.97 normally and 0.95 at the end of a 10 s prediction-only
gap. The equations are implemented as derived.

**Layer B** (`tests/test_sensor_loss.py`, `experiments.sensor_loss`): the real
3/6/10-contact pipeline with association, delivery effects and faults, scored
against ground truth (evaluation only). Metric definitions with denominators
are in `experiments/sensor_loss.py::METRICS` and in the results file. The
pipeline NIS is reported as a diagnostic only: gated, nearest-neighbour-selected
residuals are not an unbiased sample of the innovation distribution, and
consecutive frames are correlated.

Quick run on held-out seeds (2024, 31337, 99, 555), six contacts unless stated;
"during" is the fault window. Full table: `docs/results/sensor_loss_quick.md`.

| experiment | during RMSE (m) / cov95 | missing | fragments | id switches | impure | recovery (s) |
|---|---|---|---|---|---|---|
| normal | 8.6 / 0.99 | 0 | 0 | 0 | 0 | — |
| radar off 5 s | 19.5 / 1.00 | 0 | 0 | 0 | 0 | 1.0 |
| radar off 15 s | 59.7 / 0.99 | 0 | 0 | 0 | 0 | 1.0 |
| radar off 30 s | 66.8 / 1.00 | 0.10 | 6 | 6 | 0 | 2.1 (new identities) |
| one contact unobserved 15 s | 16.9 / 0.99 | 0 | 0 | 0 | 0 | 0.8 |
| all positional off 15 s | 59.0 / 0.97 | 0 | 0 | 0 | 0 | 1.0 |
| radar off, EO backup | 25.4 / 0.97 | 0 | 0 | 0 | 0 | 0.5 |
| radar off, bearing backup | 60.3 / 0.95 | 0 | 0 | 0 | 0 | 1.0 |
| radar off, RF evidence only | 59.7 / 0.99 | 0 | 0 | 0 | 0 | 1.0 |
| sparse radar 0.5 Hz | 14.8 / 0.98 | 0 | 0 | 0 | 0 | — |
| radar noise ×4 | 21.7 / 0.98 | 0 | 0 | 0 | 0 | — |
| delayed + duplicate delivery, radar off 15 s | 59.4 / 0.99 | 0 | 0 | 0 | 0 | 2.8 |
| crossing pair, radar off 15 s | 29.7 / 1.00 | 0 | 0 | **1.0** | 0 | 1.1 |
| ten contacts, radar off 15 s | 69.7 / 0.91 | 0.01 | 0.2 | **1.5** | **1.0** | 3.2 |
| three contacts, radar off 15 s | 61.7 / 1.00 | 0 | 0 | 0 | 0 | 0.9 |

Reading these together, not one at a time:

- Coverage sits at 0.97–1.00 in most cases, above nominal. The model is
  conservative for straight-flying contacts: `w = 4 m²/s³` was chosen to
  survive the demonstration's turns, and it over-states uncertainty during
  straight segments. NEES(2) diagnostics in the results file are below 2 in
  those phases. This is not inflated to make coverage look good; it is a
  tuning compromise and is reported as such.
- The bearing backup improves RMSE by almost nothing at 1.5–2 km with a 2°
  sensor: the along-line-of-sight axis dominates the error and is unobservable.
  Coverage still holds (0.95).
- Failures are real and visible: the crossing pair swaps identity on every
  run; ten contacts average one impure reacquisition per run; a 30 s outage
  exceeds retention and every contact returns as a new identity with 10 % of
  entity-frames uncovered.
- Processing cost is 0.4–0.6 s per 90 s six-contact run in pure Python.

Larger run: `python -m experiments.sensor_loss --full` (20 held-out seeds,
2000 Layer A runs; a few minutes, single process).

---

## 10. Parameters

| parameter | value | units | origin |
|---|---|---|---|
| `process_noise_w` | 4.0 | m²/s³ | tuning: velocity uncertainty √(w t) ≈ 6 m/s over 10 s tolerates the 2.6°/s turns; conservative on straight segments (§9) |
| `measurement_sigma_m` | 10 | m | synthetic radar declaration |
| `bearing_sigma_rad` | 2° | rad | synthetic bearing sensor declaration |
| `gate_chi2` | 25 | — | > 99.99 % of χ²(2); chosen for turn tolerance, see §7 |
| `gate_chi2_1dof` | 13 | — | ≈ 99.97 % of χ²(1) |
| `ambiguity_margin` | 2 | −2 ln L | likelihood ratio e |
| `reorder_window_s` | 1.5 | s | ≥ 7× the synthetic transport delay |
| `confirm_hits` | 3 | — | policy |
| `coast_after_s` / `stale_after_s` / `drop_after_s` | 2.5 / 8 / 25 | s | display and retention policy |
| `initial_velocity_sigma` | 30 | m/s | wide prior; learned within three hits |
| `heartbeat_tolerance_scans` | 2.5 | scans | policy |

---

## 11. Equation → implementation → test → experiment

| equation | function | test | experiment |
|---|---|---|---|
| `F(dt)` | `kalman.transition` | `test_transition_composes_over_adjacent_intervals` | all |
| `Q(dt)` continuous | `kalman.process_noise` | `test_process_noise_matches_hand_calculation`, `..._composes_...`, `..._dimensional_scaling` | all |
| DWNA ≠ CWNA | `kalman.process_noise_discrete` | `test_discrete_acceleration_model_does_not_compose` | — |
| predict | `kalman.predict` | `test_partitioned_prediction_matches_one_step`, `test_time_step_invariance_of_prediction_only` | all |
| blackout growth | `kalman.position_variance_after_gap` | `test_blackout_growth_matches_analytic_including_cross_terms` | `radar_off_*` |
| Joseph update, solve | `kalman.update`, `kalman.solve_spd` | `test_scalar_reference_update_on_one_axis`, `test_joseph_form_equals_standard_form_for_the_optimal_gain` | all |
| partial `H` | `kalman.position_model` | `test_partial_measurement_uses_the_measurement_subspace` | — |
| bearing `h`, `H`, wrap | `kalman.bearing_model`, `wrap_angle` | `test_bearing_*` | `radar_off_backup_brg` |
| NIS / NEES | `kalman.innovation`, `kalman.nees` | `test_nees_and_nis_are_consistent_across_independent_runs` | Layer A |
| 95 % ellipse | `kalman.position_ellipse` | `test_ellipse_*`, `test_ellipse_coverage_is_near_nominal_in_the_matched_model` | coverage columns |
| `P_gap ⪰ P_full` | — | `test_dropping_measurements_can_only_increase_covariance` | — |
| prediction-only gap, STALE display | `Tracker.advance_to` | `test_no_measurement_means_prediction_only`, `test_stale_display_is_frozen_but_uncertainty_keeps_growing` | `radar_off_*` |
| source health | `Tracker.heartbeat`, `_refresh_sources` | `test_source_health_comes_from_heartbeats_not_from_detections`, `test_degraded_source_...` | A/B/D |
| late data replay | `Tracker._reference_state`, `_apply_late` | `test_late_report_inside_the_window_gives_the_in_order_posterior`, `..._outside_the_window_...` | `delayed_duplicates` |
| dedupe | `Tracker.process` | `test_a_retry_does_not_shrink_covariance_or_add_a_hit` | `delayed_duplicates` |
| gate on `S`, `d² + ln|S|` | `Tracker.process` | `test_covariance_volume_penalises_a_vague_track`, `test_ambiguity_is_recorded_when_two_tracks_compete` | `crossing_blackout`, `ten_contacts_off_15s` |
| retention vs identity | `Tracker.advance_to` | `test_long_blackout_archives_and_reacquires_as_new_identities` | `radar_off_30s` |
| causality | `frames.build_timeline` | `test_changing_future_reports_cannot_change_earlier_frames` | all |

---

## 12. Known limitations

- **Model mismatch during turns.** A constant-velocity filter lags a
  sustained turn; the gate and `w` absorb the demonstration's 2.6°/s turns but
  a sharper manoeuvre inside a blackout will produce a large error at
  restoration and, with neighbours nearby, a wrong reacquisition. Measured, not
  fixed: `crossing_blackout` and `ten_contacts_off_15s`.
- **Conservative `w`.** Coverage above nominal on straight segments (§9).
  One candidate refinement — a lower `w` with a manoeuvre-detection widening of
  the gate — was not implemented; it should be compared against this baseline on
  held-out seeds before adoption.
- **Nearest-neighbour association.** Greedy in delivery order, no joint
  assignment, no track-existence probability. Ambiguity is recorded, not
  resolved.
- **Bearing-only range** is unobservable in this geometry; the filter's range
  during a bearing-only period is prior-driven.
- **Heartbeats are synthetic.** A real deployment needs the sensor to declare
  its scans and quality; without that, health is UNKNOWN and stays so.
- **Coverage figures are model-based**, checked against synthetic truth
  generated by a different (disturbed constant-velocity) motion model than the
  filter assumes. They say nothing about a real sensor.

---

## References

- S. Särkkä and L. Svensson, *Bayesian Filtering and Smoothing*, 2nd ed.,
  Cambridge University Press, 2023 — continuous-discrete models, SDE
  discretisation, Kalman filter forms.
- Y. Bar-Shalom, X. R. Li and T. Kirubarajan, *Estimation with Applications to
  Tracking and Navigation*, Wiley, 2001 — CWNA versus DWNA models (§6.2–6.3),
  Joseph form, NEES/NIS consistency tests, gating and out-of-sequence
  measurements.
- B. Sinopoli, L. Schenato, M. Franceschetti, K. Poolla, M. Jordan and
  S. Sastry, "Kalman Filtering with Intermittent Observations," *IEEE
  Transactions on Automatic Control* 49(9), 2004 — behaviour of the error
  covariance under randomly missing measurements.
- Stone Soup documentation, *ConstantVelocity* transition model, *KalmanUpdater*
  (Joseph form option) and the out-of-sequence-measurement tutorial —
  used to cross-check conventions; no Stone Soup code is used.
- Z. Chen, C. Heckman, S. Julier and N. Ahmed, "Weak in the NEES?: Auto-tuning
  Kalman filters with Bayesian optimization," *FUSION*, 2018 — limits of
  NEES/NIS-based tuning, which is why coverage, error and residuals are read
  together here.
