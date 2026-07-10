"""LLM mapping (pipeline stage 6): decide, per chunk, which of the hybrid
retrieval candidates the chunk text actually evidences.

Grounding rules (the hallucination mitigations from CLAUDE.md):
- The model only ever sees candidates that hybrid retrieval produced for that
  chunk, and its output is schema-constrained to pick from *those ids only*
  (enum in the JSON schema) — it cannot name a technique it wasn't offered.
- Anything else the model does wrong (a hallucinated id would require a schema
  violation, but belt-and-braces) is dropped by the id validation here.
- Every accepted mapping carries the model's quoted evidence plus the chunk's
  heading breadcrumb and id, preserving the evidence-traceability chain
  (technique -> chunk -> char span in the source markdown).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import httpx

from app.core.chroma import get_attack_collection, get_report_chunks_collection
from app.core.config import settings
from app.core.llm import CHAT_TIMEOUT, chat_json
from app.retrieval.retrieve import TechniqueMatch, search_techniques_for_report

CANDIDATES_PER_CHUNK = 8
DESCRIPTION_TRIM_CHARS = 250  # candidate descriptions are trimmed to keep the prompt small (3B model)

SYSTEM_PROMPT = (
    "You are a cybersecurity analyst mapping excerpts of a security report to "
    "MITRE ATT&CK techniques. Be conservative: only map a technique when the "
    "excerpt contains concrete evidence of it — an activity, tool, or finding "
    "that the technique describes. Do not map techniques that are merely "
    "plausible or thematically related. A technique mentioned only as something "
    "to prevent, detect, or remediate (recommendations, mitigations, hardening "
    "advice, response actions) is NOT evidence — map only adversary activity "
    "the excerpt reports as having occurred. If the excerpt is boilerplate "
    "(title page, table of contents, methodology, disclaimers), map nothing."
)

# Called as (chunks_mapped, chunk_count, mappings_so_far) after each chunk
# resolves; mappings_so_far is a report-ordered snapshot of every accepted
# mapping to date, so the caller can publish a live partial matrix.
ProgressCallback = Callable[[int, int, list["ChunkMapping"]], None]

# Polled before each chunk's LLM call; True aborts the run (user cancelled).
AbortCheck = Callable[[], bool]


class MappingAborted(Exception):
    """Raised when should_abort() turns true mid-run. Queued chunks are
    cancelled immediately; verdicts already in flight at Ollama finish on
    their own in abandoned threads and are discarded."""


@dataclass
class ChunkMapping:
    chunk_id: str
    heading_path: str
    technique_id: str
    technique_name: str
    confidence: str  # "high" | "medium" | "low"
    evidence: str
    reason: str = ""  # the model's one-sentence justification for the mapping


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _evidence_in_chunk(evidence: str, chunk: str) -> bool:
    """Whitespace/case-insensitive containment: the quote must actually occur
    in the excerpt. Catches a small model 'quoting' a candidate's description
    instead of the report (observed with llama3.2:3b: it returned a technique's
    own description text as evidence for a technique the chunk never showed)."""
    return bool(evidence) and _normalize(evidence) in _normalize(chunk)


def _response_schema(candidate_ids: list[str]) -> dict:
    """Schema for one chunk's verdict; technique_id is an enum of this chunk's
    candidates, so the constrained decoder can't invent an id."""
    return {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "technique_id": {"type": "string", "enum": candidate_ids},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reason": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["technique_id", "confidence", "reason", "evidence"],
                },
            }
        },
        "required": ["mappings"],
    }


def _trim_description(document: str) -> str:
    """KB documents are 'Name\\n\\nDescription…'; keep a word-safe prefix of the
    description part, enough to disambiguate without blowing up the prompt."""
    description = document.split("\n\n", 1)[-1].strip()
    if len(description) <= DESCRIPTION_TRIM_CHARS:
        return description
    cut = description.rfind(" ", 0, DESCRIPTION_TRIM_CHARS)
    return description[: cut if cut > 0 else DESCRIPTION_TRIM_CHARS] + "…"


def _candidate_block(candidates: list[TechniqueMatch], descriptions: dict[str, str]) -> str:
    lines = []
    for match in candidates:
        lines.append(f"- {match.attack_id} ({match.name}): {descriptions.get(match.attack_id, '')}")
    return "\n".join(lines)


def _chunk_prompt(chunk_text: str, candidates: list[TechniqueMatch], descriptions: dict[str, str]) -> str:
    return (
        "Report excerpt:\n"
        "---\n"
        f"{chunk_text}\n"
        "---\n\n"
        "Candidate ATT&CK techniques (the only valid choices):\n"
        f"{_candidate_block(candidates, descriptions)}\n\n"
        "Which candidates does the excerpt give concrete evidence for? For each, "
        "give a one-sentence reason saying what in the excerpt shows the "
        "technique being used, and quote the shortest phrase from the excerpt "
        "(at most ~12 words) that evidences it. Return an empty list if none apply."
    )


def map_report(
    report_id: str,
    on_progress: ProgressCallback | None = None,
    should_abort: AbortCheck | None = None,
) -> list[ChunkMapping]:
    """Run stage 6 for one indexed report: hybrid candidates per chunk, one LLM
    verdict per chunk, validated and flattened into ChunkMappings."""
    candidates_by_chunk = search_techniques_for_report(report_id, top_k_per_chunk=CANDIDATES_PER_CHUNK)
    if not candidates_by_chunk:
        return []

    chunks = get_report_chunks_collection().get(
        where={"report_id": report_id}, include=["documents", "metadatas"]
    )
    chunk_text = dict(zip(chunks["ids"], chunks["documents"]))
    chunk_meta = dict(zip(chunks["ids"], chunks["metadatas"]))

    # One KB fetch for every candidate description this report needs.
    all_ids = sorted({m.attack_id for ms in candidates_by_chunk.values() for m in ms})
    kb = get_attack_collection().get(ids=all_ids, include=["documents"])
    descriptions = {i: _trim_description(d) for i, d in zip(kb["ids"], kb["documents"])}

    def map_one(chunk_id: str, client: httpx.Client) -> list[ChunkMapping]:
        # Checked as each queued chunk's turn comes up, so a cancel takes
        # effect within one verdict's latency instead of after the whole queue.
        if should_abort and should_abort():
            raise MappingAborted()
        candidates = candidates_by_chunk[chunk_id]
        by_id = {m.attack_id: m for m in candidates}
        result = chat_json(
            _chunk_prompt(chunk_text[chunk_id], candidates, descriptions),
            _response_schema(list(by_id)),
            client=client,
            system=SYSTEM_PROMPT,
        )
        accepted: list[ChunkMapping] = []
        for m in result.get("mappings", []):
            tid = m.get("technique_id")
            if tid not in by_id:  # schema enum should prevent this; drop if not
                continue
            if not _evidence_in_chunk(m.get("evidence") or "", chunk_text[chunk_id]):
                continue  # fabricated/paraphrased "quote" — not grounded, drop it
            accepted.append(
                ChunkMapping(
                    chunk_id=chunk_id,
                    heading_path=chunk_meta[chunk_id].get("heading_path", ""),
                    technique_id=tid,
                    technique_name=by_id[tid].name,
                    confidence=m.get("confidence", "low"),
                    evidence=(m.get("evidence") or "").strip()[:300],
                    reason=(m.get("reason") or "").strip()[:250],
                )
            )
        return accepted

    # Submit in report order; chunks resolve concurrently (map_workers must not
    # exceed the ollama service's OLLAMA_NUM_PARALLEL or requests just queue
    # server-side). Progress snapshots are re-assembled in report order so the
    # partial matrix and evidence read naturally against the document.
    ordered = sorted(candidates_by_chunk, key=lambda cid: chunk_meta[cid]["order"])
    total = len(ordered)
    if on_progress:
        on_progress(0, total, [])

    by_chunk: dict[str, list[ChunkMapping]] = {}
    with httpx.Client(timeout=CHAT_TIMEOUT) as client:
        with ThreadPoolExecutor(max_workers=settings.map_workers) as pool:
            futures = {pool.submit(map_one, chunk_id, client): chunk_id for chunk_id in ordered}
            try:
                for future in as_completed(futures):
                    # Also honor a cancel when every remaining chunk is already
                    # in flight (map_one's check never runs again then).
                    if should_abort and should_abort():
                        raise MappingAborted()
                    by_chunk[futures[future]] = future.result()
                    if on_progress:
                        snapshot = [m for cid in ordered for m in by_chunk.get(cid, [])]
                        on_progress(len(by_chunk), total, snapshot)
            except BaseException:
                # A failed chunk fails the run: don't let queued chunks grind
                # on (each can block for the full LLM timeout) before the
                # error reaches the job.
                pool.shutdown(wait=False, cancel_futures=True)
                raise
    return [m for cid in ordered for m in by_chunk.get(cid, [])]
