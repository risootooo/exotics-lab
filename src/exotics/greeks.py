"""Bump-and-revalue Greeks for exotics -- with common random numbers.

Exotics have no closed-form Greeks, so desks bump and revalue. Done
naively (fresh random numbers per bump) the Monte Carlo noise is larger
than the bump response and the "Greek" is pure noise. The professional
fix, used throughout this module, is **common random numbers (CRN)**:
every bumped valuation reuses the *identical* seed, hence the identical
normal draws, so the price difference is the pure bump response of the
same paths. With CRN the difference estimator's variance collapses --
that, not the bump formula, is the skill being demonstrated.

Conventions:
  * delta per 1.00 of spot, gamma per 1.00^2, vega per 1 vol point.
  * spot bump: 0.5% of spot, central difference. Small enough that the
    O(h^2) bias is negligible next to MC error on smooth payoffs, large
    enough that payoff discontinuities (barrier!) are not smeared --
    near a barrier the delta is genuinely near-discontinuous and the
    stability note below applies.
  * vol bump: 1 vol point, central difference.

Stability note (barrier delta): an up-and-out call's delta falls to
zero at the barrier and peaks just below it; any finite bump straddling
the peak averages two regimes. The Case A table therefore reports delta
on a spot ladder rather than a single number, and the ladder -- not a
point estimate -- is the deliverable a hedging desk actually needs.
"""

from __future__ import annotations

import numpy as np

from . import mc
from .autocall import AutocallNote

__all__ = ["bump_greeks", "barrier_greeks", "european_greeks",
           "autocall_greeks"]


def bump_greeks(price_once, S, sigma, spot_bump_frac=0.005,
                vol_bump=0.01):
    """Central-difference Greeks around (S, sigma).

    price_once(S, sigma) -> float must be deterministic: same inputs,
    same normals (fixed seed inside). Returns dict with price, delta,
    gamma, vega_per_point."""
    h = S * spot_bump_frac
    p0 = price_once(S, sigma)
    p_up = price_once(S + h, sigma)
    p_dn = price_once(S - h, sigma)
    v_up = price_once(S, sigma + vol_bump)
    v_dn = price_once(S, sigma - vol_bump)
    return {
        "price": p0,
        "delta": (p_up - p_dn) / (2.0 * h),
        "gamma": (p_up - 2.0 * p0 + p_dn) / h ** 2,
        "vega_per_point": (v_up - v_dn) / (2.0 * vol_bump) / 100.0,
    }


def european_greeks(S, K, T, r, q, sigma, kind="CE", n_paths=200_000,
                    seed=42):
    """CRN Greeks of the MC European -- validated against the analytic
    Black-Scholes Greeks in the test suite."""
    def price_once(s, v):
        return mc.european(s, K, T, r, q, v, kind=kind,
                           n_paths=n_paths, seed=seed).price
    return bump_greeks(price_once, S, sigma)


def barrier_greeks(S, K, T, H, r, q, sigma, kind="CE",
                   flavour="up-and-out", n_steps=126, n_paths=200_000,
                   seed=42):
    """CRN Greeks of a knock-out option on the MC engine."""
    def price_once(s, v):
        return mc.barrier(s, K, T, H, r, q, v, kind=kind,
                          flavour=flavour, n_steps=n_steps,
                          n_paths=n_paths, seed=seed).price
    return bump_greeks(price_once, S, sigma)


def autocall_greeks(note: AutocallNote, coupon, spot_bump_frac=0.005,
                    vol_bump=0.01, n_paths=400_000, seed=123):
    """Greeks of the autocallable note, per 100 notional.

    Spot bumps are applied by *shifting the simulated ratio paths*
    (every future observation scales by the bump factor) -- the exact
    CRN analogue for a note written on ratios to the initial fixing,
    and free of resimulation noise. Vol bumps require fresh path sets
    at the bumped vol; the seed is held fixed, which is again CRN."""
    t = note.terms
    base = note.price(coupon)
    up = note.price(coupon, spot_shift=1.0 + spot_bump_frac)
    dn = note.price(coupon, spot_shift=(1.0 - spot_bump_frac))
    h = spot_bump_frac  # per unit of ratio space; delta quoted per 1%
    delta_per_pct = (up["price"] - dn["price"]) / (2.0 * h) / 100.0

    def at_vol(v):
        clone = AutocallNote(note.S0, note.r, note.q, v, terms=t,
                             n_paths=n_paths, seed=seed)
        return clone.price(coupon)["price"]

    v_up = at_vol(note.sigma + vol_bump)
    v_dn = at_vol(note.sigma - vol_bump)
    return {
        "price": base["price"],
        "delta_per_1pct_spot": delta_per_pct,
        "vega_per_point": (v_up - v_dn) / (2.0 * vol_bump) / 100.0,
    }
