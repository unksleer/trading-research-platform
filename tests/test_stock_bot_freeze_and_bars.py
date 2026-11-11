"""
Two defects found in stock_bot.py on 2026-11-10 (see DECISIONS.md).

1. The freeze. fetch_bars called Alpaca with no timeout. A connection that died
   without closing blocked the main loop in a socket read for good: slv-bot
   from 2026-11-03 11:39 ET, holding a position, and meta-bot from 2026-11-04
   15:01 ET. pm2 showed both online for a week.

   Fixed in two layers, and each is tested against the real thing rather than
   a mock of it: a local server that accepts a connection and never answers
   (the dead connection), and a child process blocked in a socket read (the
   frozen bot).

2. The NameError. The loop used a name `bars` that did not exist, where the
   frame is `df`. The flat-position signal log failed on every loop ("Could
   not record signal decision: name 'bars' is not defined") and the volume
   filter would have crashed had it been switched on. Tested by running the
   bot's real main loop for one pass.

No test here reads .env or touches a live bot's log or state file: the bot is
loaded under a ticker no bot uses, with the .env loader and the file log
replaced.
"""
import importlib.util
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import types

import pandas as pd
import pytest
import requests

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from utils import alpaca_http, watchdog  # noqa: E402


def _src(name):
    with open(os.path.join(DIR, name)) as handle:
        return handle.read()


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def silent_server():
    """
    A server that accepts connections and never sends a byte: what a bot sees
    when its connection has died without closing. Yields the base URL.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.2)
    held, done = [], threading.Event()

    def accept():
        while not done.is_set():
            try:
                conn, _ = listener.accept()
                held.append(conn)      # keep it open, say nothing
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    done.set()
    thread.join(2)
    for conn in held:
        conn.close()
    listener.close()


@pytest.fixture
def bars_server():
    """
    A local stand-in for data.alpaca.markets that answers the bars request the
    way Alpaca does. Yields (base URL, the timestamps it serves).
    """
    import http.server
    import json

    stamps = [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in
              pd.date_range("2026-11-02 14:00", periods=40, freq="h", tz="UTC")]
    payload = json.dumps({
        "bars": {"SPY": [{"t": t, "o": 100.0, "h": 101.0, "l": 99.0,
                          "c": 100.0 + i * 0.25, "v": 1000 + i, "n": 10,
                          "vw": 100.0} for i, t in enumerate(stamps)]},
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
    yield f"http://127.0.0.1:{server.server_address[1]}", stamps
    server.shutdown()
    server.server_close()
    thread.join(2)


SHORT = (2.0, 0.3)      # (connect, read) seconds, so the tests stay quick


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


@pytest.fixture
def bot(monkeypatch):
    """
    stock_bot.py loaded as a module, isolated from the running fleet.

    The ticker is one no bot trades, .env is not read, and no log file is
    opened, so importing it here cannot write into a live bot's files.
    """
    monkeypatch.setenv("STOCK_TICKER", "ZZTEST")
    monkeypatch.setenv("ALPACA_PAPER", "True")
    monkeypatch.setenv("STOCK_STRATEGY", "RSI_MEAN_REVERSION")
    for key in ("name", "STOCK_MIN_VOLUME_RATIO", "ZZTEST_MIN_VOLUME_RATIO",
                "STOCK_WATCHDOG_TIMEOUT_SEC", "ZZTEST_STRATEGY",
                "ALPACA_CONNECT_TIMEOUT_SEC", "ALPACA_READ_TIMEOUT_SEC"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("utils.env_loader.load", lambda *a, **k: set())
    monkeypatch.setattr(logging, "basicConfig", lambda **k: None)
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())

    spec = importlib.util.spec_from_file_location(
        "stock_bot_under_test", os.path.join(DIR, "stock_bot.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.API_KEY, module.SECRET_KEY = "test-key", "test-secret"
    return module


def run_one_pass(bot, monkeypatch, df, *, market_open=True, should_enter=False):
    """
    Run the bot's real main() for exactly one pass of the loop, flat.

    Only the edges are replaced: the market clock, the bars, the state file,
    the order and the sleep. Everything between them is the code pm2 runs.
    """
    signals, dog, buys, naps = FakeSignalLog(), FakeWatchdog(), [], []

    def fake_sleep(seconds):
        naps.append(seconds)
        raise StopLoop()

    monkeypatch.setattr(bot, "time", types.SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(bot, "is_market_open", lambda: market_open)
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: df)
    monkeypatch.setattr(bot, "load_state", lambda: {
        "position": "NONE", "entry_price": 0.0, "shares": 0.0,
        "entry_time": None, "ticker": bot.TICKER, "mode": bot.MODE})
    monkeypatch.setattr(bot, "save_state", lambda state: None)
    monkeypatch.setattr(bot, "signal_logger", lambda: signals)
    monkeypatch.setattr(bot, "place_buy",
                        lambda price: buys.append(price) or 1.0)
    if should_enter:
        monkeypatch.setattr(bot, "entry_signal", lambda ind: (True, "test entry"))
    monkeypatch.setattr(watchdog, "start", lambda *a, **k: dog)

    with pytest.raises(StopLoop):
        bot.main()
    return types.SimpleNamespace(signals=signals.rows, watchdog=dog,
                                 buys=buys, naps=naps)


# ── defect 1, layer 1: every Alpaca request has a timeout ───────────────────

def test_alpaca_py_still_has_no_timeout_of_its_own():
    """
    Why the adapter exists. If alpaca-py ever grows a timeout setting this
    fails, which is the prompt to use theirs and delete ours.
    """
    import inspect
    from alpaca.common.rest import RESTClient
    assert "timeout" not in inspect.signature(RESTClient.__init__).parameters
    assert "timeout" not in inspect.getsource(RESTClient._one_request)


def test_a_dead_data_connection_raises_instead_of_blocking(silent_server):
    """The freeze itself: get_stock_bars against a connection that never answers."""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = alpaca_http.with_timeout(
        StockHistoricalDataClient("k", "s", url_override=silent_server), SHORT)
    request = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Hour,
                               start=pd.Timestamp("2026-11-02", tz="UTC"))
    began = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        client.get_stock_bars(request)
    assert time.monotonic() - began < 10


def test_a_dead_trading_connection_raises_instead_of_blocking(silent_server):
    """Same for the client behind is_market_open, place_buy and place_sell."""
    from alpaca.trading.client import TradingClient

    client = alpaca_http.with_timeout(
        TradingClient("k", "s", paper=True, url_override=silent_server), SHORT)
    began = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        client.get_clock()
    assert time.monotonic() - began < 10


def test_default_timeout_and_its_env_override(monkeypatch):
    monkeypatch.delenv("ALPACA_CONNECT_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("ALPACA_READ_TIMEOUT_SEC", raising=False)
    assert alpaca_http.default_timeout() == (10.0, 30.0)
    monkeypatch.setenv("ALPACA_READ_TIMEOUT_SEC", "45")
    assert alpaca_http.default_timeout() == (10.0, 45.0)


@pytest.mark.parametrize("bad", ["", "0", "-5", "soon"])
def test_an_unusable_override_cannot_switch_the_timeout_off(monkeypatch, bad):
    """0 or a typo in .env must not quietly bring back 'wait forever'."""
    monkeypatch.setenv("ALPACA_READ_TIMEOUT_SEC", bad)
    monkeypatch.setenv("ALPACA_CONNECT_TIMEOUT_SEC", bad)
    assert alpaca_http.default_timeout() == (10.0, 30.0)


def test_a_client_with_no_session_is_refused_not_returned_unprotected():
    """`_session` is private to alpaca-py. If an upgrade moves it, fail loudly."""
    with pytest.raises(RuntimeError, match="no timeout can be set"):
        alpaca_http.with_timeout(object())


def test_the_bot_builds_both_clients_with_a_timeout(bot):
    assert alpaca_http.timeout_of(bot._data_client()) == (10.0, 30.0)
    assert alpaca_http.timeout_of(bot._trading_client()) == (10.0, 30.0)


def test_the_venue_client_has_a_timeout():
    """place_buy's live path and startup reconciliation go through the venue."""
    from utils.venue import AlpacaVenue
    client = AlpacaVenue("k", "s", paper=True).client()
    assert alpaca_http.timeout_of(client) == (10.0, 30.0)


def test_no_alpaca_client_is_built_outside_the_two_factories():
    """
    A new `TradingClient(...)` typed straight into the loop would have no
    timeout and nothing would say so. Both constructors may appear once each,
    inside the factory that wraps them.
    """
    src = _src("stock_bot.py")
    for constructor, factory in (("TradingClient(", "_trading_client"),
                                 ("StockHistoricalDataClient(", "_data_client")):
        assert src.count(constructor) == 1, constructor
        body = src.split(f"def {factory}():", 1)[1].split("\ndef ", 1)[0]
        assert f"with_timeout({constructor}" in body


def test_fetch_bars_survives_a_dead_connection(bot, monkeypatch, silent_server, caplog):
    """What the loop sees: an empty frame and an error in the log, in seconds."""
    from alpaca.data.historical import StockHistoricalDataClient
    monkeypatch.setattr(bot, "_data_client", lambda: alpaca_http.with_timeout(
        StockHistoricalDataClient("k", "s", url_override=silent_server), SHORT))
    began = time.monotonic()
    with caplog.at_level(logging.ERROR):
        df = bot.fetch_bars("SPY", 50)
    assert time.monotonic() - began < 10
    assert df.empty
    assert "Failed to fetch bars for SPY" in caplog.text


def test_market_clock_survives_a_dead_connection(bot, monkeypatch, silent_server, caplog):
    """is_market_open falls back to its clock-time check, as for any error."""
    from alpaca.trading.client import TradingClient
    monkeypatch.setattr(bot, "_trading_client", lambda: alpaca_http.with_timeout(
        TradingClient("k", "s", paper=True, url_override=silent_server), SHORT))
    began = time.monotonic()
    with caplog.at_level(logging.WARNING):
        assert bot.is_market_open() in (True, False)
    assert time.monotonic() - began < 10
    assert "Could not check market clock" in caplog.text


# ── defect 1, layer 2: the watchdog ─────────────────────────────────────────

def test_watchdog_expires_only_after_the_timeout():
    now = [0.0]
    dog = watchdog.LoopWatchdog(600, clock=lambda: now[0])
    assert not dog.expired()            # not started, nothing to judge
    dog.beat()
    now[0] = 599.0
    assert not dog.expired()
    now[0] = 601.0
    assert dog.expired()
    dog.beat()                          # the loop came back
    assert not dog.expired()


def test_an_announced_sleep_is_not_a_stall():
    """A bot waiting 30 minutes for the open is idle, not frozen."""
    now = [0.0]
    dog = watchdog.LoopWatchdog(600, clock=lambda: now[0])
    dog.beat(allow_sec=1800)
    now[0] = 1800 + 599
    assert not dog.expired()
    now[0] = 1800 + 601
    assert dog.expired()


def test_watchdog_thread_fires_when_the_beats_stop():
    fired = threading.Event()
    dog = watchdog.LoopWatchdog(0.2, check_every_sec=0.05,
                                on_expire=lambda d: fired.set()).start()
    assert fired.wait(5), "watchdog never fired"
    dog.stop()


def test_watchdog_thread_stays_quiet_while_the_loop_runs():
    fired = threading.Event()
    dog = watchdog.LoopWatchdog(0.3, check_every_sec=0.05,
                                on_expire=lambda d: fired.set()).start()
    for _ in range(12):                 # 0.6s of a healthy loop
        dog.beat()
        time.sleep(0.05)
    dog.stop()
    assert not fired.is_set()


def test_zero_switches_the_watchdog_off():
    dog = watchdog.start(0)
    dog.beat(allow_sec=60)              # same shape, does nothing
    assert not isinstance(dog, watchdog.LoopWatchdog)


def test_a_process_frozen_in_a_socket_read_exits_so_pm2_can_restart_it():
    """
    The frozen bot, reproduced: a main thread blocked in a read that will never
    return. Before, it stayed that way and pm2 called it online. Now it exits
    non-zero and says where it was stuck.
    """
    script = f"""
import logging, socket, sys
sys.path.insert(0, {DIR!r})
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
from utils import watchdog

def stuck_in_a_read():
    a, b = socket.socketpair()
    a.recv(1)                           # nothing will ever arrive

watchdog.start(0.5, name="frozen-test", log=logging.getLogger("t"))
stuck_in_a_read()
"""
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == watchdog.EXIT_CODE
    assert "WATCHDOG" in result.stderr
    assert "stuck_in_a_read" in result.stderr       # the stack names the place


def test_the_loop_reports_every_sleep_to_the_watchdog(bot, monkeypatch):
    run = run_one_pass(bot, monkeypatch, hourly_bars())
    assert run.naps == [bot.LOOP_INTERVAL]
    assert run.watchdog.allowed == [bot.LOOP_INTERVAL]


def test_the_market_closed_sleep_is_reported_too(bot, monkeypatch):
    monkeypatch.setattr(bot, "minutes_until_open", lambda: 90)
    run = run_one_pass(bot, monkeypatch, hourly_bars(), market_open=False)
    assert run.naps == [30 * 60]        # capped at 30 minutes, as before
    assert run.watchdog.allowed == [30 * 60]


def test_main_never_sleeps_behind_the_watchdogs_back():
    """A bare time.sleep in the loop would look like a stall after 10 minutes."""
    body = _src("stock_bot.py").split("def main():", 1)[1]
    assert body.count("time.sleep(") == 1
    assert "loop_watchdog.beat(allow_sec=seconds)\n        time.sleep(seconds)" in body


def test_watchdog_default_is_on(bot):
    assert bot.WATCHDOG_TIMEOUT_SEC == 600


# ── defect 2: `bars` did not exist ──────────────────────────────────────────

def test_fetch_bars_returns_the_timestamp_as_a_column(bot, monkeypatch, bars_server):
    """
    The shape the rest of the loop has to be written against, from a real
    alpaca-py client parsing a real response: not a frame built by hand to
    match what the fix assumes. It also shows a request that succeeds still
    succeeds with the timeout in place.
    """
    from alpaca.data.historical import StockHistoricalDataClient
    url, stamps = bars_server
    monkeypatch.setattr(bot, "_data_client", lambda: alpaca_http.with_timeout(
        StockHistoricalDataClient("k", "s", url_override=url), (2.0, 5.0)))

    df = bot.fetch_bars("SPY", 30)
    assert len(df) == 30
    assert "timestamp" in df.columns and "volume" in df.columns
    assert list(df.index) == list(range(30))        # the index is row numbers
    assert bot.latest_bar_time(df) == str(pd.Timestamp(stamps[-1]))
    assert bot.compute_indicators(df)["price"] == pytest.approx(100.0 + 39 * 0.25)


def test_latest_bar_time_refuses_a_frame_with_no_timestamp(bot):
    """
    A row number would be accepted by the signal log once and then deduplicated
    for ever after, so it must not be offered as a candle time.
    """
    with pytest.raises(KeyError):
        bot.latest_bar_time(pd.DataFrame({"close": [1.0, 2.0]}))


def test_flat_bot_records_its_signal_decision(bot, monkeypatch, caplog):
    """The line that failed 5,556 times in the SPY log."""
    df = hourly_bars()
    with caplog.at_level(logging.WARNING):
        run = run_one_pass(bot, monkeypatch, df)

    assert "Could not record signal decision" not in caplog.text
    assert "is not defined" not in caplog.text
    assert len(run.signals) == 1
    candle_time, close, position, decision = run.signals[0]
    assert candle_time == str(df["timestamp"].iloc[-1])
    assert close == pytest.approx(df["close"].iloc[-1])
    assert position == "NONE"
    assert decision["strategy"] == "RSI_MEAN_REVERSION"
    assert decision["final_signal"] == "HOLD"
    assert run.buys == []


def test_volume_filter_blocks_a_thin_bar_without_crashing(bot, monkeypatch, caplog):
    monkeypatch.setattr(bot, "MIN_VOLUME_RATIO", 1.5)
    with caplog.at_level(logging.INFO):
        run = run_one_pass(bot, monkeypatch, hourly_bars(last_volume=500.0),
                           should_enter=True)
    assert "Unexpected error" not in caplog.text
    assert "BUY blocked: volume ratio" in caplog.text
    assert run.buys == []


def test_volume_filter_lets_a_heavy_bar_through(bot, monkeypatch, caplog):
    monkeypatch.setattr(bot, "MIN_VOLUME_RATIO", 1.5)
    df = hourly_bars(last_volume=5000.0)
    with caplog.at_level(logging.INFO):
        run = run_one_pass(bot, monkeypatch, df, should_enter=True)
    assert "Unexpected error" not in caplog.text
    assert run.buys == [pytest.approx(df["close"].iloc[-1])]


def test_volume_filter_off_is_still_the_default(bot):
    """This change fixes the filter; it does not switch it on."""
    assert bot.MIN_VOLUME_RATIO == 0.0


def test_the_loop_no_longer_uses_the_name_bars():
    """
    `bars` is a local inside fetch_bars and nowhere else. In main() the frame
    is `df`.
    """
    body = _src("stock_bot.py").split("def main():", 1)[1]
    assert not re.search(r"\bbars\s*[\[.]", body)
    assert not re.search(r"len\(bars\)", body)
