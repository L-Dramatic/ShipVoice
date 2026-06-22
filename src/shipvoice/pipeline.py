from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from .config import PipelineConfig, load_config
from .models import GateResult, PipelineEvent, PipelineResult, RunMetrics
from .providers import KeywordSafetyGate, TermCorrector, build_asr, build_llm, build_retriever, build_safety_refusal, build_tts


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

        await emit("vad", "Input boundary accepted", latency_ms=0)

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
                hits=[
                    {
                        "record_id": hit.record_id,
                        "title": hit.title,
                        "score": hit.score,
                        "confidence": hit.confidence,
                        "risk_level": hit.risk_level,
                        "matched_terms": hit.matched_terms,
                    }
                    for hit in evidence
                ],
            )
        elif not gate_result.allowed:
            await emit("retrieval", "Request blocked, retrieval skipped")
        else:
            await emit("retrieval", "RAG disabled in current mode")

        if gate_result.allowed:
            llm_start = elapsed()
            answer = await self._run_llm(corrected, evidence, gate_result, history)
            answer = self._attach_answer_citations(answer, evidence)
            llm_ms = elapsed() - llm_start
            chunks = self.llm.split_chunks(answer)
            llm_first_token_ms = llm_ms
            await emit(
                "llm",
                "LLM answer completed",
                chunks=len(chunks),
                latency_ms=llm_ms,
                provider=self.llm.name,
            )
        else:
            llm_ms = 0
            llm_first_token_ms = 0
            answer = build_safety_refusal(gate_result)
            chunks = self.llm.split_chunks(answer)
            await emit(
                "llm",
                "LLM skipped because safety gate blocked the request",
                chunks=len(chunks),
                latency_ms=0,
                provider="not_called",
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
        llm_provider = getattr(self.llm, "name", self.llm.__class__.__name__) if gate_result.allowed else "not_called"
        tts_provider = getattr(tts_result, "provider", getattr(self.tts, "name", self.tts.__class__.__name__))
        execution_profile = self._execution_profile(asr_provider, llm_provider, tts_provider)
        timing_source = "observed"

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

    async def _run_llm(self, question: str, evidence: list, gate: GateResult, history: list[dict[str, str]]) -> str:
        import asyncio

        return await asyncio.to_thread(self.llm.build_answer, question, evidence, gate, history)

    @staticmethod
    def _attach_answer_citations(answer: str, evidence: list) -> str:
        citation_hits = [hit for hit in evidence if getattr(hit, "record_id", "")]
        if not citation_hits:
            return answer
        if any(hit.record_id in answer for hit in citation_hits):
            return answer
        citations = "；".join(f"[{hit.record_id}] {hit.title}" for hit in citation_hits[:2])
        return f"{answer.rstrip()} 依据：{citations}。"

    def tts_default_result(self):
        from .models import TTSResult

        return TTSResult(provider=getattr(self.tts, "name", self.tts.__class__.__name__))

    def _execution_profile(self, asr_provider: str, llm_provider: str, tts_provider: str) -> str:
        if asr_provider == "text_input":
            return "real_text"
        if llm_provider == "not_called":
            return "real_guarded"
        return "real_voice"

    def _contextualize_question(self, question: str, history: list[dict[str, str]]) -> str:
        recent_user_turns = [item["content"].strip() for item in history if item.get("role") == "user" and item.get("content")]
        context = recent_user_turns[-2:]
        if not context:
            return question
        return " ".join(context + [question])
