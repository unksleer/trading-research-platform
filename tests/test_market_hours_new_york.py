"""
Market hours are New York hours, in winter as well as summer.

stock_bot.py worked out Eastern Time as UTC minus four hours, all year. That
is right from mid March to early November and an hour out for the rest. Seen
in logs/stock_spy.log on 2026-11-24, three weeks after the clocks went back:

    08:29:34  Market closed. Next open in ~1m. Sleeping 1m.
    08:30:34  Market closed. Next open in ~1439m. Sleeping 30m.

The bell is at 09:30. The open-or-closed answer comes from Alpaca's clock, so
no bot traded on the wrong hour; what was wrong was the log line, the length
of the sleep, and the check used when Alpaca's clock cannot be reached, which
in winter would have called 08:30 to 15:00 the trading day.

Every test here names its moment in UTC and lets the bot convert it, so the
conversion is what is under test.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.join(DIR, "tests"))

from stock_bot_harness import bot  # noqa: E402,F401  (fixture)


def at(bot, monkeypatch, utc):
    """Freeze the bot's clock at a UTC moment, written 'YYYY-MM-DD HH:MM:SS'."""
    instant = datetime.strptime(utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(bot, "datetime", Frozen)


def no_alpaca_clock(bot, monkeypatch):
    def unreachable():
        raise ConnectionError("clock unreachable")
    monkeypatch.setattr(bot, "_trading_client", unreachable)


# ── the check used when Alpaca's clock cannot be reached ────────────────────

@pytest.mark.parametrize("utc, new_york, expected", [
    # Wednesday 15 July 2026: New York is UTC-4.
    ("2026-07-15 13:29:59", "09:29 EDT", False),
    ("2026-07-15 13:30:00", "09:30 EDT", True),
    ("2026-07-15 19:59:59", "15:59 EDT", True),
    ("2026-07-15 20:00:00", "16:00 EDT", False),
])
def test_summer_day_runs_0930_to_1600_new_york(bot, monkeypatch, utc, new_york, expected):
    no_alpaca_clock(bot, monkeypatch)
    at(bot, monkeypatch, utc)
    assert bot.is_market_open() is expected, new_york


@pytest.mark.parametrize("utc, new_york, expected", [
    # Tuesday 24 November 2026: New York is UTC-5.
    ("2026-11-24 13:30:00", "08:30 EST", False),   # UTC-4 called this the open
    ("2026-11-24 14:29:59", "09:29 EST", False),
    ("2026-11-24 14:30:00", "09:30 EST", True),
    ("2026-11-24 20:30:00", "15:30 EST", True),    # UTC-4 called this after the close
    ("2026-11-24 20:59:59", "15:59 EST", True),
    ("2026-11-24 21:00:00", "16:00 EST", False),
])
def test_winter_day_runs_0930_to_1600_new_york(bot, monkeypatch, utc, new_york, expected):
    no_alpaca_clock(bot, monkeypatch)
    at(bot, monkeypatch, utc)
    assert bot.is_market_open() is expected, new_york


@pytest.mark.parametrize("utc, new_york", [
    ("2026-11-21 17:00:00", "Saturday 12:00 EST"),
    ("2026-11-22 17:00:00", "Sunday 12:00 EST"),
    ("2026-07-18 16:00:00", "Saturday 12:00 EDT"),
])
def test_weekend_is_closed_at_midday(bot, monkeypatch, utc, new_york):
    no_alpaca_clock(bot, monkeypatch)
    at(bot, monkeypatch, utc)
    assert bot.is_market_open() is False, new_york


def test_the_weekday_is_new_yorks_not_utcs(bot, monkeypatch):
    """Saturday 01:00 UTC is still Friday evening in New York: closed by the
    hour, not by the day. Monday 01:00 UTC is still Sunday there."""
    no_alpaca_clock(bot, monkeypatch)
    at(bot, monkeypatch, "2026-11-23 01:00:00")     # Sunday 20:00 EST
    assert bot._now_et().weekday() == 6
    assert bot.is_market_open() is False


def test_alpacas_clock_still_decides_when_it_answers(bot, monkeypatch):
    """Unchanged: the wall clock is only asked when Alpaca cannot be."""
    import types
    for answer in (True, False):
        clock = types.SimpleNamespace(is_open=answer)
        monkeypatch.setattr(bot, "_trading_client",
                            lambda: types.SimpleNamespace(get_clock=lambda: clock))
        at(bot, monkeypatch, "2026-11-22 17:00:00")  # a Sunday
        assert bot.is_market_open() is answer


# ── minutes until the open ──────────────────────────────────────────────────

@pytest.mark.parametrize("utc, new_york, minutes", [
    # The two log lines from 2026-11-24, which read ~1m and ~1439m.
    ("2026-11-24 13:29:34", "08:29:34 EST", 60),
    ("2026-11-24 13:30:34", "08:30:34 EST", 59),
    # Just before the real bell.
    ("2026-11-24 14:29:00", "09:29:00 EST", 1),
    ("2026-11-24 14:29:34", "09:29:34 EST", 1),    # under a minute still says 1
    ("2026-11-24 14:00:00", "09:00:00 EST", 30),
])
def test_minutes_until_open_before_the_bell_in_winter(bot, monkeypatch, utc, new_york, minutes):
    at(bot, monkeypatch, utc)
    assert bot.minutes_until_open() == minutes, new_york


@pytest.mark.parametrize("utc, new_york, minutes", [
    ("2026-07-15 12:30:00", "08:30:00 EDT", 60),
    ("2026-07-15 13:29:00", "09:29:00 EDT", 1),
])
def test_minutes_until_open_before_the_bell_in_summer(bot, monkeypatch, utc, new_york, minutes):
    at(bot, monkeypatch, utc)
    assert bot.minutes_until_open() == minutes, new_york


def test_minutes_until_open_after_the_close_points_at_tomorrow(bot, monkeypatch):
    at(bot, monkeypatch, "2026-11-24 21:00:00")     # Tuesday 16:00 EST
    assert bot.minutes_until_open() == 17 * 60 + 30


@pytest.mark.parametrize("utc, new_york, minutes", [
    ("2026-11-21 17:00:00", "Saturday 12:00 EST", 45 * 60 + 30),
    ("2026-11-22 17:00:00", "Sunday 12:00 EST", 21 * 60 + 30),
])
def test_minutes_until_open_at_the_weekend_points_at_monday(bot, monkeypatch, utc, new_york, minutes):
    at(bot, monkeypatch, utc)
    assert bot.minutes_until_open() == minutes, new_york


@pytest.mark.parametrize("utc, new_york, minutes", [
    # Clocks go back on Sunday 1 November 2026: the weekend is an hour longer.
    ("2026-10-31 16:00:00", "Saturday 12:00 EDT", 46 * 60 + 30),
    # Clocks go forward on Sunday 14 March 2027: an hour shorter.
    ("2027-03-13 17:00:00", "Saturday 12:00 EST", 44 * 60 + 30),
])
def test_minutes_until_open_across_a_clock_change(bot, monkeypatch, utc, new_york, minutes):
    at(bot, monkeypatch, utc)
    assert bot.minutes_until_open() == minutes, new_york
