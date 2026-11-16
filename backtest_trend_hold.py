#!/usr/bin/env python3
"""
Hold while the trend is up: against dip-buying, and against simply holding.

Asked by Lee on 2026-11-16, after "how do the consistent few do it". Two
habits came up that this project had never tested: trade with the trend, and
let winners be bigger than losers. Every strategy tried here so far buys a dip
and sells a small bounce (average win about +2%, average loss about -5%). This
tests the other kind of trade on the same data.

The rule, the comparison and the pass/fail test are constants in this file and
were committed, with the DECISIONS.md entry of 2026-11-16, before the script
was run. Only its unit tests, on made-up prices, were run before that.

THE RULE (T200). For each stock separately, once a day:

  after a session closes, compare its close with the average of its last 200
  session closes (that one included). At or above the average: be in the
  stock. Below: be out. Act at the next session's open.

200 sessions is the standard published trend rule (the ten-month average); it
was not chosen from this data. 50 and 100 are reported as sensitivity and
never used to decide.

WHAT IT IS RUN ON. The calm six fixed by the one-stock study before this was
thought of: XLP, JNJ, PG, SPY, XLU, WMT. $100 a position, 0.10% slippage a
side, frozen one-minute IEX cache. Window: sessions 2021-06-01 to 2026-09-03.
It starts in June 2021 because the data starts in July 2020 and 200 sessions
have to exist first; every approach is measured on that same window.

THE COMPARISON, same six stocks, same window, same costs, $100 a slot:

  HOLD   buy at the first open, never sell.
  DIP    the v5 strategy as registered (RSI dip-buying with the trend gate).
  T200   the rule above.

Every figure is marked to market at each session's close, so the three are
compared on the same footing: what the six $100 slots were worth each day.

T200 PASSES only if all five hold, for the six together:
  1. net P&L above zero;
  2. net P&L above DIP's;
  3. largest drawdown smaller than HOLD's;
  4. average winning trade at least WIN_LOSS_RATIO times the average losing
     trade (the "winners bigger than losers" claim itself);
  5. up in at least MIN_GOOD_YEARS of the six calendar years 2021 to 2026.

Beating HOLD on return is deliberately not a pass term, and is reported first:
a trend rule is out of the market part of the time, so in a rising market it
is expected to make less than holding. What it is supposed to buy is a smaller
drawdown. Whether that trade is worth it is Lee's judgement, not a test.

Reported and never used to decide: each ticker, 50 and 100 sessions, the
jumpy six and all twelve, the split into 2021-2023 and 2024-2026.
"""
import argparse
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import backtest_regime_gate as g  # noqa: E402

# ── fixed before the run ─────────────────────────────────────────────────────
TREND_SESSIONS = 200
SENSITIVITY = (50, 100)
WINDOW_FROM, WINDOW_TO = "2021-06-01", "2026-09-03"
CALM = ["XLP", "JNJ", "PG", "SPY", "XLU", "WMT"]
JUMPY = ["QQQ", "SLV", "DIS", "LPL", "META", "TSLA"]
USD = 100.0
SLIP = g.SLIPPAGE
WIN_LOSS_RATIO = 2.0
MIN_GOOD_YEARS = 4
YEARS = ("2021", "2022", "2023", "2024", "2025", "2026")
SPLIT = "2024-01-01"


def session_bars(ts, opens, closes, sessions):
    """[(date, first open, last close)] for sessions that have prints."""
    out = []
    for d, o, x in sessions:
        lo, hi = np.searchsorted(ts, o), np.searchsorted(ts, x)
        if hi > lo:
            out.append((d, float(opens[lo]), float(closes[hi - 1])))
    return out


def trend_hold(bars, n, lo=WINDOW_FROM, hi=WINDOW_TO, slip=SLIP, usd=USD):
    """
    Hold while the last completed close is at or above its n-session average.

    The decision for session i uses closes up to session i-1 only and is acted
    on at session i's open. Returns (trades, equity) where equity maps each
    session date in the window to realised P&L plus the open position marked
    at that close, net of the cost of selling it. A position still open at the
    end of the window is closed at the last close and flagged.
    """
    days = [b[0] for b in bars]
    opens = [b[1] for b in bars]
    closes = [b[2] for b in bars]
    trades, equity, realized, pos, last = [], {}, 0.0, None, None
    for i, d in enumerate(days):
        if d < lo or d > hi:
            continue
        if i >= n:
            want = not (closes[i - 1] < sum(closes[i - n:i]) / n)
            if want and pos is None:
                fill = opens[i] * (1 + slip)
                pos = {"entry_day": d, "fill": fill, "shares": usd / fill}
            elif not want and pos is not None:
                out = opens[i] * (1 - slip)
                pnl = pos["shares"] * (out - pos["fill"])
                realized += pnl
                trades.append({"entry_day": pos["entry_day"], "exit_day": d,
                               "pct": pnl / usd * 100.0, "open_at_end": False})
                pos = None
        mark = pos["shares"] * (closes[i] * (1 - slip) - pos["fill"]) if pos else 0.0
        equity[d] = realized + mark
        last = i
    if pos is not None and last is not None:
        pnl = pos["shares"] * (closes[last] * (1 - slip) - pos["fill"])
        trades.append({"entry_day": pos["entry_day"], "exit_day": days[last],
                       "pct": pnl / usd * 100.0, "open_at_end": True})
    return trades, equity


def buy_and_hold(bars, lo=WINDOW_FROM, hi=WINDOW_TO, slip=SLIP, usd=USD):
    """Buy at the first open in the window, mark at every close."""
    equity, shares, fill = {}, None, None
    for d, o, c in bars:
        if d < lo or d > hi:
            continue
        if shares is None:
            fill = o * (1 + slip)
            shares = usd / fill
        equity[d] = shares * (c * (1 - slip) - fill)
    return equity


def dip_equity(trades, bars, lo=WINDOW_FROM, hi=WINDOW_TO, slip=SLIP, usd=USD):
    """
    The dip-buying trades entered in the window, marked the same way: closed
    trades at their realised result from the exit day on, open ones at that
    day's close. Returns (trades entered in the window, equity).
    """
    mine = [x for x in trades if lo <= g.day(x["entry_t"]) <= hi]
    spans = [(g.day(x["entry_t"]), g.day(x["exit_t"]), x) for x in mine]
    equity = {}
    for d, _, c in bars:
        if d < lo or d > hi:
            continue
        total = 0.0
        for start, end, x in spans:
            if end <= d:
                total += x["pct"] / 100.0 * usd
            elif start <= d:
                cost = x["entry_px"] * (1 + slip)
                total += (c * (1 - slip) - cost) / cost * usd
        equity[d] = total
    return mine, equity


def add(curves):
    """Sum equity curves over the dates they all share."""
    days = sorted(set.intersection(*(set(c) for c in curves))) if curves else []
    return {d: sum(c[d] for c in curves) for d in days}


def max_drawdown(equity):
    """Largest fall from a running peak, in dollars. The curve starts at 0."""
    peak, worst = 0.0, 0.0
    for d in sorted(equity):
        peak = max(peak, equity[d])
        worst = max(worst, peak - equity[d])
    return worst


def by_year(equity, years=YEARS):
    """Change in the curve over each calendar year."""
    out, prev = {}, 0.0
    for y in years:
        days = [d for d in sorted(equity) if d[:4] == y]
        if days:
            out[y] = equity[days[-1]] - prev
            prev = equity[days[-1]]
    return out


def shape(trades):
    wins = [t["pct"] for t in trades if t["pct"] > 0]
    losses = [t["pct"] for t in trades if t["pct"] <= 0]
    aw = st.mean(wins) if wins else 0.0
    al = st.mean(losses) if losses else 0.0
    return {"n": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate": 100.0 * len(wins) / len(trades) if trades else 0.0,
            "avg_win": aw, "avg_loss": al,
            "ratio": (aw / abs(al)) if al else float("inf") if aw else 0.0}


def time_in(trades, equity, key_in="entry_day", key_out="exit_day"):
    """Share of the window's sessions spent in a position."""
    days = sorted(equity)
    held = sum(1 for d in days if any(t[key_in] <= d < t[key_out] or
                                      (t.get("open_at_end") and t[key_in] <= d) for t in trades))
    return 100.0 * held / len(days) if days else 0.0


def summarise(equity, capital):
    days = sorted(equity)
    net = equity[days[-1]] if days else 0.0
    yrs = by_year(equity)
    return {"net": net, "pct": 100.0 * net / capital, "drawdown": max_drawdown(equity),
            "drawdown_pct": 100.0 * max_drawdown(equity) / capital,
            "years": yrs, "good_years": sum(1 for v in yrs.values() if v > 0),
            "first_half": equity[max(d for d in days if d < SPLIT)] if days else 0.0}


def verdict(t200, dip, hold, trades):
    sh = shape(trades)
    terms = {
        "1 net above zero": t200["net"] > 0,
        "2 net above dip-buying": t200["net"] > dip["net"],
        "3 drawdown smaller than holding": t200["drawdown"] < hold["drawdown"],
        f"4 average win >= {WIN_LOSS_RATIO:.0f}x average loss": sh["ratio"] >= WIN_LOSS_RATIO,
        f"5 up in {MIN_GOOD_YEARS} of 6 years": t200["good_years"] >= MIN_GOOD_YEARS,
    }
    return terms, all(terms.values())


def row(label, s, extra=""):
    yrs = "  ".join(f"{y} {s['years'].get(y, 0.0):+7.2f}" for y in YEARS)
    return (f"  {label:22} net ${s['net']:+8.2f} ({s['pct']:+6.1f}%)  worst drawdown ${s['drawdown']:7.2f} "
            f"({s['drawdown_pct']:5.1f}%)  up years {s['good_years']}/6 | {yrs}{extra}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=g.DEFAULT_CACHE)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    sessions, seed = g.load_sessions(args.cache), g.load_seed_closes(args.cache)
    bars, raw = {}, {}
    for tk in g.TICKERS:
        df = g.load_minutes(tk, args.cache)
        ts = g._ns(df.index)
        raw[tk] = (ts, df["close"].to_numpy(dtype=float))
        bars[tk] = session_bars(ts, df["open"].to_numpy(dtype=float), raw[tk][1], sessions)
    spy_ts, spy_px = raw[g.MARKET]
    mkt = g.market_state(spy_ts, spy_px, sessions, seed)

    dip_cache = {}

    def dip_trades(tk):
        if tk not in dip_cache:
            view = g.bot_view(raw[tk][0], raw[tk][1], sessions)
            dip_cache[tk] = g.simulate(tk, view, g.gate_flags(view, mkt, spy_ts, spy_px)[0], g.SLIPPAGE)[0]
        return dip_cache[tk]

    def group(tickers, n):
        t_curves, h_curves, d_curves, t_trades, d_trades, per = [], [], [], [], [], {}
        for tk in tickers:
            tr, eq = trend_hold(bars[tk], n)
            hold = buy_and_hold(bars[tk])
            dt, deq = dip_equity(dip_trades(tk), bars[tk])
            t_curves.append(eq); h_curves.append(hold); d_curves.append(deq)
            t_trades += tr; d_trades += dt
            per[tk] = {"trend": summarise(eq, USD), "hold": summarise(hold, USD), "dip": summarise(deq, USD),
                       "trend_shape": shape(tr), "trend_time_in": time_in(tr, eq), "dip_n": len(dt)}
        cap = USD * len(tickers)
        return {"trend": summarise(add(t_curves), cap), "hold": summarise(add(h_curves), cap),
                "dip": summarise(add(d_curves), cap), "trend_trades": t_trades, "dip_trades": d_trades,
                "per": per, "capital": cap}

    report = {"spec": {"sessions": TREND_SESSIONS, "window": [WINDOW_FROM, WINDOW_TO], "calm": CALM,
                       "win_loss_ratio": WIN_LOSS_RATIO, "min_good_years": MIN_GOOD_YEARS}}
    calm = group(CALM, TREND_SESSIONS)
    sh = shape(calm["trend_trades"])
    dsh = shape([{"pct": x["pct"]} for x in calm["dip_trades"]])
    days = len(add([buy_and_hold(bars[tk]) for tk in CALM]))
    print(f"calm six, {WINDOW_FROM} to {WINDOW_TO}, {days} sessions, six $100 slots, 0.10% slippage a side, marked at each close")
    print("=" * 150)
    print(row("HOLD", calm["hold"]))
    print(row("DIP (v5)", calm["dip"]))
    print(row(f"T{TREND_SESSIONS}", calm["trend"]))
    print(f"  first half (to 2023) / second half:  HOLD ${calm['hold']['first_half']:+.2f} / ${calm['hold']['net'] - calm['hold']['first_half']:+.2f}"
          f"   DIP ${calm['dip']['first_half']:+.2f} / ${calm['dip']['net'] - calm['dip']['first_half']:+.2f}"
          f"   T{TREND_SESSIONS} ${calm['trend']['first_half']:+.2f} / ${calm['trend']['net'] - calm['trend']['first_half']:+.2f}")
    print(f"  T{TREND_SESSIONS} trades: n={sh['n']} win {sh['win_rate']:.1f}% avg win {sh['avg_win']:+.2f}% avg loss {sh['avg_loss']:+.2f}% "
          f"win/loss size {sh['ratio']:.2f}x | DIP trades: n={dsh['n']} win {dsh['win_rate']:.1f}% avg win {dsh['avg_win']:+.2f}% "
          f"avg loss {dsh['avg_loss']:+.2f}% win/loss size {dsh['ratio']:.2f}x")
    terms, ok = verdict(calm["trend"], calm["dip"], calm["hold"], calm["trend_trades"])
    print("  VERDICT T200 on the calm six: " + " | ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in terms.items())
          + f"  => {'PASS' if ok else 'FAIL'}")
    report["calm"] = {k: calm[k] for k in ("trend", "hold", "dip", "per")}
    report["calm"]["trend_shape"], report["calm"]["dip_shape"] = sh, dsh
    report["verdict"] = {"terms": terms, "passed": ok}

    print("\nEACH CALM TICKER (one $100 slot)")
    for tk in CALM:
        p = calm["per"][tk]
        print(f"  {tk:4} HOLD ${p['hold']['net']:+7.2f} dd ${p['hold']['drawdown']:6.2f} | DIP ${p['dip']['net']:+7.2f} dd ${p['dip']['drawdown']:6.2f} n={p['dip_n']:3d} "
              f"| T{TREND_SESSIONS} ${p['trend']['net']:+7.2f} dd ${p['trend']['drawdown']:6.2f} n={p['trend_shape']['n']:2d} win {p['trend_shape']['win_rate']:4.0f}% "
              f"in market {p['trend_time_in']:3.0f}% up years {p['trend']['good_years']}/6")

    print("\nREPORTED, NOT USED TO DECIDE")
    sens = {}
    for n in SENSITIVITY:
        s_ = group(CALM, n); shn = shape(s_["trend_trades"])
        sens[n] = {"trend": s_["trend"], "shape": shn}
        print(row(f"calm six, T{n}", s_["trend"], f" | n={shn['n']} win {shn['win_rate']:.0f}% size {shn['ratio']:.2f}x"))
    for name, tickers in (("jumpy six", JUMPY), ("all twelve", CALM + JUMPY)):
        s_ = group(tickers, TREND_SESSIONS); shn = shape(s_["trend_trades"])
        sens[name] = {k: s_[k] for k in ("trend", "hold", "dip")}
        print(row(f"{name}, HOLD", s_["hold"]))
        print(row(f"{name}, DIP (v5)", s_["dip"]))
        print(row(f"{name}, T{TREND_SESSIONS}", s_["trend"], f" | n={shn['n']} win {shn['win_rate']:.0f}% size {shn['ratio']:.2f}x"))
    report["reported"] = sens
    if args.json:
        json.dump(report, open(args.json, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
