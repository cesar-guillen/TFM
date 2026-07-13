import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BLOCK_RE = re.compile(r"[^\n].*?(?=\n\n+|\Z)", re.S)

TARGET_CHARS = 1200  # soft size a chunk is packed towards
MAX_CHARS = 2400  # hard cap; only a single oversized block (no blank lines) exceeds this

# pymupdf4llm wraps heading text in emphasis markers (`# **1. Intro**`); strip
# them so breadcrumbs, metadata, and classification see the plain title.
EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1")

# "5.1.2 Title"-style numbering. pymupdf4llm flattens most PDF headings to a
# single `#` level, losing the hierarchy; the numeric prefix recovers it.
NUMBER_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+")

# Classification stamps rendered as headings (page banners, TLP markings).
# They are not section structure: ignored for the heading stack entirely.
BANNER_RE = re.compile(r"do not distribute|confidential|proprietary|tlp:\s*(clear|white|green|amber|red)", re.I)

# Defender-guidance sections. These name techniques as things to prevent,
# detect, or clean up — not as observed adversary activity — so mapping them
# yields false positives. Matched against each heading with its numeric prefix
# removed; a match anywhere in the heading path taints the whole subtree.
# Bilingual: English + Spanish equivalents (stems chosen to stop before
# accented characters where possible; [oó]-style classes cover the rest, since
# OCR'd PDFs sometimes lose accents).
GUIDANCE_RE = re.compile(
    r"remediat|mitigat|recommend|countermeasure|containment|eradicat|\brecovery\b"
    r"|lessons learned|post-incident|action plan|action items|next steps"
    r"|best practice|hardening|how to protect|prevention|defensive measures"
    r"|protective measures|detection opportunit|hunting quer|sigma rule|yara rule"
    # Response-phase communication/notification sections ("5.5 Communication":
    # stakeholder notifications, breach disclosure — victim response actions,
    # not adversary activity; observed mapping T1491.001 from a notification
    # sentence). Bare "communication(s)"/"notification(s)" only as the whole
    # heading so technical headings like "C2 Communications" stay content;
    # the multi-word forms are specific enough to match anywhere.
    r"|^communications?$|^notifications?$|communication plan|notification plan"
    r"|stakeholder communication|crisis communication|breach notification"
    r"|internal communication|external communication"
    # Spanish: remediación/mitigación/recomendaciones, contramedidas,
    # contención/erradicación/recuperación (IR response phases), lecciones
    # aprendidas, post-incidente, plan de acción, próximos pasos, buenas/
    # mejores prácticas, acciones/medidas correctivas, endurecimiento/
    # bastionado (hardening), prevención/preventivas, medidas defensivas/de
    # protección, cómo proteger, oportunidades de detección, reglas sigma/yara.
    r"|remediac|mitigac|recomendac|contramedida"
    r"|contenci[oó]n|erradicac|recuperaci[oó]n"
    r"|lecciones aprendidas|post-?incidente|plan de acci|pr[oó]ximos pasos"
    r"|buenas pr[aá]cticas|mejores pr[aá]cticas|correctiv"
    r"|endurecimiento|bastionado|prevenci|preventiv|medidas defensivas"
    r"|medidas de protecci|c[oó]mo proteger|oportunidades de detecci"
    r"|reglas? sigma|reglas? yara"
    # Spanish mirrors of the communication/notification rules above:
    # comunicación/comunicaciones, notificación(es), plan de comunicación/
    # notificación, comunicación interna/externa/de crisis, notificación de
    # brecha — same whole-heading restriction for the bare forms.
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
    # Spanish: índice (TOC — also "índice de figuras"), tabla de contenido(s),
    # control del documento, referencias, bibliografía, agradecimientos,
    # sobre nosotros/quiénes somos, aviso legal, descargo/exención de
    # responsabilidad, derechos de autor, historial de versiones/revisiones/
    # cambios, control de versiones, glosario, lista de distribución.
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


def _clean_heading(text: str) -> str:
    text = text.strip().rstrip("#").strip()  # trailing ATX closers
    while True:
        unwrapped = EMPHASIS_RE.sub(r"\2", text)
        if unwrapped == text:
            return text
        text = unwrapped


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


def _hard_slice(text: str, base_start: int, target_chars: int) -> list[tuple[str, int, int]]:
    """Last-resort split for a single block that alone exceeds MAX_CHARS (e.g. a
    huge table or wall of text with no blank lines). Breaks at the nearest
    preceding whitespace instead of mid-word; offsets stay exact."""
    pieces = []
    n = len(text)
    pos = 0
    while pos < n:
        end = min(pos + target_chars, n)
        if end < n:
            ws = text.rfind(" ", pos, end)
            if ws > pos:
                end = ws
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

    def flush(role_override: SectionRole | None = None) -> None:
        nonlocal order
        if not buffer:
            return
        path = heading_path()
        body = "\n\n".join(b[0] for b in buffer)
        breadcrumb = " > ".join(path)
        text = f"{breadcrumb}\n\n{body}" if breadcrumb else body
        chunks.append(
            Chunk(
                text=text,
                heading_path=path,
                order=order,
                start_char=buffer[0][1],
                end_char=buffer[-1][2],
                section_role=role_override or classify_heading_path(path),
            )
        )
        order += 1

    def emit(text: str, start: int, end: int) -> None:
        nonlocal order
        path = heading_path()
        breadcrumb = " > ".join(path)
        full_text = f"{breadcrumb}\n\n{text}" if breadcrumb else text
        chunks.append(
            Chunk(
                text=full_text,
                heading_path=path,
                order=order,
                start_char=start,
                end_char=end,
                section_role=classify_heading_path(path),
            )
        )
        order += 1

    for text, start, end in blocks:
        heading_match = HEADING_RE.match(text)
        if heading_match:
            flush()
            buffer = []
            title = _clean_heading(heading_match.group(2))
            if not title or BANNER_RE.search(title):
                continue  # section break, but not part of the hierarchy
            level = effective_level(len(heading_match.group(1)), title)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title, bool(NUMBER_PREFIX_RE.match(title))))
            continue

        if _is_toc_block(text):
            # A table of contents without a "Contents" heading; keep it out of
            # whatever section it landed in and let indexing drop it.
            flush()
            buffer = [(text, start, end)]
            flush(role_override="boilerplate")
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
