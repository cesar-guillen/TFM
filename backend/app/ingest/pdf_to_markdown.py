"""PDF -> Markdown extraction, with ligature-damage repair.

Ligature glyphs (fi, ff, fl...) in real-world PDFs break extraction two ways:

1. pymupdf4llm's default engine silently drops whole text lines containing an
   expanded ligature, and corrupts process-global state so every later
   conversion in the same process loses content too. The legacy engine has
   neither defect, so it is pinned below.
2. Fonts with a broken ToUnicode map extract each ligature as a bogus
   codepoint that lands in the markdown as U+FFFD, corrupting exactly the
   words retrieval needs ("exfiltration", "identified"). repair_ligatures()
   rewrites those words by testing the ligature expansions against vocabulary
   from the document itself plus the bundled ATT&CK descriptions — offline,
   with no extra dependency.
"""

import itertools
import json
import re
from functools import lru_cache
from pathlib import Path

import pymupdf
import pymupdf4llm

from app.ingest.ocr import format_ocr_block, ocr_document_images

pymupdf4llm.use_layout(False)

# U+FB00..FB06 -> ASCII: intact ligature codepoints break BM25 and embedding
# matching just as badly as the broken ones.
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


# Crude inflection stripping, applied to both sides so "confirming" matches a
# vocabulary entry of "confirm". Stems stay at least 4 chars.
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


class PdfParseError(Exception):
    """The upload could not be read as a PDF (corrupt, encrypted, or not one)."""


def pdf_to_markdown(pdf_path: str, ocr_enabled: bool = True) -> str:
    """`ocr_enabled=False` skips OCR entirely (a per-run user choice — see the
    upload options dialog), independent of whether tesseract is installed."""
    try:
        raw = pymupdf.open(pdf_path)
        # Garbage-collect + clean before handing the PDF to pymupdf4llm.
        # Fixes a measured 19-31x parse-time blowup (2026-09-05) on reports
        # whose export tool references every embedded image from every
        # page's resource dictionary (a PDF-export artifact, not real
        # content duplication) — pymupdf4llm's layout detector decodes and
        # MD5-hashes an image once per *reference*, so a 62-image, 41-page
        # report bloats to ~2,500 decodes instead of 62. Cleaning collapses
        # the redundant references before that ever happens. In-memory, no
        # temp file. Verified byte-identical markdown output and functionally
        # identical image metadata (only sub-pixel bbox float noise, ~1e-5pt,
        # irrelevant at any real render DPI) on all 3 affected reports; cost
        # on an already-fast report was 0.05s and still net faster overall.
        cleaned_bytes = raw.tobytes(garbage=4, deflate=True, clean=True)
        raw.close()
        doc = pymupdf.open(stream=cleaned_bytes, filetype="pdf")
        pages = pymupdf4llm.to_markdown(doc, page_chunks=True)
    except Exception as exc:
        raise PdfParseError(str(exc)) from exc

    # OCR embedded screenshots (console output, dashboards) that the text
    # layer can't see (app/ingest/ocr.py) — page_chunks=True's own per-page
    # `text` fields concatenate to byte-identical output to the plain-string
    # call (verified 2026-09-04), so this only adds content, never changes
    # existing extraction. Degrades to a no-op if tesseract isn't installed.
    ocr_by_page = ocr_document_images(doc, pages) if ocr_enabled else {}
    parts = []
    for i, page in enumerate(pages):
        text = page["text"]
        for idx, ocr_text in enumerate(ocr_by_page.get(i, []), start=1):
            text += format_ocr_block(idx, ocr_text)
        parts.append(text)
    doc.close()

    return repair_ligatures("".join(parts))
