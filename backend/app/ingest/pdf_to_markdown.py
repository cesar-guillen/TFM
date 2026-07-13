"""PDF → Markdown extraction with ligature-damage mitigation.

Ligature glyphs (ﬁ ﬀ ﬂ ﬃ ﬄ) in real-world PDFs break extraction two ways:

1. pymupdf4llm's default engine (pymupdf.layout) silently drops every text
   line containing an expanded ligature: MuPDF gives the synthesized
   constituent characters degenerate zero-width, metrics-height bboxes, the
   inflated span then fails the engine's 80%-inside-clip test
   (utils.almost_in_bbox) and the whole span is discarded. Once triggered,
   process-global state corrupts every LATER conversion in the same process
   too. The legacy engine ships with TEXT_ACCURATE_BBOXES disabled and has
   neither defect, so we pin it below.

2. Fonts with a broken ToUnicode map extract each ligature glyph as a bogus
   codepoint that ends up as U+FFFD (�) in the markdown, corrupting exactly
   the words retrieval needs ("exﬁltration", "oﬃce", "identiﬁed"...).
   repair_ligatures() rewrites those words by trying the ligature expansions
   against vocabulary from the document itself plus the bundled ATT&CK KB
   descriptions — fully offline, no new dependencies.
"""

import itertools
import json
import re
from functools import lru_cache
from pathlib import Path

import pymupdf4llm

pymupdf4llm.use_layout(False)

# U+FB00..FB06 → ASCII, for PDFs whose ToUnicode correctly yields the
# Unicode ligature codepoints (they would break BM25/embedding matching).
_LIGATURE_TABLE = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "ft",
        "ﬆ": "st",
    }
)

# MuPDF's seven supported ligatures, most common first (first vocab hit wins).
_EXPANSIONS = ("ff", "fi", "fl", "ffi", "ffl", "ft", "st")
_BROKEN_WORD_RE = re.compile(r"[A-Za-z]*�[A-Za-z�]*")
_VOCAB_RE = re.compile(r"[a-z]{3,}")
_KB_SEED = (
    Path(__file__).resolve().parent.parent
    / "attack"
    / "prebuilt_kb"
    / "attack_techniques.json"
)


# Crude inflection stripping so "conﬁrming" can match vocab "confirm" and
# "ﬁll" can match vocab "filled" — applied to both sides, stems kept ≥ 4 chars.
_SUFFIXES = ("ing", "ed", "es", "ly", "s", "d")


def _stems(word: str):
    yield word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            yield word[: -len(suffix)]


def _stemmed(words) -> frozenset[str]:
    return frozenset(stem for word in words for stem in _stems(word))


@lru_cache(maxsize=1)
def _kb_vocab() -> frozenset[str]:
    try:
        docs = json.loads(_KB_SEED.read_text())["documents"]
    except (OSError, ValueError, KeyError):
        return frozenset()
    return _stemmed(_VOCAB_RE.findall(" ".join(docs).lower()))


def _repair_word(word: str, vocab: frozenset[str]) -> str:
    holes = word.count("�")
    if holes > 3:
        return word
    for combo in itertools.product(_EXPANSIONS, repeat=holes):
        candidate = word
        for expansion in combo:
            candidate = candidate.replace("�", expansion, 1)
        if any(stem in vocab for stem in _stems(candidate.lower())):
            return candidate
    return word


def repair_ligatures(markdown: str) -> str:
    markdown = markdown.translate(_LIGATURE_TABLE)
    if "�" not in markdown:
        return markdown
    vocab = _stemmed(_VOCAB_RE.findall(markdown.lower())) | _kb_vocab()
    return _BROKEN_WORD_RE.sub(
        lambda m: _repair_word(m.group(0), vocab), markdown
    )


def pdf_to_markdown(pdf_path: str) -> str:
    return repair_ligatures(pymupdf4llm.to_markdown(pdf_path))
