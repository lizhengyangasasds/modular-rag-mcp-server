"""Markdown and plain-text document loader.

Loads `.md`, `.markdown`, and `.txt` files and returns a unified
``Document`` object with structured metadata.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from src.core.types import Document
from src.libs.loader.base_loader import BaseLoader


class MarkdownLoader(BaseLoader):
    """Loader for Markdown (.md / .markdown) and plain-text (.txt) files.

    Reads the file as UTF-8 text, extracts the title from the first
    ``# `` heading (if present), and returns a ``Document`` with the
    full text content and metadata.
    """

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt"}

    def load(self, file_path: str | Path) -> Document:
        """Load and parse a Markdown or text file.

        Args:
            file_path: Path to the file.

        Returns:
            ``Document`` with text content and populated metadata.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file type is not supported.
        """
        path = self._validate_file(file_path)

        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"MarkdownLoader only supports {self.SUPPORTED_EXTENSIONS}, "
                f"got: {suffix}"
            )

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_text = path.read_text(encoding="utf-8", errors="replace")

        doc_hash = self._sha256(path)
        doc_id = f"doc_{doc_hash[:16]}"

        title = self._extract_title(raw_text)
        section_count = self._count_sections(raw_text)

        metadata: dict[str, Any] = {
            "source_path": str(path),
            "doc_type": suffix.lstrip("."),
            "doc_hash": doc_hash,
            "file_size": path.stat().st_size,
            "line_count": raw_text.count("\n") + 1,
            "section_count": section_count,
        }
        if title:
            metadata["title"] = title

        return Document(
            id=doc_id,
            text=raw_text,
            metadata=metadata,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def _extract_title(text: str) -> str | None:
        first_lines = text.split("\n")[:20]
        for line in first_lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return None

    @staticmethod
    def _count_sections(text: str) -> int:
        return len(re.findall(r"^#{1,6}\s+.+$", text, re.MULTILINE))
