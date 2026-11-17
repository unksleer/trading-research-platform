"""
Closing an order-sending bot's position by hand.

close_position.py sells through the bot's own order path, so the journal, the
state file and the ledger end up as they would had the bot sold. These tests
run it against the fake broker (tests/broker_fakes.py), with the real
stock_bot code and the real AlpacaVenue underneath.

What it must never do: sell while the bot is running, or sell on a guess when
the broker and the state file disagree.
"""
import logging
import os
import sys
import types
from decimal import Decimal

import pandas as pd
import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import close_position as tool  # noqa: E402
from alpaca.trading.enums import OrderSide, OrderStatus  # noqa: E402
from broker_fakes import (FakeAlpaca, holding, journal_of, ledger_of,  # noqa: E402
                          order_sending_bot, run, state_of)
from stock_bot_harness import hourly_bars  # noqa: E402
from utils import execution_mode, run_lock  # noqa: E402

SHARES = "0.997506234"
QUIET = {"price": 100.00}
BUY = {"price": 100.00, "enter": True}
LAST_CLOSE = float(hourly_bars()["close"].iloc[-1])


@pytest.fixture
def fake():
    return FakeAlpaca(price=101.50)


@pytest.fixture
def bot(monkeypatch, tmp_path, fake):
    """A stopped rehearsal bot holding a position the broker also holds."""
    bot = order_sending_bot(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(bot, "is_market_open", lambda: True)
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: hourly_bars())
    holding(bot, fake, shares=SHARES, entry=100.25, signal=100.0)
    return bot


def close(bot, send=True, pm2=lambda name: "stopped"):
    lines = []
    code = tool.run(bot, do_send=send, out=lines.append, pm2=pm2)
    return code, "\n".join(lines)


def files(bot):
    out = {}
    for path in (bot.STATE_PATH, bot.JOURNAL_PATH, bot.TRADES_PATH):
        out[path] = open(path, "rb").read() if os.path.exists(path) else None
    return out


def nothing_happened(bot, fake, before):
    assert fake.sent() == [] and files(bot) == before
    assert not any(call[0] == "cancel" for call in fake.calls)


# ── the dry run, which is the default ───────────────────────────────────────

def test_without_send_it_says_what_it_would_do_and_does_nothing(bot, fake):
    before = files(bot)
    code, said = close(bot, send=False)
    assert code == 0
    assert f"state file         LONG {SHARES} ZZTEST" in said
    assert f"broker holds       {SHARES} ZZTEST" in said
    assert "Would then send: market SELL of the whole position" in said
    assert "DRY RUN. Nothing was sent and no file was changed." in said
    assert "PAPER account, no money" in said
    nothing_happened(bot, fake, before)


def test_the_command_line_is_a_dry_run_unless_it_says_send(bot, fake, monkeypatch, capsys):
    before = files(bot)
    monkeypatch.setattr(tool, "load_bot", lambda ticker, live: bot)
    monkeypatch.setattr(tool, "pm2_status", lambda name: None)
    assert tool.main(["zztest"]) == 0
    assert tool.main(["zztest", "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    nothing_happened(bot, fake, before)
    with pytest.raises(SystemExit):
        tool.main(["zztest", "--send", "--dry-run"])


# ── a clean close ───────────────────────────────────────────────────────────

def test_send_closes_the_position_through_the_journalled_path(bot, fake):
    seen = {}

    def as_it_goes_out(request):
        (entry,) = journal_of(bot).values()                 # on disk before it is sent
        seen.update(entry=dict(entry), cid=request.client_order_id,
                    owed=state_of(bot)["exit_pending"])

    fake.before_submit = as_it_goes_out
    code, said = close(bot)
    assert code == 0 and "CLOSED." in said and "The broker now holds 0 ZZTEST" in said

    assert seen["entry"]["side"] == "SELL" and seen["entry"]["status"] == "PENDING"
    assert seen["entry"]["reason"] == "Closed by hand"
    assert seen["owed"]["reason"] == "Closed by hand" and seen["owed"]["attempts"] == 1
    (cid,) = journal_of(bot)
    assert cid == seen["cid"]
    entry = journal_of(bot)[cid]
    assert entry["status"] == "FILLED" and entry["resolved"] and entry["applied"]

    state = state_of(bot)
    assert state["position"] == "NONE" and state["shares"] == 0.0
    assert "exit_pending" not in state and "unwritten_trade" not in state

    (row,) = ledger_of(bot)
    assert row["exit_reason"] == "Closed by hand" and row["mode"] == "BROKERPAPER"
    assert float(row["exit_price"]) == 101.50               # the fill
    assert float(row["exit_signal_price"]) == LAST_CLOSE    # the newest hourly close
    assert float(row["entry_price"]) == 100.25
    assert float(row["pnl_usd"]) == pytest.approx((101.50 - 100.25) * float(SHARES), abs=1e-4)
    assert row["exit_attempts"] == "1" and row["exit_order_id"] == entry["order_id"]
    assert fake.held["ZZTEST"] == 0
    assert len(bot.notifications) == 1                      # the usual trade email


def test_the_bot_carries_on_cleanly_afterwards(bot, fake, monkeypatch):
    close(bot)
    run(bot, monkeypatch, [QUIET])                          # restart: reconciles, flat
    assert state_of(bot)["position"] == "NONE" and len(ledger_of(bot)) == 1
    fake.price = Decimal("100.25")
    run(bot, monkeypatch, [BUY])                            # and trades again
    assert state_of(bot)["position"] == "LONG"
    assert len(fake.sent("sell")) == 1 and len(fake.sent("buy")) == 1


def test_a_loss_closed_by_hand_starts_the_cooldown_like_any_other(bot, fake):
    fake.price = Decimal("95.00")
    close(bot)
    state = state_of(bot)
    assert state["last_exit_pnl"] < 0 and state["last_exit_time"]


def test_it_works_the_same_for_a_live_bot(monkeypatch, tmp_path, fake):
    """Against the fake. Nothing in this suite can reach a real endpoint."""
    live = order_sending_bot(monkeypatch, tmp_path, fake, live=True)
    monkeypatch.setattr(live, "is_market_open", lambda: True)
    monkeypatch.setattr(live, "fetch_bars", lambda ticker, n: hourly_bars())
    holding(live, fake, shares=SHARES)
    names = []
    code, said = close(live, send=False, pm2=lambda name: names.append(name))
    assert code == 0 and "LIVE account, REAL MONEY" in said and names == ["zztest-live"]
    code, said = close(live)
    assert code == 0 and ledger_of(live)[0]["mode"] == "LIVE"


def test_with_no_price_to_measure_against_it_still_sells(bot, fake, monkeypatch):
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: pd.DataFrame())
    code, said = close(bot)
    assert code == 0 and "no signal price to be measured against" in said
    (row,) = ledger_of(bot)
    assert float(row["exit_signal_price"]) == 0.0 and row["exit_fill_minus_signal_pct"] == ""


def test_flat_and_flat_is_nothing_to_close(monkeypatch, tmp_path, fake):
    flat = order_sending_bot(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(flat, "is_market_open", lambda: False)   # closed does not matter
    code, said = close(flat)
    assert code == 0 and "Nothing to close" in said and fake.sent() == []


# ── refusals: nothing is sent and nothing is changed ────────────────────────

def test_it_refuses_while_the_bot_holds_its_lock(bot, fake):
    before = files(bot)
    running = run_lock.acquire(bot.LOCK_PATH, "BROKERPAPER bot for ZZTEST")
    try:
        for send in (False, True):
            code, said = close(bot, send=send)
            assert code == 2
            assert "REFUSED: The bot is running" in said
            assert "pm2 stop zztest-brokerpaper" in said and "Nothing was sent." in said
    finally:
        run_lock.release(running)
    nothing_happened(bot, fake, before)


def test_it_refuses_when_pm2_says_the_bot_is_online(bot, fake):
    """A bot started before the lock existed does not hold it. pm2 knows."""
    before = files(bot)
    code, said = close(bot, pm2=lambda name: "online")
    assert code == 2 and "pm2 shows zztest-brokerpaper online" in said
    nothing_happened(bot, fake, before)


def test_pm2_not_answering_is_said_and_the_lock_decides(bot, fake):
    code, said = close(bot, send=False, pm2=lambda name: "unknown")
    assert code == 0 and "pm2 could not be asked" in said


@pytest.mark.parametrize("broker_has", ["0", "0.5", "1.5"])
def test_it_refuses_when_the_broker_does_not_hold_what_the_state_file_says(
        bot, fake, caplog, broker_has):
    fake.held["ZZTEST"] = Decimal(broker_has)
    before = files(bot)
    with caplog.at_level(logging.INFO):
        for send in (False, True):
            code, said = close(bot, send=send)
            assert code == 2
            assert f"The state file says {SHARES} ZZTEST" in said
            assert f"the broker holds {broker_has}" in said
            assert "Find out which is right before anything is sold" in said
    nothing_happened(bot, fake, before)
    # It does not write a stop notice into the bot's log: the bot did not stop.
    assert "BROKER MISMATCH" not in caplog.text


def test_it_refuses_a_flat_state_file_over_a_position_at_the_broker(
        monkeypatch, tmp_path, fake):
    flat = order_sending_bot(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(flat, "is_market_open", lambda: True)
    fake.held["ZZTEST"] = Decimal("2")
    code, said = close(flat)
    assert code == 2 and "the broker holds 2" in said and fake.sent() == []


def test_it_refuses_when_someone_elses_order_is_working(bot, fake):
    fake.foreign.append(types.SimpleNamespace(
        id="x", client_order_id="by-hand-on-the-website", symbol="ZZTEST",
        side=OrderSide.SELL, status=OrderStatus.ACCEPTED, filled_qty="0",
        filled_avg_price=None))
    before = files(bot)
    code, said = close(bot)
    assert code == 2 and "1 open ZZTEST order(s) that are not this bot's" in said
    nothing_happened(bot, fake, before)


def test_it_refuses_when_the_market_is_closed(bot, fake, monkeypatch):
    monkeypatch.setattr(bot, "is_market_open", lambda: False)
    before = files(bot)
    code, said = close(bot)
    assert code == 2 and "The market is closed" in said
    nothing_happened(bot, fake, before)


def test_it_refuses_when_the_broker_cannot_be_asked(bot, fake):
    fake.down = True
    before = files(bot)
    code, said = close(bot)
    assert code == 2 and "The broker could not be asked" in said
    nothing_happened(bot, fake, before)


def test_it_refuses_an_unreadable_state_file_or_journal(bot, fake):
    with open(bot.JOURNAL_PATH, "w") as handle:
        handle.write("{ not json")
    code, said = close(bot)
    assert code == 2 and "order journal" in said and "cannot be read" in said
    os.remove(bot.JOURNAL_PATH)
    with open(bot.STATE_PATH, "w") as handle:
        handle.write("{ not json")
    code, said = close(bot)
    assert code == 2 and "state file" in said and "cannot be read" in said
    assert fake.sent() == []


def test_it_refuses_the_wrong_endpoint(bot, fake):
    fake._base_url = "https://api.alpaca.markets"
    code, said = close(bot)
    assert code == 2 and "Mode is BROKERPAPER but orders would go to" in said
    assert fake.calls == []


def test_it_refuses_without_keys(bot, fake):
    bot.API_KEY = ""
    code, said = close(bot)
    assert code == 2 and "API keys for this mode are not set" in said and fake.calls == []


# ── a sell that does not go through ─────────────────────────────────────────

@pytest.mark.parametrize("how, status", [("reject", "NOT_PLACED"), ("hang", "CANCELED")])
def test_a_sell_that_does_not_fill_leaves_the_position_open_and_the_exit_owed(
        bot, fake, monkeypatch, how, status):
    fake.script("sell", how)
    code, said = close(bot)
    assert code == 3 and f"NOT FILLED ({status}" in said
    assert "The exit is owed in the state file" in said
    state = state_of(bot)
    assert state["position"] == "LONG" and state["shares"] == float(SHARES)
    assert state["exit_pending"]["reason"] == "Closed by hand"
    assert ledger_of(bot) == [] and fake.held["ZZTEST"] == Decimal(SHARES)

    # Started again, the bot sells on its first tick, signal or no signal.
    run(bot, monkeypatch, [QUIET])
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert row["exit_reason"] == "Closed by hand" and row["exit_attempts"] == "2"


def test_running_it_again_finishes_a_part_sale_as_one_ledger_row(bot, fake):
    fake.script("sell", "partial")
    code, said = close(bot)
    assert code == 3 and "PARTLY SOLD" in said
    assert state_of(bot)["position"] == "LONG" and ledger_of(bot) == []
    assert state_of(bot)["shares"] == pytest.approx(float(SHARES) / 2, abs=1e-8)

    code, said = close(bot)
    assert code == 0 and "CLOSED." in said
    (row,) = ledger_of(bot)
    assert float(row["shares"]) == pytest.approx(float(SHARES), abs=1e-8)
    assert row["exit_attempts"] == "2" and fake.held["ZZTEST"] == 0


def test_an_order_with_no_final_answer_is_reported_as_exactly_that(bot, fake):
    fake.script("sell", "stuck")
    code, said = close(bot)
    assert code == 3 and "has not yet said what became of the order" in said
    assert state_of(bot)["position"] == "LONG"
    (entry,) = journal_of(bot).values()
    assert not entry["resolved"]                            # the next run finds it


def test_an_exit_the_bot_already_owed_is_recorded_as_closed_by_hand(bot, fake, monkeypatch):
    fake.script("sell", "reject")
    run(bot, monkeypatch, [{"price": 96.00}])               # the bot's stop loss, refused
    assert state_of(bot)["exit_pending"]["reason"] == "Stop Loss Triggered"
    code, said = close(bot, send=False)
    assert "an exit is already owed: Stop Loss Triggered (1 attempt(s))" in said
    code, said = close(bot)
    assert code == 0
    (row,) = ledger_of(bot)
    assert row["exit_reason"] == "Closed by hand (owed since: Stop Loss Triggered)"
    assert row["exit_attempts"] == "2"
    assert float(row["exit_signal_price"]) == 96.00         # when the exit was first decided


def test_an_unanswered_order_of_the_bots_is_settled_first(bot, fake):
    """
    The bot died after its sell went in and before the answer came back. The
    state file says LONG and the broker is flat, and that is not a mismatch:
    the journal knows why. The tool finishes that order the way the bot would
    at startup, and then finds nothing left to sell.
    """
    from utils.broker_orders import Outcome
    orders = bot.broker()
    orders._wait = lambda cid, timeout: Outcome(cid, orders.entries[cid], final=False)
    fake.script("sell", "silent")                           # goes in; the reply is lost
    left = orders.sell(Decimal(SHARES), 106.0, "Take Profit Triggered")
    fake.get_order_by_client_id(left.client_order_id)       # and it fills at the broker
    bot._BROKER = None                                      # the process is gone
    assert state_of(bot)["position"] == "LONG" and fake.held["ZZTEST"] == 0

    before = files(bot)
    code, said = close(bot, send=False)
    assert code == 0 and "Would first settle 1 unfinished order(s) from the bot" in said
    assert "REFUSED" not in said and files(bot) == before

    code, said = close(bot)
    assert code == 0 and "finishing the bot's earlier orders closed the position" in said
    assert state_of(bot)["position"] == "NONE"
    (row,) = ledger_of(bot)
    assert row["exit_reason"] == "Take Profit Triggered"    # the bot's exit, not a hand close
    assert len(fake.sent("sell")) == 1                      # no second sell


# ── the pieces around it ────────────────────────────────────────────────────

def test_it_loads_stock_bot_in_the_mode_it_was_asked_for(monkeypatch):
    """No real stock_bot is imported here: that would open a real log file."""
    stub = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "stock_bot", stub)
    monkeypatch.setattr(execution_mode, "REQUESTED", None)
    for key in ("STOCK_TICKER", "ALPACA_PAPER", "TRADE_AMOUNT_USD"):
        monkeypatch.setenv(key, "x")
    assert tool.load_bot("SPY", live=False) is stub
    assert execution_mode.REQUESTED == execution_mode.BROKER_PAPER
    assert (os.environ["STOCK_TICKER"], os.environ["ALPACA_PAPER"]) == ("SPY", "True")
    tool.load_bot("XLP", live=True)
    assert execution_mode.REQUESTED == execution_mode.LIVE
    assert (os.environ["STOCK_TICKER"], os.environ["ALPACA_PAPER"]) == ("XLP", "False")


def test_pm2_is_asked_by_name(monkeypatch):
    import json
    listing = [{"name": "spy-brokerpaper", "pm2_env": {"status": "online"}},
               {"name": "xlp-live", "pm2_env": {"status": "stopped"}}]
    monkeypatch.setattr(tool.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=json.dumps(listing)))
    assert tool.pm2_status("spy-brokerpaper") == "online"
    assert tool.pm2_status("xlp-live") == "stopped"
    assert tool.pm2_status("wmt-brokerpaper") is None

    def no_pm2(*a, **k):
        raise FileNotFoundError("pm2")
    monkeypatch.setattr(tool.subprocess, "run", no_pm2)
    assert tool.pm2_status("spy-brokerpaper") == "unknown"
