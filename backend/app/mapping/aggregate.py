"""Aggregation (pipeline stage 7): dedupe per-chunk mappings into one Navigator
layer. A technique mapped by several chunks keeps its *highest* confidence as
the score (evidence strength, not evidence volume — three weak mentions don't
make a strong one) and every chunk's evidence line in the comment, so the
matrix cell itself carries the full traceability chain. The score is the
model's own 0-100 confidence (see mapper.ChunkMapping); 0 is reserved for
"not mapped"."""

from collections import defaultdict

from app.mapping.mapper import ChunkMapping

# Score for a parent technique that wasn't mapped itself but has a mapped
# sub-technique: the matrix collapses sub-techniques by default, so without
# highlighting the parent the user could miss the flagged sub entirely. A
# neutral mid-scale value — visible, but not outranking direct high-confidence
# evidence.
PARENT_OF_MAPPED_SUB_SCORE = 50


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
    # The synthetic score never exceeds the best sub's own score — a parent
    # whose only evidence is verification-demoted subs must not outrank them.
    mapped = set(by_technique)
    for parent_id in sorted({tid.split(".")[0] for tid in mapped if "." in tid} - mapped):
        subs = sorted(tid for tid in mapped if tid.startswith(parent_id + "."))
        listing = "\n".join(
            f"{i}. {by_technique[sub_id][0].technique_name} ({sub_id})"
            for i, sub_id in enumerate(subs, 1)
        )
        best_sub = max(h.confidence for sub_id in subs for h in by_technique[sub_id])
        techniques.append(
            {
                "techniqueID": parent_id,
                "score": min(PARENT_OF_MAPPED_SUB_SCORE, best_sub),
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
