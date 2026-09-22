"""Tests for DesignPreviewService — code validation and render jobs."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hive_conductor.services.design_preview import DesignPreviewService

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


class TestRenderStubs:
    """Rendering is rejected until canonical storage and serving exist.

    Rendering remains unavailable until durable artifact ownership is implemented.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method_name", "format_name"),
        [("render_to_pdf", "PDF"), ("render_to_pptx", "PPTX"), ("render_to_docx", "DOCX")],
    )
    async def test_render_methods_report_unavailable_without_discarding_bytes(
        self,
        preview_service: DesignPreviewService,
        method_name: str,
        format_name: str,
    ) -> None:
        """Render helpers must not claim a URL without durable artifact storage."""
        with pytest.raises(HTTPException) as raised:
            await getattr(preview_service, method_name)("content", {})
        assert raised.value.status_code == 501
        assert format_name in str(raised.value.detail)
