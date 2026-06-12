from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from .config import PipelineConfig, load_config
from .models import GateResult, PipelineEvent, PipelineResult, RunMetrics
from .providers import KeywordSafetyGate, TermCorrector, build_asr, build_llm, build_retriever, build_tts


class VoiceQAPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or load_config()
        self.asr = build_asr(self.config)
        self.corrector = TermCorrector(self.config.domain_terms)
        self.gate = KeywordSafetyGate(
            self.config.blocked_keywords,
            self.config.off_domain_keywords,
            self.config.domain_terms,
        )
        self.retriever = build_retriever(self.config)
        self.llm = build_llm(self.config)
        self.tts = build_tts(self.config)

    async def run_once(
        self,
        question: str,
        *,
        audio_bytes: bytes | None = None,
        audio_name: str = "",
        history: list[dict[str, str]] | None = None,
        question_id: str = "manual",
        category: str = "manual",
        mode: str = "full",
        on_event: Callable[[PipelineEvent], Awaitable[None] | None] | None = None,
    ) -> PipelineResult:
        import time

        start = time.perf_counter()
        history = history or []
        events: list[PipelineEvent] = []

        def elapsed() -> int:
            return int((time.perf_counter() - start) * 1000)

        async def emit(stage: str, message: str, **payload: object) -> None:
            item = PipelineEvent(stage=stage, message=message, elapsed_ms=elapsed(), payload=dict(payload))
            events.append(item)
            if on_event is not None:
                maybe_awaitable = on_event(item)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable

        latency = self.config.mock_latency_ms
        streaming_enabled = mode in {"streaming", "full"}
        rag_enabled = mode in {"rag", "full"}
        gate_enabled = mode in {"guarded", "full"}
        input_mode = "audio" if audio_bytes else "text"

        await emit(
            "input",
            "Received user input",
            question=question,
            mode=mode,
            input_mode=input_mode,
            audio_name=audio_name,
            history_turns=len(history),
        )

        await self._sleep_ms(latency["vad"])
        await emit("vad", "Detected end of utterance", latency_ms=latency["vad"])

        asr_start = elapsed()
        asr_result = await self.asr.transcribe(question, audio_bytes=audio_bytes, audio_name=audio_name)
        asr_ms = elapsed() - asr_start
        transcript = asr_result.transcript
        await emit("asr", "ASR completed", transcript=transcript, latency_ms=asr_ms)

        corrected, term_hits = self.corrector.correct(transcript)
        if corrected != transcript or term_hits:
            await emit("term", "Domain term correction completed", corrected=corrected, term_hits=term_hits)

        contextual_question = self._contextualize_question(corrected, history)
        gate_result = (
            self.gate.classify(contextual_question)
            if gate_enabled
            else GateResult("not_checked", True, "Safety gate disabled in current mode")
        )
        await emit(
            "gate",
            "Safety gate completed",
            label=gate_result.label,
            allowed=gate_result.allowed,
            reason=gate_result.reason,
        )

        retrieval_ms = 0
        evidence = []
        if rag_enabled and gate_result.allowed:
            retrieval_start = elapsed()
            evidence = await self.retriever.retrieve(contextual_question)
            retrieval_ms = elapsed() - retrieval_start
            await emit(
                "retrieval",
                "RAG retrieval completed",
                latency_ms=retrieval_ms,
                hits=[{"title": hit.title, "score": hit.score} for hit in evidence],
            )
        elif not gate_result.allowed:
            await emit("retrieval", "Request blocked, retrieval skipped")
        else:
            await emit("retrieval", "RAG disabled in current mode")

        llm_start = elapsed()
        answer = await self._run_llm(corrected, evidence, gate_result, history)
        llm_ms = elapsed() - llm_start
        chunks = self.llm.split_chunks(answer)

        tts_result = None
        if streaming_enabled and getattr(self.llm, "uses_mock_timing", False) and getattr(self.tts, "supports_streaming", False):
            first_audio_ms = 0
            await self._sleep_ms(latency["llm_first_token"])
            tts_first_audio_ms = latency["tts_first_audio"]
            for index, chunk in enumerate(chunks, start=1):
                await self._sleep_ms(latency["llm_chunk"])
                if index == 1:
                    tts_result = await self.tts.synthesize_stream([chunk])
                    first_audio_ms = elapsed()
                    await emit(
                        "tts",
                        "First audio chunk ready",
                        first_audio_ms=first_audio_ms,
                        chunk=chunk,
                        provider=tts_result.provider,
                    )
            llm_first_token_ms = latency["llm_first_token"]
            await emit(
                "llm",
                "Streaming LLM output completed",
                chunks=len(chunks),
                latency_ms=elapsed() - llm_start,
                provider=self.llm.name,
            )
        else:
            llm_first_token_ms = llm_ms
            await emit(
                "llm",
                "LLM answer completed",
                chunks=len(chunks),
                latency_ms=llm_ms,
                provider=self.llm.name,
            )
            tts_start = elapsed()
            tts_result = await self.tts.synthesize(answer)
            first_audio_ms = elapsed()
            await emit(
                "tts",
                "TTS synthesis completed",
                first_audio_ms=first_audio_ms,
                provider=tts_result.provider,
            )
            tts_first_audio_ms = first_audio_ms - tts_start

        total_ms = elapsed()
        await emit("done", "Pipeline finished", total_ms=total_ms)

        asr_provider = asr_result.provider
        llm_provider = getattr(self.llm, "name", self.llm.__class__.__name__)
        tts_provider = getattr(tts_result, "provider", getattr(self.tts, "name", self.tts.__class__.__name__))
        execution_profile = self._execution_profile(asr_provider, llm_provider, tts_provider)
        timing_source = (
            "simulated"
            if getattr(self.llm, "uses_mock_timing", False) and getattr(self.tts, "supports_streaming", False)
            else "observed"
        )

        metrics = RunMetrics(
            question_id=question_id,
            mode=mode,
            category=category,
            gate_label=gate_result.label,
            input_mode=input_mode,
            asr_provider=asr_provider,
            llm_provider=llm_provider,
            tts_provider=tts_provider,
            execution_profile=execution_profile,
            timing_source=timing_source,
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
            provider_status={
                "input_mode": input_mode,
                "asr": asr_provider,
                "llm": llm_provider,
                "tts": tts_provider,
                "execution_profile": execution_profile,
                "timing_source": timing_source,
            },
            audio_output=tts_result or self.tts_default_result(),
        )

    async def _sleep_ms(self, ms: int) -> None:
        import asyncio

        await asyncio.sleep(ms / 1000)

    async def _run_llm(self, question: str, evidence: list, gate: GateResult, history: list[dict[str, str]]) -> str:
        import asyncio

        return await asyncio.to_thread(self.llm.build_answer, question, evidence, gate, history)

    def tts_default_result(self):
        from .models import TTSResult

        return TTSResult(provider=getattr(self.tts, "name", self.tts.__class__.__name__))

    def _execution_profile(self, asr_provider: str, llm_provider: str, tts_provider: str) -> str:
        providers = [asr_provider, llm_provider, tts_provider]
        mock_like = [provider for provider in providers if provider.startswith("mock") or provider == "transcript_fallback"]
        if len(mock_like) == len(providers):
            return "demo"
        if mock_like:
            return "hybrid"
        return "real"

    def _contextualize_question(self, question: str, history: list[dict[str, str]]) -> str:
        recent_user_turns = [item["content"].strip() for item in history if item.get("role") == "user" and item.get("content")]
        context = recent_user_turns[-2:]
        if not context:
            return question
        return " ".join(context + [question])
