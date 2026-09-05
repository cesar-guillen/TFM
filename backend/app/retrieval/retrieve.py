"""Hybrid retrieval: which ATT&CK techniques a piece of report text is about.

Up to three halves are fused with reciprocal rank fusion — dense over the whole
text, dense over its sentence windows, and per-sentence BM25 — because a
technique evidenced by one sentence inside a chunk about something else is
invisible to chunk-level retrieval alone. Rank-based fusion is deliberate:
cosine distances and BM25 scores live on incomparable scales.
"""

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
from app.retrieval import rerank
from app.retrieval.bm25 import bm25_search, bm25_search_sentences

# Candidates each half contributes before fusion. Wider than any final top_k,
# so a technique ranked mid-pack by one half can still win overall when another
# half also ranks it.
CANDIDATE_POOL = 30

# RRF damping constant: rank contributions are 1/(60+rank), which stops a
# single #1 rank from steamrolling everything else.
RRF_K = 60

# Seats reserved for each half's own top candidate, so strong single-half
# signal survives a cut that weak two-half agreement would otherwise win.
# Depth 1, not 2: reserves are rank-blind, and at depth 2 they consumed a third
# of the candidate budget at a quarter of the window quota's hit rate.
RESERVE_PER_HALF = 1

# ATT&CK ids cited literally in report text ("... encryption features.
# [T1573]"). Neither retrieval half can surface these — KB documents carry
# names and descriptions, not ids — so they are injected as candidates.
ATTACK_ID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")

# Mechanisms whose bare token IS a technique's name (or its one canonical
# tool), injected the same way: the sentence otherwise loses every half's slot
# competition to the chunk's dominant topic. Keep this table tiny — each token
# must name exactly one mechanism with one canonical (sub-)technique, and must
# not double as an ordinary English word (that's why "net group"/"net user"/
# "dir"/"ping" aren't here: single-token matching can't safely disambiguate
# them, and common words would false-fire on unrelated prose).
#
# Discovery entries (added 2026-09-03) target the corpus's single largest
# retrieval-ceiling gap: a real-report enumeration sentence ("ran net group,
# whoami, systeminfo, nltest, tasklist...") is itself a packed list, so one
# command wins the chunk's slot competition and the rest are structurally
# unreachable — measured on 3 external DFIR Report intrusions, Discovery was
# 40% of every miss and unreachable in 3/3 (data/dfir_analysis/). Same
# mechanism as the lateral-movement entries below, applied to the tactic
# actually costing the most recall on real reports.
MECHANISM_ALIASES = {
    "ssh": "T1021.004",
    "rdp": "T1021.001",
    "winrm": "T1021.006",
    "vnc": "T1021.005",
    "whoami": "T1033",
    "systeminfo": "T1082",
    "tasklist": "T1057",
    "netstat": "T1049",
    "ipconfig": "T1016",
    "nltest": "T1482",
    "nmap": "T1046",
    # SoftPerfect NetScan (added 2026-09-05): a second, distinct tool naming
    # the same technique — nmap alone missed it on a real report that used
    # NetScan by name and as `netscan.exe` dozens of times, T1046 never once
    # offered as a candidate through any other retrieval signal.
    "netscan": "T1046",
    "localgroup": "T1069.001",
    "icacls": "T1222",
    "dcsync": "T1003.006",
}
_MECHANISM_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Same idea, for mechanisms named by a short PHRASE rather than one token —
# single-token matching can't express these (MECHANISM_ALIASES' own docstring
# rules out "net group"/"net user" for exactly this reason: the tokens "net"
# and "group" are each too common alone to inject safely). A phrase is safe
# where its constituent words are common but the *sequence* is specific to
# the mechanism and essentially never appears in unrelated report prose.
# Added 2026-09-05, same motivation and corpus as the discovery entries above:
# a real DFIR Report bullet reads "Net - Enumerate user groups, domain
# accounts, computers, and password policy" — one compressed sentence naming
# four Discovery techniques via a bare, ambiguous "Net" that no single-token
# alias can resolve. Deliberately narrow: "user groups" and "computers" stay
# unaliased from that same sentence (ambiguous local-vs-domain, and "computers"
# alone is too generic), so this closes part of that gap, not all of it.
PHRASE_ALIASES = {
    "domain accounts": "T1087.002",
    "password policy": "T1201",
}
_PHRASE_RES = {re.compile(r"\b" + re.escape(p) + r"\b"): tid for p, tid in PHRASE_ALIASES.items()}

# Above any reachable RRF score, so citation-bearing chunks also lead the
# mapper's strongest-first submission order.
EXPLICIT_ID_SCORE = 1.0


@dataclass
class TechniqueMatch:
    attack_id: str
    name: str
    tactics: list[str]
    url: str
    is_subtechnique: bool
    score: float  # fused RRF score, higher is better; comparable across queries
    distance: float | None = None  # best cosine distance; None for BM25-only hits


# One half's candidates, best-first: (attack_id, metadata, cosine distance),
# distance being None for keyword halves.
Half = list[tuple[str, dict, float | None]]


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


@lru_cache(maxsize=1)
def _examples_count() -> int:
    try:
        return get_attack_examples_collection().count()
    except Exception:
        return 0


def _use_examples() -> bool:
    """Procedure examples merge in only when enabled and actually built, so a
    checkout that never ran build_examples degrades to KB-only retrieval."""
    return settings.example_retrieval and _examples_count() > 0


def _dense_candidates(result: dict, i: int) -> Half:
    """Best-first candidates for the i-th query of a batched Chroma result."""
    return list(zip(result["ids"][i], result["metadatas"][i], result["distances"][i]))


def _example_candidates(result: dict, i: int) -> Half:
    """Like _dense_candidates for the procedure-examples collection, whose
    record ids are "T1489:ex3" — the technique id lives in the metadata."""
    return [
        (meta["attack_id"], meta, distance)
        for meta, distance in zip(result["metadatas"][i], result["distances"][i])
    ]


def _merge_by_distance(*hit_lists: Half) -> Half:
    """Merge lists produced by the SAME query vector against different
    collections. Distances are directly comparable there, so this is a plain
    best-distance dedupe per technique rather than rank arithmetic."""
    best: dict[str, tuple[str, dict, float | None]] = {}
    for hits in hit_lists:
        for attack_id, meta, distance in hits:
            current = best.get(attack_id)
            if current is None or (distance or 0.0) < (current[2] or 0.0):
                best[attack_id] = (attack_id, meta, distance)
    return sorted(best.values(), key=lambda hit: (hit[2], hit[0]))[:CANDIDATE_POOL]


def _dense_hits(embeddings: list) -> list[Half]:
    """One candidate list per query embedding, from the KB and (when enabled)
    the procedure examples, in one batched query per collection."""
    kb_result = get_attack_collection().query(
        query_embeddings=embeddings, n_results=CANDIDATE_POOL
    )
    if not _use_examples():
        return [_dense_candidates(kb_result, i) for i in range(len(embeddings))]
    example_result = get_attack_examples_collection().query(
        query_embeddings=embeddings, n_results=CANDIDATE_POOL
    )
    return [
        _merge_by_distance(_dense_candidates(kb_result, i), _example_candidates(example_result, i))
        for i in range(len(embeddings))
    ]


def _pooled_window_candidates(per_window: list[Half]) -> tuple[Half, dict[str, int]]:
    """Merge one chunk's per-window candidate lists into a single half, pooled
    by per-window *rank* (best rank wins, ties by vote count, then id). This is
    what gives a minority sentence's technique its own undiluted dense shot;
    distances aren't comparable across windows, so pooling them would let a
    tight majority cluster re-bury the minority window's find.

    Also returns the seat quota for _fuse: each window's top
    `settings.window_seat_depth` ids mapped to their best per-window rank.
    """
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


def _fuse(
    halves: list[Half],
    top_k: int,
    window_seats: dict[str, int] | None = None,
    rerank_windows: list[str] | None = None,
) -> list[TechniqueMatch]:
    """Reciprocal rank fusion across the halves, selecting `top_k` candidates.

    Seats are allocated in three tiers:
    - `window_seats` first, with absolute priority and capped at half of top_k.
      A minority sentence's #1 hit has only one lonely half-contribution, so
      any selection by fused score re-buries it; the cap exists because table
      chunks give every row its own window and would otherwise fill the menu.
    - each half's own top candidate (RESERVE_PER_HALF), skipped when the
      cross-encoder ran: it judges single-half strength directly.
    - the rest by fused score, tie-broken by attack_id so selection is
      deterministic rather than dependent on which half was processed first.
    """
    fused: dict[str, dict] = {}
    for results in halves:
        for rank, (attack_id, meta, distance) in enumerate(results, start=1):
            entry = fused.setdefault(attack_id, {"meta": meta, "score": 0.0, "distance": None})
            entry["score"] += 1.0 / (RRF_K + rank)
            if distance is not None and (entry["distance"] is None or distance < entry["distance"]):
                entry["distance"] = distance

    scores = {a: fused[a]["score"] for a in fused}
    ranking = sorted(fused, key=lambda a: (-fused[a]["score"], a))

    cross_encoder: dict[str, float] = {}
    if rerank_windows and rerank.available():
        head = ranking[: rerank.RERANK_DEPTH]
        kb = get_attack_collection().get(ids=head, include=["documents"])
        cross_encoder = rerank.rerank_scores(rerank_windows, dict(zip(kb["ids"], kb["documents"])))
    if cross_encoder:
        ranking = rerank.blended_order(scores, cross_encoder)

    selected = sorted(
        (a for a in (window_seats or {}) if a in fused),
        key=lambda a: (window_seats[a], -fused[a]["score"], a),
    )[: top_k // 2]
    passes: list[set[str] | None] = []
    if not cross_encoder:
        passes.append({a for results in halves for a, _, _ in results[:RESERVE_PER_HALF]})
    passes.append(None)
    for pool in passes:
        for attack_id in ranking:
            if len(selected) >= top_k:
                break
            if attack_id not in selected and (pool is None or attack_id in pool):
                selected.append(attack_id)

    position = {a: i for i, a in enumerate(ranking)}
    selected.sort(key=lambda a: position.get(a, len(position)))
    return [
        _match_from_meta(a, fused[a]["meta"], fused[a]["score"], fused[a]["distance"])
        for a in selected
    ]


def _prepend_explicit_ids(
    text: str, fused: list[TechniqueMatch], top_k: int
) -> list[TechniqueMatch]:
    """Put techniques the text cites by id — or names by mechanism token — in
    front of the retrieved candidates, keeping the total at top_k so the
    mapper's prompt budget doesn't grow. Cited ids missing from the KB
    (deprecated, revoked, typos) simply don't come back and are dropped."""
    if not settings.explicit_ids:
        return fused
    cited = sorted({m.group(0).upper() for m in ATTACK_ID_RE.finditer(text)})
    lowered = text.lower()
    tokens = set(_MECHANISM_TOKEN_RE.findall(lowered))
    cited += sorted(
        {tid for token, tid in MECHANISM_ALIASES.items() if token in tokens} - set(cited)
    )
    cited += sorted(
        {tid for pattern, tid in _PHRASE_RES.items() if pattern.search(lowered)} - set(cited)
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


def search_techniques(text: str, top_k: int = 8) -> list[TechniqueMatch]:
    """Hybrid retrieval for one piece of ad-hoc text (embeds it on the fly).
    For an indexed report use search_techniques_for_report, which reuses the
    embeddings computed at ingest."""
    halves: list[Half] = [_dense_hits([embed_text(text)])[0]]
    window_seats: dict[str, int] = {}

    windows = build_windows(text) if settings.sentence_retrieval else []
    if settings.sentence_retrieval:
        if len(windows) > 1:
            window_half, window_seats = _pooled_window_candidates(_dense_hits(embed_texts(windows)))
            halves.append(window_half)
        halves.append(bm25_search_sentences(text, CANDIDATE_POOL))
    else:
        halves.append(bm25_search(text, CANDIDATE_POOL))

    return _prepend_explicit_ids(
        text, _fuse(halves, top_k, window_seats, windows or [text]), top_k
    )


def search_techniques_for_report(
    report_id: str, top_k_per_chunk: int = 5
) -> dict[str, list[TechniqueMatch]]:
    """Hybrid retrieval for every indexed chunk of one report, keyed by chunk
    id ("<report_id>:<order>"). This is the shape the LLM mapping stage
    consumes.

    Makes zero Ollama calls: the dense halves reuse the embeddings stored at
    index time (two batched HNSW queries for the whole report) and BM25 runs
    in-process. Reports indexed before sentence windows existed simply have no
    window half, and fusion degrades gracefully.
    """
    chunks = get_report_chunks_collection().get(
        where={"report_id": report_id}, include=["embeddings", "documents", "metadatas"]
    )
    chunk_ids = chunks["ids"]
    if len(chunk_ids) == 0:
        return {}
    order_to_chunk = {meta["order"]: cid for cid, meta in zip(chunk_ids, chunks["metadatas"])}

    chunk_hits = _dense_hits(chunks["embeddings"])

    # Sentence-window half: one batched query for every window in the report,
    # grouped back per chunk and rank-pooled.
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
            window_hits = _dense_hits(windows["embeddings"])
            window_half_by_chunk = {
                chunk_id: _pooled_window_candidates([window_hits[i] for i in indices])
                for chunk_id, indices in indices_by_chunk.items()
            }

    def body(i: int) -> str:
        """Chunk text without its breadcrumb line: as a sentence voter, the
        breadcrumb crowns generic hits for the section title."""
        doc = chunks["documents"][i]
        return doc.split("\n\n", 1)[1] if chunks["metadatas"][i].get("heading_path") else doc

    def fused_for(i: int, chunk_id: str) -> list[TechniqueMatch]:
        halves = [chunk_hits[i]]
        window_seats: dict[str, int] = {}
        if chunk_id in window_half_by_chunk:
            window_half, window_seats = window_half_by_chunk[chunk_id]
            halves.append(window_half)
        if settings.sentence_retrieval:
            halves.append(bm25_search_sentences(body(i), CANDIDATE_POOL))
        else:
            halves.append(bm25_search(chunks["documents"][i], CANDIDATE_POOL))

        # The reranker needs window *text*, not the stored embeddings.
        rerank_windows = build_windows(body(i)) if rerank.available() else []
        return _prepend_explicit_ids(
            chunks["documents"][i],
            _fuse(halves, top_k_per_chunk, window_seats, rerank_windows or [body(i)]),
            top_k_per_chunk,
        )

    return {chunk_id: fused_for(i, chunk_id) for i, chunk_id in enumerate(chunk_ids)}
