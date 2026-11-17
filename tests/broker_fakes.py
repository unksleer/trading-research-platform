"""
A stand-in for Alpaca's trading API, and a harness that runs stock_bot.py's
real main() against it in an order-sending mode.

The fake sits where alpaca-py's TradingClient sits, not above it. The real
AlpacaVenue builds real order requests and parses what comes back, statuses
are alpaca-py's own enum and errors are alpaca-py's own APIError, so the code
under test is everything between the bot's decision and the HTTP call.

Each order is scripted with how the venue treats it:

  fill      accepted, filled in full the first time it is asked about
  reject    refused at submission (HTTP 403)
  hang      accepted and never filled; a cancel cancels it
  stuck     accepted and never filled; a cancel is acknowledged and ignored
  partial   half filled, then nothing; a cancel leaves the half
  silent    accepted and filled, but the reply to the submission is lost
  lost      the submission never arrives and gets no reply
"""
import json
import os
import sys
import types
import uuid
from decimal import Decimal

import pytest
import requests

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from alpaca.common.exceptions import APIError  # noqa: E402
from alpaca.trading.enums import OrderSide, OrderStatus  # noqa: E402

from utils import watchdog  # noqa: E402
from stock_bot_harness import (FakeSignalLog, FakeWatchdog, StopLoop,  # noqa: E402
                               hourly_bars, load_stock_bot)

DONE = (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED)
NINE = Decimal("0.000000001")


def api_error(status, message):
    return APIError(json.dumps({"code": status * 100000, "message": message}),
                    types.SimpleNamespace(
                        response=types.SimpleNamespace(status_code=status), request=None))


class FakeAlpaca:
    _base_url = "https://paper-api.alpaca.markets"

    def __init__(self, price=100.25):
        self.price = Decimal(str(price))    # what the next fill happens at
        self.orders = {}                    # client order id -> order
        self.held = {}                      # symbol -> Decimal shares
        self.calls = []
        self.plan = {"buy": [], "sell": []}
        self.down = False                   # every call fails, as in an outage
        self.before_submit = None           # hook: look at the disk as an order goes out
        self.foreign = []                   # open orders somebody else placed
        self.open_list_lag = 0              # times the open list still shows a cancelled order

    def script(self, side, *how):
        self.plan[side].extend(how)
        return self

    def sent(self, side=None):
        return [c for c in self.calls if c[0] == "submit" and side in (None, c[1])]

    def _outage(self):
        if self.down:
            raise requests.exceptions.ConnectionError("venue unreachable")

    def submit_order(self, request):
        self._outage()
        side = "buy" if request.side == OrderSide.BUY else "sell"
        how = self.plan[side].pop(0) if self.plan[side] else "fill"
        self.calls.append(("submit", side, request.client_order_id))
        if self.before_submit:
            self.before_submit(request)
        if how == "reject":
            raise api_error(403, "insufficient buying power")
        if how == "lost":
            raise requests.exceptions.ReadTimeout("no reply")
        order = types.SimpleNamespace(
            id=uuid.uuid4(), client_order_id=request.client_order_id,
            symbol=request.symbol, side=request.side, status=OrderStatus.ACCEPTED,
            filled_qty="0", filled_avg_price=None, notional=request.notional,
            qty=request.qty, how=how)
        self.orders[request.client_order_id] = order
        if how == "silent":
            raise requests.exceptions.ReadTimeout("order went in; the reply did not come back")
        return order

    def _wanted(self, order):
        if order.notional is not None:
            return (Decimal(str(order.notional)) / self.price).quantize(NINE)
        return Decimal(str(order.qty))

    def _fill(self, order, fraction):
        qty = (self._wanted(order) * Decimal(str(fraction))).quantize(NINE)
        order.filled_qty, order.filled_avg_price = str(qty), str(self.price)
        order.status = OrderStatus.FILLED if fraction == 1 else OrderStatus.PARTIALLY_FILLED
        signed = qty if order.side == OrderSide.BUY else -qty
        self.held[order.symbol] = self.held.get(order.symbol, Decimal("0")) + signed

    def get_order_by_client_id(self, client_id):
        self._outage()
        self.calls.append(("ask", client_id))
        order = self.orders.get(client_id)
        if order is None:
            raise api_error(404, "order not found")
        if order.status not in DONE:
            if order.how in ("fill", "silent"):
                self._fill(order, 1)
            elif order.how == "partial" and order.filled_qty == "0":
                self._fill(order, "0.5")
        return order

    def cancel_order_by_id(self, order_id):
        self._outage()
        self.calls.append(("cancel", str(order_id)))
        order = next(o for o in self.orders.values() if str(o.id) == str(order_id))
        if order.status in DONE:
            raise api_error(422, "order is not cancelable")
        if order.how != "stuck":
            order.status = OrderStatus.CANCELED

    def get_all_positions(self):
        self._outage()
        return [types.SimpleNamespace(symbol=symbol, qty=str(qty),
                                      side="long" if qty > 0 else "short")
                for symbol, qty in self.held.items() if qty != 0]

    def get_orders(self, filter=None):
        self._outage()
        symbols = set(getattr(filter, "symbols", None) or [])
        self.calls.append(("open-list",))
        listed = [o for o in list(self.orders.values()) + self.foreign if o.status not in DONE]
        if self.open_list_lag > 0:
            # What the real paper API did on 2026-11-16: the list trails the
            # order's own status.
            self.open_list_lag -= 1
            listed += [o for o in self.orders.values() if o.status == OrderStatus.CANCELED]
        return [o for o in listed if not symbols or o.symbol in symbols]


def order_sending_bot(monkeypatch, tmp_path, fake, *, live=False):
    """stock_bot.py in broker-paper mode (or live), its files in tmp_path and
    its venue the real AlpacaVenue over the fake client."""
    env = {"TRADE_AMOUNT_USD": "100", "STOCK_STOP_LOSS_PERCENT": "3.0",
           "STOCK_TAKE_PROFIT_PERCENT": "5.0", "STOCK_TRAILING_STOP_PERCENT": "0.0",
           "STOCK_TRAILING_STOP_ACTIVATION_PERCENT": "0.0",
           "STOCK_COOLDOWN_HOURS_AFTER_LOSS": "0.0", "STOCK_MIN_VOLUME_RATIO": "0.0",
           "STOCK_LOOP_INTERVAL_SEC": "60"}
    if live:
        env.update({"ALPACA_LIVE_API_KEY": "live-key",
                    "ALPACA_LIVE_SECRET_KEY": "live-secret"})
    bot = load_stock_bot(monkeypatch, broker_paper=not live, live=live, env=env)
    if live:
        fake._base_url = "https://api.alpaca.markets"
    bot.STATE_PATH = str(tmp_path / "state.json")
    bot.TRADES_PATH = str(tmp_path / "ledger.csv")
    bot.JOURNAL_PATH = str(tmp_path / "journal.json")
    bot.LOCK_PATH = str(tmp_path / "running.lock")
    bot.PAUSE_PATH = str(tmp_path / "PAUSE_BUYS")
    bot.ORDER_POLL_SEC, bot.ORDER_CANCEL_SEC, bot.ORDER_POLL_INTERVAL_SEC = 0.05, 0.05, 0.0
    bot.fake = fake
    bot._real_reconcile = bot.reconcile_orders

    from utils.venue import AlpacaVenue
    the_venue = AlpacaVenue("k", "s", paper=not live)
    the_venue._client = fake
    monkeypatch.setattr(bot, "venue", lambda: the_venue)
    monkeypatch.setattr(bot, "_pause", lambda seconds: None)
    # Every journal and state write is fsynced, which on this disk is 0.2s a
    # time. The tests are about what is written, not about the platter.
    monkeypatch.setattr(os, "fsync", lambda fd: None)
    bot.notifications = []
    monkeypatch.setattr(bot, "_notify",
                        lambda *a, **k: bot.notifications.append((a, k)))
    return bot


def run(bot, monkeypatch, ticks, *, ends=StopLoop, restart=True):
    """
    One process lifetime: the real main() from startup through `ticks` passes
    of its loop. Each tick is a dict: price (the signal price), enter (the
    strategy wants in), open (market open, default True).

    Called again, it is a restart: the bot rebuilds its journal and state from
    disk and reconciles with the broker before its first tick. With
    restart=False it is the same process carrying on: what the bot holds in
    memory is kept and there is no startup check.
    """
    from utils.market_gate import GateState
    _process_ended(bot)
    if restart:
        bot._BROKER = bot._SHARED_STATE = bot._NO_BUY_BEFORE = None
        monkeypatch.setattr(bot, "reconcile_orders", bot._real_reconcile)
    else:
        monkeypatch.setattr(bot, "reconcile_orders", lambda state=None: None)
    tick = {"n": 0}
    naps = []
    gate = GateState(False, 760.0, 750.0, session="2026-11-13")
    real_indicators = getattr(bot, "_real_indicators", bot.compute_indicators)
    bot._real_indicators = real_indicators

    def current():
        return ticks[min(tick["n"], len(ticks) - 1)]

    def fake_sleep(seconds):
        naps.append(seconds)
        tick["n"] += 1
        if tick["n"] >= len(ticks):
            raise StopLoop()

    monkeypatch.setattr(bot, "time", types.SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(bot, "is_market_open", lambda: current().get("open", True))
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: hourly_bars())
    monkeypatch.setattr(bot, "compute_indicators",
                        lambda frame: {**real_indicators(frame), "price": current()["price"]})
    monkeypatch.setattr(bot, "entry_signal",
                        lambda ind: (True, "test entry") if current().get("enter") else (False, ""))
    monkeypatch.setattr(bot, "strategy_exit_reason", lambda ind: None)
    monkeypatch.setattr(bot, "trend_gate", lambda: types.SimpleNamespace(state=lambda: gate))
    monkeypatch.setattr(bot, "signal_logger", lambda: FakeSignalLog())
    monkeypatch.setattr(watchdog, "start", lambda *a, **k: FakeWatchdog())

    try:
        with pytest.raises(ends) as stopped:
            bot.main()
    finally:
        _process_ended(bot)
    return types.SimpleNamespace(naps=naps, stopped=stopped.value)


def _process_ended(bot):
    """The kernel drops a process's run lock when the process ends. Here the
    'process' is a call to main(), so the lock is dropped by hand."""
    from utils import run_lock
    run_lock.release(getattr(bot, "_RUN_LOCK", None))
    bot._RUN_LOCK = None


def state_of(bot):
    with open(bot.STATE_PATH) as handle:
        return json.load(handle)


def ledger_of(bot):
    import csv
    if not os.path.exists(bot.TRADES_PATH):
        return []
    with open(bot.TRADES_PATH, newline="") as handle:
        return list(csv.DictReader(handle))


def journal_of(bot):
    with open(bot.JOURNAL_PATH) as handle:
        return json.load(handle)


def holding(bot, fake, shares="0.997506234", entry=100.25, signal=100.0):
    """Put the bot and the broker in the same open position, as if an earlier
    buy had filled."""
    fake.held["ZZTEST"] = Decimal(shares)
    bot._SHARED_STATE = None
    bot.save_state({"position": "LONG", "entry_price": entry, "shares": float(shares),
                    "highest_price": entry, "entry_time": "2026-11-16T15:00:00+00:00",
                    "entry_signal_price": signal, "entry_order_id": "entry-order"})
