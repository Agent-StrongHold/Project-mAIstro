from io import BytesIO
from unittest.mock import patch

from reportlab.pdfgen import canvas as pdfcanvas
from server.lulu.constants import BLEED_MARGIN_IN, PICTURE_BOOK_FORMATS
from server.lulu.preflight import (
    PreflightIssue,
    PreflightResult,
    preflight_cover,
    preflight_interior,
)

PKG = "0750X0750.FC.PRE.PB.080CW444.MXX"
FMT = PICTURE_BOOK_FORMATS[PKG]
BLEED_W_PT = FMT["bleed_size_in"][0] * 72
BLEED_H_PT = FMT["bleed_size_in"][1] * 72
MIN_PAGES = FMT["min_pages"]
MAX_PAGES = FMT["max_pages"]
TRIM_W = FMT["trim_size_in"][0]
TRIM_H = FMT["trim_size_in"][1]


def _make_pdf(pages: int, width_pt: float, height_pt: float, path=None):
    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(width_pt, height_pt))
    for _ in range(pages):
        c.showPage()
    c.save()
    buf.seek(0)
    if path is not None:
        with open(path, "wb") as f:
            f.write(buf.read())
        return path
    return buf


def _cover_dims(page_count: int):
    spine = (page_count / 444) + 0.06
    cover_w_in = TRIM_W + BLEED_MARGIN_IN + TRIM_W + spine + TRIM_W + BLEED_MARGIN_IN
    cover_h_in = TRIM_H + 2 * BLEED_MARGIN_IN
    return cover_w_in * 72, cover_h_in * 72


class TestPreflightInterior:
    def test_nonexistent_file(self, tmp_path):
        result = preflight_interior(tmp_path / "nope.pdf", PKG)
        assert result.passed is False
        assert any(i.code == "FILE_NOT_FOUND" for i in result.issues)
        assert result.errors[0].severity == "error"

    def test_invalid_pdf(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"<html>not a pdf</html>")
        result = preflight_interior(bad, PKG)
        assert result.passed is False
        assert any(i.code == "INVALID_PDF" for i in result.issues)

    def test_unknown_package(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _make_pdf(MIN_PAGES, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, "NO_SUCH_PACKAGE")
        assert result.passed is False
        assert any(i.code == "UNKNOWN_PACKAGE" for i in result.issues)

    def test_valid_32_pages(self, tmp_path):
        pdf_path = tmp_path / "valid.pdf"
        _make_pdf(MIN_PAGES, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG)
        assert result.passed is True
        assert result.page_count == MIN_PAGES
        assert len(result.issues) == 0

    def test_page_count_too_low(self, tmp_path):
        pdf_path = tmp_path / "low.pdf"
        _make_pdf(16, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG)
        assert result.passed is False
        assert any(i.code == "PAGE_COUNT_TOO_LOW" for i in result.issues)

    def test_page_count_too_high(self, tmp_path):
        pdf_path = tmp_path / "high.pdf"
        _make_pdf(900, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG)
        assert result.passed is False
        assert any(i.code == "PAGE_COUNT_TOO_HIGH" for i in result.issues)

    def test_odd_page_count_warning(self, tmp_path):
        pdf_path = tmp_path / "odd.pdf"
        _make_pdf(33, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG, allow_extra_blank=True)
        assert result.passed is True
        odd_issues = [i for i in result.issues if i.code == "ODD_PAGE_COUNT"]
        assert len(odd_issues) == 1
        assert odd_issues[0].severity == "warning"

    def test_odd_page_count_error(self, tmp_path):
        pdf_path = tmp_path / "odd_err.pdf"
        _make_pdf(33, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG, allow_extra_blank=False)
        assert result.passed is False
        odd_issues = [i for i in result.issues if i.code == "ODD_PAGE_COUNT"]
        assert len(odd_issues) == 1
        assert odd_issues[0].severity == "error"

    def test_page_count_mismatch(self, tmp_path):
        pdf_path = tmp_path / "mismatch.pdf"
        _make_pdf(30, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        result = preflight_interior(pdf_path, PKG, expected_page_count=32)
        assert any(i.code == "PAGE_COUNT_MISMATCH" for i in result.issues)
        mismatch = next(i for i in result.issues if i.code == "PAGE_COUNT_MISMATCH")
        assert mismatch.severity == "warning"
        assert mismatch.details["expected"] == 32
        assert mismatch.details["actual"] == 30

    def test_page_size_mismatch(self, tmp_path):
        pdf_path = tmp_path / "wrong_size.pdf"
        _make_pdf(MIN_PAGES, 612, 792, path=pdf_path)
        result = preflight_interior(pdf_path, PKG)
        assert result.passed is False
        assert any(i.code == "PAGE_SIZE_MISMATCH" for i in result.issues)

    def test_file_too_large(self, tmp_path):
        pdf_path = tmp_path / "big.pdf"
        _make_pdf(MIN_PAGES, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        fake_stat = type("Stat", (), {"st_size": 500 * 1024 * 1024})()
        with patch("pathlib.Path.stat", return_value=fake_stat):
            result = preflight_interior(pdf_path, PKG)
        assert any(i.code == "FILE_TOO_LARGE" for i in result.issues)
        assert (
            result.issues[0].severity == "error"
            if result.issues[0].code == "FILE_TOO_LARGE"
            else True
        )

    def test_file_very_small(self, tmp_path):
        pdf_path = tmp_path / "tiny.pdf"
        _make_pdf(MIN_PAGES, BLEED_W_PT, BLEED_H_PT, path=pdf_path)
        fake_stat = type("Stat", (), {"st_size": 100})()
        with patch("pathlib.Path.stat", return_value=fake_stat):
            result = preflight_interior(pdf_path, PKG)
        small_issues = [i for i in result.issues if i.code == "FILE_VERY_SMALL"]
        assert len(small_issues) == 1
        assert small_issues[0].severity == "warning"


class TestPreflightCover:
    def test_nonexistent_file(self, tmp_path):
        result = preflight_cover(tmp_path / "nope.pdf", PKG, 32)
        assert result.passed is False
        assert any(i.code == "FILE_NOT_FOUND" for i in result.issues)

    def test_invalid_pdf(self, tmp_path):
        bad = tmp_path / "bad_cover.pdf"
        bad.write_bytes(b"garbage data")
        result = preflight_cover(bad, PKG, 32)
        assert result.passed is False
        assert any(i.code == "INVALID_PDF" for i in result.issues)

    def test_valid_cover(self, tmp_path):
        cover_w_pt, cover_h_pt = _cover_dims(32)
        pdf_path = tmp_path / "cover.pdf"
        _make_pdf(1, cover_w_pt, cover_h_pt, path=pdf_path)
        result = preflight_cover(pdf_path, PKG, 32)
        assert result.passed is True
        assert result.page_count == 1

    def test_wrong_page_count(self, tmp_path):
        cover_w_pt, cover_h_pt = _cover_dims(32)
        pdf_path = tmp_path / "cover_2pg.pdf"
        _make_pdf(2, cover_w_pt, cover_h_pt, path=pdf_path)
        result = preflight_cover(pdf_path, PKG, 32)
        assert result.passed is False
        assert any(i.code == "COVER_PAGE_COUNT" for i in result.issues)

    def test_wrong_size(self, tmp_path):
        pdf_path = tmp_path / "cover_wrong.pdf"
        _make_pdf(1, 612, 792, path=pdf_path)
        result = preflight_cover(pdf_path, PKG, 32)
        assert result.passed is False
        assert any(i.code == "COVER_SIZE_MISMATCH" for i in result.issues)


class TestPreflightResult:
    def test_errors_property(self):
        result = PreflightResult(
            passed=False,
            issues=[
                PreflightIssue("error", "E1", "bad"),
                PreflightIssue("warning", "W1", "meh"),
                PreflightIssue("error", "E2", "worse"),
            ],
        )
        assert len(result.errors) == 2
        assert all(i.severity == "error" for i in result.errors)

    def test_warnings_property(self):
        result = PreflightResult(
            passed=True,
            issues=[
                PreflightIssue("warning", "W1", "meh"),
                PreflightIssue("warning", "W2", "hmm"),
                PreflightIssue("error", "E1", "bad"),
            ],
        )
        assert len(result.warnings) == 2
        assert all(i.severity == "warning" for i in result.warnings)
