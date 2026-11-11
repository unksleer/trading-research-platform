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
"""
import os
import uuid
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
API_KEY         = os.getenv("ALPACA_API_KEY", "")
SECRET_KEY      = os.getenv("ALPACA_SECRET_KEY", "")
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

# Seconds the main loop may go without completing, on top of any sleep it has
# announced, before the watchdog ends the process so pm2 can restart it.
# 0 switches the watchdog off. Not a trading setting: it changes nothing about
# when the bot buys or sells, only what happens if the loop stops running.
WATCHDOG_TIMEOUT_SEC = float(os.getenv("STOCK_WATCHDOG_TIMEOUT_SEC", "600"))

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
log_path = os.path.join(DIR, "logs", f"stock_{TICKER.lower()}.log")
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [stock/{TICKER}] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(f"stock_bot.{TICKER}")

MODE = "PAPER" if IS_PAPER else "LIVE"

# ── State file ────────────────────────────────────────────────────────────────
STATE_PATH  = os.path.join(DIR, f"state_stock_{TICKER.lower()}_{MODE.lower()}.json")
TRADES_PATH = os.path.join(DIR, f"completed_trades_stock_{TICKER.lower()}_{MODE.lower()}.csv")

TRADE_FIELDNAMES = [
    "ticker", "entry_time", "exit_time", "entry_price", "exit_price",
    "entry_reason", "exit_reason", "gross_pct", "net_pct",
    "pnl_usd", "shares", "mode",
]


# ─────────────────────────────────────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"position": "NONE", "entry_price": 0.0, "shares": 0.0,
            "entry_time": None, "ticker": TICKER, "mode": MODE}


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


def describe_decision(ind, position, should_enter, why, exit_reason):
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
        _SIGNAL_LOG = SignalLogger(f"stock-{TICKER}")
    return _SIGNAL_LOG


def venue():
    global _VENUE
    if _VENUE is None:
        from utils.venue import AlpacaVenue
        _VENUE = AlpacaVenue(API_KEY, SECRET_KEY, paper=IS_PAPER)
    return _VENUE


def place_buy(price: float) -> float:
    """
    Submit a fractional market buy for TRADE_AMOUNT USD. Returns shares bought.

    The intent is journalled with a generated client order ID *before* the
    order is sent. If the process dies between submission and the state write,
    startup reconciliation finds the order at the venue and applies it, rather
    than the position existing at Alpaca while the bot believes it is flat.
    """
    shares = round(TRADE_AMOUNT / price, 6)
    if IS_PAPER:
        log.info(f"[{MODE}] BUY {shares:.6f} {TICKER} @ ~${price:.4f}  (${TRADE_AMOUNT:.2f})")
        # Stock bots sent no notification of any kind, live or paper, so twelve
        # of them could trade all week in silence. Alpaca equities are
        # commission-free, hence the zero fee.
        _notify("BUY", price, TRADE_AMOUNT, shares)
        return shares

    client_order_id = f"{TICKER.lower()}-buy-{uuid.uuid4().hex[:16]}"
    _journal_intent(client_order_id, "BUY", price, shares)
    try:
        order = venue().submit_buy(TICKER, TRADE_AMOUNT, client_order_id)
        parsed = venue().parse_response(order)
        log.info(f"[{MODE}] BUY submitted: {parsed['order_id']} "
                 f"({client_order_id}) — ${TRADE_AMOUNT:.2f} of {TICKER}")
        _journal_result(client_order_id, parsed)
        return shares
    except Exception as e:
        log.error(f"BUY order failed: {e}")
        _journal_result(client_order_id, {"status": "FAILED", "order_id": ""})
        return 0.0


def _journal_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "logs", f"order_journal_stock_{TICKER.lower()}.json")


def _journal_intent(client_order_id, side, price, size):
    """Record what we are about to do, before doing it."""
    try:
        path = _journal_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path) as handle:
                journal = json.load(handle)
        except (OSError, ValueError):
            journal = {}
        journal[client_order_id] = {
            "ticker": TICKER, "side": side, "price": price, "size": size,
            "status": "PENDING", "applied": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(journal, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as e:
        # Never let journalling failure stop a trade decision; log loudly.
        log.warning(f"Could not journal order intent: {e}")


def _journal_result(client_order_id, parsed):
    try:
        path = _journal_path()
        with open(path) as handle:
            journal = json.load(handle)
        if client_order_id in journal:
            journal[client_order_id].update({
                "status": parsed.get("status", ""),
                "order_id": parsed.get("order_id", ""),
                "applied": True,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            })
            tmp = path + ".tmp"
            with open(tmp, "w") as handle:
                json.dump(journal, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
    except (OSError, ValueError) as e:
        log.warning(f"Could not journal order result: {e}")


def reconcile_orders():
    """
    Resolve orders submitted but never confirmed, at startup.

    Without this, a crash between submitting and recording leaves a position at
    the venue that the bot does not know about — it will then happily open a
    second one.
    """
    if IS_PAPER:
        return
    try:
        with open(_journal_path()) as handle:
            journal = json.load(handle)
    except (OSError, ValueError):
        return
    unresolved = {k: v for k, v in journal.items() if not v.get("applied")}
    if not unresolved:
        log.info("No unresolved orders to reconcile.")
        return
    log.warning(f"{len(unresolved)} unresolved order(s); querying venue")
    for client_order_id in unresolved:
        order = venue().get_order_by_client_id(client_order_id)
        if order is None:
            log.warning(f"  {client_order_id}: not found at venue — never reached it")
            continue
        parsed = venue().parse_response(order)
        log.warning(f"  {client_order_id}: venue reports {parsed['status']} "
                    f"filled={parsed['filled_size']}")
        _journal_result(client_order_id, parsed)


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
    """Submit a market sell for all held shares."""
    if IS_PAPER:
        log.info(f"[{MODE}] SELL {shares:.6f} {TICKER} @ ~${price:.4f}  reason={reason}")
        _notify("SELL", price, shares * price, shares, realized_pnl=_realized_pnl(price, shares))
        return
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        client = _trading_client()
        req = MarketOrderRequest(
            symbol=TICKER,
            qty=shares,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)
        log.info(f"[{MODE}] SELL order submitted: {order.id} — {shares:.6f} {TICKER}  reason={reason}")
    except Exception as e:
        log.error(f"SELL order failed: {e}")


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
    reconcile_orders()
    log.info(f"  Strategy: {STRATEGY}")
    if STRATEGY == "RSI_MEAN_REVERSION":
        log.info(f"  RSI {RSI_OVERSOLD:.0f}/{RSI_OVERBOUGHT:.0f} | "
                 f"SL={STOP_LOSS_PCT}% | TP={TAKE_PROFIT_PCT}%")
    else:
        log.info(f"  SMA {SMA_SHORT}/{SMA_LONG} | SL={STOP_LOSS_PCT}% | TP={TAKE_PROFIT_PCT}%")
    log.info(f"  RSI filter: [{RSI_MIN}–{RSI_MAX}] | Trade size: ${TRADE_AMOUNT}")
    log.info(f"  Base URL: {BASE_URL}")
    log.info("=" * 60)

    if not API_KEY or not SECRET_KEY:
        log.error("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env — exiting.")
        sys.exit(1)

    state = load_state()
    log.info(f"State loaded: position={state['position']}")

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
                try:
                    signal_logger().record(
                        latest_bar_time(df), price, state["position"],
                        describe_decision(ind, state["position"], should_enter,
                                          why, None))
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

                if exit_reason:
                    log.info(f"🔴 SELL SIGNAL — {exit_reason} | chg={chg_pct:+.3f}% | Price=${price:.4f}")
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
