"""LLM mapping: decide, per chunk, which retrieval candidates the chunk text
actually evidences.

Three layers keep the output grounded:
- the model only ever sees candidates hybrid retrieval produced for that chunk,
  and the JSON schema constrains technique_id to an enum of those ids, so it
  cannot name a technique it was not offered;
- every mapping must quote its evidence, and the quote is validated against the
  chunk text (see _evidence_in_chunk) — a fabricated or paraphrased quote is
  dropped, which is what keeps the free-text reason honest;
- an optional verification pass re-judges each accepted mapping on its own.

Every accepted mapping carries its quote plus the chunk's id and heading
breadcrumb, preserving the technique -> chunk -> char span traceability chain.
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
from app.retrieval.retrieve import ATTACK_ID_RE, TechniqueMatch, search_techniques_for_report

# Confidence wording shared by both menu-mode prompts. An anchored "spread the
# scores" rubric was tried and reverted: it spread the scores as intended but
# cost recall.
_CONFIDENCE_LINE = (
    "Give each mapping a confidence score from 0 to "
    "100 reflecting how directly the excerpt shows the activity — higher when "
    "it is explicitly described, lower when only weakly but genuinely indicated"
)

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
    "when the mention is brief. " + _CONFIDENCE_LINE
)

# Pentest variant: the same rules with the actor recast — the testers play the
# adversary, and findings merely identified but not exploited are the pentest
# analogue of the incident prompt's defender-activity exclusion.
PENTEST_SYSTEM_PROMPT = (
    "You are a cybersecurity analyst mapping excerpts of a penetration-test "
    "or red-team report to MITRE ATT&CK techniques. The testers play the "
    "adversary. Be conservative: map a candidate technique only when the "
    "excerpt reports the testers actually performing the activity the "
    "technique describes — a concrete action, tool use, or demonstrated "
    "result, whether narrated in the first person (\"we\", \"the "
    "consultant\", \"the assessment team\") or attributed to the testers. "
    "Vulnerabilities that were only identified or scanned, and attacks "
    "described as possible but not carried out, are NOT evidence — only "
    "what was actually executed or exploited counts. Pentest reports "
    "narrate real actions cautiously for safety: a session, credential, or "
    "ticket the testers actually obtained, cracked, relayed, or reused is "
    "something they carried out even when called \"controlled\", "
    "\"non-disruptive\", or merely \"confirmed\" — that wording limits "
    "impact, it does not mean the action was skipped. Only a finding the "
    "testers checked WITHOUT ever using it (confirmed solely by version, "
    "configuration, or banner review, with no session or credential "
    "actually obtained) stays non-evidence. Activity by the client's staff "
    "or defenders, and remediation, hardening, or recommendation text, is "
    "NOT evidence either. Do not map techniques that are merely plausible "
    "or thematically related. Consider each candidate independently: an "
    "excerpt often evidences several distinct techniques at once, so map "
    "every candidate the excerpt genuinely supports, not only the most "
    "prominent one. When the excerpt names the specific mechanism a "
    "sub-technique describes (a named protocol like SSH or RDP, a named "
    "file like /etc/shadow, a named tool or method), map that precise "
    "sub-technique, not just its general parent. If the excerpt explicitly "
    "cites an ATT&CK technique id (e.g. \"[T1059.001]\") anywhere near "
    "described tester activity, treat that citation as concrete evidence "
    "for the matching candidate on its own, even when the surrounding text "
    "is brief or hedged — the report's own author already made that "
    "attribution. " + _CONFIDENCE_LINE
)

REPORT_TYPES = ("incident", "pentest")

# (chunks_mapped, chunk_count, report-ordered mappings so far), after every
# chunk — lets the caller publish a live partial matrix.
ProgressCallback = Callable[[int, int, list["ChunkMapping"]], None]

# Fired when a named post-verdict phase starts, so the job registry can surface
# it as its own status instead of it running invisibly inside "mapping".
PhaseCallback = Callable[[str], None]

# Polled before each chunk's LLM call; True aborts the run (user cancelled).
AbortCheck = Callable[[], bool]


# A mapping whose own reason concedes the excerpt lacks the evidence ("the
# excerpt does not explicitly mention..."), which small models emit as
# low-confidence hedges despite the prompt forbidding plausibility mappings.
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
    confidence: int  # 0-100, the model's own; used directly as the cell score
    evidence: str
    reason: str = ""  # the model's one-sentence justification
    # Set when the verification pass rejects this mapping in "demote" mode.
    # Structured state rather than a prefix on `reason`, so aggregation can
    # surface it as layer metadata without polluting the evidence comment.
    flagged: bool = False


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Max tokens allowed between consecutive quote tokens. Wide enough to absorb
# condensed parentheticals and inline citations, tight enough that the quote
# must still trace one local region — tokens scattered across the chunk (a
# fabricated quote) stay rejected.
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
    """Whether the quote actually occurs in the excerpt — the gate that catches
    a model quoting a candidate's description instead of the report.

    Three tiers, because models legitimately condense a quote even at
    temperature 0: exact (whitespace- and case-insensitive) containment, then a
    gap-bounded token subsequence, then a single-window check for very short
    quotes. Locality is the load-bearing property throughout."""
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
    # Third tier: a very short quote whose distinctive words all co-occur
    # inside one window. Handles a model canonicalizing an artifact to its
    # standard name ("/etc/shadow" for "shadow password file"). Deliberately
    # narrow — at most 3 tokens, and they must share a window — so a longer
    # fabricated quote cannot slip past on a few common words.
    distinctive = [q for q in quote if len(q) >= 4]
    if distinctive and len(quote) <= 3 and all(
        any(_tokens_match(t, q) for t in text) for q in distinctive
    ):
        return True
    return False


# Assumed when a salvaged (truncated) verdict lands without a usable score: a
# mapping whose confidence we could not read must not outrank one we could.
SALVAGED_CONFIDENCE = 30

# Below this the model has declared its own mapping a non-mapping. The genuine
# "weak but real" tier sits around 30, so this floor only removes junk.
MIN_CONFIDENCE = 10


def _response_schema(candidate_ids: list[str]) -> dict:
    """Schema for one chunk's verdict. technique_id is an enum of this chunk's
    candidates, so the constrained decoder cannot invent an id; the size bounds
    keep a rambling model from decoding into the num_predict cap, which would
    truncate the JSON and cost the verdict its tail mappings."""
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
    """KB documents are a name and description; keep a word-safe prefix of the
    description, enough to disambiguate without blowing up the prompt."""
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

# Verification judge. The verdict stage's residual false positives are
# cousin-substitutions the model is *confident* about — real evidence mapped to
# a merely-adjacent candidate — and prompt rules against them measured as pure
# regressions. So the fix is a change of task instead: one yes/no judgment per
# accepted mapping, with the technique's own description in context.
VERIFY_SYSTEM_PROMPT = (
    "You audit proposed MITRE ATT&CK technique mappings. Judge whether the "
    "report passage shows the attacker using the specific mechanism the "
    "technique describes — not merely a related topic, the same tactic, or "
    "activity that belongs to a different technique (a scheduled task is not "
    "a system service; abusing a SUID binary is not modifying an "
    "authentication process). Also answer no when the described activity was "
    "performed by defenders or the victim organization rather than the "
    "adversary. Terse but on-point evidence still counts as yes, and so does "
    "evidence naming a specific mechanism, protocol, tool, artifact or command "
    "that the technique or one of its sub-techniques covers, even when the "
    "passage never uses the technique's own words: 'Remote Desktop Protocol' "
    "shows the broader Remote Services technique in use, and deleting volume "
    "shadow copies or corrupting a backup catalog shows system recovery being "
    "inhibited."
)

# Pentest variant of the judge: same specificity rules, actor recast, and
# "identified but not exploited" joins the answer-no list.
PENTEST_VERIFY_SYSTEM_PROMPT = (
    "You audit proposed MITRE ATT&CK technique mappings from a "
    "penetration-test or red-team report, where the testers play the "
    "adversary. Judge whether the report passage shows the testers using "
    "the specific mechanism the technique describes — not merely a related "
    "topic, the same tactic, or activity that belongs to a different "
    "technique (a scheduled task is not a system service; abusing a SUID "
    "binary is not modifying an authentication process). Pentest reports "
    "narrate real actions cautiously for safety: a session, credential, or "
    "ticket the testers actually obtained, cracked, relayed, or reused "
    "still counts as yes even when called \"controlled\", "
    "\"non-disruptive\", or merely \"confirmed\" — that wording limits "
    "impact, it does not mean the action was skipped. Answer no only when "
    "the passage identifies a vulnerability WITHOUT the testers ever using "
    "it (confirmed solely by version, configuration, or banner review, no "
    "session or credential actually obtained), or when it describes the "
    "client's staff or defenders acting rather than the testers. Terse but "
    "on-point evidence still counts as yes, and so does evidence naming a "
    "specific mechanism, protocol, or tool the technique or one of its "
    "sub-techniques covers — 'Remote Desktop Protocol' shows the broader "
    "Remote Services technique in use."
)

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": ["yes", "no"]}},
    "required": ["verdict"],
}

VERIFY_MODES = ("off", "demote", "drop")

# Score a rejected mapping is capped at in "demote" mode: below the "low" tier
# so flagged cells render faintest, above 0 so they don't read as junk.
DEMOTED_CONFIDENCE = 20


def _evidence_context(evidence: str, chunk: str, radius: int = 220) -> str:
    """The sentence-scale region of the chunk around the evidence quote. The
    judge must see the clause the quote anchors, not the bare fragment: the
    mapper tends to quote 2-4 word anchors, and judged in isolation those made
    it reject obviously-correct mappings."""
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


def _verify_prompt(
    mapping: "ChunkMapping", description: str, context: str, actor: str
) -> str:
    return (
        f"Proposed technique: {mapping.technique_id} ({mapping.technique_name}): "
        f"{description}\n\n"
        "Report passage:\n"
        "---\n"
        f"{context}\n"
        "---\n"
        f'Quoted evidence: "{mapping.evidence}"\n'
        f"Proposed rationale: {mapping.reason}\n\n"
        f"Does the passage show {actor} using this specific technique?"
    )


def _verify_mapping(
    mapping: "ChunkMapping",
    description: str,
    chunk: str,
    client: httpx.Client,
    system: str = VERIFY_SYSTEM_PROMPT,
    actor: str = "the attacker",
) -> bool:
    """One tiny constrained yes/no call; errors fail open (mapping kept) so a
    transient Ollama hiccup can't silently eat true mappings."""
    try:
        result = chat_json(
            _verify_prompt(mapping, description, _evidence_context(mapping.evidence, chunk), actor),
            _VERIFY_SCHEMA,
            client=client,
            system=system,
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


# Per-candidate ("independent") verdict mode — see settings.verdict_mode. The
# menu prompt's rules minus its selection language.
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

# Pentest variant of the independent-mode prompt.
PENTEST_INDEPENDENT_SYSTEM_PROMPT = (
    "You are a cybersecurity analyst checking whether an excerpt of a "
    "penetration-test or red-team report gives concrete evidence of one "
    "specific MITRE ATT&CK technique, given below as an id and name (e.g. "
    "\"T1210\"). First check one thing: does this exact id appear anywhere "
    "in the excerpt (in running text or in a findings-table line like "
    "\"ATT&CK: T1557.001, T1210\")? If it does, answer applies=true for "
    "that reason alone and quote the id itself as evidence — the report's "
    "own author already made this attribution, next to their own "
    "description of what the testers did, and it is not your job to "
    "second-guess it, even if the surrounding narrative reads as brief, "
    "hedged, or focused on a different technique. Only when the id is "
    "absent, decide from the narrative: the testers play the adversary, so "
    "the technique applies when the excerpt reports the testers actually "
    "performing the activity it describes — a concrete action, tool use, or "
    "demonstrated result, whether narrated in the first person (\"we\", "
    "\"the consultant\") or attributed to the testers. Missing a technique "
    "the excerpt genuinely shows is as wrong as claiming one it does not; "
    "judge on the excerpt's content, not on caution. Pentest reports "
    "narrate real actions cautiously for safety: a session, credential, or "
    "ticket the testers actually obtained, cracked, relayed, or reused is "
    "something they carried out even when called \"controlled\", "
    "\"non-disruptive\", or merely \"confirmed\" — that wording limits "
    "impact, it does not mean the action was skipped. Only a finding the "
    "testers checked WITHOUT ever using it (confirmed solely by version, "
    "configuration, or banner review, with no session or credential "
    "actually obtained) is NOT evidence, and neither is activity by the "
    "client's staff or defenders, or remediation/recommendation text. "
    "Activity that is merely plausible, thematically related, or belongs "
    "to a different technique does not apply — a scheduled task is not a "
    "system service, and evidence for a sibling technique is not evidence "
    "for this one. When the technique applies, give a confidence score "
    "from 0 to 100 reflecting how directly the excerpt shows the activity, "
    "a one-sentence reason, and quote the shortest phrase (at most ~12 "
    "words) that evidences it — copied verbatim from the excerpt itself, "
    "never from the technique description (the id itself counts as a "
    "verbatim quote when it is your reason for applying). When it does not "
    "apply, return applies=false and nothing else."
)

# "applies" is the only required field, so a false verdict stops decoding
# immediately instead of filling the other fields with filler tokens; a true
# verdict missing its evidence is dropped by the standard gates.
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
    """Chunk first, candidate last: every candidate of a chunk then shares one
    long identical prefix, which Ollama's per-slot prefix cache serves without
    recomputing it. That is what makes per-candidate calls affordable."""
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


@dataclass(frozen=True)
class _Prompts:
    """The prompt family a run uses. The pentest variants recast the actor —
    the testers play the adversary, and findings merely identified are not
    evidence — and everything downstream of the prompts is identical."""

    menu: str
    independent: str
    verify: str
    verify_actor: str


def _prompts_for(report_type: str) -> _Prompts:
    if report_type == "pentest":
        return _Prompts(
            menu=PENTEST_SYSTEM_PROMPT,
            independent=PENTEST_INDEPENDENT_SYSTEM_PROMPT,
            verify=PENTEST_VERIFY_SYSTEM_PROMPT,
            verify_actor="the testers",
        )
    return _Prompts(
        menu=SYSTEM_PROMPT,
        independent=INDEPENDENT_SYSTEM_PROMPT,
        verify=VERIFY_SYSTEM_PROMPT,
        verify_actor="the attacker",
    )


def _run_verification(
    mappings: list[ChunkMapping],
    mode: str,
    descriptions: dict[str, str],
    chunk_text: dict[str, str],
    client: httpx.Client,
    prompts: _Prompts,
) -> list[ChunkMapping]:
    """Judge every accepted mapping once, then drop or demote the rejects.

    Runs as its own phase after all verdicts have landed rather than
    interleaved per chunk, for two measured reasons: judge calls landing
    mid-verdict evict the verdict prompt's cached prefix from Ollama's slots,
    and they change decode batch composition, which perturbs the verdicts
    themselves.
    """

    def judge(m: ChunkMapping) -> ChunkMapping | None:
        # A passage that cites this exact id inline (`[T1685.005]`) is the
        # strongest evidence class this pipeline recognizes elsewhere —
        # EXPLICIT_IDS injection in retrieve.py seats a cited id above any
        # retrieval score for exactly this reason — but the verification
        # judge doesn't know that and can reject it anyway. Skip judging when
        # the source chunk literally cites this mapping's own id, scanning
        # the chunk text (not the model's evidence quote) so this doesn't
        # depend on quoting behavior, same source EXPLICIT_IDS itself reads.
        cited_ids = {mm.group(0).upper() for mm in ATTACK_ID_RE.finditer(chunk_text[m.chunk_id])}
        if m.technique_id.upper() in cited_ids:
            return m
        if _verify_mapping(
            m,
            descriptions.get(m.technique_id, ""),
            chunk_text[m.chunk_id],
            client,
            system=prompts.verify,
            actor=prompts.verify_actor,
        ):
            return m
        if mode == "demote":
            m.confidence = min(m.confidence, DEMOTED_CONFIDENCE)
            m.flagged = True
            return m
        return None

    with ThreadPoolExecutor(max_workers=resolve_map_workers()) as pool:
        judged = list(pool.map(judge, mappings))
    return [m for m in judged if m is not None]


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
    on_phase: PhaseCallback | None = None,
    verify: str | None = None,
    verdict: str | None = None,
    report_type: str | None = None,
    top_k: int | None = None,
) -> list[ChunkMapping]:
    """Map one indexed report: hybrid candidates per chunk, LLM verdicts,
    validated and flattened into ChunkMappings.

    `verify`, `verdict`, `report_type` and `top_k` override the corresponding
    settings for this run only; None keeps the configured default.
    `on_phase` fires when a named post-verdict phase starts, so a caller can
    surface it as its own job status."""
    verify_run = settings.verify_mode if verify is None else verify
    if verify_run not in VERIFY_MODES:
        raise ValueError(f"verify must be one of {VERIFY_MODES}, got {verify_run!r}")
    verdict_run = settings.verdict_mode if verdict is None else verdict
    if verdict_run not in ("menu", "independent"):
        raise ValueError(f"verdict must be 'menu' or 'independent', got {verdict_run!r}")
    report_type_run = settings.report_type if report_type is None else report_type
    if report_type_run not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}, got {report_type_run!r}")
    prompts = _prompts_for(report_type_run)
    top_k_run = settings.map_candidates if top_k is None else top_k
    candidates_by_chunk = search_techniques_for_report(report_id, top_k_per_chunk=top_k_run)
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
            system=prompts.menu,
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
        # the chunk-first prompt keeps one Ollama slot's prefix cache warm;
        # parallelism stays at the chunk level, as in menu mode. No enum
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
                system=prompts.independent,
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

    # Chunks are submitted strongest-retrieval-first, so the live matrix shows
    # the report's substance within the first few verdicts and a user on CPU
    # can cancel once satisfied. Progress snapshots and the final result are
    # re-assembled in report order, so the evidence reads against the document.
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
                # on — each can block for the full LLM timeout — before the
                # error reaches the job.
                pool.shutdown(wait=False, cancel_futures=True)
                raise

        result = [m for cid in ordered for m in by_chunk.get(cid, [])]

        if verify_run != "off" and result:
            if should_abort and should_abort():
                raise MappingAborted()
            if on_phase:
                on_phase("filtering")
            result = _run_verification(
                result, verify_run, descriptions, chunk_text, client, prompts
            )
    return result
