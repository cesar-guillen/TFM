"""BM25 keyword index over the ATT&CK KB documents (pipeline stage 4, keyword half).

Exact-term matching is the mitigation for the "hard-to-categorize keywords"
problem: tool names like mimikatz/psexec/linpeas barely register in embedding
space but appear verbatim in technique descriptions, so a keyword hit on them
is a strong signal. The index is built lazily from the same Chroma collection
the dense half queries (name + description documents), so both halves score
the exact same corpus.
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
    """(index, ids, metadatas) over the full KB. Built once per process
    (~700 docs, tens of ms); the KB is static for a process's lifetime, and a
    KB rebuild (build_kb --refresh) ships with a backend restart anyway."""
    data = get_attack_collection().get(include=["documents", "metadatas"])
    corpus = [tokenize(doc) for doc in data["documents"]]
    return BM25Okapi(corpus), data["ids"], data["metadatas"]


def bm25_search(text: str, top_k: int) -> list[tuple[str, dict, float]]:
    """Top-k (attack_id, metadata, score) by BM25, `text` as one query. Zero-
    score docs (no term overlap at all) are dropped — their relative order is
    meaningless and would pollute rank fusion with noise."""
    index, ids, metadatas = get_bm25_index()
    scores = index.get_scores(tokenize(text))
    ranked = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(ids[i], metadatas[i], float(scores[i])) for i in ranked if scores[i] > 0]


# A sentence must have this many content tokens to vote in the pooled search —
# stub fragments would otherwise crown their (meaningless) #1 hit.
MIN_SENTENCE_TOKENS = 4


def bm25_search_sentences(text: str, top_k: int) -> list[tuple[str, dict, float]]:
    """Like bm25_search, but each sentence of `text` queries separately and
    results pool by *per-sentence rank* (best rank wins; ties broken by how
    many sentences voted for the technique, then id). A chunk-long query
    buries a minority sentence's 1-3 rare tokens ("SSH, RDP, and WinRM") under
    dozens of tokens matching the chunk's dominant theme. Ranks, not raw
    scores, are pooled because BM25 scores scale with sentence length — a long
    Kerberos sentence scores 50-77 while the SSH sentence's #3-ranked hit
    scores 40, so score-pooling silently re-buries exactly the minority
    sentences this function exists to surface (measured on chunk 13 of the
    Meridian Grove report)."""
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
