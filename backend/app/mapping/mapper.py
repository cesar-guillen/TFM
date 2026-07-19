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

import logging
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
    "thematically related. Consider each candidate independently: an excerpt "
    "often evidences several distinct techniques at once, so map every "
    "candidate the excerpt genuinely supports, not only the most prominent "
    "one — a lateral-movement sentence naming a protocol and a credential "
    "technique in the same breath evidences both. When the excerpt names the "
    "specific mechanism a sub-technique describes (a named protocol like SSH "
    "or RDP, a named file like /etc/shadow, a named tool or method), map that "
    "precise sub-technique, not just its general parent. If the excerpt "
    "explicitly cites an ATT&CK "
    "technique id (e.g. \"[T1573]\") next to described adversary activity, "
    "that citation is concrete evidence for the matching candidate, even "
    "when the mention is brief. Give each mapping a confidence score from 0 to "
    "100 reflecting how directly the excerpt shows the activity — higher when "
    "it is explicitly described, lower when only weakly but genuinely indicated"
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
    confidence: int  # 0-100, the model's own confidence; used directly as the cell score
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
    # Third tier: a short quote whose distinctive words (>=4 chars) all appear
    # somewhere in the chunk. Handles the 8b model canonicalizing a described
    # artifact to its standard name — it maps T1003.008 correctly but quotes
    # "/etc/shadow" for a chunk that says "shadow password file" (distinctive
    # token "shadow" is present; "etc" is format noise). Kept narrow — <=3
    # quote tokens — so a long fabricated quote can't slip past on a couple of
    # shared common words; technique_id is already enum-constrained to this
    # chunk's retrieval candidates, which bounds the blast radius further.
    distinctive = [q for q in quote if len(q) >= 4]
    if distinctive and len(quote) <= 3 and all(
        any(_tokens_match(t, q) for t in text) for q in distinctive
    ):
        return True
    return False


# Confidence to assume when a salvaged/truncated verdict lands without a usable
# score. Low-ish: a mapping we couldn't read the model's confidence for should
# not outrank one we could.
SALVAGED_CONFIDENCE = 30

# A mapping the model itself scores below this is a self-declared non-mapping
# and is dropped — observed in a real run: 8 techniques mapped at confidence 0
# off a title-page banner, each with a comment explaining the report was
# synthetic. The rubric's genuine "weak but real" tier sits at ~30, so a floor
# of 10 only removes declared junk.
MIN_CONFIDENCE = 10


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
                        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
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


logger = logging.getLogger(__name__)

# Optional second-pass verification (per-run `verify_mode` on the map
# endpoint, default settings.verify_mode): the verdict stage's residual FPs
# are cousin-substitutions the model is *confident* about — real evidence
# mapped to a merely-adjacent candidate with a reason that restates the
# excerpt instead of justifying the technique ("misconfigured SUID binary"
# mapped to Domain Controller Authentication). Prompt rules against this
# measured as pure regressions (they suppressed marginal true verdicts while
# every confident FP survived), so the fix is a task change: one yes/no
# judgment per accepted mapping, with the technique description in context.
# Measured N=8 (llama3.1:8b, both eval reports, rejections removed):
# unexpected mappings roughly halve; exact recall pays ~1.5 techniques. The
# per-run mode picks what a rejection does: "drop" removes it (strict),
# "demote" keeps it capped at DEMOTED_CONFIDENCE with a marked comment
# (balanced — nothing vanishes, suspected FPs just fall to the faint end of
# the heat scale), "off" skips judging entirely.
VERIFY_SYSTEM_PROMPT = (
    "You audit proposed MITRE ATT&CK technique mappings. Judge whether the "
    "report passage shows the attacker using the specific mechanism the "
    "technique describes — not merely a related topic, the same tactic, or "
    "activity that belongs to a different technique (a scheduled task is not "
    "a system service; abusing a SUID binary is not modifying an "
    "authentication process). Also answer no when the described activity was "
    "performed by defenders or the victim organization rather than the "
    "adversary. Terse but on-point evidence still counts as yes, and so does "
    "evidence naming a specific mechanism, protocol, or tool the technique "
    "or one of its sub-techniques covers — 'Remote Desktop Protocol' shows "
    "the broader Remote Services technique in use."
)

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["yes", "no"]}},
    "required": ["verdict"],
}

VERIFY_MODES = ("off", "demote", "drop")

# Score a judge-rejected mapping is capped at in "demote" mode: below the
# rubric's "low" (30) so flagged cells sort/render as the weakest tier, above
# 0 so they don't read as the score-0 junk cells this pipeline once produced.
DEMOTED_CONFIDENCE = 20


def _evidence_context(evidence: str, chunk: str, radius: int = 220) -> str:
    """The sentence-scale region of the chunk around the evidence quote. The
    judge must see the clause the quote anchors, not the bare fragment: the
    mapper tends to quote 2-4 word anchors ('spearphishing email', 'Kerberos
    service tickets'), and judged in isolation those made it reject
    description-obvious true mappings (measured: T1566.001 went 0/8 on the
    Health report with quote-only verification)."""
    lo_chunk, lo_ev = chunk.lower(), evidence.lower().strip()
    idx = lo_chunk.find(lo_ev)
    if idx < 0:
        # Condensed/canonicalized quote — anchor on its most distinctive token.
        idx = -1
        for token in sorted(_TOKEN_RE.findall(lo_ev), key=len, reverse=True):
            if len(token) >= 5 and (idx := lo_chunk.find(token)) >= 0:
                break
        if idx < 0:
            return evidence
    start = max(0, idx - radius)
    end = min(len(chunk), idx + len(lo_ev) + radius)
    snippet = chunk[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(chunk):
        snippet += "…"
    return snippet


def _verify_prompt(mapping: "ChunkMapping", description: str, context: str) -> str:
    return (
        f"Proposed technique: {mapping.technique_id} ({mapping.technique_name}): "
        f"{description}\n\n"
        "Report passage:\n"
        "---\n"
        f"{context}\n"
        "---\n"
        f'Quoted evidence: "{mapping.evidence}"\n'
        f"Proposed rationale: {mapping.reason}\n\n"
        "Does the passage show the attacker using this specific technique?"
    )


def _verify_mapping(
    mapping: "ChunkMapping", description: str, chunk: str, client: httpx.Client
) -> bool:
    """One tiny constrained yes/no call; errors fail open (mapping kept) so a
    transient Ollama hiccup can't silently eat true mappings."""
    try:
        result = chat_json(
            _verify_prompt(mapping, description, _evidence_context(mapping.evidence, chunk)),
            _VERIFY_SCHEMA,
            client=client,
            system=VERIFY_SYSTEM_PROMPT,
        )
    except Exception:
        logger.warning("verification call failed for %s; keeping mapping", mapping.technique_id)
        return True
    if result.get("verdict") == "no":
        logger.info(
            "verification dropped %s (evidence: %r)", mapping.technique_id, mapping.evidence
        )
        return False
    return True


# Per-candidate ("independent") verdict mode — see settings.verdict_mode.
# Shares the menu prompt's validated rules (conservative, actor-centric,
# mechanism-precision, inline-citation, confidence rubric) minus the
# menu-specific selection language.
INDEPENDENT_SYSTEM_PROMPT = (
    "You are a cybersecurity analyst checking whether an excerpt of a "
    "security report gives concrete evidence of one specific MITRE ATT&CK "
    "technique. The technique applies when the excerpt reports the attacker "
    "actually performing the activity the technique describes — a concrete "
    "action, tool use, or observed artifact. Missing a technique the excerpt "
    "genuinely shows is as wrong as claiming one it does not; judge on the "
    "excerpt's content, not on caution. Judge every statement by who acts: "
    "the same activity is evidence only when the adversary did it, and is "
    "NOT evidence when it describes defenders or the victim organization "
    "detecting, investigating, responding, or advising. Activity that is "
    "merely plausible, thematically related, or belongs to a different "
    "technique does not apply — a scheduled task is not a system service, "
    "and evidence for a sibling technique is not evidence for this one. If "
    "the excerpt explicitly cites this technique's ATT&CK id (e.g. "
    "\"[T1573]\") next to described adversary activity, that citation is "
    "concrete evidence, even when brief. When the technique applies, give a "
    "confidence score from 0 to 100 reflecting how directly the excerpt "
    "shows the activity, a one-sentence reason, and quote the shortest "
    "phrase (at most ~12 words) that evidences it — copied verbatim from "
    "the excerpt itself, never from the technique description. When it does "
    "not apply, return applies=false and nothing else."
)

# "applies" is the only required field so a false verdict can stop decoding
# immediately instead of filling reason/evidence with filler tokens; a true
# verdict missing its evidence is dropped by the standard validation gates.
_INDEPENDENT_SCHEMA = {
    "type": "object",
    "properties": {
        "applies": {"type": "boolean"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string", "maxLength": 300},
        "evidence": {"type": "string", "maxLength": 240},
    },
    "required": ["applies"],
}


def _independent_prompt(chunk_text: str, candidate: TechniqueMatch, description: str) -> str:
    """Chunk first, candidate last: every candidate of a chunk then shares a
    long identical prefix (system prompt + excerpt), which Ollama's per-slot
    prefix cache serves without recomputation (measured: 1328ms cold vs 43ms
    cached prefill) — the whole reason per-candidate calls are affordable."""
    return (
        "Report excerpt:\n"
        "---\n"
        f"{chunk_text}\n"
        "---\n\n"
        "Candidate ATT&CK technique:\n"
        f"{candidate.attack_id} ({candidate.name}): {description}\n\n"
        "Does the excerpt give concrete evidence of the attacker using this "
        "specific technique?"
    )


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
    verify: str | None = None,
    verdict: str | None = None,
) -> list[ChunkMapping]:
    """Run stage 6 for one indexed report: hybrid candidates per chunk, LLM
    verdicts, validated and flattened into ChunkMappings. `verify` picks this
    run's verification mode — "off" | "demote" | "drop"; `verdict` picks the
    verdict architecture — "menu" | "independent" (None = settings defaults
    for both)."""
    verify_run = settings.verify_mode if verify is None else verify
    if verify_run not in VERIFY_MODES:
        raise ValueError(f"verify must be one of {VERIFY_MODES}, got {verify_run!r}")
    verdict_run = settings.verdict_mode if verdict is None else verdict
    if verdict_run not in ("menu", "independent"):
        raise ValueError(f"verdict must be 'menu' or 'independent', got {verdict_run!r}")
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

    def accept(chunk_id: str, tid: str, name: str, m: dict) -> ChunkMapping | None:
        """Shared validation gates for a raw model verdict (either mode):
        evidence-quote grounding, no-evidence confession, confidence floor."""
        if not _evidence_in_chunk(m.get("evidence") or "", chunk_text[chunk_id]):
            return None  # fabricated/paraphrased "quote" — not grounded, drop it
        if NO_EVIDENCE_RE.search(m.get("reason") or ""):
            return None  # the model itself concedes the evidence isn't there
        confidence = m.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = SALVAGED_CONFIDENCE  # salvaged/truncated verdicts may lack it
        confidence = max(0, min(100, int(confidence)))
        if confidence < MIN_CONFIDENCE:
            return None  # the model itself rates this a non-mapping
        return ChunkMapping(
            chunk_id=chunk_id,
            heading_path=chunk_meta[chunk_id].get("heading_path", ""),
            technique_id=tid,
            technique_name=name,
            confidence=confidence,
            evidence=(m.get("evidence") or "").strip()[:300],
            reason=(m.get("reason") or "").strip()[:250],
        )

    def map_one_menu(chunk_id: str, client: httpx.Client) -> list[ChunkMapping]:
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
            mapping = accept(chunk_id, tid, by_id[tid].name, m)
            if mapping is not None:
                accepted.append(mapping)
        return accepted

    def map_one_independent(chunk_id: str, client: httpx.Client) -> list[ChunkMapping]:
        # One small call per candidate, issued sequentially from this thread so
        # the chunk-first prompt keeps one Ollama slot's prefix cache warm
        # (parallelism stays at the chunk level, as in menu mode). No enum
        # constraint is needed — the candidate IS the technique id.
        accepted: list[ChunkMapping] = []
        for candidate in candidates_by_chunk[chunk_id]:
            if should_abort and should_abort():
                raise MappingAborted()
            result = chat_json(
                _independent_prompt(
                    chunk_text[chunk_id], candidate, descriptions.get(candidate.attack_id, "")
                ),
                _INDEPENDENT_SCHEMA,
                client=client,
                system=INDEPENDENT_SYSTEM_PROMPT,
            )
            if not result.get("applies"):
                continue
            mapping = accept(chunk_id, candidate.attack_id, candidate.name, result)
            if mapping is not None:
                accepted.append(mapping)
        return accepted

    def map_one(chunk_id: str, client: httpx.Client) -> list[ChunkMapping]:
        # Checked as each queued chunk's turn comes up, so a cancel takes
        # effect within one verdict's latency instead of after the whole queue.
        if should_abort and should_abort():
            raise MappingAborted()
        if verdict_run == "independent":
            return map_one_independent(chunk_id, client)
        return map_one_menu(chunk_id, client)

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

        result = [m for cid in ordered for m in by_chunk.get(cid, [])]

        # Verification runs as its own phase AFTER every verdict has landed,
        # not interleaved per chunk, for two measured reasons: (a) verify
        # calls landing mid-verdict-stage evict the verdict prompt's cached
        # prefix from Ollama's slots (all slots are verdict-warm while the
        # pool is busy — the server routes by best prefix match, but only
        # among free capacity), and (b) interleaving changes decode batch
        # composition, which measurably perturbs the verdicts themselves
        # (the nondeterminism mechanism; solid techniques flipped 8/8→0/8
        # when extra calls ran alongside the verdict stage).
        if verify_run != "off" and result:
            if should_abort and should_abort():
                raise MappingAborted()

            def verify_one(m: ChunkMapping) -> ChunkMapping | None:
                if _verify_mapping(
                    m, descriptions.get(m.technique_id, ""), chunk_text[m.chunk_id], client
                ):
                    return m
                if verify_run == "demote":
                    m.confidence = min(m.confidence, DEMOTED_CONFIDENCE)
                    m.reason = f"[flagged by verification] {m.reason}"
                    return m
                return None

            with ThreadPoolExecutor(max_workers=resolve_map_workers()) as verify_pool:
                verified = list(verify_pool.map(verify_one, result))
            result = [m for m in verified if m is not None]
    return result
