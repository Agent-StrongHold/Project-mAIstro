"""Failure-mode regression tests for security fixes #1 and #5.

Moved from packages/maistro-core/tests/security/test_security_regression.py:
these exercise hive-conductor's `services` modules, which only resolve with
the backend on sys.path (this suite's conftest does that), so they always
failed inside maistro-core's test run.
"""

import asyncio

# ─── #1: Fail-closed executor refuses when no sandbox available ───────────────


class TestFailClosedExecutor:
    """The executor MUST refuse when no isolation backend is installed."""

    def test_no_backend_refuses_execution(self):
        """With all backends unavailable, execute_node returns fail-closed."""
        from services.hyperlight_executor import SandboxExecutor

        executor = SandboxExecutor()
        # Force no backend
        executor._backend = None

        result = asyncio.run(executor.execute_node("print('hi')"))
        assert result["success"] is False
        assert result["isolation"] == "fail-closed"
        assert "REFUSED" in result["error"]

    def test_no_backend_available_property_false(self):
        from services.hyperlight_executor import SandboxExecutor

        executor = SandboxExecutor()
        executor._backend = None
        assert executor.available is False


# ─── #5: Default-deny node classification ─────────────────────────────────────


class TestDefaultDenyNodeClassification:
    """Unconfigured nodes MUST NOT get the trusted 'async' tier."""

    def test_unconfigured_node_gets_sandbox(self):
        from services.graph_runner import _classify_node_execution

        node = {"config": {}}  # No tier, no capabilities
        result = _classify_node_execution(node, "test-node")
        assert result == "sandbox"

    def test_untrusted_without_approval_is_blocked(self):
        from services.graph_runner import _classify_node_execution

        node = {"config": {"untrusted": True}}  # No tier_approved_by
        result = _classify_node_execution(node, "test-node")
        assert result == "blocked"

    def test_untrusted_with_approval_gets_sandbox(self):
        from services.graph_runner import _classify_node_execution

        node = {"config": {"untrusted": True, "tier_approved_by": "admin"}}
        result = _classify_node_execution(node, "test-node")
        assert result == "sandbox"

    def test_explicitly_safe_gets_async(self):
        from services.graph_runner import _classify_node_execution

        node = {"config": {"execution_tier": "safe"}}
        result = _classify_node_execution(node, "test-node")
        assert result == "async"
