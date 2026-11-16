"""
Pre-register an experiment before running it.

Nearly every wrong conclusion this project has reached came from deciding what
counted as success after seeing the results: a grid searched over thirty
parameter pairs with the winner reported on the same data it was chosen from; a
timeframe switched because a number looked better, without first checking
whether the new setting could produce the outcome being sought; "we just need
more data" applied to a question the data could never answer.

The fix is not more discipline in the moment — it is writing the criteria down
first and making them awkward to change afterwards.

A registration records the hypothesis, the exact configuration, the start date,
the stopping rule and the success criteria, then hashes them. Results are
attached later and the hash is rechecked. If the terms moved between
registration and conclusion, the report says so instead of quietly grading
against the new terms.

This cannot prevent anyone editing a JSON file. It is meant to make doing so a
deliberate act that leaves a trace, which is enough — the failure it addresses
is drift, not fraud.
"""
import hashlib
import json
import os
import time

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENTS = os.path.join(DIR, "experiments")

# The fields that constitute the promise. Anything outside this may be edited
# freely — notes, links, a running log — without invalidating the terms.
SEALED_FIELDS = ("hypothesis", "market", "symbols", "config",
                 "success_criteria", "stopping_rule", "started")


def _seal(record):
    payload = {k: record.get(k) for k in SEALED_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def path_for(name):
    return os.path.join(EXPERIMENTS, f"{name}.json")


def register(name, hypothesis, market, symbols, config,
             success_criteria, stopping_rule, started=None, notes=""):
    """
    Write a sealed registration. Refuses to overwrite an existing one.

    Refusing matters: silently replacing a registration is exactly the drift
    this is built to catch.
    """
    os.makedirs(EXPERIMENTS, exist_ok=True)
    target = path_for(name)
    if os.path.exists(target):
        raise FileExistsError(
            f"{name} is already registered. Conclude it, or pick a new name — "
            f"rewriting a registration defeats the point of having one.")

    record = {
        "name": name,
        "hypothesis": hypothesis,
        "market": market,
        "symbols": sorted(symbols),
        "config": config,
        "success_criteria": success_criteria,
        "stopping_rule": stopping_rule,
        "started": started or time.strftime("%Y-%m-%d"),
        "notes": notes,
        "status": "running",
        "result": None,
        "concluded": None,
    }
    record["seal"] = _seal(record)
    with open(target, "w") as handle:
        json.dump(record, handle, indent=2)
    return record


def load(name):
    with open(path_for(name)) as handle:
        return json.load(handle)


def verify(record):
    """True when the sealed terms still match what was registered."""
    return record.get("seal") == _seal(record)


def scope_field(record):
    """
    Which of a trade's timestamps decides whether it belongs to a registration.

    The default, exit_time, is how every registration up to stocks v4 was
    counted: a trade counts if it closed on or after the start date. That is
    right when the run starts flat or the rules are unchanged from what opened
    the position.

    A registration can instead seal success_criteria.count_by = "entry_time".
    Stocks v5 does, because it started with two positions open that v4 had
    entered on days the v5 gate would have refused. Scoring their exits as v5
    trades would grade the gate on entries it did not allow.
    """
    by = (record.get("success_criteria") or {}).get("count_by")
    return "entry_time" if by == "entry_time" else "exit_time"


def conclude(name, result, verdict, concluded=None):
    """
    Attach the outcome. Records whether the terms were altered en route.

    A tampered registration is not rejected — it is concluded and labelled,
    because the useful signal is knowing which conclusions were graded against
    moved goalposts.
    """
    record = load(name)
    intact = verify(record)
    record["result"] = result
    record["verdict"] = verdict
    record["status"] = "concluded"
    record["concluded"] = concluded or time.strftime("%Y-%m-%d")
    record["terms_intact"] = intact
    if not intact:
        record["warning"] = ("Sealed terms changed after registration. This "
                             "conclusion was graded against different criteria "
                             "than were originally committed to.")
    with open(path_for(name), "w") as handle:
        json.dump(record, handle, indent=2)
    return record


def active():
    """Registered experiments still running."""
    if not os.path.isdir(EXPERIMENTS):
        return []
    out = []
    for entry in sorted(os.listdir(EXPERIMENTS)):
        if not entry.endswith(".json"):
            continue
        try:
            with open(os.path.join(EXPERIMENTS, entry)) as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if record.get("status") == "running":
            record["terms_intact"] = verify(record)
            out.append(record)
    return out
