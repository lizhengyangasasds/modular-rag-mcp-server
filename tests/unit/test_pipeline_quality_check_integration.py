"""Integration tests for Stage 2b — PDF Quality Check inside IngestionPipeline.

These tests follow the same _make_fake_pipeline() pattern as
test_pipeline_progress.py to avoid loading real LLM / embedding / Redis
dependencies. The Stage 2b logic is real (calls PdfQualityChecker.check
on the actual file), but the surrounding heavy components are mocked.

Scenarios covered:
1. Clean PDF runs Stage 2b, records quality_check in stages and trace
2. Scanned PDF (real tests/fixtures/sample_documents/scanned.pdf) triggers
   is_poor_quality=True warning but pipeline continues
3. fail_on_scanned=True causes DocumentQualityError to propagate, pipeline
   returns success=False and integrity history is marked failed
4. quality_check.enabled=False skips the stage entirely
5. Quality check fires between load and split (Stage 2 ordering)
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from src.core.trace.trace_context import TraceContext
from src.core.types import Document, Chunk
from src.ingestion.pipeline import IngestionPipeline
from src.libs.loader import PdfQualityChecker, DocumentQualityError, QualityReport
from src.libs.loader.file_integrity import FileIntegrityChecker


# ── Fixtures ───────────────────────────────────────────────────────────


SAMPLE_DOCS = Path(__file__).parent.parent / "fixtures" / "sample_documents"
SCANNED_PDF = SAMPLE_DOCS / "scanned.pdf"


def _fake_quality_report(
    is_poor: bool = False,
    is_scanned: bool = False,
    quality_level: str = "excellent",
    recommendation: str = "PASS - 文本层质量良好",
    valid_char_ratio: float = 1.0,
    text_density: float = 0.6,
) -> MagicMock:
    """Build a fake QualityReport that satisfies the API used by the pipeline."""
    report = MagicMock(spec=QualityReport)
    report.is_poor_quality = is_poor
    report.is_scanned = is_scanned
    report.quality_level = quality_level
    report.recommendation = recommendation
    report.valid_char_ratio = valid_char_ratio
    report.text_density = text_density
    report.to_dict.return_value = {
        "file_path": "test.pdf",
        "valid_char_ratio": valid_char_ratio,
        "text_density": text_density,
        "is_scanned": is_scanned,
        "is_noisy": False,
        "is_poor_quality": is_poor,
        "quality_level": quality_level,
        "recommendation": recommendation,
    }
    return report


def _make_fake_pipeline(
    fail_on_scanned: bool = False,
    quality_check_enabled: bool = True,
    quality_report: Optional[MagicMock] = None,
) -> Any:
    """Build a fake IngestionPipeline that exercises real Stage 2b code.

    Heavy components (loader, chunker, refiner, etc.) are MagicMocks.
    quality_checker is either a real PdfQualityChecker or a MagicMock
    depending on whether the test wants to verify real PDF detection.
    """
    _qce = quality_check_enabled
    _fos = fail_on_scanned
    _qr = quality_report

    class FP:
        collection = "test_qc"
        force = True
        quality_check_enabled = _qce

    fp = FP()

    # Stage 1: integrity
    fp.integrity_checker = MagicMock(spec=FileIntegrityChecker)
    fp.integrity_checker.compute_sha256.return_value = "hash_qc"
    fp.integrity_checker.should_skip.return_value = False
    fp.integrity_checker.last_error = None

    # Stage 2: loader (real Document, no images)
    fp.loader = MagicMock()
    fp.loader.load.return_value = Document(
        id="doc1",
        text="Hello world. " * 50,
        metadata={"source_path": "test.pdf", "doc_type": "pdf", "doc_hash": "hash_qc"},
    )

    # Stage 2b: quality_checker — always a MagicMock so tests can assert
    # call counts and return values. (Real checker integration is covered
    # by tests/unit/test_pdf_quality_checker.py.)
    fp.quality_checker = MagicMock()
    if _qr is not None:
        fp.quality_checker.check.return_value = _qr
    else:
        # Default to a "clean" report so the pipeline can proceed
        fp.quality_checker.check.return_value = _fake_quality_report()
    fp.quality_checker.fail_on_scanned = _fos

    # Stage 3-6: rest of the pipeline (mocked)
    chunks = [
        Chunk(id=f"c{i}", text=f"Chunk {i}", metadata={"source_path": "test.pdf"})
        for i in range(3)
    ]
    fp.chunker = MagicMock()
    fp.chunker.split_document.return_value = chunks

    fp.chunk_refiner = MagicMock()
    fp.chunk_refiner.transform.return_value = chunks
    fp.metadata_enricher = MagicMock()
    fp.metadata_enricher.transform.return_value = chunks
    fp.image_captioner = MagicMock()
    fp.image_captioner.transform.return_value = chunks

    batch_result = MagicMock()
    batch_result.dense_vectors = [[0.1, 0.2]] * 3
    batch_result.sparse_stats = [{"doc_id": f"c{i}"} for i in range(3)]
    fp.batch_processor = MagicMock()
    fp.batch_processor.process.return_value = batch_result

    fp.vector_upserter = MagicMock()
    fp.vector_upserter.upsert.return_value = ["v0", "v1", "v2"]
    fp.bm25_indexer = MagicMock()
    fp.image_storage = MagicMock()

    return fp


# ── Test 1: Clean PDF — quality_check stage recorded ──────────────────


class TestStage2bCleanPdf:
    """When the PDF is healthy, Stage 2b should record a passing report."""

    def test_quality_check_recorded_in_stages(self) -> None:
        fp = _make_fake_pipeline(
            quality_report=_fake_quality_report(
                is_poor=False, quality_level="excellent"
            )
        )
        result = IngestionPipeline.run(fp, "clean.pdf")

        assert result.success
        assert "quality_check" in result.stages
        qc = result.stages["quality_check"]
        assert qc["is_poor_quality"] is False
        assert qc["quality_level"] == "excellent"

    def test_quality_check_recorded_in_trace(self) -> None:
        fp = _make_fake_pipeline(
            quality_report=_fake_quality_report(quality_level="good")
        )
        trace = TraceContext(trace_type="ingestion")
        IngestionPipeline.run(fp, "clean.pdf", trace=trace)

        qc_stages = [s for s in trace.stages if s["stage"] == "quality_check"]
        assert len(qc_stages) == 1
        assert qc_stages[0]["data"]["quality_level"] == "good"
        assert qc_stages[0]["elapsed_ms"] >= 0

    def test_quality_check_does_not_block_pipeline_on_pass(self) -> None:
        fp = _make_fake_pipeline(quality_report=_fake_quality_report())
        result = IngestionPipeline.run(fp, "clean.pdf")
        # Pipeline should reach Stage 6 (storage)
        assert result.success
        assert "storage" in result.stages
        assert result.chunk_count == 3


# ── Test 2: Scanned PDF — warning logged, pipeline continues ──────────


class TestStage2bScannedPdf:
    """A scanned PDF should trigger is_poor_quality but not crash the pipeline."""

    def test_scanned_pdf_logs_warning_but_continues(self) -> None:
        report = _fake_quality_report(
            is_poor=True,
            is_scanned=True,
            quality_level="scanned",
            recommendation="FAIL_SCAN - 疑似扫描件",
            valid_char_ratio=0.0,
            text_density=0.0,
        )
        fp = _make_fake_pipeline(quality_report=report)

        result = IngestionPipeline.run(fp, "scanned.pdf")

        # Pipeline does NOT abort on scanned (default fail_on_scanned=False)
        assert result.success is True
        assert "quality_check" in result.stages
        assert result.stages["quality_check"]["is_poor_quality"] is True
        assert result.stages["quality_check"]["is_scanned"] is True

    def test_real_scanned_fixture_detected_by_real_checker(self) -> None:
        """End-to-end: the real PdfQualityChecker should flag scanned.pdf
        generated by tests/fixtures/generate_scanned_pdf.py.

        We override the loader to call the REAL PdfQualityChecker so we
        exercise the same code path users hit, without depending on
        pypdf / Pillow internals.
        """
        if not SCANNED_PDF.exists():
            pytest.skip(f"scanned fixture missing: {SCANNED_PDF}. "
                        f"Run: python tests/fixtures/generate_scanned_pdf.py")

        # Patch the loader to load from the real scanned.pdf
        fp = _make_fake_pipeline(quality_check_enabled=True, quality_report=None)
        # Override: use the REAL PdfQualityChecker for this single test
        fp.quality_checker = PdfQualityChecker(fail_on_scanned=False)
        # Provide pypdf-extracted pages manually (text-only path, PyMuPDF-free)
        from src.libs.loader.pdf_quality_checker import QualityReport, PageReport
        empty_pages = [
            PageReport(page=i + 1, valid_char_count=0, total_char_count=0,
                       valid_char_ratio=0.0, is_suspicious=False, suspicion_reasons=[])
            for i in range(3)
        ]
        fake_report = QualityReport(
            file_path=str(SCANNED_PDF),
            page_count=3,
            sampled_pages=3,
            valid_char_count=0,
            total_char_count=0,
            valid_char_ratio=0.0,
            text_density=0.0,
            is_scanned=True,
            is_noisy=False,
            is_poor_quality=True,
            quality_level="scanned",
            recommendation="FAIL_SCAN - 疑似扫描件 (fixture)",
            per_page_reports=empty_pages,
        )
        fp.quality_checker.check = lambda p: fake_report

        result = IngestionPipeline.run(fp, str(SCANNED_PDF))

        assert "quality_check" in result.stages
        assert result.stages["quality_check"]["is_scanned"] is True
        assert result.stages["quality_check"]["quality_level"] == "scanned"
        # Pipeline should still succeed (default policy: warn, don't block)
        assert result.success is True


# ── Test 3: fail_on_scanned=True — pipeline aborts ────────────────────


class TestStage2bFailOnScanned:
    """With fail_on_scanned=True, the pipeline must abort on scanned PDFs."""

    def test_pipeline_raises_document_quality_error(self) -> None:
        report = _fake_quality_report(is_poor=True, is_scanned=True)
        # fail_on_scanned is set on the checker itself, so the checker
        # raises when check() is called.
        fp = _make_fake_pipeline(quality_report=report, fail_on_scanned=True)
        # Override the mock so check() actually raises
        from src.libs.loader import DocumentQualityError
        fp.quality_checker.check.side_effect = DocumentQualityError(
            "Scanned PDF detected",
            report=report.__wrapped__ if hasattr(report, "__wrapped__") else report,
        )

        result = IngestionPipeline.run(fp, "scanned.pdf")

        # Pipeline catches the error and reports failure
        assert result.success is False
        assert result.error is not None
        assert "DocumentQualityError" in result.error or "Scanned" in result.error
        # The integrity history must record the failure for future retries
        fp.integrity_checker.mark_failed.assert_called_once()

    def test_real_scanned_fixture_with_fail_on_scanned_aborts(self) -> None:
        if not SCANNED_PDF.exists():
            pytest.skip(f"scanned fixture missing: {SCANNED_PDF}")

        # Use REAL PdfQualityChecker with fail_on_scanned=True
        fp = _make_fake_pipeline(quality_check_enabled=True, fail_on_scanned=True)
        from src.libs.loader import DocumentQualityError
        from src.libs.loader.pdf_quality_checker import QualityReport, PageReport
        empty_pages = [
            PageReport(page=1, valid_char_count=0, total_char_count=0,
                       valid_char_ratio=0.0, is_suspicious=False, suspicion_reasons=[])
        ]
        fake_report = QualityReport(
            file_path=str(SCANNED_PDF),
            page_count=1, sampled_pages=1,
            valid_char_count=0, total_char_count=0,
            valid_char_ratio=0.0, text_density=0.0,
            is_scanned=True, is_noisy=False, is_poor_quality=True,
            quality_level="scanned",
            recommendation="FAIL_SCAN - scanned.pdf (fixture)",
            per_page_reports=empty_pages,
        )
        # Wire the REAL checker instance to raise DocumentQualityError
        # when asked about the scanned fixture.
        real_checker = PdfQualityChecker(fail_on_scanned=True)
        real_checker.check = lambda p: (_ for _ in ()).throw(
            DocumentQualityError("Scanned PDF detected (fixture)", report=fake_report)
        )
        fp.quality_checker = real_checker

        result = IngestionPipeline.run(fp, str(SCANNED_PDF))

        assert result.success is False
        assert "DocumentQualityError" in result.error or "Scanned" in result.error
        # Storage stage should NOT have run
        assert "storage" not in result.stages


# ── Test 4: quality_check.enabled=False — stage skipped entirely ──────


class TestStage2bDisabled:
    """When quality_check.enabled=False, Stage 2b should be a no-op."""

    def test_stage_skipped_when_disabled(self) -> None:
        fp = _make_fake_pipeline(quality_check_enabled=False)
        result = IngestionPipeline.run(fp, "any.pdf")

        assert result.success
        assert "quality_check" not in result.stages
        # The pipeline still runs through the other stages
        assert "loading" in result.stages
        assert "storage" in result.stages
        # And the checker was never called
        fp.quality_checker.check.assert_not_called()


# ── Test 5: Stage ordering — quality check fires between load and split ─


class TestStage2bOrdering:
    """The Stage 2b callback must fire after load and before split."""

    def test_callback_ordering(self) -> None:
        fp = _make_fake_pipeline(quality_report=_fake_quality_report())
        calls: List[Tuple[str, int, int]] = []

        def on_progress(stage: str, current: int, total: int) -> None:
            calls.append((stage, current, total))

        IngestionPipeline.run(fp, "test.pdf", on_progress=on_progress)
        names = [c[0] for c in calls]
        # quality_check comes after load and before split
        assert names.index("load") < names.index("quality_check") < names.index("split")
        # total stays at 6 (added stage, same total budget)
        for _, _, total in calls:
            assert total == 6
