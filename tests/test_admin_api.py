from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402
import shipvoice.fastapi_app as fastapi_app_module  # noqa: E402
from shipvoice.fastapi_app import create_app  # noqa: E402
from shipvoice.models import GateResult, PipelineResult, RunMetrics, TTSResult  # noqa: E402
from shipvoice.pipeline import PipelineCancelled  # noqa: E402


@contextmanager
def replace_attr(target: object, name: str, value: object):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield value
    finally:
        setattr(target, name, original)


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


class CallRecorder:
    def __init__(self, *, return_value: object = None, side_effect: Exception | None = None) -> None:
        self.return_value = return_value
        self.side_effect = side_effect
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value

    @property
    def call_count(self) -> int:
        return len(self.calls)


class MinimalStore:
    def __init__(self) -> None:
        self.records: list[object] = []

    def insert_audit(self, record: object) -> None:
        self.records.append(record)


class SlowPipeline:
    def __init__(self) -> None:
        self.calls = 0

    async def run_once(self, question: str, **kwargs: object) -> PipelineResult:
        await asyncio.sleep(0.2)
        self.calls += 1
        metrics = RunMetrics(
            question_id="manual",
            mode=str(kwargs.get("mode", "full")),
            category="manual",
            gate_label="domain_safe",
            input_mode="text",
            asr_provider="fake_asr",
            llm_provider="fake_llm",
            tts_provider="fake_tts",
            execution_profile="test",
            timing_source="server_audio_payload_ready",
            first_audio_ms=1,
            total_ms=1,
            asr_ms=0,
            retrieval_ms=0,
            llm_first_token_ms=1,
            tts_first_audio_ms=1,
            answer_chars=2,
            evidence_count=0,
            server_audio_payload_ready_ms=1,
            llm_complete_ms=1,
            tts_complete_ms=1,
        )
        return PipelineResult(
            question=question,
            transcript=question,
            answer="ok",
            gate=GateResult(label="domain_safe", allowed=True, reason="test"),
            evidence=[],
            events=[],
            metrics=metrics,
            provider_status={},
            audio_output=TTSResult(provider="fake_tts", audio_base64="UklGRg==", mime_type="audio/wav"),
        )


class CancellablePipeline(SlowPipeline):
    async def run_once(self, question: str, **kwargs: object) -> PipelineResult:
        cancel_event = kwargs.get("cancel_event")
        for _ in range(40):
            if getattr(cancel_event, "is_set", lambda: False)():
                raise PipelineCancelled("run cancelled during test")
            await asyncio.sleep(0.01)
        return await super().run_once(question, **kwargs)


class AdminApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env_path = ROOT / "configs" / "runtime.fullreal.local.env"
        if env_path.exists():
            load_env_file(str(env_path))
        os.environ["SHIPVOICE_ADMIN_PASSWORD"] = "test-admin-password"
        os.environ["SHIPVOICE_ADMIN_SESSION_SECRET"] = "shipvoice-admin-test-secret"
        cls.app = create_app()

    async def asyncSetUp(self) -> None:
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def login_headers(self) -> dict[str, str]:
        response = await self.client.post("/api/admin/auth/login", json={"password": "test-admin-password"})
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    async def test_admin_endpoints_require_auth(self) -> None:
        response = await self.client.get("/api/admin/overview")
        self.assertEqual(response.status_code, 401)
        self.assertIn("authentication required", response.json()["error"])

    async def test_admin_login_and_session(self) -> None:
        status_response = await self.client.get("/api/admin/auth/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["auth"]["mode"], "configured_password")

        bad_response = await self.client.post("/api/admin/auth/login", json={"password": "wrong-password"})
        self.assertEqual(bad_response.status_code, 401)

        headers = await self.login_headers()
        session_response = await self.client.get("/api/admin/auth/session", headers=headers)
        self.assertEqual(session_response.status_code, 200)
        self.assertEqual(session_response.json()["session"]["subject"], "shipvoice-admin")

    async def test_live_and_ready_endpoints_are_separate(self) -> None:
        live_response = await self.client.get("/api/live")
        self.assertEqual(live_response.status_code, 200)
        self.assertTrue(live_response.json()["ok"])

        ready_snapshot = {
            "asr": {"endpoint": "http://asr.local/health", "reachable": True, "http_status": 200},
            "llm": {
                "endpoint": "http://llm.local/v1/models",
                "reachable": True,
                "http_status": 200,
                "model": "shipvoice-qwen2.5-7b-lora",
                "model_available": True,
                "health_reachable": True,
                "health_http_status": 200,
                "adapter_loaded": True,
                "adapter_sha256": "abc123",
            },
            "tts": {"endpoint": "http://tts.local/health", "reachable": True, "http_status": 200},
            "updated_at": "2026-06-22T00:00:00+00:00",
        }
        with replace_attr(fastapi_app_module, "provider_health_snapshot", CallRecorder(return_value=ready_snapshot)):
            ready_response = await self.client.get("/api/ready")
        self.assertEqual(ready_response.status_code, 200)
        self.assertTrue(ready_response.json()["ready"])

        with (
            patched_env(SHIPVOICE_REQUIRE_LORA="1", SHIPVOICE_LORA_ADAPTER_SHA256="abc123"),
            replace_attr(fastapi_app_module, "provider_health_snapshot", CallRecorder(return_value=ready_snapshot)),
        ):
            attested_response = await self.client.get("/api/ready")
        self.assertEqual(attested_response.status_code, 200)
        self.assertTrue(attested_response.json()["ready"])

        with (
            patched_env(SHIPVOICE_REQUIRE_LORA="1", SHIPVOICE_LORA_ADAPTER_SHA256="wrong"),
            replace_attr(fastapi_app_module, "provider_health_snapshot", CallRecorder(return_value=ready_snapshot)),
        ):
            sha_mismatch_response = await self.client.get("/api/ready")
        self.assertEqual(sha_mismatch_response.status_code, 503)
        self.assertFalse(sha_mismatch_response.json()["ready"])
        self.assertIn("adapter SHA", sha_mismatch_response.json()["components"]["llm"]["ready_reason"])

        not_ready_snapshot = {
            **ready_snapshot,
            "tts": {"endpoint": "http://tts.local/health", "reachable": False, "http_status": None},
        }
        with replace_attr(fastapi_app_module, "provider_health_snapshot", CallRecorder(return_value=not_ready_snapshot)):
            not_ready_response = await self.client.get("/api/ready")
        self.assertEqual(not_ready_response.status_code, 503)
        self.assertFalse(not_ready_response.json()["ready"])

    async def test_same_session_concurrent_run_is_rejected(self) -> None:
        with (
            patched_env(SHIPVOICE_RUN_QUEUE_WAIT_SECONDS="0.05", SHIPVOICE_RUN_TIMEOUT_SECONDS="5"),
            replace_attr(fastapi_app_module, "VoiceQAPipeline", SlowPipeline),
            replace_attr(fastapi_app_module, "SQLiteAppStore", MinimalStore),
        ):
            app = create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            first = asyncio.create_task(
                client.post(
                    "/api/run",
                    json={
                        "session_id": "session-lock-test",
                        "client_request_id": "session-lock-test:first",
                        "question": "ship safety work",
                        "mode": "full",
                    },
                )
            )
            await asyncio.sleep(0.02)
            second = await client.post(
                "/api/run",
                json={
                    "session_id": "session-lock-test",
                    "client_request_id": "session-lock-test:second",
                    "question": "ship safety work",
                    "mode": "full",
                },
            )
            first_response = await first

        self.assertEqual(first_response.status_code, 200, first_response.text)
        self.assertEqual(second.status_code, 409)
        second_payload = second.json()
        second_error = second_payload.get("error") or second_payload.get("detail", {}).get("error")
        self.assertEqual(second_error, "session already has a run in progress")

    async def test_cancel_running_run_sets_cancel_event(self) -> None:
        with (
            patched_env(SHIPVOICE_RUN_QUEUE_WAIT_SECONDS="0.05", SHIPVOICE_RUN_TIMEOUT_SECONDS="5"),
            replace_attr(fastapi_app_module, "VoiceQAPipeline", CancellablePipeline),
            replace_attr(fastapi_app_module, "SQLiteAppStore", MinimalStore),
        ):
            app = create_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            run_id = "session-cancel-test:req"
            running = asyncio.create_task(
                client.post(
                    "/api/run",
                    json={
                        "session_id": "session-cancel-test",
                        "client_request_id": run_id,
                        "question": "ship safety work",
                        "mode": "full",
                    },
                )
            )
            await asyncio.sleep(0.05)
            cancel_response = await client.post(
                f"/api/runs/{run_id}/cancel",
                json={"session_id": "session-cancel-test", "metrics": {}},
            )
            run_response = await running
            status_response = await client.get(f"/api/runs/{run_id}?session_id=session-cancel-test")

        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        self.assertTrue(cancel_response.json()["cancel_requested"])
        self.assertEqual(run_response.status_code, 499, run_response.text)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "cancelled")

    async def test_admin_export_formats(self) -> None:
        sample_run = {
            "run_id": "run-001",
            "session_id": "session-001",
            "status": "ok",
            "created_at": "2026-06-13T10:00:00+00:00",
            "mode": "full",
            "question": "question",
            "transcript": "transcript",
            "gate_label": "domain_safe",
            "gate_allowed": True,
            "answer_preview": "answer",
            "providers": {"llm": "openai_compatible:Qwen/Qwen2.5-7B-Instruct"},
            "metrics": {"total_ms": 1234},
            "error": "",
            "evidence_titles": ["record-a"],
            "audio_name": "clip.wav",
            "case_status": "open",
            "case_severity": "high",
            "case_type": "latency",
            "case_owner": "ops-a",
            "case_note": "首音过慢",
            "case_reviewer": "",
            "case_reviewed_at": "",
            "case_updated_at": "2026-06-13T10:00:00+00:00",
        }

        with replace_attr(fastapi_app_module.SQLiteAppStore, "search_runs", CallRecorder(return_value=[sample_run])):
            headers = await self.login_headers()

            jsonl_response = await self.client.get("/api/admin/runs/export?format=jsonl&limit=1", headers=headers)
            self.assertEqual(jsonl_response.status_code, 200)
            self.assertEqual(jsonl_response.headers["content-type"], "application/x-ndjson")
            self.assertIn("attachment; filename=", jsonl_response.headers["content-disposition"])
            self.assertIn('"run_id": "run-001"', jsonl_response.text)

            csv_response = await self.client.get("/api/admin/runs/export?format=csv&limit=1", headers=headers)
            self.assertEqual(csv_response.status_code, 200)
            self.assertEqual(csv_response.headers["content-type"], "text/csv; charset=utf-8")
            self.assertIn("attachment; filename=", csv_response.headers["content-disposition"])
            self.assertIn("run_id,session_id,status", csv_response.text)
            self.assertIn("case_status,case_severity,case_type", csv_response.text)
            self.assertIn("run-001", csv_response.text)

    async def test_admin_evaluation_run_invokes_scripts(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python", "script.py"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        headers = await self.login_headers()
        run_call = CallRecorder(return_value=completed)
        with (
            replace_attr(fastapi_app_module.subprocess, "run", run_call),
            replace_attr(
                fastapi_app_module.SQLiteAppStore,
                "reload_evaluations",
                CallRecorder(return_value={"dataset_count": 2, "datasets": [], "updated_at": "2026-06-13T10:00:00+00:00"}),
            ),
        ):
            response = await self.client.post(
                "/api/admin/evaluations/run",
                headers=headers,
                json={"targets": ["dashboard", "asr"], "reload_after": True},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["targets"], ["dashboard", "asr"])
        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(payload["reload"]["dataset_count"], 2)
        self.assertEqual(run_call.call_count, 2)
        invoked = [Path(args[0][1]).name for args, _kwargs in run_call.calls]
        self.assertEqual(invoked, ["build_evaluation_dashboard.py", "evaluate_asr_transcripts.py"])

    async def test_admin_evaluation_run_rejects_unknown_target(self) -> None:
        headers = await self.login_headers()
        response = await self.client.post(
            "/api/admin/evaluations/run",
            headers=headers,
            json={"targets": ["not-real"], "reload_after": False},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown evaluation targets", response.json()["error"])

    async def test_admin_run_case_update(self) -> None:
        updated_run = {
            "run_id": "run-001",
            "session_id": "session-001",
            "status": "ok",
            "created_at": "2026-06-13T10:00:00+00:00",
            "mode": "full",
            "question": "question",
            "transcript": "transcript",
            "gate_label": "domain_safe",
            "gate_allowed": True,
            "answer_preview": "answer",
            "providers": {"llm": "openai_compatible:Qwen/Qwen2.5-7B-Instruct"},
            "metrics": {"total_ms": 1234},
            "error": "",
            "evidence_titles": [],
            "audio_name": "",
            "case_status": "resolved",
            "case_severity": "medium",
            "case_type": "quality",
            "case_owner": "ops-a",
            "case_note": "复盘完成",
            "case_reviewer": "reviewer-a",
            "case_reviewed_at": "2026-06-13T10:10:00+00:00",
            "case_updated_at": "2026-06-13T10:10:00+00:00",
        }
        headers = await self.login_headers()
        update_call = CallRecorder(return_value=updated_run)
        with (
            replace_attr(fastapi_app_module.SQLiteAppStore, "update_run_case", update_call),
            replace_attr(
                fastapi_app_module.SQLiteAppStore,
                "audit_stats",
                CallRecorder(return_value={"total_runs": 1, "open_cases": 0}),
            ),
        ):
            response = await self.client.put(
                "/api/admin/runs/run-001/case",
                headers=headers,
                json={
                    "case_status": "resolved",
                    "case_severity": "medium",
                    "case_type": "quality",
                    "case_owner": "ops-a",
                    "case_note": "复盘完成",
                    "case_reviewer": "reviewer-a",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["run"]["case_status"], "resolved")
        self.assertEqual(update_call.calls[0][0][0], "run-001")

    async def test_admin_run_case_update_rejects_invalid_status(self) -> None:
        headers = await self.login_headers()
        with replace_attr(
            fastapi_app_module.SQLiteAppStore,
            "update_run_case",
            CallRecorder(side_effect=ValueError("unsupported run case status")),
        ):
            response = await self.client.put(
                "/api/admin/runs/run-001/case",
                headers=headers,
                json={
                    "case_status": "not-real",
                    "case_severity": "medium",
                    "case_type": "quality",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported run case status", response.json()["error"])

    async def test_admin_knowledge_detail_includes_history(self) -> None:
        sample_record = {
            "id": "KS099",
            "title": "受限空间隔离",
            "tags": ["有限空间", "隔离"],
            "text": "进入前需要完成机械、电气、介质隔离。",
            "status": "in_review",
            "owner": "team-a",
            "source": "安全手册 4.2",
            "review_notes": "等待老师复核",
            "last_reviewer": "reviewer-a",
            "last_reviewed_at": "2026-06-13T10:00:00+00:00",
            "current_version": 3,
            "created_at": "2026-06-12T10:00:00+00:00",
            "updated_at": "2026-06-13T10:00:00+00:00",
        }
        history = [
            {
                "record_id": "KS099",
                "version_no": 3,
                "action": "status_changed",
                "actor": "reviewer-a",
                "change_note": "提交审核",
                "created_at": "2026-06-13T10:00:00+00:00",
                "snapshot": sample_record,
            }
        ]
        headers = await self.login_headers()
        with (
            replace_attr(fastapi_app_module.SQLiteAppStore, "get_knowledge", CallRecorder(return_value=sample_record)),
            replace_attr(fastapi_app_module.SQLiteAppStore, "list_knowledge_versions", CallRecorder(return_value=history)),
        ):
            response = await self.client.get("/api/admin/knowledge/KS099", headers=headers)

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["record"]["status"], "in_review")
        self.assertEqual(payload["record"]["current_version"], 3)
        self.assertEqual(payload["history"][0]["change_note"], "提交审核")

    async def test_admin_knowledge_create_rejects_invalid_status(self) -> None:
        headers = await self.login_headers()
        with replace_attr(
            fastapi_app_module.SQLiteAppStore,
            "upsert_knowledge",
            CallRecorder(side_effect=ValueError("unsupported knowledge status")),
        ):
            response = await self.client.post(
                "/api/admin/knowledge",
                headers=headers,
                json={
                    "id": "KS101",
                    "title": "测试条目",
                    "tags": ["测试"],
                    "text": "测试正文",
                    "status": "bad-status",
                    "owner": "tester",
                    "source": "manual",
                    "reviewer": "",
                    "review_notes": "",
                    "change_note": "invalid status attempt",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported knowledge status", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
