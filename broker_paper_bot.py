#!/usr/bin/env python3
"""
broker_paper_bot.py — stock_bot.py, sending real orders to Alpaca's PAPER account.

The same strategy, the same loop, the same trend gate as stock_bot.py. The one
difference is execution: where a simulated bot writes down the signal price
and sends nothing, this sends a market order to paper-api.alpaca.markets,
waits for the fill, and writes its state and ledger from what was filled. No
real money is involved. It exists to rehearse the order path and to measure
fills against signal prices before any is.

It is a separate script, not a setting, on purpose:

  - Nothing in the environment or in .env can turn one of the registered
    simulated bots into an order sender. The mode is chosen by which script a
    process runs (utils/execution_mode.py).
  - The dashboard, restart_bots.py and the bot registry find bots by script
    name. They do not see this one, so a rehearsal bot for SPY does not show
    up as a second SPY bot or get swept up in `restart_bots.py --stocks`.

Its files are its own (see stock_bot.py, "Every file a bot writes"):

    broker_paper/state_stock_<ticker>.json
    broker_paper/completed_trades_stock_<ticker>.csv
    broker_paper/order_journal_stock_<ticker>.json
    broker_paper/signal_log_stock-<ticker>.csv
    logs/stock_<ticker>_brokerpaper.log

Start (see live_trading_stocks.md for the whole procedure):

    STOCK_TICKER=SPY TRADE_AMOUNT_USD=100 \\
      pm2 start broker_paper_bot.py --name spy-brokerpaper \\
        --interpreter .venv/bin/python --stop-exit-codes 78
"""
import os
import sys

FALSE = ("false", "0", "no", "f")


def problems(env):
    """Why this process must not start, as a list of sentences; empty if it may."""
    found = []
    ticker = (env.get("STOCK_TICKER") or "").strip().upper()
    if not ticker:
        found.append("STOCK_TICKER is not set. There is no default here: a "
                     "bot that sends orders is told what to trade.")
    try:
        amount = float(env.get("TRADE_AMOUNT_USD") or "")
        if amount <= 0:
            raise ValueError
    except ValueError:
        found.append("TRADE_AMOUNT_USD is not set to a positive number. There "
                     "is no default here.")
    if (env.get("ALPACA_PAPER") or "True").strip().lower() in FALSE:
        found.append("ALPACA_PAPER is false. This script only ever talks to "
                     "the paper account; live is live_bot.py.")
    # pm2 puts the process name in the environment and no restart overwrites
    # it (utils/identity.py). A rehearsal bot is named <ticker>-brokerpaper,
    # so a restart that changed its ticker is caught before it opens a file.
    name = (env.get("name") or "").strip().lower()
    if name and ticker and name != f"{ticker.lower()}-brokerpaper":
        found.append(f"pm2 process {name!r} is not named for {ticker}: expected "
                     f"'{ticker.lower()}-brokerpaper'. Refusing to start rather "
                     f"than trade a ticker the name does not say.")
    return found


def main():
    found = problems(os.environ)
    if found:
        for line in found:
            print(f"broker_paper_bot: {line}", file=sys.stderr)
        sys.exit(1)

    # Set here so .env cannot say otherwise: the loader leaves a value already
    # in the process environment alone for this key.
    os.environ["ALPACA_PAPER"] = "True"

    from utils import execution_mode
    execution_mode.REQUESTED = execution_mode.BROKER_PAPER

    import stock_bot
    stock_bot.main()


if __name__ == "__main__":
    main()
