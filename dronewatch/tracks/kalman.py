"""Estimation core: a nearly-constant-velocity Kalman filter, done carefully.

This module is pure mathematics. It knows nothing about tracks, sensors,
lifecycles or displays; those policies live in tracker.py. Every function here
is a documented equation with a matching test in tests/test_kalman.py, and the
derivations are written out in docs/SENSOR_LOSS_MATH.md.

State and units
    x = [p_x, p_y, v_x, v_y]^T      metres, metres, m/s, m/s
    Planar, local simulation frame: x east, y north. No altitude state: the
    sensors in this project do not support a vertical velocity estimate, and
    inventing one would be worse than carrying the last measured altitude
    separately (tracker.py does that).

Motion model (continuous white-noise acceleration)
    dp = v dt
    dv = dw,   E[dw dw^T] = W dt,   W = w * I_2   [m^2 / s^3]
    Integrating over an interval of length dt gives, exactly,
        F(dt) = [[I, dt I], [0, I]]
        Q(dt) = [[dt^3/3 W, dt^2/2 W], [dt^2/2 W, dt W]]
    Q comes from  integral_0^dt  Phi(s) G W G^T Phi(s)^T ds  with G = [0; I].
    This is NOT the discrete "constant random acceleration over one interval"
    model, whose Q is sigma_a^2 [[dt^4/4, dt^3/2], [dt^3/2, dt^2]] with
    sigma_a in m/s^2. The two are not interchangeable: only the continuous
    model composes consistently over adjacent intervals (see test
    test_partitioned_prediction_matches_one_step, and the deliberate negative
    test for the discrete model).

Measurement models
    Position:  z = [p_x, p_y] + v,  v ~ N(0, R),  R  in m^2.  H = [I_2, 0].
    Partial position (one axis) is the corresponding row of H and entry of R.
    Bearing:   z = atan2(p_y - s_y, p_x - s_x) + v,  v ~ N(0, sigma_b^2),
               from a sensor at known (s_x, s_y). Linearised at the predicted
               state; innovation wrapped to (-pi, pi]. Singular at the sensor.

Update (linear or linearised)
    nu = z - h(x^-)
    S  = H P^- H^T + R
    K  = P^- H^T S^-1                     (via Cholesky solve, no inverse)
    x^+ = x^- + K nu
    P^+ = (I - K H) P^- (I - K H)^T + K R K^T     (Joseph form)

Matrices are lists of lists; the largest is 4x4 and numpy is not a project
dependency. Numerical hygiene is limited to symmetrisation after predict and
update, which is a floating-point tidy-up, not a model correction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Matrix = List[List[float]]
Vector = List[float]

#: chi-squared quantiles used for gates and regions. Values from the standard
#: table; 2 dof for planar measurements and ellipses.
CHI2_2DOF_95 = 5.991464547107979
CHI2_2DOF_99 = 9.210340371976182
CHI2_1DOF_95 = 3.841458820694124

STATE_DIM = 4


# --- dense linear algebra, small sizes only ---------------------------------

def identity(n: int) -> Matrix:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def zeros(rows: int, cols: int) -> Matrix:
    return [[0.0] * cols for _ in range(rows)]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    inner = len(b)
    return [[sum(a[i][k] * b[k][j] for k in range(inner)) for j in range(len(b[0]))]
            for i in range(len(a))]


def matvec(a: Matrix, v: Vector) -> Vector:
    return [sum(a[i][k] * v[k] for k in range(len(v))) for i in range(len(a))]


def transpose(a: Matrix) -> Matrix:
    return [list(row) for row in zip(*a)]


def add(a: Matrix, b: Matrix) -> Matrix:
    return [[a[i][j] + b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def sub(a: Matrix, b: Matrix) -> Matrix:
    return [[a[i][j] - b[i][j] for j in range(len(a[0]))] for i in range(len(a))]


def scale(a: Matrix, k: float) -> Matrix:
    return [[k * v for v in row] for row in a]


def symmetrize(a: Matrix) -> Matrix:
    """(A + A^T) / 2. Removes floating-point asymmetry; changes nothing else."""
    return [[(a[i][j] + a[j][i]) / 2.0 for j in range(len(a))] for i in range(len(a))]


def is_finite(a: Matrix) -> bool:
    return all(math.isfinite(v) for row in a for v in row)


def is_symmetric(a: Matrix, tol: float = 1e-9) -> bool:
    n = len(a)
    if any(len(row) != n for row in a):
        return False
    return all(abs(a[i][j] - a[j][i]) <= tol * max(1.0, abs(a[i][j])) for i in range(n) for j in range(n))


def cholesky(a: Matrix) -> Optional[Matrix]:
    """Lower-triangular L with L L^T = A, or None if A is not positive definite.

    No jitter is added. A caller that wants to treat a positive semidefinite
    matrix as usable must say so explicitly (see cholesky_psd).
    """
    n = len(a)
    l = zeros(n, n)
    for i in range(n):
        for j in range(i + 1):
            s = a[i][j] - sum(l[i][k] * l[j][k] for k in range(j))
            if i == j:
                if s <= 0.0 or not math.isfinite(s):
                    return None
                l[i][i] = math.sqrt(s)
            else:
                l[i][j] = s / l[j][j]
    return l


#: Relative jitter allowed when checking a covariance for positive
#: semidefiniteness. 1e-9 of the largest diagonal element is far below any
#: physical quantity in this system (a millionth of a millimetre squared at
#: the scales involved) and only absorbs round-off.
PSD_JITTER_REL = 1e-9


def cholesky_psd(a: Matrix) -> Optional[Matrix]:
    """Cholesky of A + eps I, for checking positive semidefiniteness.

    Used for diagnostics on covariances that may be singular by construction
    (for example an exactly known position). Never used for solves.
    """
    n = len(a)
    eps = PSD_JITTER_REL * max(1.0, max(a[i][i] for i in range(n)))
    return cholesky([[a[i][j] + (eps if i == j else 0.0) for j in range(n)] for i in range(n)])


def cholesky_solve(l: Matrix, b: Vector) -> Vector:
    """Solve (L L^T) x = b given the Cholesky factor L."""
    n = len(l)
    y = [0.0] * n
    for i in range(n):
        y[i] = (b[i] - sum(l[i][k] * y[k] for k in range(i))) / l[i][i]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (y[i] - sum(l[k][i] * x[k] for k in range(i + 1, n))) / l[i][i]
    return x


def solve_spd(a: Matrix, b: Matrix) -> Optional[Matrix]:
    """Solve A X = B for symmetric positive-definite A, column by column."""
    l = cholesky(a)
    if l is None:
        return None
    cols = transpose(b)
    return transpose([cholesky_solve(l, col) for col in cols])


# --- motion model -----------------------------------------------------------

def transition(dt: float) -> Matrix:
    """F(dt) for x = [p_x, p_y, v_x, v_y]."""
    return [
        [1.0, 0.0, dt, 0.0],
        [0.0, 1.0, 0.0, dt],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def process_noise(dt: float, w: float) -> Matrix:
    """Q(dt) for continuous white acceleration with PSD W = w I_2, w in m^2/s^3."""
    q3, q2, q1 = w * dt ** 3 / 3.0, w * dt ** 2 / 2.0, w * dt
    return [
        [q3, 0.0, q2, 0.0],
        [0.0, q3, 0.0, q2],
        [q2, 0.0, q1, 0.0],
        [0.0, q2, 0.0, q1],
    ]


def process_noise_discrete(dt: float, sigma_a: float) -> Matrix:
    """The discrete white-noise-acceleration Q, sigma_a in m/s^2.

    Kept only so tests can demonstrate that it is a different model. The
    filter does not use it.
    """
    s2 = sigma_a ** 2
    q4, q3, q2 = s2 * dt ** 4 / 4.0, s2 * dt ** 3 / 2.0, s2 * dt ** 2
    return [
        [q4, 0.0, q3, 0.0],
        [0.0, q4, 0.0, q3],
        [q3, 0.0, q2, 0.0],
        [0.0, q3, 0.0, q2],
    ]


def predict(x: Vector, p: Matrix, dt: float, w: float) -> Tuple[Vector, Matrix]:
    """x^- = F x,  P^- = F P F^T + Q.  dt must be >= 0; dt == 0 is the identity."""
    if dt < 0:
        raise ValueError("prediction runs forward in time only")
    if dt == 0:
        return list(x), [row[:] for row in p]
    f = transition(dt)
    x_minus = matvec(f, x)
    p_minus = add(matmul(matmul(f, p), transpose(f)), process_noise(dt, w))
    return x_minus, symmetrize(p_minus)


# --- measurement models -----------------------------------------------------

@dataclass(frozen=True)
class Linearised:
    """A measurement model evaluated at the predicted state."""
    predicted: Vector          # h(x^-)
    jacobian: Matrix           # H, m x 4
    wrap: bool = False         # innovation is an angle in radians


def position_model(axes: Sequence[int] = (0, 1)):
    """Measures the listed position axes (0 = x, 1 = y). Linear."""
    axes = tuple(axes)
    if not axes or any(a not in (0, 1) for a in axes) or len(set(axes)) != len(axes):
        raise ValueError("position axes must be a non-empty subset of (0, 1)")

    def evaluate(x: Vector) -> Linearised:
        h = [[1.0 if j == a else 0.0 for j in range(STATE_DIM)] for a in axes]
        return Linearised(predicted=[x[a] for a in axes], jacobian=h)
    return evaluate


def bearing_model(sensor_x: float, sensor_y: float, min_range_m: float = 1.0):
    """Bearing from a fixed sensor, radians, mathematical convention.

    h(x) = atan2(p_y - s_y, p_x - s_x)
    H    = [ -d_y / r^2,  d_x / r^2,  0,  0 ]   with d = p - s, r^2 = |d|^2

    Returns None from evaluate() when the predicted position is within
    min_range_m of the sensor: the bearing is undefined there and the
    Jacobian blows up, so the update must be skipped, not attempted.
    """
    def evaluate(x: Vector) -> Optional[Linearised]:
        dx, dy = x[0] - sensor_x, x[1] - sensor_y
        r2 = dx * dx + dy * dy
        if r2 < min_range_m ** 2:
            return None
        return Linearised(predicted=[math.atan2(dy, dx)],
                          jacobian=[[-dy / r2, dx / r2, 0.0, 0.0]], wrap=True)
    return evaluate


def wrap_angle(a: float) -> float:
    """Map to (-pi, pi]."""
    a = (a + math.pi) % (2.0 * math.pi) - math.pi
    return math.pi if a == -math.pi else a


# --- update -----------------------------------------------------------------

class MeasurementRejected(ValueError):
    """The measurement could not be applied; .reason says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_covariance(r: Matrix, dim: int) -> None:
    if len(r) != dim or any(len(row) != dim for row in r):
        raise MeasurementRejected("covariance dimension mismatch")
    if not is_finite(r):
        raise MeasurementRejected("covariance not finite")
    if not is_symmetric(r, 1e-9):
        raise MeasurementRejected("covariance not symmetric")
    if cholesky(r) is None:
        raise MeasurementRejected("covariance not positive definite")


@dataclass(frozen=True)
class Innovation:
    residual: Vector
    covariance: Matrix        # S
    nis: float                # residual^T S^-1 residual
    jacobian: Matrix          # H at the linearisation point


def innovation(x_minus: Vector, p_minus: Matrix, z: Vector, r: Matrix, model) -> Innovation:
    """nu, S and the normalised innovation squared for a candidate measurement.

    Raises MeasurementRejected for invalid input or singular geometry. Does not
    modify the state; association uses this before deciding anything.
    """
    if any(not math.isfinite(v) for v in z):
        raise MeasurementRejected("measurement not finite")
    lin = model(x_minus)
    if lin is None:
        raise MeasurementRejected("measurement geometry singular")
    m = len(lin.predicted)
    if len(z) != m:
        raise MeasurementRejected("measurement dimension mismatch")
    validate_covariance(r, m)
    h = lin.jacobian
    nu = [z[i] - lin.predicted[i] for i in range(m)]
    if lin.wrap:
        nu = [wrap_angle(v) for v in nu]
    s = add(matmul(matmul(h, p_minus), transpose(h)), r)
    s = symmetrize(s)
    l = cholesky(s)
    if l is None:
        raise MeasurementRejected("innovation covariance not positive definite")
    s_inv_nu = cholesky_solve(l, nu)
    nis = sum(nu[i] * s_inv_nu[i] for i in range(m))
    return Innovation(residual=nu, covariance=s, nis=nis, jacobian=h)


def update(x_minus: Vector, p_minus: Matrix, z: Vector, r: Matrix, model,
           precomputed: Optional[Innovation] = None) -> Tuple[Vector, Matrix, Innovation]:
    """Joseph-form measurement update. Returns (x^+, P^+, innovation)."""
    inn = precomputed or innovation(x_minus, p_minus, z, r, model)
    h, s, nu = inn.jacobian, inn.covariance, inn.residual
    n, m = len(x_minus), len(nu)
    # K = P H^T S^-1  <=>  S K^T = H P   (S symmetric). Solve, do not invert.
    k_t = solve_spd(s, matmul(h, p_minus))
    if k_t is None:
        raise MeasurementRejected("innovation covariance not positive definite")
    k = transpose(k_t)                                         # n x m
    x_plus = [x_minus[i] + sum(k[i][j] * nu[j] for j in range(m)) for i in range(n)]
    i_kh = sub(identity(n), matmul(k, h))
    p_plus = add(matmul(matmul(i_kh, p_minus), transpose(i_kh)),
                 matmul(matmul(k, r), transpose(k)))
    p_plus = symmetrize(p_plus)
    if not is_finite(p_plus):
        raise MeasurementRejected("update produced non-finite covariance")
    return x_plus, p_plus, inn


# --- derived quantities ------------------------------------------------------

@dataclass(frozen=True)
class Ellipse:
    """Planar confidence region: semi-axes in metres, orientation in radians
    (mathematical convention, from +x toward +y) of the major axis."""
    semi_major_m: float
    semi_minor_m: float
    angle_rad: float


def position_ellipse(p: Matrix, probability: float = 0.95) -> Ellipse:
    """Region {d : d^T P_pos^-1 d <= c} with c = chi2_2(probability).

    For a Gaussian this contains the true position with the stated probability
    under the model. It is a model-based statement; empirical coverage is a
    separate measurement (see experiments/sensor_loss.py). Note that it is not
    the box obtained by applying 1.96 sigma to each axis independently.
    """
    if probability != 0.95:
        raise ValueError("only the 95% quantile is tabulated here")
    a, b, c = p[0][0], p[0][1], p[1][1]
    mean, diff = (a + c) / 2.0, (a - c) / 2.0
    disc = math.sqrt(max(0.0, diff * diff + b * b))
    lam1, lam2 = max(0.0, mean + disc), max(0.0, mean - disc)
    angle = 0.5 * math.atan2(2.0 * b, a - c)
    return Ellipse(math.sqrt(CHI2_2DOF_95 * lam1), math.sqrt(CHI2_2DOF_95 * lam2), angle)


def nees(x_true: Vector, x_est: Vector, p: Matrix) -> Optional[float]:
    """(x_true - x_est)^T P^-1 (x_true - x_est). None if P is not PD."""
    l = cholesky(p)
    if l is None:
        return None
    e = [x_true[i] - x_est[i] for i in range(len(x_true))]
    p_inv_e = cholesky_solve(l, e)
    return sum(e[i] * p_inv_e[i] for i in range(len(e)))


def position_variance_after_gap(p: Matrix, dt: float, w: float) -> Tuple[float, float]:
    """Analytic diagonal position variances after a prediction-only gap.

    P_xx(dt) = P_xx + 2 dt P_xv + dt^2 P_vv + w dt^3 / 3, and likewise for y.
    Used by tests as an independent check on predict(); the cross terms are
    what make the growth faster than the process-noise term alone.
    """
    pxx = p[0][0] + 2 * dt * p[0][2] + dt * dt * p[2][2] + w * dt ** 3 / 3.0
    pyy = p[1][1] + 2 * dt * p[1][3] + dt * dt * p[3][3] + w * dt ** 3 / 3.0
    return pxx, pyy
