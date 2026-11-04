#!/usr/bin/env python3
"""Exotics & Structured Products Lab -- case-study runner.

Prices, on the calibrated real-NIFTY base case (3 Nov 2026, see
data/calibration.json):

  Case A  the knock-out discount: a 3-month ATM up-and-out call vs its
          vanilla twin across barrier levels (MC with Brownian-bridge
          correction, PDE cross-check), plus the delta ladder near the
          barrier -- the hedging nightmare, quantified.
  Case B  the autocallable a bank would actually sell: 3y quarterly
          autocall on NIFTY, fair coupon solved to par, issuer margin
          at a marketed coupon 100bp lower, event probabilities and
          stresses.
  Case C  model agreement: MC vs PDE on the barrier across a strike
          grid, and the arithmetic Asian vs its Kemna-Vorst control.

Writes docs/results.json (consumed by tools/build_dashboard.py).
Run:  python main.py
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from exotics import bs_price, bs_delta, bs_vega, asian_geometric_price
from exotics import mc, pde, greeks, calibration
from exotics.autocall import AutocallNote, AutocallTerms

HERE = os.path.dirname(__file__)
N_MC = 400_000          # paths for headline prices
SEED = 20261103         # the calibration date, for reproducibility


def case_a(S, sigma, r, q):
    T, K = 0.25, 23800.0
    vanilla_bs = bs_price(S, K, T, r, q, sigma, "CE")
    vanilla_mc = mc.european(S, K, T, r, q, sigma, "CE",
                             n_paths=N_MC, seed=SEED)
    rows = []
    for mult in (1.02, 1.05, 1.08, 1.10, 1.15, 1.20, 1.30):
        H = mult * S
        res = mc.barrier(S, K, T, H, r, q, sigma, "CE", n_steps=126,
                         n_paths=N_MC, seed=SEED + int(mult * 100))
        ref = pde.pde_price(S, K, T, r, q, sigma, "CE",
                            barrier=("up-and-out", H))
        rows.append({
            "barrier_mult": mult, "barrier": H,
            "mc_price": res.price, "mc_se": res.se,
            "pde_price": ref["price"],
            "discount_pct": 100.0 * (1.0 - res.price / vanilla_bs),
        })
    # Delta ladder at the headline barrier (H = 1.10 x spot).
    H = 1.10 * S
    ladder = []
    for frac in (0.80, 0.85, 0.90, 0.95, 0.98, 0.99, 0.995):
        s_lvl = frac * H
        ref = pde.pde_price(s_lvl, K, T, r, q, sigma, "CE",
                            barrier=("up-and-out", H))
        ladder.append({
            "spot_over_barrier": frac, "spot": s_lvl,
            "uao_price": ref["price"], "uao_delta": ref["delta"],
            "uao_gamma": ref["gamma"],
            "vanilla_delta": bs_delta(s_lvl, K, T, r, q, sigma, "CE"),
        })
    g_mc = greeks.barrier_greeks(S, K, T, H, r, q, sigma,
                                 n_paths=200_000, seed=SEED)
    g_vn = greeks.european_greeks(S, K, T, r, q, sigma,
                                  n_paths=200_000, seed=SEED)
    return {
        "T": T, "strike": K, "vanilla_bs": vanilla_bs,
        "vanilla_mc": vanilla_mc.price, "vanilla_mc_se": vanilla_mc.se,
        "barrier_rows": rows,
        "headline_barrier_mult": 1.10, "headline_barrier": H,
        "delta_ladder": ladder,
        "greeks_at_spot_mc": {k: float(v) for k, v in g_mc.items()},
        "greeks_vanilla_mc": {k: float(v) for k, v in g_vn.items()},
        "vanilla_delta_bs": bs_delta(S, K, T, r, q, sigma, "CE"),
        "vanilla_vega_per_point": bs_vega(S, K, T, r, q, sigma) / 100.0,
    }


def case_b(S, sigma, r, q):
    terms = AutocallTerms()
    note = AutocallNote(S, r, q, sigma, terms, n_paths=500_000, seed=SEED)
    fair = note.fair_coupon()
    at_fair = note.price(fair)
    a_leg, b_leg = note.leg_decomposition()
    marketed = fair - 0.0100          # marketed 100bp below model-fair
    at_mkt = note.price(marketed)
    margin = 100.0 - at_mkt["price"]
    shocked_vol = AutocallNote(S, r, q, sigma + 0.05, terms,
                               n_paths=500_000, seed=SEED)
    stress_vol = shocked_vol.price(marketed)
    stress_spot = note.price(marketed, spot_shift=0.90)
    g = greeks.autocall_greeks(note, marketed, n_paths=200_000, seed=SEED)
    return {
        "terms": {"maturity_years": terms.maturity, "n_obs": terms.n_obs,
                  "autocall_level": terms.autocall_level,
                  "coupon_barrier": terms.coupon_barrier,
                  "ki_barrier": terms.ki_barrier,
                  "memory": False},
        "fair_coupon_pct": 100.0 * fair,
        "leg_redemption_net_pct": a_leg, "leg_coupon_annuity": b_leg,
        "at_fair": at_fair,
        "marketed_coupon_pct": 100.0 * marketed,
        "value_at_marketed": at_mkt["price"],
        "value_at_marketed_se": at_mkt["se"],
        "issuer_margin_pct": margin,
        "stress_vol_plus5": stress_vol["price"],
        "stress_spot_minus10": stress_spot["price"],
        "greeks_at_marketed": g,
    }


def case_c(S, sigma, r, q):
    T, H = 0.25, 1.15 * S
    rows = []
    for mult in (0.95, 1.00, 1.05, 1.10):
        K = round(mult * S / 50.0) * 50.0
        res = mc.barrier(S, K, T, H, r, q, sigma, "CE", n_steps=126,
                         n_paths=N_MC, seed=SEED + int(mult * 1000))
        ref = pde.pde_price(S, K, T, r, q, sigma, "CE",
                            barrier=("up-and-out", H))
        vega_pt = bs_vega(S, K, T, r, q, sigma) / 100.0
        rows.append({
            "strike": K, "strike_mult": mult,
            "mc_price": res.price, "mc_se": res.se,
            "pde_price": ref["price"],
            "diff_points": abs(res.price - ref["price"]),
            "diff_vol_points": abs(res.price - ref["price"]) / vega_pt,
        })
    geo_cf = asian_geometric_price(S, 23800.0, T, r, q, sigma, "CE", 63)
    geo_mc = mc.asian(S, 23800.0, T, r, q, sigma, "CE",
                      average="geometric", n_fixings=63,
                      n_paths=N_MC, seed=SEED)
    ari_mc = mc.asian(S, 23800.0, T, r, q, sigma, "CE",
                      average="arithmetic", n_fixings=63,
                      n_paths=N_MC, seed=SEED)
    return {
        "T": T, "barrier": H, "barrier_mult": 1.15, "rows": rows,
        "max_diff_points": max(x["diff_points"] for x in rows),
        "max_diff_vol_points": max(x["diff_vol_points"] for x in rows),
        "asian": {"geometric_closed_form": geo_cf,
                  "geometric_mc": geo_mc.price, "geometric_mc_se": geo_mc.se,
                  "geometric_err_se": abs(geo_mc.price - geo_cf) / geo_mc.se,
                  "arithmetic_mc": ari_mc.price,
                  "arithmetic_mc_se": ari_mc.se},
    }


def extras(S, sigma, r, q):
    lb = mc.lookback(S, 0.25, r, q, sigma, "CE", n_steps=126,
                     n_paths=200_000, seed=SEED)
    cl = mc.cliquet(S, 1.0, r, q, sigma, n_periods=12, local_cap=0.05,
                    local_floor=-0.03, global_floor=0.0,
                    n_paths=200_000, seed=SEED)
    return {"lookback_floating_call_3m": {"price": lb.price, "se": lb.se},
            "cliquet_1y_monthly_cap5_floor-3_globalfloor0": {
                "price_per_unit_notional": cl.price, "se": cl.se}}


def main():
    S, sigma, r, q = calibration.market()
    print("=" * 74)
    print("EXOTICS & STRUCTURED PRODUCTS LAB -- calibrated to real NIFTY "
          "data")
    print(f"Spot {S:,.2f} | sigma {sigma * 100:.2f}% (ATM IV, NSE bhavcopy "
          f"3 Nov 2026) | r {r * 100:.1f}% | q {q * 100:.1f}%")
    print("=" * 74)

    a = case_a(S, sigma, r, q)
    print("\nCASE A -- 3m ATM up-and-out call (K=23,800): the knock-out "
          "discount")
    print(f"Vanilla: BS {a['vanilla_bs']:.2f} | MC {a['vanilla_mc']:.2f} "
          f"+- {a['vanilla_mc_se']:.2f}")
    print(f"{'Barrier':>10} {'MC price':>10} {'+-SE':>6} {'PDE':>10} "
          f"{'Discount':>9}")
    for row in a["barrier_rows"]:
        print(f"{row['barrier']:>10,.0f} {row['mc_price']:>10.2f} "
              f"{row['mc_se']:>6.2f} {row['pde_price']:>10.2f} "
              f"{row['discount_pct']:>8.1f}%")
    print(f"\nDelta ladder at H = {a['headline_barrier']:,.0f} "
          f"(PDE; vanilla delta for contrast):")
    print(f"{'S/H':>6} {'UAO price':>10} {'UAO delta':>10} "
          f"{'UAO gamma':>11} {'Vanilla d':>10}")
    for row in a["delta_ladder"]:
        print(f"{row['spot_over_barrier']:>6.3f} {row['uao_price']:>10.2f} "
              f"{row['uao_delta']:>10.3f} {row['uao_gamma']:>11.2e} "
              f"{row['vanilla_delta']:>10.3f}")
    gm = a["greeks_at_spot_mc"]
    print(f"MC (CRN) greeks at spot: delta {gm['delta']:.3f} "
          f"(vanilla {a['vanilla_delta_bs']:.3f}), gamma {gm['gamma']:.2e}, "
          f"vega {gm['vega_per_point']:+.1f}/pt "
          f"(vanilla {a['vanilla_vega_per_point']:+.1f}/pt)")

    b = case_b(S, sigma, r, q)
    af = b["at_fair"]
    print("\nCASE B -- 3y quarterly NIFTY autocall (call 100% / coupon "
          "barrier 70% / KI 60%, no memory)")
    print(f"Fair coupon (price = par): {b['fair_coupon_pct']:.2f}% p.a. "
          f"[legs: redemption net {b['leg_redemption_net_pct']:.2f} + "
          f"coupon annuity {b['leg_coupon_annuity']:.2f} x c]")
    print(f"At fair coupon: P(autocall yr 1) {af['p_autocall_year1']:.1%}, "
          f"P(ever) {af['p_ever_autocalled']:.1%}, "
          f"P(capital loss) {af['p_capital_loss']:.2%} "
          f"(loss given loss {af['mean_loss_given_loss_pct']:.1f}%), "
          f"E[life] {af['expected_life']:.2f}y")
    print(f"Marketed at {b['marketed_coupon_pct']:.2f}% p.a.: value "
          f"{b['value_at_marketed']:.2f} +- {b['value_at_marketed_se']:.2f} "
          f"-> issuer margin {b['issuer_margin_pct']:.2f} pts")
    print(f"Stresses at marketed coupon: vol +5pts -> "
          f"{b['stress_vol_plus5']:.2f} | spot -10% -> "
          f"{b['stress_spot_minus10']:.2f}")
    gb = b["greeks_at_marketed"]
    print(f"Note greeks: delta {gb['delta_per_1pct_spot']:+.2f} pts per "
          f"+1% spot, vega {gb['vega_per_point']:+.2f} pts per vol point "
          f"(investor is short vol)")

    c = case_c(S, sigma, r, q)
    print("\nCASE C -- model agreement: MC vs PDE, up-and-out call, "
          f"H = {c['barrier']:,.0f}")
    print(f"{'Strike':>9} {'MC':>9} {'+-SE':>6} {'PDE':>9} {'|diff|':>8} "
          f"{'vol pts':>8}")
    for row in c["rows"]:
        print(f"{row['strike']:>9,.0f} {row['mc_price']:>9.2f} "
              f"{row['mc_se']:>6.2f} {row['pde_price']:>9.2f} "
              f"{row['diff_points']:>8.2f} {row['diff_vol_points']:>8.3f}")
    print(f"Max |diff|: {c['max_diff_points']:.2f} pts "
          f"({c['max_diff_vol_points']:.3f} vol pts)")
    asn = c["asian"]
    print(f"Asian control check: geometric MC {asn['geometric_mc']:.2f} vs "
          f"Kemna-Vorst {asn['geometric_closed_form']:.2f} "
          f"({asn['geometric_err_se']:.1f} SE); arithmetic MC "
          f"{asn['arithmetic_mc']:.2f} +- {asn['arithmetic_mc_se']:.2f} "
          f"(control-variate SE)")

    ex = extras(S, sigma, r, q)
    print(f"\nAlso in the engine: 3m floating-strike lookback call "
          f"{ex['lookback_floating_call_3m']['price']:.2f} +- "
          f"{ex['lookback_floating_call_3m']['se']:.2f}; 1y monthly "
          f"cliquet {ex['cliquet_1y_monthly_cap5_floor-3_globalfloor0']['price_per_unit_notional'] * 100:.2f}% "
          f"of notional")

    results = {"calibration": calibration.load(),
               "case_a": a, "case_b": b, "case_c": c, "extras": ex}
    out = os.path.join(HERE, "docs", "results.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
