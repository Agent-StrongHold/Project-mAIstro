"""Configure verbose console logging for local PM POC debugging."""

from __future__ import annotations

import logging
import os
import re
import sys

from settings_defaults import is_pm_poc_mode

from maistro.security.log_redaction import install_log_redaction

_CONFIGURED = False
_REDACTION_ACTIVE = False
_OAUTH_CALLBACK_QUERY_RE = re.compile(
    r'(?P<path>/v1/auth/oauth/[^/?#\s"]{1,128}/callback)\?[^\s"]*'
)


def _sanitize_access_log_value(value: str) -> str:
    return _OAUTH_CALLBACK_QUERY_RE.sub(r"\g<path>", value)


class OAuthCallbackQueryFilter(logging.Filter):
    """Remove the entire sensitive query from Uvicorn callback access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _sanitize_access_log_value(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _sanitize_access_log_value(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: _sanitize_access_log_value(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def _install_oauth_access_log_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthCallbackQueryFilter) for item in access_logger.filters):
        access_logger.addFilter(OAuthCallbackQueryFilter())


def _install_redaction() -> None:
    """Wrap every live log handler with ADR-064 secret redaction.

    Degraded loudly rather than silently (the F3 precedent): if this cannot be
    installed, every subsequent log line carries secrets verbatim, which is the
    exact condition SECURITY.md claims does not happen. A silent `except: pass`
    here would reproduce the gap it exists to close, so the failure is warned
    about and published on /health.
    """
    global _REDACTION_ACTIVE
    try:
        install_log_redaction()
        _REDACTION_ACTIVE = True
    except Exception as exc:  # pragma: no cover - requires a broken maistro-core
        _REDACTION_ACTIVE = False
        # The rule fires on the word "secrets" in the format string. `exc` can only
        # be an import failure for `maistro.security.log_redaction` or a handler-
        # manipulation error from inside it, so its text is a module path or a
        # handler repr — never credential material. Worth stating plainly because
        # this is the one line in the process that redaction is NOT covering: it
        # only runs when installing redaction failed.
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs an import/attribute error from the redaction installer, never key material
        logging.getLogger("hive").warning(
            "log_redaction_unavailable: logs are NOT scrubbed of secrets (ADR-064): %s",
            exc,
        )


def redaction_active() -> bool:
    """Whether ADR-064 log redaction is installed. Read by /health."""
    return _REDACTION_ACTIVE


def configure_logging() -> str:
    """Apply log level from HIVE_LOG_LEVEL / PM mode. Returns active level name."""
    global _CONFIGURED
    if _CONFIGURED:
        # Uvicorn may have reconfigured its logger after the app module import;
        # lifespan calls this again, so restore the callback-query guard.
        _install_oauth_access_log_filter()
        return logging.getLevelName(logging.getLogger().level).lower()

    level_name = os.getenv("HIVE_LOG_LEVEL", "").strip().lower()
    if not level_name and is_pm_poc_mode():
        level_name = "debug"
    if not level_name:
        level_name = "info"

    level = getattr(logging, level_name.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)

    for name in ("hive", "hive.engine", "hive.auth_middleware", "hive.request", "maistro"):
        logging.getLogger(name).setLevel(level)

    logging.getLogger("uvicorn.access").setLevel(
        logging.INFO if level <= logging.DEBUG else logging.WARNING
    )
    _install_oauth_access_log_filter()

    # ADR-064 — must be the last thing that touches the handler chain, since it
    # wraps the formatters that exist at this moment. The Conductor's own handler
    # is only added when root has none (uvicorn usually got there first), so this
    # covers uvicorn's handlers too, not just the one above.
    _install_redaction()

    _CONFIGURED = True
    logging.getLogger("hive").info(
        "logging configured level=%s pm_poc=%s",
        level_name,
        is_pm_poc_mode(),
    )
    return level_name
