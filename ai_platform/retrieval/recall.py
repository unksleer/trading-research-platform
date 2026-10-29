"""
Recall@k on the 20 hand-labelled questions, for keyword, vector, hybrid and
hybrid+rerank search, k in {1, 3, 5, 8, 10}. Writes
ai_platform/reports/recall_report.json. The hybrid+rerank row reranks 20
candidates with the cheap model (20 calls per run); offline it equals hybrid.

    python -m ai_platform.retrieval.recall [--rebuild] [--embedder model2vec|hash]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..paths import INDEX_DIR, REPORTS_DIR, ensure_dirs
from .embed import get_embedder
from .index import Index
from .search import search

QUESTIONS_FILE = Path(__file__).with_name("labelled_questions.json")
KS = (1, 3, 5, 8, 10)
MODES = ("keyword", "vector", "hybrid", "hybrid+rerank")


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    return json.loads(path.read_text())["questions"]


def is_relevant(hit, relevant: list[dict]) -> bool:
    text = hit.body.lower() + "\n" + hit.heading.lower()
    return any(hit.source.startswith(r["source"]) and r["contains"].lower() in text for r in relevant)


def _search_for(mode: str, gateway):
    if mode == "hybrid+rerank":
        return lambda index, q, k: search(index, q, k, "hybrid", rerank=True, gateway=gateway)
    return lambda index, q, k: search(index, q, k, mode)


def measure(index: Index, questions: list[dict], ks=KS, modes=MODES, gateway=None) -> dict:
    if "hybrid+rerank" in modes and gateway is None:
        from ..gateway import ModelGateway
        gateway = ModelGateway()
    out: dict = {"embedder": index.meta["embedder"], "chunks": len(index.chunks), "questions": len(questions),
                 "recall_at_k": {}, "first_relevant_rank": {}, "misses_at_5": {}}
    for mode in modes:
        fn = _search_for(mode, gateway)
        if mode == "hybrid+rerank":
            from .rerank import stats as rerank_stats
            before = rerank_stats.snapshot()
        hits_by_q = {q["id"]: fn(index, q["question"], max(ks)) for q in questions}
        if mode == "hybrid+rerank":
            out["rerank"] = rerank_stats.since(before)   # calls, parse_fallbacks, error_fallbacks for this run
        out["recall_at_k"][mode] = {}
        for k in ks:
            n = sum(any(is_relevant(h, q["relevant"]) for h in hits_by_q[q["id"]][:k]) for q in questions)
            out["recall_at_k"][mode][f"@{k}"] = round(n / len(questions), 3)
        ranks = {}
        misses = []
        for q in questions:
            r = next((h.rank for h in hits_by_q[q["id"]] if is_relevant(h, q["relevant"])), None)
            ranks[q["id"]] = r
            if r is None or r > 5:
                misses.append({"id": q["id"], "question": q["question"], "first_relevant_rank": r,
                               "top3": [h.citation() for h in hits_by_q[q["id"]][:3]]})
        out["first_relevant_rank"][mode] = ranks
        out["misses_at_5"][mode] = misses
    return out


def render(rep: dict) -> str:
    lines = [f"recall@k  embedder={rep['embedder']}  chunks={rep['chunks']}  questions={rep['questions']}",
             "  mode          " + "".join(f"{'@'+str(k):>7}" for k in KS)]
    for mode, d in rep["recall_at_k"].items():
        lines.append(f"  {mode:<14}" + "".join(f"{d['@'+str(k)]:>7.2f}" for k in KS))
    if "rerank" in rep:
        r = rep["rerank"]
        lines.append(f"  hybrid+rerank: {r['calls']} model calls, {r['parse_fallbacks']} parse fallbacks, "
                     f"{r['error_fallbacks']} error fallbacks (fallback = retriever order kept)")
    for m in rep["misses_at_5"].get("hybrid", []):
        lines.append(f"  hybrid miss@5 {m['id']} rank={m['first_relevant_rank']}: {m['question']}  top3={m['top3']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--embedder", default=None, choices=[None, "model2vec", "hash"])
    ap.add_argument("--out", default=str(REPORTS_DIR / "recall_report.json"))
    a = ap.parse_args(argv)
    ensure_dirs()
    if a.rebuild or a.embedder or not (INDEX_DIR / "meta.json").is_file():
        index = Index.build(get_embedder(a.embedder))
    else:
        index = Index.load_or_build()
    rep = measure(index, load_questions())
    Path(a.out).write_text(json.dumps(rep, indent=2))
    print(render(rep))
    print(f"written {a.out}")


if __name__ == "__main__":
    main()
