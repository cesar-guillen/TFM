from dataclasses import dataclass

from app.attack.embeddings import embed_text
from app.core.chroma import get_attack_collection, get_report_chunks_collection
from app.retrieval.bm25 import bm25_search

# Candidates each half contributes before fusion. Wider than any final top_k so
# a technique ranked ~20th by one half can still win overall when the other
# half also ranks it (the typical hybrid case: a keyword hit on a tool name
# lifting a mid-pack dense candidate).
CANDIDATE_POOL = 30
# Standard RRF damping constant (Cormack et al.): rank contributions are
# 1/(60+rank), which keeps a #1 rank from steamrolling everything else.
RRF_K = 60


@dataclass
class TechniqueMatch:
    attack_id: str
    name: str
    tactics: list[str]
    url: str
    is_subtechnique: bool
    score: float  # RRF-fused rank score (higher = better); comparable across queries
    distance: float | None = None  # cosine distance from the dense half; None if only BM25 found it


def _fuse(
    dense: list[tuple[str, dict, float]],
    keyword: list[tuple[str, dict, float]],
    top_k: int,
) -> list[TechniqueMatch]:
    """Reciprocal Rank Fusion of the two candidate lists. Rank-based rather
    than score-based on purpose: cosine distances and BM25 scores live on
    incomparable scales, and RRF sidesteps normalizing them."""
    fused: dict[str, dict] = {}
    for half, results in (("dense", dense), ("keyword", keyword)):
        for rank, (attack_id, meta, value) in enumerate(results, start=1):
            entry = fused.setdefault(attack_id, {"meta": meta, "score": 0.0, "distance": None})
            entry["score"] += 1.0 / (RRF_K + rank)
            if half == "dense":
                entry["distance"] = value

    ranked = sorted(fused.items(), key=lambda kv: kv[1]["score"], reverse=True)[:top_k]
    return [
        TechniqueMatch(
            attack_id=attack_id,
            name=entry["meta"]["name"],
            tactics=entry["meta"]["tactics"].split(",") if entry["meta"]["tactics"] else [],
            url=entry["meta"]["url"],
            is_subtechnique=entry["meta"]["is_subtechnique"],
            score=entry["score"],
            distance=entry["distance"],
        )
        for attack_id, entry in ranked
    ]


def _dense_candidates(result: dict, i: int) -> list[tuple[str, dict, float]]:
    """(attack_id, metadata, cosine_distance) for the i-th query of a
    (possibly batched) Chroma query result, best-first."""
    return list(zip(result["ids"][i], result["metadatas"][i], result["distances"][i]))


def search_techniques(text: str, top_k: int = 8) -> list[TechniqueMatch]:
    """Hybrid retrieval against the ATT&CK knowledge base: dense (embed `text`,
    nearest neighbors by cosine) and BM25 keyword candidates, combined with
    reciprocal rank fusion. A dedicated reranker model over the fused list is
    still open (see CLAUDE.md); fusion is the whole of stage 4 for now.
    """
    embedding = embed_text(text)
    result = get_attack_collection().query(query_embeddings=[embedding], n_results=CANDIDATE_POOL)
    return _fuse(_dense_candidates(result, 0), bm25_search(text, CANDIDATE_POOL), top_k)


def search_techniques_for_report(report_id: str, top_k_per_chunk: int = 5) -> dict[str, list[TechniqueMatch]]:
    """Run hybrid retrieval for every indexed chunk of one report, keyed by
    chunk id (`"<report_id>:<order>"`). The dense half reuses the chunk
    embeddings computed at index time (stored in Chroma) as the query vectors
    and resolves all chunks in a single batched HNSW query; the BM25 half
    scores each chunk's stored text against the in-process index. Zero Ollama
    calls either way. This is the shape the LLM mapping stage (6) consumes.
    """
    chunks = get_report_chunks_collection().get(
        where={"report_id": report_id}, include=["embeddings", "documents"]
    )
    chunk_ids = chunks["ids"]
    if len(chunk_ids) == 0:
        return {}

    result = get_attack_collection().query(
        query_embeddings=chunks["embeddings"], n_results=CANDIDATE_POOL
    )
    return {
        chunk_id: _fuse(
            _dense_candidates(result, i),
            bm25_search(chunks["documents"][i], CANDIDATE_POOL),
            top_k_per_chunk,
        )
        for i, chunk_id in enumerate(chunk_ids)
    }
