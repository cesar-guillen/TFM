from dataclasses import dataclass

from app.attack.embeddings import embed_text
from app.core.chroma import get_chroma_client
from app.core.config import settings


@dataclass
class TechniqueMatch:
    attack_id: str
    name: str
    tactics: list[str]
    url: str
    is_subtechnique: bool
    distance: float


def search_techniques(text: str, top_k: int = 8) -> list[TechniqueMatch]:
    """Dense retrieval against the ATT&CK knowledge base: embed `text` and
    return its top_k nearest techniques. Keyword (BM25) retrieval and
    reranking (pipeline stage 4) will combine with this later; for now this
    is the whole retrieval stage.
    """
    embedding = embed_text(text)
    collection = get_chroma_client().get_or_create_collection(settings.attack_collection)
    result = collection.query(query_embeddings=[embedding], n_results=top_k)

    matches = []
    ids = result["ids"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]
    for attack_id, meta, distance in zip(ids, metadatas, distances):
        matches.append(
            TechniqueMatch(
                attack_id=attack_id,
                name=meta["name"],
                tactics=meta["tactics"].split(",") if meta["tactics"] else [],
                url=meta["url"],
                is_subtechnique=meta["is_subtechnique"],
                distance=distance,
            )
        )
    return matches


def search_techniques_for_report(report_id: str, top_k_per_chunk: int = 5) -> dict[str, list[TechniqueMatch]]:
    """Run retrieval for every indexed chunk of one report, keyed by chunk id
    (`"<report_id>:<order>"`). One query per chunk for now — cheap since these
    are small collections and Ollama embeddings are already computed at index
    time; batching/reranking can replace this once stage 4 exists.
    """
    collection = get_chroma_client().get_or_create_collection(settings.report_chunks_collection)
    chunks = collection.get(where={"report_id": report_id}, include=["documents"])

    results: dict[str, list[TechniqueMatch]] = {}
    for chunk_id, document in zip(chunks["ids"], chunks["documents"]):
        results[chunk_id] = search_techniques(document, top_k=top_k_per_chunk)
    return results
