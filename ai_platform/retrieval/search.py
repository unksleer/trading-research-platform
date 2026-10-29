"""
Hybrid search: BM25 keyword ranks and cosine vector ranks fused with
reciprocal rank fusion. Returns top-k chunks with their sources.

    python -m ai_platform.retrieval.search "why was crypto retired" [-k 5] [--mode hybrid|keyword|vector] [--rerank]

Optional reranking (rerank=True, or AI_PLATFORM_RERANK=1): retrieve
`candidates` chunks as usual, let a cheap model order them, return the top k.
With rerank=False nothing here changes.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import numpy as np

from .index import Index

RRF_K = 60


@dataclass
class Hit:
    rank: int
    chunk_id: str
    source: str
    heading: str
    score: float
    body: str
    keyword_rank: int | None
    vector_rank: int | None

    def citation(self) -> str:
        return f"{self.source}" + (f" > {self.heading}" if self.heading else "")


def _ranks(scores: np.ndarray) -> dict[int, int]:
    order = np.argsort(-scores, kind="stable")
    return {int(i): r + 1 for r, i in enumerate(order) if scores[i] > 0 or r == 0}


def rerank_enabled() -> bool:
    return os.environ.get("AI_PLATFORM_RERANK", "").lower() in ("1", "true", "yes")


def search(index: Index, query: str, k: int = 5, mode: str = "hybrid", *,
           rerank: bool = False, candidates: int = 20, gateway=None) -> list[Hit]:
    if rerank:
        from .rerank import rerank as _rerank
        pool = search(index, query, k=max(k, candidates), mode=mode)
        if gateway is None:
            from ..gateway import ModelGateway
            gateway = ModelGateway()
        return _rerank(query, pool, gateway, top_n=k)
    n = len(index.chunks)
    if n == 0:
        return []
    kw_scores = index.bm25.scores(query)
    q = index.embedder.encode([query])[0]
    vec_scores = index.embeddings @ q
    kw_ranks = {int(i): r + 1 for r, i in enumerate(np.argsort(-kw_scores, kind="stable")) if kw_scores[i] > 0}
    vec_ranks = {int(i): r + 1 for r, i in enumerate(np.argsort(-vec_scores, kind="stable"))}

    fused = np.zeros(n, dtype=np.float64)
    if mode in ("hybrid", "keyword"):
        for i, r in kw_ranks.items():
            fused[i] += 1.0 / (RRF_K + r)
    if mode in ("hybrid", "vector"):
        for i, r in vec_ranks.items():
            fused[i] += 1.0 / (RRF_K + r)
    if mode == "keyword":
        fused = kw_scores.astype(np.float64)
    elif mode == "vector":
        fused = vec_scores.astype(np.float64)

    order = [int(i) for i in np.argsort(-fused, kind="stable")[:k]]
    hits = []
    for r, i in enumerate(order, 1):
        if fused[i] <= 0 and mode == "keyword":
            break
        c = index.chunks[i]
        hits.append(Hit(rank=r, chunk_id=c.chunk_id, source=c.source, heading=c.heading, score=float(fused[i]),
                        body=c.body, keyword_rank=kw_ranks.get(i), vector_rank=vec_ranks.get(i)))
    return hits


CHARS_PER_HIT = 1800   # a chunk is at most ~1,400 chars plus its source line


def format_context(hits: list[Hit], max_chars: int | None = None) -> str:
    """Numbered context block for a prompt; retrieved text is untrusted input.
    The window grows with k (1,800 chars per hit, floor 9,000) so that asking for
    eight chunks does not silently deliver six."""
    if max_chars is None:
        max_chars = max(9000, CHARS_PER_HIT * len(hits))
    parts, used = [], 0
    for h in hits:
        block = f"[{h.rank}] source: {h.citation()}\n{h.body}"
        if used + len(block) > max_chars:
            break
        parts.append(block); used += len(block)
    return "<context>\n" + "\n\n".join(parts) + "\n</context>"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "vector"])
    ap.add_argument("--rerank", action="store_true", help="rerank 20 candidates with the cheap model (also AI_PLATFORM_RERANK=1)")
    a = ap.parse_args(argv)
    idx = Index.load_or_build()
    for h in search(idx, a.query, a.k, a.mode, rerank=a.rerank or rerank_enabled()):
        print(f"#{h.rank}  {h.citation()}   (rrf {h.score:.4f}, kw rank {h.keyword_rank}, vec rank {h.vector_rank})")
        print("    " + h.body[:300].replace("\n", " ") + ("..." if len(h.body) > 300 else ""))


if __name__ == "__main__":
    main()
