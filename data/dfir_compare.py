"""Join the DFIR Reports' own published ATT&CK tables against this pipeline's
output, and emit a blind adjudication worksheet for the techniques we found
that they did not.

Deliberately forgiving about the shape of the hand-transcribed file: every
ATT&CK id anywhere in a row is extracted by regex, so one-id-per-row and
"T1078, T1021.001, T1486" in a single cell both work. The report a row belongs
to is matched to our output files by token overlap on the report label.

    python3 data/dfir_compare.py --their dfir_published.csv --inspect
    python3 data/dfir_compare.py --their dfir_published.csv

Outputs into data/dfir_analysis/ (dfir_out is root-owned by the container):
  comparison_summary.csv        per-report TP / missed / extra, exact + family
  <report>.adjudication.csv     shuffled, provenance-stripped worksheet
  version_check.csv             their ids that do not exist in the bundled KB

Nothing is scored automatically: `extra` techniques are candidates for
adjudication, not false positives, because the reference tables are known to be
incomplete (see CLAUDE.md / the DFIR evaluation notes).
"""

import argparse
import csv
import glob
import json
import os
import random
import re
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dfir_out")
# Outputs go to a HOST-owned dir: dfir_out is written by the container as root
# (CAP_CHOWN is dropped, so it cannot hand ownership back) and is read-only to us.
ANALYSIS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dfir_analysis")
KB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend",
                  "app", "attack", "prebuilt_kb", "attack_techniques.json")

TID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")
WORD_RE = re.compile(r"[a-z0-9]+")
STOP = {"dfir", "report", "the", "and", "to", "a", "of", "in", "on", "with",
        "part", "com", "https", "www", "thedfirreport", "reports"}


def toks(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if w not in STOP and len(w) > 2}


def parent(t: str) -> str:
    return t.split(".")[0]


def load_kb() -> dict[str, str]:
    d = json.load(open(KB))
    return {m["attack_id"]: m["name"] for m in d["metadatas"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--their", required=True, help="hand-transcribed CSV of the published tables")
    ap.add_argument("--inspect", action="store_true", help="show parsing and report matching, write nothing")
    ap.add_argument("--seed", type=int, default=20260902, help="shuffle seed for the worksheet")
    args = ap.parse_args()

    kb = load_kb()
    os.makedirs(ANALYSIS, exist_ok=True)
    ours: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(os.path.join(OUT, "*.techniques.csv"))):
        stem = os.path.basename(path)[: -len(".techniques.csv")]
        ours[stem] = list(csv.DictReader(open(path)))
    if not ours:
        raise SystemExit(f"no *.techniques.csv under {OUT} — has the batch finished?")

    # Their table: pull every ATT&CK id out of every row, keyed by report label.
    rows = list(csv.reader(open(args.their)))
    header = rows[0] if rows and not TID_RE.search(" ".join(rows[0])) else None
    body = rows[1:] if header else rows
    theirs: dict[str, set[str]] = {}
    unmatched_rows = []
    for row in body:
        line = " ".join(row)
        ids = set(TID_RE.findall(line))
        if not ids:
            continue
        label = " ".join(c for c in row if not TID_RE.search(c)) or line
        best, score = None, 0
        lt = toks(label)
        for stem in ours:
            s = len(lt & toks(stem))
            if s > score:
                best, score = stem, s
        if best is None or score < 2:
            unmatched_rows.append((label[:70], sorted(ids)[:6]))
            continue
        theirs.setdefault(best, set()).update(ids)

    print(f"their file: {len(body)} rows, header={'yes' if header else 'no'}")
    if header:
        print(f"  columns: {header}")
    print(f"our output: {len(ours)} report(s)\n")
    print(f"{'report':<58} {'theirs':>7} {'ours':>6}")
    for stem in ours:
        print(f"  {stem[:56]:<56} {len(theirs.get(stem, [])):>7} {len(ours[stem]):>6}")
    if unmatched_rows:
        print(f"\n!! {len(unmatched_rows)} row(s) could not be matched to a report:")
        for label, ids in unmatched_rows[:10]:
            print(f"   {label!r} -> {ids}")
        print("   (fix the report label in your CSV, or tell me the intended mapping)")
    missing_reports = [s for s in ours if s not in theirs]
    if missing_reports:
        print(f"\n!! no rows matched for: {', '.join(m[:40] for m in missing_reports)}")

    # ATT&CK version check: their ids that the bundled v19.1 KB does not know.
    unknown = sorted({t for ids in theirs.values() for t in ids if t not in kb})
    print(f"\nATT&CK version check: {len(unknown)} of their id(s) absent from the bundled KB")
    for t in unknown:
        holders = [s for s, ids in theirs.items() if t in ids]
        print(f"   {t}  (in {len(holders)} report(s)) — retired/renamed, or a typo")
    if unknown and not args.inspect:
        with open(os.path.join(ANALYSIS, "version_check.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["technique_id", "reports", "note"])
            for t in unknown:
                w.writerow([t, ";".join(s for s, ids in theirs.items() if t in ids),
                            "absent from bundled v19.1 KB — the mapper cannot emit it"])

    if args.inspect:
        print("\n--inspect: nothing written.")
        return 0

    # Triage signals for the worksheet. Cross-report frequency is the useful
    # one: these are all ransomware intrusions, so a technique appearing in
    # most of them is the corpus backbone, while a singleton is either a real
    # report-specific finding or noise — which is where judging effort belongs.
    freq: dict[str, int] = {}
    for stem, mine_rows in ours.items():
        for t in {r["technique_id"] for r in mine_rows}:
            freq[t] = freq.get(t, 0) + 1

    # Which techniques are supported ONLY by detection-artifact sections
    # (Sigma rule titles, IOC tables) rather than adversary narrative.
    det_only: dict[str, set[str]] = {}
    for path in glob.glob(os.path.join(OUT, "*.mappings.csv")):
        stem = os.path.basename(path)[: -len(".mappings.csv")]
        det, oth = set(), set()
        for m in csv.DictReader(open(path)):
            h = m["heading_path"]
            (det if any(k in h for k in ("Detection", "Indicator", "Sigma")) else oth).add(
                m["technique_id"])
        det_only[stem] = det - oth

    def classify(row: dict, stem: str) -> str:
        if int(row["instances"] or 0) == 0:
            return "promoted-parent"
        if row["technique_id"] in det_only.get(stem, set()):
            return "detection-sourced"
        if int(row["flagged"] or 0):
            return "judge-flagged"
        n = freq.get(row["technique_id"], 0)
        if n >= max(2, len(ours) * 2 // 3):
            return f"corpus-common ({n}/{len(ours)})"
        return f"report-specific ({n}/{len(ours)})"

    rng = random.Random(args.seed)
    summary = []
    for stem, mine_rows in ours.items():
        mine = {r["technique_id"] for r in mine_rows}
        their = theirs.get(stem, set())
        their_known = {t for t in their if t in kb}
        tp = mine & their_known
        missed = their_known - mine
        extra = mine - their_known
        fam_mine = {parent(t) for t in mine}
        fam_tp = {t for t in their_known if parent(t) in fam_mine}
        summary.append({
            "report": stem,
            "their_total": len(their), "their_in_kb": len(their_known),
            "ours_total": len(mine),
            "exact_tp": len(tp), "exact_missed": len(missed), "extra": len(extra),
            "family_tp": len(fam_tp),
            "exact_recall": round(len(tp) / len(their_known), 3) if their_known else "",
            "family_recall": round(len(fam_tp) / len(their_known), 3) if their_known else "",
        })

        # Blind worksheet: every technique we produced, provenance stripped and
        # shuffled, so judging cannot be anchored on whether they listed it.
        work = []
        for r in mine_rows:
            work.append({
                "technique_id": r["technique_id"],
                "technique_name": r["technique_name"] or kb.get(r["technique_id"], ""),
                "class": classify(r, stem),
                "n_reports": freq.get(r["technique_id"], 0),
                "sections": r["sections"],
                "instances": r["instances"],
                "evidence": r["best_evidence"] or "(parent promoted from mapped sub-techniques)",
                "verdict (correct/incorrect/unsure)": "",
                "notes": "",
            })
        rng.shuffle(work)
        with open(os.path.join(ANALYSIS, f"{stem}.adjudication.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(work[0]))
            w.writeheader()
            w.writerows(work)

    with open(os.path.join(ANALYSIS, "comparison_summary.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)

    print(f"\n{'report':<44} {'theirs':>7} {'ours':>5} {'TP':>4} {'miss':>5} {'extra':>6} {'rec':>6} {'fam':>6}")
    for s in summary:
        print(f"  {s['report'][:42]:<42} {s['their_in_kb']:>7} {s['ours_total']:>5} "
              f"{s['exact_tp']:>4} {s['exact_missed']:>5} {s['extra']:>6} "
              f"{str(s['exact_recall']):>6} {str(s['family_recall']):>6}")
    print(f"\nwrote comparison_summary.csv and {len(summary)} adjudication worksheet(s) -> {ANALYSIS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
