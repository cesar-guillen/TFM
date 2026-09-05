"""CLI for the mapping eval harness.

    docker compose exec backend python -m app.eval.run_eval [options]

Ingests the selected reference PDF (or reuses an already-indexed report),
scores retrieval coverage once, runs mapping N times, and prints a
per-technique report. Nothing is written to the matrix library — map_report is
called directly, so eval runs don't pollute /data/layers.

Options:
  --report NAME     labelled report to evaluate (see ground_truth.REPORTS;
                    default: meridian-grove)
  --pdf PATH        override the PDF path (default: the report's pdf_glob
                    under data/uploads)
  --report-id ID    skip ingest and score an already-indexed report instead
                    (must be the same document as --report's ground truth)
  --runs N          mapping passes to average over (default 5)
  --top-k K         candidates per chunk (default: settings.map_candidates)
"""

import argparse
import glob
import os
import uuid

from app.core.config import settings
from app.eval.deleak import deleak_markdown
from app.eval.ground_truth import DEFAULT_REPORT, REPORTS
from app.eval.harness import run_eval
from app.ingest.indexing import index_report
from app.ingest.pdf_to_markdown import pdf_to_markdown


def _find_pdf(pdf_glob: str) -> str | None:
    hits = sorted(glob.glob(pdf_glob), key=len)  # shortest name = least-prefixed copy
    return hits[0] if hits else None


def _ingest(pdf_path: str, deleak: bool = False) -> tuple[str, int]:
    report_id = str(uuid.uuid4())
    markdown = pdf_to_markdown(pdf_path)
    if deleak:
        markdown, stats = deleak_markdown(markdown)
        # Always report it: a silent de-leak would be worse than none, since
        # the numbers it changes are the ones being reported.
        print(f"  de-leaked: dropped {stats['sections_removed'] or 'no'} section(s)"
              f" ({stats['section_lines_removed']} lines),"
              f" {stats['inline_ids_removed']} inline ATT&CK id(s)")
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


def _prf(hits: list[int], fps: list[int], n_core: int) -> tuple[float, float, float]:
    """Macro-averaged precision / recall / F1 over the runs.

    TP = labelled core techniques recovered, FP = "unexpected" (mapped but in
    neither label set — `acceptable` is deliberately neutral, counted as
    neither), FN = core techniques not recovered. Computed per run and then
    averaged, not derived from the averages: a run that maps twice as much is
    not allowed to dominate the ratio.
    """
    if not hits:
        return 0.0, 0.0, 0.0
    ps, rs, fs = [], [], []
    for tp, fp in zip(hits, fps):
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / n_core if n_core else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        ps.append(precision)
        rs.append(recall)
        fs.append(f1)
    return sum(ps) / len(ps), sum(rs) / len(rs), sum(fs) / len(fs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mapping eval harness")
    parser.add_argument("--report", choices=sorted(REPORTS), default=DEFAULT_REPORT)
    parser.add_argument("--pdf")
    parser.add_argument("--report-id")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=settings.map_candidates)
    parser.add_argument("--verify", choices=["off", "demote", "drop"], default=None,
                        help="verification-pass mode (default: settings.verify_mode)")
    parser.add_argument("--report-type", choices=["incident", "pentest"], default=None,
                        help="prompt family (default: settings.report_type)")
    parser.add_argument("--verdict", choices=["menu", "independent"], default=None,
                        help="verdict architecture (default: settings.verdict_mode)")
    args = parser.parse_args()

    gt = REPORTS[args.report]
    core, acceptable = gt.core, gt.acceptable

    if args.report_id:
        report_id, chunk_count = args.report_id, 0
        print(f"Scoring already-indexed report {report_id}")
    else:
        pdf = args.pdf or _find_pdf(gt.pdf_glob)
        if not pdf or not os.path.exists(pdf):
            raise SystemExit(f"No PDF found (looked for {gt.pdf_glob}); pass --pdf")
        print(f"Ingesting {os.path.basename(pdf)} …")
        report_id, chunk_count = _ingest(pdf, deleak=gt.deleak)
        print(f"  indexed {chunk_count} content chunks (report_id {report_id})")

    print(
        f"Report: {gt.name}\n"
        f"Config: model={settings.ollama_model}  top_k={args.top_k}  "
        f"sentence_retrieval={settings.sentence_retrieval}  runs={args.runs}\n"
        f"        report_type={args.report_type or settings.report_type}  "
        f"verify={args.verify or settings.verify_mode}  "
        f"verdict={args.verdict or settings.verdict_mode}\n"
        f"Ground truth: {len(core)} core + {len(acceptable)} acceptable techniques\n"
    )

    res = run_eval(
        report_id, runs=args.runs, top_k=args.top_k,
        core=core, acceptable=acceptable, chunk_count=chunk_count,
        verify=args.verify, report_type=args.report_type, verdict=args.verdict,
    )

    print("=" * 72)
    print("RETRIEVAL COVERAGE (deterministic — the ceiling on what can be mapped)")
    print("=" * 72)
    reachable = len(res.family_reachable)
    exact_hits = len(res.retrieval_rank)
    print(f"core reachable (exact/parent/sub is a candidate): {reachable}/{len(core)} "
          f"({100 * reachable / len(core):.0f}%)")
    print(f"  of which the exact id is a candidate           : {exact_hits}/{len(core)}")
    if res.unreachable:
        print("NOT REACHABLE at all (cannot be mapped — retrieval-stage gap):")
        for t in res.unreachable:
            print(f"    {t:<11} {core[t]}")

    print()
    print("=" * 72)
    print(f"VERDICT RECALL ({res.runs} runs) — per-core-technique mapping frequency")
    print("=" * 72)
    print("  (exact = this id mapped; family = exact/parent/sub via promotion)\n")
    # order: hardest first (lowest exact frequency), then by id
    for t in sorted(core, key=lambda t: (res.exact_freq[t], t)):
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
    print(f"  retrieval ceiling : {len(res.family_reachable)}/{len(core)} core techniques reachable")
    print(f"  exact  recall     : {_fmt_pct(res.exact_per_run, len(core))}")
    print(f"  family recall     : {_fmt_pct(res.family_per_run, len(core))}")
    if res.unexpected_per_run:
        avg_unexp = sum(res.unexpected_per_run) / len(res.unexpected_per_run)
        print(f"  unexpected/run    : {avg_unexp:.1f} avg  "
              f"[runs: {min(res.unexpected_per_run)}–{max(res.unexpected_per_run)}]  "
              f"(mapped, not in ground truth — candidate FPs to review)")
        frequent = sorted(res.unexpected_freq.items(), key=lambda kv: (-kv[1], kv[0]))
        for tid, cnt in frequent[:12]:
            print(f"      {tid:<11} {cnt}/{res.runs} runs")

    # Precision / recall / F1 — F1 is the headline number any tuning change is
    # judged on (recall alone rewards spraying techniques; precision alone
    # rewards mapping almost nothing). Reported for both label strictnesses:
    # exact = the precise id had to be mapped; family = parent/sub counts, so
    # the mapper is credited for finding the right behaviour at the wrong
    # granularity. Printed last so it is the number that ends every run.
    if res.exact_per_run:
        print()
        for label, hits in (("exact ", res.exact_per_run), ("family", res.family_per_run)):
            p, r, f1 = _prf(hits, res.unexpected_per_run, len(core))
            print(f"  {label} precision {p:.3f} | recall {r:.3f} | F1 {f1:.3f}")


if __name__ == "__main__":
    main()
