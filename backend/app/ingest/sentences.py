"""Sentence and sentence-window splitting for sub-chunk retrieval.

Retrieval used to query at chunk granularity (~1200 chars) only, which
systematically lost techniques evidenced by a single sentence inside a chunk
dominated by another theme (measured on the Meridian Grove synthetic report:
"alternating between SSH, RDP, and WinRM sessions" never surfaced T1021 —
the chunk embedding landed in the Kerberos neighborhood and the chunk-long
BM25 query drowned three lone protocol tokens). Sentences are the unit
evidence actually lives at; windows pack them to a size worth embedding.

Lines are split before sentences so line-bounded units — markdown table rows,
list items, the breadcrumb line — never fuse with neighboring prose into one
nonsense "sentence" (timeline tables carry one attack step per row).
"""

import re

# End-of-sentence punctuation followed by whitespace and something that starts
# a sentence. The lookbehind excludes common abbreviation shapes: a single
# capital initial ("R. Alvarez") and ordinal-style number+dot ("Day 4."
# stays, "5." list markers are line-bounded anyway).
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?<!\b[A-Z].)\s+(?=[A-Z0-9\"'(¿¡])")

# Lines that are their own unit regardless of punctuation: markdown table
# rows, list items, headings. Everything else is prose that pymupdf4llm
# hard-wraps at the PDF's line width — those lines must be unwrapped back
# into their paragraph before sentence-splitting, or every wrapped line
# becomes a bogus "sentence" fragment (measured: the SSH/RDP/WinRM clause
# severed from its subject and verb).
_LINE_BOUNDED_RE = re.compile(r"^\s*(\||[-*+•]\s|\d+[.)]\s|#{1,6}\s)")

# Soft cap for a dense-retrieval window: big enough that nomic-embed gets a
# sentence or two of real context, small enough that one sentence's technique
# is not averaged away by its neighbors.
WINDOW_MAX_CHARS = 300


def split_sentences(text: str) -> list[str]:
    """Sentences of `text`. Table rows, list items, and headings are one unit
    per line; consecutive prose lines are unwrapped into their paragraph
    (blank lines end a paragraph) before sentence-splitting. Stripped, no
    empties."""
    sentences: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            joined = " ".join(paragraph)
            sentences.extend(s.strip() for s in _SENTENCE_END_RE.split(joined) if s.strip())
            paragraph.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush()
        elif _LINE_BOUNDED_RE.match(line):
            flush()
            sentences.append(line)
        else:
            paragraph.append(line)
    flush()
    return sentences


def build_windows(text: str, max_chars: int = WINDOW_MAX_CHARS) -> list[str]:
    """Pack consecutive sentences into windows of up to `max_chars` (a single
    longer sentence stays whole). Non-overlapping: the chunk-level embedding
    still exists as retrieval's coarse half, so windows only need to give the
    minority sentences their own vector, not re-cover every span."""
    windows: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in split_sentences(text):
        if current and size + len(sentence) + 1 > max_chars:
            windows.append(" ".join(current))
            current, size = [], 0
        current.append(sentence)
        size += len(sentence) + 1
    if current:
        windows.append(" ".join(current))
    return windows
