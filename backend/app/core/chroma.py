from functools import lru_cache

import chromadb

from app.core.config import settings

# Both collections use cosine distance. This makes vector magnitude irrelevant,
# which is what lets the unnormalized KB seed vectors (embedded via the legacy
# /api/embeddings endpoint) coexist with the L2-normalized vectors the batch
# /api/embed endpoint now produces (see app.attack.embeddings) — same
# directions, different magnitudes, identical cosine ranking.
COSINE_SPACE = {"hnsw:space": "cosine"}


@lru_cache
def get_chroma_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_attack_collection() -> chromadb.Collection:
    """The ATT&CK techniques KB. Raises if an existing collection still uses
    the pre-migration L2 space — normalized query vectors against unnormalized
    stored vectors under L2 would silently return garbage neighbors, so fail
    loudly with the fix instead."""
    collection = get_chroma_client().get_or_create_collection(
        settings.attack_collection, metadata=COSINE_SPACE
    )
    space = (collection.metadata or {}).get("hnsw:space", "l2")
    if space != "cosine":
        raise RuntimeError(
            f"Chroma collection '{settings.attack_collection}' uses '{space}' distance "
            "(built before the cosine migration). Re-run "
            "`docker compose exec backend python -m app.attack.build_kb` to migrate it "
            "(instant — restores from the bundled seed)."
        )
    return collection


def get_report_chunks_collection() -> chromadb.Collection:
    """Ingested report chunks. Not vector-queried today (its embeddings are
    used as *query* vectors against the KB), so an existing pre-migration L2
    collection is harmless — no space guard needed."""
    return get_chroma_client().get_or_create_collection(
        settings.report_chunks_collection, metadata=COSINE_SPACE
    )
