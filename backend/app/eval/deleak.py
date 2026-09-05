"""Remove ATT&CK answer-key material from a report's extracted markdown.

Public CTI reports frequently end with the author's own ATT&CK table. Leaving
it in measures the pipeline's ability to *read a mapping someone else wrote*,
not to derive one — and `EXPLICIT_IDS` injection compounds it by seating any
cited id at rank 1. Measured on the 10-report DFIR corpus (2026-09-02): 35
mapping instances came from `MITRE ATT&CK` sections and 10 core techniques were
recoverable ONLY from there, inflating exact recall 0.549 -> 0.584.

Evaluation-only, and opt-in per report (`ReportGroundTruth.deleak`): production
ingest keeps citations, which are a deliberate feature, and `acme-pentest`'s
documented results depend on its cited-id findings table.
"""

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# A heading naming ATT&CK/MITRE introduces the author's own mapping table.
_ATTACK_HEADING = re.compile(r"\batt\s*&?\s*ck\b|\bmitre\b", re.I)
_TID = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")
_MARKERS = re.compile(r"[*_`#]+")


def _heading_text(raw: str) -> str:
    return _MARKERS.sub("", raw).strip()


def strip_attack_sections(markdown: str) -> tuple[str, list[str], int]:
    """Drop every heading whose title names ATT&CK/MITRE, plus its body, up to
    the next heading of the same or higher level. Returns (markdown, titles
    removed, lines removed)."""
    lines = markdown.splitlines(keepends=True)
    out: list[str] = []
    removed: list[str] = []
    dropped = 0
    skip_level: int | None = None
    for line in lines:
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            title = _heading_text(m.group(2))
            if skip_level is not None and level <= skip_level:
                skip_level = None  # section ended; fall through and re-test
            if skip_level is None and _ATTACK_HEADING.search(title):
                skip_level = level
                removed.append(title)
                dropped += 1
                continue
        if skip_level is not None:
            dropped += 1
            continue
        out.append(line)
    return "".join(out), removed, dropped


def strip_inline_ids(markdown: str) -> tuple[str, int]:
    """Remove ATT&CK ids cited in running text. An id next to described
    activity is the answer, and retrieval injects it at rank 1."""
    n = len(_TID.findall(markdown))
    if not n:
        return markdown, 0
    cleaned = _TID.sub("", markdown)
    # Tidy the punctuation the removal strands: "(T1059)" -> "", "[]" -> "".
    cleaned = re.sub(r"[\[(]\s*[,;/|\s]*[\])]", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:)\]])", r"\1", cleaned)
    return cleaned, n


def deleak_markdown(markdown: str) -> tuple[str, dict]:
    """Both passes. Returns the cleaned markdown and a stats dict for logging —
    a silent de-leak would be worse than none, since the numbers it changes are
    the ones being reported."""
    before = len(markdown)
    md, sections, lines = strip_attack_sections(markdown)
    md, ids = strip_inline_ids(md)
    return md, {
        "sections_removed": sections,
        "section_lines_removed": lines,
        "inline_ids_removed": ids,
        "chars_before": before,
        "chars_after": len(md),
    }
