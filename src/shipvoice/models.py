from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PipelineEvent:
    stage: str
    message: str
    elapsed_ms: int
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    label: str
    allowed: bool
    reason: str


@dataclass
class RetrievalHit:
    title: str
    text: str
    score: int


@dataclass
class RunMetrics:
    question_id: str
    mode: str
    category: str
    gate_label: str
    first_audio_ms: int
    total_ms: int
    asr_ms: int
    retrieval_ms: int
    llm_first_token_ms: int
    tts_first_audio_ms: int
    answer_chars: int
    evidence_count: int

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    question: str
    transcript: str
    answer: str
    gate: GateResult
    evidence: list[RetrievalHit]
    events: list[PipelineEvent]
    metrics: RunMetrics

