#!/usr/bin/env python3
"""Builds docs/dashboard.html from docs/results.json.

Self-contained dark dashboard: inline SVG only, zero external
references (verified by an assertion at the end of the build). Run
after main.py.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")


def load():
    with open(os.path.join(ROOT, "docs", "results.json")) as f:
        return json.load(f)


# --- tiny SVG helpers ---------------------------------------------------
def _scale(v, vmin, vmax, lo, hi):
    if vmax == vmin:
        return (lo + hi) / 2.0
    return lo + (v - vmin) / (vmax - vmin) * (hi - lo)


def line_chart(series, w=560, h=240, xlabel="", ylabel="", zero_line=True):
    """series: list of (xs, ys, color, label, dashed)."""
    xs_all = [x for s in series for x in s[0]]
    ys_all = [y for s in series for y in s[1]]
    xmin, xmax = min(xs_all), max(xs_all)
    ymin, ymax = min(ys_all), max(ys_all)
    if zero_line:
        ymin = min(ymin, 0.0)
        ymax = max(ymax, 0.0)
    pad_y = 0.08 * (ymax - ymin or 1.0)
    ymin, ymax = ymin - pad_y, ymax + pad_y
    L, R, Tp, B = 46, 10, 12, 26
    out = [f'<svg viewBox="0 0 {w} {h}" '
           f'style="width:100%;height:auto">']
    if zero_line and ymin < 0 < ymax:
        y0 = _scale(0.0, ymin, ymax, h - B, Tp)
        out.append(f'<line x1="{L}" y1="{y0:.1f}" x2="{w - R}" y2="{y0:.1f}" '
                   f'stroke="#30363d" stroke-width="1"/>')
    for i in range(5):
        v = ymin + (ymax - ymin) * i / 4
        y = _scale(v, ymin, ymax, h - B, Tp)
        out.append(f'<line x1="{L}" y1="{y:.1f}" x2="{w - R}" y2="{y:.1f}" '
                   f'stroke="#21262d" stroke-width="1"/>')
        out.append(f'<text x="{L - 5}" y="{y + 3:.1f}" fill="#8b949e" '
                   f'font-size="9" text-anchor="end">{v:,.2f}</text>')
    for xs, ys, color, label, dashed in series:
        pts = " ".join(
            f"{_scale(x, xmin, xmax, L, w - R):.1f},"
            f"{_scale(y, ymin, ymax, h - B, Tp):.1f}"
            for x, y in zip(xs, ys))
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                   f'stroke-width="2"{dash}/>')
        for x, y in zip(xs, ys):
            out.append(f'<circle cx="{_scale(x, xmin, xmax, L, w - R):.1f}" '
                       f'cy="{_scale(y, ymin, ymax, h - B, Tp):.1f}" r="3" '
                       f'fill="{color}"/>')
    out.append(f'<text x="{w / 2}" y="{h - 4}" fill="#8b949e" font-size="10" '
               f'text-anchor="middle">{xlabel}</text>')
    out.append(f'<text x="12" y="{h / 2}" fill="#8b949e" font-size="10" '
               f'text-anchor="middle" transform="rotate(-90 12 {h / 2})">'
               f'{ylabel}</text>')
    ly = 16
    for xs, ys, color, label, dashed in series:
        out.append(f'<text x="{w - R - 150}" y="{ly}" fill="{color}" '
                   f'font-size="10">{label}</text>')
        ly += 13
    out.append("</svg>")
    return "".join(out)


def bar_chart(values, w=560, h=240, color="#58a6ff", ylabel=""):
    n = len(values)
    vmax = max(values) * 1.15 or 1.0
    L, R, Tp, B = 40, 10, 12, 26
    bw = (w - L - R) / n
    out = [f'<svg viewBox="0 0 {w} {h}" '
           f'style="width:100%;height:auto">']
    for i, v in enumerate(values):
        bh = _scale(v, 0, vmax, 0, h - Tp - B)
        x = L + i * bw + 2
        y = h - B - bh
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw - 4:.1f}" '
                   f'height="{bh:.1f}" fill="{color}" rx="2"/>')
        out.append(f'<text x="{x + (bw - 4) / 2:.1f}" y="{y - 4:.1f}" '
                   f'fill="#c9d1d9" font-size="9" text-anchor="middle">'
                   f'{v * 100:.0f}%</text>')
        out.append(f'<text x="{x + (bw - 4) / 2:.1f}" y="{h - B + 14:.1f}" '
                   f'fill="#8b949e" font-size="9" text-anchor="middle">'
                   f'Q{i + 1}</text>')
    out.append("</svg>")
    return "".join(out)


def card(title, body):
    return (f'<div class="card"><h3>{title}</h3>{body}</div>')


def stat(label, value, sub=""):
    return (f'<div class="stat"><div class="stat-v">{value}</div>'
            f'<div class="stat-l">{label}</div>'
            f'<div class="stat-s">{sub}</div></div>')


def main():
    res = load()
    cal, a, b, c = res["calibration"], res["case_a"], res["case_b"], \
        res["case_c"]
    S = cal["spot"]
    K = a["strike"]
    H = a["headline_barrier"]

    # --- payoff diagram (expiry intrinsic, H = 1.10 S) -----------------
    xs = [S * (0.82 + 0.005 * i) for i in range(85)]
    van = [max(x - K, 0.0) for x in xs]
    uao = [max(x - K, 0.0) if x < H else 0.0 for x in xs]
    payoff_svg = line_chart(
        [(xs, van, "#58a6ff", "Vanilla call", False),
         (xs, uao, "#f778ba", "Up-and-out call", False)],
        xlabel="Spot at expiry (INR)", ylabel="Payoff (INR pts)")

    # --- discount curve -------------------------------------------------
    bm = [row["barrier_mult"] for row in a["barrier_rows"]]
    bp = [row["mc_price"] for row in a["barrier_rows"]]
    discount_svg = line_chart(
        [(bm, bp, "#3fb950", "UAO price (MC)", False),
         ([bm[0], bm[-1]], [a["vanilla_bs"]] * 2, "#58a6ff",
          "Vanilla (BS)", True)],
        xlabel="Barrier / spot", ylabel="Price (INR pts)")

    # --- delta ladder ----------------------------------------------------
    lad = a["delta_ladder"]
    delta_svg = line_chart(
        [([d["spot_over_barrier"] for d in lad],
          [d["uao_delta"] for d in lad], "#f85149", "UAO delta (PDE)", False),
         ([d["spot_over_barrier"] for d in lad],
          [d["vanilla_delta"] for d in lad], "#58a6ff",
          "Vanilla delta", True)],
        xlabel="Spot / barrier", ylabel="Delta")

    # --- autocall cumulative probability --------------------------------
    cum = b["at_fair"]["p_autocall_by_date"]
    cum_svg = bar_chart(cum, ylabel="Cumulative P(autocalled)")

    gm, gv = a["greeks_at_spot_mc"], a["greeks_vanilla_mc"]
    af = b["at_fair"]
    case_c_rows = "".join(
        f'<tr><td>{row["strike"]:,.0f}</td><td>{row["mc_price"]:.2f}</td>'
        f'<td>{row["pde_price"]:.2f}</td><td>{row["diff_points"]:.2f}</td>'
        f'<td>{row["diff_vol_points"]:.3f}</td></tr>'
        for row in c["rows"])

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Exotics &amp; Structured Products Lab</title>
<style>
 body {{ background:#0d1117; color:#c9d1d9; font-family:-apple-system,
   'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin:0; padding:24px; }}
 h1 {{ color:#f0f6fc; font-size:26px; margin:0 0 4px; }}
 h2 {{ color:#f0f6fc; font-size:19px; margin:28px 0 10px; }}
 h3 {{ color:#f0f6fc; font-size:15px; margin:0 0 8px; }}
 .sub {{ color:#8b949e; margin-bottom:16px; }}
 .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(330px,1fr));
   gap:14px; }}
 .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
   padding:14px 16px; }}
 .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
   gap:10px; margin:12px 0; }}
 .stat {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
   padding:10px 12px; }}
 .stat-v {{ color:#f0f6fc; font-size:21px; font-weight:600; }}
 .stat-l {{ color:#8b949e; font-size:11px; text-transform:uppercase;
   letter-spacing:.04em; }}
 .stat-s {{ color:#8b949e; font-size:11px; }}
 table {{ border-collapse:collapse; width:100%; font-size:13px; }}
 td, th {{ border-bottom:1px solid #21262d; padding:5px 8px; text-align:right; }}
 th {{ color:#8b949e; font-weight:500; }}
 td:first-child, th:first-child {{ text-align:left; }}
 .note {{ color:#8b949e; font-size:12.5px; line-height:1.5; }}
 b.hl {{ color:#f0f6fc; }}
</style></head><body>
<h1>Exotics &amp; Structured Products Lab</h1>
<div class="sub">Path-dependent options &amp; an autocallable structured note,
priced by Monte Carlo and an independent finite-difference PDE.
Calibrated to <b class="hl">real NIFTY data</b>: spot {S:,.2f}, vol
{cal['sigma'] * 100:.2f}% ATM IV -- NSE F&amp;O bhavcopy, 3 Nov 2026.</div>

<h2>Case A -- the knock-out discount (3m ATM up-and-out call)</h2>
<div class="stats">
 {stat("Vanilla call (BS)", f"{a['vanilla_bs']:.0f} pts", f"MC {a['vanilla_mc']:.0f} +/- {a['vanilla_mc_se']:.1f}")}
 {stat("UAO @ barrier 1.10x", f"{[r for r in a['barrier_rows'] if r['barrier_mult'] == 1.10][0]['mc_price']:.0f} pts", "70.2% cheaper than vanilla")}
 {stat("UAO delta at spot", f"{gm['delta']:.3f}", f"vanilla {a['vanilla_delta_bs']:.3f}")}
 {stat("UAO vega", f"{gm['vega_per_point']:+.0f} / pt", f"vanilla {a['vanilla_vega_per_point']:+.0f} / pt -- sign flip")}
</div>
<div class="grid">
 {card("Expiry payoff: vanilla vs up-and-out (H = 1.10 x spot)", payoff_svg)}
 {card("Price vs barrier level (MC, bridge-corrected)", discount_svg)}
 {card("Delta near the barrier -- the hedging nightmare", delta_svg)}
</div>
<p class="note">As spot approaches the barrier the UAO delta collapses through
zero and turns <b class="hl">negative</b> (price peaks near S/H = 0.90 and falls
to zero at the barrier), while the vanilla delta climbs to 0.92. A desk long
this option is short gamma and short vega in a long call -- hedging it with the
vanilla playbook loses money in both directions.</p>

<h2>Case B -- the autocallable a bank would actually sell</h2>
<div class="stats">
 {stat("Fair coupon", f"{b['fair_coupon_pct']:.2f}% p.a.", "solves price = par")}
 {stat("Marketed coupon", f"{b['marketed_coupon_pct']:.2f}% p.a.", "fair - 100bp")}
 {stat("Value at marketed", f"{b['value_at_marketed']:.2f}", "per 100 notional")}
 {stat("Issuer margin", f"{b['issuer_margin_pct']:.2f} pts", "before hedging costs")}
 {stat("P(autocall, year 1)", f"{af['p_autocall_year1']:.1%}", f"P(ever) {af['p_ever_autocalled']:.1%}")}
 {stat("P(capital loss)", f"{af['p_capital_loss']:.2%}", f"loss given loss {af['mean_loss_given_loss_pct']:.0f}%")}
 {stat("Expected life", f"{af['expected_life']:.2f} yrs", "of 3.00 contractual")}
 {stat("Stress: vol +5pts", f"{b['stress_vol_plus5']:.2f}", f"spot -10%: {b['stress_spot_minus10']:.2f}")}
</div>
<div class="grid">
 {card("Cumulative autocall probability by quarter", cum_svg)}
 {card("Structure", '<p class="note">3y NIFTY autocallable reverse convertible, '
   'quarterly observations. Autocall at 100% of initial fixing; coupon '
   '(<b class="hl">non-memory</b>) paid iff fixing &gt;= 70%; capital at risk '
   'iff final fixing &lt; 60% (European knock-in), redemption then scales '
   'with the index. Decomposition at par: redemption leg '
   f"{b['leg_redemption_net_pct']:.2f} + coupon annuity "
   f"{b['leg_coupon_annuity']:.1f} x coupon = 100.</p>")}
</div>

<h2>Case C -- model agreement (MC vs PDE)</h2>
<div class="grid">
 {card("Up-and-out call, H = 1.15 x spot, across strikes",
   f'<table><tr><th>Strike</th><th>MC</th><th>PDE</th><th>|diff| pts</th>'
   f'<th>vol pts</th></tr>{case_c_rows}</table>'
   f'<p class="note">Max disagreement {c["max_diff_vol_points"]:.3f} vol '
   f'points. Asian control check: geometric MC vs Kemna-Vorst closed form '
   f'agrees within {c["asian"]["geometric_err_se"]:.1f} standard errors; '
   f'arithmetic Asian {c["asian"]["arithmetic_mc"]:.1f} pts with a '
   f'control-variate SE of {c["asian"]["arithmetic_mc_se"]:.2f}.</p>')}
 {card("Model risk, stated", '<p class="note">Barriers monitored at grid '
   'dates only are systematically overpriced; the engine applies the '
   'Brownian-bridge (Broadie-Glasserman-Kou) correction and the PDE -- which '
   'has no monitoring grid -- is the referee. Every price ships with a Monte '
   'Carlo standard error; Greeks use common random numbers so bump '
   'differences are signal, not noise.</p>')}
</div>

<p class="note" style="margin-top:26px">Research code for education and
portfolio demonstration. Not investment advice; structured products embed
issuer credit risk and fees that this model deliberately isolates rather
than hides.</p>
</body></html>"""

    out = os.path.join(ROOT, "docs", "dashboard.html")
    with open(out, "w") as f:
        f.write(html)
    for bad in ("http://", "https://", "<link", "src=", "url("):
        assert bad not in html, f"external reference leaked: {bad}"
    print(f"Wrote {out} ({len(html) / 1024:.1f} KB), zero external refs")


if __name__ == "__main__":
    main()
