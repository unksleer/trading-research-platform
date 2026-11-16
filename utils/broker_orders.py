"""
Sending an order and finding out what actually happened to it.

Until 2026-11-16 the stock bot's order path had never run. Read closely, it
would have gone wrong in the ways that lose money quietly:

  - a sell that failed was logged, and the bot then recorded the trade as
    closed and set itself flat, with the shares still at the broker;
  - a buy was recorded at the signal price and at a share count worked out
    from the signal price, and the fill was never read back;
  - only buys were journalled, so a crash around a sell left nothing to find.

This module is the replacement. One order goes through four steps, and the
journal on disk says which step it reached:

  1. written down, with a client order id, before anything is sent;
  2. sent;
  3. asked about until the venue says it is finished: filled, cancelled,
     expired or rejected. If it is still working when the wait runs out it is
     cancelled, and the answer to the cancel is waited for too;
  4. handed back as what was filled: a quantity and an average price, both
     from the venue. Never the quantity asked for, never the signal price.

An order the venue has not given a final answer on stays `resolved: false`,
and the bot does nothing else until it has one. An order that filled stays
`applied: false` until the bot has written the fill into its state file, so a
crash between the fill and the write is picked up at the next start.

Nothing here decides whether to trade. It is told to buy or sell, and reports.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# The venue will do nothing further with an order in one of these.
FINAL = ("FILLED", "CANCELED", "EXPIRED", "REJECTED")

# Our own, for an order the venue never had.
NOT_PLACED = "NOT_PLACED"

# After a send that got no reply at all, how long "the venue has no such
# order" is not believed. The order may still be on its way in.
IN_FLIGHT_GRACE_SEC = 60.0


class JournalError(Exception):
    """The intent could not be written down, so the order was not sent."""


class Outcome:
    """What became of one order. `final` False means the venue has not said."""

    def __init__(self, client_order_id, entry, final):
        self.client_order_id = client_order_id
        self.side = entry.get("side", "")
        self.status = entry.get("status", "")
        self.order_id = entry.get("order_id", "")
        self.filled_qty = float(Decimal(str(entry.get("filled_qty") or "0")))
        self.avg_price = float(Decimal(str(entry.get("filled_avg_price") or "0")))
        self.signal_price = float(entry.get("signal_price") or 0.0)
        self.reason = entry.get("reason") or ""
        self.final = final

    @property
    def filled(self):
        return self.final and self.filled_qty > 0 and self.avg_price > 0

    def __repr__(self):
        return (f"Outcome({self.side} {self.client_order_id} {self.status} "
                f"filled={self.filled_qty} @ {self.avg_price} final={self.final})")


def _now():
    return datetime.now(timezone.utc).isoformat()


class BrokerOrders:
    def __init__(self, venue, ticker, journal_path, log, *, mode="",
                 poll_timeout=30.0, poll_interval=1.0, cancel_timeout=15.0,
                 sleep=time.sleep, clock=time.monotonic):
        self.venue = venue
        self.ticker = ticker
        self.path = journal_path
        self.log = log
        self.mode = mode
        self.poll_timeout = float(poll_timeout)
        self.poll_interval = float(poll_interval)
        self.cancel_timeout = float(cancel_timeout)
        self._sleep = sleep
        self._clock = clock
        self.entries = self._read()

    # ── the journal ─────────────────────────────────────────────────────────

    def _read(self):
        try:
            with open(self.path) as handle:
                journal = json.load(handle)
        except FileNotFoundError:
            return {}
        # Unreadable is not the same as empty. An empty journal says "no order
        # is outstanding"; a journal that cannot be read does not say that.
        if not isinstance(journal, dict):
            raise ValueError(f"order journal {self.path} is not a JSON object")
        return journal

    def _write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as handle:
            json.dump(self.entries, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def _save(self):
        """Write the journal. The copy in memory stays authoritative for this
        process if the disk refuses, so a full disk cannot make the bot forget
        an order it has just sent."""
        try:
            self._write()
            return True
        except OSError as error:
            self.log.critical(f"Could not write the order journal {self.path}: {error}")
            return False

    def outstanding(self):
        """Client ids of orders not yet settled into the bot's state, oldest
        first: either the venue has not given a final answer, or it has and
        the fill is not yet written into state."""
        pending = [(entry.get("created_at", ""), cid)
                   for cid, entry in self.entries.items() if not entry.get("applied")]
        return [cid for _, cid in sorted(pending)]

    def mark_applied(self, client_order_id):
        entry = self.entries.get(client_order_id)
        if entry is not None and not entry.get("applied"):
            entry["applied"] = True
            entry["applied_at"] = _now()
            self._save()

    # ── buy and sell ────────────────────────────────────────────────────────

    def buy(self, notional_usd, signal_price):
        """Market buy for a dollar amount. Raises JournalError, having sent
        nothing, if the intent cannot be written down first: a position
        nobody has a record of opening is worse than a missed entry."""
        cid = self._new_id("buy")
        self.entries[cid] = self._intent("BUY", signal_price,
                                         notional=round(float(notional_usd), 2))
        if not self._save():
            del self.entries[cid]
            raise JournalError("order journal not writable; BUY not sent")
        return self._send(cid, lambda: self.venue.submit_buy(
            self.ticker, notional_usd, cid))

    def sell(self, quantity, signal_price, reason=""):
        """Market sell of a share quantity. Sent even if the journal cannot be
        written: being unable to get out of a position because a disk is full
        is the worse failure. The entry is still held in memory."""
        cid = self._new_id("sell")
        self.entries[cid] = self._intent("SELL", signal_price,
                                         qty=str(quantity), reason=reason)
        self._save()
        return self._send(cid, lambda: self.venue.submit_sell(
            self.ticker, quantity, cid))

    def _new_id(self, side):
        return f"{self.ticker.lower()}-{side}-{uuid.uuid4().hex[:16]}"

    def _intent(self, side, signal_price, **extra):
        return {"ticker": self.ticker, "side": side, "mode": self.mode,
                "signal_price": float(signal_price), "status": "PENDING",
                "resolved": False, "applied": False, "created_at": _now(),
                **extra}

    def _send(self, cid, submit):
        entry = self.entries[cid]
        try:
            parsed = self.venue.parse_response(submit())
            entry["order_id"] = parsed["order_id"]
            entry["status"] = parsed["status"] or "SUBMITTED"
            self._save()
            self.log.info(f"[{self.mode}] {entry['side']} sent: {parsed['order_id']} "
                          f"({cid}) status={entry['status']}")
        except Exception as error:
            # A refusal and silence are different. On a refusal the venue has
            # said no; on silence the order may have gone in anyway. Either
            # way the venue is asked, by client id, before anything is
            # concluded: a retried send can be refused as a duplicate of an
            # order that was in fact accepted the first time.
            refused = bool(self.venue.answered_no(error))
            entry["submit_error"] = str(error)[:300]
            entry["refused"] = refused
            self._save()
            self.log.error(f"{entry['side']} order ({cid}) "
                           f"{'refused by the venue' if refused else 'got no reply'}: {error}")
        return self._wait(cid, self.poll_timeout)

    # ── finding out ─────────────────────────────────────────────────────────

    def _ask(self, cid):
        """('found', parsed) | ('absent', None) | ('unknown', None)."""
        try:
            parsed = self.venue.find_order(cid)
        except Exception as error:
            self.log.warning(f"Could not ask the venue about {cid}: {error}")
            return "unknown", None
        return ("found", parsed) if parsed is not None else ("absent", None)

    def _age_sec(self, entry):
        try:
            created = datetime.fromisoformat(entry["created_at"])
            return (datetime.now(timezone.utc) - created).total_seconds()
        except (KeyError, ValueError, TypeError):
            return float("inf")

    def _wait(self, cid, timeout):
        """Ask until the order is finished or the wait runs out; then cancel
        it and wait for that. Returns an Outcome, final or not."""
        entry = self.entries[cid]
        deadline = self._clock() + timeout
        cancel_sent = False
        while True:
            answer, parsed = self._ask(cid)
            if answer == "found":
                entry["order_id"] = parsed["order_id"] or entry.get("order_id", "")
                entry["status"] = parsed["status"]
                entry["filled_qty"] = str(parsed["filled_size"])
                entry["filled_avg_price"] = str(parsed["average_price"])
                if parsed["status"] in FINAL:
                    return self._finish(cid)
            elif answer == "absent":
                # Believed at once after a refusal. After silence, only once
                # the order has had time to arrive.
                if entry.get("refused") or self._age_sec(entry) >= IN_FLIGHT_GRACE_SEC:
                    entry["status"] = NOT_PLACED
                    return self._finish(cid)

            if self._clock() >= deadline:
                if cancel_sent or answer != "found":
                    break
                # Still working after the wait. Do not leave it at the venue
                # to fill later behind the bot's back: cancel, and wait for
                # the venue to say what the order finally did.
                self.log.warning(f"{entry['side']} {cid} still {entry['status']} after "
                                 f"{timeout:.0f}s; cancelling")
                try:
                    self.venue.cancel_order(entry["order_id"])
                except Exception as error:
                    # Often "already filled". The next answer says which.
                    self.log.warning(f"Cancel of {cid} not accepted: {error}")
                cancel_sent = True
                deadline = self._clock() + self.cancel_timeout
                continue
            self._sleep(self.poll_interval)

        self._save()
        self.log.error(f"{entry['side']} {cid} has no final answer from the venue "
                       f"(last status {entry['status']}). Nothing else will be sent "
                       f"until it has one.")
        return Outcome(cid, entry, final=False)

    def _finish(self, cid):
        entry = self.entries[cid]
        entry["resolved"] = True
        entry["resolved_at"] = _now()
        filled = Decimal(str(entry.get("filled_qty") or "0"))
        if filled <= 0:
            # Nothing was filled, so there is nothing to write into state.
            entry["applied"] = True
            entry["applied_at"] = entry["resolved_at"]
        self._save()
        return Outcome(cid, entry, final=True)

    def settle(self, client_order_id):
        """Take an outstanding order as far as it will go now. Used at startup
        and at the top of a tick for anything a previous pass left behind."""
        entry = self.entries[client_order_id]
        if entry.get("resolved"):
            return Outcome(client_order_id, entry, final=True)
        # No long wait: one look, and a cancel if it is still working.
        return self._wait(client_order_id, 0.0)

    # ── the venue's own book ────────────────────────────────────────────────

    def position_qty(self):
        return self.venue.position_qty(self.ticker)

    def unknown_open_orders(self):
        """Orders working at the venue for this ticker that are not this
        bot's. One of its own that it already has a final answer on is left
        out: the venue's open list can trail the order's own status by a
        moment, and the status asked for directly is the one that counts.
        One of its own without a final answer is `outstanding`, not unknown."""
        return [order for order in self.venue.open_orders(self.ticker)
                if order.get("client_order_id") not in self.entries]
