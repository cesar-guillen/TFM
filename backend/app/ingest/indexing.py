from typing import Callable

import httpx

from app.attack.embeddings import embed_texts
from app.core.chroma import get_report_chunks_collection
from app.ingest.chunking import Chunk, chunk_markdown

EMBED_TIMEOUT = 240.0
# Chunks embedded per /api/embed request. One request per batch amortizes HTTP/
# scheduling overhead (the runner's single slot means concurrency never helps —
# see build_kb's n_slots=1 note); kept small so the progress callback still
# updates at a reasonable cadence on slow (no-AVX VM) CPUs where one batch can
# take ~a minute.
EMBED_BATCH_SIZE = 4

# Called as (chunks_embedded, chunk_count) — immediately with (0, N) when
# embedding starts, then after each batch — so the caller (app.ingest.jobs) can
# surface live progress for what's by far the slowest step in the ingest.
ProgressCallback = Callable[[int, int], None]


def _embed_chunks(chunks: list[Chunk], on_progress: ProgressCallback | None = None) -> list[list[float]]:
    embeddings: list[list[float]] = []
    if on_progress:
        on_progress(0, len(chunks))
    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i : i + EMBED_BATCH_SIZE]
            embeddings.extend(embed_texts([chunk.text for chunk in batch], client))
            if on_progress:
                on_progress(len(embeddings), len(chunks))
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

    collection = get_report_chunks_collection()
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
