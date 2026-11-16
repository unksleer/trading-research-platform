"""
The one-stock study's arithmetic (backtest_one_stock.py).

The study's value is that its choices are made on one window and judged on
another, by rules fixed before the run. These tests pin the pieces a wrong
answer could hide in: the windows do not overlap, the volatility and holding
figures are what they say, and a single stock passes only when all four terms
hold. They use no market data.
"""
import os
import sys

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import backtest_one_stock as study  # noqa: E402

NS_DAY = 86_400_000_000_000


def trade(day, pct):
    """A trade entered at 15:00 UTC on `day` (YYYY-MM-DD)."""
    import pandas as pd
    t = pd.Timestamp(day + " 15:00", tz="UTC").value
    return {"entry_t": t, "exit_t": t + NS_DAY, "pct": pct, "ledger_pct": pct + 0.2, "ticker": "X"}


def test_the_windows_do_not_overlap_and_sit_inside_the_gate_test():
    import backtest_regime_gate as g
    assert study.SELECT_TO < study.CONFIRM_FROM
    assert study.SELECT_FROM == g.TEST_FROM and study.CONFIRM_TO == g.TEST_TO


def test_confirm_stops_before_the_live_weeks_that_prompted_the_idea():
    """v4's per-ticker live results (from 2026-09-04) suggested the question."""
    import backtest_regime_gate as g
    assert study.CONFIRM_TO < g.FOUND_FROM


def test_volatility_is_the_sd_of_daily_returns_inside_the_window_only():
    closes = {"2021-01-04": 100.0, "2021-01-05": 110.0, "2021-01-06": 99.0,
              "2024-01-02": 500.0}                    # outside: must not count
    assert study.volatility(closes, "2021-01-01", "2021-12-31") == pytest.approx(10.0)


def test_hold_is_first_close_to_last_close_in_the_window():
    closes = {"2023-12-29": 1.0, "2024-01-02": 100.0, "2025-06-02": 80.0, "2026-09-03": 150.0,
              "2026-09-04": 999.0}
    assert study.hold_pct(closes, "2024-01-01", "2026-09-03") == pytest.approx(50.0)


def test_longest_losing_run_counts_consecutive_losses_in_time_order():
    rows = [trade("2024-01-0%d" % d, p) for d, p in
            ((2, 1.0), (3, -5.0), (4, -5.0), (5, 2.0), (8, -5.0))]
    assert study.losing_run(list(reversed(rows))) == 2


def test_spearman_is_a_rank_correlation():
    assert study.spearman([1, 2, 3, 4], [10, 20, 30, 400]) == pytest.approx(1.0)
    assert study.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def good_stock():
    """24 trades, positive in all three years, profit factor well above 1.2."""
    rows = []
    for year in ("2024", "2025", "2026"):
        for month in range(1, 9):
            rows.append(trade(f"{year}-{month:02d}-10", -4.0 if month == 4 else 2.0))
    return rows


def test_a_single_stock_passes_when_all_four_terms_hold():
    v = study.single_verdict("X", good_stock(), basket_pf=1.25)
    assert v["passed"] and all(v["terms"].values())
    assert v["stats"]["n"] == 24


def test_too_few_trades_fails_however_good_they_are():
    v = study.single_verdict("X", good_stock()[:10], basket_pf=1.0)
    assert not v["passed"]


def test_a_stock_that_does_not_beat_the_basket_fails():
    """Clearing 1.20 is not enough if the basket did better over the same years."""
    v = study.single_verdict("X", good_stock(), basket_pf=99.0)
    assert not v["passed"]


def test_one_good_year_is_not_consistency():
    rows = [trade(f"2024-{m:02d}-10", 6.0) for m in range(1, 11)]
    rows += [trade(f"2025-{m:02d}-10", -0.5) for m in range(1, 9)]
    rows += [trade(f"2026-{m:02d}-10", -0.5) for m in range(1, 9)]
    v = study.single_verdict("X", rows, basket_pf=1.0)
    assert v["stats"]["net"] > 0 and v["stats"]["pf"] >= study.MIN_PF
    assert not v["passed"]


def test_the_fixed_numbers_are_the_ones_in_the_decision_log():
    assert (study.MIN_SELECT_TRADES, study.MIN_CONFIRM_TRADES) == (25, 20)
    assert (study.MIN_PF, study.PF_MARGIN, study.PERSISTENCE) == (1.20, 0.10, 0.50)
