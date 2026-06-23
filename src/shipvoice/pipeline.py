from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable

from .config import PipelineConfig, load_config
from .models import GateResult, PipelineEvent, PipelineResult, RunMetrics, TTSResult
from .providers import KeywordSafetyGate, TermCorrector, build_asr, build_llm, build_retriever, build_safety_refusal, build_tts


PUBLIC_RUN_MODES = {"baseline", "streaming", "rag", "guarded", "full"}
STREAM_SENTENCE_MIN_CHARS = 6
STREAM_SENTENCE_SOFT_CHARS = 80


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
        on_audio_chunk: Callable[[dict[str, object]], Awaitable[None] | None] | None = None,
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

        mode = (mode or "full").strip().lower()
        if mode not in PUBLIC_RUN_MODES:
            raise ValueError(f"Unsupported run mode: {mode}")
        rag_enabled = mode in {"rag", "full"}
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
        gate_result = self.gate.classify(contextual_question)
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

        streamed_audio_segments = 0
        server_first_audio_chunk_ready_ms = 0
        server_audio_stream_complete_ms = 0
        response_mode = "complete_payload_non_streaming"

        if gate_result.allowed:
            llm_start = elapsed()
            if mode == "streaming" and hasattr(self.llm, "stream_answer"):
                (
                    answer,
                    tts_result,
                    llm_ms,
                    llm_first_token_ms,
                    tts_first_audio_ms,
                    tts_complete_ms,
                    server_audio_payload_ready_ms,
                    server_first_audio_chunk_ready_ms,
                    server_audio_stream_complete_ms,
                    streamed_audio_segments,
                ) = await self._run_streaming_llm_tts(
                    corrected,
                    evidence,
                    gate_result,
                    history,
                    emit=emit,
                    elapsed=elapsed,
                    llm_start=llm_start,
                    on_audio_chunk=on_audio_chunk,
                )
                response_mode = "llm_token_stream_sentence_tts"
            else:
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
                    llm_complete_ms=llm_ms,
                    provider=self.llm.name,
                )
                tts_start = elapsed()
                tts_result = await self.tts.synthesize(answer)
                server_audio_payload_ready_ms = elapsed()
                tts_complete_ms = server_audio_payload_ready_ms - tts_start
                tts_first_audio_ms = tts_complete_ms
                await emit(
                    "tts",
                    "TTS synthesis completed",
                    server_audio_payload_ready_ms=server_audio_payload_ready_ms,
                    tts_complete_ms=tts_complete_ms,
                    provider=tts_result.provider,
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
            server_audio_payload_ready_ms = elapsed()
            tts_complete_ms = server_audio_payload_ready_ms - tts_start
            tts_first_audio_ms = tts_complete_ms
            await emit(
                "tts",
                "TTS synthesis completed",
                server_audio_payload_ready_ms=server_audio_payload_ready_ms,
                tts_complete_ms=tts_complete_ms,
                provider=tts_result.provider,
            )
        first_audio_ms = server_first_audio_chunk_ready_ms or server_audio_payload_ready_ms
        if not server_audio_stream_complete_ms:
            server_audio_stream_complete_ms = server_audio_payload_ready_ms

        total_ms = elapsed()
        await emit("done", "Pipeline finished", total_ms=total_ms)

        asr_provider = asr_result.provider
        llm_provider = getattr(self.llm, "name", self.llm.__class__.__name__) if gate_result.allowed else "not_called"
        tts_provider = getattr(tts_result, "provider", getattr(self.tts, "name", self.tts.__class__.__name__))
        execution_profile = self._execution_profile(asr_provider, llm_provider, tts_provider)
        timing_source = "server_first_audio_chunk_ready" if streamed_audio_segments else "server_audio_payload_ready"

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
            server_audio_payload_ready_ms=server_audio_payload_ready_ms,
            llm_complete_ms=llm_ms,
            tts_complete_ms=tts_complete_ms,
            llm_first_delta_ms=llm_first_token_ms if streamed_audio_segments else 0,
            server_first_audio_chunk_ready_ms=server_first_audio_chunk_ready_ms,
            server_audio_stream_complete_ms=server_audio_stream_complete_ms,
            streamed_audio_segments=streamed_audio_segments,
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
                "timing_note": (
                    "Server-side first audio chunk ready time; browser playback start is recorded by client timing."
                    if streamed_audio_segments
                    else "Server-side audio payload ready time; browser playback start is recorded by client timing."
                ),
                "response_mode": response_mode,
            },
            audio_output=tts_result or self.tts_default_result(),
        )

    async def _run_streaming_llm_tts(
        self,
        question: str,
        evidence: list,
        gate: GateResult,
        history: list[dict[str, str]],
        *,
        emit: Callable[..., Awaitable[None]],
        elapsed: Callable[[], int],
        llm_start: int,
        on_audio_chunk: Callable[[dict[str, object]], Awaitable[None] | None] | None,
    ) -> tuple[str, TTSResult, int, int, int, int, int, int, int, int]:
        queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
        answer_parts: list[str] = []
        audio_segments: list[str] = []
        provider_name = getattr(self.tts, "name", self.tts.__class__.__name__)
        mime_type = "audio/wav"
        first_delta_ms: int | None = None
        tts_start_ms: int | None = None
        tts_first_audio_ms = 0
        server_first_audio_chunk_ready_ms: int | None = None
        streamed_audio_segments = 0
        next_seq = 0

        async def emit_audio_chunk(payload: dict[str, object]) -> None:
            if on_audio_chunk is None:
                return
            maybe_awaitable = on_audio_chunk(payload)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

        async def tts_worker() -> None:
            nonlocal provider_name
            nonlocal mime_type
            nonlocal tts_start_ms
            nonlocal tts_first_audio_ms
            nonlocal server_first_audio_chunk_ready_ms
            nonlocal streamed_audio_segments
            while True:
                item = await queue.get()
                if item is None:
                    return
                seq, text = item
                segment_start_ms = elapsed()
                if tts_start_ms is None:
                    tts_start_ms = segment_start_ms
                result = await self.tts.synthesize(text)
                ready_ms = elapsed()
                provider_name = result.provider
                mime_type = result.mime_type or mime_type
                if result.audio_base64:
                    audio_segments.append(result.audio_base64)
                streamed_audio_segments += 1
                if server_first_audio_chunk_ready_ms is None:
                    server_first_audio_chunk_ready_ms = ready_ms
                    tts_first_audio_ms = ready_ms - tts_start_ms
                chunk_payload = {
                    "seq": seq,
                    "text": text,
                    "chars": len(text),
                    "audio_base64": result.audio_base64,
                    "mime_type": result.mime_type or mime_type,
                    "provider": result.provider,
                    "tts_segment_ms": ready_ms - segment_start_ms,
                    "server_audio_chunk_ready_ms": ready_ms,
                    "server_first_audio_chunk_ready_ms": server_first_audio_chunk_ready_ms or 0,
                    "first_chunk": seq == 0,
                }
                await emit_audio_chunk(chunk_payload)
                await emit(
                    "tts_chunk",
                    "TTS segment ready",
                    seq=seq,
                    chars=len(text),
                    tts_segment_ms=ready_ms - segment_start_ms,
                    server_audio_chunk_ready_ms=ready_ms,
                    first_chunk=seq == 0,
                    provider=result.provider,
                    mime_type=result.mime_type or mime_type,
                )

        await emit(
            "llm_stream_start",
            "LLM streaming started",
            provider=getattr(self.llm, "name", self.llm.__class__.__name__),
        )
        worker_task = asyncio.create_task(tts_worker())
        buffer = ""
        try:
            async for delta in self.llm.stream_answer(question, evidence, gate, history):
                if not delta:
                    continue
                if first_delta_ms is None:
                    first_delta_ms = max(0, elapsed() - llm_start)
                    await emit("llm_first_delta", "First LLM delta received", llm_first_delta_ms=first_delta_ms)
                answer_parts.append(delta)
                buffer += delta
                await emit("llm_delta", "LLM token delta", delta=delta, answer_chars=sum(len(part) for part in answer_parts))
                while True:
                    sentence, buffer = self._pop_stream_sentence(buffer)
                    if not sentence:
                        break
                    await queue.put((next_seq, sentence))
                    await emit("tts_queue", "Sentence queued for TTS", seq=next_seq, chars=len(sentence))
                    next_seq += 1
            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("LLM streaming returned an empty answer.")
            cited_answer = self._attach_answer_citations(answer, evidence)
            if cited_answer != answer:
                buffer = f"{buffer}{cited_answer[len(answer):]}"
                answer = cited_answer
            final_sentence = buffer.strip()
            if final_sentence:
                await queue.put((next_seq, final_sentence))
                await emit("tts_queue", "Final sentence queued for TTS", seq=next_seq, chars=len(final_sentence))
                next_seq += 1
            llm_ms = max(0, elapsed() - llm_start)
            await emit(
                "llm",
                "LLM streaming completed",
                chunks=next_seq,
                latency_ms=llm_ms,
                llm_first_delta_ms=first_delta_ms or 0,
                llm_complete_ms=llm_ms,
                provider=getattr(self.llm, "name", self.llm.__class__.__name__),
            )
            await queue.put(None)
            await worker_task
        except Exception:
            worker_task.cancel()
            raise

        server_audio_stream_complete_ms = elapsed()
        first_audio_ready_ms = server_first_audio_chunk_ready_ms or 0
        tts_complete_ms = server_audio_stream_complete_ms - tts_start_ms if tts_start_ms is not None else 0
        await emit(
            "tts",
            "TTS streaming completed",
            server_first_audio_chunk_ready_ms=first_audio_ready_ms,
            server_audio_stream_complete_ms=server_audio_stream_complete_ms,
            server_audio_payload_ready_ms=first_audio_ready_ms,
            tts_first_audio_ms=tts_first_audio_ms,
            tts_complete_ms=tts_complete_ms,
            streamed_audio_segments=streamed_audio_segments,
            provider=provider_name,
        )
        return (
            answer,
            TTSResult(provider=provider_name, audio_segments=audio_segments, audio_base64="", mime_type=mime_type),
            llm_ms,
            first_delta_ms or 0,
            tts_first_audio_ms,
            tts_complete_ms,
            first_audio_ready_ms,
            first_audio_ready_ms,
            server_audio_stream_complete_ms,
            streamed_audio_segments,
        )

    async def _run_llm(self, question: str, evidence: list, gate: GateResult, history: list[dict[str, str]]) -> str:
        return await asyncio.to_thread(self.llm.build_answer, question, evidence, gate, history)

    @staticmethod
    def _pop_stream_sentence(buffer: str, *, force: bool = False) -> tuple[str, str]:
        text = buffer.strip()
        if not text:
            return "", ""
        for match in re.finditer(r"[。！？!?；;]", text):
            end = match.end()
            if end >= STREAM_SENTENCE_MIN_CHARS or force:
                return text[:end].strip(), text[end:].lstrip()
        if len(text) >= STREAM_SENTENCE_SOFT_CHARS:
            comma_positions = [text.rfind("，"), text.rfind(","), text.rfind("、")]
            split_at = max(comma_positions)
            if split_at >= STREAM_SENTENCE_MIN_CHARS:
                return text[: split_at + 1].strip(), text[split_at + 1 :].lstrip()
        if force:
            return text, ""
        return "", buffer

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
