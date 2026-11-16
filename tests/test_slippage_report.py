"""
slippage_report.py: fill minus signal for each trade, and the average.

The number it exists to produce is the one every backtest here assumes and
nobody had measured: what a real fill costs against the price the bot decided
at. Backtests charge 0.10% a side.
"""
import csv
import json
import os
import sys

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import slippage_report as report  # noqa: E402

FIELDS = ["ticker", "entry_time", "exit_time", "entry_price", "exit_price",
          "entry_reason", "exit_reason", "gross_pct", "net_pct", "pnl_usd", "shares", "mode",
          "entry_signal_price", "exit_signal_price", "entry_fill_minus_signal_pct",
          "exit_fill_minus_signal_pct", "entry_order_id", "exit_order_id", "exit_attempts"]


def ledger(tmp_path, rows, name="completed_trades_stock_spy.csv"):
    path = tmp_path / name
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"ticker": "SPY", "shares": 0.1, "mode": "BROKERPAPER",
                             "exit_attempts": 1, **row})
    return str(path)


TRADE = {"entry_time": "2026-11-17T15:00:00+00:00", "exit_time": "2026-11-18T16:00:00+00:00",
         "entry_signal_price": 100.0, "entry_price": 100.20,     # bought 0.20% dear
         "exit_signal_price": 105.0, "exit_price": 104.895}      # sold 0.10% cheap


def test_each_trade_gives_two_legs_with_the_sign_explained(tmp_path):
    buy, sell = report.legs_from_ledger(ledger(tmp_path, [TRADE]))
    assert (buy["side"], sell["side"]) == ("BUY", "SELL")
    diff, pct, cost = report.measure(buy)
    assert diff == pytest.approx(0.20) and pct == pytest.approx(0.20) and cost == pytest.approx(0.20)
    diff, pct, cost = report.measure(sell)
    # Raw difference is negative on a bad sell; cost is positive on any bad fill.
    assert diff == pytest.approx(-0.105) and pct == pytest.approx(-0.10) and cost == pytest.approx(0.10)


def test_the_average_is_per_side_and_set_against_the_assumed_tenth(tmp_path):
    legs = report.legs_from_ledger(ledger(tmp_path, [TRADE]))
    summary = report.summarise(legs)
    assert summary["BUY"] == (pytest.approx(0.20), 1)
    assert summary["SELL"] == (pytest.approx(0.10), 1)
    assert summary["all"] == (pytest.approx(0.15), 2)
    text = report.render(legs)
    assert "average cost, both sides   +0.150% a side over 2 fill(s)" in text
    assert "backtests assume            +0.100% a side" in text
    assert "measured minus assumed      +0.050% a side   (worse than assumed)" in text
    assert "too few to conclude from" in text


def test_a_fill_better_than_the_signal_is_a_negative_cost(tmp_path):
    good = {**TRADE, "entry_price": 99.90, "exit_price": 105.105}
    legs = report.legs_from_ledger(ledger(tmp_path, [good]))
    assert [report.measure(l)[2] for l in legs] == [pytest.approx(-0.10), pytest.approx(-0.10)]
    assert "(no worse than assumed)" in report.render(legs)


def test_an_open_position_contributes_its_buy(tmp_path):
    path = tmp_path / "state_stock_spy.json"
    path.write_text(json.dumps({"position": "LONG", "ticker": "SPY", "shares": 0.13,
                                "entry_price": 754.60, "entry_signal_price": 754.27,
                                "entry_time": "2026-11-17T15:00:00+00:00"}))
    (leg,) = report.leg_from_state(str(path))
    assert leg["open"] and leg["side"] == "BUY"
    assert "position still open" in report.render([leg])
    path.write_text(json.dumps({"position": "NONE", "entry_price": 0.0}))
    assert report.leg_from_state(str(path)) == []


def test_a_retried_sell_is_marked(tmp_path):
    legs = report.legs_from_ledger(ledger(tmp_path, [{**TRADE, "exit_attempts": 3}]))
    assert "sold on attempt 3" in report.render(legs)


def test_a_simulated_ledger_has_no_fills_and_is_not_reported_as_zero_slippage(tmp_path):
    """A simulated ledger has no signal column. Missing must not read as 0.00%."""
    path = tmp_path / "completed_trades_stock_spy_paper.csv"
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS[:12])
        writer.writeheader()
        writer.writerow({k: TRADE.get(k, "x") for k in FIELDS[:12]})
    assert report.legs_from_ledger(str(path)) == []
    assert "No fills recorded yet" in report.render([])


def test_it_reads_broker_paper_by_default_and_live_only_when_asked(tmp_path, capsys):
    run_dir = tmp_path / "broker_paper"
    run_dir.mkdir()
    ledger(run_dir, [TRADE])
    ledger(tmp_path, [TRADE], name="completed_trades_stock_spy_live.csv")
    ledger(tmp_path, [TRADE], name="completed_trades_stock_spy_paper.csv")
    paper_ledgers, _ = report.default_paths(root=str(tmp_path))
    live_ledgers, _ = report.default_paths(live=True, root=str(tmp_path))
    assert [os.path.basename(p) for p in paper_ledgers] == ["completed_trades_stock_spy.csv"]
    assert [os.path.basename(p) for p in live_ledgers] == ["completed_trades_stock_spy_live.csv"]
    assert report.main(paper_ledgers) == 0
    assert "SPY   BUY" in capsys.readouterr().out
