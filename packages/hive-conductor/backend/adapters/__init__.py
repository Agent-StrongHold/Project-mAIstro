"""Concrete adapter ports and implementations used by Hive Conductor services.

Exports here are intentional public seams: route/service code imports concrete
implementations lazily to keep optional dependencies cheap, while tests and
architecture scanners use this module to prove the adapter boundary exists.
"""

from adapters.task_backend import (
    LocalTaskBackend,
    MaistroServerTaskBackend,
    TaskBackend,
    TaskRecord,
)
from adapters.telemetry_noop import NoopTelemetry

__all__ = [
    "LocalTaskBackend",
    "MaistroServerTaskBackend",
    "NoopTelemetry",
    "TaskBackend",
    "TaskRecord",
]
