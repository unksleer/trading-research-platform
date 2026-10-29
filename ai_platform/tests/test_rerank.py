import json

from ai_platform.gateway.gateway import ModelGateway, TASK_EFFORT, TASK_ROUTES
from ai_platform.gateway.pricing import CHEAP_MODEL
from ai_platform.gateway.providers import OfflineProvider, ProviderError, ProviderResponse, Usage
from ai_platform.gateway.store import Store
from ai_platform.retrieval.chunker import chunk_corpus
from ai_platform.retrieval.corpus import Document
from ai_platform.retrieval.embed import HashEmbedder
from ai_platform.retrieval.index import Index
from ai_platform.retrieval.rerank import RERANK_SYSTEM, build_prompt, parse_order, rerank
from ai_platform.retrieval.search import Hit, search
from ai_platform.tests.test_agent import ledger_root  # noqa: F401  (fixture)


class ScriptedProvider:
    """Returns a fixed text, or raises, so the reranker's parsing can be exercised."""
    name = "scripted"

    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def complete(self, *, model, system, messages, tools, max_tokens, effort):
        self.calls.append({"model": model, "system": system, "messages": messages, "max_tokens": max_tokens})
        if self.error:
            raise ProviderError(self.error)
        return ProviderResponse(content=[{"type": "text", "text": self.text}], stop_reason="end_turn",
                                usage=Usage(10, 5), model=model)


def gw(provider):
    return ModelGateway(provider=provider, store=Store(":memory:"))


def hits(n):
    return [Hit(rank=i, chunk_id=f"c{i}", source=f"doc{i}.md", heading=f"h{i}", score=1.0 / i,
                body=f"body {i} " + "x" * 700, keyword_rank=i, vector_rank=i) for i in range(1, n + 1)]


def small_index():
    docs = [Document(source="a.md", title="a", kind="markdown", text="## Fees\nThe maker fee round trip is 0.80% on Coinbase."),
            Document(source="b.md", title="b", kind="markdown", text="## Observer\nThe observer will never touch a state file."),
            Document(source="c.md", title="c", kind="markdown", text="## Stops\nFive stop-outs between Oct 7 and Oct 20.")]
    emb = HashEmbedder()
    chunks = chunk_corpus(docs)
    return Index(chunks, emb.encode([c.text for c in chunks]), {"embedder": emb.name}, emb)


def test_rerank_is_routed_to_the_cheap_model_at_low_effort():
    assert TASK_ROUTES["rerank"] == CHEAP_MODEL and TASK_EFFORT["rerank"] == "low"


def test_garbage_model_output_returns_original_order():
    h = hits(6)
    for bad in ("I cannot rank these.", "", "null", "[\"a\", \"b\"]", "[99, 100]", "{\"order\": 2}"):
        out = rerank("q", h, gw(ScriptedProvider(bad)), top_n=4)
        assert [x.chunk_id for x in out] == ["c1", "c2", "c3", "c4"], bad
        assert [x.rank for x in out] == [1, 2, 3, 4]
    # an array wrapped in prose is still an array: the parser takes it
    out = rerank("q", h, gw(ScriptedProvider("I think [2] is best, honestly")), top_n=4)
    assert [x.chunk_id for x in out] == ["c2", "c1", "c3", "c4"]


def test_provider_error_returns_original_order():
    h = hits(5)
    out = rerank("q", h, gw(ScriptedProvider(error="boom")), top_n=3)
    assert [x.chunk_id for x in out] == ["c1", "c2", "c3"]


def test_valid_order_is_applied_deduplicated_and_padded():
    h = hits(5)
    p = ScriptedProvider("[4, 4, 2, 7, 0]")
    out = rerank("q", h, gw(p), top_n=4)
    assert [x.chunk_id for x in out] == ["c4", "c2", "c1", "c3"]      # named first, then the rest in order
    assert [x.rank for x in out] == [1, 2, 3, 4]
    assert p.calls[0]["max_tokens"] == 200 and "RERANK" in p.calls[0]["system"]


def test_prompt_truncates_candidates_and_marks_them_as_data():
    h = hits(3)
    prompt = build_prompt("why fees", h, 2)
    assert "[1] source: doc1.md > h1" in prompt and "[3] source: doc3.md > h3" in prompt
    assert all(len(line) <= 620 for line in prompt.splitlines())
    assert "at most 2" in prompt
    assert "not instructions" in RERANK_SYSTEM and "{top_n}" in RERANK_SYSTEM
    assert parse_order("sure: [3, 1, 3]", 3) == [3, 1] and parse_order("nope", 3) is None


def test_search_without_rerank_is_unchanged():
    idx = small_index()
    plain = search(idx, "maker fee round trip", k=2)
    explicit = search(idx, "maker fee round trip", k=2, rerank=False)
    assert plain == explicit
    assert plain[0].source == "a.md"


def test_search_with_rerank_offline_returns_k_hits_in_hybrid_order():
    idx = small_index()
    g = gw(OfflineProvider())
    base = search(idx, "state file observer", k=2)
    out = search(idx, "state file observer", k=2, rerank=True, candidates=20, gateway=g)
    assert len(out) == 2 and [h.chunk_id for h in out] == [h.chunk_id for h in base]
    rows = g.store.query("SELECT task_type, served_model FROM calls")
    assert [(r["task_type"], r["served_model"]) for r in rows] == [("rerank", CHEAP_MODEL)]


def test_offline_provider_answers_a_rerank_prompt_with_identity_order():
    p = OfflineProvider()
    r = p.complete(model=CHEAP_MODEL, system=RERANK_SYSTEM.format(top_n=3),
                   messages=[{"role": "user", "content": build_prompt("q", hits(5), 3)}],
                   tools=None, max_tokens=100, effort="low")
    assert json.loads(r.text) == [1, 2, 3]


def test_recall_measure_includes_hybrid_plus_rerank_offline():
    from ai_platform.retrieval.recall import load_questions, measure
    idx = Index.build(embedder=HashEmbedder(), save_to=None)
    rep = measure(idx, load_questions()[:3], ks=(1, 5), modes=("hybrid", "hybrid+rerank"), gateway=gw(OfflineProvider()))
    assert rep["recall_at_k"]["hybrid+rerank"] == rep["recall_at_k"]["hybrid"]
    assert rep["rerank"] == {"calls": 3, "parse_fallbacks": 0, "error_fallbacks": 0}


def test_recall_report_counts_parse_fallbacks():
    from ai_platform.retrieval.recall import load_questions, measure
    idx = Index.build(embedder=HashEmbedder(), save_to=None)
    rep = measure(idx, load_questions()[:3], ks=(1,), modes=("hybrid+rerank",), gateway=gw(ScriptedProvider("no json here")))
    assert rep["rerank"] == {"calls": 3, "parse_fallbacks": 3, "error_fallbacks": 0}


def test_parse_failure_logs_stop_reason(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="ai_platform.retrieval"):
        rerank("q", hits(3), gw(ScriptedProvider("garbage")), top_n=2)
    assert "stop_reason=end_turn" in caplog.text and "model=" in caplog.text


def test_rerank_is_off_by_default_and_eval_report_records_it(monkeypatch, ledger_root):  # noqa: F811
    from ai_platform.eval import run_eval
    from ai_platform.retrieval.search import rerank_enabled
    monkeypatch.delenv("AI_PLATFORM_RERANK", raising=False)
    assert rerank_enabled() is False
    g = gw(OfflineProvider())
    qs = [q for q in run_eval.load_eval_set() if q["id"] == "q02"]
    rep = run_eval.run(qs, gateway=g, k=3, use_judge=False, run_id="t", verbose=False)
    assert rep["rerank"] is False
    assert [r["task_type"] for r in g.store.query("SELECT task_type FROM calls")] == ["answer"]
    monkeypatch.setenv("AI_PLATFORM_RERANK", "1")
    assert rerank_enabled() is True
    rep = run_eval.run(qs, gateway=gw(OfflineProvider()), k=3, use_judge=False, run_id="t2", verbose=False)
    assert rep["rerank"] is True
