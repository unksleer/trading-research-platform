#!/usr/bin/env python3
"""
Market-regime entry gate on the stocks mean-reversion rule (the v5 question).

One question: does refusing NEW entries while the broad market is weak improve
the v4 rule, on data the gate was not found on?  The gate and the pass/fail
test were fixed in DECISIONS.md (2026-11-10, "rule and pass/fail test fixed
before the run") before this was run with a gate.  Nothing here tunes them.

Unlike backtest_stock_exits.py this is a minute-by-minute replay of the live
loop in stock_bot.py rather than an hourly-close shortcut:

  * hourly bars on clock hours, built from one-minute IEX bars, INCLUDING the
    bar still forming, which is what the bot sees when it polls each minute;
  * RSI 14 (Wilder) on those bars; entry when the last completed bar is under
    35 and the forming bar is at or above it;
  * decisions only while the market is open, plus the first look at the open
    on whatever the last pre-market print was;
  * exits in the bot's order: 5% stop, 8% target, 1.5% trail armed at +1%,
    RSI exit through 65; trail and RSI exit may not close below entry;
  * the 6-hour cooldown after a losing exit that the live bots run with.

The gate (entries only, exits are never gated):

  trend     SPY's close on the last completed session is below the average of
            its last N completed session closes (N = 50).
  down day  SPY's latest price at the moment of the signal is more than X%
            below its close on the last completed session (X = 1.0).

Both use only prices known at the moment of the signal.

Result on 2026-11-10 (entries 2021-01-04 to 2026-09-03, 0.10% slippage a
side): ungated 1,343 trades, 69.5% wins, PF 0.97, -$56. Trend gate 915 trades,
71.7%, PF 1.10, +$129, and it passed the three fixed terms. Trend-or-down-day
PF 1.02, failed: trades entered on a down day were the BEST group (PF 1.53),
the opposite of what the stop-out study suggested. $152 of the $182 the trend
gate saves is 2022, and the gated edge is t 0.76 on effective trades, so this
is a bear-market switch on a thin edge, not a proven one. See DECISIONS.md.

    .venv/bin/python backtest_regime_gate.py            # uses the bar cache
    .venv/bin/python backtest_regime_gate.py --json out.json

Bars are cached under scratch/regime_gate_cache (git-ignored) and fetched from
Alpaca when missing, so a re-run on the same cache is reproducible and a fresh
fetch is not byte-for-byte (dividend adjustments move old prices slightly).
"""
import argparse
import csv
import glob
import json
import os
import pickle
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TICKERS = ["DIS", "JNJ", "LPL", "META", "PG", "QQQ", "SLV", "SPY", "TSLA", "WMT", "XLP", "XLU"]
MARKET = "SPY"

# v4 as it ran (experiments/2026-09-stocks-mean-reversion-v4.json + .env)
RSI_PERIOD, OVERSOLD, OVERBOUGHT = 14, 35.0, 65.0
STOP_LOSS, TAKE_PROFIT = 5.0, 8.0
TRAIL, TRAIL_ACTIVATION = 1.5, 1.0
COOLDOWN_HOURS = 6.0
USD = 100.0
SLIPPAGE = 0.0010          # per side, the project's backtest convention
EFFECTIVE_SYMBOLS = 4.9    # twelve correlated tickers measure as 4.9 independent ones

# Fixed before the run.
TREND_DAYS, DOWN_PCT = 50, 1.0
TEST_FROM, TEST_TO = "2021-01-04", "2026-09-03"      # independent test
FOUND_FROM, FOUND_TO = "2026-09-04", "2026-11-10"    # where the gate was found
DATA_FROM = datetime(2020, 7, 1, tzinfo=timezone.utc)
DATA_TO = datetime(2026, 11, 10, 17, 45, tzinfo=timezone.utc)

NS_HOUR = 3_600_000_000_000
DEFAULT_CACHE = os.path.join(HERE, "scratch", "regime_gate_cache")


# ── data ─────────────────────────────────────────────────────────────────────
def _keys():
    from utils import env_loader
    env_loader.load()
    return os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")


def _months(a, b):
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        lo = datetime(y, m, 1, tzinfo=timezone.utc)
        y, m = (y + (m == 12), m % 12 + 1)
        yield lo, min(datetime(y, m, 1, tzinfo=timezone.utc), b)


def load_minutes(ticker, cache):
    """One-minute IEX bars, split and dividend adjusted, oldest first."""
    path = os.path.join(cache, f"min_{ticker}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    client = StockHistoricalDataClient(*_keys())
    parts = []
    for lo, hi in _months(DATA_FROM, DATA_TO):
        df = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=ticker, timeframe=TimeFrame.Minute, start=lo,
            end=hi - timedelta(seconds=1), adjustment=Adjustment.ALL, feed=DataFeed.IEX)).df
        if df is not None and not df.empty:
            if isinstance(df.index, pd.MultiIndex):
                df = df.xs(ticker, level=0)
            parts.append(df[["open", "high", "low", "close", "volume"]])
    full = pd.concat(parts).sort_index()
    full = full[~full.index.duplicated()]
    os.makedirs(cache, exist_ok=True)
    pickle.dump(full, open(path, "wb"))
    return full


def load_sessions(cache):
    """Regular sessions as (open_ns, close_ns) UTC, early closes included."""
    path = os.path.join(cache, "sessions.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetCalendarRequest
    key, secret = _keys()
    cal = TradingClient(key, secret, paper=True).get_calendar(
        GetCalendarRequest(start=DATA_FROM.date(), end=DATA_TO.date()))
    rows = []
    for c in cal:
        o = pd.Timestamp(c.open).tz_localize("America/New_York").tz_convert("UTC")
        x = pd.Timestamp(c.close).tz_localize("America/New_York").tz_convert("UTC")
        rows.append((str(c.date), o.value, x.value))
    os.makedirs(cache, exist_ok=True)
    pickle.dump(rows, open(path, "wb"))
    return rows


def load_seed_closes(cache):
    """SPY daily closes before the minute data starts, to seed the long averages."""
    path = os.path.join(cache, "spy_day_seed.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    df = StockHistoricalDataClient(*_keys()).get_stock_bars(StockBarsRequest(
        symbol_or_symbols=MARKET, timeframe=TimeFrame.Day,
        start=datetime(2019, 6, 1, tzinfo=timezone.utc), end=datetime(2020, 7, 27, tzinfo=timezone.utc),
        adjustment=Adjustment.ALL, feed=DataFeed.IEX)).df
    closes = [] if df is None or df.empty else [float(x) for x in df["close"].values]
    pickle.dump(closes, open(path, "wb"))
    return closes


def _ns(index):
    idx = pd.DatetimeIndex(index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert("UTC").as_unit("ns").asi8


# ── the bot's view, minute by minute ─────────────────────────────────────────
def wilder(values, period):
    """pandas .ewm(alpha=1/period, adjust=False).mean() over values[1:], NaN at 0."""
    out = np.full(len(values), np.nan)
    if len(values) > 1:
        a = 1.0 / period
        acc = values[1]
        out[1] = acc
        for i in range(2, len(values)):
            acc = acc * (1 - a) + a * values[i]
            out[i] = acc
    return out


def bot_view(ts, px, sessions):
    """
    What the bot sees at every moment it would decide.

    Returns evaluation points in time order: time, price, RSI of the bar in
    progress, RSI of the bar before it, and the session each belongs to. The
    first point of each session is the look the bot takes at the open, on the
    last print before it.
    """
    bucket = ts // NS_HOUR
    new_bar = np.r_[True, bucket[1:] != bucket[:-1]]
    bar_id = np.cumsum(new_bar) - 1
    last_of_bar = np.r_[np.nonzero(new_bar)[0][1:] - 1, len(ts) - 1]
    hclose = px[last_of_bar]

    delta = np.r_[np.nan, np.diff(hclose)]
    gain = np.where(delta > 0, delta, 0.0); gain[0] = np.nan
    loss = np.where(delta < 0, -delta, 0.0); loss[0] = np.nan
    ag, al = wilder(gain, RSI_PERIOD), wilder(loss, RSI_PERIOD)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi_done = np.where(al > 0, 100 - 100 / (1 + ag / al), np.nan)

    a = 1.0 / RSI_PERIOD
    prev_bar = bar_id - 1
    ok = prev_bar >= 1
    pb = np.where(ok, prev_bar, 1)
    move = px - hclose[pb]
    agf = ag[pb] * (1 - a) + a * np.where(move > 0, move, 0.0)
    alf = al[pb] * (1 - a) + a * np.where(move < 0, -move, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi_now = np.where(ok & (alf > 0), 100 - 100 / (1 + agf / alf), np.nan)
    rsi_prev = np.where(ok, rsi_done[pb], np.nan)

    idx, when, sess = [], [], []
    for s, (_, o, x) in enumerate(sessions):
        lo, hi = np.searchsorted(ts, o), np.searchsorted(ts, x)
        if lo > 0:                       # the look at the open, on the last earlier print
            idx.append(np.array([lo - 1])); when.append(np.array([o])); sess.append(np.array([s]))
        if hi > lo:
            r = np.arange(lo, hi)
            idx.append(r); when.append(ts[r]); sess.append(np.full(hi - lo, s))
    idx = np.concatenate(idx); when = np.concatenate(when); sess = np.concatenate(sess)
    return {"t": when, "px": px[idx], "rsi": rsi_now[idx], "prev": rsi_prev[idx], "sess": sess}


def market_state(spy_ts, spy_px, sessions, seed):
    """Per session: SPY's close, the previous close, and trailing averages of prior closes."""
    closes = np.full(len(sessions), np.nan)
    for s, (_, o, x) in enumerate(sessions):
        lo, hi = np.searchsorted(spy_ts, o), np.searchsorted(spy_ts, x)
        if hi > lo:
            closes[s] = spy_px[hi - 1]
    first = int(np.argmax(~np.isnan(closes)))
    hist = np.r_[np.array(seed, dtype=float), closes[first:]]
    off = len(seed) - first              # hist index of session s is s + off
    prev_close = np.full(len(sessions), np.nan)
    avgs = {n: np.full(len(sessions), np.nan) for n in (20, 50, 100, 200)}
    for s in range(first + 1, len(sessions)):
        h = s + off
        prev_close[s] = hist[h - 1]
        for n, arr in avgs.items():
            if h - n >= 0:
                arr[s] = np.nanmean(hist[h - n:h])
    return {"close": closes, "prev_close": prev_close, "avg": avgs}


def gate_flags(view, mkt, spy_ts, spy_px, trend_days=TREND_DAYS, down_pct=DOWN_PCT):
    """(trend_block, down_block) at every evaluation point. Unknown never blocks."""
    s = view["sess"]
    pc = mkt["prev_close"][s]
    with np.errstate(invalid="ignore"):
        trend = pc < mkt["avg"][trend_days][s]
        k = np.searchsorted(spy_ts, view["t"], side="right") - 1
        spy_now = np.where(k >= 0, spy_px[np.maximum(k, 0)], np.nan)
        down = (spy_now / pc - 1.0) * 100.0 < -down_pct
    return np.nan_to_num(trend, nan=False).astype(bool), np.nan_to_num(down, nan=False).astype(bool)


def simulate(ticker, view, block=None, slip=SLIPPAGE, cooldown_hours=COOLDOWN_HOURS):
    """Replay the bot's decisions. Returns (closed trades, open position or None)."""
    t, px, rsi, prev = view["t"], view["px"], view["rsi"], view["prev"]
    with np.errstate(invalid="ignore"):
        buy = (prev < OVERSOLD) & (rsi >= OVERSOLD)
        sell = (prev > OVERBOUGHT) & (rsi <= OVERBOUGHT)
    if block is not None:
        buy = buy & ~block
    cands = np.nonzero(buy)[0]
    n = len(px)
    trades, i, cool_until = [], 0, -1
    while True:
        c = np.searchsorted(cands, i)
        while c < len(cands) and t[cands[c]] < cool_until:
            c += 1
        if c >= len(cands):
            return trades, None
        e = int(cands[c])
        entry = float(px[e]); peak = entry
        j, why = e + 1, None
        while j < n:
            p = px[j]
            chg = (p - entry) / entry * 100.0
            covers = chg >= 0.0
            if chg <= -STOP_LOSS:
                why = "stop"
            elif chg >= TAKE_PROFIT:
                why = "target"
            else:
                if p > peak:
                    peak = p
                if chg >= TRAIL_ACTIVATION and p <= peak * (1 - TRAIL / 100.0) and covers:
                    why = "trail"
                elif sell[j] and covers:
                    why = "rsi"
            if why:
                break
            j += 1
        if why is None:
            return trades, {"ticker": ticker, "entry_i": e, "entry_t": int(t[e]), "entry_px": entry}
        exit_px = float(px[j])
        buy_fill, sell_fill = entry * (1 + slip), exit_px * (1 - slip)
        trades.append({
            "ticker": ticker, "entry_i": e, "entry_t": int(t[e]), "exit_t": int(t[j]),
            "entry_px": entry, "exit_px": exit_px, "why": why,
            "ledger_pct": (exit_px - entry) / entry * 100.0,
            "pct": (sell_fill - buy_fill) / buy_fill * 100.0,
        })
        if exit_px < entry and cooldown_hours > 0:
            cool_until = int(t[j]) + int(cooldown_hours * NS_HOUR)
        i = j + 1


# ── measuring ────────────────────────────────────────────────────────────────
def day(ns):
    return pd.Timestamp(ns, tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d")


def in_window(trades, lo, hi):
    return [x for x in trades if lo <= day(x["entry_t"]) <= hi]


def stats(trades, key="pct"):
    p = [x[key] for x in trades]
    usd = [v / 100.0 * USD for v in p]
    w = [v for v in p if v > 0]; l = [v for v in p if v <= 0]
    gl = abs(sum(l))
    sharpe = (st.mean(usd) / st.stdev(usd)) if len(usd) > 1 and st.stdev(usd) > 0 else 0.0
    return {
        "n": len(p), "wins": len(w), "losses": len(l),
        "win_rate": 100.0 * len(w) / len(p) if p else 0.0,
        "avg_win": st.mean(w) if w else 0.0, "avg_loss": st.mean(l) if l else 0.0,
        "pf": (sum(w) / gl) if gl > 0 else float("inf") if w else 0.0,
        "net": sum(usd), "worst": min(p) if p else 0.0, "sharpe": sharpe,
        "avg": st.mean(p) if p else 0.0,
    }


def line(label, s):
    pf = "  inf" if s["pf"] == float("inf") else f"{s['pf']:5.2f}"
    return (f"{label:34} n={s['n']:4d}  win {s['win_rate']:5.1f}%  avg win {s['avg_win']:+5.2f}%  "
            f"avg loss {s['avg_loss']:+5.2f}%  PF {pf}  net ${s['net']:+8.2f}  "
            f"avg {s['avg']:+5.2f}%  worst {s['worst']:+6.2f}%")


def versus_hold(trades, prices, lo, hi):
    """
    Two honest framings of 'against not trading', both on $100 a symbol.

    ledger: the graduation gate's own convention (pooled P&L over ONE $100
            position, against the average hold from first entry to last exit).
    fair:   average per-symbol strategy return against holding each symbol
            across the whole window.
    """
    by = {}
    for x in trades:
        by.setdefault(x["ticker"], []).append(x)
    ledger_hold = [(v[-1]["exit_px"] - v[0]["entry_px"]) / v[0]["entry_px"] for v in by.values()]
    pooled = sum(x["pct"] for x in trades) / 100.0
    window_hold, held = [], 0
    lo_ns = pd.Timestamp(lo, tz="America/New_York").value
    hi_ns = pd.Timestamp(hi, tz="America/New_York").value + 24 * NS_HOUR
    for tk, (ts, px) in prices.items():
        a, b = np.searchsorted(ts, lo_ns), np.searchsorted(ts, hi_ns) - 1
        if b > a:
            window_hold.append((px[b] - px[a]) / px[a])
    for x in trades:
        held += min(x["exit_t"], hi_ns) - x["entry_t"]
    span = (hi_ns - lo_ns) * len(prices)
    return {
        "ledger_strategy": pooled * 100, "ledger_hold": 100 * st.mean(ledger_hold) if ledger_hold else 0.0,
        "fair_strategy": pooled * 100 / len(prices), "fair_hold": 100 * st.mean(window_hold) if window_hold else 0.0,
        "time_in_market": 100.0 * held / span if span else 0.0,
    }


def live_trades(since="2026-09-04"):
    rows = []
    for path in sorted(glob.glob(os.path.join(HERE, "completed_trades_stock_*_paper.csv"))):
        for r in csv.DictReader(open(path)):
            if r.get("exit_time", "") >= since:
                rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--json", default="")
    ap.add_argument("--stage", choices=("check", "full"), default="full",
                    help="check = ungated simulator against the live ledger only")
    args = ap.parse_args()

    sessions = load_sessions(args.cache)
    seed = load_seed_closes(args.cache)
    raw = {}
    for tk in TICKERS:
        df = load_minutes(tk, args.cache)
        raw[tk] = (_ns(df.index), df["close"].to_numpy(dtype=float))
    spy_ts, spy_px = raw[MARKET]
    mkt = market_state(spy_ts, spy_px, sessions, seed)
    views = {tk: bot_view(ts, px, sessions) for tk, (ts, px) in raw.items()}
    bars = sum(len(v[0]) for v in raw.values())
    print(f"{len(TICKERS)} tickers, {bars:,} one-minute bars, {len(sessions)} sessions "
          f"{sessions[0][0]} to {sessions[-1][0]}, seed closes {len(seed)}")
    print(f"slippage {SLIPPAGE*100:.2f}%/side, ${USD:.0f}/trade, cooldown {COOLDOWN_HOURS:.0f}h after a loss\n")

    def run(trend_days=None, down_pct=None, slip=SLIPPAGE):
        out, still = [], []
        for tk in TICKERS:
            block = None
            if trend_days or down_pct:
                tr, dn = gate_flags(views[tk], mkt, spy_ts, spy_px,
                                    trend_days or TREND_DAYS, down_pct or DOWN_PCT)
                block = (tr if trend_days else False) | (dn if down_pct else False)
            tr_, op = simulate(tk, views[tk], block, slip)
            out += tr_
            if op:
                still.append(op)
        return sorted(out, key=lambda x: x["entry_t"]), still

    report = {"spec": {"trend_days": TREND_DAYS, "down_pct": DOWN_PCT, "test": [TEST_FROM, TEST_TO],
                       "found": [FOUND_FROM, FOUND_TO], "slippage": SLIPPAGE}}

    # ── 1. is the simulator the bot? ungated, no slippage, against the ledger ──
    print("=" * 100)
    print("1. SIMULATOR CHECK: ungated replay, no slippage, against the live ledger (exits from 2026-09-04)")
    sim0, open0 = run(slip=0.0)
    sim_w = [x for x in sim0 if day(x["exit_t"]) >= FOUND_FROM]
    live = live_trades(FOUND_FROM)
    lv = [{"ticker": r["ticker"], "entry_t": pd.Timestamp(r["entry_time"]).value,
           "exit_t": pd.Timestamp(r["exit_time"]).value, "pct": float(r["net_pct"]),
           "why": r["exit_reason"]} for r in live]
    print(line("live ledger", stats(lv)))
    print(line("replay, same window", stats(sim_w, "ledger_pct")))
    used, both = set(), []
    for a in lv:
        best = None
        for k, b in enumerate(sim_w):
            if k in used or b["ticker"] != a["ticker"]:
                continue
            gap = abs(b["entry_t"] - a["entry_t"]) / NS_HOUR
            if gap <= 2.0 and (best is None or gap < best[0]):
                best = (gap, k)
        if best:
            used.add(best[1]); both.append((a, sim_w[best[1]]))
    same_exit = sum(1 for a, b in both if abs(b["exit_t"] - a["exit_t"]) / NS_HOUR <= 2.0)
    diff = [b["ledger_pct"] - a["pct"] for a, b in both]
    print(f"live trades {len(lv)} | replay trades {len(sim_w)} | same entry within 2h: {len(both)} "
          f"| of those, same exit within 2h: {same_exit}")
    if diff:
        print(f"matched pairs, replay minus live result: mean {st.mean(diff):+.3f}%  "
              f"median {st.median(diff):+.3f}%  largest gap {max(diff, key=abs):+.2f}%")
    print(f"replay open at the end: {len(open0)} | live open at the stop: 2")
    report["check"] = {"live": stats(lv), "replay": stats(sim_w, "ledger_pct"), "matched_entries": len(both),
                       "matched_exits": same_exit, "live_n": len(lv), "replay_n": len(sim_w)}
    if args.stage == "check":
        unmatched_live = [a for a in lv if all(a is not p[0] for p in both)]
        unmatched_sim = [b for k, b in enumerate(sim_w) if k not in used]
        for a in unmatched_live:
            print(f"  live only   {a['ticker']:5} in {pd.Timestamp(a['entry_t'], tz='UTC')}  out {pd.Timestamp(a['exit_t'], tz='UTC')}  {a['pct']:+.2f}%  {a['why']}")
        for b in unmatched_sim:
            print(f"  replay only {b['ticker']:5} in {pd.Timestamp(b['entry_t'], tz='UTC')}  out {pd.Timestamp(b['exit_t'], tz='UTC')}  {b['ledger_pct']:+.2f}%  {b['why']}")
        return

    # ── 2. the test ──────────────────────────────────────────────────────────
    base, _ = run()
    cand_a, _ = run(trend_days=TREND_DAYS)
    cand_b, _ = run(trend_days=TREND_DAYS, down_pct=DOWN_PCT)
    flags = {}
    for tk in TICKERS:
        flags[tk] = gate_flags(views[tk], mkt, spy_ts, spy_px)
    for x in base:
        x["trend"] = bool(flags[x["ticker"]][0][x["entry_i"]])
        x["down"] = bool(flags[x["ticker"]][1][x["entry_i"]])
    prices = raw

    def section(title, lo, hi):
        print("\n" + "=" * 100)
        print(f"{title}: entries {lo} to {hi}")
        b, a, c = in_window(base, lo, hi), in_window(cand_a, lo, hi), in_window(cand_b, lo, hi)
        sb, sa, sc = stats(b), stats(a), stats(c)
        print(line("baseline (v4 as it ran)", sb))
        print(line(f"A  trend {TREND_DAYS}d", sa))
        print(line(f"B  trend {TREND_DAYS}d or down {DOWN_PCT:.1f}%", sc))
        print("\nbaseline trades split by the gate's state at entry:")
        groups = {
            "kept by both": [x for x in b if not x["trend"] and not x["down"]],
            "blocked by trend": [x for x in b if x["trend"]],
            "blocked by down day only": [x for x in b if x["down"] and not x["trend"]],
            "blocked by either": [x for x in b if x["trend"] or x["down"]],
        }
        gs = {k: stats(v) for k, v in groups.items()}
        for k, v in gs.items():
            print(line("  " + k, v))
        print("\nby year (entries):  baseline | A | B | baseline trades A blocks | B blocks")
        years = sorted({day(x["entry_t"])[:4] for x in b})
        yr = {}
        for y in years:
            f = lambda rows: [x for x in rows if day(x["entry_t"])[:4] == y]
            yb, ya, yc = stats(f(b)), stats(f(a)), stats(f(c))
            ka, kb = stats(f(groups["blocked by trend"])), stats(f(groups["blocked by either"]))
            yr[y] = {"base": yb, "A": ya, "B": yc, "A_blocked": ka, "B_blocked": kb}
            print(f"  {y}  base n={yb['n']:3d} PF {yb['pf']:4.2f} ${yb['net']:+8.2f} | "
                  f"A n={ya['n']:3d} PF {ya['pf']:4.2f} ${ya['net']:+8.2f} | "
                  f"B n={yc['n']:3d} PF {yc['pf']:4.2f} ${yc['net']:+8.2f} | "
                  f"A blocks n={ka['n']:3d} ${ka['net']:+8.2f} | B blocks n={kb['n']:3d} ${kb['net']:+8.2f}")
        print("\nagainst not trading:")
        vh = {}
        for name, rows in (("baseline", b), ("A", a), ("B", c)):
            v = versus_hold(rows, prices, lo, hi); vh[name] = v
            print(f"  {name:9} gate convention: strategy {v['ledger_strategy']:+8.2f}% vs hold {v['ledger_hold']:+7.2f}%"
                  f" | per symbol: strategy {v['fair_strategy']:+6.2f}% vs hold {v['fair_hold']:+7.2f}%"
                  f" | in market {v['time_in_market']:4.1f}% of the time")
        print("\nby ticker, net $:  " + "  ".join(
            f"{tk} {sum(x['pct'] for x in b if x['ticker']==tk):+.0f}/{sum(x['pct'] for x in a if x['ticker']==tk):+.0f}/{sum(x['pct'] for x in c if x['ticker']==tk):+.0f}"
            for tk in TICKERS) + "   (baseline/A/B)")
        return {"baseline": sb, "A": sa, "B": sc, "groups": gs, "years": yr, "versus_hold": vh}

    test = section("2. INDEPENDENT TEST", TEST_FROM, TEST_TO)
    report["test"] = test

    print("\n" + "-" * 100)
    print("PASS/FAIL on the terms fixed before the run")
    verdict = {}
    for name, blocked_key in (("A", "A_blocked"), ("B", "B_blocked")):
        s, b = test[name], test["baseline"]
        p1 = s["net"] > b["net"]
        p2 = (s["pf"] >= b["pf"] + 0.10) and s["pf"] >= 1.00
        yrs = [(y, v[blocked_key]) for y, v in test["years"].items() if v[blocked_key]["n"] >= 10]
        lost = [y for y, v in yrs if v["net"] < 0]
        p3 = bool(yrs) and len(lost) * 3 >= len(yrs) * 2
        verdict[name] = {"net_higher": p1, "pf_margin": p2, "blocked_lose_by_year": p3,
                         "years_counted": [y for y, _ in yrs], "years_blocked_lost": lost,
                         "passed": p1 and p2 and p3}
        print(f"  {name}: 1 net higher than baseline: {'yes' if p1 else 'NO'} (${s['net']:+.2f} vs ${b['net']:+.2f})"
              f" | 2 PF >= baseline+0.10 and >= 1.00: {'yes' if p2 else 'NO'} ({s['pf']:.2f} vs {b['pf']:.2f})"
              f" | 3 blocked trades lose in 2/3 of years with 10+: {'yes' if p3 else 'NO'} "
              f"({len(lost)} of {len(yrs)}: {', '.join(y for y, _ in yrs)})  => {'PASS' if verdict[name]['passed'] else 'FAIL'}")
    down_only = test["groups"]["blocked by down day only"]
    if verdict["A"]["passed"] and verdict["B"]["passed"]:
        choice = "B" if down_only["pf"] < 1.0 else "A"
    elif verdict["A"]["passed"] or verdict["B"]["passed"]:
        choice = "A" if verdict["A"]["passed"] else "B"
    else:
        choice = None
    verdict["choice"] = choice
    print(f"  down-day-only blocked trades: n={down_only['n']} PF {down_only['pf']:.2f} net ${down_only['net']:+.2f}")
    print(f"  CHOICE: {choice or 'none: no v5 from this gate'}")
    report["verdict"] = verdict

    print("\n" + "-" * 100)
    print("SENSITIVITY (reported, never used to choose), test window")
    sens = {}
    for label, kw in ([(f"trend {n}d", {"trend_days": n}) for n in (20, 50, 100, 200)] +
                      [(f"down {x:.1f}% only", {"down_pct": x}) for x in (0.5, 1.0, 1.5, 2.0)]):
        rows, _ = run(**kw)
        s = stats(in_window(rows, TEST_FROM, TEST_TO)); sens[label] = s
        print(line("  " + label, s))
    report["sensitivity"] = sens

    found = section("3. WHERE THE GATE WAS FOUND (not independent)", FOUND_FROM, FOUND_TO)
    report["found"] = found

    # ── 4. what a pass is worth: description only, nothing here chooses ──────
    print("\n" + "=" * 100)
    print("4. WHAT THE RESULT IS WORTH (description after the fact; chooses nothing), test window")
    bt, at = in_window(base, TEST_FROM, TEST_TO), in_window(cand_a, TEST_FROM, TEST_TO)
    worth = {}
    for name, rows in (("baseline", bt), ("A", at)):
        s = stats(rows)
        eff = s["n"] * EFFECTIVE_SYMBOLS / len(TICKERS)
        years = (pd.Timestamp(TEST_TO) - pd.Timestamp(TEST_FROM)).days / 365.25
        z = stats(rows, "ledger_pct")
        ex22 = stats([x for x in rows if day(x["entry_t"])[:4] != "2022"])
        blocks = [rows[k:k + 48] for k in range(0, len(rows) - 47, 48)]
        ok = sum(1 for blk in blocks if stats(blk, "ledger_pct")["win_rate"] >= 70.0
                 and stats(blk, "ledger_pct")["pf"] >= 1.0)
        worth[name] = {"sharpe": s["sharpe"], "effective_trades": eff, "t_pooled": s["sharpe"] * s["n"] ** 0.5,
                       "t_effective": s["sharpe"] * eff ** 0.5, "usd_per_year": s["net"] / years,
                       "no_slippage": z, "without_2022": ex22, "blocks": len(blocks), "blocks_passing": ok}
        print(f"  {name:9} per-trade Sharpe {s['sharpe']:+.3f} | {s['n']} pooled = {eff:.0f} effective trades | "
              f"t {s['sharpe'] * s['n'] ** 0.5:+.2f} pooled, {s['sharpe'] * eff ** 0.5:+.2f} effective | "
              f"${s['net'] / years:+.2f} a year on up to ${USD * len(TICKERS):.0f} deployed")
        print(line(f"    {name}, no slippage (ledger)", z))
        print(line(f"    {name}, 2022 entries left out", ex22))
        print(f"    consecutive 48-trade runs, ledger figures, passing BOTH shape rules "
              f"(win >= 70%, PF >= 1.00): {ok} of {len(blocks)}")
    lo_s = [i for i, s_ in enumerate(sessions) if TEST_FROM <= s_[0] <= TEST_TO]
    tr = np.array([bool(mkt["prev_close"][i] < mkt["avg"][TREND_DAYS][i]) for i in lo_s])
    longest = cur = 0
    for v in tr:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    print(f"  sessions with entries switched off by the trend rule: {int(tr.sum())} of {len(tr)} "
          f"({100 * tr.mean():.0f}%), longest stretch {longest} sessions")
    worth["sessions_blocked"] = int(tr.sum()); worth["sessions"] = len(tr); worth["longest_block"] = longest
    report["worth"] = worth

    if args.json:
        json.dump(report, open(args.json, "w"), indent=1, default=float)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
