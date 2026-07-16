"""Mapping eval harness: score the pipeline against a hand-labelled report,
separating the two failure surfaces and averaging over N runs to see through
the ±2-3-technique run-to-run nondeterminism (concurrent GPU decodes at temp 0).

Two metrics, deliberately separate — they have different fixes:
  * retrieval coverage (deterministic, one pass): of the CORE techniques, how
    many are even offered as candidates. A technique never retrieved can never
    be mapped — that's a retrieval problem, fixed upstream.
  * verdict recall (N passes): of what IS offered, how often the LLM actually
    maps it. Per-technique frequency (e.g. "/etc/shadow 2/10") is the point —
    a single run can't tell a real miss from an unlucky draw.

Plus an "unexpected" count (mapped techniques in neither core nor acceptable) —
candidate false positives to review. See ground_truth.py for the label sets;
the core/acceptable dicts are passed in, so the harness scores any labelled
report in the registry.
"""

from dataclasses import dataclass, field

from app.mapping.aggregate import aggregate_mappings
from app.mapping.mapper import map_report
from app.retrieval.retrieve import search_techniques_for_report


def _parent(tid: str) -> str:
    return tid.split(".")[0]


def _expected_universe(core: dict[str, str], acceptable: dict[str, str]) -> set[str]:
    """core ∪ acceptable, plus the parent of every labelled sub — a promoted
    parent of an expected sub is not a false positive."""
    exp = set(core) | set(acceptable)
    return exp | {_parent(t) for t in exp}


def _family_hit(tid: str, mapped: set[str]) -> bool:
    """The technique counts as recovered if the exact id is mapped, or its
    parent is (parent promotion / the model mapped the parent), or — for a
    parent label — any of its sub-techniques is mapped."""
    if tid in mapped or _parent(tid) in mapped:
        return True
    if "." not in tid and any(m.startswith(tid + ".") for m in mapped):
        return True
    return False


@dataclass
class EvalResult:
    runs: int
    top_k: int
    chunk_count: int
    # retrieval (deterministic): core id -> best exact candidate rank across
    # chunks; family_reachable = exact OR parent OR a sub is a candidate (so
    # the model can earn family credit); unreachable = not even that.
    retrieval_rank: dict[str, int]
    family_reachable: set[str]
    unreachable: list[str]
    # verdict (per run): core id -> how many of `runs` mapped it (exact / family)
    exact_freq: dict[str, int]
    family_freq: dict[str, int]
    # per-run totals, for averages + variance
    exact_per_run: list[int] = field(default_factory=list)
    family_per_run: list[int] = field(default_factory=list)
    unexpected_per_run: list[int] = field(default_factory=list)
    # unexpected (candidate FP) id -> how many runs it appeared in
    unexpected_freq: dict[str, int] = field(default_factory=dict)


def retrieval_coverage(
    report_id: str, top_k: int, core: dict[str, str]
) -> tuple[dict[str, int], set[str], list[str]]:
    """For each core technique: its best exact candidate rank (if offered), the
    set that is family-reachable (exact OR parent OR a sub is a candidate — the
    model can still earn family credit for those), and the ones not reachable
    at all (a genuine retrieval-stage gap)."""
    cands = search_techniques_for_report(report_id, top_k_per_chunk=top_k)
    best: dict[str, int] = {}
    present: set[str] = set()
    for matches in cands.values():
        for rank, m in enumerate(matches, start=1):
            present.add(m.attack_id)
            if m.attack_id not in best or rank < best[m.attack_id]:
                best[m.attack_id] = rank

    def reachable(tid: str) -> bool:
        if tid in present or _parent(tid) in present:
            return True
        return "." not in tid and any(p.startswith(tid + ".") for p in present)

    exact_rank = {t: best[t] for t in core if t in best}
    family_reachable = {t for t in core if reachable(t)}
    unreachable = [t for t in core if t not in family_reachable]
    return exact_rank, family_reachable, unreachable


def mapped_ids_once(report_id: str) -> set[str]:
    """One full mapping pass -> the set of technique ids in the aggregated
    layer (what the user sees, so parent-promoted ids are included)."""
    layer = aggregate_mappings(map_report(report_id))
    return {t["techniqueID"] for t in layer["techniques"]}


def run_eval(
    report_id: str,
    runs: int,
    top_k: int,
    core: dict[str, str],
    acceptable: dict[str, str],
    chunk_count: int = 0,
) -> EvalResult:
    retrieval_rank, family_reachable, unreachable = retrieval_coverage(report_id, top_k, core)
    universe = _expected_universe(core, acceptable)

    res = EvalResult(
        runs=runs,
        top_k=top_k,
        chunk_count=chunk_count,
        retrieval_rank=retrieval_rank,
        family_reachable=family_reachable,
        unreachable=unreachable,
        exact_freq={t: 0 for t in core},
        family_freq={t: 0 for t in core},
    )

    for _ in range(runs):
        mapped = mapped_ids_once(report_id)
        exact = {t for t in core if t in mapped}
        family = {t for t in core if _family_hit(t, mapped)}
        unexpected = mapped - universe
        for t in exact:
            res.exact_freq[t] += 1
        for t in family:
            res.family_freq[t] += 1
        for u in unexpected:
            res.unexpected_freq[u] = res.unexpected_freq.get(u, 0) + 1
        res.exact_per_run.append(len(exact))
        res.family_per_run.append(len(family))
        res.unexpected_per_run.append(len(unexpected))

    return res
