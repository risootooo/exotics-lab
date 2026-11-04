"""Loads the calibrated NIFTY inputs (data/calibration.json).

The numbers come from the real NSE F&O bhavcopy of 3 Nov 2026 and a
yfinance realised-vol cross-check -- see data/PROVENANCE.md for the full
trail. This module exists so no pricer call site ever hard-codes a
market input.
"""

from __future__ import annotations

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "..",
                     "data", "calibration.json")


def load(path=None):
    with open(path or _PATH) as f:
        return json.load(f)


def market():
    """(spot, sigma, r, q) -- the calibrated base case."""
    c = load()
    return c["spot"], c["sigma"], c["rate"], c["dividend_yield"]
