from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PipelineConfig:
    project_name: str
    latency_targets_ms: dict[str, int]
    mock_latency_ms: dict[str, int]
    rag: dict[str, Any]
    llm: dict[str, Any]
    domain_terms: list[str]
    blocked_keywords: list[str]
    off_domain_keywords: list[str]


def load_config(path: str | Path | None = None) -> PipelineConfig:
    config_path = Path(path) if path else PROJECT_ROOT / "configs" / "pipeline.json"
    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    return PipelineConfig(
        project_name=str(data["project_name"]),
        latency_targets_ms=dict(data["latency_targets_ms"]),
        mock_latency_ms=dict(data["mock_latency_ms"]),
        rag=dict(data.get("rag", {})),
        llm=dict(data.get("llm", {})),
        domain_terms=list(data["domain_terms"]),
        blocked_keywords=list(data["blocked_keywords"]),
        off_domain_keywords=list(data["off_domain_keywords"]),
    )


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)
