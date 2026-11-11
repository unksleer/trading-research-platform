"""
A timeout on every HTTP request an alpaca-py client makes.

alpaca-py (0.43.5, the version installed here) has no timeout setting. Its
RESTClient calls `self._session.request(method, url, **opts)` and `opts` never
carries one, so requests waits for a reply for as long as the socket stays
open. A connection that dies without closing never closes: on 2026-11-03
slv-bot and on 2026-11-04 meta-bot each sat in one socket read for a week,
online in pm2, with nothing watching a position.

The session is the one place every request passes through, whichever client
method made it and however many pages it fetched, so the timeout is set there:
a transport adapter that fills in a timeout when the caller gave none. A dead
connection then raises `requests.exceptions.Timeout`, which the bot's existing
error handling logs, and the loop tries again on its next tick.

The read timeout is the longest wait for the next bytes, not a limit on the
whole request, so a server that trickles a reply can still take longer. The
loop watchdog in utils/watchdog.py is the backstop for that and for anything
else that is not an Alpaca request.
"""
import os

from requests.adapters import HTTPAdapter


def _seconds(name, default):
    """An env override in seconds; anything unusable falls back to the default."""
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return float(default)
    return value if value > 0 else float(default)


def default_timeout():
    """(connect, read) in seconds. Read from the environment on each call so a
    restart picks up a change to .env like any other tuning value."""
    return (_seconds("ALPACA_CONNECT_TIMEOUT_SEC", 10),
            _seconds("ALPACA_READ_TIMEOUT_SEC", 30))


class TimeoutAdapter(HTTPAdapter):
    """Sends with a default timeout when the request did not set one."""

    def __init__(self, timeout, **kwargs):
        self.timeout = timeout
        super().__init__(**kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


def with_timeout(client, timeout=None):
    """
    Give an alpaca-py client a timeout on every request, and return it.

    Raises rather than returning an unprotected client when the client has no
    requests session where 0.43.5 keeps it. `_session` is a private attribute,
    so an alpaca-py upgrade could move it; a loud failure at that point is the
    intent, because the alternative is the timeout disappearing unnoticed and
    the freeze coming back.
    """
    session = getattr(client, "_session", None)
    if session is None or not callable(getattr(session, "mount", None)):
        raise RuntimeError(
            f"{type(client).__name__} has no requests session at ._session, so "
            f"no timeout can be set on it. alpaca-py has probably changed; "
            f"update utils/alpaca_http.py before running a bot on it.")
    adapter = TimeoutAdapter(timeout or default_timeout())
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return client


def timeout_of(client):
    """The (connect, read) timeout a client will use, or None if it has none.
    For tests and for anyone checking a client before trusting it."""
    session = getattr(client, "_session", None)
    try:
        adapter = session.get_adapter("https://data.alpaca.markets")
    except Exception:
        return None
    return getattr(adapter, "timeout", None)
