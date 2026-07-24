"""Aggregation (pipeline stage 7): dedupe per-chunk mappings into one Navigator
layer. A technique mapped by several chunks keeps its *highest* confidence as
the score (evidence strength, not evidence volume — three weak mentions don't
make a strong one) and every chunk's evidence line in the comment, so the
matrix cell itself carries the full traceability chain. The score is the
model's own 0-100 confidence (see mapper.ChunkMapping); 0 is reserved for
"not mapped"."""

import re
from collections import defaultdict

from app.mapping.mapper import ChunkMapping

_QUOTE_TOKENS = re.compile(r"[a-z0-9]+")

# A parent technique that wasn't mapped itself but has mapped sub-techniques
# gets a synthetic entry (the matrix collapses sub-techniques by default, so
# without highlighting the parent the user could miss the flagged subs
# entirely) scored as the *average* of its subs' scores — the parent reflects
# the family's overall evidence strength, and can never outrank its own best
# sub (relevant in demote mode, where flagged subs are capped low).


def _norm_quote(evidence: str) -> str:
    """Alphanumeric-token key for collapsing the same quote captured by
    overlapping chunks. Punctuation and case are dropped, not just whitespace:
    a chunk boundary often includes/excludes a trailing period or capital, so
    "…svc-sql account" and "…svc-sql account." are the same evidence and must
    dedup to one line."""
    return " ".join(_QUOTE_TOKENS.findall(evidence.lower()))


def _evidence_line(m: ChunkMapping) -> str:
    """Justification first ("why flagged"), then the verbatim quote that
    grounds it (see mapper._evidence_in_chunk). The score is carried by the
    cell, not repeated here."""
    return f'{m.reason} — "{m.evidence}"' if m.reason else f'"{m.evidence}"'


def aggregate_mappings(mappings: list[ChunkMapping], attack_version: str = "19") -> dict:
    """Collapse chunk-level mappings into a Navigator layer-JSON dict (the same
    shape the frontend's import/export and /api/matrix use)."""
    by_technique: dict[str, list[ChunkMapping]] = defaultdict(list)
    for m in mappings:
        by_technique[m.technique_id].append(m)

    techniques = []
    for technique_id, hits in sorted(by_technique.items()):
        best = max(h.confidence for h in hits)
        # Strongest evidence first, so the top comment line is always the one
        # that justifies the cell's score (in report order a technique mapped
        # by a strong chunk could otherwise lead with a weaker/misattributed
        # instance — "right technique, wrong comment"). Deduped by evidence
        # quote, not full line: overlapping chunks capture the same sentence
        # with slightly different reasons, which stacked as near-duplicate
        # lines. One clean line per distinct quote, no score-tag prefix (the
        # cell already shows the score). Stable sort keeps report order within
        # equal confidences.
        deduped: list[ChunkMapping] = []
        seen: set[str] = set()
        for h in sorted(hits, key=lambda h: -h.confidence):
            key = _norm_quote(h.evidence)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)
        comment = "\n".join(_evidence_line(h) for h in deduped)
        techniques.append(
            {
                "techniqueID": technique_id,
                "score": best,
                "comment": comment,
                "enabled": True,
            }
        )

    # Promote parents of mapped sub-techniques that weren't mapped themselves.
    mapped = set(by_technique)
    for parent_id in sorted({tid.split(".")[0] for tid in mapped if "." in tid} - mapped):
        subs = sorted(tid for tid in mapped if tid.startswith(parent_id + "."))
        listing = "\n".join(
            f"{i}. {by_technique[sub_id][0].technique_name} ({sub_id})"
            for i, sub_id in enumerate(subs, 1)
        )
        sub_scores = [max(h.confidence for h in by_technique[sub_id]) for sub_id in subs]
        techniques.append(
            {
                "techniqueID": parent_id,
                "score": round(sum(sub_scores) / len(sub_scores)),
                "comment": f"Identified subtechniques:\n{listing}",
                "enabled": True,
            }
        )

    return {
        "name": "TFM generated layer",
        "versions": {"attack": attack_version, "navigator": "5.1.0", "layer": "4.5"},
        "domain": "enterprise-attack",
        "description": "Techniques mapped from the ingested report by the local LLM pipeline",
        "techniques": techniques,
    }
