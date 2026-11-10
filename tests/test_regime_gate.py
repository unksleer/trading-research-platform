"""
The regime-gate backtest is only worth reading if its replay sees what the bot
sees and nothing later. These tests pin that down on synthetic bars.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_regime_gate as g  # noqa: E402

MIN = 60_000_000_000
DAY = 24 * g.NS_HOUR


def _minutes(days=30, seed=1, start="2025-01-06 14:30"):
    """Random-walk minute bars, 390 a day on weekdays, with a few pre-market prints."""
    rng = np.random.default_rng(seed)
    ts, sessions = [], []
    t0 = pd.Timestamp(start, tz="UTC").value
    d = 0
    while len(sessions) < days:
        o = t0 + d * DAY
        d += 1
        if pd.Timestamp(o, tz="UTC").weekday() >= 5:
            continue
        ts += [o - 45 * MIN, o - 20 * MIN]                     # pre-market
        ts += [o + k * MIN for k in range(390)]
        ts += [o + 400 * MIN]                                   # after hours
        sessions.append((str(pd.Timestamp(o, tz="UTC").date()), o, o + 390 * MIN))
    ts = np.array(ts, dtype=np.int64)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.0015, len(ts))))
    return ts, px, sessions


def _bot_rsi(ts, px, upto):
    """RSI the way stock_bot.compute_indicators does it, on bars up to index `upto`."""
    s = pd.Series(px[:upto + 1], index=pd.to_datetime(ts[:upto + 1], utc=True))
    closes = s.groupby(s.index.floor("h")).last()
    delta = closes.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    rs = gain.ewm(alpha=1 / 14, adjust=False).mean() / loss.ewm(alpha=1 / 14, adjust=False).mean().replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]), float(rsi.iloc[-2])


def test_view_matches_the_bots_own_rsi_at_any_minute():
    ts, px, sessions = _minutes()
    view = g.bot_view(ts, px, sessions)
    pos = {int(t): i for i, t in enumerate(ts)}
    opening_look = np.r_[True, view["sess"][1:] != view["sess"][:-1]]
    rng = np.random.default_rng(7)
    picks = list(rng.choice(np.arange(2000, len(view["t"])), 60, replace=False))
    picks += list(np.nonzero(opening_look)[0][6:12])
    for k in picks:
        t = int(view["t"][k])
        if opening_look[k]:                    # decided on the last print before the open
            upto = int(np.searchsorted(ts, t)) - 1
        else:
            upto = pos[t]
        now, prev = _bot_rsi(ts, px, upto)
        assert view["rsi"][k] == pytest.approx(now, abs=1e-9)
        assert view["prev"][k] == pytest.approx(prev, abs=1e-9)
        assert view["px"][k] == px[upto]


def test_view_only_decides_while_the_market_is_open():
    ts, px, sessions = _minutes(days=5)
    view = g.bot_view(ts, px, sessions)
    for t, s in zip(view["t"], view["sess"]):
        _, o, x = sessions[s]
        assert o <= t < x
    # one look at the open plus 390 minutes per session; the first session has
    # pre-market prints before it, so every session gets its opening look
    assert len(view["t"]) == 5 * 391


def test_nothing_after_the_decision_moment_changes_what_the_bot_saw():
    ts, px, sessions = _minutes()
    view = g.bot_view(ts, px, sessions)
    cut = len(ts) // 2
    px2 = px.copy()
    px2[cut:] *= 1.5                           # rewrite the future
    view2 = g.bot_view(ts, px2, sessions)
    before = view["t"] < ts[cut]
    assert before.sum() > 1000
    for key in ("px", "rsi", "prev"):
        np.testing.assert_array_equal(view[key][before], view2[key][before])


def test_gate_uses_only_prices_known_at_the_signal():
    ts, px, sessions = _minutes(days=120, seed=3)
    px = px * (1 + 0.3 * np.sin(np.linspace(0, 12, len(px))))     # rises and falls
    view = g.bot_view(ts, px, sessions)
    mkt = g.market_state(ts, px, sessions, seed=[])
    trend, down = g.gate_flags(view, mkt, ts, px, down_pct=0.5)
    cut = int(len(ts) * 0.8)
    px2 = px.copy()
    px2[cut:] *= 0.5                           # crash the market later
    mkt2 = g.market_state(ts, px2, sessions, seed=[])
    trend2, down2 = g.gate_flags(view, mkt2, ts, px2, down_pct=0.5)
    # sessions that began before the rewrite still closed at the same price on
    # every EARLIER session, so flags for decisions before the rewrite are equal
    before = view["t"] < ts[cut]
    np.testing.assert_array_equal(trend[before], trend2[before])
    np.testing.assert_array_equal(down[before], down2[before])
    assert trend[before].any() and (~trend[before]).any() and down[before].any()
    # and the rewrite did change what the gate says afterwards
    assert not (np.array_equal(trend, trend2) and np.array_equal(down, down2))


def test_trend_gate_is_yesterdays_close_against_the_prior_fifty():
    ts, px, sessions = _minutes(days=70, seed=5)
    mkt = g.market_state(ts, px, sessions, seed=[])
    closes = [px[np.searchsorted(ts, x) - 1] for _, o, x in sessions]
    s = 60
    assert mkt["prev_close"][s] == closes[s - 1]
    assert mkt["avg"][50][s] == pytest.approx(np.mean(closes[s - 50:s]))
    assert np.isnan(mkt["avg"][50][40])        # not enough history yet: unknown, never blocks


def _view(prices, rsi=None, prev=None, step_min=1):
    n = len(prices)
    return {"t": np.arange(n, dtype=np.int64) * step_min * MIN, "px": np.array(prices, float),
            "rsi": np.array(rsi if rsi is not None else [50.0] * n, float),
            "prev": np.array(prev if prev is not None else [50.0] * n, float),
            "sess": np.zeros(n, dtype=int)}


def test_stop_fires_at_five_percent_and_not_before():
    v = _view([100, 96, 95.1, 94.9, 99], rsi=[40, 50, 50, 50, 50], prev=[30, 50, 50, 50, 50])
    trades, still = g.simulate("X", v, slip=0.0)
    assert still is None and len(trades) == 1
    assert trades[0]["why"] == "stop" and trades[0]["exit_px"] == 94.9


def test_trail_and_rsi_exit_cannot_close_below_entry():
    # peaks at +1.2%, falls 1.5% from the peak to below entry: the trail must hold
    v = _view([100, 101.2, 99.6, 99.0, 101.0, 101.0],
              rsi=[40, 50, 50, 60, 60, 60], prev=[30, 50, 50, 70, 60, 70])
    trades, still = g.simulate("X", v, slip=0.0)
    assert len(trades) == 1
    assert trades[0]["why"] == "rsi" and trades[0]["exit_px"] == 101.0   # the RSI exit at 99.0 was refused


def test_trail_exits_in_profit():
    v = _view([100, 103.0, 101.4], rsi=[40, 50, 50], prev=[30, 50, 50])
    trades, _ = g.simulate("X", v, slip=0.0)
    assert trades[0]["why"] == "trail" and trades[0]["ledger_pct"] == pytest.approx(1.4)


def test_cooldown_after_a_loss_blocks_the_next_signal_for_six_hours():
    prices = [100, 94, 94, 94, 94, 99]
    rsi = [40, 50, 40, 50, 40, 50]
    prev = [30, 50, 30, 50, 30, 50]
    hourly = _view(prices, rsi, prev, step_min=120)          # signals at 0h, 4h, 8h
    trades, still = g.simulate("X", hourly, slip=0.0)
    assert trades[0]["why"] == "stop"
    assert still is not None and still["entry_t"] == 8 * g.NS_HOUR   # 4h signal skipped, 8h taken
    trades, still = g.simulate("X", hourly, slip=0.0, cooldown_hours=0)
    assert still["entry_t"] == 4 * g.NS_HOUR


def test_a_blocked_entry_is_not_taken_and_slippage_costs_both_sides():
    v = _view([100, 108.5, 100, 108.5], rsi=[40, 50, 40, 50], prev=[30, 50, 30, 50])
    block = np.array([True, False, False, False])
    trades, _ = g.simulate("X", v, block=block, slip=0.001)
    assert len(trades) == 1 and trades[0]["entry_t"] == 2 * MIN
    assert trades[0]["why"] == "target"
    assert trades[0]["pct"] == pytest.approx((108.5 * 0.999 - 100 * 1.001) / (100 * 1.001) * 100)
