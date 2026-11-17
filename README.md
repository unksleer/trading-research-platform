<img src="ai_platform/docs/logo/mark.svg" alt="" width="72" align="left">

# Trading Research Platform

A paper-trading research platform for US stocks. Twelve bots run an RSI mean-reversion strategy on Alpaca paper under a sealed registration: the hypothesis, parameters, success criteria and stopping rule are written down before the run, a change mid-run voids it, and results are judged on effective trades against buy-and-hold. The decision log ([`DECISIONS.md`](DECISIONS.md)) records what was measured and what was not.

A gen AI layer in [`ai_platform/`](ai_platform/) answers questions about the ledgers and the notes and proposes parameter changes a person confirms by hand: a model gateway, hybrid retrieval, a three-tool agent and a 50-question evaluation, with the measured write-up at [`ai_platform/docs/prototype-writeup.md`](ai_platform/docs/prototype-writeup.md).

Automated crypto trading was retired in October 2026 after four months with no evidence of an edge; that history, and the Coinbase tooling it used, stays in the log and in the code. Sections below that describe crypto bots describe the retired track.

---

## 🏗️ Architecture

[`utils/venue.py`](file:///home/leeunks/coinbase-trading-bot/utils/venue.py) is the
boundary between shared logic and exchange specifics. Everything above it is
common to both markets; only four things differ below it.

| Shared | Venue-specific |
| :--- | :--- |
| Position accounting, stops, trailing | Order submission |
| Risk limits and cooldowns | Response parsing |
| Atomic state with backup | Fee rate |
| Order journal and reconciliation | Market hours |
| Graduation criteria | |

A new venue means a new adapter, not a new bot. Per-asset variation lives in
`.env` via coin/ticker → profile → base resolution; safety machinery does not
vary per asset.

## 🛡️ Safety & Concurrency Safeguards

This bot is engineered with strict production safety safeguards to protect capital and state integrity:

1. **Dry-Run / Live-Mode Isolation**: 
   * **State Separation**: Live bots write to `state_<pair>.json` while simulated bots write to `state_<pair>_dry.json`. There is zero overlap.
   * **Log Separation**: Transactions are routed to isolated files: live trades use `trades.csv` / `completed_trades.csv`, while simulations use `trades_dry.csv` / `completed_trades_dry.csv`.
2. **Durable Order Journal**: Logs every trade intent with a generated UUID client-order ID *before* submitting it to Coinbase. Unresolved orders (from sudden crashes/reboots) are reconciled against the exchange on startup and continuously during the execution loop.
3. **Atomic Persistence & Backups**: State saves write to a temporary `.tmp` file, flush/sync to disk using `os.fsync`, and atomically swap to the main destination. Maintains a `.bak` backup file to recover from write failures.
4. **Concurrency Locking**: Utilizes a hybrid OS-level file lock (`fcntl.flock`) and thread lock (`threading.RLock`) to prevent multiple bot processes or CLI tools from mutating the same state file simultaneously.
5. **Fail-Closed Design**: In live mode, any corrupt state parser errors or schema validation mismatches will halt execution and fail-closed immediately rather than silently resetting holdings.
6. **Risk Circuit Breakers**:
   * **Stale Data Cutoff**: Stops trading if market data is older than 5 minutes.
   * **API Error Circuit Breaker**: Exits and halts trading if repeated Coinbase connection failures occur (default limit: 5).
   * **Consecutive Loss Cooldown**: Halts buying if consecutive transactions resulted in losses within a set cooldown window.
   * **Capped Exposure**: Enforces strict limit checks on order value and total product exposure.

---

### Local candle store

The exchange caps a response at ~2000 candles, and that cap flatters results:
the same strategy measured 1.71% gross edge over 83 days, 1.48% over 100 and
1.22% over 500. (Those were first compared against a 1.206% fee assumption,
since corrected to 0.80% maker; the point — that the shorter the window, the
better a strategy looks — does not depend on the fee.) `market_data/` appends each
**closed** candle to a local store, accumulating history the API will not
serve.

```bash
.venv/bin/python -m market_data.coinbase_candle_collector            # hourly, via pm2
.venv/bin/python -m market_data.coinbase_candle_collector --backfill # full API window
.venv/bin/python -m market_data.coinbase_candle_collector --report   # integrity check
```

It never stores a candle still forming — a partial high/low/close is revised
later, so a backtest built on one reads prices no trader could have acted on,
and it errs optimistically every time. Duplicates are ignored, so overlapping
runs are safe. A venue returning different values for a stored timestamp is
recorded as a conflict rather than applied. Gaps are reported, never repaired.

**The store is research infrastructure and no bot reads from it** — a test
asserts neither bot imports `market_data`. Wiring it into a trading path would
turn a stale store into a trading fault.

### Measurement discipline

Three months of tuning produced 56 paper trades and no statement about whether
anything works. The bottleneck was never the strategy — it was that the system
could not tell truth from noise. These exist to fix that, and
[`DECISIONS.md`](file:///home/leeunks/coinbase-trading-bot/DECISIONS.md)
records every change, its reasoning, and the entries that turned out wrong.

| module | question |
| :--- | :--- |
| [`utils/benchmark.py`](file:///home/leeunks/coinbase-trading-bot/utils/benchmark.py) | Does this beat **not trading**? Buy-and-hold is a graduation criterion, not a footnote — the crypto strategy lost to holding on 5 of 7 coins while passing a positive-P&L check. |
| [`utils/evidence.py`](file:///home/leeunks/coinbase-trading-bot/utils/evidence.py) | How much of a trade count is **independent**? 12 stock tickers measure as 4.9 effective symbols; crypto's 9 coins as 1.4. Pooled counts overstate evidence 2.4–6x. |
| [`utils/experiment.py`](file:///home/leeunks/coinbase-trading-bot/utils/experiment.py) | Were the criteria fixed **before** the result? Registrations are sealed; a conclusion graded against altered terms is labelled as such. |
| [`walkforward.py`](file:///home/leeunks/coinbase-trading-bot/walkforward.py) | Does it hold across **many** windows? One 60/40 split is one draw. Also reports parameter churn — an unstable fit is tracking noise. |
| [`analyze_correlation.py`](file:///home/leeunks/coinbase-trading-bot/analyze_correlation.py) | How many independent bets does the fleet hold? Cached to `logs/correlations.json`. |

```bash
.venv/bin/python walkforward.py --market stocks
.venv/bin/python analyze_correlation.py
```

**The sample-size formula that matters:** `n ≈ (1.96 / per-trade Sharpe)²`. At
the gate's 0.35 threshold that is ~31 trades; at the measured 0.074 it is ~700.
*The goal is a higher per-trade Sharpe, not more trades.*

> **The graduation gate does not establish an edge.** Per-trade noise is 13x
> the effect size, so a 20-trade sample carries a ±$0.20 band around a $0.033
> effect and a ±22 point band on win rate. Passing means "not visibly broken",
> not "profitable". This is documented at the top of `utils/graduation.py`
> rather than hidden behind a passing score.

### Bot identity

Each bot asserts, before touching state or the market, that its pm2 process
name matches the instrument it resolved. pm2 sets `name` in the process
environment and no restart overwrites it, so it is the one piece of identity a
bad restart cannot corrupt (`utils/identity.py`).

This exists because the failure it catches is silent. When eight crypto bots
were pointed at `BTC-USDC`, every one started cleanly, logged healthy, polled a
real market and wrote a state file — the same file. The only symptom was
per-coin trade files that stopped growing, which on six-hour candles is
indistinguishable from a quiet market.

`registry.audit()` covers the case the startup guard cannot — bots already
running when identity drifts — and also reports bots sharing a symbol, and so a
state file. It surfaces on the dashboard as a banner and leads the nightly
digest, whose subject line changes when something is wrong.

## 🚀 Key Features

* **Multi-Asset Live Bots**: Run isolated trading bots for multiple coins (e.g., BTC, ETH, SOL) concurrently.
* **Instant Trade Shortcut**: Launch live trading bots for any cryptocurrency instantly with a single command using the [`trade.sh`](file:///home/leeunks/coinbase-trading-bot/trade.sh) script.
* **Coin-Specific Overrides**: Finetune trading settings per asset directly in [.env](file:///home/leeunks/coinbase-trading-bot/.env) (e.g. `SOL_SMA_SHORT_WINDOW=12`).
* **ATR-Based Risk Management**: Set volatility-adapted stops (e.g., 3.0x ATR Stop Loss / 6.0x ATR Take Profit) instead of static percentages.
* **Stock & Crypto Screeners**: Run screeners for both crypto pairs ([`scanner.py`](file:///home/leeunks/coinbase-trading-bot/scanner.py), hourly under PM2 cron) and stocks ([`stock_scanner.py`](file:///home/leeunks/coinbase-trading-bot/stock_scanner.py)).
* **Email PnL Statements**: Integrated daily HTML report ([`daily_pnl_report.py`](file:///home/leeunks/coinbase-trading-bot/daily_pnl_report.py)) summarizes realized and unrealized performance for all online bots.
* **Full Signal Audit Trail**: Every candle decision — accepted, or rejected with the reason — is written to `logs/signal_log_<pair>.csv`. Filters that block good setups are invisible in the trade ledger; this is where they show up.
* **Edge Analysis Dashboard**: Separates gross edge from fee drag, breaks exits down by reason, and measures how many entries ever travelled far enough to cover the round trip. See [Dashboard](#-dashboard) below.
* **Entry Quality Tooling**: [`analyze_entries.py`](file:///home/leeunks/coinbase-trading-bot/analyze_entries.py) reports which entry conditions produce follow-through against the measured fee floor, with a per-pair breakdown so a result carried by one lucky coin is visible as such.

## 🧠 Auto-Learner Architecture (`auto_learner.py`)

A core component of this system is the nightly auto-learner. Instead of guessing parameters, the bot uses a 4-phase data-driven loop to adapt to market conditions:

1. **Diagnose**: Reads the actual sim trade history (`completed_trades_*_dry.csv`) and classifies a specific failure mode (e.g., `WHIPSAW`, `SL_TOO_TIGHT`, `TP_TOO_LOOSE`).
2. **Adapt**: Adjusts the grid search parameter bounds specifically to fix the diagnosed failure mode (e.g., searching for much longer SMA windows if whipsawing). It skips any parameter combinations that historically failed.
3. **Decide**: Backtests candidates across two unseen validation folds and records an evidence-backed recommendation. Under the default `LEARNER_MODE=ADVISORY` it **cannot** edit `.env` or restart bots — see the review workflow below.
4. **Graduate**: Evaluates sim coins against the five criteria in [`utils/graduation.py`](file:///home/leeunks/coinbase-trading-bot/utils/graduation.py) — ≥20 trades, win rate ≥55%, net P&L > $0, worst trade ≥ −$2.50, and per-trade Sharpe ≥ 0.35. Every criterion must pass; the weighted score out of 100 is for display only.

### Backtest fidelity

The learner's verdicts are only meaningful if it simulates the strategy the bot
actually trades. `quick_backtest` applies the bot's full BUY filter chain —
separation floor and ceiling, RSI band, EMA trend — in the same order and with
the same RSI maths as [`strategies/simple_moving_average.py`](file:///home/leeunks/coinbase-trading-bot/strategies/simple_moving_average.py).
Exit and filter settings are read from `.env` through the same
coin → profile → base resolution the bot uses, and logged on every run:

```
Exit regime from .env: trailing 1.5% (arms at +1.5%)
Entry filters from .env: RSI 30.0-55.0 (p14)
```

A parity test drives identical price data through both the live strategy and the
backtest filter and asserts they agree on every crossover candle, so the two
cannot drift apart silently.

When entry filters block nearly every crossover, the learner says so directly
rather than reporting an empty result:

```
All 480 combos produced <5 trades in the training window. The entry filters
(sep>=0.25%, RSI 40.0-55.0 (p14), price>EMA200) are blocking nearly every
crossover, so no parameter set can be evaluated.
```

---

## 🛠️ Usage Instructions

### 1. Launching Trading Bots (`trade.sh` Shortcut)
The helper script runs in **Dry-Run (Simulation) by default**. To launch a live bot, you must pass the `--live` flag and type the explicit acknowledgement:

```bash
# Start a simulated dry-run BTC-USDC bot
./trade.sh btc 10

# Start a live, real-money BTC-USDC bot (requires typing: I_CONFIRM_LIVE_TRADING)
./trade.sh btc 50 --live
```

### 2. Monitoring Bots (PM2 Commands)
```bash
pm2 status             # Check active bots
pm2 logs               # View live logs
pm2 logs btc-bot       # View live logs for specific bot
pm2 delete btc-bot     # Stop and remove specific bot
```

**Restart with `restart_bots.py`, not `pm2 restart`:**

```bash
.venv/bin/python restart_bots.py --check     # report identity drift, change nothing
.venv/bin/python restart_bots.py             # all bots
.venv/bin/python restart_bots.py --crypto    # or --stocks, or named bots
```

`pm2 restart <name> --update-env` copies the current shell environment into the
process. Run it from a shell that has `.env` loaded and every bot inherits
`.env`'s single `TRADING_PAIR`: on 2026-08-27 that put eight crypto bots on
`BTC-USDC` within one second, all writing the same state file, with no error
raised anywhere. `restart_bots.py` restates each bot's identity and verifies it
afterwards.

`--update-env` is also no longer needed for its original purpose.
`utils/env_loader.py` re-reads `.env` at startup with `override=True`, so a
plain restart already picks up tuning changes — **`.env` wins for tuning, the
command line wins for identity.**

`restart_bots.py` handles `bot.py` and `stock_bot.py` processes only. A stock
bot that sends real orders runs a different script: `broker_paper_bot.py` for
Alpaca's paper account, `live_bot.py` for real money (built, not authorised,
never run). Neither is touched by `restart_bots.py --stocks`, and on the
dashboard they are in a panel of their own, never among the simulated bots'
figures. `stock_bot.py` itself only simulates: it refuses to start with
`ALPACA_PAPER=False`. Starting, checking, closing by hand (`close_position.py`)
and stopping one is in [`live_trading_stocks.md`](live_trading_stocks.md).

### 3. Manually Closing Positions (`manual_sell.py`)
Close an open position manually under lock safety. Targets dry-run files by default or via argument overrides:

```bash
# List all active open positions
.venv/bin/python manual_sell.py

# Close simulated BTC position manually
.venv/bin/python manual_sell.py btc --dry

# Close live BTC position manually
.venv/bin/python manual_sell.py btc --live
```

### 4. Viewing Performance Analytics
```bash
# Display performance analytics for simulated dry-run trades
.venv/bin/python view_analytics.py --dry

# Display performance analytics for live production trades
.venv/bin/python view_analytics.py
```

### 5. Sim Performance Report (`sim_report.py`)

```bash
.venv/bin/python sim_report.py              # terminal (plain text)
.venv/bin/python sim_report.py --coin LINK  # one coin
.venv/bin/python sim_report.py --html       # the emailed HTML body
```

Summary-first: portfolio gross/fees/net with a one-line diagnosis of *which*
problem it is, a readiness leaderboard ranked by graduation score, then per-coin
detail in the same order. The nightly learner emails this as
`multipart/alternative` — HTML with the plain-text version as fallback.

### 6. Entry Quality Analysis (`analyze_entries.py`)

Reports which entry conditions actually produce follow-through. Because every
round trip costs a fixed percentage in fees, an entry whose price never travels
further than that fee is a guaranteed loss regardless of how the exit is tuned.

```bash
.venv/bin/python analyze_entries.py

# Evaluate a different candidate filter
.venv/bin/python analyze_entries.py --rsi-low 45 --rsi-high 60 --max-sma-sep 0.15
```

Buckets entries by RSI and crossover separation, shows the share that cleared
the fee floor, and breaks a candidate filter down per pair — a filter that looks
profitable overall but is carried by one lucky coin is not a filter. It flags
its own sample size when a result rests on too few trades to trust.

### 7. Stock Bots (`add_stock.py`)

Stock trades on Alpaca are **commission-free**, so the ~1.2% round-trip fee that
dominates every crypto result is absent. Results are not transferable between
the two markets.

```bash
.venv/bin/python add_stock.py --list          # registered tickers vs pm2
.venv/bin/python add_stock.py NVDA --check    # validate + backtest, change nothing
.venv/bin/python add_stock.py NVDA            # register and start
.venv/bin/python add_stock.py NVDA --amount 25
.venv/bin/python add_stock.py NVDA --remove   # stop and deregister
```

Every check runs before anything changes: that Alpaca will accept orders for the
symbol, that enough history exists for the indicators, and a backtest of the
configured strategy on that symbol against buy-and-hold. Registration starts the
pm2 process, adds the ticker to `STOCK_WATCHLIST` and runs `pm2 save`.

**Strategy selection.** `stock_bot.py` runs `STOCK_STRATEGY` (or
`<TICKER>_STRATEGY`), one of:

| value | entry | exit |
| :--- | :--- | :--- |
| `SMA_CROSSOVER` *(default)* | bullish SMA cross, RSI inside band | bearish SMA cross |
| `RSI_MEAN_REVERSION` | RSI crosses **up** through `STOCK_RSI_OVERSOLD` | RSI crosses **down** through `STOCK_RSI_OVERBOUGHT` |

Stops, targets, trailing stop and risk limits are shared, so the two differ only
in entry and strategy exit. An unrecognised value refuses to start rather than
falling back silently.

**Market trend gate (stocks v5).** No new position is opened while SPY's close
on the last completed session is below the average of its last 50 completed
session closes. It applies to every stock bot, SPY included, and to entries
only: stops, targets and every other exit work as before. The state is worked
out once a day from Alpaca's daily bars and logged as `Trend gate: ...`; a
vetoed entry is logged as `Entry blocked` and recorded in the signal log with
`blocked_by` `TREND_GATE`. If the closes cannot be fetched the state is
unknown and entries are refused (`TREND_GATE_UNKNOWN`). 50 and SPY are the
registered v5 terms and the defaults in code (`STOCK_TREND_GATE_DAYS`,
`STOCK_TREND_GATE_SYMBOL`); changing either, or setting days to 0, voids the
registration. `utils/market_gate.py` holds the rule and the reasons.

**A stuck bot ends itself.** `pm2 status` saying "online" does not mean a bot
is working: two stock bots sat blocked in a network read for a week in
November 2026 and pm2 showed them online throughout. Two things now prevent
that. Every Alpaca request has a timeout (`utils/alpaca_http.py`, 10 seconds
to connect and 30 seconds to read, `ALPACA_CONNECT_TIMEOUT_SEC` and
`ALPACA_READ_TIMEOUT_SEC`), so a dead connection raises and the loop retries
on its next tick. And a watchdog (`utils/watchdog.py`) exits the process with
code 70 if the loop has not completed 600 seconds after its last announced
sleep (`STOCK_WATCHDOG_TIMEOUT_SEC`, 0 to switch off), logging `WATCHDOG:` and
where the loop was stuck. pm2 restarts a bot that exits only if it was started
with autorestart on; one started with `--no-autorestart` stays stopped. To
check health directly, compare the modification time of `logs/stock_<ticker>.log`
with the clock: a working bot writes at least every 30 minutes, every minute
while the market is open.

Measured across 15 symbols out-of-sample, mean reversion was positive on both
hourly and daily bars at every threshold tested (66–75% win rate) against
crossover's 35–44%. Commission-free execution is why: it takes many small moves
that a 1.2% fee would erase.

**Nightly learning.** [`stock_learner.py`](file:///home/leeunks/coinbase-trading-bot/stock_learner.py)
evaluates every watchlist ticker across both strategy classes, requires the
winner to beat buy-and-hold and to be corroborated by its neighbouring settings,
and is advisory only — it never edits `.env`. It runs as part of the nightly
learner and its output is included in the emailed report.

```bash
.venv/bin/python stock_learner.py
.venv/bin/python stock_learner.py --ticker NVDA --timeframe Day
```

Compare strategy classes across the watchlist with:

```bash
.venv/bin/python compare_strategies.py --market stocks --granularity Hour
.venv/bin/python compare_strategies.py --market stocks --granularity Day --lookback-days 1800
```

### 7b. Crypto Bots (`add_crypto.py`)

The crypto counterpart to `add_stock.py`. Dry-run only — live trading stays
behind `trade.sh` and its typed confirmation.

```bash
.venv/bin/python add_crypto.py --list         # running pairs vs pm2
.venv/bin/python add_crypto.py FIL --check    # validate + backtest, change nothing
.venv/bin/python add_crypto.py FIL            # register and start
.venv/bin/python add_crypto.py FIL --remove
```

Settings come from the coins **actually running**, not from the `SIM` profile.
The nine existing coins each carry per-coin overrides, so a new coin taking
profile defaults would get the `SIM` profile's SMA 5/30 against the fleet's
10/40 — quietly a different experiment, whose results would not be comparable
with the rest. The backtest prints where its settings came from, and
says so if the fleet has drifted apart.

### 8. Candidate Screening (`screen_candidates.py`)

Ranks symbols by whether they **suit the strategy**, not by recent returns.
Mean reversion needs a symbol to reach oversold *and then recover*; one that
dips repeatedly without recovering is a downtrend, and the strategy will buy it
all the way down. That profile scores well on entry frequency and is exactly the
failure mode, so it is called out explicitly rather than ranked highly.

```bash
.venv/bin/python screen_candidates.py --market stocks --json
.venv/bin/python screen_candidates.py --market crypto --json
.venv/bin/python screen_candidates.py --market stocks --universe AAPL,MSFT
```

Each market is screened under its own cost model — equities commission-free,
Coinbase at 0.80% round trip (0.40% maker per side) — and results never transfer
between them. Both
run nightly under PM2 cron and appear on the dashboard.

Verdicts: `check` clears every screen · `weak` marginal · `skip` too few entries
· `avoid` dips without recovering.

### 9. Scheduled Jobs (PM2 cron)

Both run once per firing and then stop; `--no-autorestart` is required or PM2
will treat the exit as a crash and restart them in a loop.

```bash
# Nightly learner (04:00)
pm2 start auto_learner.py --name learner --interpreter .venv/bin/python \
    --cron "0 4 * * *" --no-autorestart

# Hourly market screener (:05 past the hour)
pm2 start scanner.py --name scanner --interpreter .venv/bin/python \
    --cron "5 * * * *" --no-autorestart

# Nightly candidate screens
pm2 start screen_candidates.py --name screen-stocks --interpreter .venv/bin/python \
    --cron "20 5 * * *" --no-autorestart -- --market stocks --json
pm2 start screen_candidates.py --name screen-crypto --interpreter .venv/bin/python \
    --cron "40 5 * * *" --no-autorestart -- --market crypto --json

pm2 save    # persist across reboot
```

The screener writes `logs/market_metrics.json`, which backs the dashboard's
Screener Scoreboard. The dashboard warns if that file goes more than three hours
stale, since that means the job stopped.

### Learner V2 review workflow

The nightly learner defaults to `LEARNER_MODE=ADVISORY`. It can analyze and
email recommendations, but it cannot edit `.env` or restart bots.

```bash
# List evidence-backed recommendations
.venv/bin/python learner_review.py

# Approve one exact recommendation for a later paper-only learner run
.venv/bin/python learner_review.py --approve RECOMMENDATION_ID
```

Applying approvals additionally requires `LEARNER_MODE=APPLY_APPROVED`.
Approvals never enable live trading and do not bypass the normal graduation
criteria.

---

## 📊 Dashboard

`pm2 start dashboard.py` serves on port 8080. Beyond live positions and process
status, it answers whether the strategy is working — as opposed to what it is
doing right now:

| Panel | What it answers |
| :--- | :--- |
| **Where the Money Goes** | Gross edge − fees = net, with the measured per-trade fee floor. A strategy can pick direction well and still lose if the round trip costs more than the move it captures; shown as separate cards that subtraction is left to the reader. |
| **Cumulative Net P&L** | The only view with a time axis. Mark `.env` changes against it to see whether a change helped. |
| **Exits by Reason** | Count and average net per exit path. Warns when one reason dominates and loses. |
| **Entry Follow-Through** | How many entries ever moved far enough to cover the round trip, against the fee floor. |
| **Signal Funnel** | Crossovers seen → blocked by which filter → entries taken. An over-tight filter is invisible in the trade ledger, where it looks identical to a quiet market. |
| **Fleet Problems** | Hidden unless something is wrong. Bots not matching their name, bots sharing a state file, bots not online — the failures that show up nowhere else because they present as an absence of trades. |
| **Go-Live Readiness** | Per-coin progress against all five graduation criteria, closest first. Evaluated by `utils/graduation.py` — the same code the nightly report renders and the promotion gate enforces, so one coin cannot show two readiness figures. |

### Bot signal states

The dashboard carries this same table as a **"What do these states mean?"**
legend under the signal panel, so it can be read without leaving the page.

| state | meaning |
| :--- | :--- |
| `IN TRADE` | holding a position |
| `ENTERING` | the entry condition fired this candle and passed every filter |
| `BLOCKED` | the entry condition fired and a filter rejected it — the filter is named |
| `NO CROSS` | crossover strategy: short SMA already above long, so the crossing has passed |
| `NO SETUP` | mean reversion: RSI has not crossed up through oversold |
| `BELOW` | crossover strategy: short SMA under long, no setup forming |
| `CLOSED` | stock bot outside market hours — not evaluating at all |

States describe what the bot is doing, not how likely a trade is. The crossover
strategy enters on the crossing itself, a single candle, so a pair already above
its long SMA has **missed** the entry rather than approached one. The previous
label for that was `CLOSE`, which read as either "close the position" or "close
to triggering" and meant neither.

`NO CROSS` and `BELOW` describe SMA geometry and are never shown for a
mean-reversion bot, which triggers on RSI instead.

### Price provenance

Position P&L is only as trustworthy as the price behind it. Prices resolve
**live ticker → the bot's last closed candle → entry price**, and every price
carries its source and age. Non-live prices are badged, and P&L derived from a
stale price renders grey rather than red or green, so it is never mistaken for a
confirmed gain or loss.

This matters: prices previously came from the screener file, which had gone 34
days without an update. An open LINK position was reported at a stale $8.68
against a live $11.51 — a $2.56 loss that did not exist. Coins missing from that
file fell back to entry price and showed exactly $0.00 unrealized, which reads
as a real value rather than a missing one.

---

## ⚙️ Configuration (`.env` Parameters)

Edit [`.env`](file:///home/leeunks/coinbase-trading-bot/.env) to configure settings. Major safety settings include:

```ini
# --- Global Safety Configs ---
DRY_RUN=True                          # Default is True. Set to False for live trading.
EMERGENCY_KILL_SWITCH=False           # Set to True to instantly disable bot executions.
APPROVED_PRODUCT_ALLOWLIST=BTC-USDC,ETH-USDC,SOL-USDC   # List of allowed pairs.

# --- Risk Limits ---
MAX_VAL_PER_ORDER=100.0               # Maximum USD value allowed per order.
MAX_EXPOSURE_PER_PRODUCT=500.0        # Maximum exposure allowed per pair.
MIN_QUOTE_RESERVE=10.0                # Minimum cash to retain.
MAX_TRADES_PER_DAY=10                 # Maximum daily buy/sell cycles.
CONSECUTIVE_LOSS_COOLDOWN_TRADES=3    # Limit on consecutive losses before cooldown.
CONSECUTIVE_LOSS_COOLDOWN_SECONDS=3600 # Loss cooldown duration in seconds.
STALE_MARKET_DATA_CUTOFF_SECONDS=300  # Cutoff age for stale market candles.
REPEATED_API_ERROR_LIMIT=5            # Error limit before circuit breaker trips.
```

Strategy parameters — SMA windows, the RSI band, separation bounds, stops and
the trailing stop — are documented per profile in
[`trading_profiles.md`](file:///home/leeunks/coinbase-trading-bot/trading_profiles.md),
along with why the fee floor drives several of those values.

> **Removed:** `MIN_BULLISH_MARKET_RATIO` gated buys on a market-breadth ratio
> read from `logs/market_metrics.json`. That file had gone 34 days without an
> update, pinning the ratio at `1.0` against a `0.35` threshold, so the gate had
> never blocked a single trade. It was removed rather than left implying a
> protection that was absent. The scanner now runs hourly (see §6 above); if you
> want breadth gating back, restore it with a staleness check that fails closed.
