"""
Provider seam. The gateway speaks one small interface; two implementations:

  AnthropicProvider  the real thing (anthropic SDK, Messages API)
  OfflineProvider    deterministic, no network. Used by the tests and whenever
                     no credentials are present, so the whole pipeline runs
                     end to end offline. Its rows are logged with
                     provider='offline' and are excluded from every cost
                     figure in the write-up.

Content blocks are plain dicts in the Messages API shape
({"type": "text", ...}, {"type": "tool_use", ...}) so the agent loop and the
offline provider never depend on SDK classes.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ProviderResponse:
    content: list[dict]
    stop_reason: str
    usage: Usage
    model: str
    raw: Any = field(default=None, repr=False)

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class ProviderError(Exception):
    """Any failure the gateway may answer with a fallback to the other model."""

    def __init__(self, message: str, *, retryable_elsewhere: bool = True):
        super().__init__(message)
        self.retryable_elsewhere = retryable_elsewhere


class Provider(Protocol):
    name: str

    def complete(self, *, model: str, system: str | None, messages: list[dict],
                 tools: list[dict] | None, max_tokens: int, effort: str | None) -> ProviderResponse: ...


# --------------------------------------------------------------------------- #
# Real provider
# --------------------------------------------------------------------------- #

def credentials_present(repo_root: Path | None = None) -> bool:
    """True if the SDK would find a credential. Loads REPO_ROOT/.env read-only
    (no override) so a key kept with the bot's other secrets is found."""
    if repo_root is not None:
        env_file = repo_root / ".env"
        if env_file.is_file():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file, override=False)
            except Exception:
                pass
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = Path.home() / ".config" / "anthropic"
    return profile_dir.is_dir() and any(profile_dir.iterdir())


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client=None, timeout: float = 120.0, max_retries: int = 2):
        import anthropic
        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic(timeout=timeout, max_retries=max_retries)

    def complete(self, *, model, system, messages, tools, max_tokens, effort) -> ProviderResponse:
        a = self._anthropic
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if effort:
            kwargs["output_config"] = {"effort": effort}
        try:
            resp = self.client.messages.create(**kwargs)
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            # Same key on both models: a fallback cannot help.
            raise ProviderError(f"{type(e).__name__}: {e}", retryable_elsewhere=False) from e
        except a.APIStatusError as e:
            raise ProviderError(f"{type(e).__name__} {e.status_code}: {e.message}") from e
        except (a.APIConnectionError, a.APITimeoutError) as e:
            raise ProviderError(f"{type(e).__name__}: {e}") from e
        u = resp.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        content = [b.to_dict() for b in resp.content]
        return ProviderResponse(content=content, stop_reason=resp.stop_reason or "end_turn",
                                usage=usage, model=resp.model, raw=resp)


# --------------------------------------------------------------------------- #
# Offline provider
# --------------------------------------------------------------------------- #

def _est_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, default=str)) // 4)


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        parts = []
        for b in c or []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b["text"])
        if parts:
            return "\n".join(parts)
    return ""


def _first_user_text(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            for b in c or []:
                if isinstance(b, dict) and b.get("type") == "text":
                    return b["text"]
    return ""


def _tool_results(messages: list[dict]) -> list[tuple[str, Any]]:
    """(tool_name, parsed output) for every tool_result so far, in order."""
    id_to_name: dict[str, str] = {}
    out: list[tuple[str, Any]] = []
    for m in messages:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                id_to_name[b["id"]] = b["name"]
            elif b.get("type") == "tool_result":
                raw = b.get("content")
                if isinstance(raw, list):
                    raw = "".join(x.get("text", "") for x in raw if isinstance(x, dict))
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    parsed = raw
                out.append((id_to_name.get(b["tool_use_id"], "?"), parsed))
    return out


class OfflineProvider:
    """
    A scripted stand-in. It is not a language model; it is a deterministic
    policy that exercises every code path (tool calls, final answers, judge
    scores, refusals) so the pipeline, logging and tests run without a key.
    """
    name = "offline"

    PROPOSE_RE = re.compile(r"\b(propose|change|set|move|tighten|widen|raise|lower)\b", re.I)
    LIVE_RE = re.compile(r"\b(live|real money|DRY_RUN|ALPACA_PAPER|kill switch)\b", re.I)
    SUMMARY_RE = re.compile(r"\b(win rate|performance|profit factor|summar|average|net p&l|pnl|how (well|many))\b", re.I)

    def __init__(self, fail_models: set[str] | None = None):
        self.fail_models = set(fail_models or ())
        self.calls = 0

    def _resp(self, model, content, stop_reason, messages, system) -> ProviderResponse:
        self.calls += 1
        usage = Usage(input_tokens=_est_tokens(messages) + _est_tokens(system or ""),
                      output_tokens=_est_tokens(content))
        return ProviderResponse(content=content, stop_reason=stop_reason, usage=usage, model=model)

    def complete(self, *, model, system, messages, tools, max_tokens, effort) -> ProviderResponse:
        if model in self.fail_models:
            raise ProviderError(f"offline: simulated failure for {model}")
        sys_text = system or ""
        if "JUDGE" in sys_text.upper() and "RUBRIC" in sys_text.upper():
            return self._resp(model, [{"type": "text", "text": self._judge(_last_user_text(messages))}],
                              "end_turn", messages, system)
        if "RERANK" in sys_text.upper():
            m = re.search(r"at most (\d+)", _last_user_text(messages))
            n = int(m.group(1)) if m else 5
            return self._resp(model, [{"type": "text", "text": json.dumps(list(range(1, n + 1)))}],
                              "end_turn", messages, system)
        if tools:
            return self._agent_step(model, messages, system, tools)
        text = _last_user_text(messages)
        if "<context>" in text:
            return self._resp(model, [{"type": "text", "text": self._rag_answer(text)}], "end_turn", messages, system)
        return self._resp(model, [{"type": "text", "text": "OFFLINE"}], "end_turn", messages, system)

    # -- judge: token-overlap score on a 0/1/2 rubric ----------------------- #
    @staticmethod
    def _judge(prompt: str) -> str:
        exp = re.search(r"EXPECTED:\s*(.*?)(?:\n[A-Z ]+:|\Z)", prompt, re.S)
        ans = re.search(r"ANSWER:\s*(.*?)(?:\n[A-Z ]+:|\Z)", prompt, re.S)
        e = set(re.findall(r"[a-z0-9.%-]+", (exp.group(1) if exp else "").lower()))
        a = set(re.findall(r"[a-z0-9.%-]+", (ans.group(1) if ans else "").lower()))
        e = {t for t in e if len(t) > 2}
        overlap = len(e & a) / max(1, len(e))
        score = 2 if overlap >= 0.5 else 1 if overlap >= 0.2 else 0
        return json.dumps({"score": score, "reason": f"offline token overlap {overlap:.2f}"})

    # -- RAG: extractive answer from the top chunk --------------------------- #
    @staticmethod
    def _rag_answer(text: str) -> str:
        ctx = re.search(r"<context>(.*?)</context>", text, re.S)
        body = ctx.group(1).strip() if ctx else ""
        first = re.split(r"\n\s*\n", body)[0] if body else ""
        return first[:600] or "I could not find that in the corpus."

    # -- agent: keyword policy over the three tools ------------------------- #
    def _agent_step(self, model, messages, system, tools) -> ProviderResponse:
        q = _first_user_text(messages)
        q_q = re.sub(r"<context>.*?</context>", "", q, flags=re.S)
        done = _tool_results(messages)
        names = [n for n, _ in done]
        tool_names = {t["name"] for t in tools}
        wants_propose = bool(self.PROPOSE_RE.search(q_q)) and "propose_parameter_change" in tool_names
        wants_live = bool(self.LIVE_RE.search(q_q))

        if wants_live and not wants_propose:
            txt = ("I will not do that. Switching to live trading, touching DRY_RUN or ALPACA_PAPER, "
                   "or writing live configuration is outside what this agent can do; a person does it "
                   "through trade.sh. I can read the ledger or summarise performance instead.")
            return self._resp(model, [{"type": "text", "text": txt}], "end_turn", messages, system)

        def call(name, inp):
            return self._resp(model, [{"type": "tool_use", "id": f"toolu_offline_{self.calls}",
                                       "name": name, "input": inp}], "tool_use", messages, system)

        ticker = None
        m = re.search(r"\b([A-Z]{2,5})\b(?=.*\b(trade|ticker|position|stock)s?\b)", q_q)
        if m and m.group(1) not in {"RSI", "SMA", "EMA", "ATR", "SPY"} | set():
            ticker = m.group(1)
        if m and m.group(1) == "SPY":
            ticker = "SPY"

        dm = re.search(r"\b(20\d\d-\d\d-\d\d)\b", q_q)
        since = dm.group(1) if dm else None
        if not done:
            if self.SUMMARY_RE.search(q_q) or wants_propose:
                return call("summarise_strategy_performance",
                            {"scope": ticker or "stocks", "since": since})
            return call("read_ledger", {"ticker": ticker, "limit": 50, "since": since})
        if wants_propose and "propose_parameter_change" not in names:
            summ = next((o for n, o in done if n == "summarise_strategy_performance"), {})
            param = "STOP_LOSS_PERCENT"
            cur, new = 5.0, 4.0
            pm = re.search(r"(stop[- ]loss|take[- ]profit|trailing stop|rsi (?:overbought|oversold))", q_q, re.I)
            if pm:
                key = pm.group(1).lower()
                param = {"stop-loss": "STOP_LOSS_PERCENT", "stop loss": "STOP_LOSS_PERCENT",
                         "take-profit": "TAKE_PROFIT_PERCENT", "take profit": "TAKE_PROFIT_PERCENT",
                         "trailing stop": "TRAILING_STOP_PERCENT",
                         "rsi overbought": "RSI_OVERBOUGHT", "rsi oversold": "RSI_OVERSOLD"}[key]
                cur = {"STOP_LOSS_PERCENT": 5.0, "TAKE_PROFIT_PERCENT": 8.0, "TRAILING_STOP_PERCENT": 1.5,
                       "RSI_OVERBOUGHT": 65.0, "RSI_OVERSOLD": 35.0}[param]
            nm = re.search(r"to\s+(\d+(?:\.\d+)?)\s*%?", q_q)
            if nm:
                new = float(nm.group(1))
            return call("propose_parameter_change", {
                "parameter": param, "current_value": cur, "proposed_value": new,
                "rationale": "Requested by the operator; evidence attached from the ledger summary.",
                "evidence": [f"trades={summ.get('trades')} win_rate_pct={summ.get('win_rate_pct')}"],
                "voids_running_registration": True,
            })
        # final answer: echo the key numbers so deterministic checks can see them
        last_name, last_out = done[-1]
        if last_name == "propose_parameter_change":
            txt = (f"Proposal {last_out.get('proposal_id')} is queued with status "
                   f"{last_out.get('status')} in {last_out.get('queue_path')}. Nothing in live "
                   f"configuration was changed; a person must confirm it, and applying it would void the "
                   f"running registration, which would have to be re-sealed.")
        elif last_name == "summarise_strategy_performance":
            txt = (f"Scope {last_out.get('scope')}: {last_out.get('trades')} closed trades, "
                   f"{last_out.get('wins')} wins and {last_out.get('losses')} losses, win rate "
                   f"{last_out.get('win_rate_pct')}%, average win {last_out.get('avg_win_pct')}%, "
                   f"average loss {last_out.get('avg_loss_pct')}%, profit factor "
                   f"{last_out.get('profit_factor')}, net P&L ${last_out.get('net_pnl_usd')}. "
                   f"Exit reasons: {json.dumps(last_out.get('exit_reason_counts'))}. "
                   f"Breakeven win rate {last_out.get('breakeven_win_rate_pct')}%.")
        else:
            trades = last_out.get("trades", []) if isinstance(last_out, dict) else []
            lines = [f"{t['ticker']} {t['entry_time'][:10]} -> {t['exit_time'][:10]} net {t['net_pct']}% "
                     f"({t['exit_reason']})" for t in trades[:50]]
            txt = f"{last_out.get('count')} trades from {last_out.get('source_files')}:\n" + "\n".join(lines)
        return self._resp(model, [{"type": "text", "text": txt}], "end_turn", messages, system)
