#!/usr/bin/env python3
"""One-shot GitHub issue closeout for the 2026-10-23 likely-done certification.

Reads payload.json next to this script. Intended to run in Actions with
permissions: issues: write (GITHUB_TOKEN). Safe to re-run: skips already-closed
issues and no-ops when the body is already patched.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "Agent-StrongHold/Project-mAIstro")
API = "https://api.github.com"
HERE = Path(__file__).resolve().parent

CLOSE_COMMENT = (
    "Closing as done: certified against develop inventory notes + in-tree "
    "implementation (2026-10-23 pass3 likely-done review)."
)
TICK_COMMENT = (
    "Acceptance checkboxes updated from inventory-note + code review "
    "(2026-10-23). Remaining open boxes (if any) are named residuals."
)


def token() -> str:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not t:
        raise SystemExit("GH_TOKEN / GITHUB_TOKEN required")
    return t


def api(method: str, path: str, tok: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "one-shot-issue-closeout",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:800]}") from e


def get_issue(tok: str, n: int) -> dict:
    return api("GET", f"/repos/{REPO}/issues/{n}", tok)


def comment(tok: str, n: int, body: str) -> None:
    try:
        api("POST", f"/repos/{REPO}/issues/{n}/comments", tok, {"body": body})
    except Exception as exc:  # noqa: BLE001
        print(f"  warn: comment failed on #{n}: {exc}")


def main() -> int:
    payload = json.loads((HERE / "payload.json").read_text())
    tok = token()
    results: dict = {"closed": [], "ticked": [], "skipped": [], "failed": []}

    # Probe write
    probe_n = (payload["close_direct"] or payload["tick_and_close"] or payload["tick_only"] or [1])[0]
    try:
        api(
            "PATCH",
            f"/repos/{REPO}/issues/{probe_n}",
            tok,
            {},  # empty patch — may 422; any non-403 proves write
        )
    except RuntimeError as exc:
        if "403" in str(exc):
            print(
                "FATAL: token cannot write issues (403). "
                "Repo Actions may be read-only for GITHUB_TOKEN; "
                "add a PAT secret or raise workflow permissions.",
                file=sys.stderr,
            )
            print(exc, file=sys.stderr)
            return 2
        # 422 on empty body is fine
        if "422" not in str(exc):
            print(f"probe note: {exc}")

    for n in payload["close_direct"]:
        try:
            issue = get_issue(tok, n)
            if issue["state"] == "closed":
                print(f"skip already-closed #{n}")
                results["skipped"].append(n)
                continue
            print(f"close #{n}")
            api(
                "PATCH",
                f"/repos/{REPO}/issues/{n}",
                tok,
                {"state": "closed", "state_reason": "completed"},
            )
            comment(tok, n, CLOSE_COMMENT)
            results["closed"].append(n)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL close #{n}: {exc}")
            results["failed"].append({"number": n, "op": "close", "error": str(exc)[:400]})
        time.sleep(0.25)

    bodies: dict[str, str] = payload.get("bodies") or {}

    for n in payload["tick_and_close"]:
        try:
            issue = get_issue(tok, n)
            body = bodies[str(n)]
            if issue["state"] == "closed" and issue.get("body") == body:
                print(f"skip already-done #{n}")
                results["skipped"].append(n)
                continue
            print(f"tick+close #{n}")
            payload_patch: dict = {"body": body}
            if issue["state"] != "closed":
                payload_patch["state"] = "closed"
                payload_patch["state_reason"] = "completed"
            api("PATCH", f"/repos/{REPO}/issues/{n}", tok, payload_patch)
            comment(
                tok,
                n,
                CLOSE_COMMENT + "\n\nAcceptance boxes ticked as satisfied per inventory-note review.",
            )
            results["ticked"].append(n)
            results["closed"].append(n)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL tick+close #{n}: {exc}")
            results["failed"].append({"number": n, "op": "tick_close", "error": str(exc)[:400]})
        time.sleep(0.25)

    for n in payload["tick_only"]:
        try:
            issue = get_issue(tok, n)
            body = bodies[str(n)]
            if issue.get("body") == body:
                print(f"skip body-already-patched #{n}")
                results["skipped"].append(n)
                continue
            print(f"tick-only #{n} (leave open)")
            api("PATCH", f"/repos/{REPO}/issues/{n}", tok, {"body": body})
            comment(tok, n, TICK_COMMENT)
            results["ticked"].append(n)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL tick-only #{n}: {exc}")
            results["failed"].append({"number": n, "op": "tick_only", "error": str(exc)[:400]})
        time.sleep(0.25)

    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in results.items()}, indent=2))
    print("closed:", results["closed"])
    print("ticked:", results["ticked"])
    print("failed:", results["failed"])
    (HERE / "results.json").write_text(json.dumps(results, indent=2))
    return 1 if results["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
