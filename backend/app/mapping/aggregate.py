"""Aggregation (pipeline stage 7): dedupe per-chunk mappings into one Navigator
layer. A technique mapped by several chunks keeps its *highest* confidence as
the score (evidence strength, not evidence volume — three weak mentions don't
make a strong one) and every chunk's evidence line in the comment, so the
matrix cell itself carries the full traceability chain."""

from collections import defaultdict

from app.mapping.mapper import ChunkMapping

# Confidence -> Navigator score. Spread wide so the heat ramp visibly separates
# the tiers; 0 is reserved for "not mapped".
CONFIDENCE_SCORES = {"high": 90, "medium": 60, "low": 30}

# Score for a parent technique that wasn't mapped itself but has a mapped
# sub-technique: the matrix collapses sub-techniques by default, so without
# highlighting the parent the user could miss the flagged sub entirely.
# Between "low" and "medium" — visible, but not outranking direct evidence.
PARENT_OF_MAPPED_SUB_SCORE = 50


def _evidence_line(m: ChunkMapping) -> str:
    """Justification first ("why flagged"), then the verbatim quote that
    grounds it (see mapper._evidence_in_chunk)."""
    line = f"[{m.confidence}]"
    if m.reason:
        line += f" {m.reason}"
    return f'{line} — "{m.evidence}"'


def aggregate_mappings(mappings: list[ChunkMapping], attack_version: str = "19") -> dict:
    """Collapse chunk-level mappings into a Navigator layer-JSON dict (the same
    shape the frontend's import/export and /api/matrix use)."""
    by_technique: dict[str, list[ChunkMapping]] = defaultdict(list)
    for m in mappings:
        by_technique[m.technique_id].append(m)

    techniques = []
    for technique_id, hits in sorted(by_technique.items()):
        best = max(CONFIDENCE_SCORES.get(h.confidence, 0) for h in hits)
        comment = "\n".join(_evidence_line(h) for h in hits)
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
        techniques.append(
            {
                "techniqueID": parent_id,
                "score": PARENT_OF_MAPPED_SUB_SCORE,
                "comment": (
                    "Not mapped directly — highlighted because sub-technique"
                    f"{'s' if len(subs) > 1 else ''} {', '.join(subs)} matched; "
                    "expand to see the evidence."
                ),
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
