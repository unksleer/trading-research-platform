"""
Before its first tick, an order-sending bot squares itself with the broker,
and stops if it cannot.

The two ways this goes wrong with real orders, both from a state file that is
not the truth: a position at the broker the bot does not know about gets
opened a second time, and a position the bot believes in that is not there
gets sold, which is a short sale.

Also here: the journal picking up after a crash, the entry script's own
checks, and the venue adapter's reading of what Alpaca sends back.
"""
import json
import logging
import os
import sys
import types
from decimal import Decimal

import pytest
import requests

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from alpaca.trading.enums import OrderSide, OrderStatus  # noqa: E402

from broker_fakes import (FakeAlpaca, api_error, holding, journal_of, ledger_of,  # noqa: E402
                          order_sending_bot, run, state_of)
from utils.venue import AlpacaVenue  # noqa: E402

MISMATCH = 78
QUIET = {"price": 100.00}
BUY = {"price": 100.00, "enter": True}
TAKE_PROFIT = {"price": 106.00}


@pytest.fixture
def fake():
    return FakeAlpaca(price=100.25)


@pytest.fixture
def bot(monkeypatch, tmp_path, fake):
    return order_sending_bot(monkeypatch, tmp_path, fake)


def stops(bot, monkeypatch, caplog, ticks=(QUIET,)):
    with caplog.at_level(logging.CRITICAL):
        result = run(bot, monkeypatch, list(ticks), ends=SystemExit)
    assert result.stopped.code == MISMATCH
    assert result.naps == []                    # never reached a tick
    assert "BROKER MISMATCH" in caplog.text
    return caplog.text


# ── state against the broker's position ─────────────────────────────────────

def test_flat_on_both_sides_starts(bot, fake, monkeypatch, caplog):
    with caplog.at_level(logging.INFO):
        result = run(bot, monkeypatch, [QUIET])
    assert result.naps == [60]
    assert "Reconciled with the broker at https://paper-api.alpaca.markets" in caplog.text
    assert "ORDERS ARE SENT in this mode (BROKERPAPER)" in caplog.text


def test_the_same_position_on_both_sides_starts(bot, fake, monkeypatch):
    holding(bot, fake)
    assert run(bot, monkeypatch, [QUIET]).naps == [60]
    assert state_of(bot)["position"] == "LONG"


def test_a_position_at_the_broker_the_bot_does_not_know_about_stops_it(bot, fake, monkeypatch, caplog):
    fake.held["ZZTEST"] = Decimal("0.5")
    text = stops(bot, monkeypatch, caplog, [BUY])
    assert "state file says 0.0 ZZTEST (position NONE), the broker holds 0.5" in text
    assert fake.sent() == []


def test_a_position_the_bot_believes_in_that_is_not_there_stops_it(bot, fake, monkeypatch, caplog):
    holding(bot, fake)
    fake.held["ZZTEST"] = Decimal("0")
    text = stops(bot, monkeypatch, caplog, [TAKE_PROFIT])
    assert "the broker holds 0" in text
    assert fake.sent() == []                    # above all, no sell of nothing
    assert state_of(bot)["position"] == "LONG" and ledger_of(bot) == []


def test_a_different_share_count_stops_it(bot, fake, monkeypatch, caplog):
    holding(bot, fake, shares="0.997506234")
    fake.held["ZZTEST"] = Decimal("0.5")
    stops(bot, monkeypatch, caplog)


def test_another_tickers_position_is_none_of_its_business(bot, fake, monkeypatch):
    """One paper account can carry a rehearsal bot per ticker."""
    fake.held["SPY"] = Decimal("3")
    assert run(bot, monkeypatch, [QUIET]).naps == [60]


def test_an_open_order_nobody_recorded_stops_it(bot, fake, monkeypatch, caplog):
    fake.foreign.append(types.SimpleNamespace(
        id="someone-else", symbol="ZZTEST", side=OrderSide.BUY,
        status=OrderStatus.NEW, filled_qty="0", filled_avg_price=None))
    text = stops(bot, monkeypatch, caplog)
    assert "1 open ZZTEST order(s) this bot has no record of" in text


def test_a_broker_that_cannot_be_reached_at_startup_stops_it(bot, fake, monkeypatch, caplog):
    """At startup there is no earlier check to lean on: unverified is not
    started."""
    fake.down = True
    text = stops(bot, monkeypatch, caplog)
    assert "could not be read, so the state file cannot be checked" in text


def test_the_wrong_endpoint_stops_it_before_anything_else(bot, fake, monkeypatch, caplog):
    fake._base_url = "https://api.alpaca.markets"           # live
    text = stops(bot, monkeypatch, caplog, [BUY])
    assert "mode is BROKERPAPER but orders would go to 'https://api.alpaca.markets'" in text
    assert fake.calls == []                                 # not one request


def test_a_live_bot_on_the_paper_endpoint_stops_too(monkeypatch, tmp_path, fake, caplog):
    live = order_sending_bot(monkeypatch, tmp_path, fake, live=True)
    assert live.MODE == "LIVE" and not live.BROKER_PAPER
    fake._base_url = "https://paper-api.alpaca.markets"
    stops(live, monkeypatch, caplog)


def test_live_runs_the_same_order_path(monkeypatch, tmp_path, fake):
    """The path being rehearsed on paper is the one live will use. Against the
    fake; nothing in this suite can reach a real endpoint."""
    live = order_sending_bot(monkeypatch, tmp_path, fake, live=True)
    run(live, monkeypatch, [BUY])
    assert state_of(live)["position"] == "LONG" and state_of(live)["entry_price"] == 100.25
    fake.price = Decimal("106.10")
    run(live, monkeypatch, [TAKE_PROFIT])
    (row,) = ledger_of(live)
    assert row["mode"] == "LIVE" and float(row["exit_price"]) == 106.10


def test_an_unreadable_state_file_is_not_read_as_flat(bot, fake, monkeypatch, caplog):
    with open(bot.STATE_PATH, "w") as handle:
        handle.write("{ not json")
    text = stops(bot, monkeypatch, caplog)
    assert "both unreadable" in text


def test_an_unreadable_journal_stops_it(bot, fake, monkeypatch, caplog):
    with open(bot.JOURNAL_PATH, "w") as handle:
        handle.write("{ not json")
    text = stops(bot, monkeypatch, caplog)
    assert "cannot be read" in text


# ── picking up after a crash ────────────────────────────────────────────────

class Crash(BaseException):
    """The process dying. Not an Exception, so nothing in the bot catches it."""


def crash_in(owner, monkeypatch, name, on_call=1):
    """Make the process die on the nth call of owner.name. Returns a function
    that puts the real one back, for the restart."""
    real = getattr(owner, name)
    calls = {"n": 0}

    def die(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= on_call:
            raise Crash()
        return real(*args, **kwargs)
    monkeypatch.setattr(owner, name, die)
    return lambda: monkeypatch.setattr(owner, name, real)


def test_a_buy_that_filled_just_before_a_crash_is_in_state_after_the_restart(bot, fake, monkeypatch):
    """The window the journal is for: filled at the broker, process dead
    before the state file was written."""
    repair = crash_in(bot, monkeypatch, "apply_fill")
    run(bot, monkeypatch, [BUY], ends=Crash)
    assert fake.held["ZZTEST"] == Decimal("0.997506234")    # the broker has it
    assert not os.path.exists(bot.STATE_PATH)               # the bot does not
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "FILLED" and entry["resolved"] and not entry["applied"]

    repair()
    run(bot, monkeypatch, [QUIET])
    state = state_of(bot)
    assert state["position"] == "LONG" and state["entry_price"] == 100.25
    assert state["shares"] == pytest.approx(0.997506234)
    assert state["entry_signal_price"] == 100.0
    assert len(fake.sent("buy")) == 1                       # not bought again
    assert all(e["applied"] for e in journal_of(bot).values())


def test_a_sell_that_filled_just_before_a_crash_closes_the_position_after_the_restart(bot, fake, monkeypatch):
    holding(bot, fake, entry=100.25, signal=100.0)
    fake.price = Decimal("106.20")
    repair = crash_in(bot, monkeypatch, "apply_fill")
    run(bot, monkeypatch, [TAKE_PROFIT], ends=Crash)
    assert fake.held["ZZTEST"] == 0 and state_of(bot)["position"] == "LONG"

    repair()
    run(bot, monkeypatch, [QUIET])
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert float(row["exit_price"]) == 106.20 and float(row["exit_signal_price"]) == 106.0
    assert row["exit_reason"] == "Take Profit Triggered"
    assert len(fake.sent("sell")) == 1                      # not sold again


def test_a_trade_closed_in_state_but_not_yet_in_the_ledger_is_written_once(bot, fake, monkeypatch):
    """A crash between the state write and the ledger write must not lose the
    row, and a second restart must not write it twice."""
    holding(bot, fake)
    fake.price = Decimal("106.20")
    # The first call is the startup check, with nothing to write.
    repair = crash_in(bot, monkeypatch, "_write_unwritten_trade", on_call=2)
    run(bot, monkeypatch, [TAKE_PROFIT], ends=Crash)
    assert state_of(bot)["position"] == "NONE" and ledger_of(bot) == []
    assert state_of(bot)["unwritten_trade"]["exit_price"] == 106.20

    repair()
    run(bot, monkeypatch, [QUIET])
    run(bot, monkeypatch, [QUIET])
    assert len(ledger_of(bot)) == 1
    assert "unwritten_trade" not in state_of(bot)


def test_an_order_left_working_by_a_crash_is_cancelled_at_startup(bot, fake, monkeypatch):
    """Died while the order was still working. It must not be left at the
    broker to fill later with nobody watching."""
    fake.script("buy", "hang")
    repair = crash_in(fake, monkeypatch, "cancel_order_by_id")
    run(bot, monkeypatch, [BUY], ends=Crash)
    (order,) = fake.orders.values()
    assert order.status == OrderStatus.ACCEPTED             # still working
    (entry,) = journal_of(bot).values()
    assert not entry["resolved"]

    repair()
    run(bot, monkeypatch, [QUIET])
    assert order.status == OrderStatus.CANCELED and fake.get_orders() == []
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "CANCELED" and entry["resolved"] and entry["applied"]
    assert not os.path.exists(bot.STATE_PATH) or state_of(bot)["position"] == "NONE"


def test_a_lagging_open_order_list_is_not_mistaken_for_someone_elses_order(bot, fake, monkeypatch):
    """
    Found with real orders on the paper API, 2026-11-16: an order that
    reported CANCELED when asked about directly was still in the open-orders
    list a moment later. The bot's own finished order must not stop it.
    """
    fake.script("buy", "hang")
    repair = crash_in(fake, monkeypatch, "cancel_order_by_id")
    run(bot, monkeypatch, [BUY], ends=Crash)
    repair()
    fake.open_list_lag = 50                                 # the list never catches up
    assert run(bot, monkeypatch, [QUIET]).naps == [60]      # started, did not stop
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "CANCELED"


def test_a_disagreement_is_read_again_before_it_is_believed(bot, fake, monkeypatch, caplog):
    """A position list that is a moment behind a fill clears on a second look;
    a real mismatch does not (the tests above)."""
    holding(bot, fake)
    real = fake.get_all_positions
    looks = {"n": 0}

    def behind_at_first():
        looks["n"] += 1
        return [] if looks["n"] == 1 else real()
    monkeypatch.setattr(fake, "get_all_positions", behind_at_first)
    with caplog.at_level(logging.WARNING):
        assert run(bot, monkeypatch, [QUIET]).naps == [60]
    assert "Reading again" in caplog.text and looks["n"] == 2


def test_an_intent_that_never_reached_the_broker_is_closed_out_at_startup(bot, fake, monkeypatch):
    """Died between writing the intent and sending the order."""
    with open(bot.JOURNAL_PATH, "w") as handle:
        json.dump({"zztest-buy-0000": {
            "ticker": "ZZTEST", "side": "BUY", "signal_price": 100.0, "notional": 100.0,
            "status": "PENDING", "resolved": False, "applied": False,
            "created_at": "2026-11-16T15:00:00+00:00"}}, handle)
    run(bot, monkeypatch, [QUIET])
    (entry,) = journal_of(bot).values()
    assert entry["status"] == "NOT_PLACED" and entry["resolved"] and entry["applied"]
    assert fake.sent() == []


def test_an_order_with_no_final_answer_at_startup_stops_the_bot(bot, fake, monkeypatch, caplog):
    fake.script("buy", "stuck")
    run(bot, monkeypatch, [BUY])
    text = stops(bot, monkeypatch, caplog)
    assert "still has no final answer from the broker" in text


# ── the entry script ────────────────────────────────────────────────────────

def test_the_entry_script_wants_a_ticker_and_an_amount_spelled_out():
    import broker_paper_bot
    assert broker_paper_bot.problems({"STOCK_TICKER": "SPY", "TRADE_AMOUNT_USD": "100"}) == []
    assert len(broker_paper_bot.problems({})) == 2
    assert len(broker_paper_bot.problems({"STOCK_TICKER": "SPY"})) == 1
    assert len(broker_paper_bot.problems({"STOCK_TICKER": "SPY", "TRADE_AMOUNT_USD": "0"})) == 1


def test_the_entry_script_never_goes_live():
    import broker_paper_bot
    (problem,) = broker_paper_bot.problems(
        {"STOCK_TICKER": "SPY", "TRADE_AMOUNT_USD": "100", "ALPACA_PAPER": "False"})
    assert "only ever talks to the paper account" in problem


def test_the_entry_script_checks_its_pm2_name_against_its_ticker():
    """What utils/identity.py does for <ticker>-bot, for <ticker>-brokerpaper."""
    import broker_paper_bot
    base = {"STOCK_TICKER": "SPY", "TRADE_AMOUNT_USD": "100"}
    assert broker_paper_bot.problems({**base, "name": "spy-brokerpaper"}) == []
    assert broker_paper_bot.problems(base) == []            # run by hand: no name
    (problem,) = broker_paper_bot.problems({**base, "name": "wmt-brokerpaper"})
    assert "not named for SPY" in problem
    (problem,) = broker_paper_bot.problems({**base, "name": "spy-bot"})
    assert "expected 'spy-brokerpaper'" in problem


def test_the_entry_script_refuses_to_start_misnamed_and_touches_nothing(tmp_path):
    import subprocess
    env = {"PATH": os.environ["PATH"], "STOCK_TICKER": "SPY",
           "TRADE_AMOUNT_USD": "100", "name": "wmt-brokerpaper"}
    result = subprocess.run([sys.executable, os.path.join(DIR, "broker_paper_bot.py")],
                            env=env, capture_output=True, text=True, timeout=60, cwd=DIR)
    assert result.returncode == 1
    assert "not named for SPY" in result.stderr
    assert not os.path.exists(os.path.join(DIR, "broker_paper", "state_stock_spy.json"))


def test_the_fleets_tools_do_not_see_a_rehearsal_bot():
    """
    The dashboard, the registry and restart_bots.py find bots by the script a
    process runs. A rehearsal bot runs broker_paper_bot.py, so it is not a
    second SPY bot to any of them and `restart_bots.py --stocks` leaves it be.
    """
    from utils import process_mode, registry
    import restart_bots
    rehearsal = {"name": "spy-brokerpaper", "pid": 1, "pm2_env": {
        "pm_exec_path": os.path.join(DIR, "broker_paper_bot.py"),
        "STOCK_TICKER": "SPY", "status": "online"}}
    assert process_mode.bots_from_pm2([rehearsal], read_env=lambda pid: {}) == []
    original = registry._pm2_processes
    registry._pm2_processes = lambda: [rehearsal]
    restart_bots_original = restart_bots.pm2_processes
    restart_bots.pm2_processes = lambda: [rehearsal]
    try:
        assert registry.bots() == []
        assert restart_bots.running_identity() == {}
    finally:
        registry._pm2_processes = original
        restart_bots.pm2_processes = restart_bots_original


# ── what Alpaca sends back, read correctly ──────────────────────────────────

def venue_over(fake):
    venue = AlpacaVenue("k", "s", paper=True)
    venue._client = fake
    return venue


def test_an_order_status_is_read_as_its_value_not_its_enum_name():
    """str(OrderStatus.FILLED) is "OrderStatus.FILLED". Read that way, no
    order was ever FILLED and the old code could not have told."""
    assert str(OrderStatus.FILLED) != "filled"
    order = types.SimpleNamespace(id="abc", status=OrderStatus.FILLED,
                                  filled_qty="0.5", filled_avg_price="200.10")
    parsed = AlpacaVenue().parse_response(order)
    assert parsed["status"] == "FILLED"
    assert parsed["filled_size"] == Decimal("0.5") and parsed["average_price"] == Decimal("200.10")
    assert AlpacaVenue().parse_response(
        types.SimpleNamespace(id="x", status="partially_filled"))["status"] == "PARTIALLY_FILLED"


def test_no_such_order_and_could_not_ask_are_told_apart(fake):
    venue = venue_over(fake)
    assert venue.find_order("never-sent") is None           # the venue said so: 404
    fake.down = True
    with pytest.raises(requests.exceptions.ConnectionError):
        venue.find_order("never-sent")                      # nobody said anything
    assert venue.get_order_by_client_id("never-sent") is None   # the old lookup cannot tell


def test_a_refusal_is_told_apart_from_silence():
    assert AlpacaVenue.answered_no(api_error(403, "insufficient buying power"))
    assert AlpacaVenue.answered_no(api_error(422, "bad request"))
    assert not AlpacaVenue.answered_no(api_error(429, "slow down"))
    assert not AlpacaVenue.answered_no(api_error(504, "gateway timeout"))
    assert not AlpacaVenue.answered_no(requests.exceptions.ReadTimeout("no reply"))


def test_position_is_zero_when_flat_and_signed_when_short(fake):
    venue = venue_over(fake)
    assert venue.position_qty("SPY") == 0
    fake.held["SPY"] = Decimal("0.133689839")
    assert venue.position_qty("spy") == Decimal("0.133689839")
    fake.held["SPY"] = Decimal("-2")
    assert venue.position_qty("SPY") == Decimal("-2")
    fake.down = True
    with pytest.raises(requests.exceptions.ConnectionError):
        venue.position_qty("SPY")


def test_a_sell_asks_for_exactly_the_shares_held(fake):
    """Rounded to six places, 0.1336898 became 0.133690: more than was held."""
    fake.held["SPY"] = Decimal("0.133689839")
    venue = venue_over(fake)
    venue.submit_sell("SPY", Decimal("0.133689839"), "cid-1")
    assert fake.orders["cid-1"].qty == 0.133689839
    assert Decimal(str(fake.orders["cid-1"].qty)) <= fake.held["SPY"]
