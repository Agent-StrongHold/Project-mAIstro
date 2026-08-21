"""In-process repo security scanner. No user code execution — file reads only."""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

PRIMITIVE_ID = "repo_security_scan"


async def scan_repo(repo_url: str, branch: str = "main") -> dict[str, Any]:
    """Clone repo and run static analysis. Returns {status, findings, summary}."""
    workdir = Path(tempfile.mkdtemp(prefix="fantasia-scan-"))
    try:
        await _clone(repo_url, branch, workdir)
        return await scan_repo_dir(workdir)
    except Exception as e:
        return {"status": "error", "findings": [], "summary": _summarize([]), "error": str(e)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def scan_repo_dir(workdir: Path) -> dict[str, Any]:
    """Run all scanners on an already-cloned directory."""
    findings = []
    findings += await _run_bandit(workdir)
    findings += await _run_semgrep(workdir)
    findings += await _run_trivy(workdir)
    summary = _summarize(findings)
    status = "passed"
    return {"status": status, "findings": findings, "summary": summary}


async def _clone(repo_url: str, branch: str, workdir: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        branch,
        repo_url,
        str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {stderr.decode()[:500]}")


async def _run_bandit(workdir: Path) -> list[dict]:
    """Run bandit on Python files."""
    py_files = list(workdir.rglob("*.py"))
    if not py_files:
        return []
    proc = await asyncio.create_subprocess_exec(
        "bandit",
        "-r",
        str(workdir),
        "-f",
        "json",
        "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    if not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return [
        {
            "tool": "bandit",
            "severity": r.get("issue_severity", "medium").lower(),
            "file": str(Path(r.get("filename", "")).relative_to(workdir)),
            "line": r.get("line_number"),
            "rule_id": r.get("test_id", ""),
            "message": r.get("issue_text", ""),
        }
        for r in data.get("results", [])
    ]


async def _run_semgrep(workdir: Path) -> list[dict]:
    """Run semgrep with auto config."""
    proc = await asyncio.create_subprocess_exec(
        "semgrep",
        "--config",
        "auto",
        "--json",
        "--quiet",
        str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    if not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return [
        {
            "tool": "semgrep",
            "severity": r.get("extra", {}).get("severity", "medium").lower(),
            "file": str(Path(r.get("path", "")).relative_to(workdir)),
            "line": r.get("start", {}).get("line"),
            "rule_id": r.get("check_id", ""),
            "message": r.get("extra", {}).get("message", ""),
        }
        for r in data.get("results", [])
    ]


async def _run_trivy(workdir: Path) -> list[dict]:
    """Run trivy on Dockerfile and filesystem."""
    dockerfile = workdir / "Dockerfile"
    if not dockerfile.exists():
        return []
    proc = await asyncio.create_subprocess_exec(
        "trivy",
        "fs",
        "--format",
        "json",
        "--quiet",
        str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    if not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings = []
    for result in data.get("Results", []):
        for vuln in result.get("Vulnerabilities", []):
            findings.append(
                {
                    "tool": "trivy",
                    "severity": vuln.get("Severity", "MEDIUM").lower(),
                    "file": result.get("Target", "Dockerfile"),
                    "line": None,
                    "rule_id": vuln.get("VulnerabilityID", ""),
                    "message": vuln.get("Title", ""),
                }
            )
    return findings


def _summarize(findings: list[dict]) -> dict:
    """Summarize findings by severity."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info")
        if sev in counts:
            counts[sev] += 1
    total = sum(counts.values())
    blocking = counts["critical"] > 0 or counts["high"] > 0
    return {"total": total, **counts, "blocking": blocking}
