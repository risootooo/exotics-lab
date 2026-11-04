"""Autocallable reverse-convertible note pricer (single underlying).

The structure priced here is the one actually sold off bank term sheets:

  * Term 3 years, quarterly observation dates (12).
  * **Autocall:** if S_obs >= 100% of the initial fixing on any
    observation date, the note redeems at par plus that date's coupon.
  * **Coupon (non-memory):** coupon c/4 of notional is paid on an
    observation date iff S_obs >= 70% (coupon barrier) and the note is
    still alive. A missed coupon is gone forever -- there is NO memory
    feature (many marketed notes add one; it is excluded here and the
    exclusion is stated wherever the coupon is quoted).
  * **Capital at risk:** if never autocalled and S_T < 60% (European
    knock-in barrier, observed at maturity only), redemption is
    notional x S_T / S_0 -- the investor takes the full downside below
    the strike, exactly like being short a down-and-in ATM put. Above
    60% the note redeems at par even though S_T is below the strike.

Prices are quoted per 100 notional. Simulation happens ONCE, at the 12
observation dates, on antithetic GBM paths; coupon enters the payoff
linearly, so price(coupon) is exactly affine in the coupon on a fixed
path set -- the fair-coupon bisection below is therefore deterministic
(no Monte Carlo jitter between iterations), and the closed-form leg
decomposition (redemption leg + coupon annuity - loss leg) is reported
alongside it as a cross-check.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["AutocallTerms", "AutocallNote"]


@dataclass
class AutocallTerms:
    notional: float = 100.0
    maturity: float = 3.0
    n_obs: int = 12                 # quarterly over 3 years
    autocall_level: float = 1.00    # x initial fixing
    coupon_barrier: float = 0.70
    ki_barrier: float = 0.60        # European: maturity only
    strike: float = 1.00

    @property
    def obs_times(self):
        return np.linspace(self.maturity / self.n_obs, self.maturity,
                           self.n_obs)


class AutocallNote:
    """Prices one note design on a fixed antithetic path set."""

    def __init__(self, S0, r, q, sigma, terms: AutocallTerms = None,
                 n_paths=400_000, seed=123):
        self.S0 = float(S0)
        self.r, self.q, self.sigma = float(r), float(q), float(sigma)
        self.terms = terms or AutocallTerms()
        t = self.terms
        if n_paths % 2:
            n_paths += 1
        rng = np.random.default_rng(seed)
        n_pairs = n_paths // 2
        times = t.obs_times
        dt = np.diff(np.concatenate([[0.0], times]))
        z = rng.standard_normal((n_pairs, t.n_obs))
        z = np.concatenate([z, -z], axis=0)
        drift = (self.r - self.q - 0.5 * self.sigma ** 2) * dt
        diff = self.sigma * np.sqrt(dt)
        log_ratios = np.cumsum(drift + diff * z, axis=1)
        # Ratio paths S_obs / S_0 -- the note only ever sees ratios,
        # which is also what makes spot-shift Greeks exact (see greeks).
        self._ratios = np.exp(log_ratios)
        self._n_pairs = n_pairs
        self._df = np.exp(-self.r * times)

    # ------------------------------------------------------------------
    def _evaluate(self, coupon, spot_shift=1.0):
        """Per-pair-mean PV and event statistics at a given annual coupon.

        Returns dict of scalars; PV arrays are reduced to antithetic
        pair means first so the SE is honest."""
        t = self.terms
        R = self._ratios * spot_shift
        m = t.n_obs
        called = R >= t.autocall_level
        any_call = called.any(axis=1)
        call_idx = np.where(any_call, called.argmax(axis=1), m)
        alive_at = np.arange(m)[None, :] <= np.minimum(call_idx, m - 1)[:, None]
        coupon_due = alive_at & (R >= t.coupon_barrier)
        # coupon per date = c * (T/m) * notional, in points of notional
        coupon_pv = (coupon_due * self._df[None, :]).sum(axis=1) \
            * coupon * (t.maturity / m) * t.notional
        # redemption
        r_final = R[:, -1]
        matured_loss = (~any_call) & (r_final < t.ki_barrier)
        redemption = np.where(
            any_call, t.notional,
            np.where(matured_loss, t.notional * r_final / t.strike,
                     t.notional))
        red_time_idx = np.where(any_call, call_idx, m - 1)
        redemption_pv = redemption * self._df[red_time_idx]
        pv = coupon_pv + redemption_pv
        n = self._n_pairs
        pv_pair = 0.5 * (pv[:n] + pv[n:])
        price = float(pv_pair.mean())
        se = float(pv_pair.std(ddof=1) / np.sqrt(n))
        life = self.terms.obs_times[red_time_idx]
        loss_pair = 0.5 * (matured_loss[:n].astype(float)
                           + matured_loss[n:].astype(float))
        out = {
            "price": price,
            "se": se,
            "p_autocall_by_date": [
                float((call_idx <= i).mean()) for i in range(m)],
            "p_autocall_year1": float(
                (call_idx <= max(1, m // 3) - 1).mean()),
            "p_ever_autocalled": float(any_call.mean()),
            "p_capital_loss": float(loss_pair.mean()),
            "expected_life": float(life.mean()),
            "mean_redemption_pv": float(redemption_pv.mean()),
            "mean_coupon_pv": float(coupon_pv.mean()),
        }
        if matured_loss.any():
            shortfall = 1.0 - r_final[matured_loss] / t.strike
            out["mean_loss_given_loss_pct"] = float(shortfall.mean() * 100.0)
        else:
            out["mean_loss_given_loss_pct"] = 0.0
        return out

    # ------------------------------------------------------------------
    def price(self, coupon, spot_shift=1.0):
        """Full diagnostic dict at an annual coupon rate (decimal)."""
        return self._evaluate(coupon, spot_shift=spot_shift)

    def fair_coupon(self, target=100.0, lo=0.0, hi=0.40, tol=1e-7):
        """Bisection on the coupon so price = target (par = 100).

        Deterministic: the path set is fixed, and price is affine in the
        coupon on it, so bisection converges to machine precision."""
        f_lo = self._evaluate(lo)["price"] - target
        f_hi = self._evaluate(hi)["price"] - target
        if f_lo * f_hi > 0:
            raise ValueError("target not bracketed by [lo, hi] coupons")
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            f_mid = self._evaluate(mid)["price"] - target
            if abs(f_mid) < tol:
                return mid
            if (f_mid < 0) == (f_lo < 0):
                lo, f_lo = mid, f_mid
            else:
                hi = mid
            if hi - lo < 1e-9:
                break
        return 0.5 * (lo + hi)

    def leg_decomposition(self):
        """price(c) = A + c * B from two evaluations on the same paths:
        A = value with zero coupon (redemption leg net of the capital-
        loss leg), B = PV of a 100%-coupon annuity (per unit coupon)."""
        a = self._evaluate(0.0)["price"]
        b = self._evaluate(1.0)["price"] - a
        return a, b
