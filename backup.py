"""
Nightly backup of the two things git does not hold: the evidence and the
repository itself.

GitHub is the only off-machine copy of the code and it refused writes for a
day in October. The ledgers, state files, candle store, registrations and
observer records are gitignored on purpose and exist nowhere else at all.
This writes both to BACKUP_DIR (default ~/backups/coinbase-trading-bot):

  <date>/repo.bundle     every branch and tag, restorable with `git clone`
  <date>/evidence.tar.gz the runtime files listed in EVIDENCE

and keeps RETAIN_DAYS of them. `.env` is NOT included: it holds live
credentials, and copying secrets into a second place is a decision, not a
default. A restore needs it re-entered by hand.

Same disk as the source, so this covers "a file was deleted or corrupted",
not "the machine died". An off-box copy is the next step, not this one.
"""
import glob
import os
import shutil
import subprocess
import sys
import tarfile
import time

DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.environ.get("BACKUP_DIR") or os.path.expanduser("~/backups/coinbase-trading-bot")
RETAIN_DAYS = int(os.environ.get("BACKUP_RETAIN_DAYS", "14"))

EVIDENCE = (
    "state_*.json",
    "completed_trades_*.csv",
    "trades.csv", "trades_dry.csv",
    "data/*.sqlite",
    "experiments/*.json",
    "logs/observer_findings.json", "logs/observer.jsonl",
    "logs/correlations.json",
    "logs/signal_log_*.csv",
    "logs/fcr_signals_*.jsonl",
    # An order-sending rehearsal bot's state, ledger, journal and signal log.
    "broker_paper/*.json", "broker_paper/*.csv",
    "logs/order_journal_stock_*.json",
)
EXCLUDE = (".env",)


def evidence_files(root=DIR):
    out = []
    for pattern in EVIDENCE:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            rel = os.path.relpath(path, root)
            if os.path.isfile(path) and rel not in EXCLUDE and ".env" not in rel.split(os.sep):
                out.append(rel)
    return out


def run(root=DIR, dest=BACKUP_DIR, retain_days=RETAIN_DAYS, now=None):
    now = now or time.time()
    stamp = time.strftime("%Y-%m-%d", time.gmtime(now))
    target = os.path.join(dest, stamp)
    os.makedirs(target, exist_ok=True)
    os.chmod(dest, 0o700)

    bundle = os.path.join(target, "repo.bundle")
    res = subprocess.run(["git", "bundle", "create", bundle, "--all"],
                         cwd=root, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git bundle failed: {res.stderr.strip()[:300]}")
    res = subprocess.run(["git", "bundle", "verify", bundle], cwd=root, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"bundle does not verify: {res.stderr.strip()[:300]}")

    files = evidence_files(root)
    tar_path = os.path.join(target, "evidence.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        for rel in files:
            tar.add(os.path.join(root, rel), arcname=rel)

    pruned = prune(dest, retain_days, now)
    return {"dir": target, "bundle_bytes": os.path.getsize(bundle),
            "evidence_files": len(files), "evidence_bytes": os.path.getsize(tar_path),
            "pruned": pruned}


def prune(dest, retain_days, now):
    """Drop dated backup folders older than retain_days. Only folders named like a date."""
    gone = []
    cutoff = now - retain_days * 86400
    for name in sorted(os.listdir(dest)):
        path = os.path.join(dest, name)
        if not os.path.isdir(path) or len(name) != 10 or name[4] != "-" or name[7] != "-":
            continue
        try:
            when = time.mktime(time.strptime(name, "%Y-%m-%d"))
        except ValueError:
            continue
        if when < cutoff:
            shutil.rmtree(path)
            gone.append(name)
    return gone


if __name__ == "__main__":
    info = run()
    print(f"backup {info['dir']}: bundle {info['bundle_bytes']/1e6:.1f} MB, "
          f"{info['evidence_files']} evidence files {info['evidence_bytes']/1e6:.1f} MB, "
          f"pruned {info['pruned'] or 'none'}")
    sys.exit(0)
