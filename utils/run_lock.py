"""
One process at a time on an order-sending bot's files.

A bot reads its state file and order journal once, at startup, and from then
on the copy in memory is the one it trusts and writes back. Anything else that
changed those files underneath it would be overwritten at the bot's next save,
and until then the two would disagree about what is held. With real orders
that ends in a position sold twice or never sold.

So the bot holds a lock for as long as it runs, and close_position.py takes
the same lock before it touches anything. The lock is the kernel's (flock on
an open file), not a file whose existence means "locked": it is released when
the process ends, however it ends, so a crash cannot leave a bot locked out.
"""
import fcntl
import os


class Held(Exception):
    """Another process has the lock. `holder` says which, if it said."""

    def __init__(self, path, holder):
        super().__init__(f"{path} is held by {holder}")
        self.path, self.holder = path, holder


def acquire(path, who=""):
    """
    Take the lock at `path` or raise Held. Returns the open file; the lock
    lasts until it is closed or the process ends, so keep a reference.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    handle = open(path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        holder = handle.read().strip() or "another process"
        handle.close()
        raise Held(path, holder)
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid {os.getpid()} ({who})" if who else f"pid {os.getpid()}")
    handle.flush()
    return handle


def release(handle):
    if handle is not None and not handle.closed:
        handle.close()
