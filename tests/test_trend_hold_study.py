"""
The trend-hold study's simulator (backtest_trend_hold.py), on made-up prices.

Written and run before the study itself, so a bug could not be found by
looking at results. What has to be true for the comparison to be fair:

  - the rule decides on completed closes and acts at the NEXT open, so nothing
    from the future can reach a decision;
  - costs are charged on every buy and sell, as in the dip-buying backtest;
  - holding, dip-buying and trend-holding are all marked the same way, at
    each session's close;
  - a verdict needs all five terms.
"""
import os
import sys

import pandas as pd
import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import backtest_trend_hold as study  # noqa: E402


def bars(closes, opens=None, start="2021-06-01"):
    """[(date, open, close)] on consecutive calendar days from `start`."""
    days = [str(d.date()) for d in pd.date_range(start, periods=len(closes), freq="D")]
    opens = opens or closes
    return list(zip(days, opens, closes))


LO, HI = "2021-01-01", "2030-01-01"


def test_fixed_numbers_are_the_ones_in_the_decision_log():
    assert study.TREND_SESSIONS == 200 and study.SENSITIVITY == (50, 100)
    assert (study.WINDOW_FROM, study.WINDOW_TO) == ("2021-06-01", "2026-09-03")
    assert study.CALM == ["XLP", "JNJ", "PG", "SPY", "XLU", "WMT"]
    assert (study.WIN_LOSS_RATIO, study.MIN_GOOD_YEARS) == (2.0, 4)
    assert sorted(study.CALM + study.JUMPY) == sorted(study.g.TICKERS)


def test_no_position_before_n_closes_exist():
    trades, equity = study.trend_hold(bars([10, 11, 12]), n=3, lo=LO, hi=HI, slip=0.0)
    assert trades == [] and set(equity.values()) == {0.0}


def test_it_buys_at_the_next_open_after_a_close_at_or_above_the_average():
    # closes 10,10,12: after day 3 the close (12) is above the 3-day average.
    # Day 4 opens at 20: that is the fill, not day 3's close.
    b = bars([10, 10, 12, 21, 22], opens=[10, 10, 12, 20, 22])
    trades, equity = study.trend_hold(b, n=3, lo=LO, hi=HI, slip=0.0)
    assert len(trades) == 1 and trades[0]["open_at_end"]
    assert trades[0]["entry_day"] == b[3][0]
    assert equity[b[3][0]] == pytest.approx(100.0 / 20 * (21 - 20))
    assert trades[0]["pct"] == pytest.approx((22 - 20) / 20 * 100)


def test_it_sells_at_the_next_open_after_a_close_below_the_average():
    # in from day 4; day 5 closes at 5, below its average; out at day 6's open (8)
    # and it stays out, because the closes after that stay below the average
    b = bars([10, 10, 12, 12, 5, 4, 3], opens=[10, 10, 12, 12, 12, 8, 4])
    trades, _ = study.trend_hold(b, n=3, lo=LO, hi=HI, slip=0.0)
    assert [(t["entry_day"], t["exit_day"], t["open_at_end"]) for t in trades] == [(b[3][0], b[5][0], False)]
    assert trades[0]["pct"] == pytest.approx((8 - 12) / 12 * 100)


def test_a_close_exactly_on_the_average_keeps_it_in():
    """Same convention as the v5 gate: only 'below' is off."""
    trades, _ = study.trend_hold(bars([10, 10, 10, 10, 10]), n=3, lo=LO, hi=HI, slip=0.0)
    assert len(trades) == 1 and trades[0]["pct"] == pytest.approx(0.0)


def test_nothing_from_the_future_changes_an_earlier_decision():
    """Change every price after day 6: the trades and marks up to day 6 are identical."""
    base = [10, 10, 12, 13, 9, 9, 14, 15, 16, 17]
    other = base[:6] + [1, 500, 2, 400]
    ta, ea = study.trend_hold(bars(base), n=3, lo=LO, hi=HI, slip=0.0)
    tb, eb = study.trend_hold(bars(other), n=3, lo=LO, hi=HI, slip=0.0)
    days = [b[0] for b in bars(base)][:6]
    assert [ea[d] for d in days] == [eb[d] for d in days]
    early = lambda ts: [(t["entry_day"], t["exit_day"], t["pct"]) for t in ts
                        if not t["open_at_end"] and t["exit_day"] <= days[-1]]
    assert early(ta) == early(tb) and early(ta)


def test_costs_are_charged_on_the_way_in_and_out():
    b = bars([10, 10, 12, 12, 5, 12, 12], opens=[10, 10, 12, 12, 12, 12, 12])
    free, _ = study.trend_hold(b, n=3, lo=LO, hi=HI, slip=0.0)
    paid, _ = study.trend_hold(b, n=3, lo=LO, hi=HI, slip=0.001)
    assert free[0]["pct"] == pytest.approx(0.0)
    assert paid[0]["pct"] == pytest.approx((12 * 0.999 - 12 * 1.001) / (12 * 1.001) * 100)
    assert paid[0]["pct"] < 0


def test_the_window_limits_when_it_trades_but_not_what_it_knows():
    """History before the window counts toward the average; no trade happens before it."""
    b = bars([10, 10, 12, 13, 14, 15], start="2021-05-28")     # window opens on the 5th bar
    trades, equity = study.trend_hold(b, n=3, lo="2021-06-01", hi=HI, slip=0.0)
    assert min(equity) == "2021-06-01"
    assert trades[0]["entry_day"] == "2021-06-01"


def test_buy_and_hold_is_one_purchase_marked_every_close():
    eq = study.buy_and_hold(bars([10, 11, 9], opens=[10, 11, 9]), lo=LO, hi=HI, slip=0.0)
    assert list(eq.values()) == pytest.approx([0.0, 10.0, -10.0])


def test_dip_trades_are_marked_at_each_close_like_everything_else():
    """A dip trade entered day 2 at 10 and closed day 4 for +5%: open days show the mark, later days the result."""
    b = bars([10, 10, 12, 10.5, 10.5])
    t = lambda day: pd.Timestamp(day + " 15:00", tz="UTC").value
    trade = {"entry_t": t(b[1][0]), "exit_t": t(b[3][0]), "entry_px": 10.0, "exit_px": 10.5, "pct": 5.0}
    mine, eq = study.dip_equity([trade], b, lo=LO, hi=HI, slip=0.0)
    assert mine == [trade]
    assert [eq[x[0]] for x in b] == pytest.approx([0.0, 0.0, 20.0, 5.0, 5.0])


def test_a_dip_trade_entered_outside_the_window_is_left_out():
    b = bars([10, 10, 12])
    t = lambda day: pd.Timestamp(day + " 15:00", tz="UTC").value
    trade = {"entry_t": t("2020-01-02"), "exit_t": t(b[1][0]), "entry_px": 10.0, "exit_px": 11.0, "pct": 10.0}
    mine, eq = study.dip_equity([trade], b, lo=LO, hi=HI, slip=0.0)
    assert mine == [] and set(eq.values()) == {0.0}


def test_max_drawdown_is_the_largest_fall_from_a_peak():
    eq = dict(zip("abcdef", [5.0, 20.0, 8.0, 15.0, 2.0, 30.0]))
    assert study.max_drawdown(eq) == pytest.approx(18.0)
    assert study.max_drawdown({"a": -7.0, "b": -3.0}) == pytest.approx(7.0)   # the curve starts at 0


def test_years_are_the_change_in_the_curve_over_each_year():
    eq = {"2021-12-30": 4.0, "2021-12-31": 5.0, "2022-06-30": 9.0, "2022-12-30": 2.0, "2023-01-03": 6.0}
    assert study.by_year(eq, ("2021", "2022", "2023")) == pytest.approx({"2021": 5.0, "2022": -3.0, "2023": 4.0})


def test_curves_add_over_shared_dates():
    assert study.add([{"a": 1.0, "b": 2.0}, {"b": 10.0, "c": 5.0}]) == {"b": 12.0}


def test_shape_measures_winners_against_losers():
    sh = study.shape([{"pct": 6.0}, {"pct": 6.0}, {"pct": -2.0}, {"pct": -2.0}, {"pct": -2.0}])
    assert sh["win_rate"] == pytest.approx(40.0) and sh["ratio"] == pytest.approx(3.0)


def _summary(net, drawdown, good_years):
    return {"net": net, "drawdown": drawdown, "good_years": good_years}


BIG_WINNERS = [{"pct": 6.0}, {"pct": -2.0}]
SMALL_WINNERS = [{"pct": 2.0}, {"pct": -5.0}]


def test_a_pass_needs_all_five_terms():
    terms, ok = study.verdict(_summary(50, 20, 5), _summary(10, 5, 4), _summary(200, 80, 5), BIG_WINNERS)
    assert ok and all(terms.values())


@pytest.mark.parametrize("trend,dip,hold,trades", [
    (_summary(-1, 20, 5), _summary(-10, 5, 4), _summary(200, 80, 5), BIG_WINNERS),    # lost money
    (_summary(50, 20, 5), _summary(60, 5, 4), _summary(200, 80, 5), BIG_WINNERS),     # dip-buying made more
    (_summary(50, 90, 5), _summary(10, 5, 4), _summary(200, 80, 5), BIG_WINNERS),     # deeper drawdown than holding
    (_summary(50, 20, 5), _summary(10, 5, 4), _summary(200, 80, 5), SMALL_WINNERS),   # winners not bigger than losers
    (_summary(50, 20, 3), _summary(10, 5, 4), _summary(200, 80, 5), BIG_WINNERS),     # up in only 3 years
])
def test_any_one_failed_term_fails_the_verdict(trend, dip, hold, trades):
    assert study.verdict(trend, dip, hold, trades)[1] is False


def test_beating_holding_on_return_is_not_a_pass_term():
    """Said in advance: a rule that is out of the market part of the time is not expected to."""
    terms, ok = study.verdict(_summary(50, 20, 5), _summary(10, 5, 4), _summary(10_000, 80, 6), BIG_WINNERS)
    assert ok
