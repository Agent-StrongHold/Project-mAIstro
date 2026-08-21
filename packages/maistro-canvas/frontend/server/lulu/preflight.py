from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyPDF2 import PdfReader

from .constants import (
    BLEED_MARGIN_IN,
    PICTURE_BOOK_FORMATS,
)

logger = logging.getLogger("lulu.preflight")


@dataclass
class PreflightIssue:
    severity: str
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResult:
    passed: bool = False
    issues: list[PreflightIssue] = field(default_factory=list)
    page_count: int = 0
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0

    @property
    def errors(self) -> list[PreflightIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[PreflightIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def _pt_to_in(pt: float) -> float:
    return pt / 72.0


def _in_to_pt(inches: float) -> float:
    return inches * 72.0


def _check_page_count(
    result: PreflightResult,
    fmt: dict,
    expected_page_count: int | None,
    allow_extra_blank: bool,
) -> None:
    """Append page-count related issues to ``result``."""
    if result.page_count < fmt["min_pages"]:
        result.issues.append(
            PreflightIssue(
                "error",
                "PAGE_COUNT_TOO_LOW",
                f"{result.page_count} pages, minimum {fmt['min_pages']}",
                {"page_count": result.page_count, "min_pages": fmt["min_pages"]},
            )
        )

    if result.page_count > fmt["max_pages"]:
        result.issues.append(
            PreflightIssue(
                "error",
                "PAGE_COUNT_TOO_HIGH",
                f"{result.page_count} pages, maximum {fmt['max_pages']}",
                {"page_count": result.page_count, "max_pages": fmt["max_pages"]},
            )
        )

    if result.page_count % 2 != 0:
        if allow_extra_blank:
            result.issues.append(
                PreflightIssue(
                    "warning",
                    "ODD_PAGE_COUNT",
                    f"{result.page_count} pages (odd) — Lulu requires even. "
                    "A blank page will be appended.",
                    {"page_count": result.page_count},
                )
            )
        else:
            result.issues.append(
                PreflightIssue(
                    "error",
                    "ODD_PAGE_COUNT",
                    f"{result.page_count} pages — must be even for Lulu printing",
                    {"page_count": result.page_count},
                )
            )

    if expected_page_count and result.page_count != expected_page_count:
        result.issues.append(
            PreflightIssue(
                "warning",
                "PAGE_COUNT_MISMATCH",
                f"Expected {expected_page_count} pages, got {result.page_count}",
                {"expected": expected_page_count, "actual": result.page_count},
            )
        )


def _check_page_size(result: PreflightResult, fmt: dict, first_page: object) -> None:
    """Record page dimensions and append a size-mismatch issue if needed."""
    mediabox = first_page.mediabox  # type: ignore[attr-defined]
    result.page_width_pt = float(mediabox.width)
    result.page_height_pt = float(mediabox.height)

    trim_w_in, trim_h_in = fmt["trim_size_in"]
    bleed_w_in, bleed_h_in = fmt["bleed_size_in"]
    expected_w_pt = _in_to_pt(bleed_w_in)
    expected_h_pt = _in_to_pt(bleed_h_in)

    width_diff_pt = abs(result.page_width_pt - expected_w_pt)
    height_diff_pt = abs(result.page_height_pt - expected_h_pt)

    if width_diff_pt > 3 or height_diff_pt > 3:
        actual_w_in = _pt_to_in(result.page_width_pt)
        actual_h_in = _pt_to_in(result.page_height_pt)
        result.issues.append(
            PreflightIssue(
                "error",
                "PAGE_SIZE_MISMATCH",
                f"Page size {actual_w_in:.3f}x{actual_h_in:.3f}in "
                f"does not match expected {bleed_w_in:.3f}x{bleed_h_in:.3f}in "
                f"(with {BLEED_MARGIN_IN}in bleed)",
                {
                    "actual_size_in": (round(actual_w_in, 3), round(actual_h_in, 3)),
                    "expected_size_in": (bleed_w_in, bleed_h_in),
                    "trim_size_in": (trim_w_in, trim_h_in),
                    "bleed_margin_in": BLEED_MARGIN_IN,
                },
            )
        )


def _check_file_size(result: PreflightResult, path: Path) -> None:
    """Append file-size related issues to ``result``."""
    file_size_mb = path.stat().st_size / (1024 * 1024)
    max_file_size_mb = 300
    if file_size_mb > max_file_size_mb:
        result.issues.append(
            PreflightIssue(
                "error",
                "FILE_TOO_LARGE",
                f"PDF is {file_size_mb:.1f}MB, maximum {max_file_size_mb}MB",
                {"file_size_mb": round(file_size_mb, 1), "max_mb": max_file_size_mb},
            )
        )

    min_size_mb = 0.01
    if file_size_mb < min_size_mb:
        result.issues.append(
            PreflightIssue(
                "warning",
                "FILE_VERY_SMALL",
                f"PDF is only {file_size_mb:.4f}MB — may be missing content",
                {"file_size_mb": round(file_size_mb, 4)},
            )
        )


def preflight_interior(
    pdf_path: str | Path,
    pod_package_id: str,
    expected_page_count: int | None = None,
    allow_extra_blank: bool = True,
) -> PreflightResult:
    result = PreflightResult()
    path = Path(pdf_path)

    if not path.exists():
        result.passed = False
        result.issues.append(PreflightIssue("error", "FILE_NOT_FOUND", f"PDF not found: {path}"))
        return result

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        result.passed = False
        result.issues.append(PreflightIssue("error", "INVALID_PDF", f"Cannot read PDF: {e}"))
        return result

    result.page_count = len(reader.pages)

    fmt = PICTURE_BOOK_FORMATS.get(pod_package_id)
    if not fmt:
        result.passed = False
        result.issues.append(
            PreflightIssue("error", "UNKNOWN_PACKAGE", f"Unknown package: {pod_package_id}")
        )
        return result

    _check_page_count(result, fmt, expected_page_count, allow_extra_blank)
    _check_page_size(result, fmt, reader.pages[0])
    _check_file_size(result, path)

    result.passed = len(result.errors) == 0
    if result.passed:
        logger.info(
            "Preflight PASSED: %d pages, %.1fx%.1fpt",
            result.page_count,
            result.page_width_pt,
            result.page_height_pt,
        )
    else:
        logger.warning("Preflight FAILED: %d errors", len(result.errors))

    return result


def preflight_cover(
    pdf_path: str | Path,
    pod_package_id: str,
    page_count: int,
) -> PreflightResult:
    result = PreflightResult()
    path = Path(pdf_path)

    if not path.exists():
        result.passed = False
        result.issues.append(
            PreflightIssue("error", "FILE_NOT_FOUND", f"Cover PDF not found: {path}")
        )
        return result

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        result.passed = False
        result.issues.append(PreflightIssue("error", "INVALID_PDF", f"Cannot read cover PDF: {e}"))
        return result

    cover_pages = len(reader.pages)
    result.page_count = cover_pages

    if cover_pages != 1:
        result.issues.append(
            PreflightIssue(
                "error",
                "COVER_PAGE_COUNT",
                f"Cover must be exactly 1 page, got {cover_pages}",
                {"page_count": cover_pages},
            )
        )

    fmt = PICTURE_BOOK_FORMATS.get(pod_package_id)
    if not fmt:
        result.passed = False
        result.issues.append(
            PreflightIssue("error", "UNKNOWN_PACKAGE", f"Unknown package: {pod_package_id}")
        )
        return result

    trim_w_in, trim_h_in = fmt["trim_size_in"]
    spine_width_in = (page_count / 444) + 0.06
    cover_w_in = (
        trim_w_in + BLEED_MARGIN_IN + trim_w_in + spine_width_in + trim_w_in + BLEED_MARGIN_IN
    )
    cover_h_in = trim_h_in + 2 * BLEED_MARGIN_IN

    first_page = reader.pages[0]
    mediabox = first_page.mediabox
    result.page_width_pt = float(mediabox.width)
    result.page_height_pt = float(mediabox.height)

    expected_w_pt = _in_to_pt(cover_w_in)
    expected_h_pt = _in_to_pt(cover_h_in)

    width_diff_pt = abs(result.page_width_pt - expected_w_pt)
    height_diff_pt = abs(result.page_height_pt - expected_h_pt)

    if width_diff_pt > 5 or height_diff_pt > 5:
        actual_w_in = _pt_to_in(result.page_width_pt)
        actual_h_in = _pt_to_in(result.page_height_pt)
        result.issues.append(
            PreflightIssue(
                "error",
                "COVER_SIZE_MISMATCH",
                f"Cover size {actual_w_in:.3f}x{actual_h_in:.3f}in "
                f"expected ~{cover_w_in:.3f}x{cover_h_in:.3f}in "
                f"(spine: {spine_width_in:.4f}in for {page_count} pages)",
                {
                    "actual_size_in": (round(actual_w_in, 3), round(actual_h_in, 3)),
                    "expected_size_in": (round(cover_w_in, 3), round(cover_h_in, 3)),
                    "spine_width_in": round(spine_width_in, 4),
                    "page_count": page_count,
                },
            )
        )

    file_size_mb = path.stat().st_size / (1024 * 1024)
    if file_size_mb > 100:
        result.issues.append(
            PreflightIssue(
                "warning",
                "COVER_FILE_LARGE",
                f"Cover PDF is {file_size_mb:.1f}MB",
                {"file_size_mb": round(file_size_mb, 1)},
            )
        )

    result.passed = len(result.errors) == 0
    return result
