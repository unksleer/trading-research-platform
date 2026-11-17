"""
The dashboard's view of the bots that send real orders, and the wall between
it and everything else on the page.

A rehearsal bot (Alpaca's paper account) and a live bot (real money) are not
among the registered simulated bots. Their P&L comes from fills; the simulated
P&L comes from signal prices; and the registered run is graded on its own
trades only. So their figures are read by one module (utils/order_bots.py),
served by one endpoint (/api/order_bots), drawn in one panel, and added to
nothing.
"""
import csv
import json
import os
import shutil
import subprocess
import sys

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import dashboard  # noqa: E402
import slippage_report  # noqa: E402
from utils import order_bots, positions  # noqa: E402

PAGE = open(os.path.join(DIR, "dashboard", "index.html")).read()
SOURCE = open(os.path.join(DIR, "dashboard.py")).read()
NOW = 1_800_000_000.0
FIELDS = ["ticker", "entry_time", "exit_time", "entry_price", "exit_price", "entry_reason",
          "exit_reason", "gross_pct", "net_pct", "pnl_usd", "shares", "mode",
          "entry_signal_price", "exit_signal_price", "entry_fill_minus_signal_pct",
          "exit_fill_minus_signal_pct", "entry_order_id", "exit_order_id", "exit_attempts"]


def trade(ticker, entry_fill, entry_signal, exit_fill, exit_signal, pnl, reason="Take Profit Triggered",
          day="2026-11-16"):
    return {"ticker": ticker, "entry_time": f"{day}T15:00:00+00:00",
            "exit_time": f"{day}T18:00:00+00:00", "entry_price": entry_fill,
            "exit_price": exit_fill, "entry_reason": "x", "exit_reason": reason,
            "gross_pct": 1.0, "net_pct": 1.0, "pnl_usd": pnl, "shares": 0.5, "mode": "x",
            "entry_signal_price": entry_signal, "exit_signal_price": exit_signal,
            "entry_order_id": "a", "exit_order_id": f"b-{day}-{ticker}", "exit_attempts": 1}


def write_ledger(folder, ticker, rows):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"completed_trades_stock_{ticker.lower()}.csv"),
              "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_state(folder, ticker, state):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"state_stock_{ticker.lower()}.json"), "w") as handle:
        json.dump(state, handle)


def write_log(root, ticker, suffix, lines, age=30.0):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    path = os.path.join(root, "logs", f"stock_{ticker.lower()}_{suffix}.log")
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    os.utime(path, (NOW - age, NOW - age))


def process(root, name, script, status="online", exit_code=None, **env):
    return {"name": name, "pid": 1, "pm2_env": {
        "pm_exec_path": os.path.join(root, script), "status": status,
        "exit_code": exit_code, "restart_time": 0, **env}}


LONG = {"position": "LONG", "shares": 0.134587273, "entry_price": 742.938,
        "entry_signal_price": 742.83, "entry_time": "2026-11-17T15:00:00+00:00"}
BANNER = "2026-11-17 09:30:00 [stock/SPY/brokerpaper] INFO - Stock Trading Bot — SPY (BROKERPAPER)"
MISMATCH = ("2026-11-17 09:30:02 [stock/SPY/brokerpaper] CRITICAL - BROKER MISMATCH — state "
            "file says 0.5 SPY (position LONG), the broker holds 0. Not trading. Exiting with "
            "code 78. See live_trading_stocks.md, 'When the bot stops itself'.")


@pytest.fixture
def root(tmp_path):
    """One rehearsal bot holding SPY with one closed trade behind it, and one
    live bot in XLP with two closed trades."""
    root = str(tmp_path)
    paper, live = os.path.join(root, "broker_paper"), os.path.join(root, "live")
    write_state(paper, "SPY", LONG)
    write_ledger(paper, "SPY", [trade("SPY", 742.938, 742.83, 743.074, 742.83, 0.0183)])
    write_log(root, "SPY", "brokerpaper", [BANNER, "... INFO - --- SPY market check ---"])
    write_state(live, "XLP", {"position": "NONE", "shares": 0.0, "entry_price": 0.0})
    write_ledger(live, "XLP", [trade("XLP", 80.10, 80.00, 81.00, 81.05, 4.50),
                               trade("XLP", 80.00, 80.00, 79.00, 79.10, -5.00, day="2026-11-17")])
    return root


def collect(root, processes=(), price=None):
    price_for = None if price is None else (lambda ticker, entry: price)
    return order_bots.collect(root, list(processes), price_for=price_for, now=NOW)


def bot(data, name):
    (found,) = [b for b in data["bots"] if b["name"] == name]
    return found


# ── what the view shows ─────────────────────────────────────────────────────

def test_it_finds_rehearsal_and_live_bots_and_keeps_them_apart(root):
    data = collect(root, [process(root, "spy-brokerpaper", "broker_paper_bot.py",
                                  TRADE_AMOUNT_USD="100"),
                          process(root, "xlp-live", "live_bot.py",
                                  args=["--ticker", "XLP", "--usd", "83", "--real-money"])])
    assert [(b["name"], b["kind"]) for b in data["bots"]] == [
        ("spy-brokerpaper", "rehearsal"), ("xlp-live", "live")]
    assert bot(data, "spy-brokerpaper")["trade_usd"] == 100.0
    assert bot(data, "xlp-live")["trade_usd"] == 83.0
    assert set(data["totals"]) == {"rehearsal", "live"}
    assert data["totals"]["rehearsal"]["realized_usd"] == pytest.approx(0.0183)
    assert data["totals"]["live"]["realized_usd"] == pytest.approx(-0.50)
    assert data["totals"]["live"]["closed_trades"] == 2
    # No figure anywhere in the payload adds the two together.
    assert set(data) == {"bots", "totals"}


def test_the_position_shows_the_fill_beside_the_signal_price(root):
    data = collect(root, price=(745.0, "candle", 900))
    held = bot(data, "spy-brokerpaper")["position"]
    assert held["held"] and held["shares"] == 0.134587273
    assert held["entry_price"] == 742.938 and held["entry_signal_price"] == 742.83
    assert held["entry_fill_minus_signal_pct"] == pytest.approx(0.01454, abs=1e-4)
    assert held["unrealized_usd"] == pytest.approx((745.0 - 742.938) * 0.134587273)
    assert bot(data, "xlp-live")["position"] == {"held": False}


def test_a_position_with_no_price_is_unpriced_not_flat(root):
    """PriceResolver answers (entry price, "entry") when it has no price."""
    data = collect(root, price=(742.938, "entry", None))
    assert bot(data, "spy-brokerpaper")["position"]["unrealized_usd"] is None
    assert data["totals"]["rehearsal"]["unpriced_positions"] == 1
    assert collect(root)["bots"][0]["position"]["unrealized_usd"] is None   # no resolver at all


def test_the_slippage_is_the_slippage_reports(root):
    data = collect(root)
    spy = bot(data, "spy-brokerpaper")
    legs = (slippage_report.legs_from_ledger(
                os.path.join(root, "broker_paper", "completed_trades_stock_spy.csv"))
            + slippage_report.leg_from_state(
                os.path.join(root, "broker_paper", "state_stock_spy.json")))
    mean, n = slippage_report.summarise(legs)["all"]
    assert n == 3 and spy["slippage"]["fills"] == 3
    assert spy["slippage"]["avg_cost_pct"] == pytest.approx(mean)
    assert spy["slippage"]["assumed_pct"] == 0.10
    assert spy["slippage"]["minus_assumed_pct"] == pytest.approx(mean - 0.10)
    newest = spy["fills"][0]
    assert newest["open"] and newest["side"] == "BUY" and newest["note"] == "position still open"
    sell = [f for f in spy["fills"] if f["side"] == "SELL"][0]
    assert sell["cost_pct"] == pytest.approx(-(743.074 - 742.83) / 742.83 * 100)
    # Live: a buy 0.125% dearer, a sell 0.062% cheaper, a buy at the signal, a sell 0.126% cheaper.
    live = data["totals"]["live"]["slippage"]
    assert live["fills"] == 4 and live["avg_cost_pct"] > 0


def test_a_hand_close_is_marked_in_the_fills_and_the_report(root):
    write_ledger(os.path.join(root, "broker_paper"), "SPY",
                 [trade("SPY", 742.9, 742.8, 741.0, 741.2, -0.25, reason="Closed by hand")])
    sell = [f for f in bot(collect(root), "spy-brokerpaper")["fills"] if f["side"] == "SELL"][0]
    assert sell["note"] == "closed by hand"
    legs = slippage_report.legs_from_ledger(
        os.path.join(root, "broker_paper", "completed_trades_stock_spy.csv"))
    assert "closed by hand" in slippage_report.render(legs)


def test_a_bot_with_nothing_yet_is_listed_with_nothing(root):
    data = collect(root, [process(root, "wmt-brokerpaper", "broker_paper_bot.py")])
    wmt = bot(data, "wmt-brokerpaper")
    assert wmt["ticker"] == "WMT" and wmt["process"]["state"] == "running"
    assert wmt["position"] == {"held": False} and wmt["slippage"] is None
    assert wmt["fills"] == [] and wmt["closed_trades"] == 0 and wmt["log_age_seconds"] is None


def test_no_bots_at_all_is_an_empty_view_not_an_error(tmp_path):
    data = collect(str(tmp_path))
    assert data["bots"] == []
    assert data["totals"]["rehearsal"]["bots"] == data["totals"]["live"]["bots"] == 0
    assert data["totals"]["live"]["slippage"] is None


# ── running, stopped, or stopped on a mismatch ──────────────────────────────

def test_running(root):
    spy = bot(collect(root, [process(root, "spy-brokerpaper", "broker_paper_bot.py")]),
              "spy-brokerpaper")
    assert spy["process"] == {"state": "running", "label": "Running", "detail": ""}
    assert spy["log_age_seconds"] == pytest.approx(30.0)    # pm2 "online" proves nothing


def test_stopped_on_a_mismatch_says_so_and_says_why(root):
    write_log(root, "SPY", "brokerpaper", [BANNER, MISMATCH])
    data = collect(root, [process(root, "spy-brokerpaper", "broker_paper_bot.py",
                                  status="stopped", exit_code=78)])
    status = bot(data, "spy-brokerpaper")["process"]
    assert status["state"] == "stopped_itself" and status["label"] == "STOPPED ON A MISMATCH"
    assert "state file says 0.5 SPY (position LONG), the broker holds 0" in status["detail"]
    assert data["totals"]["rehearsal"]["stopped_itself"] == 1
    assert data["totals"]["rehearsal"]["running"] == 0


def test_a_second_copy_that_stopped_itself_is_not_called_a_mismatch(root):
    write_log(root, "SPY", "brokerpaper", [
        BANNER, "... CRITICAL - ALREADY RUNNING — the lock is held by pid 7. Exiting with code 78."])
    status = bot(collect(root, [process(root, "spy-brokerpaper", "broker_paper_bot.py",
                                        status="stopped", exit_code=78)]),
                 "spy-brokerpaper")["process"]
    assert status["label"] == "STOPPED ITSELF" and "ALREADY RUNNING" in status["detail"]


def test_a_mismatch_from_an_earlier_run_is_not_reported_against_this_one(root):
    write_log(root, "SPY", "brokerpaper", [BANNER, MISMATCH, BANNER, "... INFO - Reconciled"])
    stopped = process(root, "spy-brokerpaper", "broker_paper_bot.py", status="stopped", exit_code=0)
    status = bot(collect(root, [stopped]), "spy-brokerpaper")["process"]
    assert status == {"state": "stopped", "label": "Stopped", "detail": ""}


def test_stopped_by_hand_errored_and_never_started(root):
    by_hand = process(root, "spy-brokerpaper", "broker_paper_bot.py", status="stopped", exit_code=0)
    assert bot(collect(root, [by_hand]), "spy-brokerpaper")["process"]["state"] == "stopped"
    errored = process(root, "spy-brokerpaper", "broker_paper_bot.py", status="errored", exit_code=1)
    assert bot(collect(root, [errored]), "spy-brokerpaper")["process"]["label"] == "Errored"
    gone = bot(collect(root), "spy-brokerpaper")["process"]
    assert gone["state"] == "not_started" and gone["label"] == "Not in pm2"


def test_a_bot_run_from_another_checkout_is_not_this_ones(root, tmp_path_factory):
    elsewhere = str(tmp_path_factory.mktemp("worktree"))
    data = collect(root, [process(elsewhere, "spy-brokerpaper", "broker_paper_bot.py")])
    assert bot(data, "spy-brokerpaper")["process"]["state"] == "not_started"


def test_the_simulated_bots_are_not_listed_here(root):
    data = collect(root, [process(root, "spy-bot", "stock_bot.py", STOCK_TICKER="SPY"),
                          process(root, "dashboard", "dashboard.py")])
    assert [b["name"] for b in data["bots"]] == ["spy-brokerpaper", "xlp-live"]
    assert all(b["process"]["state"] == "not_started" for b in data["bots"])


def test_an_owed_exit_and_unfinished_orders_are_shown(root):
    paper = os.path.join(root, "broker_paper")
    write_state(paper, "SPY", {**LONG, "exit_pending": {
        "reason": "Stop Loss Triggered", "signal_price": 720.0, "attempts": 3}})
    with open(os.path.join(paper, "order_journal_stock_spy.json"), "w") as handle:
        json.dump({"a": {"applied": True}, "b": {"applied": False}}, handle)
    spy = bot(collect(root), "spy-brokerpaper")
    assert spy["position"]["exit_owed"] == {"reason": "Stop Loss Triggered", "attempts": 3}
    assert spy["unfinished_orders"] == 1


def test_files_that_cannot_be_read_are_said_not_guessed(root):
    paper = os.path.join(root, "broker_paper")
    for name in ("state_stock_spy.json", "order_journal_stock_spy.json"):
        with open(os.path.join(paper, name), "w") as handle:
            handle.write("{ not json")
    spy = bot(collect(root), "spy-brokerpaper")
    assert "state file cannot be read" in spy["state_error"]
    assert spy["position"] == {"held": False} and spy["unfinished_orders"] is None
    assert spy["closed_trades"] == 1                         # the ledger still reads


# ── the wall between this and the simulated figures ─────────────────────────

def test_nothing_the_simulated_figures_read_can_see_an_order_bots_files(root):
    """
    Functionally, for the readers that take a root; by pattern for the ones
    in dashboard.py that do not. A rehearsal or live position in the list of
    open positions would be added to the registration's unrealised P&L
    (build_pnl_by_market takes every stock position it is given).
    """
    import fnmatch
    import re
    write_state(os.path.join(root, "live"), "XLP", {**LONG, "shares": 5.0})
    assert positions.open_positions(root) == []
    theirs = ["broker_paper/state_stock_spy.json", "broker_paper/completed_trades_stock_spy.csv",
              "live/state_stock_xlp.json", "live/completed_trades_stock_xlp.csv",
              "broker_paper/signal_log_stock-spy.csv", "live/signal_log_stock-xlp.csv"]
    patterns = set(re.findall(r'"((?:completed_trades|state|logs/signal_log)[^"]*\*[^"]*)"', SOURCE))
    assert {"completed_trades_stock_*_paper.csv", "completed_trades_*.csv"} <= patterns
    for pattern in patterns | {"state_*.json", "logs/signal_log_*.csv"}:
        for path in theirs:
            assert not fnmatch.fnmatch(path, pattern), (path, pattern)


def test_the_metrics_payload_is_built_without_them():
    """/api/metrics feeds every simulated and v5 figure on the page. The order
    bots have an endpoint of their own and are read nowhere else."""
    assert SOURCE.count("order_bots.collect(") == 1
    start = SOURCE.index("    def get_order_bots(self):")
    end = SOURCE.index("    def get_pm2_status(self):")
    assert start < SOURCE.index("order_bots.collect(") < end
    outside = SOURCE[:start] + SOURCE[end:]
    assert "order_bots" not in outside.replace("'/api/order_bots'", "").replace(
        "self.get_order_bots()", "")
    assert "broker_paper" not in outside and "live_bot" not in outside
    served = SOURCE[SOURCE.index("if self.path == '/api/order_bots'"):][:400]
    assert "self.get_order_bots()" in served and "get_dashboard_data" not in served


def test_the_endpoint_serves_this_checkouts_bots_and_says_when_pm2_is_unreadable(monkeypatch):
    handler = dashboard.DashboardHandler.__new__(dashboard.DashboardHandler)
    seen = {}

    def fake_collect(root, processes, price_for=None, now=None):
        seen.update(root=root, processes=processes)
        return {"bots": [], "totals": {}}

    monkeypatch.setattr(order_bots, "collect", fake_collect)
    monkeypatch.setattr(dashboard.subprocess, "run", lambda *a, **k: type(
        "R", (), {"stdout": json.dumps([{"name": "spy-brokerpaper"}]), "returncode": 0})())
    data = handler.get_order_bots()
    assert seen == {"root": DIR, "processes": [{"name": "spy-brokerpaper"}]}
    assert data["problem"] == "" and data["timestamp"]

    def no_pm2(*a, **k):
        raise FileNotFoundError("pm2")
    monkeypatch.setattr(dashboard.subprocess, "run", no_pm2)
    data = handler.get_order_bots()
    assert "pm2 could not be read" in data["problem"] and seen["processes"] == []


def test_the_module_only_reads():
    source = open(os.path.join(DIR, "utils", "order_bots.py")).read()
    for forbidden in ('"w"', '"a"', "os.remove", "os.replace", "subprocess", "requests",
                      "submit_", "cancel_", "save_state"):
        assert forbidden not in source, forbidden


# ── the page ────────────────────────────────────────────────────────────────

def test_the_panel_is_fed_by_its_own_endpoint_and_draws_only_into_itself():
    assert 'id="order-bots-panel"' in PAGE and "NOT PART OF V5" in PAGE
    assert "never added to the simulated figures" in PAGE
    start = PAGE.index("// ---- Order-sending bots (rehearsal and live) ----")
    script = PAGE[start:PAGE.index("// Fetch metrics on load")]
    assert "fetch('/api/order_bots')" in script and "/api/metrics" not in script
    import re
    drawn_into = set(re.findall(r"getElementById\('([^']+)'\)", script))
    assert drawn_into == {"order-bots-body", "orders-updated"}
    # And the code that draws the simulated figures knows nothing of it.
    everything_else = PAGE[PAGE.index("async function fetchMetrics("):start]
    for name in ("OrderBots", "order-bots", "order_bots", "ordUsd", "ordSlippage"):
        assert name not in everything_else, name


def test_the_panel_goes_stale_like_the_others():
    body = PAGE[PAGE.index("async function fetchOrderBots("):][:600]
    assert "markOk('orders')" in body and "markFail('orders'" in body and "throw new Error" in body
    assert "orders: 30000" in PAGE and "setInterval(fetchOrderBots, 30000)" in PAGE
    assert "orders: 'orders-updated'" in PAGE
    assert "fetchOrderBots()" in PAGE[PAGE.index("visibilitychange"):][:320]


def test_the_pages_own_script_renders_the_view(root, tmp_path):
    """The script from the page, run by node against a real payload."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    write_log(root, "SPY", "brokerpaper", [BANNER, MISMATCH.replace(
        "the broker holds 0", "the broker holds <img src=x onerror=alert(1)>")])
    data = collect(root, [process(root, "spy-brokerpaper", "broker_paper_bot.py",
                                  status="stopped", exit_code=78, TRADE_AMOUNT_USD="100")],
                   price=(745.0, "candle", 900))
    data["problem"] = ""
    start = PAGE.index("// ---- Order-sending bots (rehearsal and live) ----")
    script = PAGE[start:PAGE.index("// Fetch metrics on load")]
    harness = tmp_path / "render.js"
    harness.write_text(
        "const els = {'order-bots-body': {innerHTML: ''}, 'orders-updated': {textContent: ''}};\n"
        "const document = {getElementById: id => els[id]};\n"
        "function fmt(t) { return 'now'; }\n"
        "function ageText(ms) { return Math.round(ms / 1000) + 's'; }\n"
        "function markOk() {} function markFail() {}\n"
        + script +
        "\nrenderOrderBots(JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8')));\n"
        "console.log(els['order-bots-body'].innerHTML);\n")
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(data))
    result = subprocess.run([node, str(harness), str(payload)], capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    html = result.stdout
    assert "spy-brokerpaper" in html and "STOPPED ON A MISMATCH" in html
    assert "ord-alarm" in html and "state file says 0.5 SPY" in html
    assert "<img src=x" not in html and "&lt;img src=x" in html      # log text is escaped
    assert "0.134587 sh @ $742.9380 (fill)" in html
    assert "signal $742.8300 · fill minus signal +0.015%" in html
    assert "backtests assume +0.100%" in html and "too few fills to conclude from" in html
    assert "xlp-live" in html and "REAL MONEY" in html
    assert "Rehearsal — Alpaca paper account, no money" in html and "Live — real money" in html
    assert "$100 a trade" in html and "closed by hand" not in html
