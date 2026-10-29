"""
The model gateway. Every model call in the prototype goes through
ModelGateway.complete(). It:

  routes   by task type: cheap model for classification, extraction and
           judging; frontier model for answering, reasoning and the agent
  logs     tokens, latency, cost, model, status per attempt to SQLite
  falls    back to the other model when a call fails or is refused
  budgets  a per-day USD cap, checked before every attempt
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field

from ..paths import GATEWAY_DB, REPO_ROOT
from .pricing import CHEAP_MODEL, FRONTIER_MODEL, cost_usd
from .providers import (AnthropicProvider, OfflineProvider, Provider, ProviderError,
                        ProviderResponse, Usage, credentials_present)
from .store import Store

log = logging.getLogger("ai_platform.gateway")

# The routing rule. One place, one table.
TASK_ROUTES: dict[str, str] = {
    "classify": CHEAP_MODEL,
    "extract": CHEAP_MODEL,
    "judge": CHEAP_MODEL,
    "rerank": CHEAP_MODEL,
    "answer": FRONTIER_MODEL,
    "reason": FRONTIER_MODEL,
    "agent": FRONTIER_MODEL,
}
# Effort is the only depth control on the 5.5 models (thinking is always on).
TASK_EFFORT: dict[str, str] = {
    "classify": "low", "extract": "low", "judge": "low", "rerank": "low",
    "answer": "medium", "reason": "high", "agent": "medium",
}
DEFAULT_DAILY_BUDGET_USD = float(os.environ.get("AI_PLATFORM_DAILY_BUDGET_USD", "5.00"))


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class GatewayResponse:
    text: str
    content: list[dict]
    stop_reason: str
    model: str
    usage: Usage
    cost_usd: float
    latency_ms: int
    is_fallback: bool
    call_ids: list[int] = field(default_factory=list)

    @property
    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class ModelGateway:
    def __init__(self, provider: Provider | None = None, store: Store | None = None,
                 daily_budget_usd: float | None = None, enable_fallback: bool = True):
        self.provider = provider or self.default_provider()
        self.store = store or Store(GATEWAY_DB)
        self.daily_budget_usd = DEFAULT_DAILY_BUDGET_USD if daily_budget_usd is None else daily_budget_usd
        self.enable_fallback = enable_fallback

    # ------------------------------------------------------------------ #
    @staticmethod
    def default_provider() -> Provider:
        if os.environ.get("AI_PLATFORM_OFFLINE", "").lower() in ("1", "true", "yes"):
            return OfflineProvider()
        if credentials_present(REPO_ROOT):
            return AnthropicProvider()
        log.warning("No Anthropic credentials found; using the offline provider. "
                    "Set ANTHROPIC_API_KEY (or put it in the repo .env) for real calls.")
        return OfflineProvider()

    @staticmethod
    def route(task_type: str) -> str:
        try:
            return TASK_ROUTES[task_type]
        except KeyError:
            raise ValueError(f"unknown task_type {task_type!r}; known: {sorted(TASK_ROUTES)}") from None

    @staticmethod
    def other_model(model: str) -> str:
        return FRONTIER_MODEL if model == CHEAP_MODEL else CHEAP_MODEL

    def spend_today(self) -> float:
        return self.store.spend_today(provider=self.provider.name)

    # ------------------------------------------------------------------ #
    def complete(self, task_type: str, messages: list[dict], *, system: str | None = None,
                 tools: list[dict] | None = None, max_tokens: int = 2048,
                 interaction_id: str | None = None) -> GatewayResponse:
        requested = self.route(task_type)
        effort = TASK_EFFORT.get(task_type)
        interaction_id = interaction_id or f"ix_{uuid.uuid4().hex[:10]}"
        call_ids: list[int] = []
        attempts = [requested] + ([self.other_model(requested)] if self.enable_fallback else [])
        last_error: str | None = None

        for i, model in enumerate(attempts):
            is_fallback = i > 0
            spent = self.spend_today()
            if spent >= self.daily_budget_usd:
                call_ids.append(self.store.log_call(
                    interaction_id=interaction_id, task_type=task_type, requested_model=requested,
                    served_model=model, provider=self.provider.name, is_fallback=int(is_fallback),
                    status="budget", error=f"daily budget {self.daily_budget_usd:.2f} USD reached ({spent:.4f})"))
                raise BudgetExceeded(f"daily budget of ${self.daily_budget_usd:.2f} reached (${spent:.4f} spent)")

            t0 = time.perf_counter()
            try:
                resp: ProviderResponse = self.provider.complete(
                    model=model, system=system, messages=messages, tools=tools,
                    max_tokens=max_tokens, effort=effort)
            except ProviderError as e:
                latency = int((time.perf_counter() - t0) * 1000)
                last_error = str(e)
                call_ids.append(self.store.log_call(
                    interaction_id=interaction_id, task_type=task_type, requested_model=requested,
                    served_model=model, provider=self.provider.name, is_fallback=int(is_fallback),
                    status="error", error=last_error, latency_ms=latency))
                log.warning("gateway: %s on %s failed: %s", task_type, model, last_error)
                if not e.retryable_elsewhere:
                    break
                continue

            latency = int((time.perf_counter() - t0) * 1000)
            u = resp.usage
            cost = cost_usd(model, u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens)
            refused = resp.stop_reason == "refusal"
            call_ids.append(self.store.log_call(
                interaction_id=interaction_id, task_type=task_type, requested_model=requested,
                served_model=model, provider=self.provider.name, is_fallback=int(is_fallback),
                status="error" if refused else "ok", error="refusal" if refused else None,
                stop_reason=resp.stop_reason, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens, cache_write_tokens=u.cache_write_tokens,
                latency_ms=latency, cost_usd=cost))
            if refused:
                last_error = "refusal"
                continue
            return GatewayResponse(text=resp.text, content=resp.content, stop_reason=resp.stop_reason,
                                   model=model, usage=u, cost_usd=cost, latency_ms=latency,
                                   is_fallback=is_fallback, call_ids=call_ids)

        raise ProviderError(f"all models failed for task {task_type!r}: {last_error}",
                            retryable_elsewhere=False)
