"""Crank-Nicolson finite-difference pricer -- the independent cross-check.

The Monte Carlo engine and this solver share *no code path*: MC averages
discounted payoffs over simulated GBM paths, this solves the
Black-Scholes PDE

    dV/dtau = (sigma^2/2) V_xx + (r - q - sigma^2/2) V_x - r V,
    x = ln S,  tau = time to maturity,

on a uniform log-spot grid with a Crank-Nicolson scheme (second-order in
space and time) plus two initial implicit-Euler (Rannacher) steps to
damp the oscillations the payoff kink otherwise rings through the grid.
When the two engines agree on a barrier price to within Monte Carlo
error, the barrier number is believed; when they disagree, one of them
is wrong and the disagreement *is* the finding (see docs/CASES.md,
Case C).

Boundary conditions are the financial ones, not numerical filler:
  * vanilla call: V -> 0 as S -> 0; V -> S e^{-q tau} - K e^{-r tau} at
    the top of the grid.
  * vanilla put: mirrored.
  * up-and-out call: the grid *ends at the barrier* (x_hi = ln H) with
    V = 0 there -- knock-out is a boundary condition, not a payoff hack.
  * down-and-out put: grid starts at the barrier, V = 0.

Delta and gamma are read off the converged grid:
delta = V_x / S,  gamma = (V_xx - V_x) / S^2.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d
from scipy.linalg import solve_banded

__all__ = ["pde_price"]


def _boundaries(kind, flavour, S_lo, S_hi, K, r, q, tau):
    """Dirichlet boundary values at time-to-maturity tau."""
    if flavour == "up-and-out":
        return 0.0, 0.0
    if flavour == "down-and-out":
        return 0.0, 0.0
    if kind == "CE":
        return 0.0, S_hi * np.exp(-q * tau) - K * np.exp(-r * tau)
    return K * np.exp(-r * tau) - S_lo * np.exp(-q * tau), 0.0


def pde_price(S, K, T, r, q, sigma, kind="CE", barrier=None,
              n_x=600, n_t=600):
    """Price a European or single-barrier knock-out option by PDE.

    barrier: None, or (flavour, H) with flavour 'up-and-out' /
    'down-and-out'. Returns dict with price, delta, gamma and the final
    grid (S_grid, V_grid) for inspection / charting.
    """
    if T <= 0:
        intrinsic = max(S - K, 0.0) if kind == "CE" else max(K - S, 0.0)
        return {"price": float(intrinsic), "delta": float("nan"),
                "gamma": float("nan"), "S_grid": np.array([S]),
                "V_grid": np.array([intrinsic])}
    flavour, H = (None, None) if barrier is None else barrier
    vol_sqrt_t = sigma * np.sqrt(T)

    # --- grid domain -------------------------------------------------
    if flavour == "up-and-out":
        x_hi = np.log(H)
        x_lo = min(np.log(K), np.log(S)) - (4.0 * vol_sqrt_t + 0.30)
    elif flavour == "down-and-out":
        x_lo = np.log(H)
        x_hi = max(np.log(K), np.log(S)) + (4.0 * vol_sqrt_t + 0.30)
    else:
        half = abs(np.log(K / S)) + 5.0 * vol_sqrt_t + 0.25
        x_lo, x_hi = np.log(S) - half, np.log(S) + half
    x = np.linspace(x_lo, x_hi, n_x + 1)
    dx = x[1] - x[0]
    s_grid = np.exp(x)
    dt = T / n_t

    # --- terminal payoff ---------------------------------------------
    if kind == "CE":
        V = np.maximum(s_grid - K, 0.0)
    else:
        V = np.maximum(K - s_grid, 0.0)
    if flavour == "up-and-out":
        V[s_grid >= H] = 0.0
    elif flavour == "down-and-out":
        V[s_grid <= H] = 0.0
    lo, hi = _boundaries(kind, flavour, s_grid[0], s_grid[-1], K, r, q, 0.0)
    V[0], V[-1] = lo, hi

    # --- operator coefficients (constant on a uniform log grid) ------
    mu = r - q - 0.5 * sigma ** 2
    a = 0.5 * sigma ** 2 / dx ** 2 - mu / (2.0 * dx)     # V_{j-1}
    b = -sigma ** 2 / dx ** 2 - r                       # V_j
    c = 0.5 * sigma ** 2 / dx ** 2 + mu / (2.0 * dx)    # V_{j+1}
    m = n_x - 1                                          # interior count

    def banded(theta):
        """(I - theta*dt*L) in scipy banded form for the interior."""
    # theta = 1 (implicit Euler) or 1/2 (Crank-Nicolson)
        ab = np.zeros((3, m))
        ab[0, 1:] = -theta * dt * c
        ab[1, :] = 1.0 - theta * dt * b
        ab[2, :-1] = -theta * dt * a
        return ab

    ab_ie = banded(1.0)
    ab_cn = banded(0.5)

    for n in range(n_t):
        tau_next = (n + 1) * dt
        lo_n, hi_n = _boundaries(kind, flavour, s_grid[0], s_grid[-1],
                                 K, r, q, tau_next)
        interior = V[1:-1].copy()
        if n < 2:
            # Rannacher start: fully implicit steps.
            rhs = interior.copy()
            rhs[0] += dt * a * lo_n
            rhs[-1] += dt * c * hi_n
            interior = solve_banded((1, 1), ab_ie, rhs)
        else:
            rhs = interior + 0.5 * dt * (
                a * np.concatenate([[V[0]], V[1:-2]])
                + b * interior
                + c * np.concatenate([V[2:-1], [V[-1]]]))
            rhs[0] += 0.5 * dt * a * lo_n
            rhs[-1] += 0.5 * dt * c * hi_n
            interior = solve_banded((1, 1), ab_cn, rhs)
        V[1:-1] = interior
        V[0], V[-1] = lo_n, hi_n

    # --- read price / delta / gamma at spot ---------------------------
    x0 = np.log(S)
    price = float(interp1d(x, V, kind="cubic")(x0))
    vx = np.gradient(V, dx)
    vxx = np.gradient(vx, dx)
    delta = float(interp1d(x, vx, kind="cubic")(x0)) / S
    gamma = float((interp1d(x, vxx, kind="cubic")(x0)
                   - interp1d(x, vx, kind="cubic")(x0)) / S ** 2)
    return {"price": price, "delta": delta, "gamma": gamma,
            "S_grid": s_grid, "V_grid": V}
