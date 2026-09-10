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
