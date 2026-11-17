"""
The owner's pause switch: a file that stops an order-sending bot from opening
new positions, while it goes on managing and closing the one it has.

The pilot terms (DECISIONS.md 2026-11-17) say that when a stage is five
stop-outs behind, the bots stop buying and the stage is reviewed. Counting to
five is not built. This is the switch a person sets when that, or anything
else, calls for it: `touch live/PAUSE_BUYS`, and `rm` to resume. One file
covers every bot of its kind, and it takes effect at the next tick with no
restart.
"""
import logging
import os
import sys
from decimal import Decimal

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import close_position as tool  # noqa: E402
from broker_fakes import (FakeAlpaca, holding, ledger_of, order_sending_bot,  # noqa: E402
                          run, state_of)
from stock_bot_harness import hourly_bars, load_stock_bot  # noqa: E402
from utils import order_bots  # noqa: E402

BUY = {"price": 100.00, "enter": True}
TAKE_PROFIT = {"price": 106.00}
STOP_LOSS = {"price": 94.00}


@pytest.fixture
def fake():
    return FakeAlpaca(price=100.25)


@pytest.fixture
def bot(monkeypatch, tmp_path, fake):
    return order_sending_bot(monkeypatch, tmp_path, fake)


def pause(bot):
    open(bot.PAUSE_PATH, "w").close()


def test_while_the_file_exists_no_buy_is_sent(bot, fake, monkeypatch, caplog):
    pause(bot)
    with caplog.at_level(logging.WARNING):
        run(bot, monkeypatch, [BUY, BUY])
    assert fake.sent() == []
    assert not os.path.exists(bot.JOURNAL_PATH)             # not even written down
    assert "BUY not sent: buying is PAUSED" in caplog.text
    assert "Buying is PAUSED" in caplog.text                # and said once at startup


def test_removing_the_file_resumes_at_the_next_tick_with_no_restart(bot, fake, monkeypatch):
    pause(bot)
    ticks = {"n": 0}
    real_exists = os.path.exists

    def exists(path):
        # The owner removes the file between the first tick and the second.
        if path == bot.PAUSE_PATH and ticks["n"] >= 1 and real_exists(path):
            os.remove(path)
        return real_exists(path)

    real_open_position = bot.open_position

    def counted(state, price):
        real_open_position(state, price)
        ticks["n"] += 1

    monkeypatch.setattr(bot.os.path, "exists", exists)
    monkeypatch.setattr(bot, "open_position", counted)
    run(bot, monkeypatch, [BUY, BUY])
    assert len(fake.sent("buy")) == 1 and state_of(bot)["position"] == "LONG"


@pytest.mark.parametrize("tick, reason", [(TAKE_PROFIT, "Take Profit Triggered"),
                                          (STOP_LOSS, "Stop Loss Triggered")])
def test_a_paused_bot_still_closes_what_it_holds(bot, fake, monkeypatch, tick, reason):
    holding(bot, fake)
    pause(bot)
    fake.price = Decimal(str(tick["price"]))
    run(bot, monkeypatch, [tick])
    assert len(fake.sent("sell")) == 1 and state_of(bot)["position"] == "NONE"
    assert ledger_of(bot)[0]["exit_reason"] == reason
    run(bot, monkeypatch, [BUY])                            # and does not buy back in
    assert fake.sent("buy") == [] and state_of(bot)["position"] == "NONE"


def test_an_owed_exit_is_still_sent_while_paused(bot, fake, monkeypatch):
    holding(bot, fake)
    fake.script("sell", "reject")
    run(bot, monkeypatch, [STOP_LOSS])                      # refused: the exit is owed
    pause(bot)
    run(bot, monkeypatch, [{"price": 100.00}])
    assert state_of(bot)["position"] == "NONE" and len(fake.sent("sell")) == 2


def test_the_hand_close_tool_works_while_paused(bot, fake, monkeypatch):
    monkeypatch.setattr(bot, "is_market_open", lambda: True)
    monkeypatch.setattr(bot, "fetch_bars", lambda ticker, n: hourly_bars())
    holding(bot, fake)
    pause(bot)
    assert tool.run(bot, do_send=True, out=lambda line: None, pm2=lambda name: None) == 0
    assert state_of(bot)["position"] == "NONE"


def test_each_kind_has_its_own_switch_and_a_simulated_bot_has_none(monkeypatch):
    rehearsal = load_stock_bot(monkeypatch, name="rehearsal", broker_paper=True)
    live = load_stock_bot(monkeypatch, name="live", live=True)
    simulated = load_stock_bot(monkeypatch, name="simulated")
    assert rehearsal.PAUSE_PATH == os.path.join(DIR, "broker_paper", "PAUSE_BUYS")
    assert live.PAUSE_PATH == os.path.join(DIR, "live", "PAUSE_BUYS")
    assert not hasattr(simulated, "PAUSE_PATH")
    # The dashboard looks for the same file name.
    assert os.path.basename(live.PAUSE_PATH) == order_bots.PAUSE_FILE


def test_the_dashboard_says_when_buying_is_paused(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "live"))
    data = order_bots.collect(root, [])
    assert not data["totals"]["live"]["buying_paused"]
    open(os.path.join(root, "live", "PAUSE_BUYS"), "w").close()
    data = order_bots.collect(root, [])
    assert data["totals"]["live"]["buying_paused"]
    assert not data["totals"]["rehearsal"]["buying_paused"]
    page = open(os.path.join(DIR, "dashboard", "index.html")).read()
    assert "t.buying_paused" in page and "BUYING PAUSED" in page
