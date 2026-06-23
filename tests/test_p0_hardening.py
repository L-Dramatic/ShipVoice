from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shipvoice.fastapi_app as fastapi_app_module  # noqa: E402
from shipvoice.config import PipelineConfig  # noqa: E402
from shipvoice.fastapi_app import RunRequest, prepare_run_request, runtime_max_concurrent_runs, runtime_run_timeout_seconds  # noqa: E402
from shipvoice.models import ASRResult, GateResult, TTSResult  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402
from shipvoice.providers import (  # noqa: E402
    HttpJsonASRProvider,
    KeywordSafetyGate,
    OpenAICompatibleLLMProvider,
    TermCorrector,
    TextInputProvider,
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


class FakeLLM:
    name = "fake_llm"

    def __init__(self) -> None:
        self.calls = 0

    def build_answer(self, question, evidence, gate, history) -> str:
        self.calls += 1
        return "safe answer"

    def split_chunks(self, answer: str) -> list[str]:
        return [answer] if answer else []


class FakeTTS:
    name = "fake_tts"

    async def synthesize(self, text: str) -> TTSResult:
        return TTSResult(provider=self.name, audio_base64="UklGRg==", mime_type="audio/wav")


class FakeStreamingLLM(FakeLLM):
    name = "fake_streaming_llm"

    async def stream_answer(self, question, evidence, gate, history):
        yield "第一句先播报。"
        await asyncio.sleep(0.2)
        yield "第二句随后补充。"


class FakeStreamingTTS(FakeTTS):
    name = "fake_streaming_tts"

    async def synthesize(self, text: str) -> TTSResult:
        await asyncio.sleep(0.005)
        return TTSResult(provider=self.name, audio_base64="UklGRg==", mime_type="audio/wav")


class FakeSSEHTTPResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


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
            return result, audio_chunks, events

        result, audio_chunks, events = asyncio.run(run_streaming())

        self.assertEqual(result.provider_status["response_mode"], "llm_token_stream_sentence_tts")
        self.assertEqual(result.metrics.timing_source, "server_first_audio_chunk_ready")
        self.assertGreaterEqual(result.metrics.streamed_audio_segments, 2)
        self.assertGreaterEqual(len(audio_chunks), 2)
        self.assertLess(result.metrics.llm_first_delta_ms, result.metrics.llm_complete_ms)
        self.assertLess(events.index("audio_chunk"), events.index("llm"))
        self.assertLess(result.metrics.server_first_audio_chunk_ready_ms, result.metrics.llm_complete_ms)
        self.assertEqual(result.audio_output.audio_base64, "")
        self.assertEqual(len(result.audio_output.audio_segments), len(audio_chunks))

    def test_openai_compatible_provider_parses_sse_delta_stream(self) -> None:
        provider = OpenAICompatibleLLMProvider(
            base_url="http://llm.invalid/v1",
            model="shipvoice-qwen2.5-7b-lora",
            api_key_env="SHIPVOICE_TEST_API_KEY",
            timeout_s=1,
        )
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
        gate = GateResult(label="domain_safe", allowed=True, reason="ok")

        with patch("shipvoice.providers.urllib.request.urlopen", return_value=FakeSSEHTTPResponse(lines)) as mocked:
            chunks = list(provider._stream_answer_sync("ship safety work", [], gate, []))

        self.assertEqual(chunks, ["第一句", "第二句。"])
        request = mocked.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "shipvoice-qwen2.5-7b-lora")

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

    def test_run_request_accepts_valid_client_request_id(self) -> None:
        prepared = prepare_run_request(
            RunRequest(
                session_id="session-001",
                client_request_id="session-001:req-001",
                question="ship safety",
            )
        )

        self.assertEqual(prepared["client_request_id"], "session-001:req-001")

        with self.assertRaises(HTTPException) as context:
            prepare_run_request(RunRequest(question="ship safety", client_request_id="bad id with spaces"))
        self.assertEqual(context.exception.status_code, 422)

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
