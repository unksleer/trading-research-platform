"""
The real-order path, run through stock_bot.py's real main() against a fake
Alpaca (tests/broker_fakes.py). No test here touches a network.

What was wrong before 2026-11-16, each now a test below:

  1. "Paper" sent no order at all, so the order path had never run.
  2. A sell that failed was logged and then recorded as a closed trade; the
     bot set itself flat with the shares still at the broker.
  3. A buy was recorded at the signal price and a share count worked out from
     the signal price. The fill was never read.
  4. Sells had no client order id and no journal entry.
  5. alpaca-py's order status was read with str(), which gives
     "OrderStatus.FILLED": no status ever compared equal to anything.
"""
import logging
import os
import sys
from decimal import Decimal

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from broker_fakes import (FakeAlpaca, holding, journal_of, ledger_of,  # noqa: E402
                          order_sending_bot, run, state_of)
from stock_bot_harness import load_stock_bot  # noqa: E402
from utils import broker_orders  # noqa: E402
from utils.venue import AlpacaVenue  # noqa: E402

MISMATCH = 78


@pytest.fixture
def fake():
    return FakeAlpaca(price=100.25)


@pytest.fixture
def bot(monkeypatch, tmp_path, fake):
    return order_sending_bot(monkeypatch, tmp_path, fake)


BUY = {"price": 100.00, "enter": True}
QUIET = {"price": 100.00}
TAKE_PROFIT = {"price": 106.00}         # +5.7% on a 100.25 entry
STOP_LOSS = {"price": 96.00}


# ── a third mode, with files of its own ─────────────────────────────────────

def test_broker_paper_is_a_mode_of_its_own(bot):
    assert bot.MODE == "BROKERPAPER"
    assert bot.BROKER_PAPER and bot.SENDS_ORDERS and bot.IS_PAPER


def test_its_files_cannot_collide_with_the_simulated_bot_for_the_same_ticker(monkeypatch):
    simulated = load_stock_bot(monkeypatch, name="simulated")
    rehearsal = load_stock_bot(monkeypatch, name="rehearsal", broker_paper=True)
    live = load_stock_bot(monkeypatch, name="live", env={"ALPACA_PAPER": "False"})

    def files(b):
        signal = os.path.join(b.SIGNAL_LOG[1], f"signal_log_{b.SIGNAL_LOG[0].lower()}.csv")
        return {os.path.abspath(p) for p in
                (b.STATE_PATH, b.TRADES_PATH, b.JOURNAL_PATH, b.log_path, signal)}

    assert len(files(simulated)) == len(files(rehearsal)) == len(files(live)) == 5
    assert not files(simulated) & files(rehearsal)
    assert not files(simulated) & files(live)
    assert not files(rehearsal) & files(live)


def test_the_dashboard_and_observer_cannot_mistake_a_rehearsal_for_the_real_run(monkeypatch):
    """
    They find files by pattern in the project root. A rehearsal ledger there
    would be summed as live P&L (dashboard.py: completed_trades_*.csv less
    _dry and _paper) and a rehearsal position would be listed with the
    registered run's (utils/positions.py: state_*.json).
    """
    import fnmatch
    rehearsal = load_stock_bot(monkeypatch, broker_paper=True)
    for path in (rehearsal.STATE_PATH, rehearsal.TRADES_PATH, rehearsal.JOURNAL_PATH):
        assert os.path.dirname(path) == os.path.join(DIR, "broker_paper")
    for pattern in ("state_*.json", "completed_trades_*.csv",
                    "completed_trades_stock_*_paper.csv", "logs/signal_log_*.csv"):
        for path in (rehearsal.STATE_PATH, rehearsal.TRADES_PATH,
                     os.path.join(rehearsal.SIGNAL_LOG[1], "signal_log_stock-zztest.csv")):
            assert not fnmatch.fnmatch(os.path.relpath(path, DIR), pattern), (path, pattern)
    with open(os.path.join(DIR, ".gitignore")) as handle:
        assert "broker_paper/" in handle.read().split()      # the repo is public


def test_broker_paper_with_alpaca_paper_false_refuses_to_start(monkeypatch):
    with pytest.raises(SystemExit, match="live endpoint"):
        load_stock_bot(monkeypatch, broker_paper=True, env={"ALPACA_PAPER": "False"})


def test_an_unknown_execution_mode_refuses_to_start(monkeypatch):
    from utils import execution_mode
    load_stock_bot(monkeypatch)                         # sets REQUESTED back to None
    monkeypatch.setattr(execution_mode, "REQUESTED", "TURBO")
    import importlib.util
    spec = importlib.util.spec_from_file_location("x", os.path.join(DIR, "stock_bot.py"))
    with pytest.raises(SystemExit, match="Unknown execution mode"):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))


def test_a_live_bot_reads_its_own_keys_never_the_paper_ones(monkeypatch):
    env = {"ALPACA_PAPER": "False", "ALPACA_API_KEY": "paper-key",
           "ALPACA_SECRET_KEY": "paper-secret"}
    monkeypatch.delenv("ALPACA_LIVE_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_SECRET_KEY", raising=False)
    live = load_stock_bot(monkeypatch, env=env, test_keys=False)
    assert live.MODE == "LIVE" and live.SENDS_ORDERS
    assert (live.API_KEY, live.SECRET_KEY) == ("", "")      # so main() exits
    live = load_stock_bot(monkeypatch, test_keys=False, env={
        **env, "ALPACA_LIVE_API_KEY": "live-key", "ALPACA_LIVE_SECRET_KEY": "live-secret"})
    assert (live.API_KEY, live.SECRET_KEY) == ("live-key", "live-secret")
    paper = load_stock_bot(monkeypatch, test_keys=False, env={
        "ALPACA_API_KEY": "paper-key", "ALPACA_SECRET_KEY": "paper-secret",
        "ALPACA_LIVE_API_KEY": "live-key", "ALPACA_LIVE_SECRET_KEY": "live-secret"})
    assert (paper.API_KEY, paper.SECRET_KEY) == ("paper-key", "paper-secret")


def test_the_simulated_functions_refuse_to_run_in_an_order_sending_bot(bot):
    with pytest.raises(RuntimeError):
        bot.place_buy(100.0)
    with pytest.raises(RuntimeError):
        bot.place_sell(1.0, 100.0, "x")


# ── a buy ───────────────────────────────────────────────────────────────────

def test_a_buy_is_journalled_before_it_is_sent(bot, fake, monkeypatch):
    on_disk = []
    fake.before_submit = lambda request: on_disk.append(
        journal_of(bot)[request.client_order_id])
    run(bot, monkeypatch, [BUY])

    assert len(on_disk) == 1
    intent = on_disk[0]
    assert intent["side"] == "BUY" and intent["status"] == "PENDING"
    assert intent["signal_price"] == 100.0 and intent["notional"] == 100.0
    assert intent["resolved"] is False and intent["applied"] is False
    (cid, sent), = [(c[2], c) for c in fake.sent("buy")]
    assert cid.startswith("zztest-buy-")


def test_state_is_written_from_the_fill_not_the_signal(bot, fake, monkeypatch):
    run(bot, monkeypatch, [BUY])
    state = state_of(bot)
    assert state["position"] == "LONG"
    assert state["entry_price"] == 100.25                   # the fill; the signal was 100.00
    assert state["shares"] == pytest.approx(0.997506234)    # $100 / 100.25, from the venue
    assert state["shares"] != round(100 / 100.00, 6)        # what the old code stored
    assert state["entry_signal_price"] == 100.0
    assert state["highest_price"] == 100.25
    assert fake.held["ZZTEST"] == Decimal("0.997506234")

    (cid, entry), = journal_of(bot).items()
    assert entry["status"] == "FILLED" and entry["resolved"] and entry["applied"]
    assert entry["filled_avg_price"] == "100.25"
    assert state["entry_order_id"] == entry["order_id"] != ""
    assert state["applied_orders"] == [cid]
    (args, kwargs), = bot.notifications
    assert args[0] == "BUY" and args[1] == 100.25


def test_a_refused_buy_opens_nothing_and_is_not_hammered(bot, fake, monkeypatch, caplog):
    fake.script("buy", "reject")
    with caplog.at_level(logging.INFO):
        run(bot, monkeypatch, [BUY, BUY, BUY])
    assert state_of_or_flat(bot)["position"] == "NONE"
    assert len(fake.sent("buy")) == 1                       # not once a minute
    assert "BUY not filled (NOT_PLACED)" in caplog.text
    assert "No new attempt before" in caplog.text
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "NOT_PLACED" and entry["refused"] is True
    assert ledger_of(bot) == [] and bot.notifications == []


def state_of_or_flat(bot):
    return state_of(bot) if os.path.exists(bot.STATE_PATH) else {"position": "NONE"}


def test_a_buy_that_does_not_fill_in_time_is_cancelled_and_opens_nothing(bot, fake, monkeypatch):
    fake.script("buy", "hang")
    run(bot, monkeypatch, [BUY])
    assert state_of_or_flat(bot)["position"] == "NONE"
    assert [c[0] for c in fake.calls if c[0] == "cancel"] == ["cancel"]
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "CANCELED" and entry["resolved"] and entry["applied"]
    assert fake.get_orders() == []                          # nothing left working


def test_a_buy_whose_reply_was_lost_is_found_by_its_client_id(bot, fake, monkeypatch):
    """The order went in; the answer did not come back. Without the lookup the
    bot would be flat on paper and long at the broker."""
    fake.script("buy", "silent")
    run(bot, monkeypatch, [BUY])
    assert state_of(bot)["position"] == "LONG"
    assert state_of(bot)["entry_price"] == 100.25
    assert len(fake.sent("buy")) == 1


def test_a_buy_with_no_reply_and_no_order_is_not_written_off_too_early(bot, fake, monkeypatch):
    """
    Silence is not a refusal. "No such order" straight after a send that got no
    reply may only mean the order has not arrived yet, so nothing else is sent
    until it has had time to.
    """
    fake.script("buy", "lost")
    run(bot, monkeypatch, [BUY, BUY, BUY])
    (entry,) = journal_of(bot).values()
    assert entry["resolved"] is False and entry["refused"] is False
    assert len(fake.sent("buy")) == 1                       # held, not retried

    monkeypatch.setattr(broker_orders, "IN_FLIGHT_GRACE_SEC", 0.0)
    run(bot, monkeypatch, [QUIET])                          # later: still not there
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "NOT_PLACED" and entry["resolved"] and entry["applied"]
    assert state_of_or_flat(bot)["position"] == "NONE"


def test_nothing_is_sent_while_an_order_has_no_final_answer(bot, fake, monkeypatch, caplog):
    fake.script("buy", "stuck")                             # cancel acknowledged, ignored
    with caplog.at_level(logging.WARNING):
        run(bot, monkeypatch, [BUY, BUY, BUY])
    assert len(fake.sent("buy")) == 1
    assert "still has no final answer from the broker" in caplog.text
    assert state_of_or_flat(bot)["position"] == "NONE"

    # The venue finally fills it. The next tick writes that fill into state.
    (order,) = fake.orders.values()
    order.how = "fill"
    run(bot, monkeypatch, [QUIET], restart=False)
    assert state_of(bot)["position"] == "LONG"
    assert state_of(bot)["entry_price"] == 100.25


# ── a sell ──────────────────────────────────────────────────────────────────

def test_a_sell_is_journalled_with_a_client_id_before_it_is_sent(bot, fake, monkeypatch):
    holding(bot, fake)
    on_disk = []
    fake.before_submit = lambda request: on_disk.append(
        (request.client_order_id, journal_of(bot)[request.client_order_id]))
    run(bot, monkeypatch, [TAKE_PROFIT])
    (cid, intent), = on_disk
    assert cid.startswith("zztest-sell-")
    assert intent["side"] == "SELL" and intent["status"] == "PENDING"
    assert intent["signal_price"] == 106.0
    assert intent["reason"] == "Take Profit Triggered"
    assert intent["qty"] == "0.997506234"                   # the broker's figure, exactly


def test_a_filled_sell_closes_the_position_and_the_ledger_has_both_prices(bot, fake, monkeypatch):
    holding(bot, fake, entry=100.25, signal=100.0)
    fake.price = Decimal("105.90")                          # the sell fills under its signal
    run(bot, monkeypatch, [TAKE_PROFIT])

    assert state_of(bot)["position"] == "NONE" and state_of(bot)["shares"] == 0.0
    assert "exit_pending" not in state_of(bot)
    assert fake.held["ZZTEST"] == 0
    (row,) = ledger_of(bot)
    assert row["mode"] == "BROKERPAPER" and row["exit_reason"] == "Take Profit Triggered"
    assert float(row["entry_price"]) == 100.25 and float(row["entry_signal_price"]) == 100.0
    assert float(row["exit_price"]) == 105.90 and float(row["exit_signal_price"]) == 106.0
    assert float(row["entry_fill_minus_signal_pct"]) == pytest.approx(0.25)
    assert float(row["exit_fill_minus_signal_pct"]) == pytest.approx(-0.0943, abs=1e-4)
    # P&L is from the fills, not the signals.
    assert float(row["pnl_usd"]) == pytest.approx((105.90 - 100.25) * 0.997506234, abs=1e-4)
    assert float(row["shares"]) == pytest.approx(0.997506234)
    assert row["exit_attempts"] == "1" and row["exit_order_id"] and row["entry_order_id"]
    (args, kwargs), = bot.notifications
    assert args[0] == "SELL" and args[1] == 105.90


def test_a_refused_sell_leaves_the_position_open_and_records_no_trade(bot, fake, monkeypatch, caplog):
    """Defect 2. Before: logged, then recorded as closed, with the shares
    still at the broker."""
    holding(bot, fake)
    fake.script("sell", "reject")
    with caplog.at_level(logging.ERROR):
        run(bot, monkeypatch, [STOP_LOSS])
    state = state_of(bot)
    assert state["position"] == "LONG" and state["shares"] == pytest.approx(0.997506234)
    assert fake.held["ZZTEST"] == Decimal("0.997506234")
    assert ledger_of(bot) == [] and bot.notifications == []
    assert "SELL not filled (NOT_PLACED), attempt 1" in caplog.text
    assert "Position stays OPEN" in caplog.text
    assert state["exit_pending"]["reason"] == "Stop Loss Triggered"
    assert state["exit_pending"]["signal_price"] == 96.0


def test_an_unfilled_sell_is_retried_on_the_next_tick_even_if_the_signal_has_gone(bot, fake, monkeypatch):
    """
    The exit is owed once decided. Here the price has come back inside the
    stop by the next tick, and an RSI exit is a crossing that is only true on
    one bar; neither may cancel an exit that was already ordered.
    """
    holding(bot, fake, entry=100.25, signal=100.0)
    fake.script("sell", "reject", "hang", "fill")
    fake.price = Decimal("99.00")
    run(bot, monkeypatch, [STOP_LOSS, {"price": 99.50}, {"price": 99.60}])

    assert len(fake.sent("sell")) == 3
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert row["exit_reason"] == "Stop Loss Triggered"
    assert row["exit_attempts"] == "3"
    assert float(row["exit_signal_price"]) == 96.0          # the first decision's price
    assert float(row["exit_price"]) == 99.0
    statuses = [e["status"] for e in journal_of(bot).values() if e["side"] == "SELL"]
    assert sorted(statuses) == ["CANCELED", "FILLED", "NOT_PLACED"]


def test_a_sell_whose_reply_was_lost_is_not_sent_twice(bot, fake, monkeypatch):
    """A second sell of a position already sold is a short sale."""
    holding(bot, fake)
    fake.script("sell", "silent")
    run(bot, monkeypatch, [TAKE_PROFIT, QUIET, QUIET])
    assert len(fake.sent("sell")) == 1
    assert state_of(bot)["position"] == "NONE"
    assert fake.held["ZZTEST"] == 0
    assert len(ledger_of(bot)) == 1


def test_a_partly_filled_sell_keeps_the_rest_open_and_makes_one_ledger_row(bot, fake, monkeypatch):
    holding(bot, fake, shares="1.000000000", entry=100.0, signal=100.0)
    fake.script("sell", "partial", "fill")
    fake.price = Decimal("106.00")
    run(bot, monkeypatch, [TAKE_PROFIT])
    state = state_of(bot)
    assert state["position"] == "LONG" and state["shares"] == pytest.approx(0.5)
    assert fake.held["ZZTEST"] == Decimal("0.5")
    assert ledger_of(bot) == []                             # not closed yet

    fake.price = Decimal("104.00")
    run(bot, monkeypatch, [QUIET])                          # a restart in between, too
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert float(row["shares"]) == pytest.approx(1.0)
    assert float(row["exit_price"]) == pytest.approx(105.0)     # half at 106, half at 104
    assert float(row["pnl_usd"]) == pytest.approx(5.0)
    assert row["exit_attempts"] == "2"


def test_a_sell_is_not_sent_when_the_broker_does_not_hold_what_the_bot_thinks(bot, fake, monkeypatch, caplog):
    """Selling shares that are not there opens a short. The bot stops."""
    holding(bot, fake)
    run(bot, monkeypatch, [QUIET])                          # starts clean
    fake.held["ZZTEST"] = Decimal("0")                      # sold by hand, say
    with caplog.at_level(logging.CRITICAL):
        result = run(bot, monkeypatch, [TAKE_PROFIT], ends=SystemExit, restart=False)
    assert result.stopped.code == MISMATCH
    assert fake.sent("sell") == []
    assert "BROKER MISMATCH" in caplog.text and "the broker holds 0" in caplog.text
    assert state_of(bot)["position"] == "LONG" and ledger_of(bot) == []


def test_a_buy_is_not_sent_when_the_broker_already_holds_the_ticker(bot, fake, monkeypatch):
    run(bot, monkeypatch, [QUIET])
    fake.held["ZZTEST"] = Decimal("2")
    result = run(bot, monkeypatch, [BUY], ends=SystemExit, restart=False)
    assert result.stopped.code == MISMATCH and fake.sent("buy") == []


def test_a_broker_that_cannot_be_asked_is_not_a_mismatch(bot, fake, monkeypatch, caplog):
    """An outage in the middle of the day must not stop the bot: no order goes
    out, the position stays open, and the next tick tries again."""
    holding(bot, fake)
    run(bot, monkeypatch, [QUIET])
    fake.down = True
    with caplog.at_level(logging.ERROR):
        run(bot, monkeypatch, [STOP_LOSS], restart=False)
    assert fake.sent("sell") == [] and state_of(bot)["position"] == "LONG"
    assert "could not read the broker's position" in caplog.text
    fake.down = False
    fake.price = Decimal("96.10")
    run(bot, monkeypatch, [STOP_LOSS], restart=False)
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert row["exit_attempts"] == "2" and float(row["exit_price"]) == 96.10


def test_a_sell_goes_ahead_when_the_journal_cannot_be_written_but_a_buy_does_not(tmp_path):
    """
    Changed on 2026-11-16. The rule used to be "a journalling failure never
    blocks a trade", for both sides. For a buy that is backwards with real
    orders: a position opened with no record of the order is the thing the
    journal exists to prevent, and a missed entry costs nothing. For a sell
    the old rule stands: a full disk must not stand between a stop and its
    order.
    """
    fake = FakeAlpaca()
    venue = AlpacaVenue("k", "s", paper=True)
    venue._client = fake
    orders = broker_orders.BrokerOrders(
        venue, "ZZTEST", str(tmp_path / "journal.json"), logging.getLogger("t"),
        poll_timeout=0.05, poll_interval=0.0, cancel_timeout=0.05)

    def disk_full():
        raise OSError(28, "No space left on device")
    orders._write = disk_full

    with pytest.raises(broker_orders.JournalError):
        orders.buy(100.0, 100.0)
    assert fake.sent() == [] and orders.entries == {}

    fake.held["ZZTEST"] = Decimal("1")
    outcome = orders.sell(Decimal("1"), 100.0, "Stop Loss Triggered")
    assert outcome.filled and outcome.avg_price == 100.25
    assert len(fake.sent("sell")) == 1
    assert orders.outstanding() == [outcome.client_order_id]   # held in memory until applied
