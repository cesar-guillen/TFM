"""OCR for embedded screenshots (console output, dashboards, sandbox logs) that
pymupdf's text layer cannot see — see CLAUDE.md's Known limitations.

Retrieval-only by design: OCR'd text is appended to the markdown so it can be
embedded and BM25-matched like any other content. It is NOT exempted from the
mapper's verbatim evidence-quote gate (`_evidence_context` in mapper.py) —
well-OCR'd text (Sysmon/EDR log tables, monospace, high-contrast) comes
through close to verbatim, so a badly garbled OCR line simply fails to
validate as a quote and is correctly rejected on its own. Two failure modes
stay unrecoverable regardless of gating: black redaction boxes (genuinely
unreadable, not an OCR defect) and yellow highlight overlays on command-name
tokens, which OCR inconsistently — usually masked by column redundancy in
EDR-table screenshots (the same tool name repeats in an adjacent column).

Degrades to a no-op if `tesseract` isn't installed (see backend/Dockerfile).
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pymupdf

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

try:
    import pytesseract

    _TESSERACT_OK = True
except ImportError:
    _TESSERACT_OK = False

# Render DPI for the clipped region before OCR. Higher than a typical embedded
# screenshot's native resolution — upscaling gives tesseract more pixels per
# character, which measurably helps on the small fonts common in dashboard
# and terminal screenshots.
OCR_DPI = 300

# Skip images too small to hold meaningful text (icons, bullets, logos).
MIN_DIM_PT = 60

# Quality gate, same spirit as repair_ligatures(): reject OCR output that's
# too short or too non-alphanumeric to be real text (a pure flowchart/logo
# image OCRs to near-empty or symbol noise) rather than inject garbage into
# the markdown a human or the mapper would have to wade through.
MIN_CHARS = 20
MIN_ALNUM_RATIO = 0.4
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")

# pytesseract shells out to the tesseract binary per call, so a thread pool
# gives real OS-level parallelism. LOW ON PURPOSE, not os.cpu_count(): each
# tesseract call is already internally multi-threaded, so stacking more than
# ~2-3 external workers oversubscribes the same cores instead of adding
# throughput (measured worse at 8/16; capping tesseract's own threads to
# allow a wider pool was also tried and measured worse still).
MAX_OCR_WORKERS = 3


def _passes_quality_gate(text: str) -> bool:
    text = text.strip()
    if len(text) < MIN_CHARS:
        return False
    alnum = len(_ALNUM_RE.findall(text))
    return alnum / len(text) >= MIN_ALNUM_RATIO


def _render_page_images(page: pymupdf.Page, images: list[dict]) -> list["Image.Image"]:
    """Rasterize each real image's region to a PIL image. Kept single-threaded
    and sequential: pymupdf Page/Document objects aren't safe to call
    concurrently, but rendering is cheap (~ms) — the OCR call below is where
    the real cost lives, and that's what actually gets parallelized."""
    rendered = []
    for img in images:
        bbox = img.get("bbox")
        if bbox is None:
            continue
        rect = pymupdf.Rect(bbox)
        if rect.width < MIN_DIM_PT and rect.height < MIN_DIM_PT:
            continue
        try:
            pix = page.get_pixmap(clip=rect, dpi=OCR_DPI)
            rendered.append(pix.pil_image())
        except Exception:  # noqa: BLE001 - a single bad image must not fail ingest
            logger.warning("OCR render failed on one image, skipping", exc_info=True)
    return rendered


def _ocr_one(pil_image) -> str | None:
    try:
        text = pytesseract.image_to_string(pil_image)
    except Exception:  # noqa: BLE001 - a single bad image must not fail ingest
        logger.warning("OCR failed on one image, skipping", exc_info=True)
        return None
    return text.strip() if _passes_quality_gate(text) else None


def ocr_document_images(
    doc: pymupdf.Document, pages: list[dict]
) -> dict[int, list[str]]:
    """OCR every real (non-decorative) image across the whole document, image
    detection reused from pymupdf4llm's own `page_chunks=True` output (trusts
    the same detection it already did, rather than a second, possibly-
    inconsistent extraction pass) — parallelized across pages since each
    tesseract call is an independent subprocess. Returns {page_index: [ocr
    text, ...]} in each page's original image order; a page with no qualifying
    OCR text is simply absent from the dict."""
    if not _TESSERACT_OK:
        return {}

    # Render (sequential, pymupdf-bound) first, then OCR (parallel) — keeps
    # every pymupdf call on the main thread while the expensive subprocess
    # work runs concurrently.
    per_page_images: dict[int, list] = {}
    for i, page_dict in enumerate(pages):
        images = page_dict.get("images") or []
        if not images:
            continue
        rendered = _render_page_images(doc[i], images)
        if rendered:
            per_page_images[i] = rendered

    if not per_page_images:
        return {}

    tasks = [(i, pil) for i, rendered in per_page_images.items() for pil in rendered]
    with ThreadPoolExecutor(max_workers=MAX_OCR_WORKERS) as pool:
        results = list(pool.map(_ocr_one, [pil for _, pil in tasks]))

    out: dict[int, list[str]] = {}
    for (page_i, _), text in zip(tasks, results):
        if text:
            out.setdefault(page_i, []).append(text)
    return out


def format_ocr_block(index: int, text: str) -> str:
    """Markdown block for one page's Nth OCR'd image, clearly tagged so a
    reader (human or the mapper LLM) can see this text came from an image,
    not the report's typeset body."""
    return f"\n\n**[OCR — image {index} on this page]**\n\n```\n{text}\n```\n"
