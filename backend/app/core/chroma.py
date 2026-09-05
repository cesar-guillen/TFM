from functools import lru_cache

import chromadb

from app.core.config import settings

# Both collections use cosine distance, which makes vector magnitude
# irrelevant: the KB seed's vectors (legacy, unnormalized) and the vectors
# Ollama's /api/embed returns today (L2-normalized) rank identically.
COSINE_SPACE = {"hnsw:space": "cosine"}


@lru_cache
def get_chroma_client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_attack_collection() -> chromadb.Collection:
    """The ATT&CK techniques KB. Raises on a pre-migration L2 collection —
    normalized queries against unnormalized vectors under L2 return
    plausible-looking garbage, so fail loudly with the fix instead."""
    collection = get_chroma_client().get_or_create_collection(
        settings.attack_collection, metadata=COSINE_SPACE
    )
    space = (collection.metadata or {}).get("hnsw:space", "l2")
    if space != "cosine":
        raise RuntimeError(
            f"Chroma collection '{settings.attack_collection}' uses '{space}' distance "
            "(built before the cosine migration). Re-run "
            "`docker compose exec backend python -m app.attack.build_kb` to migrate it."
        )
    return collection


def get_report_chunks_collection() -> chromadb.Collection:
    """Ingested report chunks. Never vector-queried (its embeddings serve as
    query vectors against the KB), so no space guard is needed."""
    return get_chroma_client().get_or_create_collection(
        settings.report_chunks_collection, metadata=COSINE_SPACE
    )


def get_report_windows_collection() -> chromadb.Collection:
    """Sentence windows of ingested chunks, embedded at index time for the
    sub-chunk dense retrieval half."""
    return get_chroma_client().get_or_create_collection(
        settings.report_windows_collection, metadata=COSINE_SPACE
    )


def get_attack_examples_collection() -> chromadb.Collection:
    """ATT&CK procedure examples, one embedding each, carrying their
    technique's metadata. Kept out of attack_techniques deliberately:
    concatenating examples into the technique documents dilutes them."""
    return get_chroma_client().get_or_create_collection(
        settings.attack_examples_collection, metadata=COSINE_SPACE
    )
