"""Named constants replacing magic numbers throughout the codebase."""

from __future__ import annotations

# Chat completions — size of each SSE text chunk (chars)
STREAM_CHUNK_SIZE = 20

# Logging preview length for task descriptions
DESCRIPTION_LOG_PREVIEW_LEN = 80

# Webhook body preview length when building task descriptions
WEBHOOK_BODY_PREVIEW_LEN = 500

# WebSocket polling interval (seconds)
WS_POLL_INTERVAL = 0.5

# Worker loop poll timeout for next task (seconds)
WORKER_POLL_TIMEOUT = 1.0

# Max output bytes from sandbox exec
SANDBOX_MAX_OUTPUT = 100_000

# Default permission grant TTL (seconds)
PERMISSION_TTL = 3600

# Max task description length for prompt-stuffing prevention
PERMISSION_MAX_INPUT = 50_000
