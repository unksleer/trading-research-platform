"""
One process at a time on an order-sending bot's files.

The bot keeps its state and its order journal in memory and writes them back.
A second process on the same files (another copy of the bot, or the hand-close
tool while the bot runs) would have its work written over, and the two would
trade against each other's idea of the position.
"""
import os
import signal
import subprocess
import sys
import time

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

from broker_fakes import FakeAlpaca, order_sending_bot, run, state_of  # noqa: E402
from stock_bot_harness import load_stock_bot  # noqa: E402
from utils import run_lock  # noqa: E402

BUY = {"price": 100.00, "enter": True}


def test_the_lock_is_held_by_one_holder_at_a_time(tmp_path):
    path = str(tmp_path / "sub" / "running.lock")          # the folder is made
    first = run_lock.acquire(path, "BROKERPAPER bot for SPY")
    with pytest.raises(run_lock.Held, match=rf"pid {os.getpid()} \(BROKERPAPER bot for SPY\)"):
        run_lock.acquire(path, "close_position.py")
    run_lock.release(first)
    second = run_lock.acquire(path, "close_position.py")
    run_lock.release(second)
    run_lock.release(second)                                # twice is harmless
    run_lock.release(None)


def test_a_killed_process_does_not_leave_the_bot_locked_out(tmp_path):
    """The lock is the kernel's, not a file that means 'locked' by existing.
    A real second process holds it, is killed without warning, and it is free."""
    path = str(tmp_path / "running.lock")
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; sys.path.insert(0, sys.argv[1]);"
         "from utils import run_lock; h = run_lock.acquire(sys.argv[2], 'the bot');"
         "print('held', flush=True); time.sleep(60)", DIR, path],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(run_lock.Held, match=rf"pid {holder.pid} \(the bot\)"):
            run_lock.acquire(path, "me")
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=10)
        for _ in range(50):
            try:
                run_lock.release(run_lock.acquire(path, "me"))
                break
            except run_lock.Held:
                time.sleep(0.05)
        else:
            pytest.fail("the lock outlived the process that held it")
    finally:
        holder.kill()


def test_a_second_copy_of_an_order_sending_bot_stops_before_it_touches_anything(
        monkeypatch, tmp_path, caplog):
    import logging
    fake = FakeAlpaca()
    bot = order_sending_bot(monkeypatch, tmp_path, fake)
    other = run_lock.acquire(bot.LOCK_PATH, "BROKERPAPER bot for ZZTEST")
    try:
        with caplog.at_level(logging.CRITICAL):
            result = run(bot, monkeypatch, [BUY], ends=SystemExit)
    finally:
        run_lock.release(other)
    assert result.stopped.code == 78            # the code pm2 is told not to restart on
    assert "ALREADY RUNNING" in caplog.text and "BROKERPAPER bot for ZZTEST" in caplog.text
    assert fake.calls == []                     # not one request to the broker
    assert not os.path.exists(bot.STATE_PATH) and not os.path.exists(bot.JOURNAL_PATH)

    run(bot, monkeypatch, [BUY])                # with the lock free it runs
    assert state_of(bot)["position"] == "LONG"


def test_a_running_bot_holds_the_lock_and_gives_it_up_when_it_ends(monkeypatch, tmp_path):
    fake = FakeAlpaca()
    bot = order_sending_bot(monkeypatch, tmp_path, fake)
    seen = {}

    def while_running(request):
        try:
            run_lock.acquire(bot.LOCK_PATH, "close_position.py")
            seen["taken"] = True
        except run_lock.Held as held:
            seen["held"] = str(held)

    fake.before_submit = while_running
    run(bot, monkeypatch, [BUY])
    assert "BROKERPAPER bot for ZZTEST" in seen["held"] and "taken" not in seen
    run_lock.release(run_lock.acquire(bot.LOCK_PATH, "close_position.py"))


def test_a_simulated_bot_takes_no_lock(monkeypatch):
    """It sends nothing and has nothing to lock. Nothing new happens on the
    path the registered bots run."""
    simulated = load_stock_bot(monkeypatch)
    assert not hasattr(simulated, "LOCK_PATH") and simulated._RUN_LOCK is None
