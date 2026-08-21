"""Tests for DesignPreviewService — code validation and render jobs."""

from __future__ import annotations

import pytest
from services.design_preview import DesignPreviewService

from maistro_design.trust import TrustTier


@pytest.fixture
def preview_service() -> DesignPreviewService:
    """Create a fresh preview service for each test."""
    return DesignPreviewService()


class TestCodeValidation:
    """Test React/TSX code validation."""

    def test_validate_clean_react_code(self, preview_service: DesignPreviewService) -> None:
        """Test validation of clean React code."""
        code = """
import React, { useState } from 'react';
import { Button } from '@headlessui/react';

export default function App() {
  const [count, setCount] = useState(0);
  return (
    <div className="flex items-center justify-center h-screen bg-gray-100">
      <Button onClick={() => setCount(count + 1)}>
        Click me: {count}
      </Button>
    </div>
  );
}
"""
        result = preview_service.validate_react_code(code, TrustTier.T3)
        assert result["valid"]
        assert len(result["errors"]) == 0
        assert result["stats"]["import_count"] == 2

    def test_validate_rejects_subprocess_import(
        self, preview_service: DesignPreviewService
    ) -> None:
        """Test that subprocess import is rejected for T3."""
        code = """
import subprocess
import React from 'react';
subprocess.run(['rm', '-rf', '/'])
"""
        result = preview_service.validate_react_code(code, TrustTier.T3)
        assert not result["valid"]
        assert any("subprocess" in err.lower() for err in result["errors"])

    def test_validate_rejects_eval(self, preview_service: DesignPreviewService) -> None:
        """Test that eval() is rejected."""
        code = """
const fn = eval("function() { return 42; }");
"""
        result = preview_service.validate_react_code(code, TrustTier.T3)
        assert not result["valid"]
        assert any("eval" in err.lower() for err in result["errors"])

    def test_validate_allows_safe_imports(self, preview_service: DesignPreviewService) -> None:
        """Test that whitelisted imports are allowed."""
        code = """
import React from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
"""
        result = preview_service.validate_react_code(code, TrustTier.T3)
        assert result["valid"]
        assert len(result["errors"]) == 0

    def test_validate_detects_unusual_tailwind_classes(
        self, preview_service: DesignPreviewService
    ) -> None:
        """Test that unusual Tailwind classes trigger warnings."""
        code = """
<div className="w-full h-screen bg-blue-500 custom-class-xyz">
  Content
</div>
"""
        result = preview_service.validate_react_code(code, TrustTier.T3)
        # Should have warnings but still valid for T3
        assert len(result["warnings"]) > 0

    def test_validate_t0_allows_non_whitelisted_imports(
        self, preview_service: DesignPreviewService
    ) -> None:
        """Test that T0 (trusted) code allows more flexibility."""
        code = """
import subprocess
import os
os.system('echo safe');
"""
        result = preview_service.validate_react_code(code, TrustTier.T0)
        # T0 should not trigger errors for imports/dangerous patterns
        # (they're considered trusted)
        assert result["valid"]


class TestRenderJobs:
    """Test async render job management."""

    def test_create_render_job(self, preview_service: DesignPreviewService) -> None:
        """Test creating a render job."""
        from maistro_design.types import OutputFormat

        job = preview_service.create_render_job("project-123", OutputFormat.PDF)

        assert job.job_id is not None
        assert job.project_id == "project-123"
        assert job.format == OutputFormat.PDF
        assert job.status == "pending"
        assert job.url is None
        assert job.error is None

    def test_get_render_job(self, preview_service: DesignPreviewService) -> None:
        """Test retrieving a render job."""
        from maistro_design.types import OutputFormat

        created = preview_service.create_render_job("project-456", OutputFormat.PPTX)
        retrieved = preview_service.get_render_job(created.job_id)

        assert retrieved is not None
        assert retrieved.job_id == created.job_id
        assert retrieved.project_id == "project-456"

    def test_get_nonexistent_job(self, preview_service: DesignPreviewService) -> None:
        """Test that getting a nonexistent job returns None."""
        assert preview_service.get_render_job("nonexistent") is None

    def test_update_render_job_status(self, preview_service: DesignPreviewService) -> None:
        """Test updating a render job status."""
        from maistro_design.types import OutputFormat

        job = preview_service.create_render_job("project-789", OutputFormat.PDF)

        updated = preview_service.update_render_job(
            job.job_id, status="rendering", url=None, error=None
        )

        assert updated is not None
        assert updated.status == "rendering"

    def test_update_job_to_completed(self, preview_service: DesignPreviewService) -> None:
        """Test marking a job as completed with URL."""
        from maistro_design.types import OutputFormat

        job = preview_service.create_render_job("project-abc", OutputFormat.DOCX)

        updated = preview_service.update_render_job(
            job.job_id,
            status="completed",
            url="https://storage.example.com/project-abc-render.docx",
            error=None,
        )

        assert updated is not None
        assert updated.status == "completed"
        assert updated.url == "https://storage.example.com/project-abc-render.docx"

    def test_render_job_to_dict(self, preview_service: DesignPreviewService) -> None:
        """Test serializing a render job to dict."""
        from maistro_design.types import OutputFormat

        job = preview_service.create_render_job("project-xyz", OutputFormat.PNG)
        job_dict = job.to_dict()

        assert "job_id" in job_dict
        assert "project_id" in job_dict
        assert "format" in job_dict
        assert "status" in job_dict
        assert "created_at" in job_dict
        assert "updated_at" in job_dict


class TestRenderStubs:
    """Test server-side render method stubs (Phase 2).

    Requires optional render packages: weasyprint, python-pptx, python-docx.
    """

    @pytest.mark.asyncio
    async def test_render_to_pdf_stub(self, preview_service: DesignPreviewService) -> None:
        """Test PDF render stub returns URL."""
        pytest.importorskip("weasyprint")
        url = await preview_service.render_to_pdf("<html>Test</html>", {})
        assert url.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_render_to_pptx_stub(self, preview_service: DesignPreviewService) -> None:
        """Test PPTX render stub returns URL."""
        pytest.importorskip("pptx")
        url = await preview_service.render_to_pptx("<slides>Test</slides>", {})
        assert url.endswith(".pptx")

    @pytest.mark.asyncio
    async def test_render_to_docx_stub(self, preview_service: DesignPreviewService) -> None:
        """Test DOCX render stub returns URL."""
        pytest.importorskip("docx")
        url = await preview_service.render_to_docx("<doc>Test</doc>", {})
        assert url.endswith(".docx")
