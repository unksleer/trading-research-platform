"""
The market trend gate on new entries (stocks v5).

Rule, fixed 2026-11-10 before it was backtested: no new entry when SPY's close
on the last completed session is below the average of its last 50 completed
session closes. Exits are never gated.

What these tests are for:

  - The live rule is the backtested rule. It is compared, session by session,
    with backtest_regime_gate.market_state, the code that produced the result
    the registration rests on.
  - It uses completed sessions only. Alpaca serves a daily bar for the session
    in progress; letting it in would let today's move decide today's entries.
  - Unknown blocks. No data, short data and old data all refuse an entry.
  - In the bot it can veto an entry and do nothing else: it never opens a
    position and never stands in the way of an exit.
  - The registration counts trades by entry time, so positions v4 opened before
    v5 started are not scored as v5 trades.
"""
import datetime as dt
import http.server
import json
import logging
import os
import random
import sys
import threading

import numpy as np
import pandas as pd
import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from utils import alpaca_http, experiment, market_gate  # noqa: E402
from utils.market_gate import GateState, TrendGate  # noqa: E402
from stock_bot_harness import bot, hourly_bars, run_one_pass  # noqa: E402,F401


def _src(name):
    with open(os.path.join(DIR, name)) as handle:
        return handle.read()


def sessions_ending(last, closes):
    """[(date, close)] on consecutive weekdays, the final one dated `last`."""
    days, day = [], last
    while len(days) < len(closes):
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    return list(zip(reversed(days), closes))


TODAY = dt.date(2026, 11, 16)                    # a Monday
FRIDAY = dt.date(2026, 11, 13)


def gate_on(bars, **kw):
    return TrendGate(lambda: bars, today=lambda: TODAY, **kw)


# ── the rule ────────────────────────────────────────────────────────────────

def test_blocks_when_the_last_close_is_below_the_average():
    blocked, prior, average = market_gate.evaluate([100.0] * 49 + [99.0], 50)
    assert blocked is True and prior == 99.0
    assert average == pytest.approx((49 * 100.0 + 99.0) / 50)


def test_allows_when_the_last_close_is_above_the_average():
    blocked, _, _ = market_gate.evaluate([100.0] * 49 + [101.0], 50)
    assert blocked is False


def test_a_close_exactly_on_the_average_allows():
    """The rule is 'below'. Equal is not below."""
    blocked, prior, average = market_gate.evaluate([100.0] * 50, 50)
    assert prior == average and blocked is False


def test_the_average_includes_the_last_close_and_only_the_last_fifty():
    """Older closes must not leak in: a huge value 51 sessions back changes nothing."""
    recent = [100.0] * 49 + [99.5]
    assert market_gate.evaluate([1e6] + recent, 50) == market_gate.evaluate(recent, 50)


def test_fewer_than_fifty_closes_is_unknown():
    blocked, _, average = market_gate.evaluate([100.0] * 49, 50)
    assert blocked is None and average is None


def test_live_rule_equals_the_backtested_rule_on_every_session():
    """
    The registration rests on backtest_regime_gate. Feed both the same closes
    and require the same decision on every session that has 50 behind it.
    """
    import backtest_regime_gate as g

    rng = random.Random(7)
    closes, price = [], 500.0
    for _ in range(400):
        price *= 1.0 + rng.gauss(0.0, 0.012)
        closes.append(round(price, 2))

    day_ns = 86_400_000_000_000
    sessions = [(f"s{i}", i * day_ns, i * day_ns + day_ns // 4) for i in range(len(closes))]
    spy_ts = np.array([o + 1000 for _, o, _ in sessions], dtype=np.int64)   # one print a session
    spy_px = np.array(closes, dtype=float)
    mkt = g.market_state(spy_ts, spy_px, sessions, [])

    compared = blocks = 0
    for s in range(50, len(closes)):
        backtest = bool(mkt["prev_close"][s] < mkt["avg"][g.TREND_DAYS][s])
        live, prior, average = market_gate.evaluate(closes[:s], g.TREND_DAYS)
        assert live is backtest, f"session {s}"
        assert prior == pytest.approx(mkt["prev_close"][s])
        assert average == pytest.approx(mkt["avg"][g.TREND_DAYS][s])
        compared += 1
        blocks += live
    assert compared == 350
    assert 0 < blocks < compared          # the series exercised both answers


def test_registered_numbers_are_the_backtested_numbers():
    import backtest_regime_gate as g
    assert (g.TREND_DAYS, g.MARKET) == (50, "SPY")


# ── completed sessions only ─────────────────────────────────────────────────

def test_todays_bar_is_not_a_completed_session():
    """
    49 closes at 100, Friday at 99, and a bar for today at 200. With today's
    bar the 'last close' would be 200 and far above the average. Without it,
    Friday's 99 is below the average and entries are off.
    """
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [99.0]) + [(TODAY, 200.0)]
    state = gate_on(bars).state()
    assert state.blocked is True
    assert state.session == FRIDAY and state.prior_close == 99.0


def test_bars_dated_after_today_are_ignored_too():
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [101.0]) + [
        (TODAY, 1.0), (TODAY + dt.timedelta(days=1), 1.0)]
    assert gate_on(bars).state().blocked is False


def test_bar_order_does_not_matter():
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [99.0])
    random.Random(1).shuffle(bars)
    assert gate_on(bars).state().blocked is True


def test_new_york_decides_what_today_is():
    """01:00 UTC on the 17th is still the evening of the 16th in New York."""
    late = dt.datetime(2026, 11, 17, 1, 0, tzinfo=dt.timezone.utc)
    assert market_gate.new_york_date(late) == dt.date(2026, 11, 16)


# ── unknown blocks ──────────────────────────────────────────────────────────

def test_a_failed_fetch_is_unknown_and_refuses_entry(caplog):
    def broken():
        raise RuntimeError("read timed out")
    with caplog.at_level(logging.WARNING):
        state = TrendGate(broken, today=lambda: TODAY).state()
    assert state.blocked is None
    assert state.allows_entry is False
    assert state.blocked_by == market_gate.UNKNOWN
    assert "read timed out" in caplog.text


def test_too_few_sessions_is_unknown_and_refuses_entry():
    state = gate_on(sessions_ending(FRIDAY, [100.0] * 30)).state()
    assert state.blocked is None and state.allows_entry is False
    assert "30 completed" in state.problem


def test_old_data_is_unknown_not_a_stale_answer():
    """Closes that stop two weeks ago are not 'the last completed session'."""
    stale = sessions_ending(TODAY - dt.timedelta(days=14), [100.0] * 49 + [101.0])
    state = gate_on(stale).state()
    assert state.blocked is None and state.allows_entry is False
    assert "days old" in state.problem


def test_a_holiday_weekend_is_not_stale():
    """Friday's close read on the Tuesday after a Monday holiday is 4 days old."""
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [101.0])
    gate = TrendGate(lambda: bars, today=lambda: FRIDAY + dt.timedelta(days=4))
    assert gate.state().blocked is False


def test_only_false_allows_an_entry():
    assert GateState(False, 101.0, 100.0).allows_entry is True
    assert GateState(True, 99.0, 100.0).allows_entry is False
    assert GateState(None).allows_entry is False
    assert GateState(False, 101.0, 100.0).blocked_by == ""
    assert GateState(True, 99.0, 100.0).blocked_by == market_gate.BLOCKED


# ── once a day, and polite when failing ─────────────────────────────────────

def test_a_good_answer_is_fetched_once_a_day():
    calls, today = [], [TODAY]
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [99.0])

    def fetch():
        calls.append(1)
        return bars + [(TODAY, 150.0)]

    gate = TrendGate(fetch, today=lambda: today[0])
    for _ in range(5):
        assert gate.state().blocked is True
    assert len(calls) == 1
    today[0] = TODAY + dt.timedelta(days=1)       # next day: Monday's 150 is now complete
    assert gate.state().blocked is False
    assert len(calls) == 2


def test_a_failure_is_retried_but_not_on_every_tick():
    calls, now, fail = [], [0.0], [True]
    bars = sessions_ending(FRIDAY, [100.0] * 49 + [101.0])

    def fetch():
        calls.append(1)
        if fail[0]:
            raise RuntimeError("down")
        return bars

    gate = TrendGate(fetch, today=lambda: TODAY, clock=lambda: now[0], retry_after_sec=300)
    assert gate.state().blocked is None
    now[0] = 60.0
    assert gate.state().blocked is None            # a minute later: no new call
    assert len(calls) == 1
    now[0] = 301.0
    fail[0] = False
    assert gate.state().blocked is False           # retried, and recovered
    assert len(calls) == 2


# ── in the bot ──────────────────────────────────────────────────────────────

BLOCKING = GateState(True, 754.27, 764.10, session="2026-11-13")
ALLOWING = GateState(False, 770.00, 764.10, session="2026-11-13")
UNKNOWN = GateState(None, problem="could not fetch SPY closes: read timed out")


def test_registered_defaults_are_on_in_the_bot(bot):
    """50 and SPY with nothing set in .env: a restart cannot quietly run v4."""
    assert (bot.TREND_GATE_DAYS, bot.TREND_GATE_SYMBOL) == (50, "SPY")


def test_a_blocked_gate_vetoes_the_entry_and_says_why(bot, monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        run = run_one_pass(bot, monkeypatch, hourly_bars(), should_enter=True, gate=BLOCKING)
    assert run.buys == []
    assert "Entry blocked" in caplog.text and "entries off" in caplog.text
    assert "Unexpected error" not in caplog.text
    _, _, position, decision = run.signals[0]
    assert position == "NONE"
    assert decision["blocked_by"] == "TREND_GATE"
    assert decision["final_signal"] == "HOLD"


def test_an_allowing_gate_lets_the_entry_through(bot, monkeypatch):
    df = hourly_bars()
    run = run_one_pass(bot, monkeypatch, df, should_enter=True, gate=ALLOWING)
    assert run.buys == [pytest.approx(df["close"].iloc[-1])]
    assert run.signals[0][3]["blocked_by"] == ""
    assert run.signals[0][3]["final_signal"] == "BUY"


def test_an_unknown_gate_refuses_the_entry(bot, monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        run = run_one_pass(bot, monkeypatch, hourly_bars(), should_enter=True, gate=UNKNOWN)
    assert run.buys == []
    assert run.signals[0][3]["blocked_by"] == "TREND_GATE_UNKNOWN"
    assert "no entry without it" in caplog.text


def test_the_gate_never_creates_an_entry(bot, monkeypatch):
    """Allowed by the gate, no signal from the strategy: nothing is bought."""
    run = run_one_pass(bot, monkeypatch, hourly_bars(), should_enter=False, gate=ALLOWING)
    assert run.buys == []
    assert run.signals[0][3]["blocked_by"] == ""


def test_a_blocked_gate_without_a_signal_blocks_nothing(bot, monkeypatch):
    """blocked_by records a vetoed entry, not the gate's state on a quiet bar."""
    run = run_one_pass(bot, monkeypatch, hourly_bars(), should_enter=False, gate=BLOCKING)
    assert run.signals[0][3]["blocked_by"] == ""
    assert run.gate_calls == 1                      # asked every flat tick


LONG = {"position": "LONG", "entry_price": 100.0, "shares": 1.0, "highest_price": 100.0,
        "entry_time": "2026-11-12T18:35:56+00:00", "ticker": "ZZTEST", "mode": "PAPER"}


@pytest.mark.parametrize("gate", [BLOCKING, UNKNOWN])
def test_the_stop_loss_fires_whatever_the_gate_says(bot, monkeypatch, gate):
    """Exits are never gated: a 6% loss sells with entries off or the gate unknown."""
    run = run_one_pass(bot, monkeypatch, hourly_bars(), gate=gate, state=LONG, price=94.0)
    assert len(run.sells) == 1
    assert run.sells[0][2] == "Stop Loss Triggered"
    assert run.gate_calls == 0                      # a held position does not consult it


def test_the_take_profit_fires_whatever_the_gate_says(bot, monkeypatch):
    run = run_one_pass(bot, monkeypatch, hourly_bars(), gate=BLOCKING, state=LONG, price=109.0)
    assert [s[2] for s in run.sells] == ["Take Profit Triggered"]


def test_zero_days_switches_the_gate_off(bot, monkeypatch):
    """STOCK_TREND_GATE_DAYS=0 is v4: the gate is not consulted at all."""
    monkeypatch.setattr(bot, "TREND_GATE_DAYS", 0)
    df = hourly_bars()
    run = run_one_pass(bot, monkeypatch, df, should_enter=True, gate=BLOCKING)
    assert run.gate_calls == 0
    assert run.buys == [pytest.approx(df["close"].iloc[-1])]


def test_the_gate_sits_only_in_the_flat_branch():
    """Source check behind the behaviour above: nothing in the LONG branch asks the gate."""
    body = _src("stock_bot.py").split("def main():", 1)[1]
    flat, held = body.split('elif state["position"] == "LONG":', 1)
    assert "trend_gate()" in flat
    assert "trend_gate" not in held and "gate" not in held.lower()


# ── the bot's fetch, against a real Alpaca-shaped response ──────────────────

@pytest.fixture
def daily_server():
    """Serves SPY daily bars the way Alpaca does: midnight New York, in UTC."""
    days = [d for d, _ in sessions_ending(FRIDAY, [0.0] * 60)]
    closes = [700.0 + i for i in range(60)]
    payload = json.dumps({
        "bars": {"SPY": [{"t": f"{d.isoformat()}T05:00:00Z", "o": c, "h": c, "l": c,
                          "c": c, "v": 1000, "n": 10, "vw": c}
                         for d, c in zip(days, closes)]},
        "next_page_token": None,
    }).encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", days, closes
    server.shutdown()
    server.server_close()
    thread.join(2)


def test_fetch_market_closes_reads_session_dates_in_new_york(bot, monkeypatch, daily_server):
    """A bar stamped 05:00 UTC is that calendar day in New York, not the day before."""
    from alpaca.data.historical import StockHistoricalDataClient
    url, days, closes = daily_server
    monkeypatch.setattr(bot, "_data_client", lambda: alpaca_http.with_timeout(
        StockHistoricalDataClient("k", "s", url_override=url), (2.0, 5.0)))

    got = bot.fetch_market_closes()
    assert got == list(zip(days, closes))

    state = TrendGate(bot.fetch_market_closes, today=lambda: TODAY).state()
    assert state.session == FRIDAY
    assert state.blocked is False                   # a rising series closes above its average
    assert state.average == pytest.approx(sum(closes[-50:]) / 50)


def test_the_gate_fetch_goes_through_the_timeout_client():
    """The gate adds a network call to the loop. It must not be one that can hang."""
    body = _src("stock_bot.py").split("def fetch_market_closes():", 1)[1].split("\ndef ", 1)[0]
    assert "_data_client().get_stock_bars" in body
    assert "TimeFrame.Day" in body and "DataFeed.IEX" in body and "Adjustment.ALL" in body


# ── which trades a registration is judged on ────────────────────────────────

def _trade(symbol, entry, exit_):
    return {"_symbol": symbol, "entry_time": entry, "exit_time": exit_,
            "_net_pct": 1.0, "_pnl": 1.0}


CARRIED = _trade("QQQ", "2026-11-16T14:30:36+00:00", "2026-11-19T15:00:00+00:00")
FRESH = _trade("SPY", "2026-11-18T15:00:00+00:00", "2026-11-20T15:00:00+00:00")


def test_exit_time_is_still_the_default_scope():
    """Every registration before v5 was counted by exit; that must not move."""
    import observer
    reg = {"market": "stocks", "started": "2026-11-17", "symbols": ["QQQ", "SPY"]}
    assert experiment.scope_field(reg) == "exit_time"
    assert observer.trades_for(reg, {"stocks": [CARRIED, FRESH]}) == [CARRIED, FRESH]


def test_entry_time_scope_leaves_out_positions_opened_before_the_start():
    """
    v5 starts with positions v4 opened on days the gate would have refused.
    They close after the start; they are not v5 trades.
    """
    import observer
    reg = {"market": "stocks", "started": "2026-11-17", "symbols": ["QQQ", "SPY"],
           "success_criteria": {"count_by": "entry_time"}}
    assert experiment.scope_field(reg) == "entry_time"
    assert observer.trades_for(reg, {"stocks": [CARRIED, FRESH]}) == [FRESH]


def test_the_dashboard_scopes_the_same_way_as_the_observer():
    src = _src("dashboard.py")
    assert '.get("count_by") == "entry_time"' in src
    assert 'r[scope] >= started' in src


def _panel(monkeypatch, reg, positions):
    import dashboard
    monkeypatch.setattr(experiment, "active", lambda: [reg])
    return dashboard.DashboardHandler.build_pnl_by_market(positions)["stocks"]


POSITIONS = [
    {"market": "stocks", "coin": "QQQ", "entry_time": "2026-11-16T14:30:38+00:00",
     "unrealized_pnl": -1.11, "unrealized_known": True},          # opened under v4
    {"market": "stocks", "coin": "SPY", "entry_time": "2026-11-18T15:00:00+00:00",
     "unrealized_pnl": 2.00, "unrealized_known": True},           # opened under v5
]


def test_the_panel_does_not_put_a_carried_position_on_v5(monkeypatch):
    """
    Found on the live dashboard minutes after v5 started: 0 trades, yet the v5
    panel showed 2 open and -$0.91, the two positions v4 had left open.
    """
    reg = {"name": "v5", "market": "stocks", "started": "2026-11-17", "symbols": [],
           "success_criteria": {"count_by": "entry_time"}}
    panel = _panel(monkeypatch, reg, POSITIONS)
    assert panel["open"] == 1
    assert panel["unrealized_usd"] == pytest.approx(2.00)
    assert panel["open_before_start"] == 1
    assert panel["unrealized_before_start_usd"] == pytest.approx(-1.11)
    assert panel["total_usd"] == pytest.approx(panel["realized_usd"] + 2.00)


def test_the_panel_counts_every_open_position_under_exit_scope(monkeypatch):
    """Registrations counted by exit keep the old behaviour."""
    reg = {"name": "v4", "market": "stocks", "started": "2026-11-17", "symbols": []}
    panel = _panel(monkeypatch, reg, POSITIONS)
    assert panel["open"] == 2 and panel["open_before_start"] == 0
    assert panel["unrealized_usd"] == pytest.approx(0.89)


def test_the_page_shows_carried_positions_as_not_counted():
    page = _src(os.path.join("dashboard", "index.html"))
    assert "opened before the start, not counted" in page
    assert "p.open_before_start" in page


def test_a_running_stock_registration_with_a_gate_matches_the_bot(bot):
    """
    If the active registration seals a trend gate, the bot's defaults are that
    gate, and the registration counts by entry. Skips when none is running.
    """
    regs = [r for r in experiment.active()
            if r.get("market") == "stocks" and (r.get("config") or {}).get("trend_gate")]
    if not regs:
        pytest.skip("no running stock registration with a trend gate")
    gate = regs[0]["config"]["trend_gate"]
    assert (gate["days"], gate["symbol"]) == (bot.TREND_GATE_DAYS, bot.TREND_GATE_SYMBOL)
    assert experiment.scope_field(regs[0]) == "entry_time"
    assert experiment.verify(regs[0])
