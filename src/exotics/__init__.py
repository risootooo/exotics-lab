"""Exotics & Structured Products Lab.

Path-dependent options priced by a variance-reduced Monte Carlo engine
and cross-checked by an independent Crank-Nicolson PDE solver, plus an
autocallable reverse-convertible note pricer with a fair-coupon solver.
Calibrated to real NIFTY data (NSE bhavcopy, 3 Nov 2026).
"""

from .bs import bs_price, bs_delta, bs_vega, asian_geometric_price
from . import mc, pde, autocall, greeks, calibration

__all__ = ["bs_price", "bs_delta", "bs_vega", "asian_geometric_price",
           "mc", "pde", "autocall", "greeks", "calibration"]
