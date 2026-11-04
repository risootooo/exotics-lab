"""Vectorised Monte Carlo engine for path-dependent options (GBM).

Design choices that matter, all deliberate:

  * **Antithetic variates everywhere.** Normals are generated in pairs
    (z, -z) and standard errors are computed on *pair means*, so the
    reported SE reflects the variance reduction actually achieved.
  * **Control variates.** Each exotic is priced against a control whose
    exact price is known (the vanilla European on the same paths for
    barriers/lookbacks, the Kemna-Vorst geometric Asian for the
    arithmetic Asian), with the regression coefficient beta estimated
    from the sample. Prices are quoted with an SE *after* the control,
    never before.
  * **Brownian-bridge barrier correction.** A barrier monitored only at
    grid dates is systematically overpriced (crossings between dates are
    missed). For each step (S_i, S_{i+1}) the exact conditional
    probability that a Brownian bridge touched an upper barrier H is
        p = exp( -2 ln(H/S_i) ln(H/S_{i+1}) / (sigma^2 dt) ),
    and the payoff is weighted by the product of survival probabilities
    prod(1 - p_i). This is the Broadie-Glasserman-Kou correction; it
    makes a coarse grid behave like continuous monitoring.
    ``monitoring='discrete'`` switches it off for comparison.
  * **Chunked simulation.** Paths are generated in blocks of antithetic
    pairs, so a 1M-path x 250-step run never materialises more than one
    block (default 25k pairs) at a time.
  * Every pricer returns ``MCResult(price, se)`` -- a price without its
    error bar is treated as a bug in this repo.

Fixing convention: path-dependent features are observed on the
simulation grid (steps 1..n_steps, inception excluded) -- for Asians,
lookbacks and cliquets that grid *is* the contractual fixing schedule.
Barriers are the exception: real contracts monitor continuously, hence
the bridge correction above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .bs import bs_price, asian_geometric_price

__all__ = ["MCResult", "simulate_paths", "european", "asian", "barrier",
           "lookback", "cliquet"]

_PAIR_CHUNK = 25_000


@dataclass
class MCResult:
    price: float
    se: float

    def __repr__(self):  # pragma: no cover - cosmetic
        return f"MCResult(price={self.price:.4f}, se={self.se:.4f})"


def simulate_paths(rng: np.random.Generator, S, T, r, q, sigma,
                   n_steps, n_pairs):
    """One chunk of antithetic GBM paths, shape (2*n_pairs, n_steps+1).

    Rows [0, n_pairs) use normals z; rows [n_pairs, 2*n_pairs) use -z.
    """
    z = rng.standard_normal((n_pairs, n_steps))
    z = np.concatenate([z, -z], axis=0)
    dt = T / n_steps
    drift = (r - q - 0.5 * sigma ** 2) * dt
    diff = sigma * np.sqrt(dt)
    paths = np.empty((2 * n_pairs, n_steps + 1), dtype=float)
    paths[:, 0] = S
    paths[:, 1:] = np.exp(np.log(S) + np.cumsum(drift + diff * z, axis=1))
    return paths


def _run(payoff_fn: Callable, S, T, r, q, sigma, n_steps, n_paths, seed,
         control_exact: Optional[float] = None) -> MCResult:
    """Aggregate a payoff function over antithetic chunks.

    payoff_fn(paths) -> (payoff, control_payoff_or_None), both
    *undiscounted* per-path vectors. ``control_exact`` is the known
    *price* (discounted) of the control. Pair means drive the SE.
    """
    if n_paths < 2:
        raise ValueError("n_paths must be >= 2")
    rng = np.random.default_rng(seed)
    disc = np.exp(-r * T)
    n_pairs_total = n_paths // 2
    sum_y = sum_yy = sum_c = sum_cc = sum_yc = 0.0
    done = 0
    while done < n_pairs_total:
        n_pairs = min(_PAIR_CHUNK, n_pairs_total - done)
        paths = simulate_paths(rng, S, T, r, q, sigma, n_steps, n_pairs)
        y, c = payoff_fn(paths)
        ym = 0.5 * (y[:n_pairs] + y[n_pairs:])
        sum_y += ym.sum()
        sum_yy += (ym * ym).sum()
        if c is not None:
            cm = 0.5 * (c[:n_pairs] + c[n_pairs:])
            sum_c += cm.sum()
            sum_cc += (cm * cm).sum()
            sum_yc += (ym * cm).sum()
        done += n_pairs
    n = float(n_pairs_total)
    mean_y = sum_y / n
    var_y = max(sum_yy / n - mean_y ** 2, 0.0) * n / (n - 1.0)
    if c is None or control_exact is None:
        return MCResult(disc * mean_y, disc * np.sqrt(var_y / n))
    mean_c = sum_c / n
    var_c = max(sum_cc / n - mean_c ** 2, 0.0) * n / (n - 1.0)
    cov = (sum_yc / n - mean_y * mean_c) * n / (n - 1.0)
    beta = cov / var_c if var_c > 0 else 0.0
    # Adjusted pair value in discounted space; its dispersion is not
    # recoverable from the moments alone, so recompute the SE from the
    # residual variance identity Var(y - b c) = Var(y) - 2b Cov + b^2 Var(c).
    var_adj = max(var_y - 2.0 * beta * cov + beta ** 2 * var_c, 0.0)
    price = disc * mean_y - beta * (disc * mean_c - control_exact)
    return MCResult(price, disc * np.sqrt(var_adj / n))


def _vanilla_payoff(paths, K, kind):
    st = paths[:, -1]
    if kind == "CE":
        return np.maximum(st - K, 0.0)
    return np.maximum(K - st, 0.0)


def european(S, K, T, r, q, sigma, kind="CE", n_paths=200_000, seed=42):
    """Plain antithetic MC European -- the anchor every other pricer is
    checked against (Black-Scholes itself is the exact control)."""
    return _run(lambda p: (_vanilla_payoff(p, K, kind), None),
                S, T, r, q, sigma, 1, n_paths, seed)


def asian(S, K, T, r, q, sigma, kind="CE", average="arithmetic",
          n_fixings=63, n_paths=200_000, seed=42, control=True):
    """Average-price Asian. Fixings at steps 1..n_fixings (expiry incl.).

    Arithmetic: control variate = the geometric Asian on the same paths
    (exact price by Kemna-Vorst). Geometric: priced directly, no control
    needed (it *is* the control), so its MC can be validated against the
    closed form in the tests.
    """
    if average not in ("arithmetic", "geometric"):
        raise ValueError("average must be 'arithmetic' or 'geometric'")

    def payoff(paths):
        fixings = paths[:, 1:]
        if average == "geometric":
            avg = np.exp(np.log(fixings).mean(axis=1))
            y = (np.maximum(avg - K, 0.0) if kind == "CE"
                 else np.maximum(K - avg, 0.0))
            return y, None
        avg_a = fixings.mean(axis=1)
        y = (np.maximum(avg_a - K, 0.0) if kind == "CE"
             else np.maximum(K - avg_a, 0.0))
        if not control:
            return y, None
        avg_g = np.exp(np.log(fixings).mean(axis=1))
        c = (np.maximum(avg_g - K, 0.0) if kind == "CE"
             else np.maximum(K - avg_g, 0.0))
        return y, c

    exact = (asian_geometric_price(S, K, T, r, q, sigma, kind, n_fixings)
             if (average == "arithmetic" and control) else None)
    return _run(payoff, S, T, r, q, sigma, n_fixings, n_paths, seed,
                control_exact=exact)


def _bridge_survival(paths, H, sigma, dt, side):
    """Per-path survival weight under continuous monitoring (BGK).

    side='up': barrier above spot, survival requires S < H throughout.
    For a step with both endpoints on the survival side, the bridge
    crossing probability is exp(-2 a b / (sigma^2 dt)) with a, b the
    log-distances of the endpoints to the barrier; an endpoint beyond
    the barrier forces probability 1.
    """
    s_i = paths[:, :-1]
    s_j = paths[:, 1:]
    if side == "up":
        a = np.log(H / np.maximum(s_i, 1e-12))
        b = np.log(H / np.maximum(s_j, 1e-12))
    else:
        a = np.log(np.maximum(s_i, 1e-12) / H)
        b = np.log(np.maximum(s_j, 1e-12) / H)
    crossed_endpoint = (a <= 0.0) | (b <= 0.0)
    expo = -2.0 * np.maximum(a, 0.0) * np.maximum(b, 0.0) / (sigma ** 2 * dt)
    p_cross = np.where(crossed_endpoint, 1.0, np.exp(np.maximum(expo, -700.0)))
    return np.prod(1.0 - p_cross, axis=1)


def barrier(S, K, T, H, r, q, sigma, kind="CE", flavour="up-and-out",
            n_steps=126, n_paths=200_000, seed=42,
            monitoring="continuous", control=True):
    """Single-barrier knock-out (no rebate).

    flavour: 'up-and-out' / 'down-and-out' (call with up, put with down
    are the traded combinations; the engine does not hard-restrict it).
    monitoring='continuous' applies the Brownian-bridge correction;
    'discrete' knocks out only on grid dates.
    """
    side = "up" if flavour.startswith("up") else "down"
    dt = T / n_steps

    def payoff(paths):
        vanilla = _vanilla_payoff(paths, K, kind)
        if monitoring == "continuous":
            w = _bridge_survival(paths, H, sigma, dt, side)
        else:
            if side == "up":
                alive = (paths[:, 1:] < H).all(axis=1)
            else:
                alive = (paths[:, 1:] > H).all(axis=1)
            w = alive.astype(float)
        return vanilla * w, (vanilla if control else None)

    exact = bs_price(S, K, T, r, q, sigma, kind) if control else None
    return _run(payoff, S, T, r, q, sigma, n_steps, n_paths, seed,
                control_exact=exact)


def lookback(S, T, r, q, sigma, kind="CE", n_steps=126,
             n_paths=200_000, seed=42, control=True):
    """Floating-strike lookback: call pays S_T - min(S), put pays
    max(S) - S_T, extrema over the fixing grid 1..n_steps plus inception
    (inception is a contractual fixing for lookbacks). Control = the
    vanilla option struck at S on the same paths."""
    def payoff(paths):
        st = paths[:, -1]
        if kind == "CE":
            y = st - paths.min(axis=1)
            c = np.maximum(st - S, 0.0)
        else:
            y = paths.max(axis=1) - st
            c = np.maximum(S - st, 0.0)
        return y, (c if control else None)

    exact = bs_price(S, S, T, r, q, sigma, kind) if control else None
    return _run(payoff, S, T, r, q, sigma, n_steps, n_paths, seed,
                control_exact=exact)


def cliquet(S, T, r, q, sigma, n_periods=12, local_cap=0.04,
            local_floor=-0.02, global_floor=0.0, global_cap=None,
            steps_per_period=21, n_paths=200_000, seed=42):
    """Cliquet (ratchet): sum of per-period returns, each floored and
    capped locally, the sum floored (and optionally capped) globally.
    Price is per unit notional (payoff = notional x total return)."""
    n_steps = int(n_periods) * int(steps_per_period)

    def payoff(paths):
        idx = np.arange(1, n_periods + 1) * steps_per_period
        ends = paths[:, idx]
        starts = np.concatenate(
            [np.full((paths.shape[0], 1), float(S)), ends[:, :-1]], axis=1)
        local = ends / starts - 1.0
        local = np.clip(local, local_floor, local_cap)
        total = local.sum(axis=1)
        total = np.maximum(total, global_floor)
        if global_cap is not None:
            total = np.minimum(total, global_cap)
        return total, None

    return _run(payoff, S, T, r, q, sigma, n_steps, n_paths, seed)
