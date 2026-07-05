from typing import Callable

import httpx

from app.attack.embeddings import embed_text
from app.core.chroma import get_chroma_client
from app.core.config import settings
from app.ingest.chunking import Chunk, chunk_markdown

EMBED_TIMEOUT = 240.0

# Called after each chunk embeds, as (chunks_embedded, chunk_count) — lets the
# caller surface live progress (see app.ingest.jobs) for what's by far the
# slowest step in the ingest request.
ProgressCallback = Callable[[int, int], None]


def _embed_chunks(chunks: list[Chunk], on_progress: ProgressCallback | None = None) -> list[list[float]]:
    """Sequential on purpose: the loaded nomic-embed-text runner serves
    `/api/embeddings` with a single slot (`n_slots = 1` at load, independent of
    OLLAMA_NUM_PARALLEL) — concurrent client requests just queue behind each
    other with extra context-swap overhead, they don't run in parallel."""
    embeddings = []
    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        for i, chunk in enumerate(chunks):
            embeddings.append(embed_text(chunk.text, client))
            if on_progress:
                on_progress(i + 1, len(chunks))
    return embeddings


def index_report(
    report_id: str,
    filename: str,
    markdown: str,
    on_progress: ProgressCallback | None = None,
) -> list[Chunk]:
    """Chunk a report's extracted markdown and embed+store the chunks in the
    (separate from the ATT&CK KB) `report_chunks` Chroma collection, tagged
    with `report_id` so retrieval/mapping can scope a query to one report."""
    chunks = chunk_markdown(markdown)
    if not chunks:
        return chunks

    collection = get_chroma_client().get_or_create_collection(settings.report_chunks_collection)
    embeddings = _embed_chunks(chunks, on_progress)

    collection.upsert(
        ids=[f"{report_id}:{chunk.order}" for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {
                "report_id": report_id,
                "filename": filename,
                "order": chunk.order,
                "heading_path": " > ".join(chunk.heading_path),
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
            }
            for chunk in chunks
        ],
    )
    return chunks
