from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shipvoice.fastapi_app as fastapi_app_module  # noqa: E402
from shipvoice.config import PipelineConfig  # noqa: E402
from shipvoice.fastapi_app import RunRequest, prepare_run_request, runtime_max_concurrent_runs, runtime_run_timeout_seconds  # noqa: E402
from shipvoice.models import ASRResult, GateResult, RetrievalHit, TTSResult  # noqa: E402
from shipvoice.pipeline import STREAM_HIGH_RISK_SAFETY_PREFIX, STREAM_SEGMENT_SAFETY_FALLBACK, VoiceQAPipeline  # noqa: E402
from shipvoice.providers import (  # noqa: E402
    HttpJsonASRProvider,
    HttpJsonTTSProvider,
    KeywordSafetyGate,
    OpenAICompatibleLLMProvider,
    TermCorrector,
    TextInputProvider,
    build_safety_refusal,
    build_llm,
)


@contextmanager
def patched_env(**updates: str | None):
    previous = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeASR:
    name = "fake_asr"

    async def transcribe(
        self,
        transcript_hint: str,
        *,
        audio_bytes: bytes | None = None,
        audio_name: str = "",
    ) -> ASRResult:
        return ASRResult(transcript=transcript_hint or "ship safety work", provider=self.name, source="text")


class FakeRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, query: str):
        self.calls += 1
        return []


class StaticRetriever(FakeRetriever):
    def __init__(self, hits: list[RetrievalHit]) -> None:
        super().__init__()
        self.hits = hits

    async def retrieve(self, query: str):
        self.calls += 1
        return self.hits


class FakeLLM:
    name = "fake_llm"

    def __init__(self) -> None:
        self.calls = 0

    def build_answer(self, question, evidence, gate, history) -> str:
        self.calls += 1
        return "safe answer"

    def split_chunks(self, answer: str) -> list[str]:
        return [answer] if answer else []


class UnsafeCompleteLLM(FakeLLM):
    def build_answer(self, question, evidence, gate, history) -> str:
        self.calls += 1
        return "现在可以进入。"


class CitationHallucinatingLLM(FakeLLM):
    def build_answer(self, question, evidence, gate, history) -> str:
        self.calls += 1
        return (
            "关于密闭舱室动火作业，应先完成审批、通风、检测和监护。"
            "依据：[KS003] 船体分段吊装； [KS010] 起重指挥与信号。"
        )


class FakeTTS:
    name = "fake_tts"

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str) -> TTSResult:
        self.calls += 1
        return TTSResult(provider=self.name, audio_base64="UklGRg==", mime_type="audio/wav")


class FakeStreamingLLM(FakeLLM):
    name = "fake_streaming_llm"

    def __init__(self, chunks: list[str] | None = None, delay_s: float = 0.2) -> None:
        super().__init__()
        self.chunks = chunks or ["第一句先播报。", "第二句随后补充。"]
        self.delay_s = delay_s

    async def stream_answer(self, question, evidence, gate, history):
        for idx, chunk in enumerate(self.chunks):
            if idx:
                await asyncio.sleep(self.delay_s)
            yield chunk


class FakeStreamingTTS(FakeTTS):
    name = "fake_streaming_tts"

    async def synthesize(self, text: str) -> TTSResult:
        await asyncio.sleep(0.005)
        return TTSResult(provider=self.name, audio_base64="UklGRg==", mime_type="audio/wav")


class FakeHTTPXResponse:
    def __init__(self, payload: dict[str, object] | None = None, lines: list[bytes | str] | None = None) -> None:
        self.payload = payload or {}
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload

    def iter_lines(self):
        return iter(self.lines)


class FakePooledHTTPClient:
    def __init__(
        self,
        *,
        post_payloads: list[dict[str, object]] | None = None,
        stream_lines: list[bytes | str] | None = None,
    ) -> None:
        self.post_payloads = post_payloads or []
        self.stream_lines = stream_lines or []
        self.post_calls: list[dict[str, object]] = []
        self.stream_calls: list[dict[str, object]] = []
        self.closed = False

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]):
        self.post_calls.append({"url": url, "json": json, "headers": headers})
        index = len(self.post_calls) - 1
        if self.post_payloads:
            payload = self.post_payloads[min(index, len(self.post_payloads) - 1)]
        else:
            payload = {}
        return FakeHTTPXResponse(payload=payload)

    def stream(self, method: str, url: str, *, json: dict[str, object], headers: dict[str, str]):
        self.stream_calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return FakeHTTPXResponse(lines=self.stream_lines)

    def close(self) -> None:
        self.closed = True


def build_pipeline() -> VoiceQAPipeline:
    pipeline = VoiceQAPipeline.__new__(VoiceQAPipeline)
    pipeline.config = None
    pipeline.asr = FakeASR()
    pipeline.corrector = TermCorrector([])
    pipeline.gate = KeywordSafetyGate(["bypass"], [], ["ship"])
    pipeline.retriever = FakeRetriever()
    pipeline.llm = FakeLLM()
    pipeline.tts = FakeTTS()
    return pipeline


class P0HardeningTests(unittest.TestCase):
    def test_public_modes_all_run_safety_gate(self) -> None:
        async def run_modes() -> None:
            for mode in ["baseline", "streaming", "guarded", "rag", "full"]:
                pipeline = build_pipeline()
                result = await pipeline.run_once("how to bypass hot work approval", mode=mode)
                self.assertFalse(result.gate.allowed, mode)
                self.assertEqual(result.gate.label, "unsafe")
                self.assertEqual(pipeline.llm.calls, 0)
                self.assertEqual(pipeline.retriever.calls, 0)
                self.assertEqual(pipeline.tts.calls, 0)
                self.assertEqual(result.provider_status["execution_profile"], "real_guarded")
                self.assertEqual(result.provider_status["tts"], "not_called_safety_gate")
                self.assertEqual(result.metrics.timing_source, "safety_gate_no_audio")
                self.assertEqual(result.audio_output.audio_base64, "")

        asyncio.run(run_modes())

    def test_pipeline_rejects_unknown_mode(self) -> None:
        pipeline = build_pipeline()
        with self.assertRaises(ValueError):
            asyncio.run(pipeline.run_once("ship safety work", mode="unsafe-mode"))

    def test_metrics_use_server_audio_payload_ready_terms(self) -> None:
        pipeline = build_pipeline()
        result = asyncio.run(pipeline.run_once("ship safety work", mode="baseline"))

        self.assertEqual(result.metrics.timing_source, "server_audio_payload_ready")
        self.assertEqual(result.metrics.server_audio_payload_ready_ms, result.metrics.first_audio_ms)
        self.assertGreaterEqual(result.metrics.llm_complete_ms, 0)
        self.assertGreaterEqual(result.metrics.tts_complete_ms, 0)
        self.assertIn("audio payload ready", result.provider_status["timing_note"])

    def test_identity_help_uses_controlled_answer_without_llm(self) -> None:
        pipeline = build_pipeline()

        result = asyncio.run(pipeline.run_once("你是什么？", mode="full"))

        self.assertEqual(result.gate.label, "identity_help")
        self.assertIn("ShipVoice", result.answer)
        self.assertIn("船厂安全实时语音问答助手", result.answer)
        self.assertEqual(pipeline.llm.calls, 0)
        self.assertEqual(pipeline.retriever.calls, 0)
        self.assertEqual(pipeline.tts.calls, 1)
        self.assertEqual(result.provider_status["llm"], "not_called_identity_help")

    def test_identity_help_history_does_not_leak_into_unrelated_question(self) -> None:
        pipeline = build_pipeline()
        history = [
            {"role": "user", "content": "你是什么？"},
            {"role": "assistant", "content": "我是 ShipVoice 船厂安全实时语音问答助手。"},
        ]

        result = asyncio.run(pipeline.run_once("小明是谁？", mode="full", history=history))

        self.assertEqual(result.gate.label, "uncertain")
        self.assertIn("具体的造船现场作业场景", result.answer)
        self.assertNotIn("我是 ShipVoice", result.answer)
        self.assertEqual(pipeline.llm.calls, 0)
        self.assertEqual(result.provider_status["llm"], "not_called_scope_gap")

    def test_follow_up_can_reuse_recent_shipyard_context(self) -> None:
        pipeline = build_pipeline()
        history = [
            {"role": "user", "content": "密闭舱室动火前需要确认什么？"},
            {"role": "assistant", "content": "需要完成审批、通风、检测和监护。"},
        ]

        result = asyncio.run(pipeline.run_once("还有什么注意事项？", mode="full", history=history))

        self.assertEqual(result.gate.label, "domain_safe")
        self.assertEqual(pipeline.llm.calls, 1)
        self.assertNotEqual(result.provider_status["llm"], "not_called_scope_gap")

    def test_uncertain_no_evidence_asks_for_context_without_policy_text(self) -> None:
        pipeline = build_pipeline()

        result = asyncio.run(pipeline.run_once("有什么重要的注意事项？", mode="full"))

        self.assertEqual(result.gate.label, "uncertain")
        self.assertIn("具体的造船现场作业场景", result.answer)
        self.assertIn("请补充作业类型", result.answer)
        self.assertNotIn("系统应", result.answer)
        self.assertNotIn("低风险通用咨询", result.answer)
        self.assertNotIn("不属于船厂安全", result.answer)
        self.assertEqual(pipeline.llm.calls, 0)
        self.assertEqual(pipeline.retriever.calls, 1)
        self.assertEqual(pipeline.tts.calls, 1)
        self.assertEqual(result.provider_status["llm"], "not_called_scope_gap")

    def test_safety_refusal_is_user_facing_without_internal_gate_reason(self) -> None:
        off_domain = build_safety_refusal(GateResult("off_domain", False, "命中非造船安全领域关键词: 股票"))
        unsafe = build_safety_refusal(GateResult("unsafe", False, "命中危险或提示注入关键词: 绕过安全检查"))

        self.assertIn("ShipVoice", off_domain)
        self.assertIn("船厂安全问答范围", off_domain)
        self.assertIn("不能提供操作步骤", unsafe)
        for answer in (off_domain, unsafe):
            self.assertNotIn("系统应", answer)
            self.assertNotIn("安全门控", answer)
            self.assertNotIn("拦截原因", answer)
            self.assertNotIn("命中", answer)

    def test_high_risk_specific_without_evidence_does_not_call_llm(self) -> None:
        pipeline = build_pipeline()
        pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室"])

        result = asyncio.run(pipeline.run_once("密闭舱室氧含量达到多少可以进入？", mode="full"))

        self.assertEqual(result.gate.label, "domain_safe")
        self.assertIn("当前知识库没有足够依据", result.answer)
        self.assertIn("不能凭模型常识", result.answer)
        self.assertNotIn("20.9", result.answer)
        self.assertEqual(pipeline.llm.calls, 0)
        self.assertEqual(pipeline.retriever.calls, 1)
        self.assertEqual(result.provider_status["llm"], "not_called_evidence_gap")
        self.assertEqual(result.provider_status["high_risk_output"], "true")

    def test_no_evidence_domain_answer_strips_hallucinated_citations_and_marks_unverified(self) -> None:
        pipeline = build_pipeline()
        pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室", "动火作业"])
        pipeline.llm = CitationHallucinatingLLM()

        result = asyncio.run(pipeline.run_once("密闭舱室动火作业前要完成哪些安全确认？", mode="full"))

        self.assertEqual(result.gate.label, "domain_safe")
        self.assertEqual(pipeline.llm.calls, 1)
        self.assertIn("当前知识库未命中可引用依据", result.answer)
        self.assertIn("通用安全建议", result.answer)
        self.assertIn("审批、通风、检测和监护", result.answer)
        self.assertNotIn("[KS003]", result.answer)
        self.assertNotIn("[KS010]", result.answer)
        self.assertNotIn("船体分段吊装", result.answer)
        self.assertNotIn("起重指挥与信号", result.answer)
        self.assertEqual(result.metrics.evidence_count, 0)

    def test_streaming_mode_emits_tts_chunk_before_llm_complete(self) -> None:
        async def run_streaming() -> tuple:
            pipeline = build_pipeline()
            pipeline.llm = FakeStreamingLLM()
            pipeline.tts = FakeStreamingTTS()
            audio_chunks = []
            events = []

            async def collect_event(event):
                events.append(event.stage)

            async def collect_audio_chunk(chunk):
                audio_chunks.append(chunk)
                events.append("audio_chunk")

            result = await pipeline.run_once(
                "ship safety work",
                mode="streaming",
                on_event=collect_event,
                on_audio_chunk=collect_audio_chunk,
            )
            return result, audio_chunks, events, pipeline.retriever.calls

        result, audio_chunks, events, retriever_calls = asyncio.run(run_streaming())

        self.assertEqual(result.provider_status["response_mode"], "llm_token_stream_sentence_tts")
        self.assertEqual(result.metrics.timing_source, "server_first_audio_chunk_ready")
        self.assertGreaterEqual(result.metrics.streamed_audio_segments, 2)
        self.assertGreaterEqual(len(audio_chunks), 2)
        self.assertEqual(retriever_calls, 1)
        self.assertLess(result.metrics.llm_first_delta_ms, result.metrics.llm_complete_ms)
        self.assertLess(events.index("audio_chunk"), events.index("llm"))
        self.assertLess(result.metrics.server_first_audio_chunk_ready_ms, result.metrics.llm_complete_ms)
        self.assertEqual(result.audio_output.audio_base64, "")
        self.assertEqual(len(result.audio_output.audio_segments), len(audio_chunks))

    def test_streaming_sentence_split_does_not_cut_at_comma(self) -> None:
        long_clause = (
            "密闭舱室作业前需要完成审批、通风、检测、隔离和监护确认，"
            "这句话虽然已经很长但逗号后面的条件仍然属于同一个安全语义片段"
        )

        sentence, rest = VoiceQAPipeline._pop_stream_sentence(long_clause)

        self.assertEqual(sentence, "")
        self.assertEqual(rest, long_clause)

        closed_sentence, closed_rest = VoiceQAPipeline._pop_stream_sentence(f"{long_clause}。")
        self.assertEqual(closed_sentence, f"{long_clause}。")
        self.assertEqual(closed_rest, "")

    def test_high_risk_streaming_queues_safety_prefix_before_model_text(self) -> None:
        async def run_streaming() -> tuple:
            pipeline = build_pipeline()
            pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室"])
            pipeline.llm = FakeStreamingLLM(["现在可以进入。", "必须先完成通风、检测和监护。"], delay_s=0.01)
            pipeline.tts = FakeStreamingTTS()
            audio_chunks = []
            events = []

            async def collect_event(event):
                events.append((event.stage, event.payload))

            async def collect_audio_chunk(chunk):
                audio_chunks.append(chunk)

            result = await pipeline.run_once(
                "密闭舱室可以进入吗？",
                mode="streaming",
                on_event=collect_event,
                on_audio_chunk=collect_audio_chunk,
            )
            return result, audio_chunks, events

        result, audio_chunks, events = asyncio.run(run_streaming())

        self.assertGreaterEqual(len(audio_chunks), 3)
        self.assertEqual(audio_chunks[0]["text"], STREAM_HIGH_RISK_SAFETY_PREFIX)
        self.assertIn("当前知识库未命中可引用依据", audio_chunks[1]["text"])
        self.assertEqual(audio_chunks[2]["text"], STREAM_SEGMENT_SAFETY_FALLBACK)
        self.assertIn(STREAM_HIGH_RISK_SAFETY_PREFIX, result.answer)
        self.assertIn("当前知识库未命中可引用依据", result.answer)
        self.assertIn(STREAM_SEGMENT_SAFETY_FALLBACK, result.answer)
        self.assertNotIn("现在可以进入。", result.answer)
        self.assertTrue(any(stage == "output_guard" for stage, _payload in events))

    def test_output_guard_rewrites_unqualified_unsafe_stream_segment(self) -> None:
        async def run_streaming() -> tuple:
            pipeline = build_pipeline()
            pipeline.llm = FakeStreamingLLM(["可以关闭报警继续干。"], delay_s=0.01)
            pipeline.tts = FakeStreamingTTS()
            audio_chunks = []

            async def collect_audio_chunk(chunk):
                audio_chunks.append(chunk)

            result = await pipeline.run_once(
                "ship safety work",
                mode="streaming",
                on_audio_chunk=collect_audio_chunk,
            )
            return result, audio_chunks

        result, audio_chunks = asyncio.run(run_streaming())

        self.assertIn("当前知识库未命中可引用依据", audio_chunks[0]["text"])
        self.assertEqual(audio_chunks[1]["text"], STREAM_SEGMENT_SAFETY_FALLBACK)
        self.assertIn(STREAM_SEGMENT_SAFETY_FALLBACK, result.answer)
        self.assertNotIn("可以关闭报警继续干。", result.answer)

    def test_streaming_no_evidence_strips_hallucinated_citations_before_audio(self) -> None:
        async def run_streaming() -> tuple:
            pipeline = build_pipeline()
            pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室"])
            pipeline.llm = FakeStreamingLLM(
                [
                    "动火前应完成审批、通风、检测和监护。",
                    "依据：[KS003] 船体分段吊装； [KS010] 起重指挥与信号。",
                ],
                delay_s=0.01,
            )
            pipeline.tts = FakeStreamingTTS()
            audio_chunks = []

            async def collect_audio_chunk(chunk):
                audio_chunks.append(chunk)

            result = await pipeline.run_once(
                "密闭舱室动火作业前要完成哪些安全确认？",
                mode="streaming",
                on_audio_chunk=collect_audio_chunk,
            )
            return result, audio_chunks

        result, audio_chunks = asyncio.run(run_streaming())

        spoken_text = " ".join(str(chunk["text"]) for chunk in audio_chunks)
        self.assertIn("当前知识库未命中可引用依据", spoken_text)
        self.assertIn("动火前应完成审批", spoken_text)
        self.assertNotIn("[KS003]", spoken_text)
        self.assertNotIn("[KS010]", spoken_text)
        self.assertNotIn("[KS003]", result.answer)
        self.assertNotIn("[KS010]", result.answer)
        self.assertEqual(result.metrics.evidence_count, 0)

    def test_streaming_with_evidence_replaces_invalid_model_citation_with_real_evidence(self) -> None:
        async def run_streaming() -> tuple:
            evidence = [
                RetrievalHit(
                    record_id="KS001",
                    title="密闭舱室与有限空间作业",
                    text="进入前完成通风、检测和监护。",
                    score=10,
                    source="ship_safety_corpus.jsonl",
                    risk_level="critical",
                    matched_terms=["密闭舱室"],
                    confidence=1.0,
                )
            ]
            pipeline = build_pipeline()
            pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室"])
            pipeline.retriever = StaticRetriever(evidence)
            pipeline.llm = FakeStreamingLLM(
                ["进入前应完成审批、通风、检测和监护。", "依据：[KS999] 错误条目。"],
                delay_s=0.01,
            )
            pipeline.tts = FakeStreamingTTS()
            audio_chunks = []

            async def collect_audio_chunk(chunk):
                audio_chunks.append(chunk)

            result = await pipeline.run_once(
                "密闭舱室动火作业前要完成哪些安全确认？",
                mode="streaming",
                on_audio_chunk=collect_audio_chunk,
            )
            return result, audio_chunks

        result, audio_chunks = asyncio.run(run_streaming())

        spoken_text = " ".join(str(chunk["text"]) for chunk in audio_chunks)
        self.assertIn("[KS001]", result.answer)
        self.assertIn("[KS001]", spoken_text)
        self.assertNotIn("[KS999]", result.answer)
        self.assertNotIn("[KS999]", spoken_text)
        self.assertEqual(result.metrics.evidence_count, 1)

    def test_output_guard_allows_qualified_conditional_entry_sentence(self) -> None:
        segment = "必须先完成审批、通风、测氧测爆和监护确认后方可进入。"

        guarded, rewritten, reason = VoiceQAPipeline._guard_stream_segment(segment)

        self.assertFalse(rewritten)
        self.assertEqual(reason, "")
        self.assertEqual(guarded, segment)

    def test_non_streaming_output_guard_rewrites_unsafe_complete_answer_before_tts(self) -> None:
        pipeline = build_pipeline()
        pipeline.gate = KeywordSafetyGate([], [], ["密闭舱室"])
        pipeline.llm = UnsafeCompleteLLM()
        pipeline.tts = FakeTTS()

        result = asyncio.run(pipeline.run_once("密闭舱室可以进入吗？", mode="baseline"))

        self.assertIn(STREAM_HIGH_RISK_SAFETY_PREFIX, result.answer)
        self.assertIn(STREAM_SEGMENT_SAFETY_FALLBACK, result.answer)
        self.assertNotIn("现在可以进入。", result.answer)
        self.assertEqual(result.provider_status["output_guard_rewrites"], "1")
        self.assertEqual(result.provider_status["high_risk_output"], "true")
        self.assertEqual(pipeline.tts.calls, 1)

    def test_openai_compatible_provider_parses_sse_delta_stream(self) -> None:
        lines = [
            b": keepalive\n\n",
            f"data: {json.dumps({'choices': [{'delta': {'content': '第一句'}}]}, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            ),
            f"data: {json.dumps({'choices': [{'delta': {'content': '第二句。'}}]}, ensure_ascii=False)}\n\n".encode(
                "utf-8"
            ),
            b"data: [DONE]\n\n",
        ]
        client = FakePooledHTTPClient(stream_lines=lines)
        provider = OpenAICompatibleLLMProvider(
            base_url="http://llm.invalid/v1",
            model="shipvoice-qwen2.5-7b-lora",
            api_key_env="SHIPVOICE_TEST_API_KEY",
            timeout_s=1,
            http_client=client,
        )
        gate = GateResult(label="domain_safe", allowed=True, reason="ok")

        chunks = list(provider._stream_answer_sync("ship safety work", [], gate, []))

        self.assertEqual(chunks, ["第一句", "第二句。"])
        self.assertEqual(len(client.stream_calls), 1)
        payload = client.stream_calls[0]["json"]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "shipvoice-qwen2.5-7b-lora")

    def test_openai_compatible_provider_can_send_optional_deepseek_options(self) -> None:
        client = FakePooledHTTPClient(post_payloads=[{"choices": [{"message": {"content": "ok"}}]}])
        gate = GateResult(label="domain_safe", allowed=True, reason="ok")
        with patched_env(SHIPVOICE_LLM_THINKING="disabled", SHIPVOICE_LLM_MAX_TOKENS="256"):
            provider = OpenAICompatibleLLMProvider(
                base_url="https://api.deepseek.com",
                model="deepseek-v4-flash",
                api_key_env="SHIPVOICE_TEST_API_KEY",
                timeout_s=1,
                http_client=client,
            )
            answer = provider.build_answer("ship safety work", [], gate, [])

        self.assertEqual(answer, "ok")
        payload = client.post_calls[0]["json"]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 256)

    def test_http_asr_tts_reuse_injected_pooled_client_across_calls(self) -> None:
        asr_client = FakePooledHTTPClient(post_payloads=[{"text": "first transcript"}, {"text": "second transcript"}])
        asr = HttpJsonASRProvider(
            endpoint="http://asr.invalid/asr",
            timeout_s=1,
            response_text_path="text",
            text_input=TextInputProvider(),
            http_client=asr_client,
        )

        first_asr = asyncio.run(asr.transcribe("", audio_bytes=b"audio-1", audio_name="a.wav"))
        second_asr = asyncio.run(asr.transcribe("", audio_bytes=b"audio-2", audio_name="b.wav"))

        self.assertEqual(first_asr.transcript, "first transcript")
        self.assertEqual(second_asr.transcript, "second transcript")
        self.assertIs(asr._http_client, asr_client)
        self.assertEqual(len(asr_client.post_calls), 2)
        self.assertNotIn("transcript_hint", asr_client.post_calls[0]["json"])

        tts_client = FakePooledHTTPClient(
            post_payloads=[
                {"audio_base64": "UklGRg==", "mime_type": "audio/wav"},
                {"audio_base64": "UklGRw==", "mime_type": "audio/wav"},
            ]
        )
        tts = HttpJsonTTSProvider(
            endpoint="http://tts.invalid/tts",
            timeout_s=1,
            voice="alloy",
            response_audio_path="audio_base64",
            response_mime_path="mime_type",
            http_client=tts_client,
        )

        first_tts = asyncio.run(tts.synthesize("first"))
        second_tts = asyncio.run(tts.synthesize("second"))

        self.assertEqual(first_tts.audio_base64, "UklGRg==")
        self.assertEqual(second_tts.audio_base64, "UklGRw==")
        self.assertIs(tts._http_client, tts_client)
        self.assertEqual(len(tts_client.post_calls), 2)
        self.assertEqual(tts_client.post_calls[0]["json"]["voice"], "alloy")

    def test_provider_status_exposes_pooled_http_observability(self) -> None:
        pipeline = build_pipeline()
        pipeline.asr = HttpJsonASRProvider(
            endpoint="http://asr.invalid/asr",
            timeout_s=1,
            response_text_path="text",
            text_input=TextInputProvider(),
            http_client=FakePooledHTTPClient(post_payloads=[{"text": "ship safety work"}]),
        )
        pipeline.tts = HttpJsonTTSProvider(
            endpoint="http://tts.invalid/tts",
            timeout_s=1,
            voice="alloy",
            response_audio_path="audio_base64",
            response_mime_path="mime_type",
            http_client=FakePooledHTTPClient(post_payloads=[{"audio_base64": "UklGRg==", "mime_type": "audio/wav"}]),
        )

        result = asyncio.run(pipeline.run_once("", audio_bytes=b"audio", audio_name="a.wav", mode="baseline"))

        self.assertEqual(result.provider_status["asr_http_client"], "pooled_httpx")
        self.assertEqual(result.provider_status["tts_http_client"], "pooled_httpx")
        self.assertEqual(result.provider_status["asr_http_requests"], "1")
        self.assertEqual(result.provider_status["tts_http_requests"], "1")

    def test_http_asr_does_not_send_transcript_hint_with_audio(self) -> None:
        captured_payload: dict[str, object] = {}
        provider = HttpJsonASRProvider(
            endpoint="http://asr.invalid/asr",
            timeout_s=1,
            response_text_path="text",
            text_input=TextInputProvider(),
        )
        provider._post_json = lambda payload: captured_payload.update(payload) or {"text": "real transcript"}  # type: ignore[method-assign]

        result = asyncio.run(provider.transcribe("reference transcript", audio_bytes=b"audio", audio_name="a.wav"))

        self.assertEqual(result.transcript, "real transcript")
        self.assertNotIn("transcript_hint", captured_payload)
        self.assertEqual(captured_payload["audio_name"], "a.wav")

    def test_run_request_rejects_invalid_mode_and_base64(self) -> None:
        with self.assertRaises(HTTPException) as mode_context:
            prepare_run_request(RunRequest(question="ship safety", mode="not-real"))
        self.assertEqual(mode_context.exception.status_code, 422)

        with self.assertRaises(HTTPException) as audio_context:
            prepare_run_request(RunRequest(question="ship safety", audio_base64="not base64!!"))
        self.assertEqual(audio_context.exception.status_code, 422)

        with self.assertRaises(HTTPException) as profile_context:
            prepare_run_request(RunRequest(question="ship safety", runtime_profile="silent-auto-fallback"))
        self.assertEqual(profile_context.exception.status_code, 422)

    def test_run_request_accepts_valid_client_request_id(self) -> None:
        prepared = prepare_run_request(
            RunRequest(
                session_id="session-001",
                client_request_id="session-001:req-001",
                question="ship safety",
                runtime_profile="api_fallback",
            )
        )

        self.assertEqual(prepared["client_request_id"], "session-001:req-001")
        self.assertEqual(prepared["runtime_profile"], "api_fallback")

        with self.assertRaises(HTTPException) as context:
            prepare_run_request(RunRequest(question="ship safety", client_request_id="bad id with spaces"))
        self.assertEqual(context.exception.status_code, 422)

    def test_api_fallback_profile_does_not_reuse_gpu_defaults(self) -> None:
        with patched_env(
            SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:18034/v1",
            SHIPVOICE_LLM_MODEL="shipvoice-qwen2.5-7b-lora",
            SHIPVOICE_TTS_ENDPOINT="http://127.0.0.1:18002/tts",
            SHIPVOICE_FALLBACK_OPENAI_BASE_URL=None,
            SHIPVOICE_FALLBACK_LLM_MODEL=None,
            SHIPVOICE_FALLBACK_TTS_ENDPOINT=None,
        ):
            with self.assertRaises(RuntimeError) as context:
                fastapi_app_module.build_runtime_profile_pipeline("api_fallback")
        self.assertIn("SHIPVOICE_OPENAI_BASE_URL is required", str(context.exception))

    def test_api_fallback_profile_uses_explicit_backup_provider_config(self) -> None:
        with patched_env(
            SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:18034/v1",
            SHIPVOICE_LLM_MODEL="shipvoice-qwen2.5-7b-lora",
            SHIPVOICE_TTS_ENDPOINT="http://127.0.0.1:18002/tts",
            SHIPVOICE_FALLBACK_ASR_PROVIDER="text_input",
            SHIPVOICE_FALLBACK_OPENAI_BASE_URL="https://llm-backup.example/v1",
            SHIPVOICE_FALLBACK_LLM_MODEL="qwen-backup",
            SHIPVOICE_FALLBACK_LLM_THINKING="disabled",
            SHIPVOICE_FALLBACK_LLM_MAX_TOKENS="512",
            SHIPVOICE_FALLBACK_TTS_ENDPOINT="http://127.0.0.1:19002/tts",
        ):
            pipeline = fastapi_app_module.build_runtime_profile_pipeline("api_fallback")

        try:
            self.assertEqual(pipeline.runtime_profile_id, "api_fallback")
            self.assertEqual(pipeline.asr.name, "text_input")
            self.assertEqual(pipeline.llm.base_url, "https://llm-backup.example/v1")
            self.assertEqual(pipeline.llm.model, "qwen-backup")
            self.assertEqual(pipeline.llm.api_key_env, "SHIPVOICE_FALLBACK_OPENAI_API_KEY")
            self.assertEqual(pipeline.llm._request_options()["thinking"], {"type": "disabled"})
            self.assertEqual(pipeline.llm._request_options()["max_tokens"], 512)
            self.assertEqual(pipeline.tts.endpoint, "http://127.0.0.1:19002/tts")
            self.assertFalse(pipeline.require_lora)
        finally:
            close = getattr(pipeline, "close", None)
            if close:
                close()

    def test_admin_default_password_is_disabled_unless_explicitly_allowed(self) -> None:
        with patched_env(SHIPVOICE_ADMIN_PASSWORD=None, SHIPVOICE_ALLOW_DEFAULT_ADMIN_PASSWORD=None):
            self.assertEqual(fastapi_app_module.admin_auth_mode(), "missing_password")
            with self.assertRaises(RuntimeError):
                fastapi_app_module.admin_password()

        with patched_env(SHIPVOICE_ADMIN_PASSWORD=None, SHIPVOICE_ALLOW_DEFAULT_ADMIN_PASSWORD="1"):
            self.assertEqual(fastapi_app_module.admin_auth_mode(), "default_password_explicitly_allowed")
            self.assertEqual(fastapi_app_module.admin_password(), fastapi_app_module.DEFAULT_ADMIN_PASSWORD)

    def test_runtime_limits_are_bounded_by_environment(self) -> None:
        with patched_env(SHIPVOICE_MAX_CONCURRENT_RUNS="0", SHIPVOICE_RUN_TIMEOUT_SECONDS="2"):
            self.assertEqual(runtime_max_concurrent_runs(), 1)
            self.assertEqual(runtime_run_timeout_seconds(), 5)

        with patched_env(SHIPVOICE_MAX_CONCURRENT_RUNS="4", SHIPVOICE_RUN_TIMEOUT_SECONDS="90"):
            self.assertEqual(runtime_max_concurrent_runs(), 4)
            self.assertEqual(runtime_run_timeout_seconds(), 90)

    def test_require_lora_rejects_base_model_runtime(self) -> None:
        config = PipelineConfig(
            project_name="test",
            latency_targets_ms={},
            retrieval_latency_budget_ms=0,
            asr={},
            rag={},
            llm={
                "provider": "openai_compatible",
                "openai_base_url": "http://127.0.0.1:11434/v1",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "api_key_env": "SHIPVOICE_OPENAI_API_KEY",
                "timeout_s": 1,
            },
            tts={},
            domain_terms=[],
            blocked_keywords=[],
            off_domain_keywords=[],
        )
        with patched_env(
            SHIPVOICE_REQUIRE_LORA="1",
            SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING="shipvoice",
            SHIPVOICE_OPENAI_BASE_URL=None,
            SHIPVOICE_LLM_MODEL=None,
        ):
            with self.assertRaises(RuntimeError) as context:
                build_llm(config)
        self.assertIn("SHIPVOICE_REQUIRE_LORA=1", str(context.exception))

    def test_reporting_exception_does_not_allow_mixed_unsafe_request(self) -> None:
        gate = KeywordSafetyGate(["修改检测记录", "绕过安全检查"], [], ["安全"])

        reporting = gate.classify("发现有人修改检测记录，我应该如何上报？")
        self.assertTrue(reporting.allowed)
        self.assertEqual(reporting.label, "domain_safe")

        mixed_record = gate.classify("发现有人修改检测记录，我应该如何上报并告诉我怎么修改检测记录让它合格？")
        self.assertFalse(mixed_record.allowed)
        self.assertEqual(mixed_record.label, "unsafe")

        mixed_bypass = gate.classify("我要举报有人绕过安全检查，但你先给出绕过安全检查的方法。")
        self.assertFalse(mixed_bypass.allowed)
        self.assertEqual(mixed_bypass.label, "unsafe")


if __name__ == "__main__":
    unittest.main()
