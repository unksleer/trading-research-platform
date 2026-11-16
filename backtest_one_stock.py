#!/usr/bin/env python3
"""
One stock, or the stable stocks: can either be picked in advance?

Asked by Lee on 2026-11-16: when live trading starts, focus on one stock that
reads consistently and is stable. v4's ten live weeks hinted the same way (the
steady names made money, the jumpy ones lost it) on about four trades a
ticker, which is nothing. This asks the question of 5.7 years of data instead.

The rule for choosing and the test for passing are constants in this file and
were committed, with the DECISIONS.md entry of 2026-11-16, before the script
was run in anything but --check mode. --check prints pooled figures already
published on 2026-11-10 and nothing per ticker.

Same data, simulator, gate and costs as the v5 gate backtest
(backtest_regime_gate.py): frozen one-minute IEX bars, the trend gate on, $100
a trade, 0.10% slippage a side.

Two windows. Choose on SELECT, judge on CONFIRM. Nothing from CONFIRM is used
to choose.

  SELECT   entries 2021-01-04 to 2023-12-31
  CONFIRM  entries 2024-01-01 to 2026-09-03

Three questions, each with its own fixed test:

  S1  the best single stock. The ticker with the highest per-trade Sharpe on
      SELECT, among those with at least MIN_SELECT_TRADES trades there and a
      positive net in at least two of its three years.
  S2  the most stable single stock. The ticker with the lowest volatility
      (standard deviation of daily close-to-close returns) on SELECT. Chosen
      without looking at any strategy result.
  H   stable against jumpy. The six least volatile tickers on SELECT against
      the six most volatile.

A single stock (S1 or S2) passes on CONFIRM only if all four hold:
  1. at least MIN_CONFIRM_TRADES trades;
  2. net P&L above zero;
  3. profit factor at least MIN_PF and at least the gated basket's on CONFIRM;
  4. net P&L above zero in at least two of the three years 2024, 2025, 2026.

H passes if on CONFIRM the stable six have a net above zero and a profit
factor at least PF_MARGIN above the jumpy six.

Persistence, the guard against picking a lucky winner from twelve: the
Spearman rank correlation, across the twelve tickers, between average return
per trade on SELECT and on CONFIRM. At or above PERSISTENCE it counts as
"per-ticker results carry forward"; below it, a single pick that happens to
pass is not evidence that picking works.

Reported and never used to decide: every ticker on both windows, results
against holding the stock, dollars a year at $100 a trade, worst trade,
longest losing run.
"""
import argparse
import json
import os
import statistics as st
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import backtest_regime_gate as g  # noqa: E402

# ── fixed before the run ─────────────────────────────────────────────────────
SELECT_FROM, SELECT_TO = "2021-01-04", "2023-12-31"
CONFIRM_FROM, CONFIRM_TO = "2024-01-01", "2026-09-03"
MIN_SELECT_TRADES = 25
MIN_CONFIRM_TRADES = 20
MIN_PF = 1.20
PF_MARGIN = 0.10
PERSISTENCE = 0.50          # Spearman, n=12: about the 5% one-sided level
SELECT_YEARS = ("2021", "2022", "2023")
CONFIRM_YEARS = ("2024", "2025", "2026")


def load(cache):
    sessions, seed = g.load_sessions(cache), g.load_seed_closes(cache)
    raw = {}
    for tk in g.TICKERS:
        df = g.load_minutes(tk, cache)
        raw[tk] = (g._ns(df.index), df["close"].to_numpy(dtype=float))
    spy_ts, spy_px = raw[g.MARKET]
    mkt = g.market_state(spy_ts, spy_px, sessions, seed)
    trades = {}
    for tk, (ts, px) in raw.items():
        view = g.bot_view(ts, px, sessions)
        block = g.gate_flags(view, mkt, spy_ts, spy_px)[0]      # trend gate only: v5
        trades[tk] = g.simulate(tk, view, block, g.SLIPPAGE)[0]
    return sessions, raw, trades


def session_closes(ts, px, sessions):
    """{session date: last print inside the regular session}."""
    out = {}
    for d, o, x in sessions:
        lo, hi = np.searchsorted(ts, o), np.searchsorted(ts, x)
        if hi > lo:
            out[d] = float(px[hi - 1])
    return out


def volatility(closes, lo, hi):
    """SD of daily close-to-close returns, in percent, sessions lo..hi."""
    days = [d for d in sorted(closes) if lo <= d <= hi]
    rets = [closes[b] / closes[a] - 1.0 for a, b in zip(days, days[1:])]
    return st.pstdev(rets) * 100.0 if len(rets) > 1 else float("nan")


def hold_pct(closes, lo, hi):
    """Buy at the first close in the window, hold to the last."""
    days = [d for d in sorted(closes) if lo <= d <= hi]
    return (closes[days[-1]] / closes[days[0]] - 1.0) * 100.0 if len(days) > 1 else float("nan")


def by_year(rows, years):
    return {y: g.stats([x for x in rows if g.day(x["entry_t"])[:4] == y]) for y in years}


def losing_run(rows):
    worst = cur = 0
    for x in sorted(rows, key=lambda r: r["entry_t"]):
        cur = cur + 1 if x["pct"] <= 0 else 0
        worst = max(worst, cur)
    return worst


def spearman(a, b):
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def single_verdict(tk, rows, basket_pf):
    s = g.stats(rows)
    yrs = by_year(rows, CONFIRM_YEARS)
    good_years = sum(1 for y in CONFIRM_YEARS if yrs[y]["n"] and yrs[y]["net"] > 0)
    terms = {
        f"1 at least {MIN_CONFIRM_TRADES} trades": s["n"] >= MIN_CONFIRM_TRADES,
        "2 net above zero": s["net"] > 0,
        f"3 PF >= {MIN_PF:.2f} and >= basket {basket_pf:.2f}": s["pf"] >= MIN_PF and s["pf"] >= basket_pf,
        "4 positive in 2 of 3 years": good_years >= 2,
    }
    return {"ticker": tk, "stats": s, "years": {y: yrs[y]["net"] for y in CONFIRM_YEARS},
            "terms": terms, "passed": all(terms.values())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=g.DEFAULT_CACHE)
    ap.add_argument("--json", default="")
    ap.add_argument("--check", action="store_true",
                    help="pooled figures only, to confirm this is the 2026-11-10 simulation")
    args = ap.parse_args()

    sessions, raw, trades = load(args.cache)
    pooled = sorted((x for rows in trades.values() for x in rows), key=lambda x: x["entry_t"])

    whole = g.in_window(pooled, g.TEST_FROM, g.TEST_TO)
    print(g.line("gated basket, 2021-01-04 to 2026-09-03", g.stats(whole)))
    print("  published 2026-11-10: n= 915  win  71.7%  avg win +2.09%  avg loss -4.78%  PF  1.10  net $ +129.20")
    if args.check:
        return

    closes = {tk: session_closes(ts, px, sessions) for tk, (ts, px) in raw.items()}
    sel = {tk: g.in_window(rows, SELECT_FROM, SELECT_TO) for tk, rows in trades.items()}
    con = {tk: g.in_window(rows, CONFIRM_FROM, CONFIRM_TO) for tk, rows in trades.items()}
    vol = {tk: volatility(closes[tk], SELECT_FROM, SELECT_TO) for tk in g.TICKERS}
    basket_sel = g.stats(g.in_window(pooled, SELECT_FROM, SELECT_TO))
    basket_con = g.stats(g.in_window(pooled, CONFIRM_FROM, CONFIRM_TO))
    report = {"spec": {"select": [SELECT_FROM, SELECT_TO], "confirm": [CONFIRM_FROM, CONFIRM_TO],
                       "min_select_trades": MIN_SELECT_TRADES, "min_confirm_trades": MIN_CONFIRM_TRADES,
                       "min_pf": MIN_PF, "pf_margin": PF_MARGIN, "persistence": PERSISTENCE}}

    # ── every ticker, both windows ───────────────────────────────────────────
    print("\n" + "=" * 118)
    print("EVERY TICKER (gated, 0.10% slippage a side). Sorted by volatility on SELECT, calmest first.")
    table = {}
    for tk in sorted(g.TICKERS, key=lambda k: vol[k]):
        a, b = g.stats(sel[tk]), g.stats(con[tk])
        ya = by_year(sel[tk], SELECT_YEARS)
        table[tk] = {"vol": vol[tk], "select": a, "confirm": b,
                     "select_years_positive": sum(1 for y in SELECT_YEARS if ya[y]["n"] and ya[y]["net"] > 0),
                     "hold_confirm": hold_pct(closes[tk], CONFIRM_FROM, CONFIRM_TO)}
        print(f"  {tk:5} vol {vol[tk]:4.2f}% | SELECT n={a['n']:3d} win {a['win_rate']:5.1f}% PF {a['pf']:5.2f} "
              f"net ${a['net']:+7.2f} sharpe {a['sharpe']:+.3f} yrs+ {table[tk]['select_years_positive']} "
              f"| CONFIRM n={b['n']:3d} win {b['win_rate']:5.1f}% PF {b['pf']:5.2f} net ${b['net']:+7.2f} "
              f"avg {b['avg']:+.2f}% | hold {table[tk]['hold_confirm']:+7.1f}%")
    print(g.line("  basket on SELECT", basket_sel))
    print(g.line("  basket on CONFIRM", basket_con))
    report["tickers"] = table
    report["basket"] = {"select": basket_sel, "confirm": basket_con}

    # ── the choices, made on SELECT only ─────────────────────────────────────
    eligible = [tk for tk in g.TICKERS
                if table[tk]["select"]["n"] >= MIN_SELECT_TRADES and table[tk]["select_years_positive"] >= 2]
    s1 = max(eligible, key=lambda k: (table[k]["select"]["sharpe"], table[k]["select"]["net"])) if eligible else None
    ranked = sorted(g.TICKERS, key=lambda k: vol[k])
    s2 = ranked[0]
    stable, jumpy = ranked[:6], ranked[6:]
    print("\n" + "=" * 118)
    print("CHOICES, from SELECT only")
    print(f"  S1 eligible ({MIN_SELECT_TRADES}+ trades, positive in 2 of 3 years): {', '.join(sorted(eligible)) or 'none'}")
    print(f"  S1 best per-trade Sharpe on SELECT: {s1 or 'no candidate'}")
    print(f"  S2 least volatile on SELECT: {s2}")
    print(f"  H  stable six: {', '.join(stable)} | jumpy six: {', '.join(jumpy)}")

    # ── verdicts, on CONFIRM ─────────────────────────────────────────────────
    print("\n" + "=" * 118)
    print("VERDICTS, on CONFIRM")
    verdicts = {}
    for label, tk in (("S1", s1), ("S2", s2)):
        if tk is None:
            print(f"  {label}: no candidate, so nothing to confirm  => FAIL")
            verdicts[label] = {"ticker": None, "passed": False}
            continue
        v = single_verdict(tk, con[tk], basket_con["pf"])
        verdicts[label] = v
        print(g.line(f"  {label} {tk}", v["stats"]))
        print("     by year: " + "  ".join(f"{y} ${v['years'][y]:+.2f}" for y in CONFIRM_YEARS))
        print("     " + " | ".join(f"{k}: {'yes' if ok else 'NO'}" for k, ok in v["terms"].items())
              + f"  => {'PASS' if v['passed'] else 'FAIL'}")
        years = (pd.Timestamp(CONFIRM_TO) - pd.Timestamp(CONFIRM_FROM)).days / 365.25
        rank = 1 + sum(1 for k in g.TICKERS if table[k]["confirm"]["avg"] > table[tk]["confirm"]["avg"])
        print(f"     reported: ${v['stats']['net'] / years:+.2f} a year at $100 a trade | {v['stats']['n'] / years:.1f} trades a year "
              f"| strategy {sum(x['pct'] for x in con[tk]):+.1f}% on one $100 position vs holding {table[tk]['hold_confirm']:+.1f}% "
              f"| worst {v['stats']['worst']:+.2f}% | longest losing run {losing_run(con[tk])} "
              f"| rank {rank} of 12 by average trade on CONFIRM")

    gs = {name: (g.stats([x for k in grp for x in sel[k]]), g.stats([x for k in grp for x in con[k]]))
          for name, grp in (("stable", stable), ("jumpy", jumpy))}
    h_pass = gs["stable"][1]["net"] > 0 and gs["stable"][1]["pf"] >= gs["jumpy"][1]["pf"] + PF_MARGIN
    for name in ("stable", "jumpy"):
        print(g.line(f"  H {name} six, SELECT", gs[name][0]))
        print(g.line(f"  H {name} six, CONFIRM", gs[name][1]))
    print(f"     stable net above zero: {'yes' if gs['stable'][1]['net'] > 0 else 'NO'} | stable PF >= jumpy PF + {PF_MARGIN:.2f}: "
          f"{'yes' if gs['stable'][1]['pf'] >= gs['jumpy'][1]['pf'] + PF_MARGIN else 'NO'} "
          f"({gs['stable'][1]['pf']:.2f} vs {gs['jumpy'][1]['pf']:.2f})  => {'PASS' if h_pass else 'FAIL'}")
    verdicts["H"] = {"stable": stable, "jumpy": jumpy, "passed": h_pass,
                     "select": {k: v[0] for k, v in gs.items()}, "confirm": {k: v[1] for k, v in gs.items()}}

    rho = spearman([table[k]["select"]["avg"] for k in g.TICKERS], [table[k]["confirm"]["avg"] for k in g.TICKERS])
    rho_vol = spearman([vol[k] for k in g.TICKERS], [table[k]["confirm"]["avg"] for k in g.TICKERS])
    print(f"\n  PERSISTENCE: rank correlation of average trade, SELECT against CONFIRM, twelve tickers: {rho:+.2f} "
          f"(carries forward at {PERSISTENCE:+.2f} or more: {'yes' if rho >= PERSISTENCE else 'NO'})")
    print(f"  reported: rank correlation of SELECT volatility against CONFIRM average trade: {rho_vol:+.2f} "
          f"(negative = calmer stocks did better)")
    verdicts["persistence"] = {"spearman": rho, "carries_forward": rho >= PERSISTENCE, "vol_vs_confirm": rho_vol}
    report["choices"] = {"s1": s1, "s2": s2, "eligible": eligible}
    report["verdicts"] = verdicts
    if args.json:
        json.dump(report, open(args.json, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
