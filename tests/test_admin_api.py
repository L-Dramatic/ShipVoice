from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402
from shipvoice.fastapi_app import create_app  # noqa: E402


class AdminApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        load_env_file(str(ROOT / "configs" / "runtime.mock.env"))
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
            "providers": {"llm": "mock"},
            "metrics": {"total_ms": 1234},
            "error": "",
            "evidence_titles": ["record-a"],
            "audio_name": "clip.wav",
        }

        with patch("shipvoice.fastapi_app.SQLiteAppStore.search_runs", return_value=[sample_run]):
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
            self.assertIn("run-001", csv_response.text)

    async def test_admin_evaluation_run_invokes_scripts(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python", "script.py"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        headers = await self.login_headers()
        with (
            patch("shipvoice.fastapi_app.subprocess.run", return_value=completed) as run_mock,
            patch(
                "shipvoice.fastapi_app.SQLiteAppStore.reload_evaluations",
                return_value={"dataset_count": 2, "datasets": [], "updated_at": "2026-06-13T10:00:00+00:00"},
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
        self.assertEqual(run_mock.call_count, 2)
        invoked = [Path(call.args[0][1]).name for call in run_mock.call_args_list]
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


if __name__ == "__main__":
    unittest.main()
