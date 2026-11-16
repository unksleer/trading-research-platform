#!/usr/bin/env python3
"""
slippage_report.py — what the fills cost, against the prices the bot decided at.

A simulated bot's ledger records the signal price: the close of the newest
hourly bar at the moment the bot decided. Every backtest assumes a real fill
is 0.10% worse than that on each side. Nobody had measured it. The whole
backtested edge is about that size (profit factor 1.26 at signal prices, 1.10
with the assumed slippage), so the assumption decides whether there is an edge.

An order-sending bot (broker paper, later live) records both prices for every
trade. This prints fill minus signal for each one, and the average.

  fill minus signal   the raw difference, signed. On a buy, positive means the
                      fill was dearer than the signal. On a sell, negative
                      means the fill was cheaper than the signal.
  cost                the same thing turned so that positive is always money
                      lost to the fill: buy = fill minus signal, sell = signal
                      minus fill. This is the figure to hold against 0.10%.

Read a paper fill for what it is: Alpaca's paper account fills at the quote
with no queue and no market impact, so it is a floor on live slippage, not an
estimate of it. And the difference is not only slippage: the signal price is
an IEX print that can be up to a minute old by the time the order goes in.

    .venv/bin/python slippage_report.py                 # broker paper
    .venv/bin/python slippage_report.py --live          # live ledgers
    .venv/bin/python slippage_report.py path/to/ledger.csv ...
"""
import argparse
import csv
import glob
import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
ASSUMED_PCT = 0.10      # per side, what the backtests charge


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def legs_from_ledger(path):
    """Two legs, a buy and a sell, for every closed trade that has both prices."""
    legs = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            for side, fill_key, signal_key, when_key in (
                    ("BUY", "entry_price", "entry_signal_price", "entry_time"),
                    ("SELL", "exit_price", "exit_signal_price", "exit_time")):
                fill, signal = _num(row.get(fill_key)), _num(row.get(signal_key))
                if not fill or not signal:
                    continue
                legs.append({"ticker": row.get("ticker", ""), "side": side,
                             "when": (row.get(when_key) or "")[:19],
                             "signal": signal, "fill": fill,
                             "shares": _num(row.get("shares")) or 0.0,
                             "attempts": row.get("exit_attempts", "") if side == "SELL" else "",
                             "open": False})
    return legs


def leg_from_state(path):
    """The buy leg of a position that is still open, if there is one."""
    try:
        with open(path) as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return []
    fill, signal = _num(state.get("entry_price")), _num(state.get("entry_signal_price"))
    if state.get("position") != "LONG" or not fill or not signal:
        return []
    return [{"ticker": state.get("ticker", ""), "side": "BUY",
             "when": (state.get("entry_time") or "")[:19], "signal": signal,
             "fill": fill, "shares": _num(state.get("shares")) or 0.0,
             "attempts": "", "open": True}]


def measure(leg):
    """(fill minus signal in $, the same in %, cost in % with positive = worse)."""
    diff = leg["fill"] - leg["signal"]
    pct = diff / leg["signal"] * 100
    return diff, pct, (pct if leg["side"] == "BUY" else -pct)


def summarise(legs):
    """Average cost per side in %, for all legs and for each side. None where
    there is nothing to average."""
    def average(side=None):
        costs = [measure(l)[2] for l in legs if side is None or l["side"] == side]
        return (sum(costs) / len(costs), len(costs)) if costs else (None, 0)
    return {"all": average(), "BUY": average("BUY"), "SELL": average("SELL")}


def render(legs):
    if not legs:
        return ("  No fills recorded yet. An order-sending bot writes one row per "
                "closed trade;\n  nothing has closed, or no such bot has run.\n")
    out = [f"  {'ticker':<6}{'side':<5}{'when (UTC)':<21}{'signal':>10}{'fill':>10}"
           f"{'fill-signal':>13}{'%':>9}{'cost %':>9}  note"]
    for leg in sorted(legs, key=lambda l: (l["when"], l["side"])):
        diff, pct, cost = measure(leg)
        note = "position still open" if leg["open"] else ""
        if str(leg["attempts"]) not in ("", "1"):
            note = f"sold on attempt {leg['attempts']}; signal is the first attempt's"
        out.append(f"  {leg['ticker']:<6}{leg['side']:<5}{leg['when']:<21}"
                   f"{leg['signal']:>10.4f}{leg['fill']:>10.4f}{diff:>+13.4f}"
                   f"{pct:>+9.3f}{cost:>+9.3f}  {note}")
    summary = summarise(legs)
    out.append("")
    for label, key in (("buys", "BUY"), ("sells", "SELL"), ("both sides", "all")):
        mean, n = summary[key]
        if mean is not None:
            out.append(f"  average cost, {label:<11}{mean:>+8.3f}% a side over {n} fill(s)")
    mean, n = summary["all"]
    out.append(f"  backtests assume          {ASSUMED_PCT:>+8.3f}% a side")
    out.append(f"  measured minus assumed    {mean - ASSUMED_PCT:>+8.3f}% a side"
               + ("   (worse than assumed)" if mean > ASSUMED_PCT else "   (no worse than assumed)"))
    if n < 30:
        out.append(f"  {n} fill(s) is too few to conclude from; the spread between "
                   f"fills is what to look at.")
    return "\n".join(out) + "\n"


def default_paths(live=False, root=DIR):
    if live:
        return (sorted(glob.glob(os.path.join(root, "completed_trades_stock_*_live.csv"))),
                sorted(glob.glob(os.path.join(root, "state_stock_*_live.json"))))
    run_dir = os.path.join(root, "broker_paper")
    return (sorted(glob.glob(os.path.join(run_dir, "completed_trades_stock_*.csv"))),
            sorted(glob.glob(os.path.join(run_dir, "state_stock_*.json"))))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ledgers", nargs="*", help="ledger CSVs; default is every "
                        "broker-paper ledger and open position")
    parser.add_argument("--live", action="store_true",
                        help="read the live ledgers instead of broker paper")
    args = parser.parse_args(argv)

    ledgers, states = (args.ledgers, []) if args.ledgers else default_paths(args.live)
    legs = []
    for path in ledgers:
        legs += legs_from_ledger(path)
    for path in states:
        legs += leg_from_state(path)

    kind = "given ledgers" if args.ledgers else ("live" if args.live else "broker paper")
    print(f"\n  Fill against signal — {kind}, {len(ledgers)} ledger(s)\n")
    print(render(legs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
