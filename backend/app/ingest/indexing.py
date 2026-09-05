from typing import Callable

import httpx

from app.attack.embeddings import embed_texts
from app.core.chroma import get_report_chunks_collection, get_report_windows_collection
from app.core.config import settings
from app.ingest.chunking import Chunk, chunk_markdown
from app.ingest.sentences import build_windows

EMBED_TIMEOUT = 240.0

# (chunks_embedded, chunk_count), called immediately with (0, N) and again
# after every chunk — embedding is by far the slowest ingest step.
ProgressCallback = Callable[[int, int], None]

# Polled between chunks; True aborts the indexing (user cancelled).
AbortCheck = Callable[[], bool]


class IndexingAborted(Exception):
    """Raised when should_abort() turns true mid-indexing. Chroma is written
    once, at the end, so an aborted ingest leaves no partial chunks behind."""


def _chunk_body(chunk: Chunk) -> str:
    """The chunk text without its breadcrumb line. Windows must carry pure
    sentence semantics — a heading prefix pulls every window's embedding toward
    the section theme, which is the dilution windows exist to undo."""
    return chunk.text.split("\n\n", 1)[1] if chunk.heading_path else chunk.text


def _embed_report(
    chunks: list[Chunk],
    on_progress: ProgressCallback | None = None,
    should_abort: AbortCheck | None = None,
) -> tuple[list[list[float]], list[list[str]], list[list[list[float]]]]:
    """(chunk embeddings, window texts per chunk, window embeddings per chunk).

    One /api/embed request per chunk covering the chunk plus its sentence
    windows: the embed runner serves a single slot, so batching within a
    request is the only way to amortize per-request overhead, and per-chunk
    requests keep progress updating frequently."""
    chunk_embeddings: list[list[float]] = []
    window_texts: list[list[str]] = []
    window_embeddings: list[list[list[float]]] = []
    if on_progress:
        on_progress(0, len(chunks))
    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        for i, chunk in enumerate(chunks):
            if should_abort and should_abort():
                raise IndexingAborted()
            windows = build_windows(_chunk_body(chunk))
            vectors = embed_texts([chunk.text, *windows], client)
            chunk_embeddings.append(vectors[0])
            window_texts.append(windows)
            window_embeddings.append(vectors[1:])
            if on_progress:
                on_progress(i + 1, len(chunks))
    return chunk_embeddings, window_texts, window_embeddings


def index_report(
    report_id: str,
    filename: str,
    markdown: str,
    on_progress: ProgressCallback | None = None,
    should_abort: AbortCheck | None = None,
) -> tuple[list[Chunk], int]:
    """Chunk a report's markdown, embed it, and store the chunks (and their
    sentence windows) in Chroma, tagged with `report_id` so retrieval can scope
    to one report. With settings.section_filter on, defender-guidance and
    boilerplate chunks are neither embedded nor stored. Returns the indexed
    chunks and how many were skipped."""
    all_chunks = chunk_markdown(markdown)
    if settings.section_filter:
        chunks = [c for c in all_chunks if c.section_role == "content"]
    else:
        chunks = all_chunks
    skipped = len(all_chunks) - len(chunks)
    if not chunks:
        return chunks, skipped

    embeddings, window_texts, window_embeddings = _embed_report(chunks, on_progress, should_abort)

    # Windows first: retrieval keys on chunk presence, so if the process dies
    # between the upserts, orphan windows are harmless while chunks without
    # windows would silently lose the sub-chunk dense half.
    window_ids, window_docs, window_vecs, window_metas = [], [], [], []
    for chunk, texts, vecs in zip(chunks, window_texts, window_embeddings):
        for j, (text, vec) in enumerate(zip(texts, vecs)):
            window_ids.append(f"{report_id}:{chunk.order}:w{j}")
            window_docs.append(text)
            window_vecs.append(vec)
            window_metas.append({"report_id": report_id, "chunk_order": chunk.order})
    if window_ids:
        get_report_windows_collection().upsert(
            ids=window_ids,
            embeddings=window_vecs,
            documents=window_docs,
            metadatas=window_metas,
        )

    get_report_chunks_collection().upsert(
        ids=[f"{report_id}:{chunk.order}" for chunk in chunks],
        embeddings=embeddings,
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {
                "report_id": report_id,
                "filename": filename,
                "order": chunk.order,
                "heading_path": " > ".join(chunk.heading_path),
                "section_role": chunk.section_role,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
            }
            for chunk in chunks
        ],
    )
    return chunks, skipped
