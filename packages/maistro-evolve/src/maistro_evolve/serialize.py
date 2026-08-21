from __future__ import annotations

import json
from pathlib import Path

import yaml

from .types import PipelineGenome


def to_yaml(genome: PipelineGenome) -> str:
    data = json.loads(genome.model_dump_json())
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)


def from_yaml(text: str) -> PipelineGenome:
    data = yaml.safe_load(text)
    return PipelineGenome.model_validate(data)


def to_json(genome: PipelineGenome) -> str:
    return genome.model_dump_json(indent=2)


def from_json(text: str) -> PipelineGenome:
    return PipelineGenome.model_validate_json(text)


def save_yaml(genome: PipelineGenome, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(to_yaml(genome))


def load_yaml(path: str | Path) -> PipelineGenome:
    return from_yaml(Path(path).read_text())


def save_json(genome: PipelineGenome, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(to_json(genome))


def load_json(path: str | Path) -> PipelineGenome:
    return from_json(Path(path).read_text())
