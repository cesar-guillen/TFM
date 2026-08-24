"""Re-ingest the labelled eval reports under the CURRENT branch's ingest code
and record their report ids in /data/eval_reports.json.

Why this exists: sentence/clause windowing is applied at INDEX time, so a
report indexed under a different branch's app/ingest/sentences.py carries
windows the current code would not produce — reusing such a report id silently
measures a retrieval stage that does not exist on this branch. Run this once
after switching branches or changing anything under app/ingest/, then let the
grader/tuner agents reuse the recorded ids with --report-id.

    docker compose exec -T backend python /data/eval_reindex.py [report ...]
"""

import json
import os
import sys
import uuid

from app.eval.ground_truth import REPORTS
from app.eval.run_eval import _find_pdf
from app.ingest.indexing import index_report
from app.ingest.pdf_to_markdown import pdf_to_markdown

OUT = "/data/eval_reports.json"
DEFAULT = ["meridian-health", "meridian-grove", "openslop"]

wanted = sys.argv[1:] or DEFAULT
existing = json.load(open(OUT)) if os.path.exists(OUT) else {}

for name in wanted:
    gt = REPORTS[name]
    pdf = _find_pdf(gt.pdf_glob)
    if not pdf:
        print(f"!! {name}: no PDF matching {gt.pdf_glob}")
        continue
    report_id = str(uuid.uuid4())
    chunks, skipped = index_report(report_id, os.path.basename(pdf), pdf_to_markdown(pdf))
    existing[name] = report_id
    print(f"{name:<16} {report_id}  {len(chunks)} chunks indexed, {skipped} filtered  ({os.path.basename(pdf)})")

json.dump(existing, open(OUT, "w"), indent=2)
print(f"\nwrote {OUT}")
