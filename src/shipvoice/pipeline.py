from __future__ import annotations

import asyncio
import inspect
import re
import threading
from collections.abc import Awaitable, Callable

from .config import PipelineConfig, load_config
from .models import GateResult, PipelineEvent, PipelineResult, RunMetrics, TTSResult
from .providers import KeywordSafetyGate, TermCorrector, build_asr, build_llm, build_retriever, build_safety_refusal, build_tts


PUBLIC_RUN_MODES = {"baseline", "streaming", "rag", "guarded", "full"}
STREAM_SENTENCE_MIN_CHARS = 6
STREAM_SENTENCE_SOFT_CHARS = 80
STREAM_HIGH_RISK_TERMS = (
    "密闭舱室",
    "有限空间",
    "动火",
    "吊装",
    "报警",
    "触电",
    "救援",
    "昏迷",
    "中毒",
    "爆炸",
    "泄漏",
    "试压",
    "高处",
)
STREAM_UNSAFE_ACTION_TERMS = (
    "可以进入",
    "能进入",
    "允许进入",
    "先进去",
    "直接进去",
    "可以作业",
    "可以继续",
    "能继续",
    "可以关闭报警",
    "关闭报警",
    "关掉报警",
    "关闭报警继续",
    "拔掉报警",
    "继续干",
    "继续作业",
    "不用检测",
    "不用测氧",
    "不用测爆",
    "不测氧",
    "不测爆",
    "不用审批",
    "免审批",
    "跳过审批",
    "绕过审批",
    "规避审批",
)
STREAM_SAFETY_QUALIFIER_TERMS = (
    "不要",
    "不能",
    "禁止",
    "停止",
    "暂停",
    "必须",
    "应先",
    "先完成",
    "审批",
    "检测",
    "通风",
    "测氧",
    "测爆",
    "隔离",
    "监护",
    "负责人",
    "安全管理",
    "条件不满足",
    "后方可",
    "后才能",
    "确认后",
    "满足后",
)
STREAM_HIGH_RISK_SAFETY_PREFIX = "安全提示：不要直接行动，应先停止作业并完成审批、检测、隔离和监护确认。"
STREAM_SEGMENT_SAFETY_FALLBACK = "安全提示：不要直接进入、关闭报警或继续作业；应先停止并完成审批、检测、隔离和监护确认。"
OUTPUT_GUARD_SAFE_PREFIXES = ("不要", "不能", "禁止", "不得", "严禁", "停止", "暂停", "不可以", "不允许")
OUTPUT_GUARD_COMPLETION_QUALIFIERS = ("完成", "确认", "满足", "审批", "检测", "通风", "测氧", "测爆", "隔离", "监护")
OUTPUT_GUARD_CONDITIONAL_TRAPS = ("除非", "否则", "但是", "但", "不过")
IDENTITY_HELP_TERMS = (
    "你是什么",
    "你是谁",
    "你能做什么",
    "你可以做什么",
    "介绍一下你",
    "介绍一下shipvoice",
    "shipvoice是什么",
    "怎么使用",
    "如何使用",
    "使用说明",
)
HIGH_RISK_SPECIFIC_TERMS = (
    "多少",
    "阈值",
    "浓度",
    "氧含量",
    "爆炸下限",
    "报警值",
    "标准编号",
    "标准号",
    "条款",
    "法规",
    "载荷",
    "吨",
    "电压",
    "电流",
    "几伏",
    "几安",
    "距离",
    "几米",
    "多长时间",
)
DOMAIN_GENERAL_TERMS = (
    "安全",
    "作业",
    "船",
    "舱",
    "动火",
    "吊装",
    "试压",
    "有限空间",
    "密闭",
    "监护",
    "审批",
    "检测",
    "通风",
    "应急",
)
FOLLOW_UP_CONTEXT_TERMS = (
    "还有",
    "还要",
    "还需要",
    "继续",
    "补充",
    "刚才",
    "上面",
    "上述",
    "这个",
    "这种",
    "这种情况",
    "那",
    "那怎么办",
    "怎么办",
    "可以吗",
    "需要吗",
    "注意什么",
    "注意事项",
)
IDENTITY_HELP_ANSWER = (
    "我是 ShipVoice 船厂安全实时语音问答助手。"
    "我可以接收文字、上传音频或现场录音，将语音转写成问题，"
    "结合船厂安全知识库和 ShipVoice 模型给出保守的安全建议，并把回答合成为语音播放。"
    "我主要面向动火、有限空间、吊装、管路试压、临时用电、个人防护和应急处置等造船现场场景。"
    "对于危险、越权、离题或提示注入类请求，我会进行安全拦截；"
    "对于缺少证据的高风险具体阈值或标准编号，我不会编造答案。"
)
EVIDENCE_GAP_ANSWER = (
    "当前知识库没有足够依据回答这个高风险具体问题。"
    "我不能凭模型常识给出未经验证的标准编号、阈值、浓度、载荷、电压、电流、距离或许可条件。"
    "建议立即查阅本船厂现场规程、作业票和设备说明，并由现场负责人或安全管理人员确认。"
    "在依据未确认前，应按保守原则暂停相关高风险作业，完成审批、检测、隔离、通风、监护和应急准备。"
)
NO_EVIDENCE_GENERAL_NOTICE = (
    "当前知识库未命中可引用依据。"
    "以下为通用安全建议，不能替代现场制度、作业票或安全负责人确认。"
)
SCOPE_GAP_ANSWER = (
    "我还缺少具体的造船现场作业场景，不能直接给出安全建议。"
    "请补充作业类型、地点和主要风险点，例如动火、有限空间、吊装、管路试压、临时用电或应急处置。"
    "如果现场已经存在人员受伤、气体报警、火情、泄漏或设备失控，请先停止作业并通知现场负责人或安全管理人员。"
)


class PipelineCancelled(RuntimeError):
    pass


class VoiceQAPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or load_config()
        self.runtime_profile_id = "gpu_lora"
        self.runtime_profile_label = "GPU LoRA 主模式"
        self.runtime_profile_kind = "gpu"
        self.require_lora = False
        self.expected_adapter_sha256 = ""
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

    def close(self) -> None:
        for provider in (self.asr, self.llm, self.tts):
            close = getattr(provider, "close", None)
            if callable(close):
                close()

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
        cancel_event: threading.Event | None = None,
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

        def check_cancelled(stage: str) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise PipelineCancelled(f"run cancelled during {stage}")

        mode = (mode or "full").strip().lower()
        if mode not in PUBLIC_RUN_MODES:
            raise ValueError(f"Unsupported run mode: {mode}")
        rag_enabled = mode in {"rag", "full", "streaming"}
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
        check_cancelled("input")

        asr_start = elapsed()
        asr_result = await self._transcribe(question, audio_bytes=audio_bytes, audio_name=audio_name, cancel_event=cancel_event)
        check_cancelled("asr")
        asr_ms = elapsed() - asr_start
        transcript = asr_result.transcript
        await emit("asr", "ASR completed", transcript=transcript, latency_ms=asr_ms)

        corrected, term_hits = self.corrector.correct(transcript)
        if corrected != transcript or term_hits:
            await emit("term", "Domain term correction completed", corrected=corrected, term_hits=term_hits)

        contextual_question = (
            self._contextualize_question(corrected, history)
            if self._should_use_history_context(corrected, history)
            else corrected
        )
        controlled_answer = ""
        controlled_answer_source = ""
        if self._is_identity_help_question(corrected):
            controlled_answer = IDENTITY_HELP_ANSWER
            controlled_answer_source = "identity_help"
        gate_result = self.gate.classify(contextual_question)
        if controlled_answer_source == "identity_help":
            gate_result = GateResult("identity_help", True, "系统身份和使用帮助问题，使用受控产品说明回答")
        await emit(
            "gate",
            "Safety gate completed",
            label=gate_result.label,
            allowed=gate_result.allowed,
            reason=gate_result.reason,
        )

        retrieval_ms = 0
        evidence = []
        if controlled_answer_source:
            await emit("retrieval", "Controlled help answer, retrieval skipped", source=controlled_answer_source)
        elif rag_enabled and gate_result.allowed:
            check_cancelled("retrieval")
            retrieval_start = elapsed()
            evidence = await self.retriever.retrieve(contextual_question)
            check_cancelled("retrieval")
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
        output_guard_rewrites = 0
        high_risk_output = False
        llm_provider_override = ""

        if gate_result.allowed:
            llm_start = elapsed()
            if controlled_answer_source:
                answer = controlled_answer
                llm_ms = 0
                llm_first_token_ms = 0
                llm_provider_override = f"not_called_{controlled_answer_source}"
                await emit(
                    "llm",
                    "LLM skipped because controlled answer was available",
                    chunks=len(self.llm.split_chunks(answer)),
                    latency_ms=0,
                    provider=llm_provider_override,
                    source=controlled_answer_source,
                )
                tts_start = elapsed()
                tts_result = await self._synthesize(answer, cancel_event=cancel_event)
                check_cancelled("tts")
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
            elif not evidence and self._is_high_risk_specific_question(contextual_question):
                answer = EVIDENCE_GAP_ANSWER
                llm_ms = 0
                llm_first_token_ms = 0
                high_risk_output = True
                llm_provider_override = "not_called_evidence_gap"
                await emit(
                    "evidence_policy",
                    "High-risk specific question has no retrieval evidence; concrete answer withheld",
                    policy="no_specific_thresholds_without_evidence",
                )
                await emit(
                    "llm",
                    "LLM skipped because evidence was insufficient for high-risk specifics",
                    chunks=len(self.llm.split_chunks(answer)),
                    latency_ms=0,
                    provider=llm_provider_override,
                )
                tts_start = elapsed()
                tts_result = await self._synthesize(answer, cancel_event=cancel_event)
                check_cancelled("tts")
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
            elif not evidence and gate_result.label == "uncertain" and not self._is_domain_general_question(contextual_question):
                answer = SCOPE_GAP_ANSWER
                llm_ms = 0
                llm_first_token_ms = 0
                llm_provider_override = "not_called_scope_gap"
                await emit(
                    "scope_policy",
                    "Question lacks shipyard safety context and retrieval evidence; asking for concrete work context",
                    policy="ask_for_domain_context_without_llm",
                )
                await emit(
                    "llm",
                    "LLM skipped because the question lacks domain context",
                    chunks=len(self.llm.split_chunks(answer)),
                    latency_ms=0,
                    provider=llm_provider_override,
                )
                tts_start = elapsed()
                tts_result = await self._synthesize(answer, cancel_event=cancel_event)
                check_cancelled("tts")
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
            elif mode == "streaming" and hasattr(self.llm, "stream_answer"):
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
                    cancel_event=cancel_event,
                )
                response_mode = "llm_token_stream_sentence_tts"
            else:
                answer = await self._run_llm(corrected, evidence, gate_result, history, cancel_event=cancel_event)
                check_cancelled("llm")
                answer = self._attach_answer_citations(answer, evidence)
                answer, output_guard_rewrites, high_risk_output = self._guard_complete_answer(
                    answer,
                    question=corrected,
                    evidence=evidence,
                )
                if rag_enabled and not evidence:
                    answer = self._prepend_no_evidence_notice(answer)
                llm_ms = elapsed() - llm_start
                chunks = self.llm.split_chunks(answer)
                llm_first_token_ms = llm_ms
                await emit(
                    "llm",
                    "LLM answer completed",
                    chunks=len(chunks),
                    latency_ms=llm_ms,
                    llm_complete_ms=llm_ms,
                    output_guard_rewrites=output_guard_rewrites,
                    high_risk_output=high_risk_output,
                    provider=self.llm.name,
                )
                if output_guard_rewrites or high_risk_output:
                    await emit(
                        "output_guard",
                        "Complete answer safety-checked before TTS",
                        rewrites=output_guard_rewrites,
                        high_risk_output=high_risk_output,
                    )
                tts_start = elapsed()
                tts_result = await self._synthesize(answer, cancel_event=cancel_event)
                check_cancelled("tts")
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
            tts_result = TTSResult(provider="not_called_safety_gate")
            server_audio_payload_ready_ms = 0
            tts_complete_ms = 0
            tts_first_audio_ms = 0
            await emit(
                "tts",
                "TTS skipped because safety gate blocked the request",
                server_audio_payload_ready_ms=server_audio_payload_ready_ms,
                tts_complete_ms=tts_complete_ms,
                skipped=True,
                provider=tts_result.provider,
            )
        first_audio_ms = server_first_audio_chunk_ready_ms or server_audio_payload_ready_ms
        if not server_audio_stream_complete_ms:
            server_audio_stream_complete_ms = server_audio_payload_ready_ms

        total_ms = elapsed()
        await emit("done", "Pipeline finished", total_ms=total_ms)

        asr_provider = asr_result.provider
        llm_provider = (
            llm_provider_override
            or (getattr(self.llm, "name", self.llm.__class__.__name__) if gate_result.allowed else "not_called")
        )
        tts_provider = getattr(tts_result, "provider", getattr(self.tts, "name", self.tts.__class__.__name__))
        execution_profile = self._execution_profile(asr_provider, llm_provider, tts_provider)
        timing_source = (
            "server_first_audio_chunk_ready"
            if streamed_audio_segments
            else "safety_gate_no_audio"
            if not gate_result.allowed
            else "server_audio_payload_ready"
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
                "runtime_profile": getattr(self, "runtime_profile_id", "gpu_lora"),
                "runtime_profile_label": getattr(self, "runtime_profile_label", "GPU LoRA 主模式"),
                "runtime_profile_kind": getattr(self, "runtime_profile_kind", "gpu"),
                "asr": asr_provider,
                "llm": llm_provider,
                "tts": tts_provider,
                "execution_profile": execution_profile,
                "timing_source": timing_source,
                "timing_note": (
                    "Server-side first audio chunk ready time; browser playback start is recorded by client timing."
                    if streamed_audio_segments
                    else "Safety gate blocked the request before LLM/TTS; no audio payload is produced."
                    if not gate_result.allowed
                    else "Server-side audio payload ready time; browser playback start is recorded by client timing."
                ),
                "response_mode": response_mode,
                "output_guard_rewrites": str(output_guard_rewrites),
                "high_risk_output": str(high_risk_output).lower(),
                **self._provider_observability_status(),
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
        cancel_event: threading.Event | None = None,
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
        high_risk_stream = self._is_high_risk_stream_context(question, evidence)
        output_guard_rewrites = 0
        queued_text_segments: list[str] = []

        async def emit_audio_chunk(payload: dict[str, object]) -> None:
            if on_audio_chunk is None:
                return
            maybe_awaitable = on_audio_chunk(payload)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

        async def queue_spoken_segment(text: str, *, source: str) -> None:
            nonlocal next_seq
            nonlocal output_guard_rewrites
            self._ensure_not_cancelled(cancel_event, "tts_queue")
            segment = text.strip()
            if not segment:
                return
            segment, citation_rewritten = self._strip_unsupported_citation_text(segment, evidence)
            if citation_rewritten:
                output_guard_rewrites += 1
                await emit(
                    "output_guard",
                    "Unsupported model citation removed before TTS",
                    source=source,
                    reason="citation_not_backed_by_retrieval_evidence",
                    replacement_chars=len(segment),
                )
            if not segment:
                return
            guarded_segment, rewritten, reason = self._guard_output_segment(segment)
            if rewritten:
                output_guard_rewrites += 1
                await emit(
                    "output_guard",
                    "Streaming segment rewritten before TTS",
                    source=source,
                    reason=reason,
                    original_chars=len(segment),
                    replacement_chars=len(guarded_segment),
                )
            queued_text_segments.append(guarded_segment)
            await queue.put((next_seq, guarded_segment))
            await emit(
                "tts_queue",
                "Safety-checked segment queued for TTS",
                seq=next_seq,
                chars=len(guarded_segment),
                source=source,
                output_guard_rewritten=rewritten,
            )
            next_seq += 1

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
                self._ensure_not_cancelled(cancel_event, "tts")
                seq, text = item
                segment_start_ms = elapsed()
                if tts_start_ms is None:
                    tts_start_ms = segment_start_ms
                result = await self._synthesize(text, cancel_event=cancel_event)
                self._ensure_not_cancelled(cancel_event, "tts")
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
            if high_risk_stream:
                await emit(
                    "output_guard",
                    "High-risk streaming context detected; safety prefix queued first",
                    prefix_chars=len(STREAM_HIGH_RISK_SAFETY_PREFIX),
                )
                await queue_spoken_segment(STREAM_HIGH_RISK_SAFETY_PREFIX, source="high_risk_safety_prefix")
            if not evidence:
                await emit(
                    "evidence_policy",
                    "No retrieval evidence available; unverified general-advice notice queued",
                    policy="llm_general_advice_without_citations",
                )
                await queue_spoken_segment(NO_EVIDENCE_GENERAL_NOTICE, source="no_evidence_notice")
            stream_kwargs = {"cancel_event": cancel_event} if self._accepts_kwarg(self.llm.stream_answer, "cancel_event") else {}
            async for delta in self.llm.stream_answer(question, evidence, gate, history, **stream_kwargs):
                self._ensure_not_cancelled(cancel_event, "llm_stream")
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
                    await queue_spoken_segment(sentence, source="llm_sentence")
            answer = "".join(answer_parts).strip()
            if not answer:
                raise RuntimeError("LLM streaming returned an empty answer.")
            if high_risk_stream:
                answer = f"{STREAM_HIGH_RISK_SAFETY_PREFIX}\n{answer}"
            cited_answer = self._attach_answer_citations(answer, evidence)
            if not evidence:
                cited_answer = self._prepend_no_evidence_notice(cited_answer)
            if cited_answer != answer:
                suffix = cited_answer[len(answer):] if cited_answer.startswith(answer) else self._format_citation_sentence(evidence)
                buffer = f"{buffer}{suffix}"
                answer = cited_answer
            final_sentence = buffer.strip()
            if final_sentence:
                await queue_spoken_segment(final_sentence, source="llm_final_fragment")
            if high_risk_stream or output_guard_rewrites:
                answer = " ".join(queued_text_segments).strip()
            llm_ms = max(0, elapsed() - llm_start)
            await emit(
                "llm",
                "LLM streaming completed",
                chunks=next_seq,
                latency_ms=llm_ms,
                llm_first_delta_ms=first_delta_ms or 0,
                llm_complete_ms=llm_ms,
                output_guard_rewrites=output_guard_rewrites,
                high_risk_stream=high_risk_stream,
                provider=getattr(self.llm, "name", self.llm.__class__.__name__),
            )
            await queue.put(None)
            await worker_task
        except Exception:
            if cancel_event is not None and cancel_event.is_set():
                await queue.put(None)
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

    async def _transcribe(
        self,
        question: str,
        *,
        audio_bytes: bytes | None,
        audio_name: str,
        cancel_event: threading.Event | None,
    ):
        kwargs = {"audio_bytes": audio_bytes, "audio_name": audio_name}
        if self._accepts_kwarg(self.asr.transcribe, "cancel_event"):
            kwargs["cancel_event"] = cancel_event
        return await self.asr.transcribe(question, **kwargs)

    async def _synthesize(self, text: str, *, cancel_event: threading.Event | None) -> TTSResult:
        kwargs = {"cancel_event": cancel_event} if self._accepts_kwarg(self.tts.synthesize, "cancel_event") else {}
        return await self.tts.synthesize(text, **kwargs)

    async def _run_llm(
        self,
        question: str,
        evidence: list,
        gate: GateResult,
        history: list[dict[str, str]],
        *,
        cancel_event: threading.Event | None,
    ) -> str:
        kwargs = {"cancel_event": cancel_event} if self._accepts_kwarg(self.llm.build_answer, "cancel_event") else {}
        return await asyncio.to_thread(self.llm.build_answer, question, evidence, gate, history, **kwargs)

    @staticmethod
    def _accepts_kwarg(func: Callable[..., object], name: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return False
        return name in signature.parameters

    @staticmethod
    def _ensure_not_cancelled(cancel_event: threading.Event | None, stage: str) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise PipelineCancelled(f"run cancelled during {stage}")

    @staticmethod
    def _pop_stream_sentence(buffer: str, *, force: bool = False) -> tuple[str, str]:
        text = buffer.strip()
        if not text:
            return "", ""
        for match in re.finditer(r"[。！？!?；;]", text):
            end = match.end()
            if end >= STREAM_SENTENCE_MIN_CHARS or force:
                return text[:end].strip(), text[end:].lstrip()
        if force:
            return text, ""
        return "", buffer

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    @classmethod
    def _is_identity_help_question(cls, question: str) -> bool:
        compact = re.sub(r"\s+", "", question.lower())
        return any(term.lower() in compact for term in IDENTITY_HELP_TERMS)

    @classmethod
    def _is_high_risk_specific_question(cls, question: str) -> bool:
        compact = re.sub(r"\s+", "", question)
        if not cls._contains_any(compact, STREAM_HIGH_RISK_TERMS):
            return False
        return cls._contains_any(compact, HIGH_RISK_SPECIFIC_TERMS)

    @classmethod
    def _is_domain_general_question(cls, question: str) -> bool:
        return cls._contains_any(question, DOMAIN_GENERAL_TERMS)

    @classmethod
    def _should_use_history_context(cls, question: str, history: list[dict[str, str]]) -> bool:
        if not history:
            return False
        compact = re.sub(r"\s+", "", question)
        if cls._is_identity_help_question(question):
            return False
        if not cls._contains_any(compact, FOLLOW_UP_CONTEXT_TERMS):
            return False
        recent_user_turns = [
            str(item.get("content", "")).strip()
            for item in history
            if item.get("role") == "user" and str(item.get("content", "")).strip()
        ]
        recent_context = " ".join(recent_user_turns[-2:])
        return cls._is_domain_general_question(recent_context)

    @classmethod
    def _is_high_risk_stream_context(cls, question: str, evidence: list) -> bool:
        evidence_text = " ".join(
            " ".join(
                str(getattr(hit, attr, "") or "")
                for attr in ("title", "text", "risk_level")
            )
            for hit in evidence
        )
        return cls._contains_any(f"{question} {evidence_text}", STREAM_HIGH_RISK_TERMS)

    @classmethod
    def _guard_output_segment(cls, segment: str) -> tuple[str, bool, str]:
        compact = re.sub(r"\s+", "", segment)
        has_risky_action = cls._contains_any(compact, STREAM_UNSAFE_ACTION_TERMS)
        if not has_risky_action:
            return segment, False, ""
        if cls._is_explicitly_safe_risky_sentence(compact):
            return segment, False, ""
        return STREAM_SEGMENT_SAFETY_FALLBACK, True, "unsafe_or_ambiguous_action_before_safety_conditions"

    @classmethod
    def _is_explicitly_safe_risky_sentence(cls, compact: str) -> bool:
        action_positions = [compact.find(term) for term in STREAM_UNSAFE_ACTION_TERMS if term in compact]
        action_positions = [pos for pos in action_positions if pos >= 0]
        first_action = min(action_positions) if action_positions else -1
        if first_action < 0:
            return True
        prefix = compact[:first_action]
        if any(prefix.endswith(term) or term in prefix[-8:] for term in OUTPUT_GUARD_SAFE_PREFIXES):
            return True
        if cls._contains_any(compact[first_action:first_action + 16], OUTPUT_GUARD_CONDITIONAL_TRAPS):
            return False
        has_completion = cls._contains_any(prefix, OUTPUT_GUARD_COMPLETION_QUALIFIERS)
        has_after_gate = any(term in compact for term in ("后方可", "后才能", "确认后", "满足后", "完成后"))
        has_must_before = any(term in prefix for term in ("必须", "应先", "先完成", "先确认"))
        return bool((has_completion and has_after_gate) or has_must_before)

    @classmethod
    def _guard_complete_answer(cls, answer: str, *, question: str, evidence: list) -> tuple[str, int, bool]:
        high_risk = cls._is_high_risk_stream_context(question, evidence)
        parts = [part.strip() for part in re.split(r"(?<=[。！？!?；;])", answer) if part.strip()]
        if not parts:
            parts = [answer.strip()] if answer.strip() else []
        guarded_parts: list[str] = []
        rewrites = 0
        for part in parts:
            guarded, rewritten, _reason = cls._guard_output_segment(part)
            guarded_parts.append(guarded)
            rewrites += int(rewritten)
        guarded_answer = " ".join(guarded_parts).strip() or answer
        if high_risk and STREAM_HIGH_RISK_SAFETY_PREFIX not in guarded_answer:
            guarded_answer = f"{STREAM_HIGH_RISK_SAFETY_PREFIX} {guarded_answer}"
        return guarded_answer, rewrites, high_risk

    @classmethod
    def _guard_stream_segment(cls, segment: str) -> tuple[str, bool, str]:
        return cls._guard_output_segment(segment)

    @classmethod
    def _attach_answer_citations(cls, answer: str, evidence: list) -> str:
        answer, _rewritten = cls._strip_model_citation_text(answer)
        citation_hits = [hit for hit in evidence if getattr(hit, "record_id", "")]
        if not citation_hits:
            return answer
        citation_sentence = cls._format_citation_sentence(citation_hits)
        if citation_sentence in answer:
            return answer
        return f"{answer.rstrip()} {citation_sentence}"

    @staticmethod
    def _format_citation_sentence(evidence: list) -> str:
        citation_hits = [hit for hit in evidence if getattr(hit, "record_id", "")]
        if not citation_hits:
            return ""
        citations = "；".join(f"[{hit.record_id}] {hit.title}" for hit in citation_hits[:2])
        return f"依据：{citations}。"

    @classmethod
    def _strip_model_citation_text(cls, answer: str) -> tuple[str, bool]:
        original = answer
        cleaned = re.sub(
            r"\s*(?:依据|引用依据|参考依据|证据)\s*[:：][^。！？!?]*(?:[。！？!?]|$)",
            "",
            answer,
        )
        cleaned = re.sub(r"\[[A-Za-z]{1,8}\d{2,5}\]", "", cleaned)
        cleaned = re.sub(r"\b[A-Z]{1,8}\d{2,5}\b", "", cleaned)
        cleaned = re.sub(r"\s+([，。；！？!?])", r"\1", cleaned)
        cleaned = re.sub(r"([：:])\s+", r"\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned, cleaned != original.strip()

    @classmethod
    def _strip_unsupported_citation_text(cls, answer: str, evidence: list) -> tuple[str, bool]:
        citation_ids = cls._citation_ids(answer)
        if not citation_ids:
            return answer.strip(), False
        allowed_ids = {str(getattr(hit, "record_id", "") or "") for hit in evidence}
        allowed_ids.discard("")
        if citation_ids.issubset(allowed_ids):
            return answer.strip(), False
        return cls._strip_model_citation_text(answer)

    @staticmethod
    def _citation_ids(text: str) -> set[str]:
        bracketed = set(re.findall(r"\[([A-Za-z]{1,8}\d{2,5})\]", text))
        bare = set(re.findall(r"\b([A-Z]{1,8}\d{2,5})\b", text))
        return bracketed | bare

    @staticmethod
    def _prepend_no_evidence_notice(answer: str) -> str:
        answer = answer.strip()
        if not answer or answer.startswith(NO_EVIDENCE_GENERAL_NOTICE):
            return answer or NO_EVIDENCE_GENERAL_NOTICE
        if answer.startswith(EVIDENCE_GAP_ANSWER) or answer.startswith(SCOPE_GAP_ANSWER):
            return answer
        if answer.startswith(STREAM_HIGH_RISK_SAFETY_PREFIX):
            remainder = answer[len(STREAM_HIGH_RISK_SAFETY_PREFIX):].strip()
            return f"{STREAM_HIGH_RISK_SAFETY_PREFIX} {NO_EVIDENCE_GENERAL_NOTICE} {remainder}".strip()
        return f"{NO_EVIDENCE_GENERAL_NOTICE} {answer}"

    def tts_default_result(self):
        from .models import TTSResult

        return TTSResult(provider=getattr(self.tts, "name", self.tts.__class__.__name__))

    def _execution_profile(self, asr_provider: str, llm_provider: str, tts_provider: str) -> str:
        if llm_provider == "not_called":
            return "real_guarded"
        if asr_provider == "text_input":
            return "real_text"
        return "real_voice"

    def _contextualize_question(self, question: str, history: list[dict[str, str]]) -> str:
        recent_user_turns = [item["content"].strip() for item in history if item.get("role") == "user" and item.get("content")]
        context = recent_user_turns[-2:]
        if not context:
            return question
        return " ".join(context + [question])

    def _provider_observability_status(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for prefix, provider in (("asr", self.asr), ("llm", self.llm), ("tts", self.tts)):
            snapshot_fn = getattr(provider, "status_snapshot", None)
            if not callable(snapshot_fn):
                continue
            snapshot = snapshot_fn()
            for key, value in snapshot.items():
                status[f"{prefix}_{key}"] = str(value).lower() if isinstance(value, bool) else str(value)
        return status
