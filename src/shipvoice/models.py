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
    record_id: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    matched_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ASRResult:
    transcript: str
    provider: str
    source: str


@dataclass
class TTSResult:
    provider: str
    audio_segments: list[str] = field(default_factory=list)
    audio_base64: str = ""
    mime_type: str = ""


@dataclass
class RunMetrics:
    question_id: str
    mode: str
    category: str
    gate_label: str
    input_mode: str
    asr_provider: str
    llm_provider: str
    tts_provider: str
    execution_profile: str
    timing_source: str
    first_audio_ms: int
    total_ms: int
    asr_ms: int
    retrieval_ms: int
    llm_first_token_ms: int
    tts_first_audio_ms: int
    answer_chars: int
    evidence_count: int
    server_audio_payload_ready_ms: int = 0
    llm_complete_ms: int = 0
    tts_complete_ms: int = 0
    llm_first_delta_ms: int = 0
    server_first_audio_chunk_ready_ms: int = 0
    server_audio_stream_complete_ms: int = 0
    streamed_audio_segments: int = 0

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
    provider_status: dict[str, str] = field(default_factory=dict)
    audio_output: TTSResult = field(default_factory=lambda: TTSResult(provider="none"))


@dataclass
class AuditRecord:
    run_id: str
    session_id: str
    status: str
    created_at: str
    mode: str
    question: str
    transcript: str = ""
    gate_label: str = ""
    gate_allowed: bool | None = None
    answer_preview: str = ""
    providers: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    evidence_titles: list[str] = field(default_factory=list)
    audio_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
