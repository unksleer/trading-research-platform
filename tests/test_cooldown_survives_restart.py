"""
The cooldown after a loss must survive a restart.

The rule (stocks v4 and v5): no new entry for six hours after a trade that
closed at a loss. The bot kept the last exit's time and result in memory and
never wrote them to the state file, so a process that restarted inside the six
hours had forgotten the loss and was free to buy again at once. Restarts are
not rare: the watchdog ends a stuck bot, pm2 brings it back, and the owner
restarts the fleet to load new code.

These tests run the real main() against real state and ledger files in a temp
directory. A "restart" is a fresh load of stock_bot.py pointed at the same
files, which is what pm2 does. Only the edges are replaced: the clock, the
market, the bars, the entry signal, the trend gate and the email.
"""
import csv
import json
import logging
import os
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from utils import watchdog  # noqa: E402
from stock_bot_harness import (FakeSignalLog, FakeWatchdog, StopLoop,  # noqa: E402
                               hourly_bars, load_stock_bot)
from test_simulated_path_unchanged import ENV, UNSET  # noqa: E402

BEFORE_THE_FIX = "ef617db"      # last commit in which the cooldown was memory only
START = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)

BUY = {"price": 100.00, "enter": True}
STOP = {"price": 96.90}                     # -3.1% against a 3% stop
TARGET = {"price": 106.00}                  # +6% against a 5% target


def session(monkeypatch, tmp_path, ticks, *, at=START, cooldown="6.0", path=None,
            name="stock_bot_cooldown"):
    """One life of the process: load stock_bot.py, run main() through `ticks`
    starting at `at`, against the files in tmp_path. Returns what it did."""
    for key in UNSET:
        monkeypatch.delenv(key, raising=False)
    bot = load_stock_bot(monkeypatch, path=path, name=name,
                         env={**ENV, "STOCK_COOLDOWN_HOURS_AFTER_LOSS": cooldown})
    bot.STATE_PATH = str(tmp_path / "state_stock_zztest_paper.json")
    bot.TRADES_PATH = str(tmp_path / "completed_trades_stock_zztest_paper.csv")
    bot._SHARED_STATE = None

    tick = {"n": 0}
    out = types.SimpleNamespace(notifications=[], logs=[], bot=bot)

    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return at + timedelta(seconds=cls.calls)

    def current():
        return ticks[min(tick["n"], len(ticks) - 1)]

    def fake_sleep(seconds):
        tick["n"] += 1
        if tick["n"] >= len(ticks):
            raise StopLoop()

    class Capture(logging.Handler):
        def emit(self, record):
            out.logs.append(record.getMessage())

    from utils.market_gate import GateState
    gate = GateState(False, 760.0, 750.0, session="2026-11-13")     # entries allowed
    real_indicators = bot.compute_indicators
    handler = Capture()
    bot.log.addHandler(handler)
    bot.log.setLevel(logging.INFO)

    monkeypatch.setattr(bot, "datetime", Clock)
    monkeypatch.setattr(bot, "time", types.SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(bot, "is_market_open", lambda: True)
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: hourly_bars())
    monkeypatch.setattr(bot, "compute_indicators",
                        lambda frame: {**real_indicators(frame), "price": current()["price"]})
    monkeypatch.setattr(bot, "entry_signal",
                        lambda ind: (True, "test entry") if current().get("enter") else (False, ""))
    monkeypatch.setattr(bot, "trend_gate", lambda: types.SimpleNamespace(state=lambda: gate))
    monkeypatch.setattr(bot, "signal_logger", lambda: FakeSignalLog())
    monkeypatch.setattr(bot, "_notify", lambda *a, **k: out.notifications.append(a[0]))
    monkeypatch.setattr(watchdog, "start", lambda *a, **k: FakeWatchdog())
    try:
        with pytest.raises(StopLoop):
            bot.main()
    finally:
        bot.log.removeHandler(handler)

    with open(bot.STATE_PATH) as handle:
        out.state = json.load(handle)
    out.blocked = [line for line in out.logs if "BUY blocked: cooldown" in line]
    return out


def ledger(tmp_path):
    with open(tmp_path / "completed_trades_stock_zztest_paper.csv") as handle:
        return list(csv.DictReader(handle))


def test_a_losing_exit_is_written_to_the_state_file(monkeypatch, tmp_path):
    out = session(monkeypatch, tmp_path, [BUY, STOP])
    (trade,) = ledger(tmp_path)
    assert trade["exit_reason"] == "Stop Loss Triggered"
    assert out.state["position"] == "NONE"
    assert out.state["last_exit_time"] == trade["exit_time"]
    assert out.state["last_exit_pnl"] == pytest.approx(float(trade["pnl_usd"]), abs=1e-3)
    assert out.state["last_exit_pnl"] < 0


def test_a_restart_inside_the_six_hours_does_not_buy(monkeypatch, tmp_path):
    session(monkeypatch, tmp_path, [BUY, STOP])
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1),
                    name="stock_bot_restarted")
    assert again.notifications == []
    assert again.state["position"] == "NONE"
    assert len(again.blocked) == 1 and "/ 6h after loss" in again.blocked[0]
    assert len(ledger(tmp_path)) == 1


def test_a_restart_after_the_six_hours_buys(monkeypatch, tmp_path):
    session(monkeypatch, tmp_path, [BUY, STOP])
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=6, minutes=5),
                    name="stock_bot_restarted")
    assert again.notifications == ["BUY"]
    assert again.state["position"] == "LONG"
    assert again.blocked == []


def test_two_restarts_inside_the_six_hours_still_do_not_buy(monkeypatch, tmp_path):
    """The record must survive a save made by a process that only read it."""
    session(monkeypatch, tmp_path, [BUY, STOP])
    session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1), name="restart_one")
    third = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=5),
                    name="restart_two")
    assert third.notifications == [] and len(third.blocked) == 1


def test_a_winning_exit_starts_no_cooldown_across_a_restart(monkeypatch, tmp_path):
    first = session(monkeypatch, tmp_path, [BUY, TARGET])
    assert first.state["last_exit_pnl"] > 0
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1),
                    name="stock_bot_restarted")
    assert again.notifications == ["BUY"] and again.blocked == []


def test_the_record_stays_in_the_file_while_the_next_position_is_open(monkeypatch, tmp_path):
    """A loss, then a buy after the six hours: the file still opens and still
    says what the last exit was. Only the next exit replaces it."""
    session(monkeypatch, tmp_path, [BUY, STOP])
    held = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=7),
                   name="stock_bot_restarted")
    assert held.state["position"] == "LONG" and held.state["last_exit_pnl"] < 0
    closed = session(monkeypatch, tmp_path, [TARGET], at=START + timedelta(hours=8),
                     name="stock_bot_third")
    assert closed.state["position"] == "NONE" and closed.state["last_exit_pnl"] > 0


def test_with_the_cooldown_off_a_restart_changes_nothing(monkeypatch, tmp_path):
    session(monkeypatch, tmp_path, [BUY, STOP], cooldown="0.0")
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1),
                    cooldown="0.0", name="stock_bot_restarted")
    assert again.notifications == ["BUY"] and again.blocked == []


def test_a_state_file_written_before_the_fix_reads_as_no_cooldown(monkeypatch, tmp_path):
    """
    The files on disk today have no record of the last exit. The bot cannot
    know what it never wrote down, so the first restart onto the fixed code
    behaves as before; the cooldown holds across restarts from the next exit.
    """
    session(monkeypatch, tmp_path, [BUY, STOP])
    path = tmp_path / "state_stock_zztest_paper.json"
    state = json.loads(path.read_text())
    del state["last_exit_time"], state["last_exit_pnl"]
    path.write_text(json.dumps(state, indent=4))
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1),
                    name="stock_bot_restarted")
    assert again.notifications == ["BUY"]


def test_the_file_before_the_fix_forgot_the_loss(monkeypatch, tmp_path):
    """The defect, shown on the old file itself: same loss, same restart an
    hour later, and it buys."""
    old = subprocess.run(["git", "show", f"{BEFORE_THE_FIX}:stock_bot.py"], cwd=DIR,
                         capture_output=True, text=True)
    if old.returncode != 0:
        pytest.skip(f"commit {BEFORE_THE_FIX} is not in this checkout")
    old_dir = tmp_path / "before"
    old_dir.mkdir()
    old_path = str(old_dir / "stock_bot.py")
    (old_dir / "stock_bot.py").write_text(old.stdout)

    first = session(monkeypatch, tmp_path, [BUY, STOP], path=old_path, name="old_first")
    assert "last_exit_pnl" not in first.state
    again = session(monkeypatch, tmp_path, [BUY], at=START + timedelta(hours=1),
                    path=old_path, name="old_restarted")
    assert again.notifications == ["BUY"] and again.blocked == []


def test_without_a_restart_the_cooldown_worked_before_and_works_now(monkeypatch, tmp_path):
    """Not part of the defect, and not changed by the fix."""
    out = session(monkeypatch, tmp_path, [BUY, STOP, BUY])
    assert out.notifications == ["BUY", "SELL"] and len(out.blocked) == 1


@pytest.mark.parametrize("broker_paper", [False, True])
def test_the_record_is_kept_for_a_bot_that_sends_orders_too(monkeypatch, broker_paper):
    bot = load_stock_bot(monkeypatch, broker_paper=broker_paper,
                         name=f"stock_bot_schema_{broker_paper}")
    assert bot.SENDS_ORDERS is broker_paper
    written = bot._to_shared_schema({
        "position": "NONE", "last_exit_time": "2026-11-16T15:00:07+00:00",
        "last_exit_pnl": -3.1})
    assert written["last_exit_time"] == "2026-11-16T15:00:07+00:00"
    assert written["last_exit_pnl"] == -3.1
    # A bot that has never closed a trade gains no keys.
    assert "last_exit_time" not in bot._to_shared_schema({"position": "NONE"})
