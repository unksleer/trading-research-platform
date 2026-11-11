"""
Exit the process when the main loop stops completing.

pm2 restarts a process that exits. It does nothing about one that is alive and
stuck, and reports it "online" throughout: that is how two stock bots spent a
week blocked in a socket read (2026-11-03 and 2026-11-04) without anything
noticing. Request timeouts (utils/alpaca_http.py) remove the known cause. This
is the second layer, for the causes not yet known: whatever blocks the loop,
the process ends, and a stopped or restarting process is something pm2 and the
dashboard can both see.

The loop tells the watchdog it is alive with `beat()`. Before a sleep it says
how long the sleep is (`beat(allow_sec=...)`), because a bot waiting 30 minutes
for the market to open is idle, not stuck. If no beat arrives by the deadline
the watchdog logs where the main thread is and exits with EXIT_CODE.

It exits with os._exit. sys.exit from a thread only ends that thread, and the
main thread cannot be interrupted while it is blocked in a system call.
"""
import logging
import os
import sys
import threading
import time
import traceback

# Distinct from 1 (a Python error or sys.exit(1)) so the cause can be told
# from the exit code alone. EX_SOFTWARE in sysexits.h.
EXIT_CODE = 70


class LoopWatchdog:
    def __init__(self, timeout_sec, name="loop", log=None, on_expire=None,
                 check_every_sec=None, clock=time.monotonic):
        self.timeout_sec = float(timeout_sec)
        self.name = name
        self.log = log or logging.getLogger("watchdog")
        self._on_expire = on_expire or self._exit_process
        self._check_every = (float(check_every_sec) if check_every_sec
                             else max(1.0, min(15.0, self.timeout_sec / 10.0)))
        self._clock = clock
        self._deadline = None
        self._allowed = self.timeout_sec
        self._stop = threading.Event()
        self._thread = None
        self._watched = threading.main_thread()

    # ── called by the loop ──────────────────────────────────────────────────
    def beat(self, allow_sec=0.0):
        """The loop is alive. `allow_sec` is a sleep it is about to take."""
        self._allowed = self.timeout_sec + max(0.0, float(allow_sec))
        self._deadline = self._clock() + self._allowed

    def start(self):
        """Start watching the calling thread. Returns self."""
        self._watched = threading.current_thread()
        self.beat()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"watchdog-{self.name}")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    # ── the watching side ───────────────────────────────────────────────────
    def expired(self):
        return self._deadline is not None and self._clock() > self._deadline

    def _run(self):
        while not self._stop.wait(self._check_every):
            if self.expired():
                self._on_expire(self)
                return

    def where_is_the_loop(self):
        """The watched thread's stack, so the log says what it was stuck in."""
        frame = sys._current_frames().get(self._watched.ident)
        if frame is None:
            return "(the watched thread has no stack)"
        return "".join(traceback.format_stack(frame)).rstrip()

    def _report(self):
        self.log.critical(
            f"WATCHDOG: the {self.name} loop has not completed in "
            f"{self._allowed:.0f}s. Exiting with code {EXIT_CODE} so pm2 can "
            f"restart it. The loop was here:\n{self.where_is_the_loop()}")
        for handler in list(self.log.handlers) + list(logging.getLogger().handlers):
            try:
                handler.flush()
            except Exception:
                pass

    def _exit_process(self, _watchdog=None):
        # Report from a separate thread and wait a bounded time for it. If the
        # loop is stuck because writing the log is stuck, reporting would block
        # too, and the exit must still happen.
        reporter = threading.Thread(target=self._report, daemon=True)
        reporter.start()
        reporter.join(5.0)
        os._exit(EXIT_CODE)


class _NoWatchdog:
    """Stands in when the watchdog is switched off, so the loop has one shape."""

    def beat(self, allow_sec=0.0):
        pass

    def stop(self):
        pass


def start(timeout_sec, name="loop", log=None):
    """A started LoopWatchdog, or a do-nothing stand-in when timeout_sec <= 0."""
    if not timeout_sec or float(timeout_sec) <= 0:
        return _NoWatchdog()
    return LoopWatchdog(timeout_sec, name=name, log=log).start()
