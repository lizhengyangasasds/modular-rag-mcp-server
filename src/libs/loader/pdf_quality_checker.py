"""PDF text-layer quality checker for detecting scanned and noisy documents.

This module evaluates the quality of extracted text from PDF files before
ingestion. It detects:
- Scanned PDFs (image-only, no extractable text)
- Noisy PDFs (corrupt/malformed text layer, encoding artifacts)
- Low-density PDFs (mostly whitespace or non-text content)

Integration Point: Runs between PdfLoader and DocumentChunker in the
IngestionPipeline, enabling early rejection or OCR-fallback for low-quality
PDFs rather than wasting compute on meaningless chunks.

Usage:
    >>> checker = PdfQualityChecker(min_valid_ratio=0.80)
    >>> report = checker.check("path/to/document.pdf")
    >>> if report.is_poor_quality:
    ...     print(f"Recommendation: {report.recommendation}")
    >>> else:
    ...     print("PDF is clean, proceed with ingestion")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    """Result of a PDF text-layer quality assessment.

    Attributes:
        file_path: Path to the assessed PDF.
        page_count: Total number of pages in the PDF.
        sampled_pages: Number of pages sampled for assessment (first N).
        valid_char_count: Count of valid (printable, non-noise) characters.
        total_char_count: Total characters in sampled pages.
        valid_char_ratio: valid_char_count / total_char_count.
        text_density: Estimated text density vs theoretical page capacity.
        is_scanned: True if the PDF appears to be scanned (no real text layer).
        is_noisy: True if the text layer contains significant noise artifacts.
        is_poor_quality: True if any quality threshold is violated.
        quality_level: Human-readable quality tier (excellent/good/fair/poor/scanned).
        recommendation: Actionable next step for the ingestion pipeline.
        per_page_reports: Per-page breakdown for diagnostics.
    """

    file_path: str
    page_count: int
    sampled_pages: int
    valid_char_count: int
    total_char_count: int
    valid_char_ratio: float
    text_density: float
    is_scanned: bool = False
    is_noisy: bool = False
    is_poor_quality: bool = False
    quality_level: str = "unknown"
    recommendation: str = "unknown"
    per_page_reports: List["PageReport"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "sampled_pages": self.sampled_pages,
            "valid_char_count": self.valid_char_count,
            "total_char_count": self.total_char_count,
            "valid_char_ratio": round(self.valid_char_ratio, 4),
            "text_density": round(self.text_density, 4),
            "is_scanned": self.is_scanned,
            "is_noisy": self.is_noisy,
            "is_poor_quality": self.is_poor_quality,
            "quality_level": self.quality_level,
            "recommendation": self.recommendation,
            "per_page": [p.to_dict() for p in self.per_page_reports],
        }


@dataclass
class PageReport:
    """Per-page quality breakdown for diagnostic purposes."""

    page: int
    valid_char_count: int
    total_char_count: int
    valid_char_ratio: float
    is_suspicious: bool
    suspicion_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "valid_char_count": self.valid_char_count,
            "total_char_count": self.total_char_count,
            "valid_char_ratio": round(self.valid_char_ratio, 4),
            "is_suspicious": self.is_suspicious,
            "suspicion_reasons": self.suspicion_reasons,
        }


class PdfQualityChecker:
    """Checks PDF text-layer quality before ingestion.

    Evaluates the text extracted from a PDF (e.g. by MarkItDown) and returns
    a QualityReport with:
    - Valid character ratio (clean chars / total chars)
    - Text density (chars vs theoretical page capacity)
    - Scanned/noisy detection flags
    - Actionable recommendation

    Configuration:
        min_valid_ratio: Minimum valid_char_ratio to pass (default: 0.80).
        min_text_density: Minimum text_density to pass (default: 0.20).
        max_noise_ratio: Maximum allowed noise char ratio (default: 0.20).
        check_first_n_pages: How many leading pages to sample (default: 3).
        fail_on_scanned: If True, scanned PDFs raise DocumentQualityError
            instead of returning a report with is_poor_quality=True.

    Design Principles:
        - Non-destructive: Does not modify the PDF or extracted text.
        - Fast: Only samples the first N pages, not the entire document.
        - Informative: Reports are self-contained with actionable recommendations.
    """

    DEFAULT_MIN_VALID_RATIO = 0.80
    DEFAULT_MIN_TEXT_DENSITY = 0.20
    DEFAULT_MAX_NOISE_RATIO = 0.20
    DEFAULT_CHECK_FIRST_N_PAGES = 3
    DEFAULT_ESTIMATED_CHARS_PER_PAGE = 3000

    def __init__(
        self,
        min_valid_ratio: float = DEFAULT_MIN_VALID_RATIO,
        min_text_density: float = DEFAULT_MIN_TEXT_DENSITY,
        max_noise_ratio: float = DEFAULT_MAX_NOISE_RATIO,
        check_first_n_pages: int = DEFAULT_CHECK_FIRST_N_PAGES,
        fail_on_scanned: bool = False,
    ):
        self.min_valid_ratio = min_valid_ratio
        self.min_text_density = min_text_density
        self.max_noise_ratio = max_noise_ratio
        self.check_first_n_pages = check_first_n_pages
        self.fail_on_scanned = fail_on_scanned

    def check(self, file_path: Union[str, Path]) -> QualityReport:
        """Assess the text-layer quality of a PDF.

        Args:
            file_path: Path to the PDF file.

        Returns:
            QualityReport with quality metrics and recommendation.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            DocumentQualityError: If fail_on_scanned=True and a scanned PDF
                is detected.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        try:
            import fitz
        except ImportError:
            logger.warning("PyMuPDF not available for quality check, using text-based fallback")
            return self._check_via_text_fallback(path)

        doc = fitz.open(path)
        page_count = len(doc)

        sampled_pages: List[tuple[int, str]] = []
        for i in range(min(self.check_first_n_pages, page_count)):
            page = doc[i]
            text = page.get_text("text") or ""
            sampled_pages.append((i + 1, text))

        doc.close()

        return self._build_report(path, sampled_pages, page_count)

    def check_text(self, pages: List[tuple[int, str]]) -> QualityReport:
        """Assess quality using pre-extracted page texts.

        This overload accepts the result of a PdfLoader (List[Page]) directly,
        avoiding re-parsing the PDF. Use this when you already have extracted
        text and only need quality checking.

        Args:
            pages: List of (page_number, extracted_text) tuples.

        Returns:
            QualityReport with quality metrics and recommendation.
        """
        return self._build_report("unknown", pages, len(pages))

    def _check_via_text_fallback(self, path: Path) -> QualityReport:
        """Fallback check when PyMuPDF is not available.

        Uses only the raw text (for pipeline integration that already has
        extracted text, prefer check_text instead).
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            return QualityReport(
                file_path=str(path),
                page_count=0,
                sampled_pages=0,
                valid_char_count=0,
                total_char_count=0,
                valid_char_ratio=0.0,
                text_density=0.0,
                is_noisy=True,
                is_poor_quality=True,
                quality_level="unknown",
                recommendation="ERROR - No PDF library available for quality check",
            )

        try:
            reader = PdfReader(path)
            page_count = len(reader.pages)
            sampled = []
            for i in range(min(self.check_first_n_pages, page_count)):
                text = reader.pages[i].extract_text() or ""
                sampled.append((i + 1, text))
            return self._build_report(path, sampled, page_count)
        except Exception:
            return QualityReport(
                file_path=str(path),
                page_count=0,
                sampled_pages=0,
                valid_char_count=0,
                total_char_count=0,
                valid_char_ratio=0.0,
                text_density=0.0,
                is_noisy=True,
                is_poor_quality=True,
                quality_level="error",
                recommendation="ERROR - Could not open PDF for quality check",
            )

    def _build_report(
        self,
        path: Union[str, Path],
        sampled_pages: List[tuple[int, str]],
        page_count: int,
    ) -> QualityReport:
        """Compute quality metrics and generate a QualityReport."""
        if not sampled_pages:
            return QualityReport(
                file_path=str(path),
                page_count=page_count,
                sampled_pages=0,
                valid_char_count=0,
                total_char_count=0,
                valid_char_ratio=0.0,
                text_density=0.0,
                is_noisy=True,
                is_poor_quality=True,
                quality_level="empty",
                recommendation="FAIL_EMPTY - PDF appears to have no text content",
            )

        total_valid = 0
        total_chars = 0
        per_page: List[PageReport] = []

        for page_num, text in sampled_pages:
            page_report = self._assess_page(page_num, text)
            per_page.append(page_report)
            total_valid += page_report.valid_char_count
            total_chars += page_report.total_char_count

        valid_ratio = total_valid / max(total_chars, 1)
        sampled_count = len(sampled_pages)
        estimated_capacity = sampled_count * self.DEFAULT_ESTIMATED_CHARS_PER_PAGE
        text_density = total_valid / max(estimated_capacity, 1)

        is_scanned = self._detect_scanned(per_page, valid_ratio)
        is_noisy = valid_ratio < self.min_valid_ratio
        is_low_density = text_density < self.min_text_density
        is_poor = is_scanned or is_noisy or is_low_density

        quality_level = self._classify_level(valid_ratio, text_density, is_scanned)
        recommendation = self._get_recommendation(is_scanned, valid_ratio, text_density)

        report = QualityReport(
            file_path=str(path),
            page_count=page_count,
            sampled_pages=sampled_count,
            valid_char_count=total_valid,
            total_char_count=total_chars,
            valid_char_ratio=valid_ratio,
            text_density=text_density,
            is_scanned=is_scanned,
            is_noisy=is_noisy,
            is_poor_quality=is_poor,
            quality_level=quality_level,
            recommendation=recommendation,
            per_page_reports=per_page,
        )

        if self.fail_on_scanned and is_scanned:
            raise DocumentQualityError(
                f"Scanned PDF detected: valid_ratio={valid_ratio:.2%}, "
                f"text_density={text_density:.2%}. {recommendation}",
                report=report,
            )

        return report

    def _assess_page(self, page_num: int, text: str) -> PageReport:
        """Compute quality metrics for a single page."""
        total = len(text)

        valid_chars = sum(1 for c in text if self._is_valid_char(c))
        valid_ratio = valid_chars / max(total, 1)

        noise_chars = sum(1 for c in text if not self._is_valid_char(c))
        noise_ratio = noise_chars / max(total, 1)

        reasons: List[str] = []
        if noise_ratio > self.max_noise_ratio:
            reasons.append(f"high_noise_ratio={noise_ratio:.1%}")
        if self._is_garbage_dominant(text):
            reasons.append("garbage_dominant")
        if self._lacks_text_structure(text):
            reasons.append("no_text_structure")

        return PageReport(
            page=page_num,
            valid_char_count=valid_chars,
            total_char_count=total,
            valid_char_ratio=valid_ratio,
            is_suspicious=len(reasons) > 0,
            suspicion_reasons=reasons,
        )

    # C0 control characters that are valid whitespace (tab, LF, VT, FF, CR)
    _C0_WHITESPACE = frozenset(ord(c) for c in "\t\n\v\f\r")

    def _is_valid_char(self, char: str) -> bool:
        """Return True if character is considered valid/clean text.

        Valid characters:
        - C0 whitespace: tab, newline, vertical tab, form feed, carriage return
        - Other whitespace (detected via isspace()): space, CJK ideographic space, etc.
        - ASCII printable (0x20-0x7E)
        - All other Unicode above 0x7F except known noise blocks

        Invalid characters:
        - Non-whitespace C0 controls (0x00-0x08, 0x0E-0x1F)
        - DEL (0x7F)
        - C1 controls (0x80-0x9F) — common PDF encoding artifacts
        - Unicode private use area (0xE000-0xF8FF) — font glyph placeholders
        - Variation selectors, tags, special planes
        """
        cp = ord(char)

        # Accept known-safe C0 whitespace: \t \n \v \f \r
        if cp in self._C0_WHITESPACE:
            return True

        # Reject non-whitespace C0 controls (0x00-0x1F except above)
        if cp <= 0x1F:
            return False

        # Reject DEL
        if cp == 0x7F:
            return False

        # Accept other whitespace (space, CJK ideographic space, etc.)
        if char.isspace():
            return True

        # ASCII printable (0x20-0x7E) — already covered by isspace check above
        if cp <= 0x7E:
            return True

        # C1 controls (0x80-0x9F): always noise
        if cp <= 0x9F:
            return False

        # Private use area: always noise
        if 0xE000 <= cp <= 0xF8FF:
            return False

        # Variation selectors, tags, special planes: noise
        if 0xFE00 <= cp <= 0xFE0F or 0xFFF0 <= cp <= 0xFFFF:
            return False

        # Everything else above 0x9F: assume valid (CJK, Latin extended, etc.)
        return True

    def _is_noise_block_char(self, char: str) -> bool:
        """Return True if character belongs to a known noise/artifact block."""
        cp = ord(char)
        return (
            0x0080 <= cp <= 0x009F
            or 0xE000 <= cp <= 0xF8FF
            or 0xFE00 <= cp <= 0xFE0F
        )

    def _is_garbage_dominant(self, text: str) -> bool:
        """Return True if >= 30% of characters are garbage/noise blocks.

        Threshold at 30% ensures this only fires when noise is genuinely dominant,
        not just a small amount of encoding artifacts. The valid_ratio threshold
        (default 80%) handles moderate noise; this flag fires for severe noise.
        """
        if not text:
            return False
        garbage = sum(1 for c in text if self._is_noise_block_char(c))
        return garbage / len(text) >= 0.30

    def _lacks_text_structure(self, text: str) -> bool:
        """Return True if text has almost no sentence/punctuation structure.

        Only fires when the text contains significant garbage noise AND lacks
        punctuation. Clean prose with no punctuation is not flagged (it's just
        a formatting style). Noise-only text is already caught by _is_garbage_dominant.
        """
        if len(text) < 50:
            return False

        # Only relevant when there's significant noise (>= 30% noise chars)
        noise_count = sum(1 for c in text if not self._is_valid_char(c))
        noise_ratio = noise_count / len(text)
        if noise_ratio < 0.30:
            return False

        # Count sentence/punctuation markers
        sentence_markers = sum(1 for c in text if c in "。！？.!?，,;；:")
        return sentence_markers / len(text) < 0.001

    def _detect_scanned(self, per_page: List[PageReport], valid_ratio: float) -> bool:
        """Detect if the PDF is primarily a scanned document.

        Uses three independent signals:
        1. Very low valid_ratio (accounts for whitespace + garbage chars)
        2. Garbage-dominant pages (high noise char ratio within each page)
        3. Page-level scan: >= 80% of sampled pages are individually suspicious
        """
        # Signal 1: Very low valid ratio (text itself is mostly noise)
        if valid_ratio < 0.10:
            return True

        # Signal 2: ALL sampled pages are garbage-dominant
        # (1/1 = 100% would trigger, so this only fires when EVERY page is garbage)
        garbage_dominant_pages = [
            p for p in per_page
            if p.total_char_count > 0 and p.suspicion_reasons
            and "garbage_dominant" in p.suspicion_reasons
        ]
        if len(garbage_dominant_pages) / max(len(per_page), 1) >= 1.0:
            return True

        # Signal 3: High suspicion rate across pages (structural absence)
        if len(per_page) >= 2:
            suspicious_pages = sum(1 for p in per_page if p.is_suspicious)
            if suspicious_pages / len(per_page) >= 0.80:
                return True

        return False

    def _classify_level(self, valid_ratio: float, text_density: float, is_scanned: bool) -> str:
        """Assign a human-readable quality tier.

        Density is tracked separately via is_low_density and FAIL_DENSITY;
        quality_level reflects the intrinsic quality of the text itself.
        "scanned" is only returned when valid_ratio is genuinely near-zero (true
        scanned document), not for moderate noise which is classified by ratio.
        """
        if is_scanned and valid_ratio < 0.15:
            return "scanned"
        if valid_ratio >= 0.90:
            return "excellent"
        if valid_ratio >= 0.80:
            return "good"
        if valid_ratio >= 0.60:
            return "fair"
        return "poor"

    def _get_recommendation(self, is_scanned: bool, valid_ratio: float, text_density: float) -> str:
        """Return an actionable recommendation string."""
        if is_scanned:
            return "FAIL_SCAN - 疑似扫描件，建议先通过 OCR 处理后再摄取"
        if valid_ratio < 0.30:
            return "FAIL_NOISE - 文本层严重损坏（有效字符率 < 30%），建议启用 OCR fallback"
        if valid_ratio < self.min_valid_ratio:
            return f"FAIL_NOISE - 有效字符率 {valid_ratio:.1%} 低于阈值 {self.min_valid_ratio:.0%}，建议启用 OCR fallback 或人工检查"
        if text_density < self.min_text_density:
            return f"FAIL_DENSITY - 文本密度 {text_density:.1%} 低于阈值 {self.min_text_density:.0%}，页面可能主要是图片/空白"
        return "PASS - 文本层质量良好，可正常摄取"


class DocumentQualityError(Exception):
    """Raised when a PDF fails quality check and fail_on_scanned=True."""

    def __init__(self, message: str, report: Optional[QualityReport] = None):
        super().__init__(message)
        self.report = report
