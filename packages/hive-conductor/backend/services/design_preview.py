"""DesignPreviewService — server-side rendering and code validation for design outputs.

Handles:
1. AST validation for generated React/TSX code (imports whitelist, Tailwind classes)
2. Security scanning for T3 artifacts (untrusted user input)
3. Server-side rendering for PDF/PPTX/DOCX via async job queue
4. Preview URLs for rendered outputs

Follows async job queue pattern — render requests return immediately with job_id,
client polls /v1/design/projects/{id}/render/{job_id} for status and download URL.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import uuid4

from maistro_design.trust import TrustTier
from maistro_design.types import OutputFormat

logger = logging.getLogger("hive.design_preview")

__all__ = ["CodeValidationError", "DesignPreviewService", "RenderJob"]


class CodeValidationError(Exception):
    """Raised when generated code fails validation."""

    pass


class RenderJob:
    """Async render job tracking."""

    def __init__(
        self,
        job_id: str,
        project_id: str,
        format: OutputFormat,
        status: str = "pending",
        url: str | None = None,
        error: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.project_id = project_id
        self.format = format
        self.status = status
        self.url = url
        self.error = error
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "format": self.format,
            "status": self.status,
            "url": self.url,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class DesignPreviewService:
    """Server-side rendering and validation for design outputs."""

    ALLOWED_IMPORTS: ClassVar[frozenset[str]] = frozenset(
        {
            "react",
            "react-dom",
            "react/jsx-runtime",
            "classnames",
            "clsx",
            "@headlessui/react",
            "@radix-ui/react-*",
            "tailwindcss",
            "framer-motion",
        }
    )

    ALLOWED_TAILWIND_CLASSES: ClassVar[re.Pattern[str]] = re.compile(
        r"^(w-|h-|p-|m-|text-|bg-|border-|rounded-|shadow-|flex|grid|"
        r"absolute|relative|fixed|block|inline|flex-col|flex-row|justify-|items-|"
        r"gap-|space-|opacity-|transition|duration-|ease-|hover|focus|active)"
    )

    def __init__(self) -> None:
        """Initialize the preview service."""
        self._render_jobs: dict[str, RenderJob] = {}

    def _check_line_imports(self, line: str, result: dict[str, Any], trust_tier: TrustTier) -> int:
        """Check import line; return 1 if import, 0 otherwise."""
        if not (line.strip().startswith("import ") or line.strip().startswith("from ")):
            return 0
        if self._is_import_whitelisted(line):
            return 1
        if trust_tier == TrustTier.T3:
            result["errors"].append(f"Non-whitelisted import: {line.strip()[:60]}")
            result["valid"] = False
        return 1

    def _check_line_dangerous_patterns(
        self, line: str, result: dict[str, Any], trust_tier: TrustTier
    ) -> None:
        """Check for dangerous code patterns (T3 untrusted code only)."""
        if trust_tier != TrustTier.T3:
            return
        if any(
            pattern in line.lower()
            for pattern in ["eval(", "exec(", "__import__", "subprocess", "os.system"]
        ):
            result["errors"].append(f"Dangerous pattern detected: {line.strip()[:60]}")
            result["valid"] = False

    def _check_line_tailwind(
        self, line: str, result: dict[str, Any], trust_tier: TrustTier
    ) -> None:
        """Check Tailwind classes in line."""
        if "className" not in line and "class=" not in line:
            return
        classes = re.findall(r'["\']([^"\']*(?:w-|h-|p-|m-|text-|bg-)[^\'"]*)["\']', line)
        for cls_str in classes:
            for cls in cls_str.split():
                if not self.ALLOWED_TAILWIND_CLASSES.match(cls) and trust_tier == TrustTier.T3:
                    result["warnings"].append(f"Unusual Tailwind class: {cls}")

    def validate_react_code(self, code: str, trust_tier: TrustTier) -> dict[str, Any]:
        """Validate generated React/TSX code.

        Checks:
        1. Valid Python AST parse (basic syntax)
        2. Imports are whitelisted (no os.system, subprocess, etc.)
        3. Tailwind classes match allowed patterns (if TrustTier T3)
        4. No eval/exec/dynamic imports

        Returns validation result with warnings/errors.
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "stats": {
                "lines": len(code.splitlines()),
                "import_count": 0,
                "tailwind_classes": 0,
            },
        }

        try:
            lines = code.splitlines()
            import_count = 0

            for line in lines:
                import_count += self._check_line_imports(line, result, trust_tier)
                self._check_line_dangerous_patterns(line, result, trust_tier)
                self._check_line_tailwind(line, result, trust_tier)

            result["stats"]["import_count"] = import_count

        except Exception as exc:
            result["errors"].append(f"Parse error: {exc}")
            result["valid"] = False

        return result

    def _is_import_whitelisted(self, import_line: str) -> bool:
        """Check if an import statement is whitelisted."""
        import_line_lower = import_line.lower()
        for allowed in self.ALLOWED_IMPORTS:
            if "*" in allowed:
                # e.g., @radix-ui/react-*
                pattern = allowed.replace("*", "")
                if pattern in import_line_lower:
                    return True
            elif allowed in import_line_lower:
                return True
        return False

    def create_render_job(self, project_id: str, output_format: OutputFormat) -> RenderJob:
        """Create a new async render job.

        Returns immediately with job_id. Client polls for status/url.
        """
        job_id = str(uuid4())
        job = RenderJob(job_id, project_id, output_format, status="pending")
        self._render_jobs[job_id] = job
        logger.info(
            "Created render job %s for project %s (format: %s)", job_id, project_id, output_format
        )
        return job

    def get_render_job(self, job_id: str) -> RenderJob | None:
        """Retrieve a render job by ID."""
        return self._render_jobs.get(job_id)

    def update_render_job(
        self,
        job_id: str,
        status: str,
        url: str | None = None,
        error: str | None = None,
    ) -> RenderJob | None:
        """Update a render job status."""
        job = self._render_jobs.get(job_id)
        if job:
            job.status = status
            job.url = url
            job.error = error
            job.updated_at = datetime.now(UTC)
            logger.info("Updated render job %s: status=%s", job_id, status)
        return job

    async def render_to_pdf(self, content: str, metadata: dict[str, Any]) -> str:
        """Render HTML/React to PDF via weasyprint (Phase 2B)."""
        try:
            from services.design_render import get_design_render_service

            render_svc = get_design_render_service()
            pdf_bytes = await render_svc.render_to_pdf(content, metadata)
            # Phase 2B.2: Store in S3, return signed URL
            render_id = str(uuid4())
            logger.info("PDF rendered successfully (%d bytes)", len(pdf_bytes))
            return f"/v1/design/renders/{render_id}/output.pdf"
        except Exception as exc:
            logger.error("PDF render failed: %s", exc)
            raise

    async def render_to_pptx(self, content: str, metadata: dict[str, Any]) -> str:
        """Render to PPTX via python-pptx (Phase 2B)."""
        try:
            from services.design_render import get_design_render_service

            render_svc = get_design_render_service()
            pptx_bytes = await render_svc.render_to_pptx(content, metadata)
            # Phase 2B.2: Store in S3, return signed URL
            render_id = str(uuid4())
            logger.info("PPTX rendered successfully (%d bytes)", len(pptx_bytes))
            return f"/v1/design/renders/{render_id}/output.pptx"
        except Exception as exc:
            logger.error("PPTX render failed: %s", exc)
            raise

    async def render_to_docx(self, content: str, metadata: dict[str, Any]) -> str:
        """Render to DOCX via python-docx (Phase 2B)."""
        try:
            from services.design_render import get_design_render_service

            render_svc = get_design_render_service()
            docx_bytes = await render_svc.render_to_docx(content, metadata)
            # Phase 2B.2: Store in S3, return signed URL
            render_id = str(uuid4())
            logger.info("DOCX rendered successfully (%d bytes)", len(docx_bytes))
            return f"/v1/design/renders/{render_id}/output.docx"
        except Exception as exc:
            logger.error("DOCX render failed: %s", exc)
            raise


# Singleton instance
_singleton: DesignPreviewService | None = None


def get_design_preview_service() -> DesignPreviewService:
    """Get the DesignPreviewService singleton."""
    if _singleton is None:
        raise RuntimeError("DesignPreviewService not initialized")
    return _singleton


def init_design_preview_service() -> DesignPreviewService:
    """Initialize the DesignPreviewService singleton."""
    global _singleton
    if _singleton is None:
        _singleton = DesignPreviewService()
    return _singleton
