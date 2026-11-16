"""
Venue adapters — the boundary between shared logic and exchange specifics.

Two bots grew up separately and diverged in the parts that protect capital:
the crypto bot has an order journal, startup reconciliation, atomic state and a
risk engine; the stock bot had none of them. That divergence was not a design
decision, it was drift, and it is invisible until an order is lost or a state
file is corrupted mid-write.

Almost nothing about safety is venue-specific. Position accounting, stops,
risk limits, reconciliation and graduation are identical whether the thing
being traded is SOL or SPY. What genuinely differs is small:

  - how an order is submitted
  - how the response reports fills, fees and status
  - what the fee actually is
  - whether the market is open

Everything else is shared. A new venue means a new adapter here, not a new bot.

Per-asset variation stays where it already works: the coin/ticker -> profile ->
base resolution in .env. That is deliberately unconstrained, because volatility
and liquidity genuinely differ per asset. What must NOT vary per asset is the
safety machinery, which is why it lives above this boundary rather than inside
each bot.
"""

import logging
from decimal import Decimal


logger = logging.getLogger("coinbase_bot.venue")


class Venue:
    """Interface every adapter implements."""

    name = "base"
    # Round-trip cost as a fraction of notional. The single term that most
    # decides which strategies are viable, so it is explicit per venue rather
    # than assumed or hardcoded in a strategy.
    fee_rate_per_side = 0.0
    always_open = True

    def is_open(self):
        """Whether the venue accepts orders right now."""
        return self.always_open

    def submit_buy(self, symbol, notional_usd, client_order_id):
        raise NotImplementedError

    def submit_sell(self, symbol, quantity, client_order_id):
        raise NotImplementedError

    def parse_response(self, response):
        """
        Normalise a venue order response.

        Returns a dict with: order_id, status, filled_size, filled_value,
        fees, average_price. Missing fields come back as zero rather than
        absent, so callers never branch on presence.
        """
        raise NotImplementedError

    def round_trip_cost_pct(self):
        return self.fee_rate_per_side * 2 * 100


class CoinbaseVenue(Venue):
    """
    Coinbase Advanced Trade.

    fee_rate_per_side is the base-tier MAKER rate — the bot places post_only
    limit orders, so it is what actually gets charged. This comment previously
    described 0.006 as the maker rate while auto_learner described the same
    number as the taker rate; the venue's own schedule says maker is 0.40% and
    taker 0.60%, so this was the wrong half
    since it places limit_order_gtc. The market-order exit fallback pays the
    taker rate, roughly double.
    """

    name = "coinbase"
    fee_rate_per_side = 0.004
    always_open = True

    def __init__(self, client=None):
        self.client = client

    def submit_buy(self, symbol, notional_usd, client_order_id):
        raise NotImplementedError(
            "bot.py owns Coinbase order submission, including limit pricing and "
            "the market fallback. This adapter exists for fee and parsing "
            "consistency; moving submission here would mean rewriting a path "
            "that is already hardened and tested."
        )

    def parse_response(self, response):
        order = (response or {}).get("order", response) or {}
        return {
            "order_id": order.get("order_id", ""),
            "status": (order.get("status") or "").upper(),
            "filled_size": Decimal(str(order.get("filled_size") or 0)),
            "filled_value": Decimal(str(order.get("filled_value") or 0)),
            "fees": Decimal(str(order.get("total_fees") or 0)),
            "average_price": Decimal(str(order.get("average_filled_price") or 0)),
        }


class AlpacaVenue(Venue):
    """
    Alpaca equities.

    Commission-free, so the round trip is slippage only. That is why strategies
    which lose on Coinbase can win here, and why results never transfer between
    the two.
    """

    name = "alpaca"
    fee_rate_per_side = 0.0
    always_open = False

    def __init__(self, api_key="", secret_key="", paper=True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self._client = None

    def client(self):
        if self._client is None:
            from alpaca.trading.client import TradingClient
            from utils.alpaca_http import with_timeout
            # No request without a timeout: alpaca-py sets none, and a dead
            # connection then blocks the caller for good (see alpaca_http).
            self._client = with_timeout(TradingClient(
                self.api_key, self.secret_key, paper=self.paper))
        return self._client

    def is_open(self):
        """
        Whether the venue accepts orders right now.

        Asks the venue rather than inferring from a weekday check, because
        holidays and early closes are not derivable from the clock.

        Fails CLOSED on error, which is right for a trading gate — but it
        makes an outage indistinguishable from a genuine close, so the error
        is logged. Use `market_status()` where that distinction matters.
        """
        return self.market_status() == "open"

    def market_status(self):
        """
        "open", "closed", or "unknown" when the venue could not be reached.

        Display needs the third value. Reporting "closed" for an unreachable
        API tells the viewer the market is shut when the truth is that we do
        not know, which is exactly the class of silent wrong answer this
        project keeps finding.
        """
        try:
            return "open" if bool(self.client().get_clock().is_open) else "closed"
        except Exception as e:
            logger.warning(f"Could not read the Alpaca market clock: {e}")
            return "unknown"

    def submit_buy(self, symbol, notional_usd, client_order_id):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        return self.client().submit_order(MarketOrderRequest(
            symbol=symbol,
            notional=round(float(notional_usd), 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            # Carried through so a resubmission after a crash is recognised as
            # the same order rather than becoming a second position.
            client_order_id=client_order_id,
        ))

    def submit_sell(self, symbol, quantity, client_order_id):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        return self.client().submit_order(MarketOrderRequest(
            symbol=symbol,
            # Nine places, which is what Alpaca fills fractional shares to. At
            # six, a position of 0.1336898 shares rounded up to 0.133690 and
            # the sell asked for more than was held.
            qty=round(float(quantity), 9),
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        ))

    def get_order_by_client_id(self, client_order_id):
        """Used by reconciliation to find out what happened to an order the
        bot submitted but never recorded the outcome of."""
        try:
            return self.client().get_order_by_client_id(client_order_id)
        except Exception:
            return None

    # ── What the real-order path needs, and the lenient lookup above cannot
    #    give it: "the venue says there is no such order" kept apart from "the
    #    venue could not be asked". The first means nothing was placed. The
    #    second means nothing is known, and treating it as the first is how a
    #    filled order gets written off as never sent.

    @staticmethod
    def answered_no(error):
        """True when the venue itself replied and refused (HTTP 4xx), as
        opposed to a timeout or a dropped connection where no reply came."""
        status = getattr(error, "status_code", None)
        return isinstance(status, int) and 400 <= status < 500 and status not in (408, 429)

    def find_order(self, client_order_id):
        """The order with this client id, parsed, or None when the venue
        answers that it has none. Raises when the venue cannot be asked."""
        try:
            order = self.client().get_order_by_client_id(client_order_id)
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                return None
            raise
        return self.parse_response(order)

    def cancel_order(self, order_id):
        self.client().cancel_order_by_id(order_id)

    def position_qty(self, symbol):
        """Shares of `symbol` the account holds right now, as a Decimal:
        0 when flat, negative when short. Raises when the venue cannot be
        asked. Read from the full position list because the single-position
        call reports "flat" as an error, the same way it reports an outage."""
        for position in self.client().get_all_positions():
            if str(getattr(position, "symbol", "")).upper() == symbol.upper():
                qty = Decimal(str(position.qty))
                side = getattr(position, "side", "")
                if str(getattr(side, "value", side)).lower() == "short" and qty > 0:
                    qty = -qty
                return qty
        return Decimal("0")

    def open_orders(self, symbol):
        """Orders for `symbol` still working at the venue, parsed."""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        orders = self.client().get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN, symbols=[symbol]))
        # With the client id, so a caller can tell its own orders from anyone
        # else's. This list lags: on 2026-11-16 the paper API still listed an
        # order here a moment after reporting that same order CANCELED when
        # asked about it directly. The direct answer is the one to believe.
        return [{**self.parse_response(order),
                 "client_order_id": str(getattr(order, "client_order_id", "") or "")}
                for order in orders]

    def endpoint(self):
        """The base URL orders are sent to, so a caller can check paper
        against live before it sends anything."""
        url = getattr(self.client(), "_base_url", "")
        return str(getattr(url, "value", url))

    def parse_response(self, response):
        def num(attr):
            value = getattr(response, attr, None)
            return Decimal(str(value)) if value not in (None, "") else Decimal("0")

        def text(attr):
            # alpaca-py's status and side are enums that are also strings.
            # str() of one is "OrderStatus.FILLED", not "filled", so a status
            # read that way never compared equal to anything. Take the value.
            value = getattr(response, attr, None)
            return str(getattr(value, "value", value) or "")

        filled_qty = num("filled_qty")
        avg_price = num("filled_avg_price")
        return {
            "order_id": text("id"),
            "status": text("status").upper(),
            "filled_size": filled_qty,
            "filled_value": filled_qty * avg_price,
            # Commission-free: reported for interface symmetry, always zero.
            "fees": Decimal("0"),
            "average_price": avg_price,
        }


def for_market(market, **kwargs):
    """Adapter for 'crypto' or 'stocks'."""
    if market == "crypto":
        return CoinbaseVenue(**kwargs)
    if market == "stocks":
        return AlpacaVenue(**kwargs)
    raise ValueError(f"unknown market {market!r}; expected 'crypto' or 'stocks'")
