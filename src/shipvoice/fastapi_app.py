from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_config, project_path
from .models import AuditRecord
from .pipeline import VoiceQAPipeline
from .sqlite_store import SQLiteAppStore, utc_now_iso


WEB_ROOT = project_path("web", "static")
CONFIG_PATH = project_path("configs", "pipeline.json")
DEFAULT_ADMIN_PASSWORD = "shipvoice-admin"
DEFAULT_ADMIN_SESSION_TTL_SECONDS = 8 * 60 * 60


class RunRequest(BaseModel):
    session_id: str = ""
    question: str = ""
    mode: str = "full"
    history: list[dict[str, str]] = Field(default_factory=list)
    audio_base64: str = ""
    audio_name: str = ""


class KnowledgePayload(BaseModel):
    id: str = ""
    title: str
    tags: list[str] = Field(default_factory=list)
    text: str
    status: str = "draft"
    owner: str = ""
    source: str = ""
    reviewer: str = ""
    review_notes: str = ""
    change_note: str = ""


class ConfigPayload(BaseModel):
    raw_text: str


class RunCleanupPayload(BaseModel):
    query: str = ""
    delete_smoke: bool = True
    delete_mojibake: bool = True


class RunCasePayload(BaseModel):
    case_status: str = "open"
    case_severity: str = "medium"
    case_type: str = "quality"
    case_owner: str = ""
    case_note: str = ""
    case_reviewer: str = ""


class AdminLoginPayload(BaseModel):
    password: str


class EvaluationRunPayload(BaseModel):
    targets: list[str] = Field(default_factory=lambda: ["safety_gate", "asr", "multiturn", "dashboard"])
    reload_after: bool = True
    async_mode: bool = False


def result_to_payload(run_id: str, session_id: str, created_at: str, result) -> dict[str, Any]:
    return {
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


def probe_http_url(url: str, timeout_s: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return {
                "reachable": True,
                "http_status": getattr(response, "status", 200),
                "detail": "ok",
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "http_status": exc.code,
            "detail": "http_error",
        }
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {
            "reachable": False,
            "http_status": None,
            "detail": str(exc),
        }


def openai_models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized.removesuffix("/chat/completions") + "/models"
    if normalized.endswith("/v1"):
        return normalized + "/models"
    return normalized + "/v1/models"


def probe_openai_models(base_url: str, model: str, api_key: str = "", timeout_s: int = 5) -> dict[str, Any]:
    url = openai_models_url(base_url)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("data", []) if isinstance(payload, dict) else []
        ids = [str(item.get("id", "")).strip() for item in items if isinstance(item, dict)]
        listed = [item for item in ids if item][:8]
        model_available = model in ids if model else False
        return {
            "reachable": True,
            "http_status": 200,
            "detail": "ok",
            "probe_url": url,
            "model_available": model_available,
            "listed_models": listed,
        }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": True,
            "http_status": exc.code,
            "detail": "http_error",
            "probe_url": url,
            "model_available": False,
            "listed_models": [],
        }
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "reachable": False,
            "http_status": None,
            "detail": str(exc),
            "probe_url": url,
            "model_available": False,
            "listed_models": [],
        }


def provider_health_snapshot(pipeline: VoiceQAPipeline) -> dict[str, Any]:
    asr = pipeline.asr
    llm = pipeline.llm
    tts = pipeline.tts

    asr_endpoint = getattr(asr, "endpoint", "")
    llm_endpoint = llm._endpoint() if hasattr(llm, "_endpoint") else getattr(llm, "base_url", "")
    tts_endpoint = getattr(tts, "endpoint", "")

    def item(
        name: str,
        provider: Any,
        endpoint: str = "",
        extra: dict[str, Any] | None = None,
        probe: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = extra or {}
        probe_payload = probe or {"reachable": None, "http_status": None, "detail": "local_or_unprobed"}
        if endpoint and probe is None:
            probe_payload = probe_http_url(endpoint, timeout_s=3)
        return {
            "component": name,
            "provider": getattr(provider, "name", provider.__class__.__name__),
            "mode": "real",
            "endpoint": endpoint,
            **probe_payload,
            **extra,
        }

    llm_model = getattr(llm, "model", "")
    llm_api_key = os.environ.get(getattr(llm, "api_key_env", ""), "") if getattr(llm, "api_key_env", "") else ""
    llm_probe = None
    if llm_endpoint:
        llm_probe = probe_openai_models(getattr(llm, "base_url", llm_endpoint), llm_model, api_key=llm_api_key, timeout_s=5)
    return {
        "asr": item("ASR", asr, asr_endpoint),
        "llm": item("LLM", llm, llm_endpoint, extra={"model": llm_model}, probe=llm_probe),
        "tts": item("TTS", tts, tts_endpoint),
        "updated_at": utc_now_iso(),
    }


def admin_password() -> str:
    return os.environ.get("SHIPVOICE_ADMIN_PASSWORD", "").strip() or DEFAULT_ADMIN_PASSWORD


def admin_auth_mode() -> str:
    return "configured_password" if os.environ.get("SHIPVOICE_ADMIN_PASSWORD", "").strip() else "default_password"


def admin_session_ttl_seconds() -> int:
    raw_value = os.environ.get("SHIPVOICE_ADMIN_TOKEN_TTL_SECONDS", "").strip()
    if raw_value.isdigit():
        return max(300, int(raw_value))
    return DEFAULT_ADMIN_SESSION_TTL_SECONDS


def admin_session_secret() -> str:
    configured = os.environ.get("SHIPVOICE_ADMIN_SESSION_SECRET", "").strip()
    if configured:
        return configured
    return f"shipvoice-admin-secret:{CONFIG_PATH}:{WEB_ROOT}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def issue_admin_token() -> dict[str, Any]:
    issued_at = int(time.time())
    payload = {
        "sub": "shipvoice-admin",
        "mode": admin_auth_mode(),
        "iat": issued_at,
        "exp": issued_at + admin_session_ttl_seconds(),
    }
    payload_blob = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = hmac.new(
        admin_session_secret().encode("utf-8"),
        payload_blob.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    payload["token"] = f"{payload_blob}.{signature}"
    return payload


def verify_admin_token(token: str) -> dict[str, Any]:
    if "." not in token:
        raise HTTPException(status_code=401, detail={"error": "invalid admin token"})
    payload_blob, signature = token.split(".", 1)
    expected = hmac.new(
        admin_session_secret().encode("utf-8"),
        payload_blob.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail={"error": "invalid admin token signature"})
    try:
        payload = json.loads(_b64url_decode(payload_blob).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail={"error": "invalid admin token payload"}) from exc
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise HTTPException(status_code=401, detail={"error": "admin token expired"})
    return payload


def extract_admin_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("X-Admin-Token", "").strip()


def require_admin(request: Request) -> dict[str, Any]:
    token = extract_admin_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": "admin authentication required"})
    return verify_admin_token(token)


def create_app() -> FastAPI:
    app = FastAPI(title="ShipVoice API", version="0.2.0")
    runtime: dict[str, VoiceQAPipeline] = {"pipeline": VoiceQAPipeline()}
    store = SQLiteAppStore()

    def current_pipeline() -> VoiceQAPipeline:
        return runtime["pipeline"]

    def reload_pipeline_from_disk() -> VoiceQAPipeline:
        load_config(CONFIG_PATH)
        runtime["pipeline"] = VoiceQAPipeline()
        return runtime["pipeline"]

    def run_evaluation_scripts(
        targets: list[str],
        *,
        progress_callback: Any | None = None,
    ) -> list[dict[str, Any]]:
        project_root = project_path()
        script_specs = {
            "safety_gate": project_path("scripts", "evaluate_safety_gate.py"),
            "asr": project_path("scripts", "evaluate_asr_transcripts.py"),
            "multiturn": project_path("scripts", "evaluate_multiturn.py"),
            "dashboard": project_path("scripts", "build_evaluation_dashboard.py"),
        }
        unknown = [target for target in targets if target not in script_specs]
        if unknown:
            raise HTTPException(status_code=400, detail={"error": f"unknown evaluation targets: {', '.join(unknown)}"})

        reports: list[dict[str, Any]] = []
        total_targets = len(targets)
        for index, target in enumerate(targets, start=1):
            script_path = script_specs[target]
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    [sys.executable, str(script_path)],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=1800,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(
                    status_code=504,
                    detail={"error": f"evaluation target timed out: {target}", "target": target},
                ) from exc
            reports.append(
                {
                    "target": target,
                    "script": str(script_path),
                    "returncode": int(completed.returncode),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                    "ok": completed.returncode == 0,
                }
            )
            if progress_callback is not None:
                progress_callback(index, total_targets, reports[-1])
            if completed.returncode != 0:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "error": f"evaluation target failed: {target}",
                        "target": target,
                        "stdout_tail": completed.stdout[-4000:],
                        "stderr_tail": completed.stderr[-4000:],
                    },
                )
        return reports

    def launch_evaluation_job(payload: EvaluationRunPayload, admin: dict[str, Any]) -> dict[str, Any]:
        targets = list(dict.fromkeys([item.strip() for item in payload.targets if item.strip()]))
        if not targets:
            raise HTTPException(status_code=400, detail={"error": "no evaluation targets specified"})

        job_id = f"eval-{uuid.uuid4().hex[:12]}"
        store.create_admin_job(
            job_id=job_id,
            job_type="evaluation",
            label="离线批量评测",
            payload={
                "targets": targets,
                "reload_after": bool(payload.reload_after),
                "requested_by": admin.get("subject", "shipvoice-admin"),
            },
        )

        def worker() -> None:
            store.update_admin_job(job_id, status="running", progress=5, started_at=utc_now_iso(), error="")
            partial_reports: list[dict[str, Any]] = []
            try:
                def on_progress(index: int, total: int, report: dict[str, Any]) -> None:
                    partial_reports.append(report)
                    store.update_admin_job(
                        job_id,
                        progress=max(10, min(95, int(index / max(total, 1) * 90))),
                        result={"targets": targets, "reports": list(partial_reports)},
                    )

                reports = run_evaluation_scripts(targets, progress_callback=on_progress)
                reload_payload = store.reload_evaluations() if payload.reload_after else None
                store.update_admin_job(
                    job_id,
                    status="completed",
                    progress=100,
                    completed_at=utc_now_iso(),
                    result={
                        "targets": targets,
                        "reports": reports,
                        "reload": reload_payload,
                        "updated_at": utc_now_iso(),
                    },
                    error="",
                )
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else {"error": str(exc)}
                message = detail.get("error", str(exc)) if isinstance(detail, dict) else str(detail)
                store.update_admin_job(
                    job_id,
                    status="failed",
                    progress=100,
                    completed_at=utc_now_iso(),
                    result={
                        "targets": targets,
                        "reports": list(partial_reports),
                        "failure": detail if isinstance(detail, dict) else {"error": message},
                    },
                    error=message,
                )

        threading.Thread(target=worker, name=f"shipvoice-eval-{job_id}", daemon=True).start()
        job = store.get_admin_job(job_id)
        if job is None:
            raise HTTPException(status_code=500, detail={"error": "failed to create evaluation job"})
        return job

    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):  # type: ignore[override]
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(status_code=exc.status_code, content={"error": str(detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):  # type: ignore[override]
        return JSONResponse(status_code=422, content={"error": "request validation failed", "details": exc.errors()})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        pipeline = current_pipeline()
        return {
            "ok": True,
            "service": "shipvoice-fastapi",
            "providers": {
                "asr": getattr(pipeline.asr, "name", pipeline.asr.__class__.__name__),
                "llm": getattr(pipeline.llm, "name", pipeline.llm.__class__.__name__),
                "tts": getattr(pipeline.tts, "name", pipeline.tts.__class__.__name__),
            },
            "audit": {
                "db_path": str(store.db_path),
                "recent_runs": store.audit_stats()["total_runs"],
            },
            "runtime": {
                "env_file": os.environ.get("SHIPVOICE_ENV_FILE", ""),
            },
            "knowledge": store.knowledge_summary(),
        }

    @app.get("/api/sessions")
    def sessions(session_id: str = "") -> dict[str, Any]:
        runs = store.session_runs(session_id, limit=12) if session_id else store.recent_runs(limit=12)
        return {
            "ok": True,
            "current_session_id": session_id,
            "sessions": store.session_summaries(limit=12),
            "runs": runs,
        }

    @app.post("/api/run")
    async def run_question(request: RunRequest) -> dict[str, Any]:
        pipeline = current_pipeline()
        run_id = uuid.uuid4().hex[:12]
        created_at = utc_now_iso()
        session_id = request.session_id.strip() or uuid.uuid4().hex[:12]
        question = request.question.strip()
        audio_name = request.audio_name.strip()
        transcript = ""
        try:
            audio_bytes = base64.b64decode(request.audio_base64) if request.audio_base64 else None
            if not question and not audio_bytes:
                record = AuditRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="error",
                    created_at=created_at,
                    mode=request.mode,
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
                store.insert_audit(record)
                raise HTTPException(status_code=400, detail={"error": "missing question", "run_id": run_id, "session_id": session_id})

            result = await pipeline.run_once(
                question,
                audio_bytes=audio_bytes,
                audio_name=audio_name,
                history=request.history,
                mode=request.mode,
            )
            transcript = result.transcript
            store.insert_audit(
                AuditRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="ok",
                    created_at=created_at,
                    mode=request.mode,
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
            return result_to_payload(run_id, session_id, created_at, result)
        except HTTPException:
            raise
        except Exception as exc:
            store.insert_audit(
                AuditRecord(
                    run_id=run_id,
                    session_id=session_id,
                    status="error",
                    created_at=created_at,
                    mode=request.mode,
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
            raise HTTPException(
                status_code=500,
                detail={
                    "error": str(exc),
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                },
            ) from exc

    @app.get("/api/admin/auth/status")
    def admin_auth_status() -> dict[str, Any]:
        return {
            "ok": True,
            "auth": {
                "mode": admin_auth_mode(),
                "token_ttl_seconds": admin_session_ttl_seconds(),
            },
        }

    @app.post("/api/admin/auth/login")
    def admin_auth_login(payload: AdminLoginPayload) -> dict[str, Any]:
        if payload.password != admin_password():
            raise HTTPException(status_code=401, detail={"error": "invalid admin password"})
        session = issue_admin_token()
        return {
            "ok": True,
            "token": session["token"],
            "expires_at": session["exp"],
            "issued_at": session["iat"],
            "mode": session["mode"],
        }

    @app.get("/api/admin/auth/session")
    def admin_auth_session(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {
            "ok": True,
            "session": {
                "subject": admin.get("sub", ""),
                "mode": admin.get("mode", ""),
                "issued_at": admin.get("iat", 0),
                "expires_at": admin.get("exp", 0),
            },
        }

    @app.get("/api/admin/overview")
    def admin_overview(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        evaluation = store.evaluation_overview()
        config_payload = read_config()
        pipeline = current_pipeline()
        return {
            "ok": True,
            "knowledge": store.knowledge_summary(),
            "audit": store.audit_stats(),
            "providers": health()["providers"],
            "provider_health": provider_health_snapshot(pipeline),
            "evaluation": evaluation,
            "jobs": store.admin_job_summary(job_type="evaluation"),
            "config": {
                "project_name": config_payload["config"].get("project_name", ""),
                "llm_provider": config_payload["config"].get("llm", {}).get("provider", ""),
                "asr_provider": config_payload["config"].get("asr", {}).get("provider", ""),
                "tts_provider": config_payload["config"].get("tts", {}).get("provider", ""),
            },
        }

    @app.get("/api/admin/provider-health")
    def admin_provider_health(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {
            "ok": True,
            "providers": provider_health_snapshot(current_pipeline()),
        }

    @app.get("/api/admin/jobs")
    def admin_jobs(
        job_type: str = "",
        limit: int = 20,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        jobs = store.list_admin_jobs(job_type=job_type, limit=limit)
        return {
            "ok": True,
            "jobs": jobs,
            "summary": store.admin_job_summary(job_type=job_type),
        }

    @app.get("/api/admin/jobs/{job_id}")
    def admin_job_detail(job_id: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        job = store.get_admin_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"error": f"admin job not found: {job_id}"})
        return {"ok": True, "job": job}

    @app.get("/api/admin/runs")
    def admin_runs(
        query: str = "",
        status: str = "",
        gate_label: str = "",
        case_status: str = "",
        case_severity: str = "",
        case_type: str = "",
        limit: int = 50,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            runs = store.search_runs(
                query=query,
                status=status,
                gate_label=gate_label,
                case_status=case_status,
                case_severity=case_severity,
                case_type=case_type,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"ok": True, "stats": store.audit_stats(), "runs": runs}

    @app.get("/api/admin/runs/export")
    def admin_runs_export(
        format: str = "jsonl",
        query: str = "",
        status: str = "",
        gate_label: str = "",
        case_status: str = "",
        case_severity: str = "",
        case_type: str = "",
        limit: int = 500,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> Response:
        try:
            runs = store.search_runs(
                query=query,
                status=status,
                gate_label=gate_label,
                case_status=case_status,
                case_severity=case_severity,
                case_type=case_type,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        export_format = format.strip().lower()
        if export_format == "csv":
            buffer = io.StringIO()
            fieldnames = [
                "run_id",
                "session_id",
                "status",
                "created_at",
                "mode",
                "question",
                "transcript",
                "gate_label",
                "gate_allowed",
                "answer_preview",
                "providers",
                "metrics",
                "error",
                "evidence_titles",
                "audio_name",
                "case_status",
                "case_severity",
                "case_type",
                "case_owner",
                "case_note",
                "case_reviewer",
                "case_reviewed_at",
                "case_updated_at",
            ]
            writer = csv.DictWriter(buffer, fieldnames=fieldnames)
            writer.writeheader()
            for item in runs:
                writer.writerow(
                    {
                        **item,
                        "providers": json.dumps(item.get("providers", {}), ensure_ascii=False),
                        "metrics": json.dumps(item.get("metrics", {}), ensure_ascii=False),
                        "evidence_titles": json.dumps(item.get("evidence_titles", []), ensure_ascii=False),
                    }
                )
            content = buffer.getvalue().encode("utf-8-sig")
            filename = f"shipvoice-runs-{timestamp}.csv"
            media_type = "text/csv"
        elif export_format == "jsonl":
            content = ("\n".join(json.dumps(item, ensure_ascii=False) for item in runs) + ("\n" if runs else "")).encode("utf-8")
            filename = f"shipvoice-runs-{timestamp}.jsonl"
            media_type = "application/x-ndjson"
        else:
            raise HTTPException(status_code=400, detail={"error": f"unsupported export format: {format}"})
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.put("/api/admin/runs/{run_id}/case")
    def admin_run_case_update(
        run_id: str,
        payload: RunCasePayload,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            run = store.update_run_case(run_id, _payload_to_dict(payload))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": f"run not found: {run_id}"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"ok": True, "run": run, "stats": store.audit_stats()}

    @app.post("/api/admin/runs/cleanup")
    def admin_runs_cleanup(payload: RunCleanupPayload, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        result = store.cleanup_runs(
            query=payload.query,
            delete_smoke=payload.delete_smoke,
            delete_mojibake=payload.delete_mojibake,
        )
        return {
            "ok": True,
            "cleanup": result,
            "stats": store.audit_stats(),
        }

    @app.get("/api/admin/knowledge")
    def admin_knowledge(
        query: str = "",
        tag: str = "",
        status: str = "",
        limit: int = 100,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": store.knowledge_summary(),
            "records": store.list_knowledge(query=query, tag=tag, status=status, limit=limit),
        }

    @app.get("/api/admin/knowledge/{record_id}")
    def admin_knowledge_detail(record_id: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        record = store.get_knowledge(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"error": f"knowledge record not found: {record_id}"})
        return {"ok": True, "record": record, "history": store.list_knowledge_versions(record_id, limit=12)}

    @app.post("/api/admin/knowledge")
    def admin_knowledge_create(payload: KnowledgePayload, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        try:
            return store.upsert_knowledge(_payload_to_dict(payload))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.put("/api/admin/knowledge/{record_id}")
    def admin_knowledge_update(
        record_id: str,
        payload: KnowledgePayload,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            return store.upsert_knowledge(_payload_to_dict(payload), record_id=record_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.delete("/api/admin/knowledge/{record_id}")
    def admin_knowledge_delete(record_id: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        try:
            return store.delete_knowledge(record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": f"knowledge record not found: {record_id}"}) from exc

    @app.post("/api/admin/reindex")
    def admin_reindex(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {"ok": True, "index": store.sync_knowledge_files()}

    @app.get("/api/admin/evaluations")
    def admin_evaluations(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {
            "ok": True,
            "datasets": store.list_evaluation_datasets(),
        }

    @app.get("/api/admin/evaluations/{dataset_name}")
    def admin_evaluation_dataset(
        dataset_name: str,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        dataset = store.get_evaluation_dataset(dataset_name, query=query, limit=limit, offset=offset)
        if dataset is None:
            raise HTTPException(status_code=404, detail={"error": f"evaluation dataset not found: {dataset_name}"})
        return {"ok": True, **dataset}

    @app.post("/api/admin/evaluations/reload")
    def admin_evaluations_reload(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {"ok": True, "reload": store.reload_evaluations()}

    @app.post("/api/admin/evaluations/run")
    def admin_evaluations_run(
        payload: EvaluationRunPayload,
        admin: dict[str, Any] = Depends(require_admin),
    ) -> dict[str, Any]:
        if payload.async_mode:
            job = launch_evaluation_job(payload, admin)
            return {
                "ok": True,
                "mode": "async",
                "job": job,
                "updated_at": utc_now_iso(),
            }
        targets = list(dict.fromkeys([item.strip() for item in payload.targets if item.strip()]))
        if not targets:
            raise HTTPException(status_code=400, detail={"error": "no evaluation targets specified"})
        reports = run_evaluation_scripts(targets)
        reload_payload = store.reload_evaluations() if payload.reload_after else None
        return {
            "ok": True,
            "mode": "sync",
            "targets": targets,
            "reports": reports,
            "reload": reload_payload,
            "updated_at": utc_now_iso(),
        }

    @app.get("/api/admin/config")
    def admin_config(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        return {"ok": True, **read_config()}

    @app.post("/api/admin/config")
    def admin_config_save(payload: ConfigPayload, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        try:
            data = json.loads(payload.raw_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail={"error": f"invalid json: {exc}"}) from exc
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        pipeline = reload_pipeline_from_disk()
        return {
            "ok": True,
            "config": data,
            "providers": {
                "asr": getattr(pipeline.asr, "name", pipeline.asr.__class__.__name__),
                "llm": getattr(pipeline.llm, "name", pipeline.llm.__class__.__name__),
                "tts": getattr(pipeline.tts, "name", pipeline.tts.__class__.__name__),
            },
        }

    @app.post("/api/admin/config/reload")
    def admin_config_reload(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
        pipeline = reload_pipeline_from_disk()
        payload = read_config()
        return {
            "ok": True,
            **payload,
            "providers": {
                "asr": getattr(pipeline.asr, "name", pipeline.asr.__class__.__name__),
                "llm": getattr(pipeline.llm, "name", pipeline.llm.__class__.__name__),
                "tts": getattr(pipeline.tts, "name", pipeline.tts.__class__.__name__),
            },
        }

    @app.websocket("/ws/run")
    async def ws_run(websocket: WebSocket) -> None:
        await websocket.accept()
        pipeline = current_pipeline()
        run_id = uuid.uuid4().hex[:12]
        created_at = utc_now_iso()
        session_id = ""
        question = ""
        transcript = ""
        audio_name = ""
        mode = "full"
        try:
            raw_payload = await websocket.receive_json()
            request = RunRequest(**raw_payload)
            session_id = request.session_id.strip() or uuid.uuid4().hex[:12]
            question = request.question.strip()
            audio_name = request.audio_name.strip()
            mode = request.mode
            audio_bytes = base64.b64decode(request.audio_base64) if request.audio_base64 else None
            await websocket.send_json(
                {
                    "type": "accepted",
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                    "mode": mode,
                }
            )
            if not question and not audio_bytes:
                record = AuditRecord(
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
                store.insert_audit(record)
                await websocket.send_json({"type": "error", "error": "missing question", "run_id": run_id, "session_id": session_id})
                await websocket.close(code=1000)
                return

            async def forward_event(event) -> None:
                await websocket.send_json({"type": "event", "event": event.to_dict()})

            result = await pipeline.run_once(
                question,
                audio_bytes=audio_bytes,
                audio_name=audio_name,
                history=request.history,
                mode=mode,
                on_event=forward_event,
            )
            transcript = result.transcript
            store.insert_audit(
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
            await websocket.send_json({"type": "result", "result": result_to_payload(run_id, session_id, created_at, result)})
            await websocket.close(code=1000)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            if session_id:
                store.insert_audit(
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
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": str(exc),
                        "run_id": run_id,
                        "session_id": session_id,
                        "created_at": created_at,
                    }
                )
                await websocket.close(code=1011)
            except RuntimeError:
                pass

    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/admin.html")
    def admin_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "admin.html")

    app.mount("/", StaticFiles(directory=str(WEB_ROOT), html=True), name="static")
    return app


def _payload_to_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()  # type: ignore[no-any-return]
    return payload.dict()  # type: ignore[no-any-return]


def read_config() -> dict[str, Any]:
    raw_text = CONFIG_PATH.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    env_overrides = {
        "SHIPVOICE_ASR_PROVIDER": os.environ.get("SHIPVOICE_ASR_PROVIDER", ""),
        "SHIPVOICE_ASR_ENDPOINT": os.environ.get("SHIPVOICE_ASR_ENDPOINT", ""),
        "SHIPVOICE_LLM_PROVIDER": os.environ.get("SHIPVOICE_LLM_PROVIDER", ""),
        "SHIPVOICE_OPENAI_BASE_URL": os.environ.get("SHIPVOICE_OPENAI_BASE_URL", ""),
        "SHIPVOICE_LLM_MODEL": os.environ.get("SHIPVOICE_LLM_MODEL", ""),
        "SHIPVOICE_TTS_PROVIDER": os.environ.get("SHIPVOICE_TTS_PROVIDER", ""),
        "SHIPVOICE_TTS_ENDPOINT": os.environ.get("SHIPVOICE_TTS_ENDPOINT", ""),
        "SHIPVOICE_ENV_FILE": os.environ.get("SHIPVOICE_ENV_FILE", ""),
        "SHIPVOICE_ADMIN_AUTH_MODE": admin_auth_mode(),
    }
    return {
        "config": data,
        "raw_text": raw_text,
        "env_overrides": env_overrides,
        "config_path": str(CONFIG_PATH),
    }
