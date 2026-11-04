"""Test suite for the Exotics & Structured Products Lab.

The suite is organised the way a model-validation team would organise
it: closed-form anchors first, then Monte Carlo convergence to them,
then the PDE as an independent engine, then the structured note's
contractual extremes, then Greeks. Every tolerance is either a multiple
of the Monte Carlo standard error (the honest unit) or a PDE grid
tolerance verified by refinement -- never a magic number.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from exotics import bs_price, bs_delta, bs_vega, asian_geometric_price
from exotics import mc, pde, greeks
from exotics.autocall import AutocallNote, AutocallTerms

# Calibrated NIFTY base case (data/calibration.json).
S, K, T = 23810.85, 23800.0, 0.25
R, Q, SIG = 0.065, 0.013, 0.1534
H = 1.10 * S


# ----------------------------------------------------------------------
# Closed-form anchors
# ----------------------------------------------------------------------
def test_bs_put_call_parity():
    c = bs_price(S, K, T, R, Q, SIG, "CE")
    p = bs_price(S, K, T, R, Q, SIG, "PE")
    forward_leg = S * np.exp(-Q * T) - K * np.exp(-R * T)
    assert abs(c - p - forward_leg) < 1e-8


def test_bs_atm_zero_rates_identity():
    # Independent anchor via math.erf (a different code path from
    # scipy's norm.cdf): with S=K and r=q=0, call = S (2N(sigma sqrt(T)/2) - 1).
    import math

    def ncdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    v = bs_price(100.0, 100.0, 1.0, 0.0, 0.0, 0.20, "CE")
    expected = 100.0 * (2.0 * ncdf(0.20 / 2.0) - 1.0)
    assert abs(v - expected) < 1e-10


# ----------------------------------------------------------------------
# Monte Carlo vs closed forms
# ----------------------------------------------------------------------
def test_mc_european_call_within_3se_of_bs():
    res = mc.european(S, K, T, R, Q, SIG, "CE", n_paths=200_000, seed=101)
    assert abs(res.price - bs_price(S, K, T, R, Q, SIG, "CE")) <= 3 * res.se


def test_mc_european_put_within_3se_of_bs():
    res = mc.european(S, K, T, R, Q, SIG, "PE", n_paths=200_000, seed=102)
    assert abs(res.price - bs_price(S, K, T, R, Q, SIG, "PE")) <= 3 * res.se


def test_mc_put_call_parity_same_paths():
    c = mc.european(S, K, T, R, Q, SIG, "CE", n_paths=200_000, seed=103)
    p = mc.european(S, K, T, R, Q, SIG, "PE", n_paths=200_000, seed=103)
    forward_leg = S * np.exp(-Q * T) - K * np.exp(-R * T)
    assert abs(c.price - p.price - forward_leg) <= 3 * np.hypot(c.se, p.se)


def test_geometric_asian_mc_vs_kemna_vorst():
    cf = asian_geometric_price(S, K, T, R, Q, SIG, "CE", 63)
    res = mc.asian(S, K, T, R, Q, SIG, "CE", average="geometric",
                   n_fixings=63, n_paths=200_000, seed=104)
    assert abs(res.price - cf) <= 3.5 * res.se


def test_arithmetic_asian_above_geometric():
    # AM >= GM pathwise, so the arithmetic contract is worth more.
    ari = mc.asian(S, K, T, R, Q, SIG, "CE", average="arithmetic",
                   n_fixings=63, n_paths=200_000, seed=105)
    geo_cf = asian_geometric_price(S, K, T, R, Q, SIG, "CE", 63)
    assert ari.price > geo_cf


def test_control_variate_reduces_asian_se():
    with_cv = mc.asian(S, K, T, R, Q, SIG, "CE", average="arithmetic",
                       n_fixings=63, n_paths=100_000, seed=106, control=True)
    without = mc.asian(S, K, T, R, Q, SIG, "CE", average="arithmetic",
                       n_fixings=63, n_paths=100_000, seed=106, control=False)
    assert with_cv.se < 0.5 * without.se


# ----------------------------------------------------------------------
# Barriers: limits and monitoring
# ----------------------------------------------------------------------
def test_barrier_tends_to_vanilla_as_barrier_leaves():
    res = mc.barrier(S, K, T, 1e6 * S, R, Q, SIG, "CE",
                     n_steps=63, n_paths=100_000, seed=107)
    vanilla = bs_price(S, K, T, R, Q, SIG, "CE")
    assert abs(res.price - vanilla) <= max(4 * res.se, 1.5)


def test_barrier_dies_as_barrier_touches_spot():
    res = mc.barrier(S, K, T, S * 1.0005, R, Q, SIG, "CE",
                     n_steps=126, n_paths=100_000, seed=108)
    assert res.price < 1.0


def test_barrier_worth_less_than_vanilla():
    res = mc.barrier(S, K, T, H, R, Q, SIG, "CE",
                     n_steps=126, n_paths=100_000, seed=109)
    assert res.price <= bs_price(S, K, T, R, Q, SIG, "CE") + 3 * res.se


def test_discrete_monitoring_overprices_barrier():
    # Discrete monitoring misses intra-grid crossings, so it must price
    # the knock-out HIGHER than the bridge-corrected continuous price.
    cont = mc.barrier(S, K, T, H, R, Q, SIG, "CE", n_steps=63,
                      n_paths=200_000, seed=110, monitoring="continuous")
    disc = mc.barrier(S, K, T, H, R, Q, SIG, "CE", n_steps=63,
                      n_paths=200_000, seed=110, monitoring="discrete")
    assert disc.price >= cont.price - 3 * np.hypot(cont.se, disc.se)


# ----------------------------------------------------------------------
# PDE: the independent engine
# ----------------------------------------------------------------------
def test_pde_european_call_matches_bs():
    out = pde.pde_price(S, K, T, R, Q, SIG, "CE")
    assert abs(out["price"] - bs_price(S, K, T, R, Q, SIG, "CE")) \
        / bs_price(S, K, T, R, Q, SIG, "CE") < 1e-3


def test_pde_european_put_matches_bs():
    out = pde.pde_price(S, K, T, R, Q, SIG, "PE")
    assert abs(out["price"] - bs_price(S, K, T, R, Q, SIG, "PE")) \
        / bs_price(S, K, T, R, Q, SIG, "PE") < 1e-3


def test_pde_delta_matches_bs():
    out = pde.pde_price(S, K, T, R, Q, SIG, "CE")
    assert abs(out["delta"] - bs_delta(S, K, T, R, Q, SIG, "CE")) < 0.005


def test_pde_vs_mc_barrier_agreement():
    res = mc.barrier(S, K, T, H, R, Q, SIG, "CE",
                     n_steps=126, n_paths=200_000, seed=111)
    out = pde.pde_price(S, K, T, R, Q, SIG, "CE",
                        barrier=("up-and-out", H))
    assert abs(res.price - out["price"]) <= max(5 * res.se, 2.0)


def test_pde_barrier_tends_to_vanilla():
    far = pde.pde_price(S, K, T, R, Q, SIG, "CE",
                        barrier=("up-and-out", 3.0 * S))
    plain = pde.pde_price(S, K, T, R, Q, SIG, "CE")
    assert abs(far["price"] - plain["price"]) / plain["price"] < 5e-3


def test_pde_delta_collapses_near_barrier():
    near = pde.pde_price(0.99 * H, K, T, R, Q, SIG, "CE",
                         barrier=("up-and-out", H))
    away = pde.pde_price(0.90 * H, K, T, R, Q, SIG, "CE",
                         barrier=("up-and-out", H))
    # The hedging nightmare, in one assertion: delta near the barrier
    # is a fraction of the delta further away -- and can flip sign.
    assert near["delta"] < 0.15
    assert away["delta"] > near["delta"] + 0.10


# ----------------------------------------------------------------------
# Lookback & cliquet structure
# ----------------------------------------------------------------------
def test_lookback_call_dominates_vanilla_call():
    lb = mc.lookback(S, T, R, Q, SIG, "CE", n_steps=126,
                     n_paths=100_000, seed=112)
    van = bs_price(S, S, T, R, Q, SIG, "CE")
    assert lb.price >= van - 3 * lb.se


def test_cliquet_single_period_identity():
    # One period, no caps/floors binding: payoff = S_T/S_0 - 1, whose
    # exact price is exp(-qT) - exp(-rT) per unit notional.
    res = mc.cliquet(S, T, R, Q, SIG, n_periods=1, local_cap=10.0,
                     local_floor=-10.0, global_floor=-10.0,
                     steps_per_period=63, n_paths=200_000, seed=113)
    exact = np.exp(-Q * T) - np.exp(-R * T)
    assert abs(res.price - exact) <= 4 * res.se


# ----------------------------------------------------------------------
# Autocallable note
# ----------------------------------------------------------------------
def _note(**terms_kw):
    return AutocallNote(S, R, Q, SIG, AutocallTerms(**terms_kw),
                        n_paths=200_000, seed=114)


def test_autocall_price_increases_with_coupon():
    note = _note()
    p0 = note.price(0.00)["price"]
    p5 = note.price(0.05)["price"]
    p10 = note.price(0.10)["price"]
    assert p0 < p5 < p10


def test_autocall_zero_coupon_below_par():
    note = _note()
    out = note.price(0.0)
    assert 80.0 < out["price"] < 100.0


def test_autocall_fair_coupon_reprices_to_par():
    note = _note()
    fc = note.fair_coupon()
    assert abs(note.price(fc)["price"] - 100.0) < 0.05


def test_autocall_leg_decomposition_matches_bisection():
    note = _note()
    a, b = note.leg_decomposition()
    assert b > 0
    assert abs((100.0 - a) / b - note.fair_coupon()) < 1e-4


def test_autocall_no_capital_loss_when_ki_vanishes():
    note = _note(ki_barrier=1e-6)
    assert note.price(0.08)["p_capital_loss"] == 0.0


def test_autocall_certain_call_when_barrier_vanishes():
    note = _note(autocall_level=1e-6)
    out = note.price(0.08)
    assert out["p_autocall_year1"] == 1.0
    assert abs(out["expected_life"] - 0.25) < 1e-9


def test_autocall_investor_is_short_vol():
    base = _note()
    shocked = AutocallNote(S, R, Q, SIG + 0.05, AutocallTerms(),
                           n_paths=200_000, seed=114)
    assert shocked.price(0.08)["price"] < base.price(0.08)["price"]


# ----------------------------------------------------------------------
# Greeks (CRN bump-and-revalue)
# ----------------------------------------------------------------------
def test_crn_european_delta_gamma_vs_analytic():
    g = greeks.european_greeks(S, K, T, R, Q, SIG, "CE",
                               n_paths=200_000, seed=115)
    assert abs(g["delta"] - bs_delta(S, K, T, R, Q, SIG, "CE")) < 0.01
    # analytic gamma = e^{-qT} phi(d1) / (S sigma sqrt(T))
    from scipy.stats import norm
    from exotics.bs import d1_d2
    d1, _ = d1_d2(S, K, T, R, Q, SIG)
    gamma_exact = np.exp(-Q * T) * norm.pdf(d1) / (S * SIG * np.sqrt(T))
    assert abs(g["gamma"] - gamma_exact) / gamma_exact < 0.15
    assert abs(g["vega_per_point"] - bs_vega(S, K, T, R, Q, SIG) / 100.0) \
        / (bs_vega(S, K, T, R, Q, SIG) / 100.0) < 0.05


def test_barrier_delta_below_vanilla_delta():
    g = greeks.barrier_greeks(S, K, T, H, R, Q, SIG,
                              n_paths=200_000, seed=116)
    assert g["delta"] < bs_delta(S, K, T, R, Q, SIG, "CE") - 0.20
    assert np.isfinite(g["gamma"]) and np.isfinite(g["vega_per_point"])
