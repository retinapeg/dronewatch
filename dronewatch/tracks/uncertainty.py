"""Where is a lost contact now? Stochastic containment for a dropped track.

When a contact drops off radar the filter stops being told anything. What it
still has is a stochastic model of how the target moves, so the question
"where is it now?" has a distribution as its answer, not a point.

THE PROCESS
The tracker's motion model is an Itô SDE — nearly-constant velocity driven by
white acceleration:

    dp = v dt
    dv = dW,        E[dW dWᵀ] = W dt,      W = w I₂     [m²/s³]

Integrating from the last update over an elapsed time τ gives, exactly,

    p(τ) = p₀ + v₀τ + ∫₀^τ (τ − s) dW(s)
    v(τ) = v₀      + ∫₀^τ            dW(s)

Both integrals are Itô integrals of deterministic integrands, so the pair is
jointly Gaussian and the covariance is the Q(τ) already derived in kalman.py.
That is worth stating plainly: for THIS model the exact answer is available in
closed form, and Monte Carlo is not needed to get the containment radius.

SO WHY SIMULATE
Two reasons, and both are honest ones:

  1. As a check. The empirical containment of sampled paths must match the
     analytic radius. If it does not, one of the two is wrong. `validate()`
     runs exactly that comparison.
  2. Because a cloud of sampled PATHS is the thing an operator can actually
     read. A covariance ellipse says how big the uncertainty is; sample paths
     say what the target might be doing — which way it might have turned, how
     far it could have got. The ellipse is the summary, the paths are the
     intuition.

For a manoeuvring target the Gaussian is an approximation (a real quadcopter
can turn harder than white acceleration implies), so the sampler also supports
a bounded-speed variant that rejects physically implausible draws.

WHAT THIS IS NOT
Nothing here is fire control. `cue_feasibility` answers one narrow decision-
support question — whether a track is currently localised well enough for an
effector to be *cued at all* — and its main practical output is the negative:
telling an operator when a track has decayed past the point where any
engagement decision could be based on it. That is a safety property.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from . import kalman as K


# --- containment ------------------------------------------------------------

#: chi-squared quantiles, 2 dof, for planar containment regions.
CHI2_2DOF = {0.50: 1.3862943611, 0.90: 4.6051701860,
             0.95: 5.9914645471, 0.99: 9.2103403720}


def containment_radius(cov: K.Matrix, probability: float = 0.95) -> float:
    """Radius of the smallest CIRCLE containing the target with `probability`.

    The 95% region of a Gaussian is an ellipse; an operator wants one number.
    The conservative honest scalar is the ellipse's MAJOR semi-axis — the
    circle of that radius contains the ellipse, so it contains at least the
    stated probability. Reporting the minor axis, or an average, would
    understate the search area.
    """
    if probability not in CHI2_2DOF:
        raise ValueError(f"no tabulated quantile for {probability}")
    a, b, c = cov[0][0], cov[0][1], cov[1][1]
    mean, diff = (a + c) / 2.0, (a - c) / 2.0
    lam_max = mean + math.sqrt(max(0.0, diff * diff + b * b))
    return math.sqrt(CHI2_2DOF[probability] * max(0.0, lam_max))


def analytic_state(x0: Sequence[float], p0: K.Matrix, tau: float, w: float):
    """Exact mean and covariance τ seconds after the last measurement."""
    return K.predict(list(x0), [row[:] for row in p0], max(0.0, tau), w)


# --- Monte Carlo ------------------------------------------------------------

@dataclass(frozen=True)
class PathEnsemble:
    """Sampled realisations of where the contact could have gone."""
    times: List[float]                      # seconds since loss
    paths: List[List[Tuple[float, float]]]  # [path][step] -> (x, y)
    endpoints: List[Tuple[float, float]]
    #: Empirical fraction of endpoints inside the analytic 95% radius.
    empirical_containment: float
    analytic_radius_m: float
    empirical_radius_m: float               # 95th percentile of endpoint distance
    n_paths: int
    rejected: int                           # draws refused by the speed bound
    seed: int


def sample_paths(
    x0: Sequence[float],
    p0: K.Matrix,
    tau: float,
    w: float,
    *,
    n_paths: int = 400,
    steps: int = 24,
    seed: int = 0,
    max_speed_m_s: Optional[float] = None,
) -> PathEnsemble:
    """Simulate the SDE forward from the last known state.

    The initial state is itself uncertain, so each path starts from a draw
    of N(x0, p0) rather than from the mean — otherwise the ensemble would
    understate the spread by exactly the filter's own uncertainty at loss.

    Increments use the Euler–Maruyama scheme, which is exact here: the drift
    is linear and the diffusion is constant, so the discretisation introduces
    no error beyond floating point at these step sizes.

    `max_speed_m_s` optionally rejects draws that would require the target to
    exceed a plausible airspeed. White acceleration is unbounded, so without
    this a small fraction of paths are physically silly.
    """
    rng = random.Random(seed)
    tau = max(0.0, tau)
    steps = max(1, steps)
    dt = tau / steps
    times = [round(i * dt, 3) for i in range(steps + 1)]

    # Cholesky of the initial covariance, so paths start correctly dispersed.
    l0 = K.cholesky_psd(p0)

    sigma_step = math.sqrt(w * dt) if dt > 0 else 0.0
    paths: List[List[Tuple[float, float]]] = []
    endpoints: List[Tuple[float, float]] = []
    rejected = 0

    attempts = 0
    while len(paths) < n_paths and attempts < n_paths * 12:
        attempts += 1
        if l0 is not None:
            noise = K.matvec(l0, [rng.gauss(0.0, 1.0) for _ in range(4)])
            state = [x0[i] + noise[i] for i in range(4)]
        else:
            state = list(x0)

        pts: List[Tuple[float, float]] = [(state[0], state[1])]
        ok = True
        for _ in range(steps):
            # Position first, using the velocity at the start of the step.
            state[0] += state[2] * dt
            state[1] += state[3] * dt
            # Then the velocity increment: the Itô term.
            state[2] += rng.gauss(0.0, sigma_step)
            state[3] += rng.gauss(0.0, sigma_step)
            if max_speed_m_s is not None and math.hypot(state[2], state[3]) > max_speed_m_s:
                ok = False
                break
            pts.append((state[0], state[1]))

        if not ok:
            rejected += 1
            continue
        paths.append(pts)
        endpoints.append(pts[-1])

    # Analytic reference, and the empirical check against it.
    mean, cov = analytic_state(x0, p0, tau, w)
    r95 = containment_radius([[cov[0][0], cov[0][1]], [cov[1][0], cov[1][1]]], 0.95)
    if endpoints:
        dists = sorted(math.hypot(px - mean[0], py - mean[1]) for px, py in endpoints)
        inside = sum(1 for d in dists if d <= r95) / len(dists)
        idx = max(0, min(len(dists) - 1, int(round(0.95 * (len(dists) - 1)))))
        emp_r = dists[idx]
    else:
        inside, emp_r = 0.0, 0.0

    return PathEnsemble(
        times=times, paths=paths, endpoints=endpoints,
        empirical_containment=round(inside, 4),
        analytic_radius_m=round(r95, 2),
        empirical_radius_m=round(emp_r, 2),
        n_paths=len(paths), rejected=rejected, seed=seed,
    )


def validate(w: float = 4.0, tau: float = 20.0, n_paths: int = 4000, seed: int = 1):
    """Does the simulation agree with the closed form?

    Returns the two radii and the empirical containment. For an unbounded
    (max_speed=None) ensemble these must agree, because the model is
    linear-Gaussian and the analytic answer is exact.
    """
    x0 = [0.0, 0.0, 18.0, -6.0]
    p0 = [[100.0, 0, 20.0, 0], [0, 100.0, 0, 20.0],
          [20.0, 0, 64.0, 0], [0, 20.0, 0, 64.0]]
    ens = sample_paths(x0, p0, tau, w, n_paths=n_paths, steps=40, seed=seed)
    return {
        "analytic_radius_m": ens.analytic_radius_m,
        "empirical_radius_m": ens.empirical_radius_m,
        "empirical_containment": ens.empirical_containment,
        "ratio": round(ens.empirical_radius_m / max(ens.analytic_radius_m, 1e-9), 4),
    }


# --- effector cue feasibility (decision support, NOT fire control) ----------

@dataclass(frozen=True)
class CueAssessment:
    """Whether a track is localised well enough to cue an effector at all.

    This deliberately produces a NEGATIVE result as its main output. A
    directed-energy effector must place its own fine-tracking sensor onto the
    target; that sensor has a finite acquisition basket. Once the track's
    containment radius exceeds what the basket subtends at the target's range,
    the track cannot be handed over, and continuing to treat it as actionable
    would be unsound.
    """
    feasible: bool
    reason: str
    containment_radius_m: float
    #: What the effector's acquisition basket subtends at this range, in metres.
    basket_at_range_m: float
    range_m: float
    #: Ratio > 1 means the uncertainty is larger than the basket.
    excess: float
    seconds_since_measurement: float
    #: Seconds until containment outgrows the basket. None if already exceeded.
    seconds_until_infeasible: Optional[float]


#: Assumptions, stated so they can be argued with. These are ILLUSTRATIVE
#: figures for a generic ground-based directed-energy effector, not the
#: specification of any particular system.
#:
#: The relevant angle is the effector's COARSE ACQUISITION field of view — the
#: basket its own electro-optical tracker must find the target in before it can
#: begin fine tracking. That is degrees, not the microradians of the beam
#: itself; cueing does not require beam-level accuracy, only that the handover
#: puts the target inside the acquisition FOV. 1.5 degrees half-angle is a
#: deliberately generous figure for such a sensor.
DEFAULT_ACQUISITION_BASKET_MRAD = 26.0   # ~1.5 degrees half-angle
DEFAULT_MAX_EFFECTIVE_RANGE_M = 3000.0


def cue_feasibility(
    cov: K.Matrix,
    range_m: float,
    seconds_since_measurement: float,
    *,
    basket_mrad: float = DEFAULT_ACQUISITION_BASKET_MRAD,
    max_range_m: float = DEFAULT_MAX_EFFECTIVE_RANGE_M,
    growth_probe: Optional[Tuple[Sequence[float], K.Matrix, float]] = None,
) -> CueAssessment:
    """Assess handover feasibility from track quality alone.

    `growth_probe` is (x0, p0, w) and, when given, is used to find how long
    the track remains cueable by propagating forward until the basket is
    exceeded — the operationally useful number during a dropout.
    """
    r = containment_radius([[cov[0][0], cov[0][1]], [cov[1][0], cov[1][1]]], 0.95)
    basket = math.tan(basket_mrad / 1000.0) * max(range_m, 1.0)
    excess = r / basket if basket > 0 else float("inf")

    if range_m > max_range_m:
        feasible, reason = False, f"Beyond illustrative effective range ({max_range_m:.0f} m)"
    elif r <= basket:
        feasible, reason = True, "Track localised within acquisition basket"
    else:
        feasible = False
        reason = (f"Position uncertainty {r:.0f} m exceeds the {basket:.0f} m "
                  f"acquisition basket at this range")

    # How much longer does it stay cueable?
    until = None
    if growth_probe is not None and feasible:
        x0, p0, w = growth_probe
        lo, hi = 0.0, 120.0
        for _ in range(24):                      # bisection on containment
            mid = (lo + hi) / 2
            _, cov_mid = analytic_state(x0, p0, mid, w)
            r_mid = containment_radius(
                [[cov_mid[0][0], cov_mid[0][1]], [cov_mid[1][0], cov_mid[1][1]]], 0.95)
            if r_mid <= basket:
                lo = mid
            else:
                hi = mid
        until = round(lo, 1)

    return CueAssessment(
        feasible=feasible, reason=reason,
        containment_radius_m=round(r, 1),
        basket_at_range_m=round(basket, 1),
        range_m=round(range_m, 1),
        excess=round(excess, 2),
        seconds_since_measurement=round(seconds_since_measurement, 1),
        seconds_until_infeasible=until,
    )


# --- behaviour-adaptive containment -----------------------------------------
#
# Constant velocity plus white acceleration treats every contact the same. A
# drone that has been holding a steady turn for the last ten seconds is far
# more likely to keep turning than to fly straight, and one that has been
# jinking should be given a wider region than one that has been cruising.
# So: read the recent track, estimate what it was DOING, and let that shape
# the region.

@dataclass(frozen=True)
class Behaviour:
    """What the recent track history says the contact was doing."""
    speed_m_s: float
    heading_rad: float               # mathematical convention
    turn_rate_rad_s: float           # +ve anticlockwise; 0 = straight
    #: How much the contact has been manoeuvring, as an acceleration sigma.
    manoeuvre_sigma: float
    speed_sigma: float
    n_points: int
    fit_quality: str                 # 'good' | 'thin' | 'none'


def behaviour_from_history(history: Sequence[Tuple[float, float, float]]) -> Behaviour:
    """Estimate speed, heading, turn rate and manoeuvre level from (t, x, y).

    Uses the last few seconds only; older behaviour is not predictive of the
    next few. Turn rate is the least-squares slope of heading against time,
    which is robust to a little position noise at these cadences.
    """
    pts = [p for p in history if p is not None]
    if len(pts) < 3:
        return Behaviour(0.0, 0.0, 0.0, 2.0, 0.0, len(pts), "none")
    pts = pts[-12:]                                   # ~6 s at 2 Hz
    vs, hs, ts = [], [], []
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:]):
        dt = t1 - t0
        if dt <= 1e-6:
            continue
        vx, vy = (x1 - x0) / dt, (y1 - y0) / dt
        vs.append(math.hypot(vx, vy))
        hs.append(math.atan2(vy, vx))
        ts.append((t0 + t1) / 2)
    if len(hs) < 2:
        return Behaviour(0.0, 0.0, 0.0, 2.0, 0.0, len(pts), "none")

    # Unwrap headings so a turn through ±pi does not look like a reversal.
    unwrapped = [hs[0]]
    for h in hs[1:]:
        d = h - unwrapped[-1]
        while d > math.pi: d -= 2 * math.pi
        while d < -math.pi: d += 2 * math.pi
        unwrapped.append(unwrapped[-1] + d)

    n = len(ts)
    tm, hm = sum(ts) / n, sum(unwrapped) / n
    sxx = sum((t - tm) ** 2 for t in ts)
    turn = sum((t - tm) * (h - hm) for t, h in zip(ts, unwrapped)) / sxx if sxx > 1e-9 else 0.0

    speed = sum(vs) / len(vs)
    speed_sigma = math.sqrt(sum((v - speed) ** 2 for v in vs) / max(1, len(vs) - 1))
    # Residual heading change not explained by the constant turn, as lateral
    # acceleration, plus along-track speed change: the manoeuvre level.
    resid = [h - (hm + turn * (t - tm)) for t, h in zip(ts, unwrapped)]
    lat_sigma = speed * math.sqrt(sum(r * r for r in resid) / max(1, len(resid) - 1)) / max(0.25, (ts[-1] - ts[0]) / max(1, n - 1))
    man = math.sqrt(lat_sigma ** 2 + speed_sigma ** 2)
    # Clamp to a physically sane band. Positions from a filtered track carry
    # the filter's own jitter, which the lateral-acceleration estimate
    # amplifies; above ~3 m/s^1.5 the draws are mostly rejected by the
    # airspeed bound and the ensemble stops meaning anything.
    return Behaviour(
        speed_m_s=speed, heading_rad=unwrapped[-1], turn_rate_rad_s=turn,
        manoeuvre_sigma=max(0.8, min(3.0, man)), speed_sigma=min(speed_sigma, 4.0),
        n_points=len(pts), fit_quality="good" if len(pts) >= 6 else "thin",
    )


@dataclass(frozen=True)
class Regime:
    name: str
    weight: float
    turn_rate_rad_s: float
    accel_sigma: float


def regimes_for(b: Behaviour) -> List[Regime]:
    """A small multiple-model mixture, weighted by what the contact was doing.

    A contact in a steady turn gets most of its mass on 'continue the turn';
    one flying straight gets most on 'straight' with symmetric turn branches.
    The weights are stated here rather than fitted, so they can be argued with.
    """
    steady = abs(b.turn_rate_rad_s) > 0.02              # > ~1.1 deg/s
    w_turn = b.manoeuvre_sigma
    if b.fit_quality == "none":
        return [Regime("straight", 0.6, 0.0, 2.5),
                Regime("turn-left", 0.2, +0.06, 3.0),
                Regime("turn-right", 0.2, -0.06, 3.0)]
    if steady:
        s = 1.0 if b.turn_rate_rad_s > 0 else -1.0
        return [Regime("continue-turn", 0.55, b.turn_rate_rad_s, w_turn),
                Regime("tighten-turn", 0.15, b.turn_rate_rad_s * 1.8, w_turn * 1.3),
                Regime("roll-out", 0.20, 0.0, w_turn),
                Regime("reverse-turn", 0.10, -s * abs(b.turn_rate_rad_s), w_turn * 1.3)]
    return [Regime("straight", 0.60, 0.0, w_turn),
            Regime("turn-left", 0.18, +0.07, w_turn * 1.2),
            Regime("turn-right", 0.18, -0.07, w_turn * 1.2),
            Regime("decelerate", 0.04, 0.0, w_turn * 1.5)]


@dataclass(frozen=True)
class AdaptiveEnsemble:
    times: List[float]
    paths: List[List[Tuple[float, float]]]
    regimes: List[str]                       # regime per path
    behaviour: Behaviour
    regime_weights: List[Tuple[str, float]]
    #: Convex hull (metres) of the innermost 95% of endpoints: the MORPHED region.
    hull95: List[Tuple[float, float]]
    #: For comparison: the isotropic analytic R95 of the plain CV model.
    cv_radius_m: float
    empirical_radius_m: float
    n_paths: int
    rejected: int
    seed: int


def _hull(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Andrew's monotone chain. Returns the hull anticlockwise."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return list(pts)
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def sample_paths_adaptive(
    x0: Sequence[float],
    p0: K.Matrix,
    tau: float,
    history: Sequence[Tuple[float, float, float]],
    *,
    n_paths: int = 300,
    steps: int = 24,
    seed: int = 0,
    max_speed_m_s: float = 45.0,
    min_speed_m_s: float = 3.0,
    w_cv_reference: float = 4.0,
) -> AdaptiveEnsemble:
    """Monte Carlo over a behaviour-weighted mixture of manoeuvre regimes.

    Each path draws a regime, then integrates a coordinated-turn model with
    that regime's turn rate, driven by white acceleration at that regime's
    level. Speed is bounded to a plausible envelope. The result is a cloud
    whose shape follows the contact's recent behaviour — curving along a
    turn, stretching along a straight run — rather than an isotropic circle.

    This is deliberately a simulation rather than a closed form: the mixture
    of turn rates is not Gaussian, so there is no exact ellipse to quote.
    """
    rng = random.Random(seed)
    b = behaviour_from_history(history)
    regs = regimes_for(b)
    cum, acc = [], 0.0
    for r in regs:
        acc += r.weight
        cum.append(acc)

    tau = max(0.0, tau)
    steps = max(1, steps)
    dt = tau / steps
    times = [round(i * dt, 3) for i in range(steps + 1)]
    l0 = K.cholesky_psd(p0)

    # A good fit over ~12 points beats a single filter velocity for the initial
    # heading and speed: the filter's velocity is the same measurements seen
    # through a constant-velocity assumption, so during a turn it lags. Fall
    # back to the filter only when the history is too thin to fit.
    v_filter = math.hypot(x0[2], x0[3])
    use_b = b.fit_quality == "good" or (b.fit_quality == "thin" and v_filter < 2.0)

    paths, regimes, endpoints = [], [], []
    rejected, attempts = 0, 0
    while len(paths) < n_paths and attempts < n_paths * 12:
        attempts += 1
        u = rng.random() * cum[-1]
        reg = next(r for r, c in zip(regs, cum) if u <= c)

        noise = K.matvec(l0, [rng.gauss(0, 1) for _ in range(4)]) if l0 else [0, 0, 0, 0]
        x, y = x0[0] + noise[0], x0[1] + noise[1]
        if use_b:
            spd = max(min_speed_m_s, b.speed_m_s + rng.gauss(0, max(0.5, b.speed_sigma)))
            hdg = b.heading_rad + rng.gauss(0, 0.06)
        else:
            vx, vy = x0[2] + noise[2], x0[3] + noise[3]
            spd, hdg = max(min_speed_m_s, math.hypot(vx, vy)), math.atan2(vy, vx)

        sig = reg.accel_sigma * math.sqrt(dt)
        pts = [(x, y)]
        ok = True
        for _ in range(steps):
            hdg += reg.turn_rate_rad_s * dt
            x += spd * math.cos(hdg) * dt
            y += spd * math.sin(hdg) * dt
            # White acceleration: along-track on speed, cross-track on heading.
            spd += rng.gauss(0, sig)
            hdg += rng.gauss(0, sig) / max(spd, 1.0)
            if spd > max_speed_m_s or spd < 0:
                ok = False
                break
            spd = max(min_speed_m_s, spd)
            pts.append((x, y))
        if not ok:
            rejected += 1
            continue
        paths.append(pts)
        regimes.append(reg.name)
        endpoints.append(pts[-1])

    # Region: hull of the 95% of endpoints nearest their own centroid.
    if endpoints:
        cx = sum(p[0] for p in endpoints) / len(endpoints)
        cy = sum(p[1] for p in endpoints) / len(endpoints)
        ranked = sorted(endpoints, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
        keep = ranked[: max(3, int(round(0.95 * len(ranked))))]
        hull = _hull(keep)
        emp_r = math.hypot(keep[-1][0] - cx, keep[-1][1] - cy)
    else:
        hull, emp_r = [], 0.0

    _, cov = analytic_state(x0, p0, tau, w_cv_reference)
    cv_r = containment_radius([[cov[0][0], cov[0][1]], [cov[1][0], cov[1][1]]], 0.95)

    return AdaptiveEnsemble(
        times=times, paths=paths, regimes=regimes, behaviour=b,
        regime_weights=[(r.name, r.weight) for r in regs],
        hull95=[(round(px, 1), round(py, 1)) for px, py in hull],
        cv_radius_m=round(cv_r, 1), empirical_radius_m=round(emp_r, 1),
        n_paths=len(paths), rejected=rejected, seed=seed,
    )
