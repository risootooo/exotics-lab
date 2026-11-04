# Calibration provenance

Every model input in this repo traces to a real observation or a stated
assumption. Nothing is hard-coded silently; `data/calibration.json` is the
single source and `src/exotics/calibration.py` loads it.

| Input | Value | Source |
|---|---|---|
| NIFTY spot S0 | 23,810.85 | `UndrlygPric`, NIFTY `IDO` rows, NSE F&O bhavcopy 3 Nov 2026 (`BhavCopy_NSE_FO_0_0_0_20261103_F_0000.csv`, from the 220-file `fo_YYYYMMDD.zip` archive, Nov 2025 – Nov 2026) |
| Vol σ | 15.34% | ATM IV of the same file's chain: expiry 9 Nov 2026, strike 23,800, CE 10.76% / PE 19.92% averaged (the gap is a measured settlement-print parity break — see the sibling `greeks-lab` repo). Cross-checks: realised vol 11.8–15.8% (below) |
| IV term points | 13.0–13.8% out to ~2y, 18.2% at 3.1y | Same bhavcopy file, LEAPS expiries to 2031; far prints are illiquid and flagged indicative |
| Historical vol | 21d 15.79% · 63d 11.84% · 126d 12.19% · 252d 13.86% · EWMA(0.94) 14.97% | yfinance `^NSEI` daily closes, 4 Nov 2024 – 3 Nov 2026 (the feed's 2026-11-04 row is NaN and was excluded) |
| Rate r | 6.5% cont. | Stated assumption (house convention of the sibling repos; ≈ India 10y G-Sec, early Nov 2026) |
| Dividend yield q | 1.3% cont. | Stated assumption (NIFTY trailing yield band 1.1–1.4%) |

Regeneration: the bhavcopy archive lives outside this repo (267 MB). The
sibling `greeks-lab` repo (`tools/build_sample.py`, `src/greekslab/chain.py`)
contains the parser used to read it; this repo only ships the extracted
numbers above.
