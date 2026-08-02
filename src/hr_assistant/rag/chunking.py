"""Markdown chunking for the RAG pipeline.

The corpus is Hugo-flavoured markdown (GitLab handbook pages): YAML front
matter, headings, and occasional Hugo shortcodes. We split by headings so each
chunk stays on one topic, merge tiny sections and split oversized ones, and
prefix every chunk with its document title + section path — small chunks stay
meaningful on their own both for the embedder and for the LLM reading them.
"""

import re
from dataclasses import dataclass
from pathlib import Path

TARGET_CHUNK_CHARS = 1400  # merge sections until roughly this size
MAX_CHUNK_CHARS = 2200  # hard split threshold for oversized sections

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SHORTCODE_RE = re.compile(r"\{\{[%<].*?[%>]\}\}", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")


@dataclass
class Chunk:
    id: str
    text: str  # what gets embedded and returned to the LLM
    source: str  # file name, e.g. "time-off-types.md"
    title: str  # document title from front matter
    section: str  # heading path, e.g. "Flexible Paid Time Off (PTO) > Overview"


def _parse_front_matter(raw: str) -> tuple[str, str]:
    """Return (title, body). Title falls back to the file's first heading."""
    title = ""
    match = _FRONT_MATTER_RE.match(raw)
    body = raw
    if match:
        body = raw[match.end():]
        for line in match.group(1).splitlines():
            if line.strip().startswith("title:"):
                title = line.split(":", 1)[1].strip().strip("\"'")
                break
    return title, body


def _clean(text: str) -> str:
    text = _SHORTCODE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split body into (heading_path, content) sections by markdown headings."""
    sections: list[tuple[str, str]] = []
    path: dict[int, str] = {}
    current_lines: list[str] = []
    current_path = ""

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_path, content))

    in_code_block = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
        heading = None if in_code_block else _HEADING_RE.match(line)
        if heading:
            flush()
            current_lines = []
            level = len(heading.group(1))
            path[level] = heading.group(2).strip()
            for deeper in [k for k in path if k > level]:
                del path[deeper]
            current_path = " > ".join(path[k] for k in sorted(path) if k > 1) or path.get(1, "")
        else:
            current_lines.append(line)
    flush()
    return sections


def _split_long(content: str) -> list[str]:
    """Split an oversized section on paragraph boundaries."""
    paragraphs = content.split("\n\n")
    parts: list[str] = []
    buf = ""
    for para in paragraphs:
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) > MAX_CHUNK_CHARS and buf:
            parts.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


def chunk_markdown_file(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    title, body = _parse_front_matter(raw)
    body = _clean(body)
    if not title:
        title = path.stem.replace("-", " ").title()

    chunks: list[Chunk] = []
    buf_text = ""
    buf_section = ""

    def emit(section: str, content: str) -> None:
        header = f"[{title} — {section}]" if section else f"[{title}]"
        chunks.append(
            Chunk(
                id=f"{path.name}#{len(chunks)}",
                text=f"{header}\n{content}",
                source=path.name,
                title=title,
                section=section,
            )
        )

    for section, content in _split_sections(body):
        if len(content) > MAX_CHUNK_CHARS:
            if buf_text:
                emit(buf_section, buf_text)
                buf_text = ""
            for part in _split_long(content):
                emit(section, part)
            continue
        if buf_text and len(buf_text) + len(content) > TARGET_CHUNK_CHARS:
            emit(buf_section, buf_text)
            buf_text = ""
        if not buf_text:
            buf_section = section
        buf_text = f"{buf_text}\n\n{content}".strip() if buf_text else content
    if buf_text:
        emit(buf_section, buf_text)
    return chunks


def chunk_directory(docs_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("*.md")):
        if path.name.upper().startswith("ATTRIBUTION"):
            continue
        chunks.extend(chunk_markdown_file(path))
    return chunks
