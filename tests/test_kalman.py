"""Layer A: the filter mathematics in isolation.

Known association, linear-Gaussian world, no tracker policy. Every test either
compares against a hand calculation, an analytic identity, or a statistic with
a stated chi-squared bound. Passing here says the equations are implemented as
derived; it says nothing about whether the multi-contact tracker associates
the right measurements (that is tests/test_tracking.py and the experiments).
"""
from __future__ import annotations

import math
import random

import pytest

from dronewatch.tracks import kalman as K

W = 4.0            # m^2/s^3, the project default PSD
R_POS = [[100.0, 0.0], [0.0, 100.0]]   # 10 m radar, isotropic


def diag(*values):
    return [[v if i == j else 0.0 for j in range(len(values))] for i, v in enumerate(values)]


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def mat_close(a, b, tol=1e-9):
    return all(close(a[i][j], b[i][j], tol) for i in range(len(a)) for j in range(len(a[0])))


# --- prediction ---------------------------------------------------------------

def test_zero_time_prediction_is_the_identity():
    x, p = [10.0, -5.0, 3.0, 2.0], diag(25.0, 25.0, 9.0, 9.0)
    x2, p2 = K.predict(x, p, 0.0, W)
    assert x2 == x and p2 == p
    assert K.process_noise(0.0, W) == [[0.0] * 4 for _ in range(4)]
    assert K.transition(0.0) == K.identity(4)


def test_process_noise_matches_hand_calculation():
    # dt = 0.5, w = 4:  dt^3/3 w = 0.125/3*4 = 0.166..., dt^2/2 w = 0.5, dt w = 2.0
    q = K.process_noise(0.5, 4.0)
    assert close(q[0][0], 4.0 * 0.125 / 3.0)
    assert close(q[1][1], 4.0 * 0.125 / 3.0)
    assert close(q[0][2], 0.5) and close(q[2][0], 0.5)
    assert close(q[1][3], 0.5) and close(q[3][1], 0.5)
    assert close(q[2][2], 2.0) and close(q[3][3], 2.0)
    # No coupling between the x and y channels.
    assert q[0][1] == 0.0 and q[0][3] == 0.0 and q[2][3] == 0.0


def test_process_noise_dimensional_scaling():
    """Q is homogeneous of degree 1 in w and rescales as a covariance when the
    length unit changes: lengths x k  =>  w x k^2  =>  Q x k^2."""
    q1 = K.process_noise(0.7, 4.0)
    q2 = K.process_noise(0.7, 8.0)
    assert mat_close(q2, K.scale(q1, 2.0))
    k = 1000.0   # metres -> millimetres
    qk = K.process_noise(0.7, 4.0 * k * k)
    assert mat_close(qk, K.scale(q1, k * k))


def test_transition_composes_over_adjacent_intervals():
    fa, fb, fab = K.transition(0.3), K.transition(1.1), K.transition(1.4)
    assert mat_close(K.matmul(fb, fa), fab)


def test_continuous_process_noise_composes_over_adjacent_intervals():
    """Q(a+b) = F(b) Q(a) F(b)^T + Q(b): the defining property of a Q that comes
    from a continuous-time SDE."""
    a, b = 0.3, 1.1
    lhs = K.process_noise(a + b, W)
    fb = K.transition(b)
    rhs = K.add(K.matmul(K.matmul(fb, K.process_noise(a, W)), K.transpose(fb)), K.process_noise(b, W))
    assert mat_close(lhs, rhs)


def test_discrete_acceleration_model_does_not_compose():
    """The point of the distinction: the discrete model's Q depends on how the
    interval is cut, so it is not an SDE discretisation."""
    a, b = 0.3, 1.1
    lhs = K.process_noise_discrete(a + b, 2.2)
    fb = K.transition(b)
    rhs = K.add(K.matmul(K.matmul(fb, K.process_noise_discrete(a, 2.2)), K.transpose(fb)),
                K.process_noise_discrete(b, 2.2))
    assert not mat_close(lhs, rhs, 1e-6)


def test_partitioned_prediction_matches_one_step():
    x, p = [100.0, 200.0, -12.0, 7.0], [[40.0, 5.0, 3.0, 0.0], [5.0, 30.0, 0.0, 2.0],
                                       [3.0, 0.0, 16.0, 1.0], [0.0, 2.0, 1.0, 12.0]]
    x1, p1 = K.predict(x, p, 2.5, W)
    xa, pa = K.predict(x, p, 0.4, W)
    xb, pb = K.predict(xa, pa, 0.9, W)
    xc, pc = K.predict(xb, pb, 1.2, W)
    assert all(close(x1[i], xc[i]) for i in range(4))
    assert mat_close(p1, pc)


def test_prediction_keeps_covariance_symmetric_and_psd():
    p = [[40.0, 5.0, 3.0, 0.0], [5.0, 30.0, 0.0, 2.0], [3.0, 0.0, 16.0, 1.0], [0.0, 2.0, 1.0, 12.0]]
    _, p2 = K.predict([0.0] * 4, p, 7.0, W)
    assert K.is_symmetric(p2)
    assert K.cholesky(p2) is not None


def test_blackout_growth_matches_analytic_including_cross_terms():
    """P_xx(t) = P_xx + 2t P_xv + t^2 P_vv + w t^3/3. The cross term is what a
    naive 'add process noise' argument misses."""
    p = [[25.0, 0.0, 6.0, 0.0], [0.0, 25.0, 0.0, -4.0], [6.0, 0.0, 9.0, 0.0], [0.0, -4.0, 0.0, 9.0]]
    for t in (0.5, 3.0, 15.0, 30.0):
        _, pt = K.predict([0.0] * 4, p, t, W)
        pxx, pyy = K.position_variance_after_gap(p, t, W)
        assert close(pt[0][0], pxx) and close(pt[1][1], pyy)
        assert close(pt[0][0], 25.0 + 12.0 * t + 9.0 * t * t + W * t ** 3 / 3.0)
    # Velocity variance grows linearly and the position-velocity covariance
    # grows too; position variance grows fastest. Not every entry must grow:
    # a negative cross term can shrink briefly, and that is correct behaviour.
    _, p30 = K.predict([0.0] * 4, p, 30.0, W)
    assert p30[2][2] > p[2][2] and p30[0][0] > p[0][0] and p30[0][2] > p[0][2]


def test_prediction_refuses_negative_time():
    with pytest.raises(ValueError):
        K.predict([0.0] * 4, K.identity(4), -0.1, W)


# --- update -------------------------------------------------------------------

def test_scalar_reference_update_on_one_axis():
    """With diagonal P and a measurement of x only, the update reduces to the
    textbook scalar filter: K = Pxx/(Pxx+R), P+ = Pxx - Pxx^2/(Pxx+R)."""
    x, p = [10.0, 20.0, 1.0, 2.0], diag(50.0, 60.0, 9.0, 9.0)
    z, r = [16.0], [[25.0]]
    x2, p2, inn = K.update(x, p, z, r, K.position_model((0,)))
    gain = 50.0 / 75.0
    assert close(x2[0], 10.0 + gain * 6.0)
    assert close(p2[0][0], 50.0 - 50.0 * 50.0 / 75.0)
    # Untouched channels: y and both velocities.
    assert close(x2[1], 20.0) and close(x2[2], 1.0) and close(x2[3], 2.0)
    assert close(p2[1][1], 60.0) and close(p2[2][2], 9.0) and close(p2[3][3], 9.0)
    assert close(inn.nis, 36.0 / 75.0)


def test_joseph_form_equals_standard_form_for_the_optimal_gain():
    """(I-KH)P(I-KH)^T + KRK^T equals (I-KH)P when K is optimal, so a correct
    Joseph implementation reproduces the standard result while staying PSD."""
    x = [0.0, 0.0, 0.0, 0.0]
    p = [[40.0, 5.0, 3.0, 0.0], [5.0, 30.0, 0.0, 2.0], [3.0, 0.0, 16.0, 1.0], [0.0, 2.0, 1.0, 12.0]]
    z = [3.0, -2.0]
    _, p_joseph, inn = K.update(x, p, z, R_POS, K.position_model())
    h = inn.jacobian
    s_inv_hp = K.solve_spd(inn.covariance, K.matmul(h, p))
    k = K.transpose(s_inv_hp)
    p_standard = K.matmul(K.sub(K.identity(4), K.matmul(k, h)), p)
    assert mat_close(p_joseph, K.symmetrize(p_standard), 1e-8)
    assert K.cholesky(p_joseph) is not None


def test_update_keeps_covariance_symmetric_psd_and_smaller():
    p = [[40.0, 5.0, 3.0, 0.0], [5.0, 30.0, 0.0, 2.0], [3.0, 0.0, 16.0, 1.0], [0.0, 2.0, 1.0, 12.0]]
    _, p2, _ = K.update([0.0] * 4, p, [1.0, 1.0], R_POS, K.position_model())
    assert K.is_symmetric(p2) and K.cholesky(p2) is not None
    # P - P+ is PSD: information never decreases on an update.
    assert K.cholesky_psd(K.sub(p, p2)) is not None


def test_zero_valued_coordinates_are_a_real_measurement():
    x, p = [30.0, -30.0, 0.0, 0.0], diag(100.0, 100.0, 25.0, 25.0)
    x2, p2, _ = K.update(x, p, [0.0, 0.0], R_POS, K.position_model())
    assert close(x2[0], 15.0) and close(x2[1], -15.0)
    assert p2[0][0] < p[0][0]


def test_partial_measurement_uses_the_measurement_subspace():
    x, p = [0.0, 0.0, 0.0, 0.0], diag(100.0, 100.0, 25.0, 25.0)
    _, p2, inn = K.update(x, p, [5.0], [[100.0]], K.position_model((1,)))
    assert inn.jacobian == [[0.0, 1.0, 0.0, 0.0]]
    assert close(p2[1][1], 50.0)
    assert close(p2[0][0], 100.0), "the unmeasured axis must not tighten"


def test_missing_altitude_never_becomes_zero_altitude():
    """The state has no altitude, so the model cannot even express one; the
    tracker carries the last measured altitude separately and leaves it None
    when absent. This guards the model surface."""
    with pytest.raises(ValueError):
        K.position_model((0, 1, 2))


@pytest.mark.parametrize("bad", [
    [[-1.0, 0.0], [0.0, 1.0]],            # not PD
    [[1.0, 2.0], [2.0, 1.0]],             # indefinite
    [[1.0, 0.5], [0.0, 1.0]],             # not symmetric
    [[float("nan"), 0.0], [0.0, 1.0]],    # not finite
    [[1.0]],                              # wrong dimension
])
def test_invalid_measurement_covariance_is_rejected(bad):
    with pytest.raises(K.MeasurementRejected):
        K.update([0.0] * 4, diag(100.0, 100.0, 25.0, 25.0), [0.0, 0.0], bad, K.position_model())


def test_non_finite_measurement_is_rejected():
    with pytest.raises(K.MeasurementRejected):
        K.innovation([0.0] * 4, diag(100.0, 100.0, 25.0, 25.0), [float("inf"), 0.0], R_POS, K.position_model())


def test_nis_is_the_normalised_innovation_squared():
    p = diag(100.0, 100.0, 25.0, 25.0)
    inn = K.innovation([0.0] * 4, p, [20.0, 0.0], R_POS, K.position_model())
    # S = 200 I, nu = (20, 0): nis = 400/200 = 2
    assert close(inn.nis, 2.0)


# --- bearing model --------------------------------------------------------------

def test_bearing_innovation_wraps_across_pi():
    model = K.bearing_model(0.0, 0.0)
    x = [-100.0, -1.0, 0.0, 0.0]                      # predicted bearing ~ -179.4 deg
    z = [math.radians(179.4)]
    inn = K.innovation(x, diag(100.0, 100.0, 25.0, 25.0), z, [[math.radians(2.0) ** 2]], model)
    assert abs(inn.residual[0]) < math.radians(2.0), "wrapped, not ~359 degrees"


def test_bearing_jacobian_matches_finite_difference():
    model = K.bearing_model(50.0, -20.0)
    x = [300.0, 400.0, 0.0, 0.0]
    lin = model(x)
    eps = 1e-4
    for axis in (0, 1):
        xp = list(x); xp[axis] += eps
        xm = list(x); xm[axis] -= eps
        fd = K.wrap_angle(model(xp).predicted[0] - model(xm).predicted[0]) / (2 * eps)
        assert close(lin.jacobian[0][axis], fd, 1e-5)
    assert lin.jacobian[0][2] == 0.0 and lin.jacobian[0][3] == 0.0


def test_bearing_is_singular_at_the_sensor():
    model = K.bearing_model(0.0, 0.0, min_range_m=1.0)
    with pytest.raises(K.MeasurementRejected):
        K.innovation([0.2, 0.3, 0.0, 0.0], diag(100.0, 100.0, 25.0, 25.0), [0.0], [[0.01]], model)


def test_bearing_update_tightens_across_the_line_of_sight_only():
    """Target due east of the sensor: a bearing constrains y, not x."""
    model = K.bearing_model(0.0, 0.0)
    x, p = [1000.0, 0.0, 0.0, 0.0], diag(400.0, 400.0, 25.0, 25.0)
    sigma_b = math.radians(1.0)
    _, p2, _ = K.update(x, p, [0.0], [[sigma_b ** 2]], model)
    # Linearised, a bearing at range r is a cross-range measurement with
    # sigma = r sigma_b, so the y channel follows the scalar filter exactly.
    cross_var = (1000.0 * sigma_b) ** 2
    assert close(p2[1][1], 400.0 * cross_var / (400.0 + cross_var), 1e-6)
    assert close(p2[0][0], p[0][0], 1e-6), "range is unobservable from one bearing"


# --- ellipse ---------------------------------------------------------------------

def test_ellipse_axes_from_diagonal_covariance():
    e = K.position_ellipse([[4.0, 0.0], [0.0, 1.0]])
    assert close(e.semi_major_m, math.sqrt(K.CHI2_2DOF_95 * 4.0))
    assert close(e.semi_minor_m, math.sqrt(K.CHI2_2DOF_95 * 1.0))
    assert close(e.angle_rad, 0.0)
    # And explicitly not the per-axis 1.96 sigma box.
    assert not close(e.semi_major_m, 1.96 * 2.0, 1e-3)


def test_ellipse_orientation_follows_the_covariance():
    # Equal variances with positive correlation: major axis along +45 degrees.
    e = K.position_ellipse([[10.0, 6.0], [6.0, 10.0]])
    assert close(e.angle_rad, math.pi / 4)
    assert close(e.semi_major_m, math.sqrt(K.CHI2_2DOF_95 * 16.0))
    assert close(e.semi_minor_m, math.sqrt(K.CHI2_2DOF_95 * 4.0))


# --- dropout ordering ----------------------------------------------------------------

def run_schedule(times_with_measurements, dt=0.5, horizon=20.0):
    """Predict at every dt; update only at the listed times. Measurement values
    do not affect P in a linear filter, so zeros are fine."""
    x, p = [0.0] * 4, diag(100.0, 100.0, 900.0, 900.0)
    t = 0.0
    while t < horizon - 1e-9:
        x, p = K.predict(x, p, dt, W)
        t += dt
        if any(abs(t - m) < 1e-9 for m in times_with_measurements):
            x, p, _ = K.update(x, p, [0.0, 0.0], R_POS, K.position_model())
    return p


def test_dropping_measurements_can_only_increase_covariance():
    every = [0.5 * i for i in range(1, 41)]
    gap = [m for m in every if not 5.0 <= m <= 12.0]
    p_full, p_gap = run_schedule(every), run_schedule(gap)
    diff = K.sub(p_gap, p_full)
    assert K.cholesky_psd(diff) is not None, "P_gap - P_full must be PSD"
    assert p_gap[0][0] > p_full[0][0] and p_gap[2][2] > p_full[2][2]


def test_time_step_invariance_of_prediction_only():
    """Predicting over a gap in one step or many gives the same distribution."""
    x, p = [50.0, 10.0, 20.0, -3.0], diag(100.0, 100.0, 900.0, 900.0)
    x1, p1 = K.predict(x, p, 12.0, W)
    x2, p2 = x, p
    for _ in range(120):
        x2, p2 = K.predict(x2, p2, 0.1, W)
    assert all(close(x1[i], x2[i], 1e-8) for i in range(4))
    assert mat_close(p1, p2, 1e-7)


# --- consistency (Monte Carlo, independent trials) -------------------------------------

def simulate_truth_and_filter(seed, steps=60, dt=0.5, sigma_r=10.0):
    """Truth follows exactly the filter's model (continuous white acceleration,
    integrated over dt with the same Q), so NEES ~ chi2(4) is the expectation.
    Returns per-step (nees, nis) with NIS from the accepted measurement."""
    rng = random.Random(seed)
    # Sample process noise with covariance Q(dt) via its Cholesky factor.
    l = K.cholesky(K.process_noise(dt, W))
    x_true = [0.0, 0.0, 15.0, -5.0]
    x, p = [0.0, 0.0, 0.0, 0.0], diag(100.0, 100.0, 900.0, 900.0)
    # Initialise from a first measurement, as the tracker does.
    z0 = [x_true[0] + rng.gauss(0, sigma_r), x_true[1] + rng.gauss(0, sigma_r)]
    x, p, _ = K.update(x, p, z0, R_POS, K.position_model())
    out = []
    for _ in range(steps):
        f = K.transition(dt)
        noise = K.matvec(l, [rng.gauss(0, 1) for _ in range(4)])
        x_true = [v + noise[i] for i, v in enumerate(K.matvec(f, x_true))]
        x, p = K.predict(x, p, dt, W)
        z = [x_true[0] + rng.gauss(0, sigma_r), x_true[1] + rng.gauss(0, sigma_r)]
        inn = K.innovation(x, p, z, R_POS, K.position_model())
        x, p, _ = K.update(x, p, z, R_POS, K.position_model(), precomputed=inn)
        out.append((K.nees(x_true, x, p), inn.nis))
    return out


def chi2_mean_bounds(dof, n_runs):
    """95% interval for the AVERAGE of n_runs independent chi2(dof) variables,
    via the normal approximation to chi2(n*dof)/n. Adequate for n >= 100."""
    mean = dof
    sd = math.sqrt(2.0 * dof / n_runs)
    return mean - 1.96 * sd, mean + 1.96 * sd


def test_nees_and_nis_are_consistent_across_independent_runs():
    """Trials are independent runs evaluated at fixed step indices, not
    temporally correlated frames from one run."""
    n_runs = 200
    runs = [simulate_truth_and_filter(1000 + i) for i in range(n_runs)]
    lo4, hi4 = chi2_mean_bounds(4, n_runs)
    lo2, hi2 = chi2_mean_bounds(2, n_runs)
    for step in (9, 29, 59):
        mean_nees = sum(r[step][0] for r in runs) / n_runs
        mean_nis = sum(r[step][1] for r in runs) / n_runs
        assert lo4 <= mean_nees <= hi4, f"NEES at step {step}: {mean_nees:.2f} not in [{lo4:.2f},{hi4:.2f}]"
        assert lo2 <= mean_nis <= hi2, f"NIS at step {step}: {mean_nis:.2f} not in [{lo2:.2f},{hi2:.2f}]"


def test_ellipse_coverage_is_near_nominal_in_the_matched_model():
    """Model-based 95% region against truth generated by the same model."""
    n_runs, inside = 300, 0
    for i in range(n_runs):
        rng = random.Random(5000 + i)
        l = K.cholesky(K.process_noise(0.5, W))
        x_true = [0.0, 0.0, 15.0, -5.0]
        x, p = [0.0, 0.0, 0.0, 0.0], diag(100.0, 100.0, 900.0, 900.0)
        for _ in range(40):
            noise = K.matvec(l, [rng.gauss(0, 1) for _ in range(4)])
            x_true = [v + noise[j] for j, v in enumerate(K.matvec(K.transition(0.5), x_true))]
            x, p = K.predict(x, p, 0.5, W)
            z = [x_true[0] + rng.gauss(0, 10.0), x_true[1] + rng.gauss(0, 10.0)]
            x, p, _ = K.update(x, p, z, R_POS, K.position_model())
        # Prediction-only gap of 10 s, then test the region.
        x, p = K.predict(x, p, 10.0, W)
        noise_gap = K.matvec(K.cholesky(K.process_noise(10.0, W)), [rng.gauss(0, 1) for _ in range(4)])
        x_true = [v + noise_gap[j] for j, v in enumerate(K.matvec(K.transition(10.0), x_true))]
        d = [x_true[0] - x[0], x_true[1] - x[1]]
        pos = [[p[0][0], p[0][1]], [p[1][0], p[1][1]]]
        l2 = K.cholesky(pos)
        s = K.cholesky_solve(l2, d)
        if d[0] * s[0] + d[1] * s[1] <= K.CHI2_2DOF_95:
            inside += 1
    coverage = inside / n_runs
    # Binomial 95% band around 0.95 for n=300 is about +/- 0.025.
    assert 0.91 <= coverage <= 0.985, coverage
