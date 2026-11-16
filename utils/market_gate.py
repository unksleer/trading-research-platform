"""
The market trend gate on new entries (stocks v5).

Rule, fixed in DECISIONS.md on 2026-11-10 before it was tested and not tuned
since: no new entry when the market symbol's close on the last completed
session is below the average of its last N completed session closes. SPY and
50. Exits are never gated.

What it is for. v4's stop-outs came in clusters while the market was weak. In
the backtest (backtest_regime_gate.py, entries 2021-01-04 to 2026-09-03) the
trades this rule would have blocked lost money as a group in five years of
six. It is a bear-market switch: most of what it saved was 2022.

Two things here have to match that backtest or the paper run tests a different
rule.

  Closes. The backtest took each session's close as the last one-minute IEX
  print inside the regular session. This reads Alpaca's daily IEX bars. Over
  363 sessions (2025-06-02 to 2026-11-09) the two agree to the cent on 355,
  differ by at most 0.013%, and give the same gate decision on all 314
  sessions where both could be computed.

  Completed sessions only. A daily bar exists for the session in progress, and
  its "close" is just the latest price. Using it would let today's move decide
  today's entries, which the rule does not do. Any bar dated today or later in
  New York is dropped.

Unknown blocks. If the closes cannot be fetched, or there are fewer than N
completed sessions, the state is unknown and an entry is refused. The backtest
let unknown through, but there it only meant "before the data starts". Here it
means the market data is unavailable, and an entry taken blind is not evidence
about a gated strategy. The same goes for closes that stop more than a few
days short of today: that is old data, not the last session. A good answer is
kept for the rest of that New York day, because it cannot change until the
session ends. A failure is retried, but not more often than every few minutes,
so a bot that asks on every tick does not hammer an API that is already down.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _NEW_YORK = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _NEW_YORK = None

BLOCKED = "TREND_GATE"
UNKNOWN = "TREND_GATE_UNKNOWN"

# The last completed session can be this many calendar days back and still be
# the last one: a Friday close read on the Tuesday after a Monday holiday is 4.
MAX_SESSION_AGE_DAYS = 5
RETRY_AFTER_SEC = 300


def new_york_date(now=None):
    now = now or datetime.now(timezone.utc)
    if _NEW_YORK is None:                           # pragma: no cover
        return (now - timedelta(hours=5)).date()
    return now.astimezone(_NEW_YORK).date()


def completed_closes(bars, today):
    """
    [(date, close)] for completed sessions, oldest first.

    `bars` is [(session_date, close)] in any order; anything dated `today` or
    later is the session in progress and is left out.
    """
    done = sorted((d, float(c)) for d, c in bars if d < today)
    return done


def evaluate(closes, days):
    """
    The rule itself, on completed-session closes oldest first.

    Returns (blocked, prior_close, average). blocked is None when there are
    fewer than `days` closes: unknown, and the caller decides what that means.
    """
    if days <= 0 or len(closes) < days:
        return None, (closes[-1] if closes else None), None
    window = closes[-days:]
    average = sum(window) / float(days)
    prior = closes[-1]
    return prior < average, prior, average


class GateState:
    """One answer: may a new position be opened right now?"""

    def __init__(self, blocked, prior_close=None, average=None, session=None,
                 symbol="SPY", days=50, problem=""):
        self.blocked = blocked              # True, False, or None for unknown
        self.prior_close = prior_close
        self.average = average
        self.session = session              # date of the last completed session
        self.symbol = symbol
        self.days = days
        self.problem = problem

    @property
    def allows_entry(self):
        return self.blocked is False

    @property
    def blocked_by(self):
        """The signal log's blocked_by value, or '' when entries are allowed."""
        if self.blocked is False:
            return ""
        return BLOCKED if self.blocked else UNKNOWN

    def describe(self):
        if self.blocked is None:
            return (f"trend gate unknown ({self.problem or 'no data'}); "
                    f"no entry without it")
        gap = (self.prior_close / self.average - 1.0) * 100.0
        side = "below" if self.blocked else "at or above"
        verdict = "entries off" if self.blocked else "entries on"
        return (f"{self.symbol} closed {self.prior_close:.2f} on {self.session}, "
                f"{gap:+.2f}% {side} its {self.days}-session average "
                f"{self.average:.2f}: {verdict}")


class TrendGate:
    """
    The gate as the bot uses it.

    `fetch` returns [(session_date, close)] for the market symbol, covering at
    least `days` completed sessions. It is the only part that touches the
    network, so the rule can be tested without one.
    """

    def __init__(self, fetch, days=50, symbol="SPY", today=new_york_date, log=None,
                 clock=time.monotonic, retry_after_sec=RETRY_AFTER_SEC):
        self.fetch = fetch
        self.days = int(days)
        self.symbol = symbol
        self._today = today
        self._log = log or logging.getLogger("market_gate")
        self._clock = clock
        self._retry_after = float(retry_after_sec)
        self._cached_day = None
        self._cached = None
        self._unknown = None
        self._unknown_at = None

    @property
    def enabled(self):
        return self.days > 0

    def state(self):
        today = self._today()
        if self._cached is not None and self._cached_day == today:
            return self._cached
        if (self._unknown is not None
                and self._clock() - self._unknown_at < self._retry_after):
            return self._unknown
        state = self._work_out(today)
        if state.blocked is None:
            self._unknown, self._unknown_at = state, self._clock()
            self._log.warning(f"Trend gate: {state.describe()}")
        else:
            self._cached_day, self._cached = today, state
            self._unknown = None
            self._log.info(f"Trend gate: {state.describe()}")
        return state

    def _work_out(self, today):
        def unknown(problem, prior=None):
            return GateState(None, prior_close=prior, symbol=self.symbol,
                             days=self.days, problem=problem)
        try:
            done = completed_closes(self.fetch(), today)
        except Exception as e:
            return unknown(f"could not fetch {self.symbol} closes: {e}")
        blocked, prior, average = evaluate([c for _, c in done], self.days)
        if blocked is None:
            return unknown(f"{len(done)} completed {self.symbol} sessions, "
                           f"need {self.days}", prior)
        age = (today - done[-1][0]).days
        if age > MAX_SESSION_AGE_DAYS:
            return unknown(f"newest {self.symbol} close is {done[-1][0]}, "
                           f"{age} days old", prior)
        return GateState(blocked, prior, average, session=done[-1][0],
                         symbol=self.symbol, days=self.days)
