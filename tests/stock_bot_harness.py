"""
Shared harness for tests that run stock_bot.py's real code.

`bot` loads stock_bot.py as a module, isolated from the running fleet: a ticker
no bot trades, .env not read, no log file opened. `run_one_pass` runs the real
main() for one pass of its loop with only the edges replaced.
"""
import importlib.util
import logging
import os
import sys
import types

import pandas as pd
import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from utils import watchdog  # noqa: E402


class StopLoop(BaseException):
    """Raised from the bot's sleep to end main() after one pass. Not an
    Exception, so the loop's own `except Exception` cannot swallow it."""


class FakeSignalLog:
    def __init__(self):
        self.rows = []

    def record(self, candle_time, close, position, decision):
        self.rows.append((candle_time, close, position, decision))
        return True


class FakeWatchdog:
    def __init__(self):
        self.allowed = []

    def beat(self, allow_sec=0.0):
        self.allowed.append(allow_sec)

    def stop(self):
        pass


def hourly_bars(n=150, last_volume=1000.0):
    """Bars in the shape fetch_bars returns: timestamp is a COLUMN."""
    stamps = pd.date_range("2026-11-02 14:00", periods=n, freq="h", tz="UTC")
    closes = [100.0 + (i % 7) * 0.3 for i in range(n)]
    volume = [1000.0] * (n - 1) + [last_volume]
    return pd.DataFrame({"timestamp": stamps, "open": closes, "high": closes,
                         "low": closes, "close": closes, "volume": volume})


def load_stock_bot(monkeypatch, path=None, *, name="stock_bot_under_test",
                   broker_paper=False, live=False, env=None, test_keys=True):
    """
    Load a stock_bot.py as a module, isolated from the running fleet: a ticker
    no bot trades, .env not read, no log file opened. `path` lets a test load
    another copy of the file (the one from before a change, say).
    `broker_paper` and `live` load it the way broker_paper_bot.py and
    live_bot.py do: the mode is set in utils.execution_mode, not in the
    environment.
    """
    monkeypatch.setenv("STOCK_TICKER", "ZZTEST")
    monkeypatch.setenv("ALPACA_PAPER", "True")
    monkeypatch.setenv("STOCK_STRATEGY", "RSI_MEAN_REVERSION")
    for key in ("name", "STOCK_MIN_VOLUME_RATIO", "ZZTEST_MIN_VOLUME_RATIO",
                "STOCK_WATCHDOG_TIMEOUT_SEC", "ZZTEST_STRATEGY",
                "STOCK_TREND_GATE_DAYS", "STOCK_TREND_GATE_SYMBOL",
                "ALPACA_CONNECT_TIMEOUT_SEC", "ALPACA_READ_TIMEOUT_SEC"):
        monkeypatch.delenv(key, raising=False)
    if live:
        monkeypatch.setenv("ALPACA_PAPER", "False")
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("utils.env_loader.load", lambda *a, **k: set())
    monkeypatch.setattr(logging, "basicConfig", lambda **k: None)
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    from utils import execution_mode
    monkeypatch.setattr(execution_mode, "REQUESTED",
                        execution_mode.BROKER_PAPER if broker_paper
                        else (execution_mode.LIVE if live else None))

    spec = importlib.util.spec_from_file_location(
        name, path or os.path.join(DIR, "stock_bot.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if test_keys:
        module.API_KEY, module.SECRET_KEY = "test-key", "test-secret"
    return module


@pytest.fixture
def bot(monkeypatch):
    """
    stock_bot.py loaded as a module, isolated from the running fleet.

    The ticker is one no bot trades, .env is not read, and no log file is
    opened, so importing it here cannot write into a live bot's files.
    """
    return load_stock_bot(monkeypatch)


def run_one_pass(bot, monkeypatch, df, *, market_open=True, should_enter=False,
                 gate=None, state=None, price=None):
    """
    Run the bot's real main() for exactly one pass of the loop. Flat unless a
    `state` is given.

    Only the edges are replaced: the market clock, the bars, the state file,
    the orders, the trend gate's answer and the sleep. Everything between them
    is the code pm2 runs. `gate` is the GateState the trend gate reports; the
    default is one that allows entries, so tests about other things are not
    about the gate.
    """
    from utils.market_gate import GateState
    signals, dog, buys, naps = FakeSignalLog(), FakeWatchdog(), [], []
    sells, gate_calls = [], []
    if gate is None:
        gate = GateState(False, 760.0, 750.0, session="2026-11-13")

    def gate_state():
        gate_calls.append(1)
        return gate

    def fake_sleep(seconds):
        naps.append(seconds)
        raise StopLoop()

    monkeypatch.setattr(bot, "time", types.SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(bot, "is_market_open", lambda: market_open)
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: df)
    monkeypatch.setattr(bot, "load_state", lambda: dict(state) if state else {
        "position": "NONE", "entry_price": 0.0, "shares": 0.0,
        "entry_time": None, "ticker": bot.TICKER, "mode": bot.MODE})
    monkeypatch.setattr(bot, "trend_gate",
                        lambda: types.SimpleNamespace(state=gate_state))
    monkeypatch.setattr(bot, "place_sell",
                        lambda shares, px, reason: sells.append((shares, px, reason)))
    monkeypatch.setattr(bot, "record_trade", lambda st, px, reason: None)
    if price is not None:
        real_indicators = bot.compute_indicators
        monkeypatch.setattr(bot, "compute_indicators",
                            lambda frame: {**real_indicators(frame), "price": price})
    monkeypatch.setattr(bot, "save_state", lambda state: None)
    monkeypatch.setattr(bot, "signal_logger", lambda: signals)
    monkeypatch.setattr(bot, "place_buy",
                        lambda price: buys.append(price) or 1.0)
    if should_enter:
        monkeypatch.setattr(bot, "entry_signal", lambda ind: (True, "test entry"))
    monkeypatch.setattr(watchdog, "start", lambda *a, **k: dog)

    with pytest.raises(StopLoop):
        bot.main()
    return types.SimpleNamespace(signals=signals.rows, watchdog=dog, buys=buys,
                                 naps=naps, sells=sells, gate_calls=len(gate_calls))


