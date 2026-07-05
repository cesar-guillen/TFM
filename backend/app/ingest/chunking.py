import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BLOCK_RE = re.compile(r"[^\n].*?(?=\n\n+|\Z)", re.S)

TARGET_CHARS = 1200  # soft size a chunk is packed towards
MAX_CHARS = 2400  # hard cap; only a single oversized block (no blank lines) exceeds this


@dataclass
class Chunk:
    text: str
    heading_path: list[str]
    order: int
    start_char: int
    end_char: int


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
    Paragraphs are the atomic unit and are never split mid-paragraph; a section
    too large for one chunk is packed across multiple chunks along paragraph
    boundaries, carrying the last paragraph forward as overlap. Only a single
    block that alone exceeds `max_chars` (no internal blank line to split on)
    falls back to a whitespace-aware hard slice.
    """
    blocks = _split_blocks(markdown)
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[tuple[str, int, int]] = []
    order = 0

    def heading_path() -> list[str]:
        return [text for _, text in heading_stack]

    def flush() -> None:
        nonlocal order
        if not buffer:
            return
        body = "\n\n".join(b[0] for b in buffer)
        breadcrumb = " > ".join(heading_path())
        text = f"{breadcrumb}\n\n{body}" if breadcrumb else body
        chunks.append(
            Chunk(
                text=text,
                heading_path=heading_path(),
                order=order,
                start_char=buffer[0][1],
                end_char=buffer[-1][2],
            )
        )
        order += 1

    def emit(text: str, start: int, end: int) -> None:
        nonlocal order
        breadcrumb = " > ".join(heading_path())
        full_text = f"{breadcrumb}\n\n{text}" if breadcrumb else text
        chunks.append(
            Chunk(text=full_text, heading_path=heading_path(), order=order, start_char=start, end_char=end)
        )
        order += 1

    for text, start, end in blocks:
        heading_match = HEADING_RE.match(text)
        if heading_match:
            flush()
            buffer = []
            level = len(heading_match.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_match.group(2).strip()))
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
