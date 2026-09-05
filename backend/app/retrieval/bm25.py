"""BM25 keyword index over the ATT&CK KB documents (the keyword retrieval half).

Exact-term matching is what rescues tool names — mimikatz, psexec — which
barely register in embedding space but appear verbatim in technique
descriptions. The index is built from the same Chroma collection the dense half
queries, so both halves score an identical corpus.
"""

import re
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi

from app.core.chroma import get_attack_collection
from app.ingest.sentences import split_sentences

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric runs: keeps tool names ("mimikatz") whole and
    splits ATT&CK ids ("T1003.001" -> ["t1003", "001"]) so id fragments and
    dotted sub-technique ids both match."""
    return _TOKEN_RE.findall(text.lower())


@lru_cache
def get_bm25_index() -> tuple[BM25Okapi, list[str], list[dict]]:
    """(index, ids, metadatas) over the full KB. Built once per process — the
    KB is static for a process's lifetime, and rebuilding it restarts the
    backend anyway."""
    data = get_attack_collection().get(include=["documents", "metadatas"])
    corpus = [tokenize(doc) for doc in data["documents"]]
    return BM25Okapi(corpus), data["ids"], data["metadatas"]


def bm25_search(text: str, top_k: int) -> list[tuple[str, dict, float]]:
    """Top-k (attack_id, metadata, score) by BM25 over `text` as one query.
    Zero-score docs are dropped: their relative order is meaningless and would
    feed rank fusion pure noise."""
    index, ids, metadatas = get_bm25_index()
    scores = index.get_scores(tokenize(text))
    ranked = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(ids[i], metadatas[i], float(scores[i])) for i in ranked if scores[i] > 0]


# Minimum content tokens for a sentence to vote: a stub fragment would
# otherwise crown a meaningless #1 hit.
MIN_SENTENCE_TOKENS = 4


def bm25_search_sentences(text: str, top_k: int) -> list[tuple[str, dict, float]]:
    """Like bm25_search, but each sentence queries separately and results pool
    by per-sentence *rank* (best rank wins, ties by vote count, then id). A
    chunk-long query buries a minority sentence's few rare tokens under the
    chunk's dominant theme; and ranks rather than scores are pooled because
    BM25 scores scale with sentence length, so score-pooling would re-bury
    exactly the sentences this function exists to surface."""
    sentences = [s for s in split_sentences(text) if len(tokenize(s)) >= MIN_SENTENCE_TOKENS]
    if len(sentences) <= 1:
        return bm25_search(text, top_k)
    index, ids, metadatas = get_bm25_index()
    best_rank: dict[int, int] = {}
    votes: dict[int, int] = {}
    best_score: dict[int, float] = {}
    for sentence in sentences:
        scores = index.get_scores(tokenize(sentence))
        top = np.argsort(scores)[::-1][:top_k]
        for rank, i in enumerate(top, start=1):
            if scores[i] <= 0:
                break
            i = int(i)
            if i not in best_rank or rank < best_rank[i]:
                best_rank[i] = rank
            votes[i] = votes.get(i, 0) + 1
            best_score[i] = max(best_score.get(i, 0.0), float(scores[i]))
    ranked = sorted(best_rank, key=lambda i: (best_rank[i], -votes[i], ids[i]))[:top_k]
    return [(ids[i], metadatas[i], best_score[i]) for i in ranked]
