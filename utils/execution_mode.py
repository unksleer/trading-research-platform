"""
Which execution mode a stock bot process was started in.

stock_bot.py has three:

  simulated     ALPACA_PAPER=True, the default. No order is sent anywhere. The
                ledger records the signal price. This is what the twelve
                registered bots run.
  broker paper  Real orders to Alpaca's PAPER account, state and ledger written
                from the fills. Started only through broker_paper_bot.py.
  live          ALPACA_PAPER=False. Real orders, real money, the same order
                path as broker paper.

Broker paper is chosen here, by the entry script, and not by an environment
variable. An environment variable can reach a process it was never meant for:
`pm2 restart --update-env` copies the calling shell into every bot, and .env is
read by all of them. A variable that turned simulation into order sending would
be one bad restart away from all twelve registered bots. So there is no such
variable. broker_paper_bot.py sets REQUESTED before it imports stock_bot, and a
process whose script is stock_bot.py can never be in broker-paper mode.
"""

BROKER_PAPER = "BROKER_PAPER"

# None = decide from ALPACA_PAPER as before (simulated or live).
REQUESTED = None
