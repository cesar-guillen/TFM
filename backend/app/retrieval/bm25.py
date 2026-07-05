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

from rank_bm25 import BM25Okapi

from app.core.chroma import get_attack_collection

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
    """Top-k (attack_id, metadata, score) by BM25. Zero-score docs (no term
    overlap at all) are dropped — their relative order is meaningless and
    would pollute rank fusion with noise."""
    index, ids, metadatas = get_bm25_index()
    scores = index.get_scores(tokenize(text))
    ranked = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(ids[i], metadatas[i], float(scores[i])) for i in ranked if scores[i] > 0]
