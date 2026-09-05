import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BLOCK_RE = re.compile(r"[^\n].*?(?=\n\n+|\Z)", re.S)

TARGET_CHARS = 1200  # soft size a chunk is packed towards
MAX_CHARS = 2400  # hard cap; only a single oversized block (no blank lines) exceeds this

# pymupdf4llm wraps heading text in emphasis markers (`# **1. Intro**`).
EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")

# "5.1.2 Title" numbering, from which heading depth is recovered: the PDF's
# own heading levels are unreliable.
NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+")

# Some PDFs render sub-headings as bold body text, which HEADING_RE cannot
# see: the parent section is then packed by size alone and one chunk straddles
# several unrelated topics. A block that is exactly one bold span on one line
# AND carries a numeric prefix is such a heading. The numeric requirement is
# what keeps bold *emphasis* out of the hierarchy ("**1.4 TB** of data…" is
# prose, "**Report Reference:** …" is metadata, table headers are multi-span).
BOLD_HEADING_RE = re.compile(r"^\*\*(?!\s)([^*\n]{1,120}?)\s*\*\*$")

# Classification stamps rendered as headings (page banners, TLP markings).
# They are not section structure: ignored for the heading stack entirely.
BANNER_RE = re.compile(r"do not distribute|confidential|proprietary|tlp:\s*(clear|white|green|amber|red)", re.I)

# Defender-guidance sections: they name techniques as things to prevent or
# clean up, not as observed adversary activity, so mapping them yields false
# positives. Matched against each heading with its numeric prefix removed; a
# match anywhere in the path taints the whole subtree. English + Spanish, with
# [oó]-style classes because OCR sometimes drops accents. Bare
# "detection"/"response" are deliberately absent — they head narrative
# timelines.
GUIDANCE_RE = re.compile(
    r"remediat|mitigat|recommend|countermeasure|containment|eradicat|\brecovery\b"
    r"|lessons learned|post-incident|action plan|action items|next steps"
    r"|best practice|hardening|how to protect|prevention|defensive measures"
    r"|protective measures|detection opportunit|hunting quer|sigma rule|yara rule"
    # REJECTED 2026-09-03 (tried and reverted — see CLAUDE.md's "Detection-
    # section boilerplate" note): classifying "Detections"/"Sigma"/"Diamond
    # Model"/"Timeline Indicators" headings as guidance was tested on 3 real
    # de-leaked DFIR Report intrusions, both verdict modes. It cut FPs
    # meaningfully on 1 of 3 (rdp-ransomhub: unexpected/run 34.8->29.8 under
    # menu) but cost real recall on another (confluence-lockbit: exact recall
    # 71.4%->63.1% under menu, 71.4%->67.9% under independent) — below this
    # project's own 2-of-3 bar for keeping a change. Root cause confirmed, not
    # assumed: T1059.003 and T1003.001 flipped from solid hits to misses even
    # though their evidence (mimikatz x12, lsass x2) survives untouched in the
    # narrative — removing ~10 chunks of Sigma/Detections text reshuffled
    # chunk boundaries for unrelated spans, the same composition-sensitivity
    # mechanism cycles 5b/7/12 already measured. If revisited: try demoting
    # these sections' evidence weight at the VERDICT stage instead of
    # removing the chunks from indexing entirely, since the ingest-time
    # removal is what perturbs unrelated chunk boundaries.
    # Response-phase communication/notification sections (stakeholder
    # notifications, breach disclosure). The bare forms match only as a whole
    # heading, so "C2 Communications" stays content.
    r"|^communications?$|^notifications?$|communication plan|notification plan"
    r"|stakeholder communication|crisis communication|breach notification"
    r"|internal communication|external communication"
    # Spanish equivalents of the rules above.
    r"|remediac|mitigac|recomendac|contramedida"
    r"|contenci[oó]n|erradicac|recuperaci[oó]n"
    r"|lecciones aprendidas|post-?incidente|plan de acci|pr[oó]ximos pasos"
    r"|buenas pr[aá]cticas|mejores pr[aá]cticas|correctiv"
    r"|endurecimiento|bastionado|prevenci|preventiv|medidas defensivas"
    r"|medidas de protecci|c[oó]mo proteger|oportunidades de detecci"
    r"|reglas? sigma|reglas? yara"
    # Spanish mirrors of the communication/notification rules.
    r"|^comunicaci[oó]n(es)?$|^notificaci[oó]n(es)?$"
    r"|plan de comunicaci|plan de notificaci"
    r"|comunicaci[oó]n (interna|externa|de crisis)|notificaci[oó]n de brecha",
    re.I,
)

# Document furniture with no mappable content: front/back matter and metadata.
BOILERPLATE_RE = re.compile(
    r"table of contents|^contents$|document control|references$|bibliography"
    r"|acknowledg|about us|disclaimer|legal notice|copyright|revision history"
    r"|version history|document history|glossary|distribution list"
    # Spanish equivalents.
    r"|[ií]ndice|tabla de contenidos?|control del? documento|referencias$"
    r"|bibliograf|agradecimient|sobre nosotros|qui[eé]nes somos"
    r"|aviso legal|descargo de responsabilidad|exenci[oó]n de responsabilidad"
    r"|derechos de autor|historial de (versiones|revisiones|cambios)"
    r"|control de versiones|glosario|lista de distribuci",
    re.I,
)

# A line of a table-of-contents rendered as text: "Some Section ....... 12".
DOT_LEADER_RE = re.compile(r"\.{2,}\s*\d{1,4}\s*$")

SectionRole = str  # "content" | "guidance" | "boilerplate"


@dataclass
class Chunk:
    text: str
    heading_path: list[str]
    order: int
    start_char: int
    end_char: int
    section_role: SectionRole = "content"


def classify_heading_path(heading_path: list[str]) -> SectionRole:
    """Role of the section a heading path leads to. Walks deepest-first so the
    nearest classified ancestor wins: an unmatched subsection like "What Went
    Well" inherits `guidance` from its "Lessons Learned" parent."""
    for heading in reversed(heading_path):
        title = NUMBER_PREFIX_RE.sub("", heading)
        if GUIDANCE_RE.search(title):
            return "guidance"
        if BOILERPLATE_RE.search(title):
            return "boilerplate"
    return "content"


# A "Key: value" metadata line, as found on title pages.
KEY_VALUE_RE = re.compile(r"^[^:\n]{1,40}:\s*\S")


def classify_untitled(body: str) -> SectionRole:
    """Role of a chunk with no heading path — the preamble before the first
    heading (title page, banners, report metadata), which
    classify_heading_path cannot see. Furniture lines are banners, boilerplate
    keywords, key-value metadata and short unpunctuated fragments; a majority
    of them marks the chunk boilerplate, while a prose introduction stays
    content.

    Applied to the FIRST chunk only: reports that style every heading as bold
    text have empty heading paths throughout, and classifying all of that
    misfiles real timeline chunks (timestamps look like metadata)."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return "boilerplate"
    furniture = 0
    for line in lines:
        bare = re.sub(r"[*_#]", "", line).strip()
        if (
            BANNER_RE.search(bare)
            or BOILERPLATE_RE.search(bare)
            or KEY_VALUE_RE.match(bare)
            or (len(bare) < 60 and not bare.endswith((".", "!", "?", ":")))
        ):
            furniture += 1
    return "boilerplate" if furniture * 2 >= len(lines) else "content"


def _clean_heading(text: str) -> str:
    text = text.strip().rstrip("#").strip()  # trailing ATX closers
    while True:
        unwrapped = EMPHASIS_RE.sub(r"\2", text)
        if unwrapped == text:
            return text
        text = unwrapped


def _bold_heading(block: str) -> str | None:
    """The title of a bold-rendered numbered sub-heading, or None. See
    BOLD_HEADING_RE — the whole block must be the single bold span."""
    match = BOLD_HEADING_RE.match(block.strip())
    if match and NUMBER_PREFIX_RE.match(match.group(1)):
        return match.group(1)
    return None


def _is_toc_block(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    hits = sum(1 for line in lines if DOT_LEADER_RE.search(line))
    return hits >= 3 and hits * 2 >= len(lines)


def _split_blocks(markdown: str) -> list[tuple[str, int, int]]:
    """Split markdown into blank-line-delimited blocks (paragraphs, headings,
    whole tables — anything without an internal blank line stays atomic)."""
    blocks = []
    for m in BLOCK_RE.finditer(markdown):
        text = m.group().strip()
        if text:
            blocks.append((text, m.start(), m.end()))
    return blocks


# Where a hard slice may cut, best first: end of line (keeps a table row
# whole), end of sentence, any whitespace. A boundary counts only if it leaves
# the piece at least half the target size.
_SLICE_BOUNDARY_RES = (re.compile(r"\n"), re.compile(r"[.!?][\"')]?\s"), re.compile(r"\s"))


def _hard_slice(text: str, base_start: int, target_chars: int) -> list[tuple[str, int, int]]:
    """Last-resort split for a single block that alone exceeds MAX_CHARS (e.g. a
    huge table or wall of text with no blank lines). Prefers to break at a line
    end, then a sentence end, then any whitespace — so rows and sentences stay
    whole whenever the block allows it; offsets stay exact."""
    pieces = []
    n = len(text)
    pos = 0
    while pos < n:
        end = min(pos + target_chars, n)
        if end < n:
            floor = pos + target_chars // 2
            for boundary_re in _SLICE_BOUNDARY_RES:
                cuts = [m.end() for m in boundary_re.finditer(text, floor, end)]
                if cuts:
                    end = cuts[-1]
                    break
        piece = text[pos:end].strip()
        if piece:
            pieces.append((piece, base_start + pos, base_start + end))
        pos = end
    return pieces


def chunk_markdown(
    markdown: str,
    target_chars: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
) -> list[Chunk]:
    """Section-aware, overlapping chunker.

    Headings define section boundaries (never merged across a heading change).
    A heading's depth comes from its numeric prefix when it has one ("5.1" is a
    child of "5."), recovering the hierarchy pymupdf4llm flattens; unnumbered
    headings inside a numbered section nest one level below it. Every chunk is
    tagged with a `section_role` from its heading path (see
    `classify_heading_path`), so indexing can drop defender-guidance and
    boilerplate sections instead of mapping them.

    Paragraphs are the atomic unit and are never split mid-paragraph; a section
    too large for one chunk is packed across multiple chunks along paragraph
    boundaries, carrying the last paragraph forward as overlap. Only a single
    block that alone exceeds `max_chars` (no internal blank line to split on)
    falls back to a whitespace-aware hard slice.
    """
    blocks = _split_blocks(markdown)
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str, bool]] = []  # (level, title, numbered)
    buffer: list[tuple[str, int, int]] = []
    order = 0

    def heading_path() -> list[str]:
        return [title for _, title, _ in heading_stack]

    def effective_level(md_level: int, title: str) -> int:
        number = NUMBER_PREFIX_RE.match(title)
        if number:
            # Depth follows the numbering; level 1 stays reserved for an
            # unnumbered document title above the numbered sections.
            return number.group(1).count(".") + 2
        for level, _, numbered in reversed(heading_stack):
            if numbered:
                return level + 1
        return md_level

    def emit(body: str, start: int, end: int, role: SectionRole | None = None) -> None:
        nonlocal order
        path = heading_path()
        breadcrumb = " > ".join(path)
        if role is None:
            # An untitled chunk can only be classified from its own text, and
            # only the document's preamble is worth classifying that way.
            role = (
                classify_heading_path(path)
                if path
                else (classify_untitled(body) if order == 0 else "content")
            )
        chunks.append(
            Chunk(
                text=f"{breadcrumb}\n\n{body}" if breadcrumb else body,
                heading_path=path,
                order=order,
                start_char=start,
                end_char=end,
                section_role=role,
            )
        )
        order += 1

    def flush(role: SectionRole | None = None) -> None:
        if not buffer:
            return
        emit("\n\n".join(b[0] for b in buffer), buffer[0][1], buffer[-1][2], role)

    for text, start, end in blocks:
        heading_match = HEADING_RE.match(text)
        bold_title = None if heading_match else _bold_heading(text)
        if heading_match or bold_title:
            flush()
            buffer = []
            title = _clean_heading(heading_match.group(2)) if heading_match else bold_title
            if not title or BANNER_RE.search(title):
                continue  # section break, but not part of the hierarchy
            # A bold heading always carries a numeric prefix, so effective_level
            # resolves its depth from the numbering and never reads md_level.
            level = effective_level(len(heading_match.group(1)) if heading_match else 6, title)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title, bool(NUMBER_PREFIX_RE.match(title))))
            continue

        if _is_toc_block(text):
            # A table of contents without a "Contents" heading; keep it out of
            # whatever section it landed in and let indexing drop it.
            flush()
            buffer = [(text, start, end)]
            flush("boilerplate")
            buffer = []
            continue

        if len(text) > max_chars:
            flush()
            buffer = []
            for piece_text, piece_start, piece_end in _hard_slice(text, start, target_chars):
                emit(piece_text, piece_start, piece_end)
            continue

        projected = sum(len(b[0]) for b in buffer) + 2 * len(buffer) + len(text)
        if buffer and projected > target_chars:
            last = buffer[-1]
            flush()
            buffer = [last]
        buffer.append((text, start, end))

    flush()
    return chunks
