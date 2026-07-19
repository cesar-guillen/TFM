import re
from dataclasses import dataclass
from functools import lru_cache

from app.attack.embeddings import embed_text, embed_texts
from app.core.chroma import (
    get_attack_collection,
    get_attack_examples_collection,
    get_report_chunks_collection,
    get_report_windows_collection,
)
from app.core.config import settings
from app.ingest.sentences import build_windows
from app.retrieval.bm25 import bm25_search, bm25_search_sentences

# Candidates each half contributes before fusion. Wider than any final top_k so
# a technique ranked ~20th by one half can still win overall when another
# half also ranks it (the typical hybrid case: a keyword hit on a tool name
# lifting a mid-pack dense candidate).
CANDIDATE_POOL = 30
# Standard RRF damping constant (Cormack et al.): rank contributions are
# 1/(60+rank), which keeps a #1 rank from steamrolling everything else.
RRF_K = 60
# Each half's strongest candidates are guaranteed a seat in the fused top_k.
# Plain RRF lets weak two-half agreement outrank strong single-half signal
# (dense #3 alone scores 1/63 ≈ 0.016 while dense #15 + BM25 #20 agreement
# scores ≈ 0.026) — measured costing T1014 Rootkit (dense #3, fused #9) and
# T1490 (BM25 #8) their seats on the Meridian Grove report.
RESERVE_PER_HALF = 2

# ATT&CK technique ids cited literally in report text (CISA advisories cite
# inline: "... traffic encryption features. [T1573]"). Neither retrieval half
# can surface these — KB documents carry names + descriptions, not ids — so
# they are injected as candidates directly (see _prepend_explicit_ids).
ATTACK_ID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")

# Remote-access mechanisms that ARE a technique's name: when the bare token
# appears in a chunk, the matching sub-technique is injected as a candidate
# alongside explicitly-cited ids. Measured motivation: "alternating between
# SSH, RDP, and WinRM sessions" produced a menu that was 100% Kerberos-family
# — the protocol sentence loses every retrieval half's slot competition to the
# chunk's dominant topic (rank-pooling tie-breaks favor the majority cluster),
# leaving textbook lateral movement unmappable. Deliberately tiny and curated:
# each token names exactly one mechanism with one canonical sub-technique, so
# injection is near-zero-risk (the verdict stage still judges the evidence).
MECHANISM_ALIASES = {
    "ssh": "T1021.004",
    "rdp": "T1021.001",
    "winrm": "T1021.006",
    "vnc": "T1021.005",
}
_MECHANISM_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Sorts above any fused RRF score (three #1 ranks ≈ 3/(60+1) ≈ 0.049), so
# chunks with citations also lead the mapper's strongest-first submission.
EXPLICIT_ID_SCORE = 1.0


@dataclass
class TechniqueMatch:
    attack_id: str
    name: str
    tactics: list[str]
    url: str
    is_subtechnique: bool
    score: float  # RRF-fused rank score (higher = better); comparable across queries
    distance: float | None = None  # best cosine distance from any dense half; None if only BM25 found it


def _match_from_meta(
    attack_id: str, meta: dict, score: float, distance: float | None
) -> TechniqueMatch:
    return TechniqueMatch(
        attack_id=attack_id,
        name=meta["name"],
        tactics=meta["tactics"].split(",") if meta["tactics"] else [],
        url=meta["url"],
        is_subtechnique=meta["is_subtechnique"],
        score=score,
        distance=distance,
    )


# One retrieval half's candidates, best-first: (attack_id, metadata, cosine
# distance) — distance is None for keyword (BM25) halves.
Half = list[tuple[str, dict, float | None]]


def _fuse(
    halves: list[Half], top_k: int, window_seats: dict[str, int] | None = None
) -> list[TechniqueMatch]:
    """Reciprocal Rank Fusion across any number of halves. Rank-based rather
    than score-based on purpose: cosine distances and BM25 scores live on
    incomparable scales, and RRF sidesteps normalizing them.

    Two guards against RRF's known pathologies:
    - deterministic tie-break by attack_id — the old dict-insertion tie-break
      silently favored whichever half was processed first (measured costing
      T1566.001, BM25 #2 for its chunk, a coin-flip seat);
    - RESERVE_PER_HALF seats per half, so a candidate one half is confident
      about survives the cut even when the other halves don't corroborate.

    `window_seats` (id -> best per-window rank, from _pooled_window_candidates)
    are seated with *absolute priority*, ahead of fused ordering — a quota, not
    a reservation. A minority sentence's #1 has a fused score of one lonely
    half-contribution, so any selection by fused score re-buries it under
    multi-half consensus (measured: with seats merely added to the reserved
    set, T1059.001 — window #1 for its sentence — still lost its seat to the
    chunk's phishing consensus cluster). Deduped across windows the quota is
    small in practice (windows about the same topic share a #1), and it is
    capped at half of top_k — table chunks give every row its own window, and
    an uncapped quota there filled all the seats and evicted strong fused
    candidates (measured costing T1053.005 its cand#4 seat in the timeline
    chunk). Over the cap, seats go by per-window rank tier, then fused score.
    """
    fused: dict[str, dict] = {}
    for results in halves:
        for rank, (attack_id, meta, distance) in enumerate(results, start=1):
            entry = fused.setdefault(attack_id, {"meta": meta, "score": 0.0, "distance": None})
            entry["score"] += 1.0 / (RRF_K + rank)
            if distance is not None and (entry["distance"] is None or distance < entry["distance"]):
                entry["distance"] = distance

    ranking = sorted(fused, key=lambda a: (-fused[a]["score"], a))
    seated = sorted(
        (a for a in (window_seats or {}) if a in fused),
        key=lambda a: (window_seats[a], -fused[a]["score"], a),
    )[: top_k // 2]
    selected = list(seated)
    reserved = {a for results in halves for a, _, _ in results[:RESERVE_PER_HALF]}
    for pool in (reserved, None):
        for attack_id in ranking:
            if len(selected) >= top_k:
                break
            if attack_id not in selected and (pool is None or attack_id in pool):
                selected.append(attack_id)
    selected.sort(key=lambda a: (-fused[a]["score"], a))
    return [
        _match_from_meta(a, fused[a]["meta"], fused[a]["score"], fused[a]["distance"])
        for a in selected
    ]


def _prepend_explicit_ids(
    text: str, fused: list[TechniqueMatch], top_k: int
) -> list[TechniqueMatch]:
    """Put techniques the text cites by id — or names by mechanism token (see
    MECHANISM_ALIASES) — ahead of the retrieval candidates, keeping the total
    at top_k so the mapper's prompt budget doesn't grow. Cited ids missing
    from the KB (deprecated/revoked, typos) just don't come back from the
    collection and are dropped silently."""
    if not settings.explicit_ids:
        return fused
    cited = sorted({m.group(0).upper() for m in ATTACK_ID_RE.finditer(text)})
    tokens = set(_MECHANISM_TOKEN_RE.findall(text.lower()))
    cited += sorted(
        {tid for token, tid in MECHANISM_ALIASES.items() if token in tokens} - set(cited)
    )
    if not cited:
        return fused
    kb = get_attack_collection().get(ids=cited, include=["metadatas"])
    explicit = [
        _match_from_meta(attack_id, meta, EXPLICIT_ID_SCORE, None)
        for attack_id, meta in zip(kb["ids"], kb["metadatas"])
    ][:top_k]
    if not explicit:
        return fused
    seen = {m.attack_id for m in explicit}
    return (explicit + [m for m in fused if m.attack_id not in seen])[:top_k]


def _dense_candidates(result: dict, i: int) -> Half:
    """(attack_id, metadata, cosine_distance) for the i-th query of a
    (possibly batched) Chroma query result, best-first."""
    return list(zip(result["ids"][i], result["metadatas"][i], result["distances"][i]))


@lru_cache(maxsize=1)
def _examples_count() -> int:
    try:
        return get_attack_examples_collection().count()
    except Exception:
        return 0


def _use_examples() -> bool:
    """Examples merge in only when enabled AND the collection was built —
    a checkout that never ran app.attack.build_examples degrades gracefully
    to KB-only dense retrieval."""
    return settings.example_retrieval and _examples_count() > 0


def _example_candidates(result: dict, i: int) -> Half:
    """Like _dense_candidates, but for the procedure-examples collection,
    whose record ids are "T1489:ex3" — the technique id lives in metadata."""
    return [
        (meta["attack_id"], meta, distance)
        for meta, distance in zip(result["metadatas"][i], result["distances"][i])
    ]


def _merge_by_distance(*hit_lists: Half) -> Half:
    """Merge candidate lists produced by the SAME query vector against
    different collections (KB documents, procedure examples). Distances are
    directly comparable there — same query, same embedding space, cosine to
    different documents — so unlike cross-half fusion this is a plain
    best-distance dedupe per technique, not rank arithmetic."""
    best: dict[str, tuple[str, dict, float | None]] = {}
    for hits in hit_lists:
        for attack_id, meta, distance in hits:
            current = best.get(attack_id)
            if current is None or (distance or 0.0) < (current[2] or 0.0):
                best[attack_id] = (attack_id, meta, distance)
    return sorted(best.values(), key=lambda hit: (hit[2], hit[0]))[:CANDIDATE_POOL]


def _pooled_window_candidates(per_window: list[Half]) -> tuple[Half, dict[str, int]]:
    """Merge one chunk's per-window candidate lists into a single half, pooled
    by *per-window rank* (best rank wins; ties broken by vote count, then id).
    This is what gives a minority sentence's technique its own undiluted dense
    shot — the chunk-level embedding averages it away. Ranks rather than raw
    distances, because distances aren't comparable across windows: a window
    whose #1 hit sits at 0.31 (T1021.001 for the SSH/RDP/WinRM sentence) is a
    stronger signal than another window's #6 at 0.28 — distance-pooling let
    the Kerberos windows' tight cluster re-bury the minority window's find.

    Also returns the seat quota for _fuse: each window's top
    `settings.window_seat_depth` ids mapped to their best per-window rank.
    Pooling alone undoes the minority-sentence rescue at the last step — every
    window's #1 ties at pooled rank 1, so a minority window's find sorts
    behind the majority cluster's tie-break votes, misses the pooled half's
    RESERVE_PER_HALF prefix, and RRF buries it uncorroborated (measured:
    T1059.001 ranked #1 for its PowerShell window yet never surfaced as a
    candidate)."""
    best_rank: dict[str, int] = {}
    votes: dict[str, int] = {}
    best_dist: dict[str, float] = {}
    metas: dict[str, dict] = {}
    seats: dict[str, int] = {}
    for hits in per_window:
        for rank, (attack_id, meta, distance) in enumerate(hits, start=1):
            if rank <= settings.window_seat_depth:
                seats[attack_id] = min(rank, seats.get(attack_id, rank))
            if attack_id not in best_rank or rank < best_rank[attack_id]:
                best_rank[attack_id] = rank
            votes[attack_id] = votes.get(attack_id, 0) + 1
            if attack_id not in best_dist or distance < best_dist[attack_id]:
                best_dist[attack_id] = distance
            metas[attack_id] = meta
    ranked = sorted(best_rank, key=lambda a: (best_rank[a], -votes[a], a))[:CANDIDATE_POOL]
    return [(a, metas[a], best_dist[a]) for a in ranked], seats


def search_techniques(text: str, top_k: int = 8) -> list[TechniqueMatch]:
    """Hybrid retrieval against the ATT&CK knowledge base, fusing up to three
    halves with reciprocal rank fusion: dense over the whole text, dense over
    its sentence windows (when the text spans several), and per-sentence
    rank-pooled BM25. A dedicated reranker model over the fused list is still
    open (see CLAUDE.md)."""
    kb = get_attack_collection()
    examples = get_attack_examples_collection() if _use_examples() else None
    halves: list[Half] = []
    window_seats: dict[str, int] = {}

    def dense_hits(embeddings: list) -> list[Half]:
        """One merged (KB ∪ examples) candidate list per query embedding."""
        kb_result = kb.query(query_embeddings=embeddings, n_results=CANDIDATE_POOL)
        if examples is None:
            return [_dense_candidates(kb_result, i) for i in range(len(embeddings))]
        ex_result = examples.query(query_embeddings=embeddings, n_results=CANDIDATE_POOL)
        return [
            _merge_by_distance(_dense_candidates(kb_result, i), _example_candidates(ex_result, i))
            for i in range(len(embeddings))
        ]

    embedding = embed_text(text)
    halves.append(dense_hits([embedding])[0])

    if settings.sentence_retrieval:
        windows = build_windows(text)
        if len(windows) > 1:
            window_half, window_seats = _pooled_window_candidates(
                dense_hits(embed_texts(windows))
            )
            halves.append(window_half)
        halves.append(bm25_search_sentences(text, CANDIDATE_POOL))
    else:
        halves.append(bm25_search(text, CANDIDATE_POOL))

    return _prepend_explicit_ids(text, _fuse(halves, top_k, window_seats), top_k)


def search_techniques_for_report(report_id: str, top_k_per_chunk: int = 5) -> dict[str, list[TechniqueMatch]]:
    """Run hybrid retrieval for every indexed chunk of one report, keyed by
    chunk id (`"<report_id>:<order>"`). All dense queries reuse embeddings
    computed at index time (chunk embeddings from report_chunks, sentence-
    window embeddings from report_windows) and resolve in two batched HNSW
    queries; the BM25 half scores each chunk's sentences against the
    in-process index. Zero Ollama calls either way. This is the shape the LLM
    mapping stage (6) consumes.

    Reports indexed before sentence windows existed simply have no entries in
    report_windows — the window half is absent and fusion degrades gracefully
    to the remaining halves."""
    chunks = get_report_chunks_collection().get(
        where={"report_id": report_id}, include=["embeddings", "documents", "metadatas"]
    )
    chunk_ids = chunks["ids"]
    if len(chunk_ids) == 0:
        return {}
    order_to_chunk = {meta["order"]: cid for cid, meta in zip(chunk_ids, chunks["metadatas"])}

    examples = get_attack_examples_collection() if _use_examples() else None

    def dense_hits(embeddings) -> list[Half]:
        """One merged (KB ∪ procedure-examples) candidate list per query
        embedding — two batched HNSW queries instead of one when examples
        are available."""
        kb_result = get_attack_collection().query(
            query_embeddings=embeddings, n_results=CANDIDATE_POOL
        )
        if examples is None:
            return [_dense_candidates(kb_result, i) for i in range(len(embeddings))]
        ex_result = examples.query(query_embeddings=embeddings, n_results=CANDIDATE_POOL)
        return [
            _merge_by_distance(_dense_candidates(kb_result, i), _example_candidates(ex_result, i))
            for i in range(len(embeddings))
        ]

    chunk_hits = dense_hits(chunks["embeddings"])

    # Sentence-window dense half: one batched KB query for every window of the
    # report, grouped back per chunk and max-pooled (plus each chunk's
    # per-window seat set for fusion).
    window_half_by_chunk: dict[str, tuple[Half, dict[str, int]]] = {}
    if settings.sentence_retrieval:
        windows = get_report_windows_collection().get(
            where={"report_id": report_id}, include=["embeddings", "metadatas"]
        )
        if len(windows["ids"]) > 0:
            indices_by_chunk: dict[str, list[int]] = {}
            for i, meta in enumerate(windows["metadatas"]):
                chunk_id = order_to_chunk.get(meta["chunk_order"])
                if chunk_id is not None:
                    indices_by_chunk.setdefault(chunk_id, []).append(i)
            window_hits = dense_hits(windows["embeddings"])
            window_half_by_chunk = {
                chunk_id: _pooled_window_candidates([window_hits[i] for i in indices])
                for chunk_id, indices in indices_by_chunk.items()
            }

    def halves_for(i: int, chunk_id: str) -> tuple[list[Half], dict[str, int]]:
        halves = [chunk_hits[i]]
        window_seats: dict[str, int] = {}
        if chunk_id in window_half_by_chunk:
            window_half, window_seats = window_half_by_chunk[chunk_id]
            halves.append(window_half)
        if settings.sentence_retrieval:
            # Body only (chunk documents are "<breadcrumb>\n\n<body>"): the
            # breadcrumb line as a sentence voter crowns generic hits for the
            # section title; the windows half is body-only for the same reason.
            doc = chunks["documents"][i]
            body = doc.split("\n\n", 1)[1] if chunks["metadatas"][i].get("heading_path") else doc
            halves.append(bm25_search_sentences(body, CANDIDATE_POOL))
        else:
            halves.append(bm25_search(chunks["documents"][i], CANDIDATE_POOL))
        return halves, window_seats

    def fused_for(i: int, chunk_id: str) -> list[TechniqueMatch]:
        halves, window_seats = halves_for(i, chunk_id)
        return _prepend_explicit_ids(
            chunks["documents"][i],
            _fuse(halves, top_k_per_chunk, window_seats),
            top_k_per_chunk,
        )

    return {chunk_id: fused_for(i, chunk_id) for i, chunk_id in enumerate(chunk_ids)}
