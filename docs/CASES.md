# Case studies — real NIFTY calibration, 3 Nov 2026

All cases run on one calibrated base case, extracted from the real NSE
F&O bhavcopy of 3 Nov 2026 (see `data/PROVENANCE.md`): **spot 23,810.85**,
**σ = 15.34%** (ATM IV of the 9 Nov 2026 expiry, strike 23,800),
r = 6.5%, q = 1.3%. Every Monte Carlo price below used 400k antithetic
paths (500k for the note) with the stated variance reduction; every
price carries its standard error. Reproduce with `python main.py`.

---

## Case A — The knock-out discount, and the delta that turns on you

**Contract:** 3-month call, K = 23,800 (the real ATM strike), up-and-out,
no rebate. Vanilla twin: BS **890.86** pts (MC 893.19 ± 1.32).

| Barrier | × spot | UAO price (MC) | ± SE | PDE | Discount vs vanilla |
|---:|---:|---:|---:|---:|---:|
| 24,287 | 1.02 | 1.08 | 0.02 | 1.10 | 99.9% |
| 25,001 | 1.05 | 32.66 | 0.19 | 32.63 | 96.3% |
| 25,716 | 1.08 | 146.09 | 0.44 | 146.07 | 83.6% |
| 26,192 | 1.10 | 265.21 | 0.61 | 263.77 | 70.2% |
| 27,382 | 1.15 | 574.78 | 0.94 | 577.84 | 35.5% |
| 28,573 | 1.20 | 776.80 | 0.92 | 777.85 | 12.8% |
| 30,954 | 1.30 | 884.09 | 0.33 | 883.96 | 0.8% |

The discount is violently non-linear: the last 5% of barrier headroom
(1.30× → 1.20×) costs 12 points of discount; the first 5% above spot
(1.05× → 1.02×) costs 96 points of the remaining value. A barrier is
not a haircut on the vanilla — it is a different instrument.

**The hedging nightmare, quantified.** Delta of the 1.10× contract on a
spot ladder at fixed H = 26,192 (PDE grid; MC-CRN agrees at spot):

| S / H | UAO price | UAO delta | UAO gamma | Vanilla delta |
|---:|---:|---:|---:|---:|
| 0.800 | 38.00 | +0.049 | +4.5e-05 | 0.073 |
| 0.850 | 140.33 | +0.102 | +1.7e-05 | 0.253 |
| 0.900 | 255.60 | +0.047 | −1.03e-04 | 0.531 |
| 0.909 (spot) | 265.21 | +0.015 (MC) | −1.19e-04 (MC) | 0.583 |
| 0.950 | 212.06 | −0.116 | −1.12e-04 | 0.782 |
| 0.980 | 93.33 | −0.175 | −3.2e-05 | 0.881 |
| 0.990 | 46.68 | −0.180 | −2.2e-07 | 0.905 |
| 0.995 | 23.21 | −0.179 | +1.5e-05 | 0.915 |

Read it as a hedging desk lives it. The option's *price peaks at
today's spot* (≈ S/H 0.91) and falls in both directions. Delta rises to
+0.10 at 0.85·H, collapses through zero at spot, and saturates near
**−0.18** into the barrier — while the vanilla delta marches to +0.92.
Gamma is negative across the whole upper corridor, and vega flips sign
too: **−28.6 pts per vol point** (MC-CRN) against the vanilla's +46.3.
A trader who hedges this long call with vanilla intuition — long delta,
long vega — is positioned exactly backwards on both. This sign-flipping
delta is why barrier books are hedged with barrier-spread overlays and
why issuers overhedge into the barrier — and why, in March-style gaps,
the hedging flow itself moves the underlying.

---

## Case B — The autocallable a bank would actually sell

**Structure (per 100 notional):** 3-year NIFTY autocallable reverse
convertible, quarterly observations. Autocall at **100%** of the initial
fixing (23,810.85); coupon paid on an observation date iff the fixing
is ≥ **70%** — **non-memory**, a missed coupon is gone; capital at risk
iff the final fixing is < **60%** (European knock-in), redemption then
100 × S_T/S_0. Priced on 500k antithetic paths at the calibrated flat
vol of 15.34%.

**Fair coupon: 7.11% p.a.** The price decomposes exactly (the coupon
enters linearly, verified against the bisection solver to 1e-4):

> price(c) = **94.97** (redemption leg, net of the capital-loss leg)
> \+ **70.74 × c** (coupon annuity) → c\* = (100 − 94.97)/70.74 = 7.11%

And the redemption leg itself splits (same paths, knock-in barrier sent
to zero): certain-par redemption is worth **95.18**, so the down-and-in
put the investor sells is worth **0.21 points** — and the remaining
**4.82 points** of the gap to par is pure discounting at 6.5% over the
note's short expected life. In other words, of the 5.03 points of
coupon PV the investor receives at fair, 4.82 is interest on their own
money handed back early; **0.21 points is the entire payment for
selling a 3-year tail put on the index** — under a flat-vol model that
prices that tail with ATM vol. Hold that number against the skew
caveat below.

At the fair coupon:

| Quantity | Value |
|---|---:|
| P(autocall within year 1) | 79.4% |
| P(ever autocalled) | 90.8% |
| P(capital loss) | 0.57% |
| Loss given loss | 45.2% of notional |
| Expected life | 0.78 yrs (of 3.00) |

**Where the margin sits.** Marketed 100bp below fair, at **6.11%
p.a.**, the note is worth **99.29 ± 0.01** — an issuer margin of
**0.71 points** of notional before hedging, funding and distribution
costs. Stresses at the marketed coupon: vol +5 pts → **98.10**
(−1.19); spot −10% → **97.81** (−1.48). Local Greeks: delta +0.10 pts
per +1% spot (the note is mostly a redemption-timing claim, not a
directional one), vega −0.16 pts per vol point locally, steepening to
≈ −0.24/pt across the +5 stress — the investor is short vol, and
increasingly short as vol rises.

**The honest caveat a structurer must attach.** The 0.57% capital-loss
probability is a *flat-vol GBM* number: it prices the 60% barrier with
the same 15.34% vol as the at-the-money options. The real 3 Nov 2026
smile (sibling `greeks-lab` repo) is steeply skewed — downside strikes
trade several vol points higher — and GBM tails are thinner than
NIFTY's. A skew-aware model raises the knock-in put's value, raises
the fair coupon, and fattens the loss tail. Quoting 7.11% as "the"
fair coupon without that sentence is how structured products get
mis-sold; the model's job is to make the sentence unavoidable. The
note also embeds issuer credit risk, which this pricer deliberately
isolates (single-curve discounting) rather than prices.

---

## Case C — Model agreement: does the PDE convict the Monte Carlo?

Two engines that share no code — path averaging vs a Crank-Nicolson
grid with the barrier as a boundary condition — price the same
up-and-out call (H = 27,382, 1.15× spot, T = 3m):

| Strike | MC | ± SE | PDE | \|diff\| pts | \|diff\| vol pts |
|---:|---:|---:|---:|---:|---:|
| 22,600 | 1,276.13 | 1.01 | 1,276.62 | 0.48 | 0.015 |
| 23,800 | 576.62 | 0.94 | 577.84 | 1.23 | 0.026 |
| 25,000 | 175.26 | 0.57 | 174.60 | 0.66 | 0.015 |
| 26,200 | 21.34 | 0.16 | 21.38 | 0.04 | 0.001 |

**Max disagreement: 1.23 points = 0.026 vol points**, inside Monte
Carlo error at every strike. The largest residual in the whole study
sits in Case A's 1.15× row (3.06 pts ≈ 0.07 vol pts) — the combined
bridge-correction and grid error at a barrier far enough away that
both engines are near their tolerance; it is reported, not tuned away.

**Control-variate audit (Asians).** The geometric Asian has an exact
price (Kemna–Vorst): closed form **501.61** vs geometric MC
**501.46 ± 1.05** — 0.2 SE. Using that closed form as the control for
the arithmetic Asian cuts the standard error from **0.743 to 0.012**
(63×, same paths, same seed): arithmetic Asian = **508.63 ± 0.01**.

**Monitoring bias, measured.** The same barrier priced with *discrete*
monitoring on a 63-step grid (no bridge correction): **300.88** vs
**263.11** continuous — a **14.4% overpricing** from missed intra-step
crossings. Any barrier price quoted off a daily-stepped simulation
without a bridge correction (or a PDE) carries this bias silently.

**Also in the engine** (same calibration): 3-month floating-strike
lookback call **1,481.57 ± 0.78** — 66% above the vanilla, the price of
buying every dip perfectly; 1-year monthly cliquet (local cap +5%,
floor −3%, global floor 0) **8.09% of notional**.
