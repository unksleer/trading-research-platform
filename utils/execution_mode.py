"""
Which execution mode a stock bot process was started in.

stock_bot.py has three:

  simulated     ALPACA_PAPER=True, the default. No order is sent anywhere. The
                ledger records the signal price. This is what the twelve
                registered bots run.
  broker paper  Real orders to Alpaca's PAPER account, state and ledger written
                from the fills. Started only through broker_paper_bot.py.
  live          Real orders, real money, the same order path as broker paper.
                Started only through live_bot.py.

The two order-sending modes are chosen here, by the entry script, and not by
an environment variable. An environment variable can reach a process it was
never meant for: `pm2 restart --update-env` copies the calling shell into every
bot, and .env is read by all of them. A variable that turned simulation into
order sending would be one bad restart away from all twelve registered bots.
So there is no such variable. broker_paper_bot.py and live_bot.py set REQUESTED
before they import stock_bot, and a process whose script is stock_bot.py can
only ever simulate.

Until 2026-11-17 live was the exception: ALPACA_PAPER=False on stock_bot.py
started a live bot. That is exactly the kind of variable described above, so
stock_bot.py now refuses to start with it.
"""

BROKER_PAPER = "BROKER_PAPER"
LIVE = "LIVE"

# None = simulated. Set by an entry script, never read from the environment.
REQUESTED = None

# The most a live bot may put into one trade, in dollars. The terms Lee agreed
# (DECISIONS.md 2026-11-17) are four stages by what is in the account, $100,
# $250, $500 and $1,000, each split across the six stocks: $16, $41, $83 and
# $166 a trade. This is the last stage's trade size. Nothing larger can be
# started without editing this line. Checked by live_bot.py before it starts
# and again by stock_bot.py, so no route into live mode goes round it. It is a
# ceiling only: which stage is running is Lee's decision at the time, and
# nothing here knows or enforces it.
LIVE_MAX_TRADE_USD = 166.0

# The stocks a live bot may trade: the calm six, where the backtested edge is
# (DECISIONS.md 2026-11-16, one-stock study). Any other ticker is refused.
LIVE_TICKERS = ("XLP", "JNJ", "PG", "SPY", "XLU", "WMT")
