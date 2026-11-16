# Stock bots: from simulation to real orders

How a stock bot that sends real orders is started, checked and stopped. Two
kinds: **broker paper** (real orders to Alpaca's paper account, no money) and
**live** (the same order path, real money). Broker paper is built and has been
run against Alpaca. Live has not been run and is not authorised; its section
says what is still missing.

`live_trading_setup.md` is the old guide for the retired Coinbase bots.

## The three modes

| | Simulated | Broker paper | Live |
|---|---|---|---|
| Started with | `stock_bot.py`, `ALPACA_PAPER=True` | `broker_paper_bot.py` | `stock_bot.py`, `ALPACA_PAPER=False` |
| Sends orders | No | Yes, to `paper-api.alpaca.markets` | Yes, to `api.alpaca.markets` |
| Money | None | None | Real |
| Ledger prices | The signal price | The fill, with the signal price beside it | The fill, with the signal price beside it |
| State and ledger | `state_stock_<t>_paper.json`, `completed_trades_stock_<t>_paper.csv` | `broker_paper/state_stock_<t>.json`, `broker_paper/completed_trades_stock_<t>.csv` | `state_stock_<t>_live.json`, `completed_trades_stock_<t>_live.csv` |
| Log | `logs/stock_<t>.log` | `logs/stock_<t>_brokerpaper.log` | `logs/stock_<t>_live.log` |
| Order journal | none | `broker_paper/order_journal_stock_<t>.json` | `logs/order_journal_stock_<t>_live.json` |
| Keys read | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | the same (they are paper keys) | `ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY` |

The twelve registered bots (stocks v5) are simulated and are not changed by
any of this. A rehearsal bot for SPY runs beside `spy-bot`; they share no file.

Broker paper cannot be switched on by a setting. No environment variable and
nothing in `.env` selects it: the mode is chosen by which script the process
runs. So a bad restart cannot turn a registered bot into an order sender.

The strategy is the same in all three: the same entries, exits and trend gate.
Only what happens after a decision differs.

## What an order goes through

1. It is written to the order journal with a client order id, before it is sent.
2. It is sent: a market order, a dollar amount to buy, the exact share count
   held to sell.
3. The bot asks Alpaca about it every second until Alpaca says it is finished:
   filled, cancelled, expired or rejected. After 30 seconds unfinished, the bot
   cancels it and waits for the answer to that.
4. State and ledger are written from what Alpaca says was filled: the quantity
   and the average price. Never the quantity asked for or the signal price.

What follows from that:

- **A sell that does not fill leaves the position open.** No trade is
  recorded. The exit stays owed and is sent again on the next tick, even if
  the signal that asked for it has gone.
- **A buy that does not fill opens nothing**, and no new buy is tried for 15
  minutes.
- **While an order has no final answer, nothing else is sent.**
- Before every order the bot checks that Alpaca holds what the state file
  says. If it does not, the bot stops (see below).

## Start a broker-paper rehearsal bot

The code has to be in the main checkout first. Merging is a separate decision.
It needs no restart: the running bots keep the code they started with, and the
simulated path they pick up at their next restart is tested to be unchanged.

From `/home/leeunks/coinbase-trading-bot`, with a clean environment so nothing
from the calling shell is copied into the process:

```bash
env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="$SHELL" LANG="$LANG" PATH="$PATH" STOCK_TICKER=SPY TRADE_AMOUNT_USD=100 pm2 start broker_paper_bot.py --name spy-brokerpaper --interpreter .venv/bin/python --stop-exit-codes 78
```

```bash
pm2 save
```

- The name must be `<ticker>-brokerpaper`. The bot checks its name against its
  ticker and refuses to start if they disagree.
- `STOCK_TICKER` and `TRADE_AMOUNT_USD` have no default. Leave one out and it
  refuses to start.
- `--stop-exit-codes 78` tells pm2 to leave the bot stopped when it stops
  itself over a mismatch, and still restart it after a watchdog exit (70).
  This flag is in pm2 7.0.3's help; it has not been tried here.
- One paper account can carry a rehearsal bot per ticker. Each checks only its
  own ticker's position. Change `SPY` and `spy` in the command for another.

**It will probably sit idle at first.** The trend gate applies as it does to
the registered bots, and entries are off while SPY's last close is below its
50-session average (754.27 against 764.10 on 2026-11-16). SPY alone trades about 13
times a year in the backtest. To see fills sooner, run one per calm ticker
(XLP, JNJ, PG, SPY, XLU, WMT). Adding `STOCK_TREND_GATE_DAYS=0` to the command
would switch the gate off for that one process, which rehearses the orders
sooner but is no longer the v5 strategy.

## Check it

```bash
pm2 describe spy-brokerpaper
```

```bash
tail -n 40 logs/stock_spy_brokerpaper.log
```

At startup the log must show both of these:

```
ORDERS ARE SENT in this mode (BROKERPAPER): $100.00 a trade. ...
Reconciled with the broker at https://paper-api.alpaca.markets: 0 SPY held, state file agrees, no open orders.
```

After a fill it shows the fill beside the signal:

```
[BROKERPAPER] BUY FILLED 0.134587273 SPY @ $742.9380 (signal $742.8300, fill minus signal +0.015%) order a2996834-...
```

Fills against signals, per trade and on average:

```bash
.venv/bin/python slippage_report.py
```

The position on Alpaca's paper dashboard should always equal `shares` in
`broker_paper/state_stock_spy.json`. The bot checks this itself at every start
and before every order.

A rehearsal bot does not appear on the project dashboard, in the observer or
in `restart_bots.py`. That is deliberate, so its trades cannot be counted as
v5's, and it means the log and the report are the only places to look for now.

## Restart it

```bash
pm2 restart spy-brokerpaper
```

Plain restart, no `--update-env`. pm2 keeps the ticker and amount it was
started with; `.env` is re-read for tuning as for every bot. `restart_bots.py`
does not know this bot and will not restart it.

## Stop it

```bash
pm2 stop spy-brokerpaper
```

**Stopping does not close a position.** If the bot holds shares when it is
stopped, they stay in the paper account and in its state file, and it picks
them up when started again. To remove the bot for good:

```bash
pm2 delete spy-brokerpaper
```

```bash
pm2 save
```

There is no tool yet for closing a rehearsal position by hand. If a position
is closed on Alpaca's site, the state file no longer matches and the bot will
refuse to start until `broker_paper/state_stock_spy.json` is moved aside
(which loses that open trade from the ledger).

## When the bot stops itself

It exits with code 78 and a `BROKER MISMATCH` line in its log saying which of
these it found. It sends nothing once it has found one.

| The log says | What it means | What to do |
|---|---|---|
| state file says X, the broker holds Y | The account and the state file disagree about the position. | Look at Alpaca. Find out which is right before touching either. |
| N open order(s) this bot has no record of | Something else placed an order in this ticker on this account. | Cancel it on Alpaca if it should not be there, then start the bot. |
| an order from before this start still has no final answer | An order is still working at Alpaca and could not be cancelled. | Look at the order on Alpaca; cancel it there; start the bot. |
| the broker's position could not be read | Alpaca could not be reached at startup, three tries. | Start it again when Alpaca is reachable. |
| mode is BROKERPAPER but orders would go to ... | The endpoint is not the paper one. | Do not start it. Something is wrong with the install. |
| state file / order journal cannot be read | A file is damaged. | Do not delete it. Compare with Alpaca first. |

An outage in the middle of the day is not a mismatch. The bot logs that it
could not check, sends nothing, and tries again on the next tick.

Things outside the bot that will cause a mismatch stop, correctly: trading the
same ticker by hand in the same account, a stock split, or a dividend
reinvested as shares.

## Reading the slippage report

```
  ticker side when (UTC)               signal      fill  fill-signal        %   cost %
  SPY    BUY  2026-11-16T17:47:32    742.8300  742.9380      +0.1080   +0.015   +0.015
  SPY    SELL 2026-11-16T17:47:48    742.8300  743.0740      +0.2440   +0.033   -0.033
```

- **fill-signal** is the raw difference. **cost %** is the same number turned
  so that positive always means the fill was worse than the signal.
- The backtests charge 0.10% a side. The backtested profit factor is 1.26 at
  signal prices and 1.10 with that charge, so the average cost decides whether
  there is an edge.
- **A paper fill is a floor, not an estimate.** Alpaca's paper account fills
  at the quote with no queue and no market impact. Real fills will be no
  better and may be worse.
- The difference is not all slippage. The signal price is the latest IEX
  trade in the hourly bar, which can be up to a minute old and is not the
  national best quote.
- A sell that needed more than one attempt is measured against the price at
  the first attempt, so the delay counts as cost.

## Live, later

Not authorised and not run. The plan on record is stages of $100, $250, $500
and $1,000 a trade.

What is already in place: live uses the order path above, unchanged, and the
tests run it against a fake broker. A live bot refuses to start without its
own keys and stops if it finds itself pointed at the paper endpoint.

What a live start would be, once the list below is dealt with:

```bash
env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="$SHELL" LANG="$LANG" PATH="$PATH" STOCK_TICKER=SPY TRADE_AMOUNT_USD=100 ALPACA_PAPER=False pm2 start stock_bot.py --name spy-live --interpreter .venv/bin/python --stop-exit-codes 78
```

Before stage one:

1. **Live keys.** `ALPACA_LIVE_API_KEY` and `ALPACA_LIVE_SECRET_KEY` in `.env`.
   They are separate names so the live key is never handed to the simulated
   bots, which all read `ALPACA_API_KEY`.
2. **An account that holds none of the ticker.** The bot treats any share of
   its ticker in the account as its own position. Shares held for other
   reasons will stop it at startup.
3. **Day-trade and settlement rules.** A buy and a sell on the same day is a
   day trade. Check Alpaca's current rules for the account type and size
   before starting: a restricted account can have a sell refused, and the bot
   would then hold the position and retry every minute until it is accepted.
   The paper account has $100,000 and never shows this.
4. **A live entry script.** Broker paper has one that checks the process name
   and has no defaults. Live still starts from `stock_bot.py`, where a process
   named `spy-live` gets no name check and a missing `TRADE_AMOUNT_USD` falls
   back to a default instead of refusing.
5. **The dashboard.** It will list a live stock bot as a second bot for its
   ticker and read the simulated bot's signal log for it. Not looked at.
6. **Enough rehearsal fills** to believe the cost per side, and a decision on
   what cost would call the pilot off.
7. **A way to close a position by hand** that keeps the state file right.

Not verified by anything in this repository: a real-money fill, a partial fill
from Alpaca, an order rejected for day-trading, and pm2's behaviour on exit
code 78.
