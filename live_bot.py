#!/usr/bin/env python3
"""
live_bot.py — stock_bot.py, sending real orders with REAL MONEY.

Not authorised and never run as of 2026-11-17 (live_trading_stocks.md,
"Live"). This file exists so that when live is authorised there is one way
in, and it is this.

The same strategy, loop, trend gate and order path as broker_paper_bot.py.
The difference is the account: api.alpaca.markets and the live key pair.

Everything a live bot needs is said on its command line, and nothing is taken
from the environment:

    --ticker SPY      which stock. One of the calm six, or it refuses.
    --usd 16          dollars a trade. No default, and never above $166,
                      the last stage's trade size (utils/execution_mode.py).
    --real-money      the statement that this is meant. Without it, it refuses.

Why the command line and not environment variables, which is how every other
bot is told what it is: an environment variable can reach a process it was
never meant for. `pm2 restart --update-env` copies the calling shell into the
process, and .env is read by every bot. pm2 keeps a process's arguments across
restarts and nothing overwrites them. So this script reads its ticker and its
trade size from its arguments, writes them into its own environment over
whatever is there, and only then loads stock_bot. STOCK_TICKER, TRADE_AMOUNT_USD
or ALPACA_PAPER in the environment or in .env change nothing here.

And nothing in the environment can make any other script live: stock_bot.py
refuses to start with ALPACA_PAPER=False, and live mode is set only below.

Its files are its own (see stock_bot.py, "Every file a bot writes"):

    live/state_stock_<ticker>.json
    live/completed_trades_stock_<ticker>.csv
    live/order_journal_stock_<ticker>.json
    live/signal_log_stock-<ticker>.csv
    logs/stock_<ticker>_live.log

Start (see live_trading_stocks.md for what has to be true first):

    pm2 start live_bot.py --name spy-live --interpreter .venv/bin/python \\
      --stop-exit-codes 78 -- --ticker SPY --usd 16 --real-money
"""
import argparse
import os
import sys

from utils import execution_mode


def parse(argv):
    parser = argparse.ArgumentParser(
        prog="live_bot.py", add_help=True,
        description="A stock bot that sends real-money orders. See the file's docstring.")
    parser.add_argument("--ticker")
    parser.add_argument("--usd")
    parser.add_argument("--real-money", action="store_true")
    return parser.parse_args(argv)


def problems(args, env):
    """Why this process must not start, as a list of sentences; empty if it may."""
    found = []
    ticker = (args.ticker or "").strip().upper()
    if not ticker:
        found.append("--ticker is missing. There is no default: a bot that "
                     "spends money is told what to trade, on its command line.")
    elif ticker not in execution_mode.LIVE_TICKERS:
        found.append(f"--ticker {ticker} is not one of the stocks a live bot may "
                     f"trade ({', '.join(execution_mode.LIVE_TICKERS)}; "
                     f"utils/execution_mode.py, LIVE_TICKERS).")
    amount = None
    try:
        amount = float(args.usd)
        if not amount > 0:      # also catches nan
            raise ValueError
    except (TypeError, ValueError):
        amount = None
        found.append("--usd is missing or is not a positive number of dollars. "
                     "There is no default.")
    if amount is not None and amount > execution_mode.LIVE_MAX_TRADE_USD:
        found.append(f"--usd {amount:,.2f} is above the most a live bot may put "
                     f"into one trade, ${execution_mode.LIVE_MAX_TRADE_USD:,.0f} "
                     f"(utils/execution_mode.py, LIVE_MAX_TRADE_USD).")
    if not args.real_money:
        found.append("--real-money is missing. This script spends real money; "
                     "it starts only when its command line says that is meant. "
                     "For a rehearsal with no money, use broker_paper_bot.py.")
    # pm2 puts the process name in the environment and no restart overwrites
    # it (utils/identity.py). A live bot is named <ticker>-live.
    name = (env.get("name") or "").strip().lower()
    if name and ticker and name != f"{ticker.lower()}-live":
        found.append(f"pm2 process {name!r} is not named for {ticker}: expected "
                     f"'{ticker.lower()}-live'. Refusing to start rather than "
                     f"trade a ticker the name does not say.")
    return found


def main(argv=None):
    args = parse(sys.argv[1:] if argv is None else argv)
    found = problems(args, os.environ)
    if found:
        for line in found:
            print(f"live_bot: {line}", file=sys.stderr)
        print("live_bot: REFUSING TO START. Nothing was sent.", file=sys.stderr)
        sys.exit(1)

    ticker, amount = args.ticker.strip().upper(), float(args.usd)
    # The command line is the authority. Written over whatever the environment
    # holds, and before stock_bot loads .env: its loader leaves these three
    # alone once they are in the process environment.
    said = os.environ.get("STOCK_TICKER")
    if said and said.strip().upper() != ticker:
        print(f"live_bot: ignoring STOCK_TICKER={said!r} from the environment; "
              f"the command line says {ticker}.", file=sys.stderr)
    os.environ["STOCK_TICKER"] = ticker
    os.environ["TRADE_AMOUNT_USD"] = repr(amount)
    os.environ["ALPACA_PAPER"] = "False"

    execution_mode.REQUESTED = execution_mode.LIVE

    import stock_bot
    stock_bot.main()


if __name__ == "__main__":
    main()
