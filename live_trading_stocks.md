# Stock bots: from simulation to real orders

How a stock bot that sends real orders is started, checked, closed by hand
and stopped. Two kinds: **broker paper** (real orders to Alpaca's paper
account, no money) and **live** (the same order path, real money). Broker
paper is built and has been run against Alpaca. Live is built, has never been
run and is not authorised; its section says what is still missing.

`live_trading_setup.md` is the old guide for the retired Coinbase bots.

## The three modes

| | Simulated | Broker paper | Live |
|---|---|---|---|
| Started with | `stock_bot.py`, `ALPACA_PAPER=True` | `broker_paper_bot.py` | `live_bot.py --ticker T --usd N --real-money` |
| Sends orders | No | Yes, to `paper-api.alpaca.markets` | Yes, to `api.alpaca.markets` |
| Money | None | None | Real |
| Ledger prices | The signal price | The fill, with the signal price beside it | The fill, with the signal price beside it |
| State and ledger | `state_stock_<t>_paper.json`, `completed_trades_stock_<t>_paper.csv` | `broker_paper/state_stock_<t>.json`, `broker_paper/completed_trades_stock_<t>.csv` | `live/state_stock_<t>.json`, `live/completed_trades_stock_<t>.csv` |
| Log | `logs/stock_<t>.log` | `logs/stock_<t>_brokerpaper.log` | `logs/stock_<t>_live.log` |
| Order journal | none | `broker_paper/order_journal_stock_<t>.json` | `live/order_journal_stock_<t>.json` |
| On the dashboard | The existing panels | "Order-Sending Bots" panel only | "Order-Sending Bots" panel only |
| Keys read | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | the same (they are paper keys) | `ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY` |

The twelve registered bots (stocks v5) are simulated and are not changed by
any of this. A rehearsal bot for SPY runs beside `spy-bot`; they share no file.

Neither order-sending mode can be switched on by a setting. No environment
variable and nothing in `.env` selects one: the mode is chosen by which script
the process runs. So a bad restart cannot turn a registered bot into an order
sender. Until 2026-11-17 live was the exception (`ALPACA_PAPER=False` on
`stock_bot.py`); `stock_bot.py` now refuses to start with that.

The files of both order-sending modes are in folders of their own
(`broker_paper/`, `live/`). Everything else in the project finds bots' files
by pattern in the project root, so nothing else can pick these up: not the
simulated P&L, not the v5 registration's figures, not the observer.

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
- **One process per bot.** The bot holds a lock on its files for as long as it
  runs (`broker_paper/running_stock_<t>.lock`). A second copy of the same bot
  stops at once, and `close_position.py` refuses while the lock is held. The
  lock goes when the process ends, however it ends.

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
  Tried on pm2 7.0.3 on 2026-11-17 with throwaway processes: exit 78 stayed
  stopped with no restarts, exit 70 was restarted.
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

On the dashboard, rehearsal and live bots are in a panel of their own,
**Order-Sending Bots**, near the top. For each bot it shows whether the
process is running, stopped, or stopped itself (with the reason from its log),
how long ago its log was written, the position with the fill beside the signal
price, the latest fills, realized P&L from fills, and the average cost against
the signal price beside the 0.10% the backtests assume. Rehearsal and live are
totalled separately. Nothing in that panel is added to any other figure on the
page, and a rehearsal or live bot appears nowhere else on it: not in the
simulated P&L, the registration panel, the positions ledger or the process
monitor. It is also not in the observer or in `restart_bots.py`. The panel
needs the dashboard restarted once after this code is merged.

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

## Close a position by hand

Stop the bot, then:

```bash
.venv/bin/python close_position.py SPY
```

That is a dry run: it prints the state file's position, what Alpaca holds,
whether the market is open, and what it would send. It sends nothing and
changes no file. To do it:

```bash
.venv/bin/python close_position.py SPY --send
```

- The sell goes through the bot's own order path: journalled before it is
  sent, waited on, state and ledger written from the fill. The ledger row's
  exit reason is `Closed by hand`.
- Afterwards the bot is flat and its files are consistent. Started again
  (`pm2 start spy-brokerpaper`), it reconciles and trades on its next signal.
  Leave it stopped if that is not wanted.
- **The bot must be stopped first.** A running bot keeps its state in memory
  and would write it back over the tool's. The tool checks the bot's lock and
  pm2, and refuses while the bot is running.
- It refuses, and sends nothing, if Alpaca does not hold exactly what the
  state file says, if there is an open order in the ticker that is not the
  bot's, if a file cannot be read, or if the market is closed. It does not
  decide which side is right.
- If the sell is sent and does not fill, the position stays open and the exit
  stays owed, as with the bot's own exits: run the tool again, or start the
  bot and it sells on its first tick in market hours.
- For a live bot add `--live`. That sends a real-money sell.

Do not close a bot's position on Alpaca's site. The state file then no longer
matches, the bot refuses to start, and the only way back is to move
`broker_paper/state_stock_spy.json` aside, which loses the open trade from the
ledger.

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
| ALREADY RUNNING, the lock is held by ... | Another process is working this bot's files: a second copy of the bot, or `close_position.py` mid-run. | Find the other process. Start the bot when it has finished. |

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
- A sell marked `closed by hand` is measured against the newest hourly close
  at the moment the tool was run, not against a signal.

## Live

Built, not authorised, never run. No order has ever gone to the live endpoint.

The terms Lee agreed are in `DECISIONS.md` (2026-11-17, "Live pilot terms"):
the calm six on the v5 rules, in four stages by what is in the account, the
account split equally across the six.

| Stage | In the account | A trade |
|---|---|---|
| 1 | $100 | $16 |
| 2 | $250 | $41 |
| 3 | $500 | $83 |
| 4 | $1,000 | $166 |

Funding the account, the first live order and every move to a larger stage
each need Lee's go at the time. Nothing in the code knows which stage is
running or moves between them; the trade size is whatever the start command
says, up to the ceiling below.

What a live start would be, once the list below is dealt with. One process
per stock, six in all; this is SPY at stage 1:

```bash
env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="$SHELL" LANG="$LANG" PATH="$PATH" pm2 start live_bot.py --name spy-live --interpreter .venv/bin/python --stop-exit-codes 78 -- --ticker SPY --usd 16 --real-money
```

What `live_bot.py` insists on:

- **Ticker, trade size and `--real-money` on the command line.** None has a
  default. Leave one out and it refuses to start.
- **Nothing from the environment.** `STOCK_TICKER`, `TRADE_AMOUNT_USD` and
  `ALPACA_PAPER`, in the shell or in `.env`, change nothing: the script
  writes what its command line said over them. pm2 keeps a process's
  arguments across restarts, so a restart cannot change what the bot trades
  or how much.
- **At most $166 a trade**, stage 4's trade size. Checked by `live_bot.py`
  and again inside `stock_bot.py`. Raising it means editing
  `LIVE_MAX_TRADE_USD` in `utils/execution_mode.py`. It is a ceiling, not a
  stage check: `--usd 166` starts on a $100 account if that is what is typed.
- **Only the calm six**: XLP, JNJ, PG, SPY, XLU, WMT (`LIVE_TICKERS`, same
  file).
- **The name `<ticker>-live`.**
- **Its own keys**, `ALPACA_LIVE_API_KEY` and `ALPACA_LIVE_SECRET_KEY`. It
  never falls back to the paper keys, and it stops if it finds itself pointed
  at the paper endpoint.

Everything else is as for a rehearsal bot: the order path, the startup check,
the lock, exit code 78, `close_position.py SPY --live`, the dashboard panel
(marked REAL MONEY), `slippage_report.py --live`.

Before stage one:

1. **Lee's decision.** Nothing here starts a live bot.
2. **Live keys.** `ALPACA_LIVE_API_KEY` and `ALPACA_LIVE_SECRET_KEY` in `.env`.
   They are separate names so the live key is never handed to the simulated
   bots, which all read `ALPACA_API_KEY`.
3. **An account that holds none of the six.** Each bot treats any share of its
   ticker in the account as its own position. Shares held for other reasons
   will stop it at startup.
4. **One question for Alpaca.** The small-account rules were looked up on
   2026-11-17 (`DECISIONS.md`): the pattern-day-trader rule is gone, an
   account under $2,000 is a margin account at 1x with no shorting, and a buy
   and a sell on the same day does not restrict it. Not found in so many
   words: whether good-faith violations can arise on such an account. Ask
   Alpaca, or read it off the live account's settings, before funding.
5. **Enough rehearsal fills** to believe the cost per side, and a decision on
   what cost would call the pilot off. The rehearsal runs at $100 a trade;
   fills at $16 have not been looked at.
6. **The terms left open** in the pilot entry: what counts as a bot fault,
   and whether a stage's 20 trades count by entry or by exit.

Not verified by anything in this repository: any order on the live endpoint,
a real-money fill, a partial fill from Alpaca, an order rejected for
day-trading, and `live_bot.py` or `close_position.py --live` run for real.
They are tested against a fake broker only. The dashboard panel has been
drawn by its own script in a test and not looked at in a browser.
