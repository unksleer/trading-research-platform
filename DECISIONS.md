# Decision log

Every change, the reason for it, and what the numbers actually said — including
where earlier entries in this file were wrong. Newest first.

The purpose is not a changelog. It is to stop the same ground being re-covered:
several decisions here reversed earlier ones, and in at least two cases the
reversal happened because a claim was checked rather than repeated.

**Conventions.** A claim with no interval attached is a point estimate and
should be read as one. "Measured" means from live trades; "backtested" means
from historical simulation, which is weaker. Effective trades ≠ pooled trades.

**Entries are not rewritten.** Each records what was believed and measured at
the time, including figures later shown to be wrong — the 1.206% fee used
before 2026-09-02, for instance. A later entry corrects; the earlier one
stands, because a log that edits its past cannot be audited. Reference
documents (README, trading_profiles) are kept current instead.

---

## 2026-10-26 — Server rebooted for a kernel update; Mac lost local-network access

**What happened:** `dev-server` rebooted itself at 11:56:41 for an automatic
kernel update (5.15.0-198) after 74 days up. pm2 resurrected the saved
process list: dashboard and 12 stock bots online, the four cron jobs
(observer, backup, candle-collector, screen-stocks) stopped between runs as
normal. Static IP, sshd and ufw unchanged. No bot restarts since.

**Separate problem found while checking:** the Mac (`MiniLee`) could neither
ping nor SSH to the server ("No route to host"), although this Claude session,
an SSH connection from the same Mac accepted at 12:20:57, kept working and
was the only established session. Zero new packets from the Mac reached the
server's NIC. Cause was on the Mac: a macOS upgrade reset the per-app
**Local Network** privacy permission for Terminal. Re-enabling it in System
Settings → Privacy & Security → Local Network fixed SSH immediately. Nothing
on the server was changed.

**Lesson:** an established connection surviving while new ones fail points at
a per-app or stateful filter on the client, not at the server. Check the
client's permission settings before touching the server's firewall.

---

## 2026-10-14 — Candidate Screens: stocks only

**Asked:** remove crypto from the Candidate Screens panel, the one piece
left out of the morning's cleanup. `load_screens` now reads
`screen_stocks.json` only; a leftover `screen_crypto.json` is ignored (and
the one on disk is archived). The panel renders a single column when one
market is present. 1 test added. Served: `screens markets served: ['stocks']`.
Suite: 511 passed in 7.89s.

## 2026-10-14 — Dashboard: every crypto reference removed

**Asked:** "clean up all the crypto references on the dashboard." Done the
same day as the retirement.

**Removed from the page.** The fee waterfall ("Where the Money Goes") and
Entry Follow-Through — both existed to expose crypto's fee drag and needed
excursion data the stock ledger does not carry. The Signal Funnel (SMA
crossovers seen vs taken). The Multi-Asset Screener Scoreboard (the scanner,
deleted from pm2 today). The Auto-Learner panel (the learner, likewise).
The crypto row of the cumulative P&L chart. The SMA Short / SMA Long /
Spread columns of the signal table, and the NO CROSS and BELOW states with
their legend entries — all crossover-bot vocabulary. "all markets" scope
labels on the headline cards. "Coin"/"Pair" column headers → "Symbol".
Title: "Coinbase Systematic Trading Dashboard" → "Systematic Trading
Dashboard". "P&L by Market" → "Registration P&L".

**Removed from the server.** `build_signal_funnel`, the scanner and
learner report loaders, and the `scanner`, `scanner_age_seconds`,
`signal_funnel`, `auto_learner_report` keys. `build_analytics` is scoped to
simulated stock trades and now serves only exits by reason, per-symbol
readiness and the pooled gate; `waterfall`, `fee_floor_pct`,
`entry_quality` and `equity_curve` are gone rather than empty, so no
renderer can draw a blank panel for them. `build_pnl_by_market` and
`build_pooled_graduation` read stock ledgers only.

**Kept.** The hidden Candidate Screens panel (the stock screener still
runs). `bot.py`'s own signal states in the server, unused. CSS class names
with "coin" in them: not user-visible, and renaming them is churn.

**Verification (pasted):**

```
top-level keys: ['active_positions', 'analytics', 'bots', 'completed_trades', 'fleet_problems', 'observer', 'performance', 'pnl_by_market', 'screens', 'timestamp']
retired keys absent: True
analytics keys: ['exit_reasons', 'graduation', 'pooled_graduation', 'trade_count'] | stock trades: 37 | exit reasons: [('RSI fell back through 65', 23), ('Stop Loss Triggered', 8), ('SMA Bearish Cross', 3), ('Trailing Stop (peak=$114.7600, trail=1.5%)', 1), ('Stop Loss', 1), ('Trailing Stop (peak=$106.5600, trail=1.5%)', 1)]
pnl_by_market markets: ['stocks'] | curve points: 29
pooled graduation markets: ['stocks']
states: ['IN TRADE', 'NO SETUP'] | rows: 12
```

The page's script was checked for parse errors and for calls to removed
functions after each pass; one pass had spliced a block twice (a cut whose
end anchor matched before its start) and was redone from the committed
file rather than patched.

**Tests:** the analytics suite rewritten for stocks (fee-floor, waterfall,
entry-quality, equity-curve and funnel tests removed; a test now asserts the
retired keys are absent); P&L, pooled-graduation, equity-curve and legend
tests updated. Suite: 510 passed in 7.74s.

## 2026-10-14 — Automated crypto trading retired; the project is stocks-only

**Decision (owner's):** "automated crypto trading is not worth the effort
based on the last 4 months work with this … scrap that part of this project
and focus more on the stock." Raised once against it on 2026-10-10 (let the
sealed Donchian registration run to its 2027-01-15 stop, since paper costs
nothing); the owner reaffirmed. Done as decided.

**What the four months established**, so it does not get re-covered:
- Short-hold crypto strategies (SMA cross, RSI mean reversion, hourly and
  six-hour) cannot clear the 0.8% round trip. Many trades, settled.
- The Donchian 80/40 trend design cleared fees but gave back 71–100% of
  peak on every closed trade, and at the stop carried −$66.00 unrealised on
  six open positions after the 2026-10-08 drop, against +$8.53 realised.
- Nine coins behaved as about 1.3 independent instruments, so 20 effective
  trades was most of a year away. Crypto was one bet on market direction
  taken nine times.
- On this venue, at these fees, with these instruments, no automated
  design produced evidence of an edge. The Donchian registration's own
  verdict is unknown (0 effective trades) and is recorded as unknown, not
  as a failure.

**Positions at the stop, marked to market, never closed** (closing paper
positions would record trades nobody took; the state files hold them):

```
ADA-USDC     entry 0.2448    now 0.2280    since 2026-09-22  unrealised   -7.22
  BTC-USDC     entry 86930.3200 now 81944.9200 since 2026-09-21  unrealised   -6.11
  ETH-USDC     entry 2787.9500 now 2428.0700 since 2026-09-21  unrealised  -13.26
  NEAR-USDC    entry 5.7072    now 4.9413    since 2026-10-11  unrealised  -13.77
  SOL-USDC     entry 118.5800  now 104.0900  since 2026-09-21  unrealised  -12.57
  XRP-USDC     entry 1.5289    now 1.3344    since 2026-09-21  unrealised  -13.07
  total unrealised on open crypto positions: -66.00
```

**Done:**
- `2026-09-crypto-donchian-breakout` concluded: stopped by owner, not a
  result, terms intact.
- Removed from pm2 and the saved list: the nine crypto bots, the learner
  (crypto-only), the crypto screener, the scanner. The Coinbase candle
  collector and `data/market_data.sqlite` are kept; data costs nothing.
- Runtime files archived to `archive/2026-10-crypto-retired/` (18 files +
  9 signal logs) with a README; committed, since the archive is un-ignored
  on purpose.
- Dashboard restarted and serving; the crypto column of P&L by Market now
  reads zero with no registration, which is true. Observer run clean.
  Fleet audit clean. Suite: 526 passed, 1 skipped in 7.89s (the skip is a test that
  needs a crypto ledger in the root).

```
remaining: ['backup', 'candle-collector', 'dashboard', 'dis-bot', 'hgtv-automation', 'jnj-bot', 'lpl-bot', 'meta-bot', 'observer', 'pg-bot', 'pm2-logrotate', 'qqq-bot', 'screen-stocks', 'slv-bot', 'spy-bot', 'tsla-bot', 'wmt-bot', 'xlp-bot', 'xlu-bot']
API ok; crypto panel: {'closed': 0, 'realized_usd': 0, 'open': 0} | stocks closed 29 | fleet: []
2026-10-14 14:30Z  0 stop · 0 warn · 2 info
```

**What remains.** Twelve stock bots on the mean-reversion v4 registration
(29 closed as of today, 9+ effective of 20, next review 2026-11-04), the
observer, the backup, log rotation, the stock screener. The roadmap of
2026-10-07 applies with the crypto track deleted. `bot.py`, the crypto
strategies and `add_crypto.py` stay in the repository, unused: deleting
working code to make a point is not a decision anyone needs reversed.

## 2026-10-10 — Why SUI "did so well": it didn't, particularly — and the ledger was mislabelling every crypto trade

**Asked:** the SUI-USDC card shows one trade, net +$7.14, and whether to dig
into why it did so well and log it.

**First, a check that turned into a finding.** The card's exit reason reads
"SMA Bearish Cross", on a registration that runs Donchian 80/40. Each bot's
`/proc` environment still carries `*_ACTIVE_PROFILE=SIM` from pm2's startup
snapshot, which looked for a moment like the August incident again. It is
not: `env_loader` loads `.env` over the snapshot at startup, every bot
resolves `BREAKOUT → DONCHIAN_BREAKOUT 80/40, SL 15, no trail`, each one's
startup log says `Strategy initialized: Donchian_Breakout_80_40`, the
signal log has no SMA values since the switch, and the SUI entry bar
(2026-09-21 18:00 close 1.0425) was a genuine 80-bar close-high breakout
(prior 80-bar close-high 1.0156) at which SMA 10/40 showed no cross at all.
The bots are running what is registered.

The label was the defect: `bot.py` recorded every entry as the literal
string "SMA Bullish Cross" and `utils/state.py` mapped every non-RSI
strategy exit to "SMA Bearish Cross", whatever strategy was running. All
four Donchian trades in the ledger carry SMA labels. **Fixed:** the state
manager now names entries and exits after the running strategy
(`Donchian_Breakout_80_40 entry` / `exit`), falling back to the old strings
only if no strategy was set. Existing ledger rows are not rewritten. Crypto
bots restarted through `restart_bots.py --crypto`; identity verified; the
five open positions survived the restart. 3 tests added. Suite: 527 passed in 7.69s.

```
All bots match their names.
sui: Donchian_Breakout_80_40
  near: Donchian_Breakout_80_40
  btc: Donchian_Breakout_80_40
  crypto open positions: 5 ['ADA-USDC', 'BTC-USDC', 'ETH-USDC', 'SOL-USDC', 'XRP-USDC']
```

**Now the actual question. All four closed Donchian trades, same window:**

```
pair         entry            exit             net%    mfe%    mae%   hold_d
  LINK-USDC    2026-09-25T06:00 2026-10-07T06:00  +1.08  +17.26   -0.96   12.0
  NEAR-USDC    2026-09-22T06:00 2026-10-08T18:22  +0.27  +25.66   -8.40   16.5
  RENDER-USDC  2026-09-21T20:40 2026-10-08T19:18  +0.06  +19.70   -7.42   16.9
  SUI-USDC     2026-09-22T00:00 2026-10-07T12:00  +7.14  +24.35   -9.83   15.5
```

SUI was not the one that worked. All four coins ran 17–26% above entry
after their breakouts — the whole market rallied in the last week of
September — and all four then gave most of it back waiting for a close
below the 40-bar low, which is what a Donchian exit does by design. SUI kept
7.1 points of its 24.4 because its exit bar came on 2026-10-07 06:00, before
the 2026-10-08 drop (SUI low 0.997 that day); NEAR and RENDER exited on the
8th, after the drop had eaten theirs. Same strategy, same rally, one day's
difference in when the channel broke. There is no "why SUI" to learn.

**What there is to learn, and it is about the exit, not the coin.** The
run's give-back from peak to realised is 71% (SUI), 94% (LINK), 99% (NEAR)
and 100% (RENDER). That is the cost of the rule that let the trade reach
+24% in the first place; a tighter exit would have kept more of these four
and cut off the trend the strategy exists to catch. The backtest that
registered 80/40 showed the same shape. This is recorded for the January
review, not acted on: the registration is sealed, and four trades say
nothing about whether the trade-off is right.

**SUI's own path, for the record** (entry 1.0389):

```
2026-09-22 00:00 o=1.0418 h=1.0821 l=0.9981 c=1.0201  low vs entry  -3.93%
  2026-09-23 12:00 o=1.0143 h=1.0181 l=0.9330 c=0.9686  low vs entry -10.19%
  2026-09-24 06:00 o=0.9623 h=0.9720 l=0.9356 c=0.9522  low vs entry  -9.94%
  2026-09-25 06:00 o=1.0169 h=1.1522 l=1.0059 c=1.1395  low vs entry  -3.18%
  2026-09-27 18:00 o=1.2512 h=1.2949 l=1.2461 c=1.2638  low vs entry +19.94%
```

The −10.2% low on 2026-09-23 is inside the 15% stop with room; a 10% stop
would have been hit at the exact low, two days before the +24% run. Same
lesson as the 2026-10-01 wick study: on six-hour crypto bars, stops near
5–10% get picked off.

**Against holding.** Over the registration window (2026-09-21 to today)
SUI went 1.0389 → 1.1149, +7.3%; the strategy realised +7.1% and is flat
now. No excess over simply holding, on one trade.

## 2026-10-07 — Housekeeping: log rotation, the 04:00 overlap, shell strings, a backup

Four items deferred from the Astra review and the roadmap, done in the quiet
stretch. None touches a strategy, a registration or a trading parameter.

**1. pm2 log rotation.** `~/.pm2/logs` had reached 1.1 GB with no rotation
(sol-bot alone 85 MB). `pm2-logrotate` installed and configured:

```
$ pm2 set pm2-logrotate:max_size 20M
$ pm2 set pm2-logrotate:retain 14
$ pm2 set pm2-logrotate:compress true
$ pm2 set pm2-logrotate:workerInterval 300
$ pm2 set pm2-logrotate:rotateInterval 0 3 * * *
```

**2. The 04:00 overlap.** Five crypto bots (render, link, sui, sol, xrp)
carry a legacy `0 4 * * *` cron restart that the other four do not, and
the learner ran at the same minute — reading live bot settings from
processes that were mid-restart. The intended fix was to drop the bots'
restart; pm2 7.0.3 did not honour `--cron-restart 0` on restart (the five
restarted, identity verified clean, cron unchanged). So the learner moved
to `30 4 * * *` instead, which removes the overlap without touching a
trading process again. The bots' daily restart remains, harmless and noted.

```
render-bot   0 4 * * *      online
  link-bot     0 4 * * *      online
  learner      30 4 * * *     stopped
  sui-bot      0 4 * * *      online
  sol-bot      0 4 * * *      online
  xrp-bot      0 4 * * *      online
All bots match their names.
```

**3. `shell=True` removed** from the four places that built a
`KEY=VALUE pm2 ...` shell string (`restart_bots.py`, `add_crypto.py`,
`add_stock.py`, `auto_learner.py`). Each now passes an argument list with
the identity in an explicit `env=`. Same semantics — the assignments still
override the caller's environment, which is what prevents the August
BTC incident — with no shell in between. A test parses every project
script and fails on any `shell=True`.

**4. A nightly backup.** GitHub was the only off-machine copy of the code
and refused writes all day; the evidence (ledgers, state, candle store,
registrations, observer records) is gitignored and existed in exactly one
place. `backup.py` writes a verified git bundle of every branch plus a
tarball of the evidence to `~/backups/coinbase-trading-bot/<date>/`, keeps
14 days, and runs under pm2 at 03:30. `.env` is deliberately excluded.
This is same-disk, so it covers deletion and corruption, not hardware loss;
an off-box copy is the next step.

```
backup /home/leeunks/backups/coinbase-trading-bot/2026-10-07: bundle 0.7 MB, 62 evidence files 2.3 MB, pruned none
backup: stopped 30 3 * * *
```

**Tests:** 4 added (`tests/test_housekeeping.py`). Suite: 524 passed in 7.97s.

**Not done:** the two early-close-day after-hours bars in the SPY store
(needs a market calendar); the GitHub push, still failing on GitHub's side
— this entry's commit is local until it clears.

## 2026-10-07 — Oct 4 review; First Candle Rule concluded and parked; observer hold threshold measured from the run

Three follow-ups from the Oct 4 review point, done together.

**1. The Oct 4 review of stocks v4: no rule fired, nothing changed.**
Status at review, scoped to the registration (since 2026-09-04): 23 closed,
17 wins avg +1.95%, 6 losses avg −5.05%, win rate 74%, profit factor 1.10,
realized +$8.17, 9 effective trades of the 20 the shape rules apply at. The
run was −$4.87 on 2026-09-30 and +$8.17 a week later on nine more closed
trades; that swing is the sample size, not the strategy. The trailing-stop
dead-zone finding (2026-09-29) stands: real, 26% of backtest stop-outs,
latching makes net worse, exits left alone. Next review point 2026-11-04;
the observer projects 20 effective trades around 2026-11-16.

**2. First Candle Rule v2 stopped by its own rule, concluded, bot parked.**
The observer emailed a stop on 2026-10-07 14:12Z: over 23 sessions the
rejection mix drifted (volume_below_threshold 39% live vs 59% backtest),
which the registration pre-committed to treat as "harness suspect, stop".
On inspection the pipeline reproduced the backtest — every session logged a
decision with a named reason, accept rate 1/23 = 4.3% against ~5% backtest,
one trade (2026-09-28, stop loss, net −$0.21), zero orders, zero production
files touched — and the drift is a quieter September than the two-year
average, absorbed by the no-breakout and EMA rejections. The registration
is concluded with that verdict (terms intact) and `fcr-spy` is removed from
pm2 and the saved process list. The strategy was always expected to fail
(backtest PF 0.30); the run existed to validate the harness, and did.
Correction to what was said in conversation the same day: the run placed
one trade, not zero.

```
status: concluded | concluded: 2026-10-07 | terms_intact: True
fcr-spy removed from pm2 and saved
fcr-spy still in pm2: False
active registrations: ['2026-09-crypto-donchian-breakout', '2026-09-stocks-mean-reversion-v4']
```

**3. Observer: the "held too long" threshold is now measured from the run.**
`EXPECTED_HOLD_DAYS["RSI_MEAN_REVERSION"]` was set to 5 before any run
existed. The run's winners go to 17 days, so the check kept flagging normal
holds (JNJ, WMT) as worth a look. `observer.expected_hold_days()` now uses
the 90th percentile of the registration's own closed holds once there are
ten or more (stocks today: n=23, median 8.2, p90 15.0, max 34.0 days), and
the constant only until then; the finding names which basis it used. Limit
is still 2× that. Crypto Donchian has 2 closed trades, so it stays on the
assumed 28 days. After the change the observer's run shows no held-too-long
finding; WMT at 12 days is inside 2 × 15.

```
=== observer findings after the run ===
  [info] 2026-09-crypto-donchian-breakout: Progress — 0 effective trades of 20 · stops 2027-01-15 · 2 pooled
  [info] 2026-09-stocks-mean-reversion-v4: Progress — 9 effective trades of 20 · 23 pooled · at this rate 20 effective trades ≈ 2026-11-16
  [info] 2026-09-stocks-mean-reversion-v4: Win/loss shape — 17 wins avg +1.95% · 6 losses avg -5.05% · win rate 74% · profit factor 1.10 · 23 pooled ≈ 9 effective · rules apply at 20 effective
```

**Tests:** 4 added to `tests/test_observer.py` (assumed until ten trades;
measured p90 not max; unparseable rows skipped; `run()` must pass the trades
in or the measurement is silently never used). Suite: 520 passed in 7.50s.

## 2026-10-01 — System Process Monitor: mode read from the process, bots picked by script

**Asked:** what the panel is for and whether it is accurate. It was accurate
for "is the process alive" and wrong in three ways: the Mode badge came from
pm2's startup environment snapshot (the same stale snapshot behind the
August identity incident) and never looked at `ALPACA_PAPER`, so every
stock bot's "Simulated" was the code's default rather than a check; the
filter took names ending in `-bot`, so `fcr-spy` — a running trading bot —
was missing while the dashboard itself was counted as a bot; and the
header said 22 bots when there were 21.

**Change.** `utils/process_mode.py`. Bots are picked by the script they run
(`bot.py`, `stock_bot.py`, `fcr_bot.py`), not by name. Mode is read from the
process's own environment under `/proc/<pid>/environ` — what the bot
actually read at startup — using the variable that governs that script, with
the crypto coin/profile override order mirrored from `config/settings.py`.
Absent or unreadable is reported as **Unknown**, in its own colour, never
defaulted to paper. Restart counts (lifetime and unstable) are in the row's
hover text, since the lifetime figure alone misleads (sol-bot 11,244, from a
crash loop months ago; zero unstable, up for hours).

**Verification (pasted):**

```
22 rows; names: ['fcr-spy'] | dashboard listed: False
modes: Counter({'Simulated': 22})
status: Counter({'ONLINE': 22})
```

Twenty-two rows is right: 21 "-bot" processes plus fcr-spy, and no
dashboard. All read paper from their own environment.

**Tests:** 6 added (`tests/test_process_monitor.py`), including one where
pm2's snapshot says live and the process says paper — the row must say
paper. Suite: 515 passed, 1 skipped.

**Still true.** Online is not the same as working. The fleet banner and the
observer's fleet check, which look at whether each bot's signal log is still
being written, remain the health signal; this panel is process liveness.

## 2026-10-01 — Stop-outs: wick hits or real reversals? (a study, not a change)

**Asked:** whether watching wicks is worth anything for learning. Answer
given: not as named patterns, yes as a measurement. The one measurement
worth taking now: of the stop-outs so far, how many were wick hits — the
price touched the stop and the bar closed back above it — and did the
price recover afterwards. Nothing in the bots, settings or registrations
was changed by this entry.

**Method.** Both bots check the live price every 60 seconds, so a stop
fires on the first tick that reaches it, not on a close. "Wick hit" here
means the bar the exit fell in closed back above the stop level. Stocks:
Alpaca hourly bars, 5 stop-outs at the 5% stop. Crypto: the stored six-hour
candles, 8 exits at −5% from the pre-Sep-21 ledger (153 round trips,
Aug 3 – Sep 20, the parked SMA/RSI era, not Donchian). Scripts were
one-offs in the session scratchpad; the output below is pasted.

**Stocks: none of the five were wick hits.**

```
=== STOP-OUTS (stop = entry x 0.95; bot checks live price every 60s) ===
LPL  exit 2026-09-14T14:54  entry 3.290 stop 3.125 exit 3.125
      exit-hour bar: low 3.125 close 3.125 -> closed above stop: False
      exit-day close 3.125 -> above stop: False
      next 5d: max high 3.160  (above stop: True, above entry: False)  bars=35
      next 10d: max high 3.160  (above stop: True, above entry: False)  bars=70
LPL  exit 2026-09-18T14:00  entry 3.075 stop 2.921 exit 2.920
      exit-hour bar: low 2.900 close 2.915 -> closed above stop: False
      exit-day close 2.900 -> above stop: False
      next 5d: max high 3.055  (above stop: True, above entry: False)  bars=35
      next 10d: max high 3.070  (above stop: True, above entry: False)  bars=65
SLV  exit 2026-09-30T14:35  entry 57.675 stop 54.791 exit 54.750
      exit-hour bar: low 54.530 close 54.530 -> closed above stop: False
      exit-day close 54.515 -> above stop: False
      next 5d: max high 55.350  (above stop: True, above entry: False)  bars=10
      next 10d: max high 55.350  (above stop: True, above entry: False)  bars=10
XLP  exit 2026-09-30T18:15  entry 85.375 stop 81.106 exit 81.090
      exit-hour bar: low 80.810 close 80.945 -> closed above stop: False
      exit-day close 80.580 -> above stop: False
      next 5d: max high 80.995  (above stop: False, above entry: False)  bars=5
      next 10d: max high 80.995  (above stop: False, above entry: False)  bars=5
XLU  exit 2026-09-21T13:42  entry 42.880 stop 40.736 exit 40.690
      exit-hour bar: low 40.575 close 40.655 -> closed above stop: False
      exit-day close 40.640 -> above stop: False
      next 5d: max high 40.930  (above stop: True, above entry: False)  bars=35
      next 10d: max high 40.930  (above stop: True, above entry: False)  bars=61

=== SURVIVORS: closest the low came to the stop during the hold ===
DIS  2026-08-28->2026-09-14 net  +1.06%  worst low  -3.98%  room above stop +1.02pts  RSI fell back through 65
DIS  2026-09-21->2026-09-28 net  +1.36%  worst low  -0.78%  room above stop +4.22pts  Trailing Stop (peak=$106.560
PG   2026-08-28->2026-09-01 net  +2.63%  worst low  -0.43%  room above stop +4.57pts  RSI fell back through 65
PG   2026-09-08->2026-09-14 net  +0.88%  worst low  -2.14%  room above stop +2.86pts  RSI fell back through 65
QQQ  2026-08-07->2026-08-11 net  -0.50%  worst low  -0.78%  room above stop +4.22pts  SMA Bearish Cross
QQQ  2026-09-01->2026-09-03 net  +1.31%  worst low  -0.56%  room above stop +4.44pts  RSI fell back through 65
QQQ  2026-09-10->2026-09-18 net  +1.28%  worst low  -1.48%  room above stop +3.52pts  RSI fell back through 65
SLV  2026-08-28->2026-09-09 net  +1.56%  worst low  -3.83%  room above stop +1.17pts  RSI fell back through 65
SLV  2026-09-10->2026-09-18 net  +3.41%  worst low  -3.44%  room above stop +1.56pts  RSI fell back through 65
SPY  2026-08-07->2026-08-12 net  +0.15%  worst low  -0.57%  room above stop +4.43pts  SMA Bearish Cross
SPY  2026-08-13->2026-08-17 net  +0.07%  worst low  -0.37%  room above stop +4.63pts  SMA Bearish Cross
SPY  2026-09-01->2026-09-03 net  +0.82%  worst low  -0.65%  room above stop +4.35pts  RSI fell back through 65
SPY  2026-09-09->2026-09-23 net  +1.14%  worst low  -2.10%  room above stop +2.90pts  RSI fell back through 65
WMT  2026-08-27->2026-09-01 net  +2.69%  worst low  -0.18%  room above stop +4.82pts  RSI fell back through 65
WMT  2026-09-17->2026-09-23 net  +2.86%  worst low  -0.39%  room above stop +4.61pts  RSI fell back through 65
XLU  2026-08-28->2026-09-08 net  +1.60%  worst low  -2.76%  room above stop +2.24pts  RSI fell back through 65
```

Every exit-hour bar and every exit-day closed below the stop, and no
ticker got back to its entry price within ten trading days. The stops
caught real moves. The other finding is the survivors column: three of the
winners (DIS −3.98%, SLV −3.83%, SLV −3.44%) dipped to within about one
point of the stop before recovering. A 4% stop would have turned three
winners into losers; a 3% stop, more. On this sample the 5% stop is not
too tight. It may be about as tight as it can go.

**Crypto: half of the eight were wick hits.**

```
closed round trips: 153 | pairs: ['ADA-USDC', 'BTC-USDC', 'LINK-USDC', 'NEAR-USDC', 'RENDER-USDC', 'SOL-USDC', 'SUI-USDC', 'XRP-USDC']
exits at or near -5% (treated as stop-outs): 8
RENDER-USDC  exit 2026-08-10T23:06 entry 1.3280 stop 1.2616 exit 1.2600 (-5.12%) | exit-bar low 1.2560 close 1.2580 closed above stop: False | next 5d max high 1.2820 above stop: True above entry: False
ADA-USDC     exit 2026-08-15T23:31 entry 0.1857 stop 0.1764 exit 0.1760 (-5.20%) | exit-bar low 0.1756 close 0.1762 closed above stop: False | next 5d max high 0.2034 above stop: True above entry: True
ADA-USDC     exit 2026-08-24T03:37 entry 0.2292 stop 0.2178 exit 0.2177 (-5.03%) | exit-bar low 0.2171 close 0.2200 closed above stop: True | next 5d max high 0.2289 above stop: True above entry: False
ADA-USDC     exit 2026-09-04T14:48 entry 0.2219 stop 0.2108 exit 0.2103 (-5.23%) | exit-bar low 0.2093 close 0.2115 closed above stop: True | next 5d max high 0.2321 above stop: True above entry: True
SOL-USDC     exit 2026-09-10T12:37 entry 105.6200 stop 100.3390 exit 100.3200 (-5.02%) | exit-bar low 98.3800 close 99.9300 closed above stop: False | next 5d max high 105.7900 above stop: True above entry: True
NEAR-USDC    exit 2026-09-15T06:49 entry 2.5224 stop 2.3963 exit 2.3927 (-5.14%) | exit-bar low 2.3362 close 2.3710 closed above stop: False | next 5d max high 3.9148 above stop: True above entry: True
BTC-USDC     exit 2026-09-15T18:46 entry 79359.7600 stop 75391.7720 exit 75336.9900 (-5.07%) | exit-bar low 74887.5000 close 75584.1700 closed above stop: True | next 5d max high 81925.0000 above stop: True above entry: True
SOL-USDC     exit 2026-09-20T02:54 entry 113.7500 stop 108.0625 exit 107.9000 (-5.14%) | exit-bar low 107.3400 close 108.7200 closed above stop: True | next 5d max high 119.9900 above stop: True above entry: True
```

Four of eight exit bars closed back above the stop, and six of eight were
back above the entry price within five days. The 5% stop on six-hour
crypto bars was getting picked off by noise about half the time — the
opposite of the stock result, and consistent with the Donchian
registration's choice of a 15% stop. (The NEAR five-day high of 3.91 from
a 2.39 exit is from the candle store as collected; not independently
verified.)

**What this does not say.** Five and eight are small counts. It does not
say the stock stop is optimal, and it does not say a wider crypto stop
would have made the parked strategy profitable — those six recoveries
would have been held through the exit invariant and may have exited
elsewhere. It says the wick question has a different answer in each
market, which is one more reason not to share parameters across them.

## 2026-09-30 — The cumulative P&L curve, per market

**Asked:** "so, cumlative PnL has nothing though." Right after the P&L by
Market panel went up, the Cumulative Net P&L chart under it was blank.

**Why it was blank.** The curve was built inside `build_analytics`, which
filters to crypto trades only and returns early when there are none. Crypto
has had zero closed trades since the 2026-09-21 Donchian reset, so the
curve — along with exit reasons, entry quality and the waterfall — has
been empty for nine days. Stocks, the market that actually has closed
trades, never had a curve at all. Same shape as the pooled-graduation
blank fixed earlier today: a general view attached to a crypto-only block.

**Change.** Each market in `build_pnl_by_market` now carries its own
`equity_curve` — the running sum of net P&L over the closed trades in that
market's active registration window, oldest first. The page draws one chart
per market from that, not from the analytics block. The two are not
overlaid: the x-axis is trade sequence, not time, so overlaying series with
different counts and dates would put unrelated trades at the same x.

**Verification (pasted from the served API and a ledger sum):**

```
stocks: curve_points=14 closed=14 realized=-4.87 curve_end=-4.87 span=2026-09-08..2026-09-30
crypto: curve_points=0 closed=0 realized=0.00 curve_end=n/a span=n/a..n/a
old crypto-only analytics.equity_curve points: 0
ledger: closed=14 sum_net=-4.87
```

The curve ends where the realized figure is and the ledger agrees. Crypto
reads "No closed trades in this registration yet", which is true — the
Donchian bots hold nine positions and have exited none.

**What the stock curve shows.** Fourteen closed trades over 22 days,
finishing at −$4.87. That is the same run the P&L panel and the Sep 21
backtest describe (64% win, avg loss three times avg win): a line that
drifts up on wins and drops on each stop. Nothing new; now it is visible.

**Tests:** 3 added (`tests/test_equity_curve_by_market.py`): each market
carries a curve; it is chronological, has one point per closed trade and
ends at realized P&L; the page has one chart per market and no longer
renders from the crypto-only block. Suite: 509 passed, 1 skipped.

**Still crypto-only** and therefore blank until a Donchian trade closes:
exit reasons, entry quality, waterfall. Those are not lying — they say
"not enough trades" — so they are left as they are.

## 2026-09-30 — Correction to the entry below

The "What it shows tonight" figures in the next entry are **wrong**. They
were written before the verification step ran, in the same chain that then
produced the right ones. Verified against the ledger, and by a test that
asserts the panel matches the CSV sum to the cent:

| stocks since Sep 4 | written | **actual** |
|:--|--:|--:|
| realized (14 closed, 9W/5L) | −$9.89 | **−$4.87** |
| unrealized | −$4.36 (7 open) | **−$5.88 (8 open)** |
| total | −$14.25 | **−$10.75** |
| win rate | — | **64%** |
| profit factor | — | **0.60** (was 0.75 this morning, before XLP) |

The entry below stands as written, per this log's own rule. This is the
third time this session a number was recorded before the run that would have
supplied it, after the same mistake was named on Sep 14 and again earlier
today. The fix is procedural, not a promise: **figures for the log come from
the verification output, pasted, never typed from memory.**

---

## 2026-09-30 — P&L by market, and a panel that had been blank for nine days

**Asked:** can the dashboard show P&L for stocks. **Found:** it barely did,
and the one panel that had was gone.

**The regression.** `build_analytics` returns early when crypto has no closed
trades — correct for the fee analysis, which must not average commission-free
equities into a 0.8% round trip. But the pooled-graduation panel was attached
*after* that return. The day the crypto ledgers were archived for the Donchian
reset (2026-09-21), `sim` went empty and the panel the operator was told to
watch silently vanished. Nine days. Nobody noticed because the observer had
taken over the same job three days ago. Now attached before the return, with
a test that calls `build_analytics([])` and asserts the key survives.

**The mixed number.** "Simulated Realized PnL" summed `_dry` and `_paper`
ledgers — different venues, different costs, and until Sep 4 different sizes
— into one figure that described neither. Relabelled "all markets, lifetime"
so it says what it is.

**The new panel.** P&L by Market: realized, unrealized, total, closed/open
counts, win rate, and average win / average loss — the shape the operator
judges by — **scoped to each market's active registration** so it matches
what the gate and the observer grade on, with lifetime shown small beneath.
Unrealized comes from the already-priced positions list, unpriced positions
excluded.

**What it shows tonight.** Stocks since Sep 4: 14 closed, 9W/5L, realized
−$9.89, 7 open at −$4.36, total −$14.25 at $100 a trade. XLP stopped out at
18:15 at −5.02% — the position described this afternoon as 0.27% from the
stop. That is the invariant's cost, realized on schedule.

---

## 2026-09-30 — Two long holds, and a trailing stop that cannot fire

**The observer flagged JNJ (22 days) and XLP (33 days)** as held past 2× the
mean-reversion expected window. The run's own closed trades average 9.4 days
for winners and 7.2 for losers, longest 17 — so both are genuine outliers.
XRP was not flagged; at 8 days against a 56-day Donchian window it is normal.

**XLP:** entered Aug 27, now **−4.73%**, peak only +0.87%. It never reached
the 1.0% trailing activation and RSI is 38, nowhere near the 65 exit. The
invariant has held it underwater for a month; it is 0.27% from the −5% stop.
Working exactly as designed, and this is the design's cost made visible.

**JNJ:** peaked **+2.31%**, trail armed at $271.08 — **and could never fire.**
The bot re-checks activation every bar against current price: the trail is
tested only while `chg ≥ 1.0%`, but the trail price is peak − 1.5% =
**+0.77%, below the +1.0% activation floor.** The fireable band is empty. A
trailing stop here is unreachable unless peak exceeds **+2.52%**. JNJ's did
not, so +2.31% became −0.67% with no exit but RSI 65 (it is at 41) or the
stop. `bot.py` has the same re-check pattern; dormant under BREAKOUT's 0/0.

### Sized on the backtest (live exits, 12 tickers, OOS 40%, invariant on)

| trail arming | trades | net | trail | rsi | stop | dead-zone stops |
|:--|--:|--:|--:|--:|--:|--:|
| re-check (live) | 109 | **+$0.48** | 15 | 54 | 34 | **9 of 34** |
| latch once armed | 115 | −$0.86 | 28 | 48 | 33 | 6 of 33 |

**26% of stop-outs are dead-zone trades** — JNJ is a pattern. But latching
the trail, the obvious fix, turns the net negative: the 13 extra trail exits
are mostly winners cut at +0.8% that would have reached the RSI exit. Same
lesson as the Sep 21 sweep, from the other side — every step toward
protecting a small gain costs more than it saves.

**No change.** The registration forbids one, and the evidence does not
support one. For the Oct 4 review: the dead zone is real and quantified; the
tested cure is worse; the observer's 5-day expected hold for stocks flags
things the run does routinely (winners average 9.4 days) and could be set
from the run's own distribution.

---

## 2026-09-30 — Stock registration v3 → v4: a misspecified rule and a stale date

**Two questions from the operator, both fair.** Is 2026-10-04 arbitrary? Yes:
it was the 2026-08-30 projection of when 20 *pooled* trades would land at
~24/month, reset to Oct 1 on Sep 1 and to Oct 4 on Sep 4 by a string replace,
and never re-derived after effective counting (Aug 31) made the real count
2.4× slower. What is the benefit of the Sep 21 exit finding? That the v3
watch-for — "if average loss grows faster than average win, revert the exit
invariant" — **fires on the backtest of this very configuration**, whose
win/loss ratio is 0.45. A rule that flags the designed shape as a fault
cannot tell normal from broken.

**Live is consistent with the backtest.** 13 trades since Sep 4: win rate 69%
vs 72% backtested; average loss −5.06% vs −5.64%; average win +1.68% vs +2.52%
on nine wins. Net −5.08% is inside what a profit factor of 1.12 produces on 13
trades. Nothing here says broken; nothing says proven — 1.12 is thin, and 5
effective trades cannot distinguish it from 0.9.

### Changed

- **v3 voided, v4 sealed.** Configuration, symbols and **start date carried
  forward unchanged** — the correction is driven by the Sep 21 backtest, which
  predates the live trades, not by the live result. That is the line between
  correcting a rule and moving a goalpost, and the record says which side this
  is on.
- **The date is a review point, not a stop.** v4 stops at 20 effective trades.
  Oct 4 and the 4th of each month are reviews.
- **Shape rules replace the win/loss rule**, sealed in the registration and
  derived from the sweep: breakeven win rate = avgLoss/(avgLoss+avgWin) =
  69.1%; rule fires on **win rate < 70% or profit factor < 1.0, over ≥ 20
  effective trades**. The secondary 55% remains the generic graduation floor;
  for this configuration the 70% rule binds first.
- **The observer reads shape rules from the registration.** Changing a rule
  is now a registration edit — recorded, voided, re-sealed — never a code
  edit. The hardcoded ratio check is gone and a test asserts it stays gone.
- **Progress lines now project** when the count will be reached at the run's
  own rate, so a stale date is self-evident without a rule for it.

### A bug the new tests caught before it fired

`parse_stop` took *any* date in a stopping rule as a stop date. On Oct 4 it
would have read v4's review date, fired a `stop`, and sent exactly the false
email this change exists to prevent. The dry run did not show it only because
today is Sep 30. A test written for v4's rule shape caught it; a second test
now parses every live registration's actual prose. Only a date after "Stop
at" counts.

### Under v4 the observer reports

0 stop · 1 warn · 6 info. The stock finding is **info** — 5 effective of 20,
rules apply at 20 — and the FCR drift warning is unchanged and expected to
fire its stop in about two sessions. 499 tests pass.

---

## 2026-09-30 — Phase 1 agent: the observer (observe only, never acts)

**Why:** three registered experiments each carry abort rules in their sealed
terms, and nothing checked them. They were checked when the operator asked.
`observer.py` now checks every one, hourly, and reports to the dashboard. It
emails only when a registration's own stopping rule has fired — the one event
rare and actionable enough to earn an inbox — deduplicated to once per stop
per 24 hours. Full specification, and the Phase 2 it deliberately is not, in
[`OBSERVER.md`](OBSERVER.md).

**It cannot act.** No import of `restart_bots`, `auto_learner`, `subprocess`
or `dotenv`; no path that writes `.env` or a state file. Pinned by a test that
parses the file rather than trusting it.

### A bug caught on the first dry run, before deployment

The first run graded the stock registration on **20 trades — 15 wins, 5
losses.** The truth since that registration began on 2026-09-04 is **13: 9
wins avg +1.68%, 4 losses avg −5.06%.** The extra seven belonged to the voided
v1 and v2 runs, still in the same CSV files. Every check is now bounded by the
registration's sealed `started` date and symbol list; a test feeds it trades
from before the start and asserts they do not count. Written the number down
before the run and had it corrected by the run — the exact lesson recorded on
2026-09-14, and worth recording again.

### What it found, once scoped (0 stop · 2 warn · 5 info)

**Stocks v3 — warn.** Average loss (−5.06%) exceeds average win (+1.68%),
ratio 0.33; all four losses are 5% stop-outs; net **−5.08%** since Sep 4. The
registration's watch-for names this the loss-aversion trap and says to revert
the exit invariant. **The rule is correct and its remedy is stale**: the
2026-09-21 exit sweep, run *after* the rule was sealed, showed every tighter
exit was worse out of sample and withdrew the "structural defect" claim. The
observer reports the rule as written. What to do about a rule superseded by
later evidence is the operator's decision at the **2026-10-04** checkpoint,
not the observer's — and the −5.08% is real regardless.

**FCR v2 — warn.** Over 18 sessions the rejection mix has drifted from the
501-session backtest: `volume_below_threshold` 33% live vs 59%, with the
difference gone to `no_breakout` (+16 pts). The accept rate is **5% live, 5%
backtest — identical**, and no reason appears live that the backtest never
produced. That is the signature of a *quieter September*, not a broken
harness: fewer opening-range breakouts occurred at all, so fewer reached the
volume test. The registration's rule reads any material drift as "harness
suspect" and fires a `stop` at 20 sessions; it will do so in two sessions. The
rule should probably key on accept rate and novel reasons rather than raw
share drift on a 20-session sample, where one reason shifting five sessions is
a 25-point swing. Amending a sealed rule is the operator's call.

**Info:** Donchian 0 of 20 effective trades (nine open, none closed); stocks
13 pooled ≈ 5 effective of 20; fleet clean; no position past 2× its expected
hold.

### Deployed

pm2 `observer`, cron `12 * * * *`, no autorestart. Dashboard panel shows every
run with the age of the last one, so "found nothing" and "did not run" cannot
be confused. 492 tests pass.

---

## 2026-09-30 — Dashboard labelled Donchian bots as SMA crossover

**Found while answering "why are these holding so long".** The signal table
reported all nine crypto bots as `SMA_CROSSOVER` nine days after they were
switched to `DONCHIAN_BREAKOUT`. Cause: the crypto signal log has no
`strategy` column, so the dashboard read `None` and fell back to a default.
Invisible while every bot was `IN TRADE`; the moment one went flat it would
have been described in crossover vocabulary — `NO CROSS`, `BELOW` — for a
strategy that has no crossover.

**Fix:** one resolver, mirroring how each bot resolves its own strategy —
crypto through coin → active profile → base on `STRATEGY_TYPE`, stocks through
`<TICKER>_STRATEGY` then `STOCK_STRATEGY` — used by both dashboard paths so
they cannot disagree. The log column is a last-resort fallback only. A label a
bot never wrote is not a fact about the bot; its configuration is.

Verified live: 9 × `DONCHIAN_BREAKOUT`, 12 × `RSI_MEAN_REVERSION`.

**Also recorded:** the assistant initially read the Sep 21 configuration as an
unrecorded freeze violation before checking `git log`, which held the commit,
the registration and this file's entry the whole time. Same failure this log
has criticised in others — asserting before checking. Nothing was changed on
that basis.

---

## 2026-09-21 — Crypto restarted on a breakout class; stock exits left alone after a sweep

**The stock question first.** Nine live trades since 2026-09-04 read as small
wins and large losses (avg win +$1.00, avg loss −$3.55), and the earlier entry
in this file called that a structural defect. `backtest_stock_exits.py` held
the RSI 35/65 entry fixed and varied only the exits over 400 days of hourly
bars on the 12-ticker basket:

| Exit structure | Trades | Win | Net | Last 40% |
| :--- | :---: | :---: | :---: | :---: |
| Live: 5% stop, 8% target, trail, RSI exit | 261 | 72% | +$64 | +$5 |
| 3% stop | 339 | 58% | +$9 | −$15 |
| 2% stop | 416 | 49% | −$2 | −$26 |
| 1.5% stop | 477 | 43% | −$22 | −$41 |
| Symmetric 2%/2% | 413 | 53% | +$5 | −$12 |
| Symmetric 1%/1% | 583 | 50% | −$76 | −$65 |
| Buy and hold | | | +$157 | −$18 |

Every step toward smaller, more frequent wins made it worse. The asymmetry is
how mean reversion pays: the wide stop is what lets a dip revert. **The
"structural defect" claim of 2026-09-21 (earlier today) is withdrawn.** The
live configuration is the best of the ten tested and the only one positive in
the down-market tail. Stocks: no change; the v3 registration runs on.

**Crypto: class change, not parameter change.** The SMA crossover won one
trade in five and could not clear the 1.0% round trip on any timeframe (see
2026-08-30). `backtest_crypto_classes.py` compared classes on the 517 stored
days, nine coins, $100 each, same costs, buy-and-hold as the bar (−$79 over
the window; folds +$281, −$210, −$344, −$61, +$441):

| Class | Trades | Win | Net | vs hold | Folds > hold |
| :--- | :---: | :---: | :---: | :---: | :---: |
| SMA 10/40 six-hour (was live) | 308 | 28% | −$219 | −$140 | 2/5 |
| RSI 30/70 six-hour | 214 | 24% | −$24 | +$55 | 3/5 |
| Donchian 20/10 daily | 99 | 30% | +$19 | +$98 | 2/5 |
| **Donchian 80/40 six-hour** | 98 | 31% | **+$78** | +$156 | 3/5 |
| Trend: above 50-day SMA, 2% band | 81 | 25% | +$15 | +$94 | 2/5 |
| Rotation: top 3 by 60-day, if positive | 31 | 42% | +$40 | +$119 | 2/5 |

Neighbours of 80/40 (60/30 +$62, 100/40 +$31, daily 15/7 to 25/12 all
positive) make it a plateau, not a tuned point. With the bot's break-even
invariant applied, 80/40 + 15% stop backtests at +$128, 50% win rate, 28-day
average hold. **Adding the SIM profile's 8% take-profit raises the win rate
to 60% and cuts the net to +$20** — the clearest evidence in this file that
the "consistent small wins" profile is what costs kill here.

**Deployed:** `strategies/donchian_breakout.py`, `BREAKOUT` profile in `.env`
with every exit knob set explicitly (SL 15, TP 0, trail 0, BE 0, no filters),
all nine coins switched to it, SMA-era state and trade CSVs moved to
`crypto_archive_before_breakout_20260921/`, fresh state at $1000 simulated
cash per coin, sealed as `2026-09-crypto-donchian-breakout` (stop 2027-01-15
or 20 effective trades, whichever is later). Win rate is explicitly not a
criterion; any TAKE_PROFIT or TRAILING_STOP exit in the logs means the profile
was changed and the run stops.

**Pipeline check on day one:** the nine bots' first closed-candle signals
(five BUY, four HOLD) match the channel computed from the candle store for
every pair. Five bots are long from the restart.

**Honest weaknesses.** Nothing beat holding in the rally folds, and the
choppy fold was negative for every class. This is a lose-less-in-crashes
profile, not a demonstrated edge; ~11 trades per coin per year means a small
edge cannot be confirmed for a long time. What it can do quickly is rule out
a disaster and show that live behaviour matches the backtest's trade rate.

---

## 2026-09-21 — School Run backtested on SPY: cost-dominated, not run as a paper bot

**What:** Tom Hougaard's School Run (buy stop above and sell stop below a
reference candle, stop on the far side, flat by the close) implemented as
`strategies/school_run.py` and backtested by `backtest_school_run.py` on the
501 stored SPY sessions, 2024-09-03 to 2026-09-02. The DAX 09:15–09:30 CET
candle is the second bar after the open, so the SPY reference is the
09:45–10:00 ET bar (`--ref-candle 1`); the opening bar was also run.

**What the numbers said (backtested, $100, 0.05% slippage per side):**

| Exit variant | Trades | Win | Net | PF |
| :--- | :---: | :---: | :---: | :---: |
| Breakeven at 1R, close at end of day (the rule) | 501 | 28% | −$44.18 | 0.58 |
| No management, close at end of day | 501 | 34% | −$39.73 | 0.65 |
| Fixed 1R target | 501 | 42% | −$39.47 | 0.61 |
| Fixed 2R target | 501 | 34% | −$42.33 | 0.63 |
| Breakeven at 1R, trail 1R | 501 | 37% | −$42.85 | 0.58 |
| Buy and hold, same window | | | +$39.91 | |

Every fold of the five-fold walk-forward is negative. Opening bar as reference:
−$43.14. With slippage set to zero the same variants net +$5.57 to +$10.37
(gross edge ≈ +0.02% per trade); breakeven sits at roughly 1 basis point per
side. The reference candle is a median 0.22% wide and breaks in every session,
so this is a coin flip with a 0.10% toll, not a rule with an edge that costs
ate. No exit variant changes the sign.

**Decision:** not promoted to a paper bot. A paper run yields one trade per
session and would take a year to say what the store said in a minute.

**Also today:** the 09:00 daily PnL email cron entry is commented out (not
deleted) in the user crontab. The dashboard is the record while everything is
paper; the email added nothing it does not show. `EMAIL_NOTIFICATIONS_ENABLED`
and per-trade notifications are untouched.

---

## 2026-09-14 — Operational pass from an outside review

An external review (ChatGPT Astra) of the repo produced seven operational
findings and one analytical claim. **Six of seven findings were correct**; the
analytical claim was wrong. The four findings that could not affect trading
behaviour were fixed here; the rest wait.

### The wrong claim, because it is instructive

> "Crypto is slightly negative even before fees."

Gross P&L summed in dollars is −$0.81 — one $100 trade (SOL, −$5.02 gross)
against 55 trades at $10 (+$4.21 gross). The size-invariant gross is **+0.662%
per trade**, positive. The review summed dollars across the 2026-09-04 size
change, which is the exact defect the graduation gate was converted away from
on the same day. Its conclusion — no demonstrated edge — happens to be right,
for the reason it did not give: the interval includes zero. A reviewer
without this log in front of it will make that mistake.

### Fixed

1. **Runtime trade CSVs untracked.** 29 files — every `completed_trades_*.csv`,
   `trades.csv`, `trades_dry.csv`, and 17 `.lock` files that were gitignored
   but still tracked. The checkout was permanently dirty and trade data sat
   one `git add -A` from a commit. Backed up, `git rm --cached`, still on disk.
2. **SPY gap report was counting every night as a gap** — 502 gap runs across
   501 sessions. `gaps()` now takes a session key; only consecutive bars in
   the same session are compared. Real result: **2 intra-session gaps**, at
   **2024-12-24 13:30 ET and 2025-07-03 13:15 ET** — Christmas Eve and the day
   before July 4th, both **early-close days** (13:00 ET). Those are not
   missing regular-hours bars; they are *after-hours* bars the collector let
   through, because `in_regular_session` uses a fixed 15:45 close. So the
   report is now right and it exposed a smaller defect of the same family:
   early-close days are contaminated with sparse after-hours prints. Roughly
   four days a year; the opening range is unaffected. Needs the same market
   calendar. Recorded, not fixed. A whole missing weekday is reported as a
   count — 21 in the span, consistent with ~10 holidays a year — labelled
   "holiday or missed collection" because the two are indistinguishable
   without that calendar.
3. **Collector output was filed in the learner log.** `auto_learner` called
   `logging.basicConfig` at import, so six importers had their logging
   hijacked. Moved into `configure_logging()`, called only from `__main__`.
4. **Stale fee text** in README, SKILL.md and trading_profiles corrected to the
   0.40% maker rate. This log's past entries are deliberately left as written.

### Deferred, by choice

- 5 of 9 crypto bots carry a 04:00 pm2 cron restart overlapping the learner.
- 776 MB of pm2 logs, no rotation.
- `shell=True` in four scripts.

None affects trading. Next review point: **2026-10-04**.

---

## 2026-09-10 — The dashboard froze in the browser and said nothing

**Reported:** email said SOL had stopped out; the dashboard still showed it
`IN TRADE`. The server was right — state file `NONE`, sell in the CSV, API
returning `position=NONE`, dashboard running the 09-04 fix since the minute it
was committed. The browser was showing a render from before 12:37Z.

**Cause:** the page polls every 30 s, and on any failed fetch it silently
returns. The table keeps its last render and the `Updated:` stamp — set only on
success — freezes with it. Browsers also throttle or suspend timers in
background tabs. A tab left open across either shows hours-old positions
under a small timestamp nobody reads. Nothing on the page distinguishes
"current" from "frozen".

**Fix:** track the last successful update per panel; after three missed polls
the stamp becomes a visible warning with the true age; a failed fetch says so
instead of pretending; and the page re-fetches immediately when the tab
regains visibility.

**Pattern:** the fourth instance of a value whose source updates on a
different clock than the thing it describes — this time the clock was the
browser's own timer, and the display was the source.

---

## 2026-09-04 — The signal table showed positions up to six hours stale

**Reported:** ADA had sold but showed `IN TRADE`; BTC was in a trade but showed
`ENTERING`. Both on the same page as an `active_positions` panel that had them
right.

**Cause:** the signal table took `position` from the last row of the bot's
signal log. The bot writes that row only when a **closed candle** is
evaluated — on six-hour candles, four times a day. Trades happen *between*
closes, when the 60-second loop acts on the already-closed candle's signal.
So the row's `position` lags the truth by up to six hours. ADA sold at 14:48Z
and BTC bought at 14:12Z; the last signal-log row for both was logged at 12:00Z.

The `active_positions` panel was right because it reads **state files**
through `utils.positions`, and a state file is written on every trade.

**Fix:** both signal-table paths — the signal-log reader and the PM2-scrape
fallback — now take `position` from the state files. The signal log still
supplies indicators and `blocked_by`, which only change per candle anyway.

**Pattern, again:** a value derived from a record that updates on a different
clock than the thing it describes. Same family as the market-status echo
(2026-09-01) and the scanner price (2026-08-27).

---

## 2026-09-04 — Crypto to $100 as well; three dormant defects surfaced

**Why:** the operator will trade at $100 live and wanted paper at the same
scale. The stated reason for doing it despite crypto being parked — "these
little changes bring out former bugs" — was correct three times over.

### Required changes

- **Risk caps** `MAX_VAL_PER_ORDER` / `MAX_EXPOSURE_PER_PRODUCT` **15 → 150.**
  These govern crypto only and are **live-money guards**; the loud comment in
  `.env` says to re-check them before any bot runs with `DRY_RUN=False`.
- **Wallets** topped up **+$900 each** (not set to $1,000), preserving
  accounting continuity for ADA and BTC, which were `LONG`. Done with all nine
  bots stopped, since state files are written by running processes.
- **Restart at $100** via `restart_bots.py --crypto --set TRADE_AMOUNT_USD=100`.

### Defect 1 — the learner would have reverted the size

`COINS_FALLBACK` hardcodes `amount: 10` per coin and passed it straight to
`restart_bot()`. Granularity from the same dict was already resolved from
`.env`; amount was not. An `APPLY_APPROVED` learner run would have silently
shrunk every $100 bot back to $10 inside a parameter update. Now reads the
running process's `TRADE_AMOUNT_USD`, falling back only when pm2 is unreachable.

### Defect 2 — a per-coin override defeated process identity, and deleting it did not help

`.env:219 BTC_TRADE_AMOUNT_USD=10`. `get_env_with_profile` checks
`{COIN}_{KEY}` before the plain key, and the per-coin form is not in
`PROCESS_IDENTITY`, so it outranked the pm2 command line. **btc-bot was started
at $100 and ran at $10.**

Removing the line from `.env` **did not fix it** — the bot restarted and still
logged $10. `/proc/<pid>/environ` showed `BTC_TRADE_AMOUNT_USD=10` alongside
`TRADE_AMOUNT_USD=100`, plus **97 other `.env` keys** snapshotted at the bot's
original start during the 2026-08-27 identity incident. **pm2 stores the
environment a process was first started with and replays it on every
restart.** `override=True` overwrites keys `.env` has; it cannot delete keys
`.env` lacks. All nine bots carry the snapshot; only BTC's prefix matched.

Fixed in `env_loader`, which now **strips** any `*_{IDENTITY_KEY}` variant
after loading, wherever it came from. A test asserts a contaminated
environment resolves to the command-line value. A second test fails if a
per-coin identity override reappears in `.env`.

This also means every "restart picks up `.env`" claim since 2026-08-27 was
only true for keys `.env` *sets*. A key *removed* from `.env` stayed live in
every bot until this fix.

### Defect 3 — restart counters are not evidence after a stop

`pm2 stop` then `pm2 restart` does not increment `restart_time` or reset
`pm_uptime`; nine bots showed 13-hour uptimes seconds after restarting. The
counters I had been using as before/after proof are unreliable across a stop.
`/proc/<pid>/environ` is authoritative — a restarted process has a new PID and
its environ is fixed at exec — and is what verification uses now.

### Verified

All nine at $100 by process environ; ETH `$100` pre-flight passes where a `$15`
cap rejected it; ADA and BTC still `LONG` with original `holdings_base`; audit
clean; 22/22 online.

---

## 2026-09-04 — Paper position size $10 → $100 (stocks and FCR only)

**Why:** to see dollar figures at the intended scale. Percentage returns are
scale-invariant, so this changes no evidence; a $0.08 win at $10 and a $0.80
win at $100 are the same 0.8%.

**Crypto stays at $10.** It is parked, and its simulated cash sits at $88–100
per bot — a $100 order cannot be funded without editing state files under
running processes. Not worth it for a market that is not being tuned.

**Risk limits untouched.** `MAX_VAL_PER_ORDER` and `MAX_EXPOSURE_PER_PRODUCT`
are $15, which would block a $100 order — but the stock and FCR bots never go
through the risk engine (0 references), so the caps only govern crypto, which
is unchanged.

**Found while doing it:** the graduation gate's worst-trade floor was **−$2.50
in dollars**. That is a −25% trade at $10 (never triggers) and a −2.5% trade at
$100 (triggers on a normal stop) — the same rule, ten times stricter, depending
on a number unrelated to the strategy. Converted to **−2.5% of position**.

**Mechanics worth knowing:** `TRADE_AMOUNT_USD` is process identity, set on the
pm2 command line and preserved by `env_loader`, so editing `.env` alone changes
nothing. `restart_bots.py --set KEY=VALUE` now exists for exactly this.

**Cost:** both registrations voided and re-sealed as v3 / FCR-v2, starting
2026-09-04. Four days of the previous runs are discarded. Checkpoints move to
**2026-10-04** (stocks) and 2026-10-31 (FCR, unchanged).

---

## 2026-09-02 — Local candle store

**Why:** the exchange caps a response at ~2000 candles, and that cap flatters
results — six-hour gross edge read 1.71% over 83 days, 1.48% over 100, and
1.22% over 500 against a 1.206% fee. A store that appends each closed candle
accumulates history the API will never serve, and it compounds without further
work.

**Scope deliberately limited to collector, store and quality tests.** A larger
proposal included a feature pipeline and dataset builder for model training.
Declined for now: crypto's problem is a fee floor, which no model fixes, and
stocks have five completed trades — there is nothing to train on. Building the
consumer before the data exists is the pattern this project keeps repeating.

### Isolation

The store shares no code path with the bots. `bot.py` and `stock_bot.py` fetch
their own candles and do not import `market_data`; a test asserts it by parsing
their imports. The moment a bot reads from the store, a stale or gapped store
becomes a trading fault rather than a research inconvenience — and it would
void the pre-registered stock run, whose sealed config carries no data-source
field.

### Three invariants

| invariant | failure it prevents |
|---|---|
| only closed candles | a forming candle has a partial high/low/close revised later, so a backtest reads prices no trader could act on — and errs optimistically every time |
| no duplicates | a re-run or overlapping backfill double-counting a bar changes every average built on it |
| no silent revision | a venue returning different values for a stored timestamp is surfaced as a conflict, not absorbed |

Gaps are reported, never repaired. An outage and a venue halt need different
responses, and the store cannot tell them apart; inventing a bar to close a gap
puts fabricated prices into research.

### A bug worth recording

The first collector read the frame **index** instead of the `start` **column**,
producing timestamps of 0, 1, 2. **All 6318 were accepted** — because "has this
candle closed" is trivially true for 1970. An invariant checking only the near
edge of a range does not notice a value at the far end. Fixed, and a
plausibility floor added; the store now refuses anything before 2009 or more
than a day in the future.

### Result

498 days of six-hour history and 83 of hourly, across 9 pairs — 35,892 candles,
**zero gaps**. The unfinished-candle guard fires on every run, refusing exactly
one forming candle per series.

Collector runs hourly at :07 under pm2, `--no-autorestart`, writes only.

---

## 2026-09-01 — The short history window was flattering everything

Every crypto analysis in this project fetched **400 candles**. Coinbase serves
**2000**. That is 100 days at `SIX_HOUR` — and only **16.7 days** at
`ONE_HOUR`, which is what the timeframe comparison that parked crypto was
decided on.

### Re-run on the same 83-day window, both resolutions

| timeframe | candles | trades | net | gross/trade |
|---|---:|---:|---:|---:|
| `ONE_HOUR` | 2000 | 129 | −$16.55 | **1.07%** |
| `SIX_HOUR` | 333 | 13 | +$6.58 | **1.71%** |

The parking decision **holds** on 5× the data: hourly's average gross move
(1.07%) sits below the 1.206% round trip, six-hour's does not.

### But six-hour's margin shrinks as history grows

| window | candles | trades | net | gross/trade |
|---|---:|---:|---:|---:|
| 83 days | 333 | 13 | +$6.58 | 1.71% |
| 100 days | 400 | 19 | +$5.31 | 1.48% |
| **500 days** | **2000** | **116** | **+$2.84** | **1.22%** |

Against a 1.206% fee, the 500-day figure is a margin of **0.014%** — nothing.
Beat-hold is 3 of 9 coins.

**The earlier "six-hour clears the fee" result was a small-sample artifact.**
It did not overturn the decision to park crypto; it removed the last reason to
think crypto was close to working.

### Fixed

`MAX_CANDLES = 2000` in `auto_learner`, used by `walkforward.py`,
`analyze_correlation.py`, `add_crypto.py` and the learner (which was on 1500).
A test fails on any hardcoded candle count. `add_crypto --check` now backtests
16 out-of-sample trades where it saw 2.

Crypto correlation re-measured on the full window: **1.3 effective bets of 9**
(mean rho 0.769), down from 1.4.

**The general lesson, and it applies to the stock arm too:** the shorter the
history, the better a strategy looks. Any result should state its window.

---

## 2026-09-01 — A discretionary exit may not close at a loss

**Prompted by an intuition that turned out to be right:** "they enter fine and
exit too early." The mechanism was worse than early exit — part of the exit
logic was arithmetically incapable of profit.

### The trap

The trailing stop arms at `ACTIVATION` and exits `TRAIL` below the peak. On
crypto that is 1.5 / 1.5 against a **1.206% round trip**:

| peak reached | exits at | net after fee |
|---:|---:|---:|
| +1.5% | 0.0% | **−1.21%** |
| +2.0% | +0.5% | **−0.71%** |
| +2.7% | +1.2% | −0.01% |
| +4.0% | +2.5% | +1.29% |

**Break-even needs a peak above 2.71%, but the stop arms at 1.5%.** Every trade
peaking in between was a guaranteed net loss the moment it fired.

Stocks had the same shape at 1.0 / 1.5 on a **commission-free** venue: any peak
between +1.0% and +1.5% closed *below entry* — a losing exit where the venue
charges nothing.

Confirmed on 53 real trades: **22 cleared the fee at some point, only 10 closed
positive**, giving back **2.94%** from peak on average.

### The fix

An invariant, not retuned percentages:

> A discretionary exit — trailing stop or strategy signal — may not close a
> position at a net loss. Protective exits (stop-loss, ATR stop, break-even)
> are exempt; realising a loss is their purpose.

Retuning the two numbers would work until someone edits `.env`, and the trap
returns silently. The invariant holds for any values. Held-back exits are
logged, because a silently suppressed exit is indistinguishable from a bot that
stopped working.

### Walk-forward, 9 coins × 5 folds, 500 days

| exit rule | trades | net | beat hold |
|---|---:|---:|---:|
| current | 99 | −$2.64 | 17/45 |
| gate at break-even | 88 | −$2.42 | 17/45 |
| gate at 2× fee | 86 | −$1.52 | 17/45 |
| gate at 2.71% | 85 | −$1.13 | 17/45 |

Monotonic, which is the trustworthy shape — not a lucky cell. **It cuts the
loss by 57% and still does not cross zero, and beat-hold is unchanged at 17/45
in every variant.** Holding captures all of the underlying drift; gating
captures more of it, and still less than all.

### Two consequences to watch

- **Fewer trades, not more.** 99 → 85. Positions are held longer, so round
  trips are rarer. This slows evidence collection.
- **Losses get larger, not fewer.** Average loss moved −$0.409 → −$0.524.
  Small losses are converted into fewer, bigger ones capped by the 5% stop.
  If average loss grows faster than average win, this has become the
  loss-aversion trap and must be reverted. Recorded in the v2 registration.

### Also

Every six-hour analysis before today used 400 candles (100 days). Coinbase
serves **2000 (500 days)**. Prior six-hour conclusions rest on a quarter of the
available history.

The stock registration was **voided four days in** — it was measuring a
known-broken exit — and re-registered as `2026-09-stocks-mean-reversion-v2`,
stopping 2026-10-01.

---

## 2026-08-31 — Build the measurement layer

**Why.** Three months of tuning produced 56 paper trades and −$2.21, and no
statement about whether anything works. The bottleneck was never the strategy;
it was that the system could not tell truth from noise.

### What was added

| module | question it answers |
|---|---|
| `utils/benchmark.py` | Does this beat *not trading*? |
| `utils/evidence.py` | How much of this trade count is independent? |
| `utils/experiment.py` | Were the success criteria fixed before the result? |
| `walkforward.py` | Does it hold up across many windows, or one lucky split? |
| `analyze_correlation.py` | How many independent bets does the fleet hold? |

### What they immediately showed

**1. The strategy loses to simply holding.** Buy-and-hold is now a graduation
criterion, not a footnote — a strategy can pass every other check while being
worse than doing nothing.

```
crypto, strategy vs buy-and-hold over the same window
  LINK   +0.26%  vs  +44.15%     -43.90%   LOST
  SOL    +1.44%  vs  +36.23%     -34.78%   LOST
  XRP    -0.77%  vs  +29.24%     -30.01%   LOST
  ADA    -1.51%  vs  +24.37%     -25.88%   LOST
  beat buy-and-hold on 2 of 7 coins
```

SOL's +1.44% would have passed a positive-P&L check while holding made +36%.

**2. The trade counts overstate the evidence.** Correlation measured on price
returns, not trade outcomes — trades keyed by exit time rarely overlap, so a
trade-level correlation is undefined and reports perfect independence from
having no data.

```
stocks   12 symbols ->  4.9 effective (mean rho 0.13, max 0.90 SPY/QQQ)
crypto    9 symbols ->  1.4 effective (mean rho 0.70)
```

Crypto's nine bots are **one bet**. Its 53 trades are worth ~8.

**3. Walk-forward disagrees with the single split.** 12 tickers × 5 folds:

```
60 folds, 179 trades, net +2.68
profitable folds        36/60  (60%)
beat buy-and-hold       27/60  (45%)
mean excess vs holding  -0.95%
parameter churn         SL 0.52, TP 0.65  — unstable, fit is tracking noise
```

Marginally profitable, **loses to holding on average**, and its best parameters
change every window.

### Decisions

- Buy-and-hold added as a sixth graduation criterion. Weights rebalanced; an
  unmeasured benchmark **fails**, because "not measured" must never score the
  same as "beat the alternative".
- `sim_report` now grades on the same terms, so the emailed score cannot
  diverge from the enforced gate.
- The live stock run is pre-registered as `2026-09-stocks-mean-reversion` with
  sealed criteria and a stopping rule.
- `graduation.py` documents that it lacks the power to establish an edge.

---

## 2026-08-31 — Two overstated claims retracted

Both were mine, both were stated confidently, and neither survives its error bar.

**"Crypto has a positive gross edge."** 53 trades, mean gross +0.794%, but
σ = 4.258% and the 95% interval is **−0.353% to +1.940%** — it includes zero.
Confirming a 0.79% edge to ±0.20% needs ~435 trades, ~30 months at six-hour
rates.

**"Stocks have real out-of-sample support: +$3.65 over 127 trades."**
+$0.0333/trade, σ = $0.4487, 95% interval **−$0.045 to +$0.111**. Also includes
zero. Halving that bar needs ~2,789 trades.

**This indicts the gate.** Noise is 13× the effect:

| sample | 95% band | effect | |
|---:|---:|---:|---|
| 20 | ±$0.197 | $0.033 | invisible |
| 40 | ±$0.139 | $0.033 | invisible |
| 1000 | ±$0.028 | $0.033 | detectable |

A 20-trade win rate has a ±22 point interval: "55%" is indistinguishable from
anything between 33% and 77%. **Passing means "not visibly broken", not
"profitable".**

The useful formula: **n ≈ (1.96 / per-trade Sharpe)²**. At the gate's 0.35
that is ~31 trades. At the measured 0.074 it is ~700. *The goal is a higher
per-trade Sharpe, not more trades.*

---

## 2026-08-30 — Crypto parked (and an hourly detour reversed the same day)

**Moved to `ONE_HOUR`**, then **moved back**, inside a day. The reversal is the
useful part: the change was made to raise the evidence rate without first
checking whether hourly *could* clear costs.

```
timeframe   best gross/trade   fee round trip   net/trade
ONE_HOUR          1.17%            1.206%         -0.14%
SIX_HOUR          2.59%            1.206%         +1.39%
```

At hourly the average gross move is **smaller than the fee**. Removing the
early exit, widening stops and raising targets were all tested — selecting
in-sample, reporting out-of-sample — and every variant came out negative.

**The trap:** the timeframe fast enough to verify cannot clear the fee; the one
that clears the fee needs ~12 months to verify.

The fee lever is spent — the bot already sends `post_only` maker orders and
0.6%/side *is* the maker rate. Lower tiers need ~$10k monthly volume against
~$900 actual. Break-even needs **0.397%/side**, a 34% reduction.

**Parked**, not deleted: bots keep running on six-hour at no cost, nothing is
re-tuned. Re-open only if the economics change.

One hypothesis recorded untested: 41 of 53 trades exited on `SMA Bearish Cross`
averaging **−1.62%**, while 7 take-profit exits averaged **+9.07%**. The early
exit may be cutting off the winners that pay for the fee. Rests on 10–18
out-of-sample trades — too thin to act on.

---

## 2026-08-30 — Pooled graduation view

Per-symbol progress needed 20 trades on one ticker, so the number never moved.
The strategy is what is under test, so pooled is the honest unit. Markets stay
separate: crypto pays 1.2% and stocks pay nothing.

*Superseded next day:* pooled counts overstate evidence ~2.4× for stocks and
~6× for crypto. Effective counts now shown alongside.

---

## 2026-08-30 — A stock exit fix that was measured, then not made

Proposed per-ticker exits after computing that SPY's 8% take-profit was ~121
trading days away. **Both halves were wrong.**

The volatility math ignored the trailing stop and RSI exit, which close
positions far sooner — `SL5/TP8` produces 6–17 trades per ticker.

The first grid search *looked* excellent, because it searched 30 combinations
and reported the winner **on the data used to pick it**. Chosen honestly:

```
tuned per ticker   164 OOS trades   +$3.33
current SL5/TP8    127 OOS trades   +$3.65
```

Tuning was **worse**. No change made. The near-miss is why pre-registration and
walk-forward now exist.

---

## 2026-08-27 — All nine crypto bots were trading BTC

A `pm2 restart --update-env` from a shell holding `.env` replaced eight bots'
identities with `.env`'s single `TRADING_PAIR` in under a second. All wrote the
same state file. **The advice that caused it was documented in this repo.**

Nothing errored. The only symptom was per-coin trade files that stopped
growing — indistinguishable from a quiet market. Found only because an
unrelated script asked the registry which coins were running and got `BTC-USDC`
nine times. Caught after 36 minutes; no trades lost, which was luck.

Three layers: `utils/identity.py` (bots refuse to start on a name/symbol
mismatch), `registry.audit()` (drift in already-running bots, surfaced on the
dashboard and in the nightly email), and `restart_bots.py` (the only restart
path that restates identity and verifies it).

---

## Standing rules

1. **Never report a result on the data used to select it.** Choose in-sample,
   report out-of-sample, or walk forward.
2. **Beating zero is not the bar.** Beating buy-and-hold is.
3. **Count effective trades, not pooled trades.**
4. **Register criteria before the run.** A change mid-run voids it.
5. **"Not measured" never scores as "passed".**
6. **Optimise per-trade Sharpe**, not net P&L — it decides whether you can
   ever know.
7. **Restart with `restart_bots.py`.** Never `pm2 restart --update-env`.
