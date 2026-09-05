"""Batch-map the DFIR Report PDFs in /data/dfir_reports under the shipped
"Balanced + Grouped" configuration, and dump the results as CSV for
comparison against each report's own published ATT&CK table.

Config: verdict=menu (Grouped), verify=demote (Balanced), report_type=incident,
top_k from settings — i.e. exactly what the UI's default upload options run.
Each report's own published ATT&CK table is stripped before ingest.

Writes to /data/dfir_out:
  <stem>.techniques.csv   one row per technique in the final layer  <- compare
  <stem>.mappings.csv     one row per evidence instance (adjudication detail)
  all_techniques.csv      every report concatenated
  manifest.json           report ids, chunk counts, timings, config

Resumable: a report whose .techniques.csv already exists is skipped, so an
interrupted run continues where it stopped.

    docker compose exec -T -e PYTHONPATH=/app backend \
        python /data/dfir_batch.py [--only substring] [--redo]
"""

import csv
import glob
import json
import os
import sys
import time
import traceback
import uuid

from app.core.config import settings
from app.mapping.aggregate import aggregate_mappings
from app.mapping.mapper import map_report
from app.ingest.indexing import index_report
from app.eval.deleak import deleak_markdown
from app.ingest.pdf_to_markdown import pdf_to_markdown

SRC = "/data/dfir_reports"
OUT = "/data/dfir_out"

VERDICT = "menu"       # "Grouped"
VERIFY = "demote"      # "Balanced"
REPORT_TYPE = "incident"
TOP_K = settings.map_candidates

only = None
redo = "--redo" in sys.argv
if "--only" in sys.argv:
    only = sys.argv[sys.argv.index("--only") + 1]

os.makedirs(OUT, exist_ok=True)
pdfs = sorted(glob.glob(os.path.join(SRC, "*.pdf")))
if only:
    pdfs = [p for p in pdfs if only.lower() in os.path.basename(p).lower()]
if not pdfs:
    raise SystemExit(f"no PDFs matched under {SRC}")

manifest_path = os.path.join(OUT, "manifest.json")
manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
manifest.setdefault("config", {})
manifest["config"] = {
    "verdict_mode": VERDICT,
    "verify_mode": VERIFY,
    "report_type": REPORT_TYPE,
    "top_k": TOP_K,
    "model": settings.ollama_model,
    "embed_model": settings.ollama_embed_model,
}
manifest.setdefault("reports", {})

print(f"config: verdict={VERDICT} verify={VERIFY} type={REPORT_TYPE} "
      f"top_k={TOP_K} model={settings.ollama_model}", flush=True)
print(f"{len(pdfs)} report(s) queued\n", flush=True)

TECH_COLS = ["report", "technique_id", "technique_name", "score", "flagged",
             "instances", "sections", "best_evidence"]
MAP_COLS = ["report", "technique_id", "technique_name", "confidence", "flagged",
            "chunk_id", "heading_path", "evidence", "reason"]

for i, pdf in enumerate(pdfs, 1):
    stem = os.path.splitext(os.path.basename(pdf))[0]
    tech_csv = os.path.join(OUT, f"{stem}.techniques.csv")
    if os.path.exists(tech_csv) and not redo:
        print(f"[{i}/{len(pdfs)}] {stem}\n    skipped (already done)", flush=True)
        continue

    print(f"[{i}/{len(pdfs)}] {stem}", flush=True)
    entry = {"pdf": os.path.basename(pdf)}
    t0 = time.time()
    try:
        md = pdf_to_markdown(pdf)
        # These reports publish their own ATT&CK table; leaving it in measures
        # table-reading rather than mapping (see app/eval/deleak.py).
        md, dl = deleak_markdown(md)
        entry["deleak"] = dl
        if dl["sections_removed"] or dl["inline_ids_removed"]:
            print(f"    de-leaked: {dl['sections_removed'] or 'no'} section(s), "
                  f"{dl['section_lines_removed']} lines, "
                  f"{dl['inline_ids_removed']} inline id(s)", flush=True)
        entry["markdown_chars"] = len(md)
        report_id = str(uuid.uuid4())
        chunks, skipped = index_report(report_id, os.path.basename(pdf), md)
        t_ingest = time.time() - t0
        entry.update(report_id=report_id, chunks=len(chunks),
                     chunks_filtered=skipped, ingest_seconds=round(t_ingest, 1))
        print(f"    ingested: {len(chunks)} chunks ({skipped} filtered), "
              f"{len(md) // 1000}k chars, {t_ingest:.0f}s", flush=True)

        t1 = time.time()
        mappings = map_report(report_id, verify=VERIFY, verdict=VERDICT,
                              report_type=REPORT_TYPE, top_k=TOP_K)
        layer = aggregate_mappings(mappings)
        t_map = time.time() - t1
    except Exception:
        entry["error"] = traceback.format_exc(limit=3)
        manifest["reports"][stem] = entry
        json.dump(manifest, open(manifest_path, "w"), indent=2)
        print(f"    FAILED:\n{entry['error']}", flush=True)
        continue

    # Per-technique detail, keyed off the aggregated layer (what the matrix shows).
    by_tid: dict[str, list] = {}
    for m in mappings:
        by_tid.setdefault(m.technique_id, []).append(m)

    with open(os.path.join(OUT, f"{stem}.mappings.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(MAP_COLS)
        for m in mappings:
            w.writerow([stem, m.technique_id, m.technique_name, m.confidence,
                        int(m.flagged), m.chunk_id, m.heading_path,
                        m.evidence, m.reason])

    rows = []
    for t in layer["techniques"]:
        tid = t["techniqueID"]
        inst = by_tid.get(tid, [])
        flagged = any(md_.get("name") == "flagged" for md_ in t.get("metadata", []))
        best = max(inst, key=lambda m: m.confidence).evidence if inst else ""
        sections = sorted({m.heading_path for m in inst if m.heading_path})
        rows.append([stem, tid, inst[0].technique_name if inst else "",
                     t.get("score", ""), int(flagged), len(inst),
                     " | ".join(sections[:4]), best])
    rows.sort(key=lambda r: (-(r[3] or 0), r[1]))

    with open(tech_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TECH_COLS)
        w.writerows(rows)

    entry.update(techniques=len(rows), mappings=len(mappings),
                 flagged=sum(r[4] for r in rows), map_seconds=round(t_map, 1))
    manifest["reports"][stem] = entry
    json.dump(manifest, open(manifest_path, "w"), indent=2)
    print(f"    mapped: {len(rows)} techniques from {len(mappings)} instances "
          f"({entry['flagged']} flagged), {t_map / 60:.1f}m -> {os.path.basename(tech_csv)}\n",
          flush=True)

# Concatenate everything that exists so far.
combined = os.path.join(OUT, "all_techniques.csv")
with open(combined, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(TECH_COLS)
    for path in sorted(glob.glob(os.path.join(OUT, "*.techniques.csv"))):
        with open(path, newline="") as src:
            r = csv.reader(src)
            next(r, None)
            w.writerows(r)

done = [r for r in manifest["reports"].values() if "techniques" in r]
failed = [r for r in manifest["reports"].values() if "error" in r]
print(f"\n{'=' * 60}\ndone: {len(done)} report(s), {len(failed)} failed")
print(f"combined -> {combined}")
