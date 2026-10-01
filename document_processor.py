

from __future__ import annotations
from pathlib import Path
from typing import List
import re

import pdfplumber
import docx

from config import CHUNK_SIZE, CHUNK_OVERLAP


def extract_text(file_path: Path) -> str:
    """Extract raw text from a PDF, DOCX or TXT file."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(file_path)
    elif suffix in (".docx",):
        return _extract_docx(file_path)
    elif suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def _extract_pdf(file_path: Path) -> str:
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_docx(file_path: Path) -> str:
    document = docx.Document(str(file_path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def clean_text(text: str) -> str:
    """Normalize whitespace and strip noisy control characters."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split text into overlapping chunks on paragraph/sentence boundaries where
    possible, falling back to a hard character split.
    """
    text = clean_text(text)
    if not text:
        return []

    # First split on paragraphs, then greedily pack into chunk_size windows.
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 1 <= chunk_size:
            current = f"{current}\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            # If a single paragraph is longer than chunk_size, hard-split it.
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[i:i + chunk_size])
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # Apply overlap between consecutive chunks for better retrieval recall.
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            overlapped.append((prev_tail + "\n" + chunks[i]).strip())
        return overlapped

    return chunks


def process_file(file_path: Path) -> List[str]:
    """Full pipeline: extract -> clean -> chunk."""
    raw = extract_text(file_path)
    return chunk_text(raw)
