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

## 2026-11-16 — Trend-hold study: the rule, the comparison and the pass/fail test, fixed before the run

**Asked:** Lee, "how do the consistent few do it", then "Yes, test it". Two
habits of the traders who last came up that this project has never tested:
trade with the trend, and let winners be bigger than losers. Every strategy
run here buys a dip and sells a small bounce (average win about +2%, average
loss about -5%, so it has to be right 71% of the time). This entry and
`backtest_trend_hold.py` are committed before the script is run. Only its unit
tests, on made-up prices, have been run. The result goes in a separate entry
above; this one is not edited afterwards.

**The rule, T200.** For each stock separately, once a day: after a session
closes, compare its close with the average of its last 200 session closes,
that one included. At or above: be in the stock. Below: be out. Act at the
next session's open.

**Why 200.** It is the standard published trend rule (the ten-month average)
and was not chosen from this data. 50 and 100 sessions are reported as
sensitivity and never used to decide.

**What it is run on.** The calm six fixed by the one-stock study before this
was thought of: XLP, JNJ, PG, SPY, XLU, WMT. $100 a position, 0.10% slippage a
side, the frozen one-minute IEX cache. Sessions 2021-06-01 to 2026-09-03: the
data starts in July 2020 and 200 sessions have to exist first, and every
approach is measured on that same window.

**The comparison.** Same six stocks, same window, same costs, one $100 slot a
stock, all three marked to market at every session's close:

- HOLD: buy at the first open, never sell.
- DIP: the v5 strategy as registered.
- T200: the rule above.

**T200 passes only if all five hold, for the six together:**

1. Net P&L above zero.
2. Net P&L above DIP's.
3. Largest drawdown smaller than HOLD's.
4. Average winning trade at least 2 times the average losing trade. This is
   the "winners bigger than losers" claim itself.
5. Up in at least 4 of the 6 calendar years 2021 to 2026.

**Not a pass term, and reported first: return against HOLD.** A trend rule is
out of the market part of the time, so in a rising market it is expected to
make less than holding. What it is supposed to buy is a smaller drawdown.
Whether that trade is worth it is Lee's judgement and not something a test
can settle. Said now so that "it made less than holding" is not later read as
a surprise or as a failure of the test.

**Reported, never used to decide:** each ticker, T50 and T100, the jumpy six
and all twelve, the split into 2021-2023 and 2024-2026.

**Known limits, before the run.** One window of 5.3 years with one bear market
in it (2022). No selection step, so no confirmation window either: the rule
and the stocks were fixed from outside, and the whole window is the test. A
200-session rule makes few trades (a handful a stock), so term 4 rests on a
small number of trades. Backtested at assumed costs; nothing here is a live
result.

**Not touched:** v5, the bots, the registration.

---

## 2026-11-16 — One-stock study result: a stock cannot be picked from its past, but the calm six carry the whole basket

**Run** on the terms fixed in the entry below, committed (8b47871) before the
run. `backtest_one_stock.py`, the frozen gate-backtest cache, trend gate on,
$100 a trade, 0.10% slippage a side. Backtested, not measured.

**1. Every ticker, calmest first.** Volatility is measured on SELECT.

```
       vol  | SELECT 2021-2023              | CONFIRM 2024-01-01 to 2026-09-03      | holding,
            |  n   win    PF     net        |  n   win    PF     net     avg trade  | CONFIRM
XLP   0.86% | 23  73.9%  1.35   +$5.59      | 30  73.3%  1.37   +$6.09    +0.20%    |  +25.2%
JNJ   1.02% | 33  66.7%  1.04   +$1.32      | 31  74.2%  1.61  +$16.16    +0.52%    |  +88.0%
PG    1.10% | 27  63.0%  0.64  -$11.53      | 33  81.8%  2.58  +$33.34    +1.01%    |   +6.2%
SPY   1.10% | 35  88.6%  2.12  +$17.98      | 35  88.6%  2.76  +$23.71    +0.68%    |  +68.5%
XLU   1.14% | 27  77.8%  1.06   +$1.85      | 29  75.9%  1.29   +$7.79    +0.27%    |  +44.1%
WMT   1.28% | 28  71.4%  1.58  +$12.40      | 34  82.4%  2.41  +$32.85    +0.97%    | +109.9%
QQQ   1.50% | 43  67.4%  0.93   -$4.45      | 41  82.9%  1.52  +$19.68    +0.48%    |  +80.7%
SLV   1.72% | 44  63.6%  0.81  -$15.87      | 46  65.2%  0.92   -$6.65    -0.14%    | +179.7%
DIS   1.90% | 43  69.8%  1.07   +$4.52      | 34  70.6%  0.89   -$5.25    -0.15%    |  +21.4%
LPL   2.54% | 38  63.2%  0.94   -$5.13      | 50  56.0%  0.63  -$46.69    -0.93%    |  -35.8%
META  2.97% | 38  63.2%  0.86  -$10.37      | 46  76.1%  1.59  +$34.84    +0.76%    |  +77.9%
TSLA  3.71% | 60  63.3%  0.79  -$25.49      | 67  76.1%  1.41  +$42.51    +0.63%    |  +51.5%
basket      | 439 68.6%  0.95  -$29.19      | 476 74.6%  1.27 +$158.39    +0.33%    |
```

**2. The choices, from SELECT only.** S1 eligible: DIS, JNJ, META, QQQ, SPY,
WMT; best per-trade Sharpe: **SPY**. S2 least volatile: **XLP**. H: stable six
XLP, JNJ, PG, SPY, XLU, WMT; jumpy six QQQ, SLV, DIS, LPL, META, TSLA.

**3. Verdicts on the fixed terms.**

```
S1 SPY  n=35  win 88.6%  avg win +1.20%  avg loss -3.37%  PF 2.76  net +$23.71   2024 +$4.43  2025 +$11.58  2026 +$7.70
        20+ trades yes | net > 0 yes | PF >= 1.20 and >= basket 1.27 yes | positive in 2 of 3 years yes   => PASS
S2 XLP  n=30  win 73.3%  avg win +1.02%  avg loss -2.05%  PF 1.37  net  +$6.09   2024 -$0.68  2025  +$2.41  2026 +$4.35
        20+ trades yes | net > 0 yes | PF >= 1.20 and >= basket 1.27 yes | positive in 2 of 3 years yes   => PASS
H       stable six  SELECT n=173 PF 1.18 +$27.60  | CONFIRM n=192 win 79.7% PF 1.94 +$119.95
        jumpy six   SELECT n=266 PF 0.88 -$56.79  | CONFIRM n=284 win 71.1% PF 1.08  +$38.44
        stable net > 0 yes | stable PF >= jumpy PF + 0.10 yes (1.94 vs 1.08)                              => PASS
PERSISTENCE  rank correlation of average trade, SELECT against CONFIRM, twelve tickers: -0.09             => does NOT carry forward
```

**4. How to read the two single-stock passes: they are worth little.**

- Persistence is -0.09 against a bar of 0.50. A ticker's result on 2021-2023
  says nothing about its rank on 2024-2026. PG was the worst of the calm six
  on SELECT and the best of all twelve on CONFIRM; TSLA was last on SELECT and
  near the top on CONFIRM. By the reading fixed beforehand, the SPY pass is
  one draw and is not evidence that picking a stock works.
- After the fact: 9 of the 12 tickers pass the same four terms on CONFIRM.
  2024-2026 was a good stretch for this strategy on nearly everything (basket
  PF 1.27 against 0.95 on SELECT), so the bar was low. A pick at random would
  have passed three times in four.
- XLP passed on $6.09 in 2.7 years, $2.28 a year at $100 a trade, ninth of
  twelve by average trade. "Passed" and "worth trading" are different things.
- What can be said for SPY, as description: it is the only ticker that is the
  gate's own market, it won 31 of 35 in each window, and it is one of three
  tickers (SPY, WMT, XLP, all calm) that pass the four terms on SELECT too.
  Its t on CONFIRM is about 2.0 on 35 trades.

**5. The finding that holds up: calm against jumpy.** This split is made from
volatility, which is known in advance and does not use any strategy result,
and it has several hundred trades on each side.

```
whole test 2021-01-04 to 2026-09-03
stable six  n=365  win 77.0%  avg win +1.53%  avg loss -3.35%  PF 1.52  net +$147.55  avg +0.40%
jumpy six   n=550  win 68.2%  avg win +2.51%  avg loss -5.47%  PF 0.98  net  -$18.35  avg -0.03%
by year, PF:  stable 1.58  1.02  0.92  1.66  1.86  2.45   (2021 to 2026)
              jumpy  1.10  0.64  0.83  1.18  1.36  0.80
```

- The basket's whole backtested profit, +$129.20, is the calm six (+$147.55)
  less the jumpy six (-$18.35). The jumpy six make 60% of the trades and lose.
- Same direction in both windows. On CONFIRM the stable six's per-trade
  Sharpe is 0.247 on 192 trades, t about 3.4.
- It does not rest on LPL. With LPL left out the jumpy five are PF 0.87 on
  SELECT and 1.25 on CONFIRM, still under the stable six's 1.18 and 1.94.
- It is a group result, not a ranking. Within the twelve, volatility against
  CONFIRM average trade is only -0.18: META and TSLA did well in 2024-2026.
  The calm group is better mostly because its losses are smaller (-3.35%
  against -5.47%) at a higher win rate, not because every calm stock beats
  every jumpy one.
- The calm six still lost a little in 2023 and made $1 in 2022.
- The volatility ranking was measured on 2021-2023, so only the CONFIRM half
  of this table is strictly out of sample. The ranking itself is not
  surprising: staples, healthcare, utilities, a retailer and the index.

**6. Against simply holding.** Every pick lost to holding the stock it traded.
SPY: +23.7% on one $100 position against +68.5% held, with the money in a
position about a third of the time. $8.87 a year at $100 a trade, 13 trades a
year. The strategy is not a way to beat owning the stock; at best it is a
smaller return for much less time exposed.

**What this means for the idea.** "Pick the one stock that reads
consistently" is not supported: which stock did best does not persist.
"Trade the stable ones" is supported, as a backtest: the calm group is where
the edge is. If it has to be one stock for a live pilot, SPY is the
defensible choice, for what it is (the gate's own market, the calm group, the
same result in both windows), not because it won a contest. One stock at 13
trades a year takes years to judge live.

**Not changed.** v5 runs the registered twelve; dropping the jumpy six would
be a change to entries and would void it. A calm-six basket is a candidate
for the next registration or for a live pilot design, Lee's call.

**Tests.** 11 new in `tests/test_one_stock_study.py`; full suite 599 passed, 2 skipped.

---

## 2026-11-16 — One-stock study: the choosing rule and the pass/fail test, fixed before the run

**Asked:** Lee, about live trading: "really start to focus on maybe 1 stock,
one that could consistently be read and stable", then "Yes, run it" to testing
that on the backtest data. This entry and `backtest_one_stock.py` are committed
before the script is run in anything but `--check` mode. The result goes in a
separate entry above; this one is not edited afterwards.

**Why a rule is needed before looking.** v4's ten live weeks hinted that the
steady names worked and the jumpy ones did not (WMT +$8.28, DIS +$6.63 against
SLV -$12.58, QQQ -$5.12). That is about four trades a ticker. Picking the best
of twelve after seeing them is the mistake the registrations exist to stop:
one of twelve always looks best.

**What has and has not been seen.** The 2026-11-10 gate run printed results by
ticker for the whole test window. They were "reported, never used to choose"
and are not in this log. They have not been looked at in writing this entry;
the script's `--check` mode prints only the pooled basket line, which matched
the published one (915 trades, 71.7%, PF 1.10, +$129.20). Every choice below
is mechanical, so a rule cannot have been bent to a result even by someone who
had seen them.

**Data and simulator.** The frozen cache and the minute-by-minute replay of
the 2026-11-10 gate backtest, with the v5 trend gate on, $100 a trade, 0.10%
slippage a side.

**Two windows.** Choose on SELECT, judge on CONFIRM.

- SELECT: entries 2021-01-04 to 2023-12-31.
- CONFIRM: entries 2024-01-01 to 2026-09-03. It stops before the live weeks
  that prompted the idea.

**Three questions.**

- **S1, the best single stock.** The ticker with the highest per-trade Sharpe
  on SELECT, among those with at least 25 trades there and a positive net in
  at least two of 2021, 2022, 2023. If none qualifies there is no candidate.
- **S2, the most stable single stock.** The ticker with the lowest volatility
  on SELECT (standard deviation of daily close-to-close returns). Chosen
  without any strategy result.
- **H, stable against jumpy.** The six least volatile tickers on SELECT against
  the six most volatile.

**A single stock (S1 or S2) passes on CONFIRM only if all four hold:**

1. At least 20 trades.
2. Net P&L above zero.
3. Profit factor at least 1.20, and at least the gated basket's over the same
   window. One stock gives up the basket's spread of risk; it has to be
   clearly better per trade to be worth that.
4. Net P&L above zero in at least two of 2024, 2025, 2026.

**H passes** if on CONFIRM the stable six have a net above zero and a profit
factor at least 0.10 above the jumpy six.

**Persistence, the guard on S1.** Across the twelve tickers, the Spearman rank
correlation between average return per trade on SELECT and on CONFIRM. At 0.50
or more (about the 5% level for twelve), per-ticker results carry forward.
Below it, an S1 pick that happens to pass is one draw from twelve and is not
evidence that picking a stock works.

**Reported, never used to decide:** every ticker on both windows, each pick
against simply holding that stock, dollars a year at $100 a trade, worst
trade, longest losing run, the pick's rank among the twelve on CONFIRM.

**What a pass would and would not mean.** A pass says the pick held up on
2.7 years it was not chosen on, in a backtest at assumed costs. It is not a
live result, and v4 had a passing backtest too. A fail on S1 with low
persistence says the stock cannot be chosen from its own past results. A fail
on H says "stable" is not what separates the winners.

**Not touched:** v5, the bots, the registration. This is a study on old data.

---

## 2026-11-16 — Dashboard restarted for v5; its panel was putting v4's open positions on v5

**Asked:** Lee, "Restart dashboard", so the registration panel counts v5
trades by entry time as the observer does. Plain `pm2 restart dashboard` at
10:28 ET (no `--update-env`; `restart_bots.py` only handles bots).

**Found on the first look.** The panel named the v5 registration, since
2026-11-17, 0 closed: right. It also showed `2 open` and a total of -$0.91:
the LPL and QQQ positions v4 had opened, with their unrealised P&L counted as
v5's. The entry-time scope added this morning covered closed trades and not
open positions. A run that has not traded was showing a result.

**Fixed.** Under entry-time counting, a position opened before the start is
not counted in the panel's open count, unrealised figure or total. It is shown
on its own line, "opened before the start, not counted". Registrations counted
by exit are unchanged. Display only: no bot, rule or registration term is
touched. Three tests added; full suite 588 passed, 2 skipped in the worktree.

**Not changed:** the observer already scoped correctly (it only reads closed
trades).

---

## 2026-11-16 — v5 is live: bots restarted on the gate, entries off from the first tick

**Asked:** Lee, "Seal and restart". Done in that order: registration and the
entry below committed (feff8e2), `lab1-container-ci` fast-forwarded to it,
then `restart_bots.py --stocks` at 10:25 ET from a clean environment.

**Measured, from the logs, 10:25 to 10:27 ET.**

- All twelve restarted, identity verified by the script before and after, all
  online, restart count 2.
- Every bot logged `Trend gate: no new entry while SPY's last close is below
  its 50-session average` at startup, and the watchdog line.
- The ten flat bots each worked the gate out on their first tick and logged
  the same answer: `SPY closed 754.27 on 2026-11-13, -1.29% below its
  50-session average 764.10: entries off`. That is the figure the backtest
  code gives for today.
- QQQ and LPL are holding v4 positions and did not consult the gate, as
  designed; their exits run as before. Neither will count as a v5 trade.
- Three ticks each, no ERROR, WARNING or CRITICAL line in any log.
- The observer, run read-only: `2026-11-stocks-mean-reversion-v5 · Progress ·
  0 effective trades of 20 · 0 pooled`.

**Not done.** The `dashboard` process was not restarted, so its registration
panel is still running the old code: it would count a v4 position that closes
from tomorrow on as a v5 trade until it is restarted. Lee's call. Nothing is
pushed; `lab1-container-ci` is ahead of GitHub.

**Next review:** 2026-12-17. Nothing about v5 changes before the stop except
a defect fix.

---

## 2026-11-16 — Stocks v5 registered: v4 plus the SPY trend gate, terms sealed before it starts

**Asked:** Lee, "Yes, register v5", then "Seal and restart" after seeing the
terms below. This entry and the registration are committed before the bots are
restarted on the gate. What the restart showed goes in a separate entry above.

**What prompted it.** SLV stopped out this morning at -5.63% (bought Nov 12
at 45.33 on RSI recovering through 35, gapped down over the weekend, sold at
the open at 42.78). The bot did what it is built to do. Checked afterwards:
the trend gate would have blocked that entry (SPY's Nov 11 close 759.80
against a 50-session average of 764.56, 0.62% below). It has been off-entries
every session since Nov 6, so it would also have blocked the SPY trade of
Nov 6 that made +3.11%. Two trades; no evidence either way. The evidence for
the gate is still the 2026-11-10 backtest.

**The change.** One rule added to v4, exactly as fixed on 2026-11-10 before it
was backtested: no new entry while SPY's close on the last completed session
is below the average of its last 50 completed session closes. Entries only.
Stops, targets, the trail, the RSI exit and the exit invariant are untouched.
All twelve bots, SPY included. Code in `utils/market_gate.py` and the flat
branch of `stock_bot.py` (commit 1b4af9c).

**Is the live rule the backtested rule? Three checks.**

- Same arithmetic: `market_gate.evaluate` against
  `backtest_regime_gate.market_state` on a 400-session series, identical
  decision, prior close and average on all 350 sessions that have 50 behind
  them (a test).
- Same closes: the backtest took a session's close as the last one-minute IEX
  print in the regular session; the bot reads Alpaca's daily IEX bars. Over
  363 sessions (2025-06-02 to 2026-11-09) they agree to the cent on 355,
  differ by at most 0.013%, and give the same gate decision on 314 of 314.
- Same answers on live data: the bot's own code, run today, gives prior close
  and average of 735.40/765.15, 752.72/764.86, 749.93/764.56, 759.80/764.56,
  757.16/764.44 and 754.27/764.10 for the sessions of Nov 9 to Nov 16, the
  figures the backtest code gives. All six: entries off.

**Two places the live gate is deliberately not the backtest.**

- The session in progress is excluded. Alpaca serves a daily bar for today
  whose "close" is the latest price. The backtest never had that problem.
- Unknown blocks. In the backtest "unknown" only meant "before there are 50
  closes" and it let entries through. Live it means the closes could not be
  fetched, or stop more than 5 days short of today, and an entry is refused.
  An entry taken blind is not evidence about a gated strategy.

**Terms, sealed in `experiments/2026-11-stocks-mean-reversion-v5.json`
(seal 7d0055e5d477d5c8).**

| Term | v5 | v4 was |
|---|---|---|
| Config | v4 unchanged, plus the gate | |
| Start | 2026-11-17 | 2026-09-04 |
| Stop | 20 effective trades (48 pooled) | same |
| Primary | pooled excess vs buy-and-hold > 0 | same |
| Shape: win rate | >= 71% | >= 70% |
| Shape: profit factor | >= 1.00 | same |
| Secondary floors | win 55%, net > 0, Sharpe 0.35, worst -2.5% | same |
| Trades counted | entered on or after the start | exited on or after the start |
| Reviews, not stops | the 17th of each month from 2026-12-17 | the 4th |

- **71%** is v4's method on v5's backtest: breakeven win rate =
  avgLoss/(avgLoss+avgWin), rounded up. Gated backtest, 915 trades, at ledger
  prices because that is what the observer scores: avg win +2.18%, avg loss
  -5.33%, breakeven 70.97%, achieved 75.5%, profit factor 1.26. The figure was
  not picked from the pass rates below; they were computed for 70, 71 and 72
  and are reported for what they say about the test.
- **Counted by entry.** LPL (entered Nov 13) and QQQ (entered Nov 16) are open
  and were entered under v4 on sessions the gate would have blocked. Scoring
  their exits as v5 trades would grade the gate on entries it did not allow.
  The registration seals `count_by: entry_time`; `observer.trades_for` and the
  dashboard panel read it. Every earlier registration still counts by exit.
- **Start is Nov 17, restart is Nov 16.** Today's session is gated off whatever
  happens, so no v5 entry can be made before tomorrow's open.
- `cooldown_hours_after_loss: 6` is now in the sealed config. It was already
  live under v4 and in the backtest; v4's record left it out.

**What this run can and cannot show. Said before it starts.**

- Cut into consecutive 48-trade runs at ledger prices, the gated backtest
  passes both shape rules in 12 of 19 runs; the ungated one in 15 of 27. A v5
  that works exactly as backtested fails about one time in three, and v4
  passes more than half the time. The run cannot tell v5 from v4. It can rule
  out a disaster or show a large edge.
- It will be slow. A 48-trade gated run took a median of 103 days in the
  backtest (58 to 223). Late February is the middle estimate, not six to
  eight weeks.
- Worst trade >= -2.5% and Sharpe >= 0.35 are the generic floors. The backtest
  of this configuration does not meet them (223 of 915 trades worse than
  -2.5%; Sharpe 0.095 at ledger prices). They are expected to fail and are
  not the test.
- The ledger records signal prices, not fills. With 0.10% slippage a side the
  backtest's profit factor is 1.10, not 1.26. Paper fills have still never
  been compared with signal prices.
- No entries until SPY closes back above its average (764.10 today). A quiet
  stretch is the gate working.

**Not changed.** No threshold, exit or size. The gate's defaults are in code
(`STOCK_TREND_GATE_DAYS=50`, `STOCK_TREND_GATE_SYMBOL=SPY`), not `.env`, so a
restart cannot quietly run v4; `.env` was not edited. `ai_platform/ledger.py`
still hardcodes v4's start date for its own summaries.

**Tests.** 34 new in `tests/test_trend_gate.py`. Full suite 585 passed,
2 skipped, with the registration in place.

---

## 2026-11-11 — Stock bots restarted on the fix; first live run is clean; slv and meta are unfrozen

**Asked:** Lee, "can you run the restart", after agreeing to merge the fix
(entry below, commit b242989) into `lab1-container-ci`.

**Done.** `restart_bots.py --stocks` at 11:36 ET, market open. All twelve
stock bots restarted, identity verified by the script before and after, all
online in pm2 with a restart count of 1.

**Measured, from the logs, 11:36 to 11:43 ET.**

- Every bot logged `Watchdog: exits if the loop stalls for 600s beyond its
  sleep`, so every bot is on the new code.
- Every bot completed 8 loop ticks, one a minute, fetching live bars through
  the new timeout. No ERROR, WARNING or CRITICAL line in any of the twelve
  logs. This is the live run the entry below said had not happened.
- No bot traded in those 8 ticks.
- `slv-bot`, frozen since Nov 3, loaded its LONG position (entry 45.10,
  2.217295 shares) and is holding: 47.05 on its first tick, +4.32%, inside its
  5% stop and 8% target. Its exits are evaluated every minute again. The
  replay in the 2026-11-10 entry had this trade out on Nov 4 at +4.78%; the
  live bot missed that exit and its eventual exit will be a different one. v4
  is already concluded, so this changes nothing there.
- `meta-bot`, frozen since Nov 4, is flat and evaluating entries again.
- The ten flat bots each created `logs/signal_log_stock-<ticker>.csv`. After
  three ticks META's held one row, for the 16:00 UTC bar: one row per hourly
  bar, as intended. "Could not record signal decision" no longer appears.

**How the restart was run.** `restart_bots.py` passes the calling shell's
environment to pm2. It was run under `env -i` with only HOME, USER, LOGNAME,
SHELL, LANG and PATH, so that nothing from the Claude session that ran it was
copied into the bots.

**Found, not changed.** The twelve bots' pm2 environments already hold
`CLAUDE_*` variables from some earlier session, including an old messaging
token. None matches the session that ran this restart. They have no effect on
trading. pm2 only adds to a process's environment on restart, so removing them
means deleting and re-registering the bots. Lee's call.

**Still open from the entry below:** autorestart is off on `spy-bot`,
`qqq-bot` and `lpl-bot`; the trade email has no timeout; the dashboard has not
been looked at with the new signal files; nothing is pushed.

---

## 2026-11-11 — stock_bot.py: the freeze and the `bars` name are fixed in code; nothing is restarted

**Asked:** Lee, to fix the two defects recorded on 2026-11-10 (two entries
below). Code and tests only. No strategy parameter, entry rule or exit rule is
changed. No pm2 process was restarted, so **all twelve bots are still running
the old code** and `slv-bot` and `meta-bot` are still frozen. The fix takes
effect for a bot when Lee restarts it.

**1. The freeze: every Alpaca request now times out.** alpaca-py 0.43.5 (the
version in `.venv`) has no timeout setting. Its `RESTClient` calls
`self._session.request(method, url, **opts)` and `opts` never carries one, so
a connection that dies without closing is waited on for ever. The fix is a
requests transport adapter on that session which fills in a timeout when none
was given (`utils/alpaca_http.py`): 10 seconds to connect, 30 seconds for the
next bytes of a reply. A dead connection now raises, the bot's existing
handling logs it, and the loop tries again on its next tick.

- `stock_bot.py` builds its clients in two places only, `_data_client()` and
  `_trading_client()`, both with the timeout. They serve `fetch_bars`,
  `is_market_open` and the live branch of `place_sell`.
- `AlpacaVenue.client()` in `utils/venue.py` has it too. That is the client
  behind the live branch of `place_buy` and startup reconciliation, and
  `fcr_bot.py` uses the same class.
- `_session` is private to alpaca-py. If an upgrade moves it, `with_timeout`
  raises instead of handing back an unprotected client, and a test fails.
- The two numbers can be changed with `ALPACA_CONNECT_TIMEOUT_SEC` and
  `ALPACA_READ_TIMEOUT_SEC`. Zero, a negative or a typo falls back to 10 and
  30; the timeout cannot be switched off from `.env`.

**2. Second layer: a watchdog.** The read timeout bounds the wait for the next
bytes, not the whole request, and not every blocking call in the loop is an
Alpaca request. So the loop now reports to a watchdog thread
(`utils/watchdog.py`) before every sleep, saying how long the sleep is. If the
loop has not come back 600 seconds after that sleep should have ended, the
watchdog logs `WATCHDOG:` with the main thread's stack (where it was stuck)
and exits the process with code 70. `STOCK_WATCHDOG_TIMEOUT_SEC` changes the
600; 0 switches it off.

- What happens next depends on pm2. Nine bots have autorestart on and will
  come back by themselves. **`spy-bot`, `qqq-bot` and `lpl-bot` were started
  with `--no-autorestart`**: for those three a watchdog exit leaves the bot
  stopped. That is visible in `pm2 status`, which a freeze was not, but it is
  not a restart. Changing it means re-registering those three; not done, Lee's
  call.
- A watchdog restart is a restart like any other: the bot re-reads `.env`, so
  it picks up any tuning change made since it last started, and it acts at
  once on its saved position. With a 10-minute limit that position is at most
  about 10 minutes unwatched, against a week.

**3. `bars` → `df`.** Three lines in the main loop used a name that did not
exist. Two were the volume filter, now reading `df['volume']`. The third was
the signal log's candle time, `str(bars.index[-1])`. Swapping the name alone
would have been wrong there: `fetch_bars` returns `df.tail(n).reset_index()`,
so the index is row numbers and the timestamp is a column. The log keeps one
row per candle time, so a row number would have written one row and then
nothing. It now uses `latest_bar_time(df)`, which reads the `timestamp` column
and raises if there is none.

**What changes when a bot restarts on this code.**

- A flat stock bot starts writing `logs/signal_log_stock-<ticker>.csv`. None
  of those files exists today. The dashboard prefers that file to scraping the
  pm2 log, so the source of the "signal" it shows for flat stock bots changes.
  Not checked on the running dashboard.
- The log records the **first** evaluation of each hourly bar. The bot
  evaluates the bar still forming, every minute, so an entry that triggers
  later in the hour is in the trade ledger but its signal-log row says HOLD.
  That is how the shared logger deduplicates and it is not changed here.
- The volume filter no longer crashes. It is still off
  (`STOCK_MIN_VOLUME_RATIO` defaults to 0) and this entry does not turn it on.

**Tests.** `tests/test_stock_bot_freeze_and_bars.py`, 31 tests. The freeze is
tested against the thing itself: a local server that accepts a connection and
never answers (a real alpaca-py client raises a timeout in under a second
instead of blocking), and a child process blocked in a socket read (it exits
with code 70 and names the function it was stuck in). The `bars` fix is tested
by running the bot's real `main()` for one pass with only the clock, the bars,
the state file and the sleep replaced, and by parsing a real Alpaca-shaped
response to confirm the timestamp is a column. Against the old `stock_bot.py`
14 of the 31 fail. Full suite: 549 passed, 3 skipped (518 before, plus 31; the
3 skips need data files this checkout does not have).

**Not done, not verified.**

- Not run against the live Alpaca API or under pm2. The first restart is the
  first real run.
- `utils/notifications.py` opens its SMTP connection with no timeout, and the
  bot sends mail inside `place_buy` and `place_sell`, before the state file is
  written. A mail server that hangs would block the loop there. The watchdog
  now ends that after 10 minutes; a timeout on the SMTP call would be the
  proper fix. The module is shared with the crypto bots, so it was left alone.
- `dashboard.py` builds its own `TradingClient` for the market clock with no
  timeout. Outside the bot loop, not changed.
- The crypto bots (`bot.py`) were not examined for the same defect.

**To deploy (Lee).** The commit is on branch `claude/gallant-panini-22db10`;
the bots run from the main checkout, which is on `lab1-container-ci`. From
`/home/leeunks/coinbase-trading-bot`:

    git merge --ff-only claude/gallant-panini-22db10
    .venv/bin/python restart_bots.py --check
    .venv/bin/python restart_bots.py --stocks

or name bots instead of `--stocks` to do it in stages, e.g.
`restart_bots.py slv-bot meta-bot`. Never `pm2 restart --update-env` by hand.
`slv-bot` will act on its Nov 3 position (entry 45.10) on its first tick.
Nothing is pushed.

---

## 2026-11-10 — v5 market-gate backtest result: the trend gate passes its test, the down-day gate is refuted, and the edge is thin

**Asked:** Lee, "Step 1". Run on the terms fixed in the entry two below, which
was committed (dfbc9e7) before any gated run. `backtest_regime_gate.py`,
5,856,619 one-minute IEX bars, twelve tickers, 2020-07-27 to 2026-11-10,
$100 a trade, 0.10% slippage a side. Backtested, not measured.

**1. The replay is the bot.** Ungated, no slippage, against the live ledger:

```
live ledger          n=  48  win  66.7%  avg win +2.18%  avg loss -5.25%  PF  0.83  net $  -14.30
replay, same window  n=  50  win  68.0%  avg win +2.33%  avg loss -5.27%  PF  0.94  net $   -5.04
live trades 48 | replay trades 50 | same entry within 2h: 45 | of those, same exit within 2h: 43
matched pairs, replay minus live result: mean -0.007%  median +0.000%  largest gap -0.42%
```

Minute-built hourly bars equal Alpaca's hourly bars exactly (3,108 bars
compared on SPY, DIS, LPL). The two extra replay trades are trades the live
bots could not take because two of them were frozen; see the entry below.

**2. Independent test, entries 2021-01-04 to 2026-09-03.**

```
baseline (v4 as it ran)            n=1343  win  69.5%  avg win +2.17%  avg loss -5.08%  PF  0.97  net $  -55.96  avg -0.04%  worst -13.33%
A  trend 50d                       n= 915  win  71.7%  avg win +2.09%  avg loss -4.78%  PF  1.10  net $ +129.20  avg +0.14%  worst -12.51%
B  trend 50d or down 1.0%          n= 863  win  70.6%  avg win +2.02%  avg loss -4.74%  PF  1.02  net $  +23.90  avg +0.03%  worst -12.27%

baseline trades split by the gate's state at entry:
  kept by both                     n= 770  win  70.6%  PF  1.04  net $  +44.65  avg +0.06%
  blocked by trend                 n= 449  win  65.0%  PF  0.79  net $ -182.48  avg -0.41%
  blocked by down day only         n= 124  win  78.2%  PF  1.53  net $  +81.87  avg +0.66%

by year (entries):  baseline | A | baseline trades A blocks
  2021  base n=227 PF 1.20 $  +54.89 | A n=211 PF 1.20 $  +51.98 | A blocks n= 18 $   -1.54
  2022  base n=305 PF 0.69 $ -202.56 | A n=101 PF 0.72 $  -56.46 | A blocks n=207 $ -152.28
  2023  base n=192 PF 0.87 $  -39.80 | A n=127 PF 0.86 $  -24.70 | A blocks n= 66 $  -15.45
  2024  base n=209 PF 1.24 $  +62.53 | A n=184 PF 1.29 $  +65.82 | A blocks n= 30 $   +9.71
  2025  base n=224 PF 1.18 $  +53.19 | A n=157 PF 1.49 $  +77.50 | A blocks n= 72 $  -13.35
  2026  base n=186 PF 1.05 $  +15.79 | A n=135 PF 1.07 $  +15.08 | A blocks n= 56 $   -9.57
```

**3. Verdict on the fixed terms.**

```
A: 1 net higher than baseline: yes ($+129.20 vs $-55.96) | 2 PF >= baseline+0.10 and >= 1.00: yes (1.10 vs 0.97) | 3 blocked trades lose in 2/3 of years with 10+: yes (5 of 6)  => PASS
B: 1 net higher than baseline: yes ($+23.90 vs $-55.96) | 2 PF >= baseline+0.10 and >= 1.00: NO (1.02 vs 0.97) | 3 blocked trades lose in 2/3 of years with 10+: NO (3 of 6)  => FAIL
CHOICE: A
```

A, the trend gate alone, is the v5 proposal. It is not registered; that needs
Lee's OK.

**4. The down-day lead from the stop-out study was wrong.** Measured at the
moment of entry instead of with the full day's move, trades taken while SPY
was down more than 1% were the best group in the test (124 trades, 78.2% wins,
PF 1.53) and all four of them in the Sep to Nov window were winners. The
study's "7 trades, PF 0.32" was the look-ahead it was flagged for. Dropped.

**5. What the pass is worth. Less than the headline.** Description after the
fact; none of it was used to choose.

```
baseline  per-trade Sharpe -0.011 | 1343 pooled = 548 effective trades | t -0.26 effective | $-9.88 a year on up to $1200 deployed
A         per-trade Sharpe +0.039 |  915 pooled = 374 effective trades | t +0.76 effective | $+22.82 a year on up to $1200 deployed
A, no slippage (ledger)        n= 915  win  75.5%  PF  1.26  net $ +312.64  avg +0.34%
baseline, no slippage (ledger) n=1343  win  72.4%  PF  1.11  net $ +212.80  avg +0.16%
A, 2022 entries left out       n= 814  win  73.0%  PF  1.18  net $ +185.67  avg +0.23%
consecutive 48-trade runs, ledger figures, passing BOTH shape rules: A 14 of 19 | baseline 15 of 27
sessions with entries switched off by the trend rule: 391 of 1424 (27%), longest stretch 60 sessions
against not trading, per symbol: A +10.77% vs hold +71.13% | gate convention: A +129.20% vs hold +69.37% | in market 30.2% of the time
```

- The gate's gain is mostly one year. Of the $182 the blocked trades lost,
  $152 is 2022. In the other five years it moves the result by a few dollars
  either way. It is a bear-market switch, which is what it was meant to be,
  but the evidence for it is one bear market.
- A still lost money in 2022 and 2023 (PF 0.72 and 0.86). The gate shrinks the
  loss; it does not make the entries work in a weak year.
- The gated edge is not distinguishable from zero: t 0.76 on effective trades.
- The edge is the size of the cost assumption. Ungated v4 is PF 1.11 with no
  slippage and 0.97 with 0.10% a side. The live ledger records signal prices,
  so it sees the no-slippage figure. Paper fills have never been compared
  with signal prices; that is a gap.
- Against holding the same twelve symbols A makes about a seventh as much per
  symbol while in the market 30% of the time. The gate convention (all twelve
  symbols' P&L over one $100 position) is the only framing in which it beats
  holding, and it flatters.
- On v4's own window the trend gate would have blocked 9 trades that lost
  $12.60. Scored the way the observer scores (ledger prices, exits from
  Sep 4) the gated replay is 44 trades, 68.2% wins, PF 1.01, against 50
  trades, 68.0%, PF 0.94 ungated. That is under the 70% win floor and a hair
  over the PF floor: v5 would also have failed over those ten weeks, by less.
- The Sep 21 backtest behind v4's shape rules (72%, PF 1.12) covered roughly
  the last 400 days. This run puts 2025 at PF 1.18 and 2026 at 1.05, so that
  backtest was right about its period and the period was a good one.

**Sensitivity (reported, not used):** trend average 20d PF 1.09, 50d 1.10,
100d 1.09, 200d 1.01 (no 200-day average exists before May 2021 in this
data). Not a knife-edge at 50.

**Not done:** no bot, config or registration was touched. Tests: 520 passed,
10 new in `tests/test_regime_gate.py` (replay RSI equals the bot's at any
minute; nothing after the decision moment changes the view or the gate).
Bar cache is in `scratch/regime_gate_cache` (git-ignored, 269 MB).

**Next, Lee's call:** register v5 = v4 plus the trend gate, in paper, with
shape rules re-derived from this run; or decide the edge is too thin to spend
two more months on and go to the basket question first.

---

## 2026-11-10 — Two stock bots frozen since Nov 3 and Nov 4; v4 verdict stands

**Found:** while checking the replay against the ledger. The replay took two
trades the live run did not: SLV out on Nov 4 (+4.78%) and META Nov 5 to 6
(+2.50%).

**Cause.** `slv-bot` last logged at 2026-11-03 11:39:14 ET and `meta-bot` at
2026-11-04 15:01:07 ET, both on the line `--- market check ---`, each a few
minutes after a failed connection to `data.alpaca.markets` (11:37:58 and
14:53:37). Both processes are online in
pm2, asleep in a socket read on an established connection (kernel wait
`wait_woken`; a healthy bot sits in `do_select`). `fetch_bars` in
`stock_bot.py` makes its request with no timeout, so a connection that dies
without closing blocks the loop for good. pm2 sees a live process and does
nothing.

**Effect.**

- SLV has been LONG since Nov 3 (entry 45.10) with nothing watching its stop
  or its exits for a week. Paper, so no money, but the 2026-11-10 note that
  the open positions "need their stops watched" was wrong for this one.
- META has been flat and blind since Nov 4.
- The v4 stopping rule allows a fix for "a defect that stops trades executing
  or makes an exit unable to fire". This was one, unnoticed, on two of twelve
  bots for the last week of the run.
- The verdict does not change. With both bots working the replay gives 50
  trades, 68.0% wins, PF 0.94 at ledger prices, against the sealed floors of
  70% and 1.00. v4 fails either way, by less than the ledger shows.

**Also found:** `stock_bot.py` lines 651, 661 and 662 use a name `bars` that
does not exist (the frame is `df`). The signal log for a flat bot has failed
on every loop since at least Aug 27 with "Could not record signal decision"
(5,556 times in the SPY log), and the volume filter would crash if it were
ever switched on. No effect on trades, because the error is caught and the
volume filter is off.

**Not done:** nothing restarted, no code changed. Restarting a bot makes it
act at once on a week-old position, which is Lee's call. The fix (a timeout on
the data request, the `bars` name) is a code change to the bots and is
separate from the gate test.

**Correction to earlier messages:** the Nov 5 and Nov 10 entries were
committed on the branch `lab1-container-ci`, which was checked out, while the
push went to `main`. They were not pushed, although Lee was told they were.
They are local commits; nothing from Nov 5 on is on GitHub.

---

## 2026-11-10 — v5 market-gate backtest: rule and pass/fail test fixed before the run

**Asked:** Lee, "Step 1" of the plan in the entry below: test one change to v4,
a market gate on new entries, on old data. This entry is written and committed
before any gated simulation has been run. The result goes in a separate entry
above this one; this one is not edited afterwards.

**Which data is the real test.** The gate was found on the v4 live trades
(entries Sep 4 to Nov 10). Those trades cannot also confirm it. The data from
before Sep 4 has never been looked at with this rule, so it is the independent
test. The Sep 4 to Nov 10 window is run afterwards for two narrower purposes:
to check the simulator against the live ledger, and to see the causal version
of the rule on the trades it came from. It is not independent evidence. This
corrects the wording of the Nov 5 plan, which called that window a walk-forward.

**Data.** Alpaca one-minute bars, IEX feed, split and dividend adjusted,
2020-07-27 (first available) to 2026-11-10 14:00 UTC, the twelve v4 tickers.
Fetched once and frozen for the run.

**Simulator.** A minute-by-minute replay of the live loop in `stock_bot.py`,
not the hourly-close shortcut used on Sep 21: hourly bars built on clock hours
including the bar still forming, RSI 14, entry when the last completed bar is
under 35 and the forming bar is at or above it, checks only while the market
is open. Exits exactly as v4: 5% stop, 8% target, 1.5% trail armed at +1%,
RSI exit through 65, trail and RSI exit blocked below entry. $100 a trade,
0.10% slippage a side (the project's backtest convention). Before any gated
run the ungated simulator is compared with the 48 live trades.

**The gate, two parts, numbers taken from the stop-out study and not tuned:**

- Trend: no new entry when SPY's close on the last completed session is below
  the average of its last 50 completed session closes.
- Down day: no new entry when SPY's latest price at the moment of the signal is
  more than 1.0% below its close on the last completed session.

Both use only prices known at the moment of the signal. Exits are never gated.

**Candidates.** Baseline: v4 as it ran. A: trend only. B: trend or down day.

**Test window.** Entries from 2021-01-04 to 2026-09-03.

**A candidate passes only if all three hold in the test window, gated run
against baseline run on the same data and costs:**

1. Net P&L is higher than baseline.
2. Profit factor is at least 0.10 above baseline and at least 1.00.
3. The baseline trades the gate would have blocked lose money as a group in at
   least two thirds of the calendar years that have ten or more of them.

**Choosing.** Both pass: A, unless the baseline trades blocked by the down-day
part alone have a profit factor under 1.00, then B. One passes: that one.
Neither passes: no v5 from this gate. The conclusion is then that these
entries have no edge a market filter can rescue, and the basket is what to
rethink.

**Reported but never used to choose:** trend averages of 20, 100 and 200 days,
down-day thresholds of 0.5%, 1.5% and 2.0%, results by year and by ticker,
excess against buy-and-hold on the ledger convention, time in the market.

**What a pass would and would not mean.** A pass makes the gate the v5 proposal
for Lee to approve and register. It does not show v5 makes money. v4 also had a
passing backtest (72% wins, profit factor 1.12 on Sep 21) and failed live.

---

## 2026-11-10 — Stop-out study on v4's 16 stops: the stop is right, the entries in a weak market are wrong

**Asked (2026-11-05 plan, step 3):** before designing v5, find out which of
three things the stops are: a stop that is too tight, an entry that is wrong,
or a market condition. Read-only study of the 48 registration trades against
Alpaca hourly and daily bars (IEX feed, dividend-adjusted). In-sample, 16
stops, about 20 effective trades: every figure below is a lead to test, not a
result.

**1. The stop is not too tight.** After a stop the price mostly kept going.

```
after the stop, close vs exit price: +1d median 0.28 +3d 0.72 +5d -0.61 +10d -2.26
higher 5d later: 6 of 13 | traded back above ENTRY within 5d: 1 of 13 | within 10d: 3 of 12 | median further low within 5d: -1.71
```

Only TSLA (Oct 16) recovered its entry inside five days. Same answer as the
Oct 1 wick study: stock stops are real moves, not noise.

**2. A tighter stop and a time exit both make it worse** on these trades.

```
actual (5% stop)             win rate  66.7%  avg win +2.18%  avg loss -5.25%  PF 0.83  sum of net%  -14.30  stops 16
stop at 4%                   win rate  64.6%  avg win +2.18%  avg loss -4.25%  PF 0.93  sum of net%   -4.70  stops 17
stop at 3%                   win rate  52.1%  avg win +2.15%  avg loss -3.25%  PF 0.72  sum of net%  -21.03  stops 23
stop at 2%                   win rate  43.8%  avg win +2.33%  avg loss -2.25%  PF 0.81  sum of net%  -11.79  stops 27
time exit at 3 days          win rate  43.8%  avg win +2.05%  avg loss -2.60%  PF 0.61  sum of net%  -27.20  stops  4
time exit at 5 days          win rate  45.8%  avg win +2.17%  avg loss -3.28%  PF 0.56  sum of net%  -37.38  stops  8
time exit at 7 days          win rate  54.2%  avg win +2.19%  avg loss -3.66%  PF 0.71  sum of net%  -23.59  stops 10
time exit at 10 days         win rate  64.6%  avg win +2.17%  avg loss -5.01%  PF 0.79  sum of net%  -18.06  stops 12
winners whose low went past -3% before winning: 7 of 32 | past -4%: 1 | past -2%: 12
```

Winners take a median 6.05 days (p90 11.8) and 7 of 32 dipped past -3% first,
so cutting earlier in price or in time kills winners faster than it saves on
losers. The 3% stop floated on Nov 5 is withdrawn. No variant clears PF 1.0.

**3. Half the stops had been ahead, but a break-even stop does not rescue it.**
Best point reached before the stop: 4 stops under +0.5%, 4 at +0.5 to +1%,
4 at +1 to +2%, 4 at +2 to +3% (median +1.19%).

```
break-even stop after +1.0%   PF 0.95  sum net%   -2.08   losers turned into scratches: 8 | winners cut to scratch: 14
break-even stop after +1.5%   PF 0.81  sum net%  -11.24   losers turned into scratches: 5 | winners cut to scratch: 10
break-even stop after +2.0%   PF 0.84  sum net%   -9.86   losers turned into scratches: 4 | winners cut to scratch: 6
break-even stop after +3.0%   PF 0.81  sum net%  -15.83   losers turned into scratches: 0 | winners cut to scratch: 1
```

Winners revisit their entry price too often on the way up. Not a fix.

**4. The losses are a market-condition problem.** 13 of 16 stops had SPY
negative over the hold; 7 of 16 fell on days SPY lost more than 1%; 7 of 16
came on days with two or more stops (Sep 30, Oct 16, Nov 5). Split by the
market at ENTRY:

```
all                                n=48  win rate  66.7%  avg net -0.30%  PF 0.83  net $-9.08  stops 16
SPY above its 50-day at entry      n=40  win rate  70.0%  avg net +0.02%  PF 1.02  net $+6.19  stops 12
SPY below its 50-day at entry      n= 8  win rate  50.0%  avg net -1.91%  PF 0.34  net $-15.27  stops 4
SPY down >1% on entry day          n= 7  win rate  42.9%  avg net -1.97%  PF 0.32  net $-13.82  stops 4
SPY not down >1% on entry day      n=41  win rate  70.7%  avg net -0.01%  PF 0.99  net $+4.74  stops 12
ticker above its own 50-day        n=23  win rate  60.9%  avg net -0.71%  PF 0.64  net $-14.07  stops 9
ticker below its own 50-day        n=25  win rate  72.0%  avg net +0.08%  PF 1.05  net $+4.99  stops 7
blocked by EITHER filter           n=15  win rate  46.7%  PF 0.33  sum net%  -29.08
kept if both filters applied       n=33  win rate  75.8%  PF 1.36  sum net%  +14.78
```

The two SPY filters do not overlap (0 trades in both). Fifteen trades taken in
a weak market lost twice the run's entire loss; the other 33 would have passed
both shape rules. The ticker's own trend does not help and points the other
way.

**What this is not.** It is in-sample, on about 14 effective trades, chosen
after the fact. The "down >1% on entry day" split uses the full day's
close-to-close move, which is not known at the moment of entry: as measured it
has look-ahead, and a real rule must use the move from the prior close to the
entry time. The 50-day split uses the prior day's close and is causal. Bars
are dividend-adjusted while fills are not, so moves are off by a dividend
(under 0.5%) on the ETFs.

**5. Stop mechanics.** 6 of 16 exits came in the first 15 minutes of a session
(overnight gaps). Average slip past the 5% line is -0.25%; the worst, SLV on
Oct 30, gapped to -7.54%. A stop cannot fix a gap; position count on gap days
can.

**Conclusion for v5:** keep the 5% stop and the exits. Test ONE change: a
market-regime gate on new entries (SPY below its 50-day average, and/or SPY
down more than 1% from the prior close at the time of entry). Backtest on data
to 2026-09-03 only, with the rule fixed before the run, then walk forward
Sep 4 to Nov 10 without touching it. If the gate does not show up
out-of-sample, the honest reading is that v4's entries have no edge and the
basket is the thing to rethink, not the exits.

---

## 2026-11-10 — Stocks mean-reversion v4 concluded: failed on its own terms

**What happened:** the observer reached the registered stop at its 10:12 run
(20 effective trades of 20, 48 pooled) and sent the one email it is allowed
to send. `Registration stopping rule reached` (stop) and `Shape rule breached`
(warn). The registration is concluded with seal intact; nothing was changed
during the run.

**Result, registration window only (exits 2026-09-08 to 2026-11-10), computed
with `utils.graduation.evaluate` and `utils.benchmark`:**

```
closed 48 · wins 32 · losses 16 · win rate 66.7%
avg win +2.178% · avg loss -5.25% · profit factor 0.83
net P&L -$9.08 realized · 2 open at the stop, +$3.52 unrealized
worst trade -7.54% · per-trade Sharpe -0.081
strategy -9.08% vs buy-and-hold -4.99% -> excess -4.09%
exits: RSI fell back through 65: 24 · Stop Loss Triggered: 16 · Trailing Stop: 8
per ticker ($): DIS +6.63 · JNJ +2.59 · LPL -2.25 · META -2.90 · PG +3.46 · QQQ -5.12
                SLV -12.58 · SPY -2.84 · TSLA -3.75 · WMT +8.28 · XLP +3.68 · XLU -4.27
```

| Sealed term | Required | Measured | |
|---|---|---|---|
| Primary: pooled excess vs buy-and-hold | > 0 | -4.09% | fail |
| Shape: win rate | >= 70% | 66.7% | fail |
| Shape: profit factor | >= 1.00 | 0.83 | fail |
| Win rate (generic floor) | >= 55% | 66.7% | pass |
| Net P&L | > 0 | -$9.08 | fail |
| Per-trade Sharpe | >= 0.35 | -0.081 | fail |
| Worst trade | >= -2.5% | -7.54% | fail |

**Verdict:** failed. The hypothesis (a positive per-trade edge that beats
buy-and-hold) is not supported. Per the registration's own power caveat this
does not prove the strategy loses money; 20 effective trades can rule out a
large edge, and it has.

**Two things to read carefully.** (1) The buy-and-hold figure uses the gate's
ledger convention: pooled P&L over one $100 position, against an equal-weight
hold from each symbol's first entry to its last exit. On the $1,200 actually
deployed the loss is 0.76%. Either way it is not a pass. (2) The worst trade
of -7.54% is past the 5% stop, so at least one exit gapped through the stop
line; that goes into the stop-out study.

**Not changed:** the twelve stock bots are still running in paper with the
same configuration, and two positions are open. Trades from here are outside
any registration and are not evidence for or against v4. Whether to leave the
bots running until v5 is registered is the owner's call.

**Next, per the 2026-11-05 plan:** the stop-out study on the 16 stops, then
v5 candidates backtested on data to 2026-09-03 and walked forward.

---

## 2026-11-05 — v4 will fail its shape rules; the plan for what follows

**Status at 2026-11-05 (ledger since 2026-09-04, `ai_platform.ledger.summarise`):**
41 closed, 27 wins / 14 losses, win rate 65.9%, avg win +2.305%, avg loss
−5.283%, profit factor 0.841, net −$11.73, breakeven win rate for this shape
69.6%. Observer: 46 pooled ≈ 19 effective of 20, verdict ≈ 2026-11-08. Three
stop-outs today, the third cluster of correlated stops (Oct 16, Oct 20, Nov 5).
Exit mix: 21 RSI reverts, 14 stop-outs, 6 trailing stops.

**Asked:** whether the next iteration will "put something in" so the strategy
stops losing. **Answer given:** no. The stop loss is the brake and is working;
the 14 stops are the entry being wrong 34% of the time. What a new design can
change is the cost of a wrong trade relative to a right one.

**Plan agreed:**

1. Let v4 reach 20 effective trades (~Nov 8). No change before then; a change
   voids the registration.
2. Conclude v4 with the verdict and the numbers above. It will fail the
   registered shape rules (win rate ≥70%, PF ≥1.0).
3. Stop-out study on the 14 stops before any design work: MFE before the
   reversal; price path 5 days after the stop; how many fell on days SPY was
   down >1%. Those three answers choose between "entry is wrong", "stop is too
   tight" and "needs a market filter".
4. Backtest two or three v5 candidates on data to 2026-09-03 only, then walk
   forward Sep 4 – Nov 8 untouched: a SPY regime filter (below 50-day, or down
   >1% on the day), a ~3% stop (breakeven win rate ≈57%), a time exit for
   trades that have not reverted in N days.
5. Pre-register v5 with the six criteria plus the shape rules; 20 effective
   trades again (six to eight weeks).

**Stated plainly:** 65% win rate with +2.3% winners is normal for RSI mean
reversion. v5 tries to buy down the cost of the asymmetric loss, not remove
it. At 19 effective trades the profit factor has wide error bars; the verdict
is "did not pass its own rules", not "the strategy loses money".

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
