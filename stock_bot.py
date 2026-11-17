#!/usr/bin/env python3
"""
stock_bot.py — SMA Crossover Stock Trading Bot (Alpaca)

Same strategy logic as the crypto bot (SMA crossover + RSI filter) but
runs against the Alpaca Markets API for US equities.

Key differences vs crypto bot:
  - Market hours gate: only trades 9:30am–4:00pm ET, Mon–Fri
  - No 24/7 market — bot sleeps outside market hours
  - Commission-free via Alpaca — fee hurdle is near zero
  - Paper trading via paper-api.alpaca.markets (set ALPACA_PAPER=True)
  - Fractional shares supported — $10/trade works fine

PM2 launch (one per ticker):
  STOCK_TICKER=SPY TRADE_AMOUNT_USD=10 ALPACA_PAPER=True \\
    pm2 start stock_bot.py --name spy-bot --interpreter .venv/bin/python --no-autorestart

  STOCK_TICKER=QQQ TRADE_AMOUNT_USD=10 ALPACA_PAPER=True \\
    pm2 start stock_bot.py --name qqq-bot --interpreter .venv/bin/python --no-autorestart

  STOCK_TICKER=LPL TRADE_AMOUNT_USD=10 ALPACA_PAPER=True \\
    pm2 start stock_bot.py --name lpl-bot --interpreter .venv/bin/python --no-autorestart

Execution modes (utils/execution_mode.py, live_trading_stocks.md):
  simulated     ALPACA_PAPER=True, as above. No order is sent; the ledger
                records the signal price. What the registered bots run.
  broker paper  Real orders to Alpaca's paper account, state and ledger from
                the fills. Started through broker_paper_bot.py, never this file.
  live          The same order path, real money. Started through live_bot.py,
                never this file: ALPACA_PAPER=False here is refused.
"""
import os
import sys
import csv
import json
import time
import logging
from datetime import datetime, timezone, timedelta

import pandas as pd
from dotenv import load_dotenv  # noqa: F401  (kept for compatibility)
from utils.env_loader import load as load_config

# ── Load .env ─────────────────────────────────────────────────────────────────
# .env wins for tuning, the pm2 command line wins for identity. A plain
# load_dotenv would leave stale values in place and a restart would silently
# change nothing.
_CHANGED = load_config()

# ── Configuration from environment ───────────────────────────────────────────
TICKER          = os.getenv("STOCK_TICKER", "SPY").upper()

# Confirm this process is the bot its pm2 name claims before TICKER is baked
# into the log file, state file and trade file below. Checked here rather than
# after logging is configured, because a wrong ticker sends the complaint into
# the wrong bot's log.
from utils import identity as _identity
_identity.enforce(TICKER)
TRADE_AMOUNT    = float(os.getenv("TRADE_AMOUNT_USD", 10))
IS_PAPER        = os.getenv("ALPACA_PAPER", "True").strip().lower() not in ("false", "0", "no")

# Three execution modes (utils/execution_mode.py). Simulated is the default and
# sends nothing. Broker paper sends real orders to Alpaca's paper account and
# live sends them to the real one; each is reached only through its own entry
# script (broker_paper_bot.py, live_bot.py), never through an environment
# variable.
from utils import execution_mode as _execution_mode
if _execution_mode.REQUESTED not in (None, _execution_mode.BROKER_PAPER,
                                     _execution_mode.LIVE):
    sys.exit(f"Unknown execution mode {_execution_mode.REQUESTED!r}; refusing to start.")
BROKER_PAPER    = _execution_mode.REQUESTED == _execution_mode.BROKER_PAPER
LIVE            = _execution_mode.REQUESTED == _execution_mode.LIVE
if BROKER_PAPER and not IS_PAPER:
    sys.exit("Broker-paper mode with ALPACA_PAPER=False: that would send paper-mode "
             "orders to the live endpoint. Refusing to start.")
if LIVE and IS_PAPER:
    sys.exit("Live mode with ALPACA_PAPER not false: that would send live-mode "
             "orders to the paper endpoint. Refusing to start.")
if not IS_PAPER and not LIVE:
    # ALPACA_PAPER=False used to be all it took to make this script send
    # real-money orders, and an environment variable can arrive by accident
    # (a restart with --update-env, a line in .env).
    sys.exit("REFUSING TO START: ALPACA_PAPER is false, and stock_bot.py no longer "
             "trades live on an environment variable. A live bot is started with "
             "live_bot.py (live_trading_stocks.md). A simulated bot needs "
             "ALPACA_PAPER=True.")
if LIVE and not (0 < TRADE_AMOUNT <= _execution_mode.LIVE_MAX_TRADE_USD):
    sys.exit(f"REFUSING TO START: live trade size ${TRADE_AMOUNT:,.2f} is outside "
             f"$0 to ${_execution_mode.LIVE_MAX_TRADE_USD:,.0f} "
             f"(utils/execution_mode.py, LIVE_MAX_TRADE_USD).")
# True when this process sends orders to a broker. Everything the simulated
# bots do is on the False side of it.
SENDS_ORDERS    = BROKER_PAPER or LIVE

# A live bot reads its own key pair. ALPACA_API_KEY is the paper key that every
# simulated bot reads from .env, so live cannot share the name: putting a live
# key there would hand it to all of them.
if IS_PAPER:
    API_KEY     = os.getenv("ALPACA_API_KEY", "")
    SECRET_KEY  = os.getenv("ALPACA_SECRET_KEY", "")
else:
    API_KEY     = os.getenv("ALPACA_LIVE_API_KEY", "")
    SECRET_KEY  = os.getenv("ALPACA_LIVE_SECRET_KEY", "")
BASE_URL        = os.getenv("ALPACA_BASE_URL",
                            "https://paper-api.alpaca.markets" if IS_PAPER
                            else "https://api.alpaca.markets")

# SMA windows — stocks have smaller % moves than crypto, so tighter windows
SMA_SHORT       = int(os.getenv(f"{TICKER}_SMA_SHORT_WINDOW",  os.getenv("STOCK_SMA_SHORT_WINDOW",  "10")))
SMA_LONG        = int(os.getenv(f"{TICKER}_SMA_LONG_WINDOW",   os.getenv("STOCK_SMA_LONG_WINDOW",   "30")))
STOP_LOSS_PCT   = float(os.getenv(f"{TICKER}_STOP_LOSS_PERCENT",  os.getenv("STOCK_STOP_LOSS_PERCENT",  "3.0")))
TAKE_PROFIT_PCT = float(os.getenv(f"{TICKER}_TAKE_PROFIT_PERCENT", os.getenv("STOCK_TAKE_PROFIT_PERCENT", "5.0")))
RSI_MIN         = float(os.getenv("STOCK_RSI_BUY_MIN", "40"))
RSI_MAX         = float(os.getenv("STOCK_RSI_BUY_MAX", "70"))
LOOP_INTERVAL   = int(os.getenv("STOCK_LOOP_INTERVAL_SEC", "60"))
CANDLE_BARS     = int(os.getenv("STOCK_CANDLE_BARS", "100"))  # 1h bars to fetch
TRAILING_STOP_PCT = float(os.getenv(f"{TICKER}_TRAILING_STOP_PERCENT", os.getenv("STOCK_TRAILING_STOP_PERCENT", "0.0")))
TRAILING_ACTIVATION_PCT = float(os.getenv(f"{TICKER}_TRAILING_STOP_ACTIVATION_PERCENT", os.getenv("STOCK_TRAILING_STOP_ACTIVATION_PERCENT", "0.0")))
MIN_VOLUME_RATIO = float(os.getenv(f"{TICKER}_MIN_VOLUME_RATIO", os.getenv("STOCK_MIN_VOLUME_RATIO", "0.0")))
COOLDOWN_HOURS = float(os.getenv(f"{TICKER}_COOLDOWN_HOURS_AFTER_LOSS", os.getenv("STOCK_COOLDOWN_HOURS_AFTER_LOSS", "0.0")))

# Market trend gate on new entries (stocks v5): no new position while the market
# symbol's last completed session closed below the average of its last N
# completed session closes. Exits are never gated. 50 and SPY are the registered
# v5 terms (experiments/, DECISIONS.md 2026-11-10 and 2026-11-16), fixed before
# the backtest and not tuned; changing either voids the registration. 0 = off,
# which is v4.
TREND_GATE_DAYS   = int(os.getenv("STOCK_TREND_GATE_DAYS", "50"))
TREND_GATE_SYMBOL = os.getenv("STOCK_TREND_GATE_SYMBOL", "SPY").strip().upper()

# Seconds the main loop may go without completing, on top of any sleep it has
# announced, before the watchdog ends the process so pm2 can restart it.
# 0 switches the watchdog off. Not a trading setting: it changes nothing about
# when the bot buys or sells, only what happens if the loop stops running.
WATCHDOG_TIMEOUT_SEC = float(os.getenv("STOCK_WATCHDOG_TIMEOUT_SEC", "600"))

# Order sending only (broker paper and live); the simulated bots never read
# these. How long an order is asked about before it is cancelled, how long the
# cancel is waited on, and how long a buy that did not fill is left alone
# before another is tried. All far inside the watchdog's 600 seconds.
ORDER_POLL_SEC          = float(os.getenv("STOCK_ORDER_POLL_SEC", "30"))
ORDER_CANCEL_SEC        = float(os.getenv("STOCK_ORDER_CANCEL_SEC", "15"))
ORDER_POLL_INTERVAL_SEC = 1.0
BUY_RETRY_COOLDOWN_SEC  = float(os.getenv("STOCK_BUY_RETRY_COOLDOWN_SEC", "900"))
# Exit code for "the broker's book and mine disagree". Its own number so pm2
# can be told to leave the bot stopped on it (--stop-exit-codes 78) while
# still restarting it after a watchdog exit (70).
EXIT_BROKER_MISMATCH    = 78

# Which entry/exit logic to run. Measured across 15 symbols on both hourly and
# daily bars, RSI_MEAN_REVERSION was positive out-of-sample at every threshold
# tested (66-75% win rate) while SMA_CROSSOVER managed 35-44%. Commission-free
# execution is why: mean reversion takes many small moves, which a 1.2% fee
# would erase but a 0.20% slippage cost does not.
STRATEGY = os.getenv(f"{TICKER}_STRATEGY",
                     os.getenv("STOCK_STRATEGY", "SMA_CROSSOVER")).strip().upper()
VALID_STRATEGIES = ("SMA_CROSSOVER", "RSI_MEAN_REVERSION")
RSI_OVERSOLD   = float(os.getenv(f"{TICKER}_RSI_OVERSOLD",
                                 os.getenv("STOCK_RSI_OVERSOLD", "30")))
RSI_OVERBOUGHT = float(os.getenv(f"{TICKER}_RSI_OVERBOUGHT",
                                 os.getenv("STOCK_RSI_OVERBOUGHT", "70")))

# ── Logging ───────────────────────────────────────────────────────────────────
DIR = os.path.dirname(os.path.abspath(__file__))
MODE = "BROKERPAPER" if BROKER_PAPER else ("PAPER" if IS_PAPER else "LIVE")

# Every file a bot writes is named here. A simulated bot's names are what they
# have always been. An order-sending bot gets names of its own for all of
# them, so it can run beside the simulated bot for the same ticker without
# either writing into the other's log, state, ledger, journal or signal log.
#
# An order-sending bot keeps its state, ledger, journal and signal log in a
# folder of its own (broker_paper/ or live/) rather than beside the others,
# because the dashboard, the observer and the reports find files by pattern
# (state_*.json, completed_trades_*.csv). In the project root a rehearsal
# ledger would be counted as live P&L, and a rehearsal or live position would
# be added to the registered run's unrealised P&L. Out of the root, only the
# code written to read them does (utils/order_bots.py, slippage_report.py).
if SENDS_ORDERS:
    RUN_DIR      = os.path.join(DIR, "broker_paper" if BROKER_PAPER else "live")
    log_path     = os.path.join(DIR, "logs", f"stock_{TICKER.lower()}_"
                                             f"{'brokerpaper' if BROKER_PAPER else 'live'}.log")
    STATE_PATH   = os.path.join(RUN_DIR, f"state_stock_{TICKER.lower()}.json")
    TRADES_PATH  = os.path.join(RUN_DIR, f"completed_trades_stock_{TICKER.lower()}.csv")
    JOURNAL_PATH = os.path.join(RUN_DIR, f"order_journal_stock_{TICKER.lower()}.json")
    # Held for as long as the process runs, so two processes can never work
    # the same state file and journal (utils/run_lock.py).
    LOCK_PATH    = os.path.join(RUN_DIR, f"running_stock_{TICKER.lower()}.lock")
    # The owner's pause switch. While this file exists no bot of this kind
    # opens a new position; open ones are still managed and closed. A file and
    # not a setting, so it takes effect at the next tick with no restart, and
    # one file covers every bot in the folder.
    PAUSE_PATH   = os.path.join(RUN_DIR, "PAUSE_BUYS")
    SIGNAL_LOG   = (f"stock-{TICKER}", RUN_DIR)
    LOG_TAG      = f"stock/{TICKER}/{'brokerpaper' if BROKER_PAPER else 'live'}"
else:
    log_path     = os.path.join(DIR, "logs", f"stock_{TICKER.lower()}.log")
    STATE_PATH   = os.path.join(DIR, f"state_stock_{TICKER.lower()}_{MODE.lower()}.json")
    TRADES_PATH  = os.path.join(DIR, f"completed_trades_stock_{TICKER.lower()}_{MODE.lower()}.csv")
    JOURNAL_PATH = os.path.join(DIR, "logs", f"order_journal_stock_{TICKER.lower()}.json")
    SIGNAL_LOG   = (f"stock-{TICKER}", "logs")
    LOG_TAG      = f"stock/{TICKER}"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{LOG_TAG}] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(f"stock_bot.{TICKER}")

TRADE_FIELDNAMES = [
    "ticker", "entry_time", "exit_time", "entry_price", "exit_price",
    "entry_reason", "exit_reason", "gross_pct", "net_pct",
    "pnl_usd", "shares", "mode",
]

# The ledger of an order-sending bot. entry_price and exit_price are FILLS
# there, so the P&L columns are what the account actually made. The signal
# prices sit beside them: the price the bot decided at, which is what a
# simulated ledger records and what every backtest assumes. Fill minus signal
# is the slippage, and the whole backtested edge is about the size of the
# 0.10% a side the backtest assumed for it (slippage_report.py).
BROKER_TRADE_FIELDNAMES = TRADE_FIELDNAMES + [
    "entry_signal_price", "exit_signal_price",
    "entry_fill_minus_signal_pct", "exit_fill_minus_signal_pct",
    "entry_order_id", "exit_order_id", "exit_attempts",
]

# State an order-sending bot keeps that a simulated bot has no use for.
BROKER_STATE_KEYS = (
    "entry_signal_price", "entry_order_id", "exit_pending",
    "exit_filled_shares", "exit_filled_value",
    "applied_orders", "unwritten_trade",
)

# When the last trade closed and what it made. The cooldown after a loss reads
# these, so they are written to the state file in every mode: kept in memory
# only, a restart inside the cooldown forgot the loss and the bot could buy
# again at once (DECISIONS.md, 2026-11-17). Written only once a trade has
# closed, so a bot that has never exited gains no keys.
COOLDOWN_STATE_KEYS = ("last_exit_time", "last_exit_pnl")


# ─────────────────────────────────────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            if SENDS_ORDERS:
                # A simulated bot that cannot read its state starts flat and
                # loses nothing real. With orders, "flat" is a claim about an
                # account, and it is not made from a file that would not open.
                return _load_state_backup_or_stop()
    return {"position": "NONE", "entry_price": 0.0, "shares": 0.0,
            "entry_time": None, "ticker": TICKER, "mode": MODE}


def _load_state_backup_or_stop() -> dict:
    try:
        with open(STATE_PATH + ".bak") as f:
            state = json.load(f)
        log.error(f"{STATE_PATH} could not be read; using its backup. Startup "
                  f"reconciliation checks it against the broker.")
        return state
    except Exception:
        _stop_on_mismatch(f"state file {STATE_PATH} and its backup are both unreadable")


def save_state(state: dict):
    """
    Atomic write with a backup, via the same StateManager the crypto bot uses.

    Previously this was json.dump straight onto the live file: a crash or a
    full disk mid-write left truncated JSON and the position was lost. The
    shared manager writes to a temp file, fsyncs, then renames, and keeps a
    .bak to recover from.
    """
    _state_manager().state = _to_shared_schema(state)
    _state_manager().save_state()


_SHARED_STATE = None


def _to_shared_schema(state: dict) -> dict:
    """
    Map the stock bot's state onto the shared schema.

    The shared schema calls the position size holdings_base; for equities that
    is shares. Same float, same meaning — worth bridging rather than forking
    the schema, because forking is how the two bots diverged in the first place.
    """
    return {
        "version": 2,
        "dry_run": IS_PAPER,
        "position": state.get("position", "NONE"),
        "entry_price": float(state.get("entry_price", 0.0) or 0.0),
        "holdings_base": float(state.get("shares", 0.0) or 0.0),
        "cash_usd": float(state.get("cash_usd", 100.0) or 0.0),
        "trades": state.get("trades", []),
        "orders": state.get("orders", {}),
        # Preserved verbatim so nothing the bot relies on is dropped in transit.
        "shares": float(state.get("shares", 0.0) or 0.0),
        "entry_time": state.get("entry_time"),
        "highest_price": state.get("highest_price", 0.0),
        "ticker": TICKER,
        # The last exit, for the cooldown after a loss, in every mode.
        **{key: state[key] for key in COOLDOWN_STATE_KEYS if key in state},
        # Nothing else is added for a simulated bot.
        **({key: state[key] for key in BROKER_STATE_KEYS if key in state}
           if SENDS_ORDERS else {}),
    }


def _state_manager():
    global _SHARED_STATE
    if _SHARED_STATE is None:
        from utils.state import StateManager
        _SHARED_STATE = StateManager(state_file=STATE_PATH, dry_run=IS_PAPER,
                                     persist_trade_csv=False)
    return _SHARED_STATE


def record_trade(state: dict, exit_price: float, exit_reason: str):
    entry_price = state["entry_price"]
    shares      = state["shares"]
    gross_pct   = (exit_price - entry_price) / entry_price * 100
    pnl_usd     = (exit_price - entry_price) * shares

    row = {
        "ticker":       TICKER,
        "entry_time":   state.get("entry_time", ""),
        "exit_time":    datetime.now(timezone.utc).isoformat(),
        "entry_price":  round(entry_price, 4),
        "exit_price":   round(exit_price, 4),
        "entry_reason": state.get("entry_reason", "SMA Bullish Cross"),
        "exit_reason":  exit_reason,
        "gross_pct":    round(gross_pct, 4),
        "net_pct":      round(gross_pct, 4),  # no commission
        "pnl_usd":      round(pnl_usd, 4),
        "shares":       round(shares, 6),
        "mode":         MODE,
    }
    file_exists = os.path.exists(TRADES_PATH)
    with open(TRADES_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    log.info(f"Trade recorded: {exit_reason}  PnL=${pnl_usd:+.4f}  gross={gross_pct:+.3f}%")
    # Store exit info in state for cooldown filter
    state["last_exit_time"] = row["exit_time"]
    state["last_exit_pnl"] = float(pnl_usd)


# ─────────────────────────────────────────────────────────────────────────────
# Alpaca clients
# ─────────────────────────────────────────────────────────────────────────────
# Every Alpaca client the loop uses is built here, and nowhere else, so that
# none can be built without a request timeout. alpaca-py has no timeout of its
# own: a connection that died without closing blocked fetch_bars for a week on
# two bots (slv 2026-11-03, meta 2026-11-04) while pm2 showed them online.
def _trading_client():
    from alpaca.trading.client import TradingClient
    from utils.alpaca_http import with_timeout
    return with_timeout(TradingClient(API_KEY, SECRET_KEY, paper=IS_PAPER))


def _data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    from utils.alpaca_http import with_timeout
    return with_timeout(StockHistoricalDataClient(API_KEY, SECRET_KEY))


# ─────────────────────────────────────────────────────────────────────────────
# Market hours check (Eastern Time)
# ─────────────────────────────────────────────────────────────────────────────
def is_market_open() -> bool:
    """Returns True if US stock market is currently open (9:30am–4pm ET, Mon–Fri)."""
    try:
        client = _trading_client()
        clock = client.get_clock()
        return clock.is_open
    except Exception as e:
        log.warning(f"Could not check market clock via Alpaca: {e}. Falling back to time-based check.")
        # Fallback: manual time check (UTC offset for ET)
        now_utc = datetime.now(timezone.utc)
        # ET is UTC-4 (EDT) or UTC-5 (EST) — use UTC-4 as approximation
        now_et = now_utc - timedelta(hours=4)
        if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open  = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now_et < market_close


def minutes_until_open() -> int:
    """Returns minutes until next market open. Used for smart sleep."""
    now_utc = datetime.now(timezone.utc)
    now_et  = now_utc - timedelta(hours=4)
    # If market is open today, next open is tomorrow at 9:30
    if now_et.weekday() < 5:
        if now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30):
            open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        else:
            # After close — next trading day
            open_et = (now_et + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    else:
        # Weekend — find next Monday
        days_ahead = 7 - now_et.weekday()
        open_et = (now_et + timedelta(days=days_ahead)).replace(hour=9, minute=30, second=0, microsecond=0)
    delta = (open_et - now_et).total_seconds() / 60
    return max(1, int(delta))


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching — 1-hour bars from Alpaca
# ─────────────────────────────────────────────────────────────────────────────
def fetch_bars(ticker: str, n_bars: int = 100) -> pd.DataFrame:
    """Fetch the last n_bars of 1-hour OHLCV bars for a stock ticker."""
    try:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import Adjustment, DataFeed

        data_client = _data_client()
        end   = datetime.now(timezone.utc)
        start = end - timedelta(hours=n_bars * 2)  # fetch extra to ensure enough bars

        req = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=TimeFrame.Hour,
            start=start,
            end=end,
            adjustment=Adjustment.ALL,
            feed=DataFeed.IEX,   # IEX = free tier; SIP requires paid subscription
        )
        bars = data_client.get_stock_bars(req)
        df = bars.df

        if df.empty:
            return pd.DataFrame()

        # Flatten multi-index if present
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(ticker, level=0)

        df = df.sort_index()
        df["close"] = pd.to_numeric(df["close"])
        return df.tail(n_bars).reset_index()

    except Exception as e:
        log.error(f"Failed to fetch bars for {ticker}: {e}")
        return pd.DataFrame()


def fetch_market_closes():
    """
    [(session date in New York, close)] for the trend gate's market symbol:
    daily IEX bars, adjusted like every other bar the bot reads. Enough
    calendar days to hold twice the sessions the gate needs. Raises on any
    failure; the gate turns that into "unknown, no entry".
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment, DataFeed

    end = datetime.now(timezone.utc)
    req = StockBarsRequest(
        symbol_or_symbols=TREND_GATE_SYMBOL,
        timeframe=TimeFrame.Day,
        start=end - timedelta(days=TREND_GATE_DAYS * 3 + 30),
        end=end,
        adjustment=Adjustment.ALL,
        feed=DataFeed.IEX,
    )
    df = _data_client().get_stock_bars(req).df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(TREND_GATE_SYMBOL, level=0)
    stamps = pd.DatetimeIndex(df.index).tz_convert("America/New_York")
    return [(stamp.date(), float(close)) for stamp, close in zip(stamps, df["close"])]


_TREND_GATE = None


def trend_gate():
    global _TREND_GATE
    if _TREND_GATE is None:
        from utils.market_gate import TrendGate
        _TREND_GATE = TrendGate(fetch_market_closes, days=TREND_GATE_DAYS,
                                symbol=TREND_GATE_SYMBOL, log=log)
    return _TREND_GATE


def latest_bar_time(df: pd.DataFrame) -> str:
    """
    The timestamp of the newest bar, as the signal log's candle_time.

    fetch_bars returns df.tail(n).reset_index(), so the timestamp is a column
    and the index is just 0..n-1. Reading the index here would hand the signal
    log the same row number on every loop, and since the log keeps one row per
    candle_time it would then write one row and no more. So anything without a
    real timestamp is an error, not a guess.
    """
    if "timestamp" in df.columns:
        return str(df["timestamp"].iloc[-1])
    if isinstance(df.index, pd.DatetimeIndex):
        return str(df.index[-1])
    raise KeyError("bars have no 'timestamp' column and no datetime index")


# ─────────────────────────────────────────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame) -> dict:
    closes = df["close"]
    sma_s  = closes.rolling(SMA_SHORT).mean()
    sma_l  = closes.rolling(SMA_LONG).mean()

    # RSI
    delta  = closes.diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_l  = loss.ewm(alpha=1/14, adjust=False).mean()
    rs     = avg_g / avg_l.replace(0, float("nan"))
    rsi    = 100 - (100 / (1 + rs))

    return {
        "price":     float(closes.iloc[-1]),
        "sma_short": float(sma_s.iloc[-1]),
        "sma_long":  float(sma_l.iloc[-1]),
        "prev_sma_short": float(sma_s.iloc[-2]),
        "prev_sma_long":  float(sma_l.iloc[-2]),
        "rsi":       float(rsi.iloc[-1]),
        # Mean reversion triggers on RSI *crossing* a level, not sitting past
        # it, so the previous bar's value is required.
        "prev_rsi":  float(rsi.iloc[-2]),
    }


def describe_decision(ind, position, should_enter, why, exit_reason, blocked_by=None):
    """
    What the bot decided this candle, in the shared signal-log shape.

    Without this the dashboard had to infer intent by regexing log lines, and
    it inferred it under SMA-crossover rules — so mean-reversion bots showed as
    about to enter while sitting at RSI 50, nowhere near their oversold trigger.
    """
    if STRATEGY == "RSI_MEAN_REVERSION":
        raw = "BUY" if (ind["prev_rsi"] < RSI_OVERSOLD <= ind["rsi"]) else "HOLD"
        blocked = ""
    else:
        crossed = (ind["prev_sma_short"] < ind["prev_sma_long"]
                   and ind["sma_short"] > ind["sma_long"])
        raw = "BUY" if crossed else "HOLD"
        blocked = "RSI" if (crossed and not should_enter) else ""
    if blocked_by:
        # The strategy wanted in and something above it said no (the trend
        # gate). raw_signal stays BUY so the blocked opportunity is on record.
        blocked = blocked_by
    return {
        "raw_signal": raw,
        "final_signal": "BUY" if should_enter else ("SELL" if exit_reason else "HOLD"),
        "blocked_by": blocked,
        "sma_short": ind.get("sma_short"),
        "sma_long": ind.get("sma_long"),
        "spread_pct": (abs(ind["sma_short"] - ind["sma_long"]) / ind["sma_long"] * 100
                       if ind.get("sma_long") else None),
        "rsi": ind.get("rsi"),
        "ema": None,
        "strategy": STRATEGY,
    }


def entry_signal(ind):
    """
    Whether to open a position. Returns (should_enter, description).

    Both strategies are expressed here so the exit logic, risk limits and
    execution path below are shared and cannot diverge between them.
    """
    if STRATEGY == "RSI_MEAN_REVERSION":
        crossed_up = ind["prev_rsi"] < RSI_OVERSOLD <= ind["rsi"]
        if crossed_up:
            return True, (f"RSI recovered through {RSI_OVERSOLD:.0f} "
                          f"({ind['prev_rsi']:.1f} -> {ind['rsi']:.1f})")
        return False, ""

    bullish_cross = ind["prev_sma_short"] < ind["prev_sma_long"] and ind["sma_short"] > ind["sma_long"]
    if not bullish_cross:
        return False, ""
    if not (RSI_MIN <= ind["rsi"] <= RSI_MAX):
        return False, f"RSI={ind['rsi']:.1f} outside [{RSI_MIN}-{RSI_MAX}]"
    return True, "Bullish crossover confirmed"


def strategy_exit_reason(ind):
    """Strategy-driven exit, separate from the stop/target/trailing exits."""
    if STRATEGY == "RSI_MEAN_REVERSION":
        if ind["prev_rsi"] > RSI_OVERBOUGHT >= ind["rsi"]:
            return f"RSI fell back through {RSI_OVERBOUGHT:.0f}"
        return None
    if ind["prev_sma_short"] > ind["prev_sma_long"] and ind["sma_short"] < ind["sma_long"]:
        return "SMA Bearish Cross"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Order execution via Alpaca
# ─────────────────────────────────────────────────────────────────────────────
_VENUE = None
_SIGNAL_LOG = None


def signal_logger():
    global _SIGNAL_LOG
    if _SIGNAL_LOG is None:
        from utils.signal_log import SignalLogger
        _SIGNAL_LOG = SignalLogger(SIGNAL_LOG[0], log_dir=SIGNAL_LOG[1])
    return _SIGNAL_LOG


def venue():
    global _VENUE
    if _VENUE is None:
        from utils.venue import AlpacaVenue
        _VENUE = AlpacaVenue(API_KEY, SECRET_KEY, paper=IS_PAPER)
    return _VENUE


def place_buy(price: float) -> float:
    """
    The simulated buy. Nothing is sent anywhere: it logs, notifies, and returns
    the share count TRADE_AMOUNT would have bought at the signal price. An
    order-sending bot never comes here; it goes through open_position.
    """
    if SENDS_ORDERS:
        raise RuntimeError("place_buy is the simulated path; this bot sends orders")
    shares = round(TRADE_AMOUNT / price, 6)
    log.info(f"[{MODE}] BUY {shares:.6f} {TICKER} @ ~${price:.4f}  (${TRADE_AMOUNT:.2f})")
    # Stock bots sent no notification of any kind, live or paper, so twelve
    # of them could trade all week in silence. Alpaca equities are
    # commission-free, hence the zero fee.
    _notify("BUY", price, TRADE_AMOUNT, shares)
    return shares


# ─────────────────────────────────────────────────────────────────────────────
# Real orders: broker paper and live. Nothing below, down to _realized_pnl, is
# reached by a simulated bot.
# ─────────────────────────────────────────────────────────────────────────────
_BROKER = None
_NO_BUY_BEFORE = None
_RUN_LOCK = None
_pause = time.sleep     # startup only; the loop's one sleep is in main()


def broker():
    """The order journal and the wait for a fill (utils/broker_orders.py)."""
    global _BROKER
    if _BROKER is None:
        from utils.broker_orders import BrokerOrders
        _BROKER = BrokerOrders(venue(), TICKER, JOURNAL_PATH, log, mode=MODE,
                               poll_timeout=ORDER_POLL_SEC,
                               poll_interval=ORDER_POLL_INTERVAL_SEC,
                               cancel_timeout=ORDER_CANCEL_SEC)
    return _BROKER


def _stop_on_mismatch(message):
    """
    End the process when the broker's book and this bot's cannot be squared.

    It exits rather than sitting there refusing to trade. A stopped process
    shows as stopped; one that is online and doing nothing looks exactly like
    one that is working, which is how two bots sat frozen for a week.
    """
    log.critical(f"BROKER MISMATCH — {message}. Not trading. Exiting with code "
                 f"{EXIT_BROKER_MISMATCH}. See live_trading_stocks.md, "
                 f"'When the bot stops itself'.")
    sys.exit(EXIT_BROKER_MISMATCH)


def take_run_lock():
    """
    Be the only process working this bot's state file and order journal.

    Both are read once and then kept in memory, so a second process (another
    copy of the bot, or close_position.py) would write over what this one
    knows and the two would send orders against each other's position. Held
    until the process ends, however it ends. Exits with the code pm2 is told
    to leave alone, so a duplicate does not restart in a loop.
    """
    global _RUN_LOCK
    from utils import run_lock
    try:
        _RUN_LOCK = run_lock.acquire(LOCK_PATH, f"{MODE} bot for {TICKER}")
    except run_lock.Held as held:
        log.critical(f"ALREADY RUNNING — {held}. Two processes must not work the "
                     f"same state file. Exiting with code {EXIT_BROKER_MISMATCH}.")
        sys.exit(EXIT_BROKER_MISMATCH)


def _same_qty(a, b) -> bool:
    return abs(float(a) - float(b)) <= 1e-6


def _utcnow():
    return datetime.now(timezone.utc)


def _broker_book(expected_qty, tries=2, wait_sec=2):
    """
    (shares of TICKER the broker holds, open orders there that are not this
    bot's). Raises if the broker cannot be asked.

    Read again before a disagreement is believed. Seen on the paper API on
    2026-11-16: the list of open orders still showed an order a moment after
    that order itself reported CANCELED. A real disagreement is still there a
    few seconds later; a lagging list is not.
    """
    for attempt in range(1, tries + 1):
        held = broker().position_qty()
        unknown = broker().unknown_open_orders()
        if (_same_qty(held, expected_qty) and not unknown) or attempt == tries:
            return held, unknown
        log.warning(f"Broker shows {held} {TICKER} and {len(unknown)} unknown open "
                    f"order(s); expected {expected_qty} and none. Reading again.")
        _pause(wait_sec)


def open_position(state: dict, price: float):
    """
    Send a market buy for TRADE_AMOUNT and, if it fills, open the position at
    what was filled. `price` is the signal price; it is kept only to measure
    the fill against.
    """
    global _NO_BUY_BEFORE
    if os.path.exists(PAUSE_PATH):
        log.warning(f"BUY not sent: buying is PAUSED ({PAUSE_PATH} exists). "
                    f"Remove the file to resume.")
        return
    if _NO_BUY_BEFORE is not None and _utcnow() < _NO_BUY_BEFORE:
        log.info(f"BUY not sent: the last one did not fill. No new attempt "
                 f"before {_NO_BUY_BEFORE.isoformat(timespec='seconds')}.")
        return
    # The account must be as empty of this ticker as the state file says.
    try:
        held, working = _broker_book(0.0)
    except Exception as e:
        log.error(f"BUY not sent: could not check the broker first ({e}).")
        return
    if held != 0:
        _stop_on_mismatch(f"about to buy with a flat state file, but the broker "
                          f"holds {held} {TICKER}")
    if working:
        _stop_on_mismatch(f"about to buy, but the broker has {len(working)} open "
                          f"{TICKER} order(s) this bot has no record of")

    from utils.broker_orders import JournalError
    try:
        outcome = broker().buy(TRADE_AMOUNT, price)
    except JournalError as e:
        log.critical(f"{e}. No position opened.")
        return
    if not outcome.final:
        return          # settle_outstanding holds the next tick until it is
    if not outcome.filled:
        _buy_did_not_fill(outcome)
        return
    apply_fill(state, outcome)


def _buy_did_not_fill(outcome):
    global _NO_BUY_BEFORE
    _NO_BUY_BEFORE = _utcnow() + timedelta(seconds=BUY_RETRY_COOLDOWN_SEC)
    log.error(f"BUY not filled ({outcome.status}). No position opened. No new "
              f"attempt for {BUY_RETRY_COOLDOWN_SEC:.0f}s.")


def close_position(state: dict, price: float, reason: str):
    """
    Send a market sell for the whole position. The position is closed only by
    a fill. A sell that is refused, cancelled or unanswered leaves the state
    file LONG, and the exit stays owed: the next tick sends it again whether
    or not the signal that asked for it is still showing.
    """
    owed = state.get("exit_pending") or {
        "reason": reason, "signal_price": price,
        "decided_at": _utcnow().isoformat(), "attempts": 0}
    owed["attempts"] = int(owed.get("attempts", 0)) + 1
    state["exit_pending"] = owed
    try:
        save_state(state)
    except Exception as e:
        # Do not let a disk problem stand between a stop loss and its order.
        log.critical(f"Could not save state before selling ({e}). Selling anyway.")

    try:
        held, working = _broker_book(state["shares"])
    except Exception as e:
        log.error(f"SELL not sent: could not read the broker's position ({e}). "
                  f"Position stays OPEN; retried next tick.")
        return
    if not _same_qty(held, state["shares"]):
        _stop_on_mismatch(f"about to sell {state['shares']} {TICKER} but the broker "
                          f"holds {held}")
    if working:
        _stop_on_mismatch(f"about to sell, but the broker has {len(working)} open "
                          f"{TICKER} order(s) this bot has no record of")

    # The broker's own figure, so the order is for exactly what is there.
    outcome = broker().sell(held, owed["signal_price"], owed["reason"])
    if not outcome.final:
        return
    if not outcome.filled:
        log.error(f"SELL not filled ({outcome.status}), attempt {owed['attempts']}. "
                  f"Position stays OPEN at {state['shares']} {TICKER}; retried next tick.")
        return
    apply_fill(state, outcome)


def apply_fill(state: dict, outcome):
    """
    Write one finished order into the state file and, when it closes the
    position, into the ledger. Quantity and price are the venue's.

    Order of writes: state first, ledger second, journal last. Each step is
    safe to repeat, so a crash between any two is made good at the next start
    without a position or a ledger row being lost or counted twice.
    """
    cid = outcome.client_order_id
    if cid in state.get("applied_orders", []):
        broker().mark_applied(cid)
        return
    qty, fill_price = outcome.filled_qty, outcome.avg_price
    closed = None

    if outcome.side == "BUY":
        if state.get("position") != "NONE":
            _stop_on_mismatch(f"buy {cid} filled {qty} {TICKER} but the state file "
                              f"already holds a position")
        state.update({
            "position":      "LONG",
            "entry_price":   fill_price,
            "shares":        qty,
            "highest_price": fill_price,
            "entry_time":    _utcnow().isoformat(),
            "entry_reason":  "SMA Bullish Cross",
            "entry_signal_price": outcome.signal_price,
            "entry_order_id": outcome.order_id,
        })
        for key in ("exit_pending", "exit_filled_shares", "exit_filled_value"):
            state.pop(key, None)
    else:
        if state.get("position") != "LONG":
            _stop_on_mismatch(f"sell {cid} filled {qty} {TICKER} but the state file "
                              f"holds no position")
        sold = float(state.get("exit_filled_shares", 0.0)) + qty
        value = float(state.get("exit_filled_value", 0.0)) + qty * fill_price
        if _same_qty(state["shares"], qty) or qty > state["shares"]:
            closed = _broker_trade_row(state, sold, value / sold, outcome)
            state.update({"position": "NONE", "entry_price": 0.0,
                          "shares": 0.0, "entry_time": None,
                          "unwritten_trade": closed})
            for key in ("exit_pending", "exit_filled_shares", "exit_filled_value",
                        "entry_signal_price", "entry_order_id"):
                state.pop(key, None)
        else:
            # Part of the position sold and the order is finished. Keep the
            # rest open and the exit owed; the ledger row waits for the last
            # share so one round trip is one row.
            state.update({"shares": state["shares"] - qty,
                          "exit_filled_shares": sold, "exit_filled_value": value})

    state["applied_orders"] = (state.get("applied_orders", []) + [cid])[-20:]
    save_state(state)
    if closed is not None:
        _write_unwritten_trade(state)
    broker().mark_applied(cid)

    slip = ((fill_price - outcome.signal_price) / outcome.signal_price * 100
            if outcome.signal_price > 0 else 0.0)
    log.info(f"[{MODE}] {outcome.side} FILLED {qty:.9f} {TICKER} @ ${fill_price:.4f} "
             f"(signal ${outcome.signal_price:.4f}, fill minus signal {slip:+.3f}%) "
             f"order {outcome.order_id}")
    if outcome.side == "BUY":
        _notify("BUY", fill_price, qty * fill_price, qty)
    elif closed is not None:
        _notify("SELL", closed["exit_price"], closed["shares"] * closed["exit_price"],
                closed["shares"], realized_pnl=closed["pnl_usd"])


def _broker_trade_row(state: dict, shares: float, exit_price: float, outcome) -> dict:
    entry_price = float(state["entry_price"])
    owed = state.get("exit_pending") or {}
    entry_signal = float(state.get("entry_signal_price") or 0.0)
    exit_signal = float(owed.get("signal_price") or outcome.signal_price or 0.0)
    gross_pct = (exit_price - entry_price) / entry_price * 100

    def minus_signal(fill, signal):
        return round((fill - signal) / signal * 100, 4) if signal > 0 else ""

    return {
        "ticker":       TICKER,
        "entry_time":   state.get("entry_time", ""),
        "exit_time":    _utcnow().isoformat(),
        "entry_price":  round(entry_price, 6),
        "exit_price":   round(exit_price, 6),
        "entry_reason": state.get("entry_reason", "SMA Bullish Cross"),
        "exit_reason":  owed.get("reason") or outcome.reason,
        "gross_pct":    round(gross_pct, 4),
        "net_pct":      round(gross_pct, 4),  # no commission
        "pnl_usd":      round((exit_price - entry_price) * shares, 4),
        "shares":       round(shares, 9),
        "mode":         MODE,
        "entry_signal_price": round(entry_signal, 6),
        "exit_signal_price":  round(exit_signal, 6),
        "entry_fill_minus_signal_pct": minus_signal(entry_price, entry_signal),
        "exit_fill_minus_signal_pct":  minus_signal(exit_price, exit_signal),
        "entry_order_id": state.get("entry_order_id", ""),
        "exit_order_id":  outcome.order_id,
        "exit_attempts":  int(owed.get("attempts") or 1),
    }


def _write_unwritten_trade(state: dict):
    """Append the closed trade held in state to the ledger, once. The row is
    kept in the state file until it is in the ledger, so a crash between the
    two cannot lose it; the order id stops it being written twice."""
    row = state.get("unwritten_trade")
    if not row:
        return
    already = False
    if os.path.exists(TRADES_PATH):
        with open(TRADES_PATH, newline="") as f:
            already = any(r.get("exit_order_id") == str(row.get("exit_order_id"))
                          for r in csv.DictReader(f))
    if not already:
        new_file = not os.path.exists(TRADES_PATH)
        with open(TRADES_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BROKER_TRADE_FIELDNAMES)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())
        log.info(f"Trade recorded: {row['exit_reason']}  PnL=${row['pnl_usd']:+.4f}  "
                 f"gross={row['gross_pct']:+.3f}%  (from fills)")
    # For the cooldown filter, as record_trade does for a simulated bot.
    state["last_exit_time"] = row["exit_time"]
    state["last_exit_pnl"] = float(row["pnl_usd"])
    state.pop("unwritten_trade", None)
    save_state(state)


def settle_outstanding(state: dict) -> bool:
    """
    Finish any order a previous pass left without a final answer, and write
    any fill not yet in the state file. True when nothing is outstanding.
    While it is False the bot sends nothing else. With nothing outstanding
    this is a look at a dict and no network call.
    """
    for cid in broker().outstanding():
        outcome = broker().settle(cid)
        if not outcome.final:
            log.warning(f"Order {cid} still has no final answer from the broker; "
                        f"nothing else is sent until it has.")
            return False
        if outcome.filled:
            apply_fill(state, outcome)
        else:
            broker().mark_applied(cid)
            if outcome.side == "BUY":
                _buy_did_not_fill(outcome)
            else:
                log.error(f"SELL {cid} not filled ({outcome.status}). Position stays OPEN.")
    return True


def reconcile_orders(state: dict = None):
    """
    Square this bot with the broker before the first tick. Order sending only;
    a simulated bot returns at once.

    1. The endpoint is the one this mode is for: paper for broker paper.
    2. A closed trade that reached the state file but not the ledger is
       written to the ledger.
    3. Every order in the journal without a final answer gets one, and any
       fill not yet in the state file is written into it.
    4. The broker's position in this ticker is what the state file says, and
       the broker has no open order for it.

    If any of that cannot be done the bot stops instead of trading: a position
    at the broker that the bot does not know about is opened a second time,
    and one it believes in that is not there is sold short.
    """
    if not SENDS_ORDERS:
        return
    try:
        endpoint = venue().endpoint()
    except Exception as e:
        _stop_on_mismatch(f"could not build the broker client ({e})")
    on_paper = "paper-api.alpaca.markets" in endpoint
    if BROKER_PAPER != on_paper:
        _stop_on_mismatch(f"mode is {MODE} but orders would go to {endpoint!r}")

    try:
        broker()
    except (OSError, ValueError) as e:
        _stop_on_mismatch(f"order journal {JOURNAL_PATH} cannot be read ({e})")
    _write_unwritten_trade(state)

    tries = 8       # ten seconds apart: longer than an order can be in flight
    for attempt in range(1, tries + 1):
        if settle_outstanding(state):
            break
        if attempt == tries:
            _stop_on_mismatch("an order from before this start still has no final "
                              "answer from the broker")
        _pause(10)

    mine = float(state.get("shares", 0.0) or 0.0) if state.get("position") == "LONG" else 0.0
    held = working = None
    for attempt in range(1, 4):
        try:
            held, working = _broker_book(mine, tries=3, wait_sec=5)
            break
        except Exception as e:
            log.warning(f"Could not read the broker's book (try {attempt} of 3): {e}")
            if attempt == 3:
                _stop_on_mismatch("the broker's position could not be read, so the "
                                  "state file cannot be checked against it")
            _pause(5)

    if not _same_qty(held, mine):
        _stop_on_mismatch(f"state file says {mine} {TICKER} "
                          f"(position {state.get('position')}), the broker holds {held}")
    if working:
        _stop_on_mismatch(f"the broker has {len(working)} open {TICKER} order(s) "
                          f"this bot has no record of")
    log.info(f"  Reconciled with the broker at {endpoint}: {held} {TICKER} held, "
             f"state file agrees, no open orders.")


def _realized_pnl(exit_price: float, shares: float) -> float:
    """P&L against the recorded entry, or 0.0 when there is no open entry."""
    try:
        entry = float(load_state().get("entry_price") or 0.0)
    except Exception:
        return 0.0
    if entry <= 0 or shares <= 0:
        return 0.0
    return (exit_price - entry) * shares


def _notify(side: str, price: float, amount_usd: float, shares: float,
            realized_pnl: float = 0.0):
    """
    Email on an actual entry or exit.

    Deliberately only on a real fill. A separate watchlist scanner used to mail
    "BUY SIGNAL" whenever a coin merely approached a setup, which reads exactly
    like a trade confirmation and was not one — so alerts here fire when a
    position genuinely opens or closes, and never on a signal.

    A notification must never take a bot down: an SMTP outage is not a reason
    to stop trading, so failures are logged and swallowed.
    """
    try:
        from utils.notifications import send_trade_notification
        send_trade_notification(side, TICKER, float(price), float(amount_usd),
                                float(shares), 0.0, IS_PAPER, float(realized_pnl))
    except Exception as e:
        log.warning(f"Trade notification failed ({side} {TICKER}): {e}")


def place_sell(shares: float, price: float, reason: str):
    """The simulated sell. Nothing is sent. An order-sending bot goes through
    close_position instead."""
    if SENDS_ORDERS:
        raise RuntimeError("place_sell is the simulated path; this bot sends orders")
    log.info(f"[{MODE}] SELL {shares:.6f} {TICKER} @ ~${price:.4f}  reason={reason}")
    _notify("SELL", price, shares * price, shares, realized_pnl=_realized_pnl(price, shares))


# ─────────────────────────────────────────────────────────────────────────────
# Main trading loop
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(f"Stock Trading Bot — {TICKER} ({MODE})")
    if STRATEGY not in VALID_STRATEGIES:
        log.error(f"STOCK_STRATEGY={STRATEGY!r} is not one of {VALID_STRATEGIES}. "
                  f"Refusing to start rather than silently falling back.")
        sys.exit(1)
    log.info(f"  Strategy: {STRATEGY}")
    if STRATEGY == "RSI_MEAN_REVERSION":
        log.info(f"  RSI {RSI_OVERSOLD:.0f}/{RSI_OVERBOUGHT:.0f} | "
                 f"SL={STOP_LOSS_PCT}% | TP={TAKE_PROFIT_PCT}%")
    else:
        log.info(f"  SMA {SMA_SHORT}/{SMA_LONG} | SL={STOP_LOSS_PCT}% | TP={TAKE_PROFIT_PCT}%")
    log.info(f"  RSI filter: [{RSI_MIN}–{RSI_MAX}] | Trade size: ${TRADE_AMOUNT}")
    log.info(f"  Base URL: {BASE_URL}")
    if TREND_GATE_DAYS > 0:
        log.info(f"  Trend gate: no new entry while {TREND_GATE_SYMBOL}'s last close is "
                 f"below its {TREND_GATE_DAYS}-session average")
    else:
        log.warning("  Trend gate: OFF (STOCK_TREND_GATE_DAYS=0)")
    log.info("=" * 60)

    if not API_KEY or not SECRET_KEY:
        if IS_PAPER:
            log.error("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env — exiting.")
        else:
            log.error("LIVE mode: ALPACA_LIVE_API_KEY and ALPACA_LIVE_SECRET_KEY must "
                      "be set in .env — exiting.")
        sys.exit(1)

    if SENDS_ORDERS:
        # Before the state file is read: whoever holds the lock may be about
        # to change it.
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        take_run_lock()
    state = load_state()
    log.info(f"State loaded: position={state['position']}")
    if SENDS_ORDERS:
        log.warning(f"  ORDERS ARE SENT in this mode ({MODE}): ${TRADE_AMOUNT:.2f} a trade. "
                    f"State {STATE_PATH}, ledger {TRADES_PATH}.")
        if os.path.exists(PAUSE_PATH):
            log.warning(f"  Buying is PAUSED: {PAUSE_PATH} exists. No new position is "
                        f"opened until it is removed. Exits are not affected.")
    reconcile_orders(state)

    # Second layer behind the request timeouts: if the loop stops completing
    # for any reason, end the process rather than sit "online" doing nothing.
    from utils import watchdog as _watchdog
    loop_watchdog = _watchdog.start(WATCHDOG_TIMEOUT_SEC, name=f"stock/{TICKER}", log=log)
    if WATCHDOG_TIMEOUT_SEC > 0:
        log.info(f"  Watchdog: exits if the loop stalls for {WATCHDOG_TIMEOUT_SEC:.0f}s "
                 f"beyond its sleep")
    else:
        log.warning("  Watchdog: OFF (STOCK_WATCHDOG_TIMEOUT_SEC=0)")

    def nap(seconds):
        # Tell the watchdog how long the loop means to be away, then sleep.
        # Every pass through the loop ends in one of these.
        loop_watchdog.beat(allow_sec=seconds)
        time.sleep(seconds)

    while True:
        try:
            # ── Market hours gate ─────────────────────────────────────────────
            if not is_market_open():
                mins = minutes_until_open()
                sleep_mins = min(mins, 30)  # wake every 30m max to recheck
                log.info(f"Market closed. Next open in ~{mins}m. Sleeping {sleep_mins}m.")
                nap(sleep_mins * 60)
                continue

            # Order sending only: nothing new until every earlier order has a
            # final answer from the broker and its fill is in the state file.
            if SENDS_ORDERS and not settle_outstanding(state):
                nap(LOOP_INTERVAL)
                continue

            # ── Fetch data and compute indicators ─────────────────────────────
            log.info(f"--- {TICKER} market check ---")
            df = fetch_bars(TICKER, CANDLE_BARS + SMA_LONG + 10)
            if df.empty or len(df) < SMA_LONG + 5:
                log.warning(f"Not enough bars ({len(df)}). Waiting...")
                nap(LOOP_INTERVAL)
                continue

            ind = compute_indicators(df)
            price     = ind["price"]
            sma_s     = ind["sma_short"]
            sma_l     = ind["sma_long"]
            prev_s    = ind["prev_sma_short"]
            prev_l    = ind["prev_sma_long"]
            rsi       = ind["rsi"]

            spread = (sma_s - sma_l) / sma_l * 100
            direction = "ABOVE" if sma_s > sma_l else "BELOW"

            log.info(
                f"Indicators | SMA_short={sma_s:.4f} | SMA_long={sma_l:.4f} | "
                f"short is {abs(spread):.3f}% {direction} long | spread={abs(spread):.3f}% | "
                f"RSI={rsi:.1f}[{RSI_MIN}-{RSI_MAX}] | "
                f"Position: {state['position']}"
            )

            # ── Strategy logic ────────────────────────────────────────────────
            if state["position"] == "NONE":
                should_enter, why = entry_signal(ind)

                # Market trend gate (v5). Asked on every flat tick, not only
                # when a signal fires: the answer is worked out once a day and
                # kept, so the decision at the moment of a signal does not
                # hang on a network call made at that moment. It can only
                # veto an entry; it never creates one and never touches exits.
                gate_block = None
                if TREND_GATE_DAYS > 0:
                    gate = trend_gate().state()
                    if should_enter and not gate.allows_entry:
                        should_enter = False
                        gate_block = gate.blocked_by
                        why = f"{why}; {gate.describe()}"
                try:
                    signal_logger().record(
                        latest_bar_time(df), price, state["position"],
                        describe_decision(ind, state["position"], should_enter,
                                          why, None, blocked_by=gate_block))
                except Exception as sig_err:
                    log.warning(f"Could not record signal decision: {sig_err}")

                if should_enter:
                    # Volume confirmation filter
                    vol_ok = True
                    if MIN_VOLUME_RATIO > 0.0:
                        avg_vol = float(df['volume'].rolling(window=20).mean().iloc[-1]) if len(df) >= 20 else 0
                        cur_vol = float(df['volume'].iloc[-1])
                        if avg_vol > 0:
                            vol_ratio = cur_vol / avg_vol
                            if vol_ratio < MIN_VOLUME_RATIO:
                                log.info(f"⚠️  BUY blocked: volume ratio {vol_ratio:.2f} < {MIN_VOLUME_RATIO:.2f}")
                                vol_ok = False

                    # Cooldown after loss filter
                    cooldown_ok = True
                    if COOLDOWN_HOURS > 0.0 and state.get("last_exit_pnl", 0) < 0:
                        last_exit_t = state.get("last_exit_time")
                        if last_exit_t:
                            try:
                                exit_dt = datetime.fromisoformat(last_exit_t.replace('Z', '+00:00'))
                                hours_since = (datetime.now(timezone.utc) - exit_dt).total_seconds() / 3600.0
                                if hours_since < COOLDOWN_HOURS:
                                    log.info(f"⚠️  BUY blocked: cooldown {hours_since:.1f}h / {COOLDOWN_HOURS:.0f}h after loss")
                                    cooldown_ok = False
                            except Exception:
                                pass

                    if vol_ok and cooldown_ok:
                        log.info(f"🟢 BUY SIGNAL — {why} | RSI={rsi:.1f}")
                        if SENDS_ORDERS:
                            # A real order; state is written from its fill.
                            open_position(state, price)
                        else:
                            shares = place_buy(price)
                            if shares > 0:
                                state.update({
                                    "position":     "LONG",
                                    "entry_price":  price,
                                    "shares":       shares,
                                    "highest_price": price,
                                    "entry_time":   datetime.now(timezone.utc).isoformat(),
                                    "entry_reason": "SMA Bullish Cross",
                                })
                                save_state(state)
                elif why:
                    log.info(f"⚠️  Entry blocked — {why}")

            elif state["position"] == "LONG":
                entry_price = state["entry_price"]
                chg_pct = (price - entry_price) / entry_price * 100

                # A discretionary exit may not close a position at a net loss.
                # The stop loss is exempt — realising a loss is its whole job.
                #
                # Alpaca equities are commission-free, so "covers costs" here
                # is simply "above entry". The trap it prevents is the same one
                # measured on the crypto side: the trailing stop arms at
                # TRAILING_ACTIVATION_PCT and exits TRAILING_STOP_PCT below the
                # peak, so at 1.0/1.5 any trade peaking between +1.0% and +1.5%
                # exits BELOW entry — a losing exit on a venue that charges
                # nothing, which should have been free money.
                #
                # An invariant rather than retuned percentages, so a later
                # settings change cannot silently restore the trap.
                covers_costs = chg_pct >= 0.0

                exit_reason = None
                if chg_pct <= -STOP_LOSS_PCT:
                    exit_reason = "Stop Loss Triggered"
                elif chg_pct >= TAKE_PROFIT_PCT:
                    exit_reason = "Take Profit Triggered"
                elif TRAILING_STOP_PCT > 0.0 and TRAILING_ACTIVATION_PCT > 0.0:
                    highest = state.get("highest_price", entry_price)
                    if price > highest:
                        highest = price
                        state["highest_price"] = highest
                        save_state(state)
                    if chg_pct >= TRAILING_ACTIVATION_PCT:
                        trail_price = highest * (1.0 - TRAILING_STOP_PCT / 100.0)
                        if price <= trail_price and covers_costs:
                            exit_reason = f"Trailing Stop (peak=${highest:.4f}, trail={TRAILING_STOP_PCT}%)"
                        else:
                            held = "" if covers_costs else "  [held: below entry]"
                            log.info(f"Trailing stop active: peak=${highest:.4f}, "
                                     f"stop=${trail_price:.4f}, current=${price:.4f}{held}")
                if exit_reason is None:
                    strategy_exit = strategy_exit_reason(ind)
                    if strategy_exit and not covers_costs:
                        log.info(f"Holding through strategy exit — {strategy_exit} — "
                                 f"net {chg_pct:+.2f}% is below entry. Stop loss still active.")
                    elif strategy_exit:
                        exit_reason = strategy_exit

                if SENDS_ORDERS and state.get("exit_pending"):
                    # An exit was decided on an earlier tick and its sell did
                    # not fill. It is owed whatever the signal shows now.
                    exit_reason = state["exit_pending"]["reason"]

                if exit_reason:
                    log.info(f"🔴 SELL SIGNAL — {exit_reason} | chg={chg_pct:+.3f}% | Price=${price:.4f}")
                    if SENDS_ORDERS:
                        # A real order. The position closes only on a fill,
                        # and the ledger row is written from that fill.
                        close_position(state, price, exit_reason)
                    else:
                        place_sell(state["shares"], price, exit_reason)
                        record_trade(state, price, exit_reason)
                        state.update({
                            "position": "NONE", "entry_price": 0.0,
                            "shares": 0.0, "entry_time": None,
                        })
                        save_state(state)
                else:
                    log.info(
                        f"Holding {state['shares']:.6f} {TICKER} | "
                        f"Entry=${entry_price:.4f} | Current=${price:.4f} | "
                        f"P&L: {chg_pct:+.3f}% (${(price - entry_price) * state['shares']:+.4f})"
                    )

        except KeyboardInterrupt:
            log.info("Bot interrupted by user. Exiting gracefully.")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)

        nap(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
