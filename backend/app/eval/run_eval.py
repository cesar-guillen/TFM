"""CLI for the mapping eval harness.

    docker compose exec backend python -m app.eval.run_eval [options]

Ingests the reference PDF (or reuses an already-indexed report), scores
retrieval coverage once, runs mapping N times, and prints a per-technique
report. Nothing is written to the matrix library — map_report is called
directly, so eval runs don't pollute /data/layers.

Options:
  --pdf PATH        report to evaluate (default: the bundled Meridian Grove
                    sample under data/uploads matching *sample_report._2.pdf)
  --report-id ID    skip ingest and score an already-indexed report instead
  --runs N          mapping passes to average over (default 5)
  --top-k K         candidates per chunk (default: settings.map_candidates)
"""

import argparse
import glob
import os
import uuid

from app.core.config import settings
from app.eval.ground_truth import ACCEPTABLE, CORE
from app.eval.harness import run_eval
from app.ingest.indexing import index_report
from app.ingest.pdf_to_markdown import pdf_to_markdown

DEFAULT_GLOB = "/data/uploads/*sample_report._2.pdf"


def _find_default_pdf() -> str | None:
    hits = sorted(glob.glob(DEFAULT_GLOB), key=len)  # shortest name = least-prefixed copy
    return hits[0] if hits else None


def _ingest(pdf_path: str) -> tuple[str, int]:
    report_id = str(uuid.uuid4())
    markdown = pdf_to_markdown(pdf_path)
    chunks, _skipped = index_report(report_id, os.path.basename(pdf_path), markdown)
    return report_id, len(chunks)


def _bar(n: int, total: int, width: int = 10) -> str:
    filled = round(width * n / total) if total else 0
    return "█" * filled + "·" * (width - filled)


def _fmt_pct(values: list[int], denom: int) -> str:
    if not values:
        return "n/a"
    avg = sum(values) / len(values)
    return f"{avg:.1f}/{denom} ({100 * avg / denom:.0f}%)  [runs: {min(values)}–{max(values)}]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mapping eval harness")
    parser.add_argument("--pdf")
    parser.add_argument("--report-id")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=settings.map_candidates)
    args = parser.parse_args()

    if args.report_id:
        report_id, chunk_count = args.report_id, 0
        print(f"Scoring already-indexed report {report_id}")
    else:
        pdf = args.pdf or _find_default_pdf()
        if not pdf or not os.path.exists(pdf):
            raise SystemExit(f"No PDF found (looked for {DEFAULT_GLOB}); pass --pdf")
        print(f"Ingesting {os.path.basename(pdf)} …")
        report_id, chunk_count = _ingest(pdf)
        print(f"  indexed {chunk_count} content chunks (report_id {report_id})")

    print(
        f"Config: model={settings.ollama_model}  top_k={args.top_k}  "
        f"sentence_retrieval={settings.sentence_retrieval}  runs={args.runs}\n"
        f"Ground truth: {len(CORE)} core + {len(ACCEPTABLE)} acceptable techniques\n"
    )

    res = run_eval(report_id, runs=args.runs, top_k=args.top_k, chunk_count=chunk_count)

    print("=" * 72)
    print("RETRIEVAL COVERAGE (deterministic — the ceiling on what can be mapped)")
    print("=" * 72)
    reachable = len(res.family_reachable)
    exact_hits = len(res.retrieval_rank)
    print(f"core reachable (exact/parent/sub is a candidate): {reachable}/{len(CORE)} "
          f"({100 * reachable / len(CORE):.0f}%)")
    print(f"  of which the exact id is a candidate           : {exact_hits}/{len(CORE)}")
    if res.unreachable:
        print("NOT REACHABLE at all (cannot be mapped — retrieval-stage gap):")
        for t in res.unreachable:
            print(f"    {t:<11} {CORE[t]}")

    print()
    print("=" * 72)
    print(f"VERDICT RECALL ({res.runs} runs) — per-core-technique mapping frequency")
    print("=" * 72)
    print("  (exact = this id mapped; family = exact/parent/sub via promotion)\n")
    # order: hardest first (lowest exact frequency), then by id
    for t in sorted(CORE, key=lambda t: (res.exact_freq[t], t)):
        ex, fam = res.exact_freq[t], res.family_freq[t]
        rank = res.retrieval_rank.get(t)
        if rank:
            rank_s = f"cand#{rank}"
        elif t in res.family_reachable:
            rank_s = "fam-only"  # exact sub not offered, but parent/sub is
        else:
            rank_s = "UNREACH"
        # offered (exact or family) yet almost never mapped => verdict-stage miss
        flag = ""
        if t in res.family_reachable and fam <= res.runs // 3:
            flag = "  <-- reachable, rarely mapped (verdict miss)"
        print(f"  {t:<11} exact {ex:>2}/{res.runs} {_bar(ex, res.runs)}  "
              f"family {fam:>2}/{res.runs}  {rank_s}{flag}")

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  retrieval ceiling : {len(res.family_reachable)}/{len(CORE)} core techniques reachable")
    print(f"  exact  recall     : {_fmt_pct(res.exact_per_run, len(CORE))}")
    print(f"  family recall     : {_fmt_pct(res.family_per_run, len(CORE))}")
    if res.unexpected_per_run:
        avg_unexp = sum(res.unexpected_per_run) / len(res.unexpected_per_run)
        print(f"  unexpected/run    : {avg_unexp:.1f} avg  "
              f"[runs: {min(res.unexpected_per_run)}–{max(res.unexpected_per_run)}]  "
              f"(mapped, not in ground truth — candidate FPs to review)")
        frequent = sorted(res.unexpected_freq.items(), key=lambda kv: (-kv[1], kv[0]))
        for tid, cnt in frequent[:12]:
            print(f"      {tid:<11} {cnt}/{res.runs} runs")


if __name__ == "__main__":
    main()
