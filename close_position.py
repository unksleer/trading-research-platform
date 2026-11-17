#!/usr/bin/env python3
"""
close_position.py — close an order-sending bot's position by hand.

For a rehearsal bot (broker_paper_bot.py) or, with --live, a live bot
(live_bot.py). It sells the whole position through the bot's own order path:
the sell is written to the bot's order journal before it is sent, waited on
until the broker gives a final answer, and the bot's state file and ledger are
written from the fill. The ledger row says "Closed by hand". Afterwards the
bot's files are what they would be had the bot sold, so it can be started
again and carries on flat.

    .venv/bin/python close_position.py SPY            # says what it would do; sends nothing
    .venv/bin/python close_position.py SPY --send     # does it
    .venv/bin/python close_position.py SPY --live --send

STOP THE BOT FIRST (pm2 stop spy-brokerpaper). A running bot keeps its state
and journal in memory and would write them back over this tool's. The tool
checks, and refuses while the bot is running.

It refuses, and sends nothing, when:
  - the bot is running;
  - the broker does not hold exactly what the state file says;
  - the broker has an open order in this ticker that is not the bot's;
  - the state file or the order journal cannot be read, or the broker cannot
    be asked;
  - the market is closed (a market order cannot fill).
It never works out for itself which side is right. That is for a person.

If the sell is sent and does not fill, the position stays open and the exit
stays owed in the state file, as it does when the bot's own sell does not
fill: run this again, or start the bot and it sells on its first tick in
market hours.

Exit code: 0 closed, nothing to close, or a dry run that found no obstacle;
2 refused, nothing sent; 3 sent but the position is not (fully) closed.
"""
import argparse
import json
import os
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
REASON = "Closed by hand"


def pm2_status(name):
    """'online', 'stopped', ... for the pm2 process of that name; None if pm2
    has no such process; 'unknown' if pm2 could not be asked."""
    try:
        result = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
        processes = json.loads(result.stdout or "")
    except Exception:
        return "unknown"
    for process in processes:
        if process.get("name") == name:
            return str((process.get("pm2_env") or {}).get("status", "unknown"))
    return None


def load_bot(ticker, live):
    """stock_bot, loaded in the mode whose position is to be closed. This is
    how the tool gets the bot's own file names and its own order path."""
    from utils import execution_mode
    os.environ["STOCK_TICKER"] = ticker
    os.environ["ALPACA_PAPER"] = "False" if live else "True"
    os.environ["TRADE_AMOUNT_USD"] = "1"       # never used: this tool only sells
    execution_mode.REQUESTED = execution_mode.LIVE if live else execution_mode.BROKER_PAPER
    import stock_bot
    return stock_bot


def process_name(bot):
    return f"{bot.TICKER.lower()}-{'brokerpaper' if bot.BROKER_PAPER else 'live'}"


def _read_state(bot):
    """The state file as it is on disk, without the bot's stop-on-failure."""
    if not os.path.exists(bot.STATE_PATH):
        return {"position": "NONE", "shares": 0.0, "entry_price": 0.0}
    with open(bot.STATE_PATH) as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError("not a JSON object")
    return state


def survey(bot, running):
    """
    Everything the decision rests on, read and nothing written: (facts,
    reasons to refuse). `running` is a sentence when the bot is running.
    """
    facts, refuse = {"running": running}, []
    if running:
        refuse.append(f"The bot is running ({running}). Stop it first: "
                      f"pm2 stop {process_name(bot)}")
    if not bot.API_KEY or not bot.SECRET_KEY:
        refuse.append("The API keys for this mode are not set in .env.")
        return facts, refuse

    try:
        state = _read_state(bot)
    except (OSError, ValueError) as error:
        refuse.append(f"The state file {bot.STATE_PATH} cannot be read ({error}).")
        return facts, refuse
    long = state.get("position") == "LONG"
    facts["state"] = state
    facts["mine"] = float(state.get("shares", 0.0) or 0.0) if long else 0.0

    try:
        facts["unfinished"] = bot.broker().outstanding()
    except (OSError, ValueError) as error:
        refuse.append(f"The order journal {bot.JOURNAL_PATH} cannot be read ({error}).")
        return facts, refuse

    try:
        endpoint = bot.venue().endpoint()
        on_paper = "paper-api.alpaca.markets" in endpoint
        facts["endpoint"] = endpoint
        if bot.BROKER_PAPER != on_paper:
            refuse.append(f"Mode is {bot.MODE} but orders would go to {endpoint!r}.")
            return facts, refuse
        for attempt in (1, 2):
            held = bot.broker().position_qty()
            unknown = bot.broker().unknown_open_orders()
            if (bot._same_qty(held, facts["mine"]) and not unknown) or attempt == 2:
                break
            bot._pause(2)       # the broker's lists can trail by a moment
    except Exception as error:
        refuse.append(f"The broker could not be asked ({error}).")
        return facts, refuse
    facts["held"], facts["unknown"] = held, unknown

    # With an order of the bot's still unanswered, the two cannot be compared
    # yet: the answer may be a fill. --send settles it first and then makes
    # this same check through the bot's own startup code.
    if not facts["unfinished"] and not bot._same_qty(held, facts["mine"]):
        refuse.append(f"The state file says {facts['mine']:.9f} {bot.TICKER} "
                      f"(position {state.get('position')}) and the broker holds "
                      f"{held}. Find out which is right before anything is sold.")
    if unknown:
        refuse.append(f"The broker has {len(unknown)} open {bot.TICKER} order(s) "
                      f"that are not this bot's.")
    facts["market_open"] = bool(bot.is_market_open())
    if facts["mine"] > 0 and not facts["market_open"]:
        refuse.append("The market is closed. A market order cannot fill now; "
                      "run this again in market hours (9:30 to 16:00 New York).")
    return facts, refuse


def describe(bot, facts, out):
    account = ("Alpaca PAPER account, no money" if bot.BROKER_PAPER
               else "Alpaca LIVE account, REAL MONEY")
    out(f"\n  Hand close: {bot.TICKER}, {bot.MODE} ({account})\n")
    out(f"  bot process        {'RUNNING: ' + facts['running'] if facts['running'] else 'not running'}")
    state = facts.get("state")
    if state is None:
        return
    if facts["mine"] > 0:
        out(f"  state file         LONG {facts['mine']:.9f} {bot.TICKER}, entered "
            f"{str(state.get('entry_time') or '?')[:19]} at "
            f"${float(state.get('entry_price') or 0):.4f}")
        owed = state.get("exit_pending")
        if owed:
            out(f"                     an exit is already owed: {owed.get('reason')} "
                f"({owed.get('attempts', 0)} attempt(s))")
    else:
        out(f"  state file         flat (position {state.get('position')})")
    if "unfinished" in facts:
        n = len(facts["unfinished"])
        out(f"  unfinished orders  {n} in the bot's journal"
            + ("; they are settled first, as the bot does at startup" if n else ""))
    if "held" in facts:
        out(f"  broker holds       {facts['held']} {bot.TICKER} at {facts['endpoint']}")
        out(f"  other open orders  {len(facts['unknown'])}")
    if "market_open" in facts:
        out(f"  market             {'open' if facts['market_open'] else 'closed'}")
    out("")


def last_price(bot):
    """The newest hourly close, which is what the bot calls its signal price.
    Only a reference to measure the fill against; 0.0 if it cannot be had."""
    try:
        bars = bot.fetch_bars(bot.TICKER, 5)
        return float(bars["close"].iloc[-1]) if len(bars) else 0.0
    except Exception:
        return 0.0


def send(bot, reason, out):
    """Sell the position through the bot's order path. Returns the exit code."""
    state = bot.load_state()
    try:
        # Exactly what the bot does before its first tick: finish any order
        # left without an answer, write any fill not yet in the state file,
        # and check the broker's book against it.
        bot.reconcile_orders(state)
    except SystemExit:
        out(f"  REFUSED by the bot's own startup check. Nothing was sent. The "
            f"reason is the last line of {bot.log_path}")
        return 2
    if state.get("position") != "LONG":
        out("  Nothing left to close: finishing the bot's earlier orders closed "
            "the position.")
        return 0

    price = last_price(bot)
    if price <= 0:
        out("  No recent price could be read, so this fill will have no signal "
            "price to be measured against. Selling anyway.")
    owed = state.get("exit_pending")
    if owed and not str(owed.get("reason", "")).startswith(reason):
        # The bot had already decided to sell and its order did not fill. The
        # ledger should still say a person closed it.
        owed["reason"] = f"{reason} (owed since: {owed.get('reason')})"
    before = float(state["shares"])
    try:
        bot.close_position(state, price, reason)
    except SystemExit:
        out(f"  STOPPED by the bot's check before the order. The reason is the "
            f"last line of {bot.log_path}")
        return 2

    if state.get("position") == "NONE":
        row = _last_ledger_row(bot)
        if row:
            out(f"  CLOSED. Sold {row['shares']} {bot.TICKER} at "
                f"${float(row['exit_price']):.4f}. P&L on the trade "
                f"${float(row['pnl_usd']):+.4f}, from the fills. Ledger: {bot.TRADES_PATH}")
        else:
            out("  CLOSED.")
        try:
            out(f"  The broker now holds {bot.broker().position_qty()} {bot.TICKER}.")
        except Exception as error:
            out(f"  (The broker's position could not be re-read: {error}.)")
        out(f"  The bot is flat. Started again, it trades again on its next "
            f"signal; leave it stopped if that is not wanted.")
        return 0

    left = float(state.get("shares") or 0.0)
    if bot.broker().outstanding():
        out("  SENT, and the broker has not yet said what became of the order. "
            "The position is still recorded as open.")
    elif left < before and not bot._same_qty(left, before):
        out(f"  PARTLY SOLD: {before - left:.9f} sold, {left:.9f} {bot.TICKER} still held.")
    else:
        out(f"  NOT FILLED ({_last_sell_status(bot)}). The position is still open: "
            f"{left:.9f} {bot.TICKER}.")
    out("  The exit is owed in the state file. Run this again, or start the bot "
        "and it sells on its first tick in market hours.")
    return 3


def _last_ledger_row(bot):
    import csv
    try:
        with open(bot.TRADES_PATH, newline="") as handle:
            rows = list(csv.DictReader(handle))
        return rows[-1] if rows else None
    except OSError:
        return None


def _last_sell_status(bot):
    sells = sorted((entry.get("created_at", ""), entry)
                   for entry in bot.broker().entries.values() if entry.get("side") == "SELL")
    if not sells:
        return "no order on record"
    entry = sells[-1][1]
    return entry.get("status", "?") + (f": {entry['submit_error']}"
                                       if entry.get("submit_error") else "")


def run(bot, do_send=False, reason=REASON, out=print, pm2=None):
    """The whole tool, given the bot module. Returns the exit code."""
    from utils import run_lock
    pm2 = pm2 or pm2_status
    name = process_name(bot)
    running, lock = "", None
    try:
        lock = run_lock.acquire(bot.LOCK_PATH, "close_position.py")
    except run_lock.Held as held:
        running = f"its lock is held by {held.holder}"
    if not running:
        # A bot started before the lock existed does not hold it; pm2 knows.
        status = pm2(name)
        if status == "online":
            running = f"pm2 shows {name} online"
        elif status == "unknown":
            out(f"  (pm2 could not be asked whether {name} is running; going by "
                f"the bot's lock file alone.)")
    try:
        facts, refuse = survey(bot, running)
        describe(bot, facts, out)
        if refuse:
            for line in refuse:
                out(f"  REFUSED: {line}")
            out("  Nothing was sent.\n")
            return 2
        if facts["mine"] <= 0 and not facts["unfinished"]:
            out(f"  Nothing to close: the bot is flat and so is the broker.\n")
            return 0
        if facts["unfinished"]:
            out(f"  {'First settling' if do_send else 'Would first settle'} "
                f"{len(facts['unfinished'])} unfinished order(s) from the bot, and "
                f"check the broker's position against the state file after that.")
        if facts["mine"] > 0:
            out(f"  {'Then sending' if do_send else 'Would then send'}: market SELL "
                f"of the whole position ({facts['mine']:.9f} {bot.TICKER} on record), "
                f"recorded as \"{reason}\".")
        if not do_send:
            out("  DRY RUN. Nothing was sent and no file was changed. Add --send "
                "to do it.\n")
            return 0
        code = send(bot, reason, out)
        out("")
        return code
    finally:
        run_lock.release(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Close a rehearsal or live stock bot's position by hand. "
                    "Without --send it only says what it would do.")
    parser.add_argument("ticker")
    parser.add_argument("--live", action="store_true",
                        help="the live bot's position (real money); default is "
                             "the broker-paper rehearsal bot's")
    parser.add_argument("--send", action="store_true",
                        help="send the order; without this nothing is sent")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would be done and send nothing (the default)")
    args = parser.parse_args(argv)
    if args.send and args.dry_run:
        parser.error("--send and --dry-run together: pick one")
    bot = load_bot(args.ticker.strip().upper(), args.live)
    return run(bot, do_send=args.send)


if __name__ == "__main__":
    sys.exit(main())
