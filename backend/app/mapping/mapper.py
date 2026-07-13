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

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import httpx

from app.core.chroma import get_attack_collection, get_report_chunks_collection
from app.core.config import settings
from app.core.llm import CHAT_TIMEOUT, chat_json, resolve_map_workers
from app.retrieval.retrieve import TechniqueMatch, search_techniques_for_report

# Candidate count and description length are settings (MAP_CANDIDATES /
# MAP_DESC_CHARS): prompt reading (prefill) dominates a chunk's cost on CPU,
# so the CPU compose profiles run leaner values than the full-quality
# defaults (see app.core.config).

SYSTEM_PROMPT = (
    "You are a cybersecurity analyst mapping excerpts of a security report to "
    "MITRE ATT&CK techniques. Be conservative: map a candidate technique only "
    "when the excerpt reports the attacker actually performing the activity "
    "the technique describes — a concrete action, tool use, or observed "
    "artifact. Judge every statement by who acts: the same activity is "
    "evidence only when the adversary did it, and is NOT evidence when it "
    "describes defenders or the victim organization detecting, investigating, "
    "responding, or advising (recommendations, mitigations, hardening, "
    "response actions). Do not map techniques that are merely plausible or "
    "thematically related. If the excerpt explicitly cites an ATT&CK "
    "technique id (e.g. \"[T1573]\") next to described adversary activity, "
    "that citation is concrete evidence for the matching candidate, even "
    "when the mention is brief. Confidence reflects how directly the excerpt "
    "shows the activity: high = explicitly described; medium = strongly "
    "implied by specific details; low = a weak but real indication. If the "
    "excerpt does not actually indicate the activity, return no mapping for "
    "that technique — never use low confidence as a hedge for missing "
    "evidence. If the excerpt is boilerplate (title page, table of contents, "
    "methodology, disclaimers) or describes only the victim's response "
    "process, map nothing."
)

# Called as (chunks_mapped, chunk_count, mappings_so_far) after each chunk
# resolves; mappings_so_far is a report-ordered snapshot of every accepted
# mapping to date, so the caller can publish a live partial matrix.
ProgressCallback = Callable[[int, int, list["ChunkMapping"]], None]

# Polled before each chunk's LLM call; True aborts the run (user cancelled).
AbortCheck = Callable[[], bool]


# A mapping whose own reason concedes the excerpt lacks the evidence ("The
# excerpt does not explicitly mention DNS communication, but...") — observed
# repeatedly from llama3.1:8b as low-confidence hedges despite the prompt
# forbidding plausibility mappings. The negation is about the excerpt's
# evidence, so it doubles as a mechanical confession detector.
NO_EVIDENCE_RE = re.compile(
    r"(excerpt|report|text) (does not|doesn'?t)"
    r"|no explicit(ly)? (mention|statement|evidence|indication)"
    r"|not explicitly (mention|state|describe)"
    r"|there is no (mention|evidence|indication)"
    # "...but does not confirm it was default": confirm/verify negations are
    # always about evidence certainty, whatever the sentence's subject.
    r"|(does not|doesn'?t|cannot|can'?t) (confirm|verify)",
    re.I,
)


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


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Max tokens allowed between consecutive quote tokens in the chunk. Big enough
# to absorb condensed parentheticals and inline citations ("leveraging Windows
# Command Prompt [T1059.003] and/or PowerShell" condensed to "leverage
# PowerShell" needs 8 — the bracket id alone costs 2 tokens), small enough
# that the quote still has to trace one local region — tokens scattered
# across the chunk (a fabricated quote) stay rejected.
_EVIDENCE_MAX_GAP = 8


def _tokens_match(a: str, b: str) -> bool:
    """Exact, or an inflection-tolerant stem match: the shared prefix must
    cover all but the last ≤3 chars of the shorter token ("leverage" ~
    "leveraging" share "leverag"; "encrypted" ~ "encryption" share "encrypt").
    Tokens shorter than 4 chars must match exactly."""
    if a == b:
        return True
    common = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        common += 1
    return common >= 4 and common >= min(len(a), len(b)) - 3


def _evidence_in_chunk(evidence: str, chunk: str) -> bool:
    """The quote must actually occur in the excerpt. Catches a small model
    'quoting' a candidate's description instead of the report (observed with
    llama3.2:3b: it returned a technique's own description text as evidence
    for a technique the chunk never showed). Exact whitespace/case-insensitive
    containment first; failing that, a gap-bounded token subsequence, because
    models legitimately condense quotes ("HTTP and HTTPS" — observed with
    llama3.1:8b — for a sentence naming both protocols with parentheticals)."""
    if not evidence:
        return False
    if _normalize(evidence) in _normalize(chunk):
        return True
    quote = _TOKEN_RE.findall(evidence.lower())
    if not quote:
        return False
    text = _TOKEN_RE.findall(chunk.lower())
    for start, token in enumerate(text):
        if not _tokens_match(token, quote[0]):
            continue
        pos = start
        for wanted in quote[1:]:
            window = text[pos + 1 : pos + 1 + _EVIDENCE_MAX_GAP]
            hit = next(
                (i for i, t in enumerate(window) if _tokens_match(t, wanted)),
                None,
            )
            if hit is None:
                break
            pos += 1 + hit
        else:
            return True
    return False


def _response_schema(candidate_ids: list[str]) -> dict:
    """Schema for one chunk's verdict; technique_id is an enum of this chunk's
    candidates, so the constrained decoder can't invent an id. The size bounds
    (maxItems / maxLength) keep a rambling model from generating until it hits
    the num_predict cap, which truncates the JSON mid-token — chat_json
    salvages that, but a verdict cut short still loses its tail mappings."""
    return {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "maxItems": len(candidate_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "technique_id": {"type": "string", "enum": candidate_ids},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "reason": {"type": "string", "maxLength": 300},
                        "evidence": {"type": "string", "maxLength": 240},
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
    limit = settings.map_desc_chars
    description = document.split("\n\n", 1)[-1].strip()
    if len(description) <= limit:
        return description
    cut = description.rfind(" ", 0, limit)
    return description[: cut if cut > 0 else limit] + "…"


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
        "(at most ~12 words) that evidences it — copied verbatim, exactly as "
        "written in the excerpt. Return an empty list if none apply."
    )


def map_report(
    report_id: str,
    on_progress: ProgressCallback | None = None,
    should_abort: AbortCheck | None = None,
) -> list[ChunkMapping]:
    """Run stage 6 for one indexed report: hybrid candidates per chunk, one LLM
    verdict per chunk, validated and flattened into ChunkMappings."""
    candidates_by_chunk = search_techniques_for_report(report_id, top_k_per_chunk=settings.map_candidates)
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
            if NO_EVIDENCE_RE.search(m.get("reason") or ""):
                continue  # the model itself concedes the evidence isn't there
            confidence = m.get("confidence")
            if confidence not in ("high", "medium", "low"):
                confidence = "low"  # salvaged partial verdicts may carry a cut enum
            accepted.append(
                ChunkMapping(
                    chunk_id=chunk_id,
                    heading_path=chunk_meta[chunk_id].get("heading_path", ""),
                    technique_id=tid,
                    technique_name=by_id[tid].name,
                    confidence=confidence,
                    evidence=(m.get("evidence") or "").strip()[:300],
                    reason=(m.get("reason") or "").strip()[:250],
                )
            )
        return accepted

    # Chunks resolve concurrently (map_workers must not exceed the ollama
    # service's OLLAMA_NUM_PARALLEL or requests just queue server-side).
    # Submission order is strongest-retrieval-first: the chunks most likely to
    # carry real findings get their verdicts early, so the live matrix shows
    # the substance of the report within the first few chunks — on CPU, where
    # a full run takes minutes, a user can Cancel once satisfied. Progress
    # snapshots and the final result are re-assembled in *report* order so the
    # matrix and evidence still read naturally against the document.
    ordered = sorted(candidates_by_chunk, key=lambda cid: chunk_meta[cid]["order"])
    by_signal = sorted(
        candidates_by_chunk,
        key=lambda cid: max(m.score for m in candidates_by_chunk[cid]),
        reverse=True,
    )
    total = len(ordered)
    if on_progress:
        on_progress(0, total, [])

    by_chunk: dict[str, list[ChunkMapping]] = {}
    with httpx.Client(timeout=CHAT_TIMEOUT) as client:
        with ThreadPoolExecutor(max_workers=resolve_map_workers()) as pool:
            futures = {pool.submit(map_one, chunk_id, client): chunk_id for chunk_id in by_signal}
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
