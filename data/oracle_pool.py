"""Oracle ceiling of the raw retrieval pool — bounds what ANY reranker could do.

A reranker reorders what retrieval already found; it cannot invent candidates.
So the question "is a reranker worth building?" reduces to: how many core
techniques sit somewhere in the three halves' CANDIDATE_POOL(=30) lists but are
discarded by fusion's truncation to top_k=8?

  pool ceiling  = core techniques present in ANY chunk's raw half-pools
  shipped       = core techniques present in the fused top-8 (today)
  headroom      = the gap a perfect reranker could close

Reported per report, and per-chunk-aware: a technique only counts toward the
"recoverable" figure if it is in the pool of a chunk that is plausibly about it
(we report both the chunk-agnostic figure, matching the harness, and the count
of distinct chunks whose pool holds it).

    docker compose exec -T -e PYTHONPATH=/app backend python /tmp/oracle_pool.py
"""

import json

from app.core.chroma import get_report_chunks_collection, get_report_windows_collection
from app.core.config import settings
from app.eval.ground_truth import REPORTS
from app.retrieval import retrieve as R

IDS = json.load(open("/data/eval_reports.json"))
TOP_K = settings.map_candidates


def half_pools(report_id):
    """Every half's raw candidate list per chunk, before fusion truncation."""
    chunks = get_report_chunks_collection().get(
        where={"report_id": report_id}, include=["embeddings", "documents", "metadatas"]
    )
    ids = chunks["ids"]
    order_to_chunk = {m["order"]: c for c, m in zip(ids, chunks["metadatas"])}
    kb = R.get_attack_collection()

    def dense(embs):
        res = kb.query(query_embeddings=embs, n_results=R.CANDIDATE_POOL)
        return [R._dense_candidates(res, i) for i in range(len(embs))]

    chunk_hits = dense(chunks["embeddings"])

    window_half = {}
    if settings.sentence_retrieval:
        w = get_report_windows_collection().get(
            where={"report_id": report_id}, include=["embeddings", "metadatas"]
        )
        if len(w["ids"]) > 0:
            by_chunk = {}
            for i, meta in enumerate(w["metadatas"]):
                cid = order_to_chunk.get(meta["chunk_order"])
                if cid is not None:
                    by_chunk.setdefault(cid, []).append(i)
            wh = dense(w["embeddings"])
            window_half = {
                cid: R._pooled_window_candidates([wh[i] for i in idx])[0]
                for cid, idx in by_chunk.items()
            }

    out = {}
    for i, cid in enumerate(ids):
        halves = [chunk_hits[i]]
        if cid in window_half:
            halves.append(window_half[cid])
        doc = chunks["documents"][i]
        body = doc.split("\n\n", 1)[1] if chunks["metadatas"][i].get("heading_path") else doc
        halves.append(R.bm25_search_sentences(body, R.CANDIDATE_POOL))
        out[cid] = {a for h in halves for a, _, _ in h}
    return out


print(f"top_k={TOP_K}  CANDIDATE_POOL={R.CANDIDATE_POOL}\n")
print(f"{'report':<17}{'core':>5}{'shipped@8':>11}{'pool ceiling':>14}{'headroom':>10}")
print("-" * 60)

detail = {}
for name in ["openslop", "meridian-health", "meridian-grove"]:
    gt = REPORTS[name]
    rid = IDS[name]
    core = set(gt.core)

    pools = half_pools(rid)
    in_pool = {t for t in core if any(t in p for p in pools.values())}

    fused = R.search_techniques_for_report(rid, top_k_per_chunk=TOP_K)
    shipped = {t for t in core if any(t in {m.attack_id for m in ms} for ms in fused.values())}

    gained = sorted(in_pool - shipped)
    detail[name] = (gained, pools, core)
    print(f"{name:<17}{len(core):>5}{len(shipped):>11}{len(in_pool):>14}{len(in_pool)-len(shipped):>10}")

print()
for name, (gained, pools, core) in detail.items():
    print(f"\n{name}: {len(gained)} core techniques in the pool but cut by fusion")
    for t in gained:
        n = sum(1 for p in pools.values() if t in p)
        print(f"   {t:<12} in {n:>2} chunk pool(s)   {REPORTS[name].core[t][:64]}")
    still = sorted(core - {x for x in core if any(x in p for p in pools.values())})
    print(f"   -- absent from every pool ({len(still)}): {', '.join(still) or 'none'}")
