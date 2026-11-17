"""
What the order-sending bots are doing, for the dashboard. Read-only.

Two kinds of stock bot send real orders: a rehearsal bot (broker_paper_bot.py,
Alpaca's paper account, no money) and a live bot (live_bot.py, real money).
Neither is one of the registered simulated bots, and nothing they do belongs
in the registered run's figures:

  - a rehearsal fill is not a v5 trade, and counting it would change the
    sample the registration is graded on;
  - their ledgers hold fills, the simulated ledgers hold signal prices, and a
    sum of the two describes neither.

So their files live in folders of their own (broker_paper/, live/) that no
other reader looks in, and this module is the one place that reads them. It
returns rehearsal and live separately and never adds either to anything else.
The dashboard shows what it returns in a panel of its own.

Nothing here writes a file, sends an order or talks to a broker. The process
list is handed in (a parsed `pm2 jlist`), and so is the price lookup.
"""
import csv
import glob
import json
import os
import re
import time

KINDS = {
    # kind: (entry script, folder, pm2 name suffix, log file suffix)
    "rehearsal": ("broker_paper_bot.py", "broker_paper", "-brokerpaper", "brokerpaper"),
    "live":      ("live_bot.py",         "live",         "-live",        "live"),
}
EXIT_STOPPED_ITSELF = 78        # stock_bot.EXIT_BROKER_MISMATCH
BANNER = "Stock Trading Bot —"  # first line a bot logs when it starts
LAST_FILLS = 8


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tickers_on_disk(folder):
    found = set()
    for pattern, rx in (("state_stock_*.json", r"state_stock_(.+)\.json$"),
                        ("completed_trades_stock_*.csv", r"completed_trades_stock_(.+)\.csv$"),
                        ("order_journal_stock_*.json", r"order_journal_stock_(.+)\.json$")):
        for path in glob.glob(os.path.join(folder, pattern)):
            match = re.search(rx, os.path.basename(path))
            if match:
                found.add(match.group(1).upper())
    return found


def _process_ticker(process, suffix):
    """The ticker a pm2 process is for: from its name, which no restart can
    change, else from what it was started with."""
    name = str(process.get("name") or "")
    if name.lower().endswith(suffix) and len(name) > len(suffix):
        return name[: -len(suffix)].upper()
    env = process.get("pm2_env") or {}
    args = env.get("args") or []
    if isinstance(args, list) and "--ticker" in args[:-1]:
        return str(args[args.index("--ticker") + 1]).upper()
    return str(env.get("STOCK_TICKER") or "").upper() or None


def _trade_size(process):
    env = (process or {}).get("pm2_env") or {}
    args = env.get("args") or []
    if isinstance(args, list) and "--usd" in args[:-1]:
        return _num(args[args.index("--usd") + 1])
    return _num(env.get("TRADE_AMOUNT_USD"))


def _processes_by_ticker(processes, root, script, suffix):
    found = {}
    for process in processes or []:
        env = process.get("pm2_env") or {}
        path = env.get("pm_exec_path") or ""
        if os.path.basename(path) != script:
            continue
        # A bot run from another checkout writes that checkout's files.
        if os.path.realpath(os.path.dirname(path)) != os.path.realpath(root):
            continue
        ticker = _process_ticker(process, suffix)
        if ticker:
            found[ticker] = process
    return found


def _log_tail(path, size=65536):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - size))
            return handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def last_critical(lines):
    """The last CRITICAL message of the bot's latest run, or ''. This is where
    a bot that stopped itself says why."""
    start = 0
    for index, line in enumerate(lines):
        if BANNER in line:
            start = index
    for line in reversed(lines[start:]):
        if " CRITICAL - " in line:
            return line.split(" CRITICAL - ", 1)[1].strip()
    return ""


def process_status(process, log_lines):
    """
    {state, label, detail} for one bot's process.

    state: running | stopped_itself | stopped | errored | not_started.
    A bot that stopped itself exits with code 78 and pm2 is told to leave it
    stopped; the reason is the last CRITICAL line of its log.
    """
    if process is None:
        return {"state": "not_started", "label": "Not in pm2",
                "detail": "No pm2 process for this bot. Its files are from an earlier run."}
    env = process.get("pm2_env") or {}
    status = str(env.get("status") or "unknown").lower()
    exit_code = env.get("exit_code")
    why = last_critical(log_lines)
    if status == "online":
        return {"state": "running", "label": "Running", "detail": ""}
    if exit_code == EXIT_STOPPED_ITSELF:
        mismatch = "BROKER MISMATCH" in why
        return {"state": "stopped_itself",
                "label": "STOPPED ON A MISMATCH" if mismatch else "STOPPED ITSELF",
                "detail": why or "Exit code 78. The reason is in its log."}
    if status == "errored":
        return {"state": "errored", "label": "Errored",
                "detail": why or "pm2 gave up restarting it. See its log."}
    return {"state": "stopped", "label": "Stopped",
            "detail": (f"Last check before it stopped: {why}" if why else "")}


def _state(path):
    """(state dict or None, error text)."""
    if not os.path.exists(path):
        return None, ""
    try:
        with open(path) as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("not a JSON object")
        return state, ""
    except (OSError, ValueError) as error:
        return None, f"state file cannot be read: {error}"


def _unfinished_orders(path):
    """Orders in the journal not yet settled into the state file; None if the
    journal cannot be read."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path) as handle:
            journal = json.load(handle)
        return sum(1 for entry in journal.values() if not entry.get("applied"))
    except (OSError, ValueError, AttributeError):
        return None


def _ledger(path):
    """(closed trades, realized $) from one bot's own ledger."""
    closed, realized = 0, 0.0
    try:
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                pnl = _num(row.get("pnl_usd"))
                if pnl is None:
                    continue
                closed += 1
                realized += pnl
    except OSError:
        pass
    return closed, realized


def _legs(ledger_path, state_path):
    import slippage_report as report
    legs = []
    if os.path.exists(ledger_path):
        try:
            legs += report.legs_from_ledger(ledger_path)
        except (OSError, csv.Error):
            pass
    legs += report.leg_from_state(state_path)
    return legs


def _slippage(legs):
    """Average cost a side against what the backtests assume, or None."""
    import slippage_report as report
    summary = report.summarise(legs)
    mean, n = summary["all"]
    if mean is None:
        return None
    return {"fills": n, "avg_cost_pct": mean,
            "buy_cost_pct": summary["BUY"][0], "buys": summary["BUY"][1],
            "sell_cost_pct": summary["SELL"][0], "sells": summary["SELL"][1],
            "assumed_pct": report.ASSUMED_PCT,
            "minus_assumed_pct": mean - report.ASSUMED_PCT}


def _fill_rows(legs):
    import slippage_report as report
    rows = []
    for leg in sorted(legs, key=lambda l: (l["when"], l["side"]), reverse=True)[:LAST_FILLS]:
        diff, pct, cost = report.measure(leg)
        rows.append({"when": leg["when"], "side": leg["side"], "signal": leg["signal"],
                     "fill": leg["fill"], "shares": leg["shares"],
                     "fill_minus_signal_pct": pct, "cost_pct": cost,
                     "open": bool(leg["open"]), "note": report.note(leg)})
    return rows


def _position(state, price_for, ticker):
    if not state or state.get("position") != "LONG":
        return {"held": False}
    shares = _num(state.get("shares")) or 0.0
    entry = _num(state.get("entry_price")) or 0.0
    signal = _num(state.get("entry_signal_price"))
    out = {"held": True, "shares": shares, "entry_price": entry,
           "entry_signal_price": signal, "entry_time": state.get("entry_time") or "",
           "entry_fill_minus_signal_pct": ((entry - signal) / signal * 100
                                           if signal and entry else None),
           "price": None, "unrealized_usd": None, "exit_owed": None}
    owed = state.get("exit_pending")
    if isinstance(owed, dict):
        out["exit_owed"] = {"reason": owed.get("reason") or "",
                            "attempts": int(owed.get("attempts") or 0)}
    if price_for is not None and entry > 0:
        try:
            price, source, _age = price_for(ticker, entry)
        except Exception:
            price, source = None, "entry"
        # "entry" means no price could be had. An unpriced position is not flat.
        if price and source != "entry":
            out["price"] = float(price)
            out["unrealized_usd"] = (float(price) - entry) * shares
    return out


def collect(root, processes, price_for=None, now=None):
    """
    Every rehearsal and live bot that has a pm2 process or files on disk.

    Returns {"bots": [...], "totals": {"rehearsal": {...}, "live": {...}}}.
    The two totals are never added to each other or to anything else.
    """
    now = time.time() if now is None else now
    bots, totals = [], {}
    for kind, (script, folder_name, suffix, log_suffix) in KINDS.items():
        folder = os.path.join(root, folder_name)
        running = _processes_by_ticker(processes, root, script, suffix)
        kind_legs, kind_bots = [], []
        for ticker in sorted(_tickers_on_disk(folder) | set(running)):
            low = ticker.lower()
            state_path = os.path.join(folder, f"state_stock_{low}.json")
            ledger_path = os.path.join(folder, f"completed_trades_stock_{low}.csv")
            log_path = os.path.join(root, "logs", f"stock_{low}_{log_suffix}.log")
            process = running.get(ticker)
            state, state_error = _state(state_path)
            legs = _legs(ledger_path, state_path)
            closed, realized = _ledger(ledger_path)
            try:
                log_age = max(0.0, now - os.path.getmtime(log_path))
            except OSError:
                log_age = None
            kind_legs += legs
            kind_bots.append({
                "kind": kind,
                "ticker": ticker,
                "name": (process or {}).get("name") or f"{low}{suffix}",
                "process": process_status(process, _log_tail(log_path)),
                "restarts": ((process or {}).get("pm2_env") or {}).get("restart_time"),
                "trade_usd": _trade_size(process),
                "log_age_seconds": log_age,
                "state_error": state_error,
                "position": _position(state, price_for, ticker),
                "unfinished_orders": _unfinished_orders(
                    os.path.join(folder, f"order_journal_stock_{low}.json")),
                "closed_trades": closed,
                "realized_usd": realized,
                "slippage": _slippage(legs),
                "fills": _fill_rows(legs),
            })
        bots += kind_bots
        priced = [b["position"]["unrealized_usd"] for b in kind_bots
                  if b["position"].get("unrealized_usd") is not None]
        totals[kind] = {
            "bots": len(kind_bots),
            "running": sum(1 for b in kind_bots if b["process"]["state"] == "running"),
            "stopped_itself": sum(1 for b in kind_bots
                                  if b["process"]["state"] == "stopped_itself"),
            "open_positions": sum(1 for b in kind_bots if b["position"]["held"]),
            "closed_trades": sum(b["closed_trades"] for b in kind_bots),
            "realized_usd": sum(b["realized_usd"] for b in kind_bots),
            "unrealized_usd": sum(priced),
            "unpriced_positions": sum(1 for b in kind_bots if b["position"]["held"]
                                      and b["position"]["unrealized_usd"] is None),
            "slippage": _slippage(kind_legs),
        }
    return {"bots": bots, "totals": totals}
