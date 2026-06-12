from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_config, project_path
from .models import AuditRecord
from .pipeline import VoiceQAPipeline
from .sqlite_store import SQLiteAppStore, utc_now_iso


WEB_ROOT = project_path("web", "static")
CONFIG_PATH = project_path("configs", "pipeline.json")


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


class ConfigPayload(BaseModel):
    raw_text: str


class RunCleanupPayload(BaseModel):
    query: str = ""
    delete_smoke: bool = True
    delete_mojibake: bool = True


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
        is_mock = "mock" in getattr(provider, "name", "").lower() or getattr(provider, "name", "") == "transcript_fallback"
        probe_payload = probe or {"reachable": None, "http_status": None, "detail": "mock_or_local_fallback"}
        if endpoint and probe is None:
            probe_payload = probe_http_url(endpoint, timeout_s=3)
        return {
            "component": name,
            "provider": getattr(provider, "name", provider.__class__.__name__),
            "mode": "mock" if is_mock else "real",
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

    @app.get("/api/admin/overview")
    def admin_overview() -> dict[str, Any]:
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
            "config": {
                "project_name": config_payload["config"].get("project_name", ""),
                "llm_provider": config_payload["config"].get("llm", {}).get("provider", ""),
                "asr_provider": config_payload["config"].get("asr", {}).get("provider", ""),
                "tts_provider": config_payload["config"].get("tts", {}).get("provider", ""),
            },
        }

    @app.get("/api/admin/provider-health")
    def admin_provider_health() -> dict[str, Any]:
        return {
            "ok": True,
            "providers": provider_health_snapshot(current_pipeline()),
        }

    @app.get("/api/admin/runs")
    def admin_runs(query: str = "", status: str = "", gate_label: str = "", limit: int = 50) -> dict[str, Any]:
        return {
            "ok": True,
            "stats": store.audit_stats(),
            "runs": store.search_runs(query=query, status=status, gate_label=gate_label, limit=limit),
        }

    @app.post("/api/admin/runs/cleanup")
    def admin_runs_cleanup(payload: RunCleanupPayload) -> dict[str, Any]:
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
    def admin_knowledge(query: str = "", tag: str = "", limit: int = 100) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": store.knowledge_summary(),
            "records": store.list_knowledge(query=query, tag=tag, limit=limit),
        }

    @app.get("/api/admin/knowledge/{record_id}")
    def admin_knowledge_detail(record_id: str) -> dict[str, Any]:
        record = store.get_knowledge(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail={"error": f"knowledge record not found: {record_id}"})
        return {"ok": True, "record": record}

    @app.post("/api/admin/knowledge")
    def admin_knowledge_create(payload: KnowledgePayload) -> dict[str, Any]:
        return store.upsert_knowledge(_payload_to_dict(payload))

    @app.put("/api/admin/knowledge/{record_id}")
    def admin_knowledge_update(record_id: str, payload: KnowledgePayload) -> dict[str, Any]:
        return store.upsert_knowledge(_payload_to_dict(payload), record_id=record_id)

    @app.delete("/api/admin/knowledge/{record_id}")
    def admin_knowledge_delete(record_id: str) -> dict[str, Any]:
        try:
            return store.delete_knowledge(record_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"error": f"knowledge record not found: {record_id}"}) from exc

    @app.post("/api/admin/reindex")
    def admin_reindex() -> dict[str, Any]:
        return {"ok": True, "index": store.sync_knowledge_files()}

    @app.get("/api/admin/evaluations")
    def admin_evaluations() -> dict[str, Any]:
        return {
            "ok": True,
            "datasets": store.list_evaluation_datasets(),
        }

    @app.get("/api/admin/evaluations/{dataset_name}")
    def admin_evaluation_dataset(dataset_name: str, query: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        dataset = store.get_evaluation_dataset(dataset_name, query=query, limit=limit, offset=offset)
        if dataset is None:
            raise HTTPException(status_code=404, detail={"error": f"evaluation dataset not found: {dataset_name}"})
        return {"ok": True, **dataset}

    @app.post("/api/admin/evaluations/reload")
    def admin_evaluations_reload() -> dict[str, Any]:
        return {"ok": True, "reload": store.reload_evaluations()}

    @app.get("/api/admin/config")
    def admin_config() -> dict[str, Any]:
        return {"ok": True, **read_config()}

    @app.post("/api/admin/config")
    def admin_config_save(payload: ConfigPayload) -> dict[str, Any]:
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
    def admin_config_reload() -> dict[str, Any]:
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
    }
    return {
        "config": data,
        "raw_text": raw_text,
        "env_overrides": env_overrides,
        "config_path": str(CONFIG_PATH),
    }
