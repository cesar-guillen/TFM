"""Aggregation: collapse per-chunk mappings into one Navigator layer.

A technique mapped by several chunks keeps its *highest* confidence as the cell
score (evidence strength, not volume) and every distinct piece of evidence in
the cell comment, so the matrix carries the full traceability chain.
"""

import re
from collections import defaultdict

from app.mapping.mapper import ChunkMapping

_QUOTE_TOKENS = re.compile(r"[a-z0-9]+")


def _norm_quote(evidence: str) -> str:
    """Alphanumeric-token key for collapsing the same quote as captured by
    overlapping chunks — a chunk boundary often adds or drops a trailing
    period, so punctuation and case must be ignored, not just whitespace."""
    return " ".join(_QUOTE_TOKENS.findall(evidence.lower()))


def _evidence_line(m: ChunkMapping) -> str:
    """Justification first, then the verbatim quote grounding it. The score is
    carried by the cell, not repeated here."""
    return f'{m.reason} — "{m.evidence}"' if m.reason else f'"{m.evidence}"'


def _comment(hits: list[ChunkMapping]) -> str:
    """One line per distinct piece of evidence, strongest first — so the top
    line always justifies the cell's score."""
    lines = []
    seen: set[str] = set()
    for hit in sorted(hits, key=lambda h: -h.confidence):
        key = _norm_quote(hit.evidence)
        if key in seen:
            continue
        seen.add(key)
        lines.append(_evidence_line(hit))
    return "\n".join(lines)


def aggregate_mappings(mappings: list[ChunkMapping], attack_version: str = "19") -> dict:
    """Collapse chunk-level mappings into a Navigator layer-JSON dict — the
    same shape the frontend's import/export and GET /api/matrix use."""
    by_technique: dict[str, list[ChunkMapping]] = defaultdict(list)
    for m in mappings:
        by_technique[m.technique_id].append(m)

    techniques = []
    for technique_id, hits in sorted(by_technique.items()):
        entry = {
            "techniqueID": technique_id,
            "score": max(h.confidence for h in hits),
            "comment": _comment(hits),
            "enabled": True,
        }
        # Carried as standard Navigator metadata rather than a marker in the
        # comment, so it round-trips through save/export and the frontend can
        # render it as an outlined cell. Set when *any* supporting instance was
        # demoted, even if a stronger one set the score.
        if any(h.flagged for h in hits):
            entry["metadata"] = [{"name": "flagged", "value": "true"}]
        techniques.append(entry)

    # Promote parents of mapped sub-techniques that weren't mapped themselves:
    # the matrix collapses sub-techniques by default, so an unhighlighted
    # parent would hide them entirely. The parent scores as the average of its
    # subs, so it reflects the family's evidence and never outranks its best
    # sub (which matters in demote mode, where flagged subs are capped low).
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
