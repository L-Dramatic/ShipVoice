from __future__ import annotations

import time

from .config import PipelineConfig, load_config
from .models import GateResult, PipelineEvent, PipelineResult, RunMetrics
from .providers import KeywordSafetyGate, MockASRProvider, MockTTSProvider, TermCorrector, build_llm, build_retriever


class VoiceQAPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or load_config()
        latency = self.config.mock_latency_ms
        self.asr = MockASRProvider(latency["asr"])
        self.corrector = TermCorrector(self.config.domain_terms)
        self.gate = KeywordSafetyGate(
            self.config.blocked_keywords,
            self.config.off_domain_keywords,
            self.config.domain_terms,
        )
        self.retriever = build_retriever(self.config)
        self.llm = build_llm(self.config)
        self.tts = MockTTSProvider(latency["tts_first_audio"], latency["tts_chunk"])

    async def run_once(
        self,
        question: str,
        *,
        question_id: str = "manual",
        category: str = "manual",
        mode: str = "full",
    ) -> PipelineResult:
        start = time.perf_counter()
        events: list[PipelineEvent] = []

        def elapsed() -> int:
            return int((time.perf_counter() - start) * 1000)

        def event(stage: str, message: str, **payload: object) -> None:
            events.append(PipelineEvent(stage=stage, message=message, elapsed_ms=elapsed(), payload=dict(payload)))

        latency = self.config.mock_latency_ms
        streaming_enabled = mode in {"streaming", "full"}
        rag_enabled = mode in {"rag", "full"}
        gate_enabled = mode in {"guarded", "full"}

        event("input", "收到用户语音问题", question=question, mode=mode)

        time.sleep(latency["vad"] / 1000)
        event("vad", "检测到用户停止说话", latency_ms=latency["vad"])

        asr_start = elapsed()
        transcript = await self.asr.transcribe(question)
        asr_ms = elapsed() - asr_start
        event("asr", "ASR 完成转写", transcript=transcript, latency_ms=asr_ms)

        corrected, term_hits = self.corrector.correct(transcript)
        if corrected != transcript or term_hits:
            event("term", "完成术语热词/纠错处理", corrected=corrected, term_hits=term_hits)

        gate_result = self.gate.classify(corrected) if gate_enabled else GateResult("not_checked", True, "当前模式未启用安全门控")
        event("gate", "安全门控完成", label=gate_result.label, allowed=gate_result.allowed, reason=gate_result.reason)

        retrieval_ms = 0
        evidence = []
        if rag_enabled and gate_result.allowed:
            retrieval_start = elapsed()
            evidence = await self.retriever.retrieve(corrected)
            retrieval_ms = elapsed() - retrieval_start
            event(
                "retrieval",
                "RAG 检索完成",
                latency_ms=retrieval_ms,
                hits=[{"title": hit.title, "score": hit.score} for hit in evidence],
            )
        elif not gate_result.allowed:
            event("retrieval", "危险或无关请求已短路，跳过知识库检索")
        else:
            event("retrieval", "当前模式未启用 RAG")

        answer = self.llm.build_answer(corrected, evidence, gate_result)

        llm_start = elapsed()
        if streaming_enabled:
            chunks = self.llm.split_chunks(answer)
            first_audio_ms = 0
            await self._sleep_ms(latency["llm_first_token"])
            tts_first_audio_ms = latency["tts_first_audio"]
            for index, chunk in enumerate(chunks, start=1):
                await self._sleep_ms(latency["llm_chunk"])
                if index == 1:
                    await self._sleep_ms(latency["tts_first_audio"])
                    first_audio_ms = elapsed()
                    event("tts", "首句音频已可播放", first_audio_ms=first_audio_ms, chunk=chunk)
            llm_first_token_ms = latency["llm_first_token"]
            event("llm", "流式 LLM 输出完成", chunks=len(chunks), latency_ms=elapsed() - llm_start)
        else:
            # Simulate serial generation: no audio can start before the full answer is ready.
            chunks = await self.llm.stream(answer)
            llm_first_token_ms = elapsed() - llm_start
            event("llm", "串行 LLM 完整回答生成完成", chunks=len(chunks), latency_ms=elapsed() - llm_start)

        if streaming_enabled:
            if len(chunks) > 1:
                await self.tts.synthesize_stream(chunks[1:])
        else:
            tts_start = elapsed()
            await self.tts.synthesize_stream(chunks)
            first_audio_ms = elapsed()
            event("tts", "串行 TTS 完整合成后开始播放", first_audio_ms=first_audio_ms)
            tts_first_audio_ms = first_audio_ms - tts_start

        total_ms = elapsed()
        event("done", "流水线完成", total_ms=total_ms)

        metrics = RunMetrics(
            question_id=question_id,
            mode=mode,
            category=category,
            gate_label=gate_result.label,
            first_audio_ms=first_audio_ms,
            total_ms=total_ms,
            asr_ms=asr_ms,
            retrieval_ms=retrieval_ms,
            llm_first_token_ms=llm_first_token_ms,
            tts_first_audio_ms=tts_first_audio_ms,
            answer_chars=len(answer),
            evidence_count=len(evidence),
        )
        return PipelineResult(
            question=question,
            transcript=corrected,
            answer=answer,
            gate=gate_result,
            evidence=evidence,
            events=events,
            metrics=metrics,
        )

    async def _sleep_ms(self, ms: int) -> None:
        import asyncio

        await asyncio.sleep(ms / 1000)
