"""
Loader Module.

This package contains document loader components:
- Base loader class
- PDF loader
- File integrity checker
"""

from src.libs.loader.base_loader import BaseLoader
from src.libs.loader.file_integrity import FileIntegrityChecker, SQLiteIntegrityChecker
from src.libs.loader.markdown_loader import MarkdownLoader
from src.libs.loader.pdf_quality_checker import (
    DocumentQualityError,
    PdfQualityChecker,
    QualityReport,
)

__all__ = [
    "BaseLoader",
    "PdfLoader",
    "MarkdownLoader",
    "FileIntegrityChecker",
    "SQLiteIntegrityChecker",
    "PdfQualityChecker",
    "QualityReport",
    "DocumentQualityError",
]


def __getattr__(name: str):
    if name == "PdfLoader":
        from src.libs.loader.pdf_loader import PdfLoader

        return PdfLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
