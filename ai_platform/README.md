<img src="docs/logo/mark.svg" alt="" width="72" align="left">

# ai_platform — a small, finished gen-AI prototype on the trading research platform

Four runnable pieces and a write-up: [docs/prototype-writeup.md](docs/prototype-writeup.md) (the same text with the C4 and sequence diagrams as a page: [docs/prototype-writeup-page.html](docs/prototype-writeup-page.html)). Every number in it comes from `reports/` or the gateway log.
Read-only against trading state: the only thing it writes outside `ai_platform/data/` is nothing.
Proposals go to `ai_platform/data/proposal_queue.jsonl` and a person confirms them by hand.

```
model gateway   ai_platform/gateway    routing by task type, SQLite call log, fallback, daily budget
retrieval       ai_platform/retrieval  chunk + local embeddings + BM25, hybrid search, recall@k on 20 labelled questions
agent           ai_platform/agent      three typed tools, step budget 10, every tool call logged, proposals to a queue
evaluation      ai_platform/eval       50 real questions, deterministic checks + 3-point judge, one command, one score
web UI          ai_platform/service.py one FastAPI process serving a JSON API and ai_platform/ui/index.html
```

## Setup

```bash
.venv/bin/pip install anthropic model2vec          # already installed in this repo's venv
export ANTHROPIC_API_KEY=sk-ant-...                # or put ANTHROPIC_API_KEY=... in the repo .env
```

Without a key everything still runs through a deterministic **offline provider** (tests use it; its rows are
logged as `provider=offline` and excluded from every cost figure). Force it with `AI_PLATFORM_OFFLINE=1`.

Per-day budget: `AI_PLATFORM_DAILY_BUDGET_USD` (default 5.00). Data dir: `AI_PLATFORM_DATA_DIR` (default `ai_platform/data`).
When run from a git worktree the ledgers are read from the main checkout (`AI_PLATFORM_REPO_ROOT` overrides).

## Commands

All from the repo root with `.venv/bin/python`.

```bash
# 1. gateway: cost per interaction from the log (real calls only by default)
python -m ai_platform.gateway.report [--provider anthropic|offline|all] [--day 2026-10-14]

# 2. retrieval
python -m ai_platform.retrieval.index                      # build the index (32 docs, ~234 chunks)
python -m ai_platform.retrieval.search "why was crypto retired" -k 5 [--mode hybrid|keyword|vector]
python -m ai_platform.retrieval.recall                      # recall@{1,3,5,8,10} x {keyword,vector,hybrid,hybrid+rerank} -> reports/recall_report.json

# 3. agent
python -m ai_platform.agent.agent "What is the stock win rate since 2026-09-04?"
python -m ai_platform.agent.agent "Propose tightening the stock stop loss to 4%."
python -m ai_platform.agent.proposals list | confirm <id> | reject <id>

# 4. evaluation: one command, one score -> reports/eval_report.json
python -m ai_platform.eval.run_eval [--kind rag|agent] [--ids q01,a06] [--no-judge]

# 5. web UI: one process, JSON API + one static page on http://127.0.0.1:8765/
python -m ai_platform.service [--host 0.0.0.0] [--port 8765]

# tests (offline, ~5 s)
python -m pytest ai_platform/tests -q
```

## Routing rule

| task type | model | effort | used by |
|---|---|---|---|
| classify, extract, judge, rerank | `claude-haiku-5-5` | low | the eval judge; the optional retrieval reranker (`AI_PLATFORM_RERANK=1`, default off) |
| answer, reason, agent | `claude-opus-5-5` | medium (reason: high) | RAG answers, the agent loop |

On any provider error or a `refusal` stop the gateway retries once on the other model and logs both rows.
Budget is checked before every attempt against today's spend for the active provider.

## What the agent can and cannot do

- `read_ledger`, `summarise_strategy_performance`: read the paper-trade CSVs; statistics are computed in code.
- `propose_parameter_change`: allow-listed parameters only, range-checked, appended to the queue with
  `status=pending_confirmation`. It cannot name `DRY_RUN`, `ALPACA_PAPER` or the kill switch (the schema rejects them).
- The eval fingerprints `.env`, `experiments/*.json` and `state_*.json` before and after every question and reports
  `live_state_untouched`.

## The web UI

```bash
.venv/bin/python -m ai_platform.service            # binds 127.0.0.1:8765; --host 0.0.0.0 for a container
```

One process (FastAPI + uvicorn), one static page (`ai_platform/ui/index.html`, plain HTML/CSS/JS, no build
step), no database beyond the existing SQLite log. The page has a question box with an agent/rag toggle, the
answer with its sources, the tool calls (inputs, ok/error, duration), the receipt for that interaction
(model, tokens, latency, cost per call), today's spend against the daily budget in the header, the proposal
queue with Confirm/Reject, and an Eval panel with a Run button, progress and the last report.

Every model call still goes through `ModelGateway`; the service adds nothing of its own except a worker
thread for the eval. The routing table and the budget live in the gateway and are only exposed here.

| endpoint | what |
|---|---|
| `GET /` | the page |
| `POST /api/ask` `{question, mode: agent\|rag, k}` | answer, sources, tool_calls, interaction_id, cost_usd, latency_ms, models |
| `GET /api/receipt/{interaction_id}` | the `calls` and `tool_calls` rows for that interaction, with totals |
| `GET /api/report[?provider=anthropic\|offline\|all&day=YYYY-MM-DD]` | `report.summarise()` plus today's spend, the budget and the routing table |
| `GET /api/proposals`, `POST /api/proposals/{id}/decide` `{status: confirmed\|rejected, note}` | the queue; a decision changes the queue file and nothing else |
| `POST /api/eval/run` `{ids?, kind?, judge, k}` → 202, `GET /api/eval/status` | `run_eval.run` in a background thread (a full judged run is ~6 min and ~$1.50); one run at a time |
| `GET /healthz`, `GET /readyz` | process up; SQLite writable, index loadable, credentials present (503 otherwise) |

A UI eval run writes `ai_platform/data/eval_report_last.json`; the committed `reports/eval_report.json`
(the measured run the write-up cites) is left alone, and is what the panel shows until a UI run exists.
The API key never appears in a response: no endpoint returns configuration, and the JSON response class
scrubs the credential value from every body as a last line of defence (`test_service.py` checks both).
