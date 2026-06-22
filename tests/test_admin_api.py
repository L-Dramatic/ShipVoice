from __future__ import annotations

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


@contextmanager
def replace_attr(target: object, name: str, value: object):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield value
    finally:
        setattr(target, name, original)


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


class AdminApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_env_file(str(ROOT / "configs" / "runtime.fullreal.local.env"))
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
