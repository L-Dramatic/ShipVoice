from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PipelineConfig:
    project_name: str
    latency_targets_ms: dict[str, int]
    mock_latency_ms: dict[str, int]
    asr: dict[str, Any]
    rag: dict[str, Any]
    llm: dict[str, Any]
    tts: dict[str, Any]
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
        asr=dict(data.get("asr", {})),
        rag=dict(data.get("rag", {})),
        llm=dict(data.get("llm", {})),
        tts=dict(data.get("tts", {})),
        domain_terms=list(data["domain_terms"]),
        blocked_keywords=list(data["blocked_keywords"]),
        off_domain_keywords=list(data["off_domain_keywords"]),
    )


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def load_env_file(path: str | Path, *, override: bool = True) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = PROJECT_ROOT / env_path
    if not env_path.exists():
        raise FileNotFoundError(f"env file not found: {env_path}")

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value

    os.environ["SHIPVOICE_ENV_FILE"] = str(env_path.resolve())
    loaded["SHIPVOICE_ENV_FILE"] = str(env_path.resolve())
    return loaded
