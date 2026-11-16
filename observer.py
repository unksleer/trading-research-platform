#!/usr/bin/env python3
"""
observer.py — Phase 1 agent. Looks, reports, never acts.

Three registered experiments each carry abort rules in their own sealed terms
— "any TAKE_PROFIT exit means the profile was changed, stop"; "if average loss
grows faster than average win, revert" — and until now nothing checked them.
They were checked when the operator asked. This runs hourly and checks them
every time.

WHAT IT MAY DO. Read trade ledgers, state files, signal logs, registrations
and the correlation cache; write logs/observer_findings.json for the dashboard
and one audit row per run to logs/observer.jsonl; send one email when a
registration's own stopping rule has fired, deduplicated so the same stop is
not mailed every hour.

WHAT IT MAY NOT DO. Write .env, touch a state file, restart or stop a bot,
change a parameter, or import the tooling that could. Enforced by a test that
parses this file's imports and scans it for the forbidden calls — a check that
cannot act is stronger than one told not to. Phase 2 (see OBSERVER.md) would
add the ability to apply changes within a sealed registration's terms; it does
not exist in this file and must not be added to it.

Findings carry a level. `stop` is a registration rule firing and is the only
level that emails. `warn` is a watch-for clause tripping. `info` is progress.

    .venv/bin/python observer.py            # one run
    .venv/bin/python observer.py --dry-run  # compute, print, write nothing
"""
import argparse
import csv
import glob
import json
import os
import re
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

FINDINGS_PATH = os.path.join(DIR, "logs", "observer_findings.json")
AUDIT_PATH = os.path.join(DIR, "logs", "observer.jsonl")
CORRELATIONS_PATH = os.path.join(DIR, "logs", "correlations.json")

STOP, WARN, INFO = "stop", "warn", "info"

# FCR rejection mix over 501 backtested sessions (backtest_fcr.py, 2026-09-02).
# The live run is judged against this; a material drift means the harness,
# not the market, has changed.
FCR_BASELINE = {"volume_below_threshold": 283, "no_breakout_close_above_range_high": 140,
                "price_below_ema200": 23, "rsi_outside_band": 19,
                "insufficient_history_for_indicators": 7, "no_candle_to_enter_on": 4}
FCR_DRIFT_ABS = 0.20          # absolute share difference that counts as material
FCR_WARN_SESSIONS = 10
FCR_STOP_SESSIONS = 20

EXPECTED_HOLD_DAYS = {"DONCHIAN_BREAKOUT": 28, "RSI_MEAN_REVERSION": 5,
                      "SMA_CROSSOVER": 5, "FIRST_CANDLE_RULE": 1}
LONG_HOLD_MULTIPLE = 2.0
DONCHIAN_AVG_LOSS_LIMIT_PCT = -10.0
STOP_EMAIL_COOLDOWN_S = 24 * 3600


def finding(level, scope, title, detail, **extra):
    return {"level": level, "scope": scope, "title": title, "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(), **extra}


# ── readers ──────────────────────────────────────────────────────────────────

def read_trades(pattern):
    rows = []
    for path in glob.glob(os.path.join(DIR, pattern)):
        try:
            with open(path, newline="") as fh:
                for r in csv.DictReader(fh):
                    if not r.get("exit_time") or r.get("exit_time") == "exit_time":
                        continue
                    try:
                        r["_net_pct"] = float(r.get("net_pct") or 0.0)
                        r["_pnl"] = float(r.get("pnl_usd") or 0.0)
                    except (TypeError, ValueError):
                        continue
                    r["_symbol"] = (r.get("ticker") or r.get("pair") or "").upper()
                    rows.append(r)
        except OSError:
            continue
    return rows


def trades_for(reg, all_trades):
    """
    Only the trades a registration is entitled to be judged on.

    A registration seals a start date and a symbol list. Counting anything
    outside them grades the run on evidence it did not produce: the first dry
    run reported 15 wins and 5 losses for the stock registration that began
    2026-09-04, when the truth was 9 and 4 — the extra six were from the
    voided v1 and v2 runs, still sitting in the same CSV files.
    """
    from utils import experiment
    started = reg.get("started") or ""
    symbols = {s.upper() for s in reg.get("symbols", [])}
    rows = all_trades.get(reg.get("market"), [])
    # exit_time unless the registration seals count_by = entry_time.
    when = experiment.scope_field(reg)
    return [r for r in rows
            if (r.get(when) or "") >= started
            and (not symbols or r["_symbol"] in symbols)]


def effective_factor(market):
    """Pooled -> effective multiplier from the correlation cache; 1.0 if unknown."""
    try:
        with open(CORRELATIONS_PATH) as fh:
            m = json.load(fh).get("markets", {}).get(market, {})
        k, keff = m.get("symbols"), m.get("effective_symbols")
        return (keff / k) if k and keff else 1.0
    except (OSError, ValueError, ZeroDivisionError):
        return 1.0


def parse_stop(rule):
    """
    (date or None, trade count or None, 'later'|'earlier') from prose.

    Only a date that follows "Stop at" is a stop date. The first version took
    ANY date in the rule, so a registration saying "2026-10-04 is a REVIEW
    point, not a stop" would have fired a stop — and an email — on 2026-10-04.
    A test written for that rule shape caught it four days early.
    """
    date = re.search(r"\bStop at\s+(\d{4}-\d{2}-\d{2})", rule or "", re.I)
    count = re.search(r"(\d+)\s+(?:effective|logged)\s+(?:trades|sessions)", rule or "", re.I)
    mode = "later" if re.search(r"whichever is later", rule or "", re.I) else "earlier"
    return (date.group(1) if date else None,
            int(count.group(1)) if count else None, mode)


# ── checks ───────────────────────────────────────────────────────────────────

def check_registrations(active, trades_by_market, fcr_sessions):
    out = []
    today = datetime.now(timezone.utc).date().isoformat()
    for reg in active:
        name, market = reg["name"], reg["market"]
        strategy = reg["config"].get("strategy", "")
        stop_date, stop_n, mode = parse_stop(reg.get("stopping_rule", ""))
        if strategy == "FIRST_CANDLE_RULE":
            started = reg.get("started") or ""
            pooled = sum(1 for k in fcr_sessions if k >= started); eff = pooled; unit = "sessions"
        else:
            rows = trades_for(reg, trades_by_market)
            pooled = len(rows); eff = int(round(pooled * effective_factor(market))); unit = "effective trades"
        date_hit = bool(stop_date and today >= stop_date)
        count_hit = bool(stop_n and eff >= stop_n)
        done = (date_hit and count_hit) if mode == "later" else (date_hit or count_hit)
        detail = (f"{eff} {unit}" + (f" of {stop_n}" if stop_n else "")
                  + (f" · stops {stop_date}" if stop_date else "")
                  + f" · {pooled} pooled")
        # Projection at the run's own observed rate. Oct 4 was a projection
        # made before effective counting existed and never re-derived; showing
        # the live projection next to the sealed date makes a stale date
        # self-evident without a rule for it.
        try:
            start = datetime.fromisoformat(reg["started"]).date()
            days = max(1, (datetime.now(timezone.utc).date() - start).days)
            if stop_n and eff and eff < stop_n:
                need_days = int((stop_n - eff) * days / eff)
                from datetime import timedelta
                eta = (datetime.now(timezone.utc).date() + timedelta(days=need_days)).isoformat()
                detail += f" · at this rate {stop_n} {unit} ≈ {eta}"
        except (KeyError, ValueError, TypeError):
            pass
        if done:
            out.append(finding(STOP, name, "Registration stopping rule reached",
                               detail + " — the run is over on its own terms; review before anything changes."))
        else:
            out.append(finding(INFO, name, "Progress", detail))
    return out


def check_donchian(rows, reg_name):
    out = []
    bad = [r for r in rows if re.search(r"take.?profit|trailing", r.get("exit_reason", ""), re.I)]
    if bad:
        out.append(finding(STOP, reg_name, "Exit type forbidden by the registration",
                           f"{len(bad)} crypto exit(s) by take-profit or trailing stop — the BREAKOUT "
                           f"profile sets both to 0, so this means the profile was changed. "
                           f"First: {bad[0].get('_symbol')} {bad[0].get('exit_time','')[:10]} "
                           f"'{bad[0].get('exit_reason')}'"))
    losses = [r["_net_pct"] for r in rows if r["_net_pct"] < 0]
    wins = [r["_net_pct"] for r in rows if r["_net_pct"] > 0]
    if losses:
        avg_loss = st.mean(losses)
        if avg_loss < DONCHIAN_AVG_LOSS_LIMIT_PCT:
            out.append(finding(WARN, reg_name, "Average loss exceeds the registration's 10% limit",
                               f"avg loss {avg_loss:+.2f}% over {len(losses)} losing trades — "
                               f"the 15% stop may be too wide for this basket"))
    if wins and losses:
        out.append(finding(INFO, reg_name, "Win/loss shape",
                           f"{len(wins)} wins avg {st.mean(wins):+.2f}% · {len(losses)} losses avg "
                           f"{st.mean(losses):+.2f}% · ratio {abs(st.mean(wins)/st.mean(losses)):.2f} "
                           f"(registration wants ≥ 2.0; win rate is not a criterion)"))
    return out


def check_shape_rules(rows, reg, market):
    """
    Win/loss shape, judged by the rules the registration seals — not by rules
    written into this file.

    The first version hardcoded "average loss exceeds average win -> warn". The
    Sep 21 exit sweep showed that ratio is 0.45 on the backtest of this very
    configuration: the rule flagged the strategy's designed shape as a fault
    and would have fired on day one of any run. A rule that cannot tell normal
    from broken is worse than none. So the thresholds live in
    success_criteria.shape_rules and this code only applies them:

        min_win_rate_pct     fire when win rate falls below this ...
        min_profit_factor    ... or profit factor falls below this ...
        min_effective_trades ... but only once this many effective trades exist;
                             before that, report the shape as info.

    Changing a rule is then a registration edit — recorded, sealed, voided and
    re-sealed like any other change to the terms — never a code edit.
    """
    out = []
    wins = [r["_net_pct"] for r in rows if r["_net_pct"] > 0]
    losses = [r["_net_pct"] for r in rows if r["_net_pct"] < 0]
    if not rows or not (wins or losses):
        return out
    n = len(rows)
    eff = int(round(n * effective_factor(market)))
    wr = 100.0 * len(wins) / n
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl else float("inf")
    aw = st.mean(wins) if wins else 0.0
    al = st.mean(losses) if losses else 0.0
    detail = (f"{len(wins)} wins avg {aw:+.2f}% · {len(losses)} losses avg {al:+.2f}% · "
              f"win rate {wr:.0f}% · profit factor {pf:.2f} · {n} pooled ≈ {eff} effective")

    rules = (reg.get("success_criteria") or {}).get("shape_rules") or {}
    if not rules:
        out.append(finding(INFO, reg["name"], "Win/loss shape", detail + " · no shape rules sealed"))
        return out

    need = int(rules.get("min_effective_trades", 20))
    if eff < need:
        out.append(finding(INFO, reg["name"], "Win/loss shape",
                           detail + f" · rules apply at {need} effective"))
        return out
    problems = []
    if "min_win_rate_pct" in rules and wr < float(rules["min_win_rate_pct"]):
        problems.append(f"win rate {wr:.0f}% below the sealed {float(rules['min_win_rate_pct']):.0f}% floor")
    if "min_profit_factor" in rules and pf < float(rules["min_profit_factor"]):
        problems.append(f"profit factor {pf:.2f} below the sealed {float(rules['min_profit_factor']):.2f} floor")
    if problems:
        out.append(finding(WARN, reg["name"], "Shape rule breached", detail + " — " + "; ".join(problems)))
    else:
        out.append(finding(INFO, reg["name"], "Win/loss shape", detail + " · within sealed rules"))
    return out


def fcr_session_reasons():
    """Last decision per session from the FCR signal log; (sessions, Counter)."""
    path = os.path.join(DIR, "logs", "fcr_signals_spy.jsonl")
    last = {}
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("session"):
                    last[d["session"]] = d
    except OSError:
        return {}, Counter()
    reasons = Counter(d.get("reason") or "accepted" for d in last.values())
    return last, reasons


def check_fcr(sessions, reasons, reg_name):
    out = []
    n = len(sessions)
    if n < FCR_WARN_SESSIONS:
        out.append(finding(INFO, reg_name, "Rejection mix", f"{n} sessions logged; drift check starts at {FCR_WARN_SESSIONS}"))
        return out
    base_total = sum(FCR_BASELINE.values())
    drifts = []
    for reason, base_n in FCR_BASELINE.items():
        live = reasons.get(reason, 0) / n
        base = base_n / base_total
        if abs(live - base) > FCR_DRIFT_ABS:
            drifts.append(f"{reason}: live {live:.0%} vs backtest {base:.0%}")
    if drifts:
        level = STOP if n >= FCR_STOP_SESSIONS else WARN
        out.append(finding(level, reg_name, "Live rejection mix has drifted from the backtest",
                           f"over {n} sessions — " + "; ".join(drifts) +
                           (" — registration says the harness is suspect and the run stops"
                            if level == STOP else " — warning until 20 sessions")))
    else:
        out.append(finding(INFO, reg_name, "Rejection mix", f"{n} sessions, within {FCR_DRIFT_ABS:.0%} of the backtest on every reason"))
    return out


MIN_TRADES_FOR_OWN_HOLD = 10


def expected_hold_days(strategy, rows=None):
    """
    What a long hold is, for this strategy, measured from its own run.

    With at least MIN_TRADES_FOR_OWN_HOLD closed trades, the 90th percentile
    of their hold lengths; otherwise the constant. The constants were set
    before any run existed (5 days for mean reversion) and turned out tighter
    than the run's own winners (max 17 days), so the check kept flagging
    normal holds as worth a look. A threshold the run cannot move is a guess
    that never gets corrected.
    """
    holds = []
    for r in rows or []:
        try:
            t0 = datetime.fromisoformat(r["entry_time"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(r["exit_time"].replace("Z", "+00:00"))
            holds.append((t1 - t0).total_seconds() / 86400.0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    if len(holds) >= MIN_TRADES_FOR_OWN_HOLD:
        holds.sort()
        return max(1.0, holds[int(round(0.9 * (len(holds) - 1)))]), "measured"
    return float(EXPECTED_HOLD_DAYS.get(strategy, 7)), "assumed"


def check_positions(trades=None):
    out = []
    try:
        from utils import positions
        held = positions.open_positions()
    except Exception as e:
        return [finding(WARN, "fleet", "Could not read positions", str(e))]
    now = datetime.now(timezone.utc)
    trades = trades or {}
    for p in held:
        try:
            age = (now - datetime.fromisoformat(p["entry_time"].replace("Z", "+00:00"))).days
        except Exception:
            continue
        strategy = "DONCHIAN_BREAKOUT" if p["market"] == "crypto" else "RSI_MEAN_REVERSION"
        expected, basis = expected_hold_days(strategy, trades.get(p["market"]))
        limit = expected * LONG_HOLD_MULTIPLE
        if age > limit:
            out.append(finding(INFO, "positions", f"{p['symbol']} held {age} days",
                               f"more than {LONG_HOLD_MULTIPLE:.0f}x the {strategy} expected hold "
                               f"of {expected:.0f} days ({basis}); not a fault, but worth a look"))
    return out


def check_fleet():
    try:
        from utils import registry
        problems = registry.audit()
    except Exception as e:
        return [finding(WARN, "fleet", "Fleet audit failed", str(e))]
    return [finding(WARN, "fleet", "Fleet problem", p) for p in problems]


# ── run ──────────────────────────────────────────────────────────────────────

def run():
    from utils import experiment
    active = experiment.active()
    trades = {
        "crypto": read_trades("completed_trades_*-usdc_dry.csv"),
        "stocks": read_trades("completed_trades_stock_*_paper.csv"),
    }
    fcr_sessions, fcr_reasons = fcr_session_reasons()

    findings = []
    findings += check_registrations(active, trades, fcr_sessions)
    for reg in active:
        s = reg["config"].get("strategy", "")
        mine = trades_for(reg, trades)
        if s == "DONCHIAN_BREAKOUT":
            findings += check_donchian(mine, reg["name"])
        elif s == "RSI_MEAN_REVERSION":
            findings += check_shape_rules(mine, reg, "stocks")
        elif s == "FIRST_CANDLE_RULE":
            started = reg.get("started") or ""
            scoped = {k: v for k, v in fcr_sessions.items() if k >= started}
            reasons = Counter(d.get("reason") or "accepted" for d in scoped.values())
            findings += check_fcr(scoped, reasons, reg["name"])
    findings += check_positions(trades)
    findings += check_fleet()
    return findings


def recently_emailed(key):
    try:
        with open(AUDIT_PATH) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                for e in d.get("emailed", []):
                    if e == key and time.time() - d.get("t", 0) < STOP_EMAIL_COOLDOWN_S:
                        return True
    except OSError:
        pass
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from utils import env_loader
    env_loader.load()

    findings = run()
    counts = Counter(f["level"] for f in findings)
    print(f"  {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z  "
          f"{counts.get(STOP,0)} stop · {counts.get(WARN,0)} warn · {counts.get(INFO,0)} info")
    for f in findings:
        if f["level"] != INFO:
            print(f"    [{f['level'].upper()}] {f['scope']}: {f['title']} — {f['detail'][:110]}")

    if args.dry_run:
        return 0

    emailed = []
    for f in (x for x in findings if x["level"] == STOP):
        key = f"{f['scope']}|{f['title']}"
        if recently_emailed(key):
            continue
        from utils import notifications
        body = (f"{f['title']}\n\nRegistration: {f['scope']}\n\n{f['detail']}\n\n"
                f"The observer changes nothing. This run has met its own stopping rule; "
                f"review it before anything is altered.\n")
        if notifications.send_email(f"[OBSERVER STOP] {f['scope']}: {f['title']}", body):
            emailed.append(key)

    os.makedirs(os.path.dirname(FINDINGS_PATH), exist_ok=True)
    payload = {"generated_at": time.time(), "findings": findings, "counts": dict(counts)}
    tmp = FINDINGS_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, FINDINGS_PATH)
    with open(AUDIT_PATH, "a") as fh:
        fh.write(json.dumps({"t": time.time(), "counts": dict(counts), "emailed": emailed,
                             "n_findings": len(findings)}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
