"""Sentence and sentence-window splitting for sub-chunk retrieval.

Chunk-granularity retrieval (~1200 chars) systematically loses techniques
evidenced by a single sentence inside a chunk dominated by another theme.
Sentences are the unit evidence actually lives at; windows pack them into
something worth embedding.

Lines are split before sentences so line-bounded units — table rows, list
items, the breadcrumb — never fuse with neighbouring prose into one nonsense
"sentence".
"""

import re

# End-of-sentence punctuation, whitespace, then a sentence start. The
# lookbehind excludes a single capital initial ("R. Alvarez").
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?<!\b[A-Z].)\s+(?=[A-Z0-9\"'(¿¡])")

# Lines that are their own unit regardless of punctuation: table rows, list
# items, headings. Everything else is prose that pymupdf4llm hard-wraps at the
# PDF's line width, and must be unwrapped back into its paragraph before
# sentence-splitting — otherwise every wrapped line becomes a bogus fragment.
_LINE_BOUNDED_RE = re.compile(r"^\s*(\||[-*+•]\s|\d+[.)]\s|#{1,6}\s)")

# Soft cap for a window: enough context for the embedding model, small enough
# that one sentence's technique is not averaged away by its neighbours.
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
    """Pack consecutive sentences into windows of up to `max_chars`; a longer
    single sentence stays whole. Non-overlapping — the chunk-level embedding is
    still retrieval's coarse half, so windows only need to give minority
    sentences their own vector."""
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
