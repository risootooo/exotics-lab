"""Black-Scholes-Merton closed forms used as controls and cross-checks.

Conventions (repo-wide): S spot, K strike, T years (act/365), r and q
continuously compounded, sigma annualised vol, kind 'CE' / 'PE' (NSE
option-type codes).

Contents:
  * bs_price / bs_delta / bs_vega  - vanilla reference values. Every Monte
    Carlo pricer in this repo is anchored to these (control variate or
    test), so a bug here would poison everything; the tests therefore pin
    them against put-call parity and textbook values.
  * asian_geometric_price          - Kemna-Vorst closed form for the
    discretely-fixed geometric-average option. It is the exact price of
    the geometric contract and the standard control variate for the
    arithmetic one.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

__all__ = ["bs_price", "bs_delta", "bs_vega",
           "asian_geometric_price"]


def _check_kind(kind: str) -> str:
    k = kind.upper()
    if k in ("CE", "C", "CALL"):
        return "CE"
    if k in ("PE", "P", "PUT"):
        return "PE"
    raise ValueError(f"unknown option kind {kind!r}, use 'CE' or 'PE'")


def d1_d2(S, K, T, r, q, sigma):
    vol_sqrt_t = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def bs_price(S, K, T, r, q, sigma, kind):
    """Black-Scholes-Merton price with continuous dividend yield q."""
    kind = _check_kind(kind)
    S, K, T, sigma = (np.asarray(x, dtype=float) for x in (S, K, T, sigma))
    intrinsic = np.maximum(S - K, 0.0) if kind == "CE" else np.maximum(K - S, 0.0)
    live = (T > 0) & (sigma > 0)
    if not np.any(live):
        return float(intrinsic) if np.ndim(intrinsic) == 0 else intrinsic
    d1, d2 = d1_d2(np.where(live, S, 1.0), np.where(live, K, 1.0),
                   np.where(live, T, 1.0), r, q, np.where(live, sigma, 1.0))
    if kind == "CE":
        price = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
    price = np.where(live, price, intrinsic)
    return float(price) if np.ndim(price) == 0 else price


def bs_delta(S, K, T, r, q, sigma, kind):
    kind = _check_kind(kind)
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    if kind == "CE":
        return float(np.exp(-q * T) * norm.cdf(d1))
    return float(-np.exp(-q * T) * norm.cdf(-d1))


def bs_vega(S, K, T, r, q, sigma):
    """Vega per 1.00 of sigma (divide by 100 for per-vol-point)."""
    d1, _ = d1_d2(S, K, T, r, q, sigma)
    return float(S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(T))


def asian_geometric_price(S, K, T, r, q, sigma, kind, n_fixings):
    """Kemna-Vorst price of a geometric-average option with fixings at
    t_i = i * T / n_fixings, i = 1..n_fixings (expiry included, inception
    excluded).

    For G = (prod S_{t_i})^{1/N}, ln G is normal with
        mean  m = ln S + (r - q - sigma^2/2) * T * (N+1) / (2N)
        var   v = sigma^2 * T * (N+1)(2N+1) / (6 N^2)
    (using sum_{i,j} min(i,j) = N(N+1)(2N+1)/6), so the contract is a
    Black formula on the lognormal G with forward exp(m + v/2).
    """
    kind = _check_kind(kind)
    N = int(n_fixings)
    if T <= 0:
        return float(max(S - K, 0.0) if kind == "CE" else max(K - S, 0.0))
    m = np.log(S) + (r - q - 0.5 * sigma ** 2) * T * (N + 1) / (2.0 * N)
    v = sigma ** 2 * T * (N + 1) * (2 * N + 1) / (6.0 * N * N)
    sv = np.sqrt(v)
    d1 = (m + v - np.log(K)) / sv
    d2 = d1 - sv
    fwd = np.exp(m + 0.5 * v)
    disc = np.exp(-r * T)
    if kind == "CE":
        return float(disc * (fwd * norm.cdf(d1) - K * norm.cdf(d2)))
    return float(disc * (K * norm.cdf(-d2) - fwd * norm.cdf(-d1)))
