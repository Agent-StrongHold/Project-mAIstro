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

# Sentinel tool-argument resource floors. Deployments may tighten these freely;
# raising them requires an explicit security configuration override.
TOOL_ARGUMENT_MAX_BYTES = 100 * 1024
TOOL_ARGUMENT_MAX_DEPTH = 32

# Thumbs retention for the optimizer's user-satisfaction signal (#696).
#
# The reader these replace had no window and no bound at all: it walked
# `InMemoryOutcomeStore._outcomes` end to end, so its effective retention was
# whatever `MAX_OUTCOMES` happened to be and its effective window was "since
# this process started". Neither was a decision anyone took.
#
# 90 days because a thumb is a judgement about a node's behaviour, and a node
# that was rewritten last week should not still be scored on feedback from a
# quarter ago -- but the optimizer runs on a 24-hour metrics window, so a
# thumbs window that short would make user feedback the one signal that
# vanished between runs.
THUMB_WINDOW_DAYS = 90

# Bound on one thumbs read. Large enough that no realistic DAG's feedback is
# truncated, small enough that a durable store is never asked for an unbounded
# scan. A truncated read is the most recent thumbs, which is the half that
# matters if it ever binds.
THUMB_LIMIT = 5_000
