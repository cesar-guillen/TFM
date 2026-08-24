"""Dump raw mappings for the grader agent: one mapping pass per labelled
report under the config being measured, printed as technique | score | section
| quote, alongside the ground-truth verdict for each (core / acceptable /
unexpected). This is the qualitative half of grading — the harness gives the
numbers, this gives the evidence behind them.

Config here MUST match the grader's measurement command (grouped/menu mode,
top_k from settings, verify off) or the taxonomy describes a pipeline nobody
is measuring.

Run inside the backend container:
    docker compose exec -T -e PYTHONPATH=/app backend python /data/autoloop_dump.py [report ...]
"""

import json
import os
import sys

from app.core.config import settings
from app.eval.ground_truth import REPORTS
from app.mapping.aggregate import aggregate_mappings
from app.mapping.mapper import map_report

IDS_FILE = "/data/eval_reports.json"
DEFAULT = ["meridian-health", "meridian-grove", "openslop"]

# The measured configuration: grouped (menu) verdicts, one call per chunk with
# all candidates offered at once — the shipped default on main.
VERDICT = "menu"
VERIFY = settings.verify_mode
TOP_K = settings.map_candidates

if not os.path.exists(IDS_FILE):
    raise SystemExit(f"{IDS_FILE} missing — run /data/eval_reindex.py first")
ids = json.load(open(IDS_FILE))
targets = sys.argv[1:] or DEFAULT


def parent(t: str) -> str:
    return t.split(".")[0]


print(f"config: verdict={VERDICT}  verify={VERIFY}  top_k={TOP_K}  model={settings.ollama_model}")

for name in targets:
    gt = REPORTS[name]
    rid = ids[name]
    core, acceptable = gt.core, gt.acceptable
    universe = set(core) | set(acceptable)
    universe |= {parent(t) for t in universe}

    mappings = map_report(rid, verify=VERIFY, verdict=VERDICT, top_k=TOP_K)
    layer = aggregate_mappings(mappings)
    scored = {t["techniqueID"]: t["score"] for t in layer["techniques"]}

    print(f"\n{'=' * 78}\nREPORT: {gt.name}  ({len(scored)} techniques in final layer)\n{'=' * 78}")

    quotes: dict[str, list[str]] = {}
    sections: dict[str, set[str]] = {}
    for m in mappings:
        quotes.setdefault(m.technique_id, []).append(m.evidence)
        sections.setdefault(m.technique_id, set()).add(m.heading_path or "?")

    print("\n-- MAPPED (verdict | id | score | section | evidence quotes) --")
    for tid in sorted(scored, key=lambda t: -scored[t]):
        if tid in core:
            verdict = "CORE-HIT"
        elif tid in acceptable:
            verdict = "acceptable"
        elif tid in universe:
            verdict = "parent-of-expected"
        else:
            verdict = "UNEXPECTED-FP"
        secs = "; ".join(sorted(sections.get(tid, {"(promoted parent)"})))[:70]
        qs = " || ".join(dict.fromkeys(quotes.get(tid, [])))[:170]
        print(f"{verdict:<19} {tid:<11} {scored[tid]:>3}  [{secs}]  {qs}")

    missed = [t for t in core if t not in scored and parent(t) not in scored]
    print(f"\n-- MISSED CORE ({len(missed)}/{len(core)}) --")
    for t in missed:
        print(f"  {t:<11} {core[t]}")
