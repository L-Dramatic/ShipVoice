from __future__ import annotations

import asyncio
import base64
import functools
import json
import os
import socket
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web" / "static"
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.audit import AuditStore, utc_now_iso  # noqa: E402
from shipvoice.knowledge import KnowledgeStore  # noqa: E402
from shipvoice.models import AuditRecord  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def find_free_port(preferred: int = 8010) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free local port found from {preferred} to {preferred + 19}")


def main() -> None:
    preferred_port = int(os.getenv("SHIPVOICE_PORT", "8010"))
    port = find_free_port(preferred_port)
    pipeline = VoiceQAPipeline()
    audit = AuditStore(ROOT / "results" / "runtime")
    knowledge = KnowledgeStore()
    handler = functools.partial(
        ShipVoiceHandler,
        directory=str(WEB_ROOT),
        pipeline=pipeline,
        audit=audit,
        knowledge=knowledge,
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"ShipVoice demo: http://127.0.0.1:{port}")
    print(f"ShipVoice admin: http://127.0.0.1:{port}/admin.html")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


class ShipVoiceHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        pipeline: VoiceQAPipeline,
        audit: AuditStore,
        knowledge: KnowledgeStore,
        **kwargs,
    ) -> None:
        self.pipeline = pipeline
        self.audit = audit
        self.knowledge = knowledge
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json(self._health_payload())
            return
        if parsed.path == "/api/sessions":
            self._send_json(self._sessions_payload(parsed))
            return
        if parsed.path == "/api/admin/overview":
            self._send_json(self._admin_overview())
            return
        if parsed.path == "/api/admin/runs":
            self._send_json(self._admin_runs(parsed))
            return
        if parsed.path == "/api/admin/knowledge":
            self._send_json(self._admin_knowledge_list(parsed))
            return
        if parsed.path.startswith("/api/admin/knowledge/"):
            record_id = parsed.path.removeprefix("/api/admin/knowledge/").strip()
            record = self.knowledge.get_record(record_id)
            if record is None:
                self._send_json({"error": f"knowledge record not found: {record_id}"}, status=404)
                return
            self._send_json({"ok": True, "record": record})
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            self._handle_run()
            return
        if parsed.path == "/api/admin/knowledge":
            payload = self._read_json_payload()
            result = self.knowledge.upsert(payload)
            self._send_json(result, status=201 if result.get("action") == "created" else 200)
            return
        if parsed.path == "/api/admin/reindex":
            result = self.knowledge.rebuild_index()
            self._send_json({"ok": True, "index": result})
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/admin/knowledge/"):
            self.send_error(404)
            return
        record_id = parsed.path.removeprefix("/api/admin/knowledge/").strip()
        payload = self._read_json_payload()
        result = self.knowledge.upsert(payload, record_id=record_id)
        self._send_json(result)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/admin/knowledge/"):
            self.send_error(404)
            return
        record_id = parsed.path.removeprefix("/api/admin/knowledge/").strip()
        try:
            result = self.knowledge.delete(record_id)
        except KeyError:
            self._send_json({"error": f"knowledge record not found: {record_id}"}, status=404)
            return
        self._send_json(result)

    def _handle_run(self) -> None:
        run_id = uuid.uuid4().hex[:12]
        created_at = utc_now_iso()
        session_id = ""
        mode = "full"
        question = ""
        transcript = ""
        audio_name = ""
        try:
            payload = self._read_json_payload()
            question = str(payload.get("question", "")).strip()
            mode = str(payload.get("mode", "full")).strip() or "full"
            history = payload.get("history", [])
            session_id = str(payload.get("session_id", "")).strip() or uuid.uuid4().hex[:12]
            audio_base64 = str(payload.get("audio_base64", "")).strip()
            audio_name = str(payload.get("audio_name", "")).strip()
            audio_bytes = base64.b64decode(audio_base64) if audio_base64 else None
            if not question and not audio_bytes:
                self.audit.append(
                    AuditRecord(
                        run_id=run_id,
                        session_id=session_id,
                        status="error",
                        created_at=created_at,
                        mode=mode,
                        question="",
                        transcript="",
                        gate_label="bad_request",
                        answer_preview="",
                        providers={},
                        metrics={},
                        error="missing question",
                        evidence_titles=[],
                        audio_name=audio_name,
                    )
                )
                self._send_json({"error": "missing question", "run_id": run_id, "session_id": session_id}, status=400)
                return
            result = asyncio.run(
                self.pipeline.run_once(
                    question,
                    audio_bytes=audio_bytes,
                    audio_name=audio_name,
                    history=history if isinstance(history, list) else [],
                    mode=mode,
                )
            )
            transcript = result.transcript
            self.audit.append(
                AuditRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="ok",
                    created_at=created_at,
                    mode=mode,
                    question=result.question,
                    transcript=result.transcript,
                    gate_label=result.gate.label,
                    gate_allowed=result.gate.allowed,
                    answer_preview=result.answer[:180],
                    providers=result.provider_status,
                    metrics=result.metrics.to_row(),
                    evidence_titles=[hit.title for hit in result.evidence],
                    audio_name=audio_name,
                )
            )
            self._send_json(
                {
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                    "question": result.question,
                    "transcript": result.transcript,
                    "answer": result.answer,
                    "gate": result.gate.__dict__,
                    "evidence": [hit.__dict__ for hit in result.evidence],
                    "events": [event.to_dict() for event in result.events],
                    "metrics": result.metrics.to_row(),
                    "provider_status": result.provider_status,
                    "audio_output": result.audio_output.__dict__,
                }
            )
        except Exception as exc:
            session_id = session_id or uuid.uuid4().hex[:12]
            self.audit.append(
                AuditRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="error",
                    created_at=created_at,
                    mode=mode,
                    question=question,
                    transcript=transcript,
                    gate_label="error",
                    answer_preview="",
                    providers={},
                    metrics={},
                    error=str(exc),
                    evidence_titles=[],
                    audio_name=audio_name,
                )
            )
            self._send_json(
                {
                    "error": str(exc),
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                },
                status=500,
            )

    def _health_payload(self) -> dict[str, object]:
        return {
            "ok": True,
            "service": "shipvoice",
            "providers": {
                "asr": getattr(self.pipeline.asr, "name", self.pipeline.asr.__class__.__name__),
                "llm": getattr(self.pipeline.llm, "name", self.pipeline.llm.__class__.__name__),
                "tts": getattr(self.pipeline.tts, "name", self.pipeline.tts.__class__.__name__),
            },
            "audit": {
                "log_path": str(self.audit.audit_path),
                "recent_runs": self.audit.total_runs(),
            },
            "knowledge": self.knowledge.summary(),
        }

    def _sessions_payload(self, parsed) -> dict[str, object]:
        query = parse_qs(parsed.query)
        session_id = query.get("session_id", [""])[0].strip()
        runs = self.audit.session_runs(session_id, limit=12) if session_id else self.audit.recent_runs(limit=12)
        return {
            "ok": True,
            "current_session_id": session_id,
            "sessions": self.audit.session_summaries(limit=12),
            "runs": runs,
        }

    def _admin_runs(self, parsed) -> dict[str, object]:
        query = parse_qs(parsed.query)
        runs = self.audit.search_runs(
            query=query.get("query", [""])[0],
            status=query.get("status", [""])[0],
            gate_label=query.get("gate_label", [""])[0],
            limit=int(query.get("limit", ["50"])[0] or "50"),
        )
        return {
            "ok": True,
            "stats": self.audit.stats(),
            "runs": runs,
        }

    def _admin_knowledge_list(self, parsed) -> dict[str, object]:
        query = parse_qs(parsed.query)
        records = self.knowledge.list_records(
            query=query.get("query", [""])[0],
            tag=query.get("tag", [""])[0],
            limit=int(query.get("limit", ["100"])[0] or "100"),
        )
        return {
            "ok": True,
            "summary": self.knowledge.summary(),
            "records": records,
        }

    def _admin_overview(self) -> dict[str, object]:
        asr_summary = self._read_json(ROOT / "results" / "asr_eval_summary.json")
        multiturn_summary = self._read_json(ROOT / "results" / "multiturn_eval_summary.json")
        real_chain_summary = self._read_json(ROOT / "results" / "remote_real_chain_20260612_chattts_48359" / "summary.json")
        return {
            "ok": True,
            "knowledge": self.knowledge.summary(),
            "audit": self.audit.stats(),
            "providers": self._health_payload()["providers"],
            "evaluation": {
                "asr": {
                    "status": asr_summary.get("status", "missing"),
                    "evaluated_rows": asr_summary.get("evaluated_rows", 0),
                    "avg_cer": asr_summary.get("avg_cer", 0),
                    "term_recall": asr_summary.get("term_recall", 0),
                },
                "multiturn": {
                    "dialogs": multiturn_summary.get("dialogs", 0),
                    "gate_accuracy": multiturn_summary.get("gate_accuracy", 0),
                    "top1_title_accuracy": multiturn_summary.get("top1_title_accuracy", 0),
                    "followup_grounding_accuracy": multiturn_summary.get("followup_grounding_accuracy", 0),
                    "avg_total_ms": multiturn_summary.get("avg_total_ms", 0),
                    "avg_first_audio_ms": multiturn_summary.get("avg_first_audio_ms", 0),
                },
                "real_chain": {
                    "num_samples": real_chain_summary.get("num_samples", 0),
                    "avg_asr_ms": real_chain_summary.get("avg_asr_ms", 0),
                    "avg_retrieval_ms": real_chain_summary.get("avg_retrieval_ms", 0),
                    "avg_first_audio_ms": real_chain_summary.get("avg_first_audio_ms", 0),
                },
            },
        }

    def _read_json_payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _read_json(self, path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    main()
