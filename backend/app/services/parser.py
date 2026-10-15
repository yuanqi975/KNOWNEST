from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ";", "；"]
Strategy = Literal["auto", "heading", "heuristic", "recursive", "legacy"]


class ChunkingConfig(BaseModel):
    strategy: Strategy = "auto"
    chunk_size: int = Field(default=512, ge=100, le=10000)
    chunk_overlap: int = Field(default=80, ge=0, le=5000)
    separators: list[str] = Field(default_factory=lambda: DEFAULT_SEPARATORS.copy())
    token_limit: int = Field(default=0, ge=0, le=8192)
    languages: list[str] = Field(default_factory=list)
    enable_parent_child: bool = True
    parent_chunk_size: int = Field(default=4096, ge=512, le=8192)

    @field_validator("separators")
    @classmethod
    def validate_separators(cls, value: list[str]) -> list[str]:
        value = list(dict.fromkeys(item for item in value if item))
        return value or DEFAULT_SEPARATORS.copy()

    @model_validator(mode="after")
    def validate_relationships(self) -> "ChunkingConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.enable_parent_child and self.parent_chunk_size < self.chunk_size:
            raise ValueError("parent_chunk_size must be greater than or equal to chunk_size")
        return self


@dataclass
class ParsedChunk:
    content: str
    sequence: int
    page_number: int | None = None
    paragraph_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    heading_path: list[str] | None = None
    strategy: str = "recursive"
    chunk_level: str = "single"
    parent_sequence: int | None = None


def extract_text(path: Path, file_type: str) -> str:
    if file_type == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if file_type == ".docx":
        from docx import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = DocxDocument(str(path))
        blocks: list[str] = []
        for block in document.element.body.iterchildren():
            if block.tag.endswith("}p"):
                content = Paragraph(block, document).text
            elif block.tag.endswith("}tbl"):
                table = Table(block, document)
                content = "\n".join(
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for row in table.rows
                )
            else:
                continue
            if content.strip():
                blocks.append(content)
        return "\n\n".join(blocks)
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()


def approximate_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    other = max(0, len(text) - cjk)
    return max(1, int(cjk + other / 4)) if text else 0


def profile_document(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    headings = [line for line in lines if re.match(r"^#{1,6}\s+\S+", line)]
    numbered = [line for line in lines if re.match(r"^(?:\d+(?:\.\d+)*[.)]|第\s*[一二三四五六七八九十百千万0-9]+\s*[章节])", line)]
    chapter_markers = [line for line in lines if re.match(r"^(?:chapter|section|kapitel)\s+\w+", line, re.I)]
    uppercase = [line for line in lines if len(line) >= 4 and line.upper() == line and re.search(r"[A-Z]", line)]
    visual = [line for line in lines if re.fullmatch(r"[-_=*~]{3,}", line)]
    return {"char_count": len(normalized), "line_count": len(lines), "heading_count": len(headings), "numbered_section_count": len(numbered), "chapter_marker_count": len(chapter_markers), "uppercase_title_count": len(uppercase), "visual_separator_count": len(visual), "form_feed_count": text.count("\f"), "languages": [lang for lang, pattern in (("zh", r"[\u3400-\u9fff]"), ("en", r"[A-Za-z]"), ("de", r"\b(?:der|die|das|und|Kapitel)\b")) if re.search(pattern, text, re.I)]}


def _boundary(text: str, start: int, limit: int, separators: list[str]) -> int:
    if limit >= len(text):
        return len(text)
    candidates = [text.rfind(separator, start, limit) + len(separator) for separator in separators if text.rfind(separator, start, limit) >= 0]
    valid = [candidate for candidate in candidates if candidate > start + max(1, (limit - start) // 2)]
    return max(valid) if valid else limit


def _window_chunks(text: str, config: ChunkingConfig, *, base_offset: int = 0, heading_path: list[str] | None = None, strategy: str = "recursive", sequence_start: int = 0) -> list[ParsedChunk]:
    if config.token_limit:
        effective_size = min(config.chunk_size, max(100, config.token_limit * 4))
        config = config.model_copy(update={"chunk_size": effective_size, "chunk_overlap": min(config.chunk_overlap, max(0, effective_size - 1), max(0, config.token_limit * 2))})
    chunks: list[ParsedChunk] = []
    start = 0
    sequence = sequence_start
    while start < len(text):
        limit = min(len(text), start + config.chunk_size)
        end = _boundary(text, start, limit, config.separators)
        raw = text[start:end]
        content = raw.strip()
        if content:
            left_trim = len(raw) - len(raw.lstrip())
            right_trim = len(raw) - len(raw.rstrip())
            chunks.append(ParsedChunk(content, sequence, char_start=base_offset + start + left_trim, char_end=base_offset + end - right_trim, heading_path=heading_path, strategy=strategy))
            sequence += 1
        if end >= len(text):
            break
        next_start = max(start + 1, end - config.chunk_overlap)
        start = next_start if next_start > start else end
    return chunks


def _heading_chunks(text: str, config: ChunkingConfig) -> list[ParsedChunk]:
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    if not matches:
        return []
    chunks: list[ParsedChunk] = []
    stack: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        level, title = len(match.group(1)), match.group(2).strip()
        stack = [(depth, name) for depth, name in stack if depth < level]
        stack.append((level, title))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_start = match.start()
        chunks.extend(_window_chunks(text[section_start:end], config, base_offset=section_start, heading_path=[name for _, name in stack], strategy="heading", sequence_start=len(chunks)))
    return chunks


def _heuristic_chunks(text: str, config: ChunkingConfig) -> list[ParsedChunk]:
    separators = ["\f", "\n\n", "\n"] + [item for item in config.separators if item not in {"\n\n", "\n"}]
    tuned = config.model_copy(update={"separators": separators})
    return _window_chunks(text.replace("\f", "\n\n"), tuned, strategy="heuristic")


def _valid_chunks(chunks: list[ParsedChunk], config: ChunkingConfig) -> bool:
    if not chunks:
        return False
    sizes = [len(item.content) for item in chunks]
    tiny = sum(size < max(24, config.chunk_size // 10) for size in sizes)
    oversized = sum(size > config.chunk_size * 1.25 for size in sizes)
    return tiny <= max(3, len(chunks) // 2) and oversized == 0


def split_document(text: str, config: ChunkingConfig | None = None) -> tuple[list[ParsedChunk], dict[str, Any]]:
    config = config or ChunkingConfig()
    normalized = normalize_text(text)
    profile = profile_document(normalized)
    candidates: list[tuple[str, list[ParsedChunk]]] = []
    if config.strategy in {"auto", "heading"}:
        candidates.append(("heading", _heading_chunks(normalized, config)))
    if config.strategy in {"auto", "heuristic"}:
        candidates.append(("heuristic", _heuristic_chunks(normalized, config)))
    if config.strategy in {"auto", "recursive", "legacy", "heading", "heuristic"}:
        candidates.append(("recursive", _window_chunks(normalized, config, strategy="recursive")))
    selected_name, selected = "recursive", []
    rejected: list[dict[str, str]] = []
    for name, chunks in candidates:
        if _valid_chunks(chunks, config):
            selected_name, selected = name, chunks
            break
        rejected.append({"strategy": name, "reason": "切分结果为空、过多短片段或存在超长片段"})
    for index, chunk in enumerate(selected):
        chunk.sequence = index
        chunk.strategy = selected_name
    stats = {"selected_strategy": selected_name, "profile": profile, "rejected_strategies": rejected, "chunk_count": len(selected), "avg_chars": round(sum(len(item.content) for item in selected) / len(selected), 1) if selected else 0, "min_chars": min((len(item.content) for item in selected), default=0), "max_chars": max((len(item.content) for item in selected), default=0), "approx_tokens": sum(approximate_tokens(item.content) for item in selected)}
    return selected, stats


def split_text(text: str, target_chars: int = 2400, overlap: int = 320) -> list[ParsedChunk]:
    config = ChunkingConfig(strategy="recursive", chunk_size=target_chars, chunk_overlap=min(overlap, max(0, target_chars - 1)), enable_parent_child=False)
    chunks, _ = split_document(text, config)
    return chunks


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size
