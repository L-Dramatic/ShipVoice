from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager, contextmanager
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
from .pipeline import PipelineCancelled, VoiceQAPipeline
from .sqlite_store import SQLiteAppStore, utc_now_iso


WEB_ROOT = project_path("web", "static")
CONFIG_PATH = project_path("configs", "pipeline.json")
DEFAULT_ADMIN_PASSWORD = "shipvoice-admin"
DEFAULT_ADMIN_SESSION_TTL_SECONDS = 8 * 60 * 60
PUBLIC_RUN_MODES = {"baseline", "streaming", "rag", "guarded", "full"}
MAX_SESSION_ID_CHARS = 128
MAX_QUESTION_CHARS = 512
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BASE64_CHARS = 12 * 1024 * 1024
MAX_AUDIO_NAME_CHARS = 160
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CONTENT_CHARS = 2000
MAX_HISTORY_TOTAL_CHARS = 8000
MAX_CLIENT_REQUEST_ID_CHARS = 96
_EPHEMERAL_ADMIN_SESSION_SECRET = secrets.token_urlsafe(32)
DEFAULT_RUNTIME_PROFILE = "gpu_lora"
RUNTIME_PROFILE_ORDER = ("gpu_lora", "api_fallback")
RUNTIME_PROFILE_LABELS = {
    "gpu_lora": "GPU LoRA 主模式",
    "api_fallback": "API 备用模式",
}
RUNTIME_PROFILE_KINDS = {
    "gpu_lora": "gpu",
    "api_fallback": "api_fallback",
}


class RunRequest(BaseModel):
    session_id: str = ""
    client_request_id: str = ""
    question: str = ""
    mode: str = "full"
    runtime_profile: str = ""
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


class ClientTimingPayload(BaseModel):
    session_id: str = ""
    client_request_id: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


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


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def int_env(name: str, default: int, *, minimum: int = 1, maximum: int = 3600) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def runtime_max_concurrent_runs() -> int:
    return int_env("SHIPVOICE_MAX_CONCURRENT_RUNS", 2, minimum=1, maximum=32)


def runtime_run_timeout_seconds() -> int:
    return int_env("SHIPVOICE_RUN_TIMEOUT_SECONDS", 240, minimum=5, maximum=3600)


def runtime_queue_wait_seconds() -> float:
    raw_value = os.environ.get("SHIPVOICE_RUN_QUEUE_WAIT_SECONDS", "").strip()
    if not raw_value:
        return 0.05
    try:
        return min(max(float(raw_value), 0.0), 30.0)
    except ValueError:
        return 0.05


def sanitize_limited_text(value: str, *, field_name: str, max_chars: int, allow_empty: bool = True) -> str:
    text = (value or "").strip()
    if not text and not allow_empty:
        raise HTTPException(status_code=422, detail={"error": f"{field_name} is required"})
    if len(text) > max_chars:
        raise HTTPException(
            status_code=413,
            detail={"error": f"{field_name} is too long", "max_chars": max_chars},
        )
    return text


def normalize_session_id(value: str) -> str:
    session_id = sanitize_limited_text(
        value,
        field_name="session_id",
        max_chars=MAX_SESSION_ID_CHARS,
        allow_empty=True,
    )
    if session_id and not all(ch.isalnum() or ch in "-_:" for ch in session_id):
        raise HTTPException(status_code=422, detail={"error": "session_id contains unsupported characters"})
    return session_id


def normalize_client_request_id(value: str) -> str:
    request_id = sanitize_limited_text(
        value,
        field_name="client_request_id",
        max_chars=MAX_CLIENT_REQUEST_ID_CHARS,
        allow_empty=True,
    )
    if request_id and not all(ch.isalnum() or ch in "-_:" for ch in request_id):
        raise HTTPException(status_code=422, detail={"error": "client_request_id contains unsupported characters"})
    return request_id


def normalize_run_mode(value: str) -> str:
    mode = (value or "full").strip().lower()
    if mode not in PUBLIC_RUN_MODES:
        raise HTTPException(
            status_code=422,
            detail={"error": f"unsupported run mode: {mode}", "allowed_modes": sorted(PUBLIC_RUN_MODES)},
        )
    return mode


def normalize_runtime_profile(value: str) -> str:
    profile = (value or os.environ.get("SHIPVOICE_DEFAULT_RUNTIME_PROFILE", DEFAULT_RUNTIME_PROFILE)).strip().lower()
    profile = profile or DEFAULT_RUNTIME_PROFILE
    if profile not in RUNTIME_PROFILE_ORDER:
        raise HTTPException(
            status_code=422,
            detail={"error": f"unsupported runtime profile: {profile}", "allowed_profiles": list(RUNTIME_PROFILE_ORDER)},
        )
    return profile


def sanitize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    total_chars = 0
    for item in history[-MAX_HISTORY_TURNS:]:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role not in {"user", "assistant"}:
            raise HTTPException(status_code=422, detail={"error": f"unsupported history role: {role}"})
        if len(content) > MAX_HISTORY_CONTENT_CHARS:
            raise HTTPException(
                status_code=413,
                detail={"error": "history content is too long", "max_chars": MAX_HISTORY_CONTENT_CHARS},
            )
        total_chars += len(content)
        if total_chars > MAX_HISTORY_TOTAL_CHARS:
            raise HTTPException(
                status_code=413,
                detail={"error": "history is too long", "max_chars": MAX_HISTORY_TOTAL_CHARS},
            )
        sanitized.append({"role": role, "content": content})
    return sanitized


def decode_audio_base64(value: str) -> bytes | None:
    audio_base64 = (value or "").strip()
    if not audio_base64:
        return None
    if len(audio_base64) > MAX_AUDIO_BASE64_CHARS:
        raise HTTPException(
            status_code=413,
            detail={"error": "audio_base64 is too large", "max_bytes": MAX_AUDIO_BYTES},
        )
    try:
        audio_bytes = base64.b64decode(audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"error": f"invalid audio_base64: {exc}"}) from exc
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": "decoded audio is too large", "max_bytes": MAX_AUDIO_BYTES},
        )
    return audio_bytes


def prepare_run_request(request: RunRequest) -> dict[str, Any]:
    session_id = normalize_session_id(request.session_id) or uuid.uuid4().hex[:12]
    client_request_id = normalize_client_request_id(request.client_request_id)
    question = sanitize_limited_text(
        request.question,
        field_name="question",
        max_chars=MAX_QUESTION_CHARS,
        allow_empty=True,
    )
    mode = normalize_run_mode(request.mode)
    runtime_profile = normalize_runtime_profile(request.runtime_profile)
    audio_name = sanitize_limited_text(
        request.audio_name,
        field_name="audio_name",
        max_chars=MAX_AUDIO_NAME_CHARS,
        allow_empty=True,
    )
    audio_bytes = decode_audio_base64(request.audio_base64)
    history = sanitize_history(request.history)
    if not question and not audio_bytes:
        raise HTTPException(status_code=400, detail={"error": "missing question"})
    return {
        "session_id": session_id,
        "client_request_id": client_request_id,
        "question": question,
        "mode": mode,
        "runtime_profile": runtime_profile,
        "audio_name": audio_name,
        "audio_bytes": audio_bytes,
        "history": history,
    }


def result_to_payload(run_id: str, session_id: str, created_at: str, result) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "session_id": session_id,
        "created_at": created_at,
        "mode": result.metrics.mode,
        "runtime_profile": result.provider_status.get("runtime_profile", DEFAULT_RUNTIME_PROFILE),
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


def cached_or_summary_payload(item: dict[str, Any], cached_result: dict[str, Any] | None = None) -> dict[str, Any]:
    if cached_result:
        return {
            "ok": True,
            "status": "completed",
            "cached": True,
            "result": cached_result,
        }
    return {
        "ok": True,
        "status": item.get("status", "unknown"),
        "cached": False,
        "summary": item,
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


def service_health_url(endpoint: str) -> str:
    normalized = (endpoint or "").rstrip("/")
    for suffix in ("/asr", "/tts", "/v1/chat/completions", "/chat/completions"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)] + "/health"
    return normalized + "/health" if normalized else ""


def openai_health_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized.removesuffix("/chat/completions")
    if normalized.endswith("/v1"):
        normalized = normalized.removesuffix("/v1")
    return normalized + "/health" if normalized else ""


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


def probe_openai_health(base_url: str, api_key: str = "", timeout_s: int = 5) -> dict[str, Any]:
    url = openai_health_url(base_url)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        health = payload if isinstance(payload, dict) else {}
        return {
            "health_url": url,
            "health_reachable": True,
            "health_http_status": getattr(response, "status", 200),
            "health": health,
            "adapter_loaded": health.get("adapter_loaded"),
            "adapter_sha256": health.get("adapter_sha256", ""),
            "adapter_hash_algorithm": health.get("adapter_hash_algorithm", ""),
        }
    except urllib.error.HTTPError as exc:
        return {
            "health_url": url,
            "health_reachable": True,
            "health_http_status": exc.code,
            "health": {},
            "adapter_loaded": None,
            "adapter_sha256": "",
            "adapter_hash_algorithm": "",
        }
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "health_url": url,
            "health_reachable": False,
            "health_http_status": None,
            "health": {"error": str(exc)},
            "adapter_loaded": None,
            "adapter_sha256": "",
            "adapter_hash_algorithm": "",
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
        llm_probe.update(probe_openai_health(getattr(llm, "base_url", llm_endpoint), api_key=llm_api_key, timeout_s=5))
    asr_probe = probe_http_url(service_health_url(asr_endpoint), timeout_s=5) if asr_endpoint else None
    tts_probe = probe_http_url(service_health_url(tts_endpoint), timeout_s=5) if tts_endpoint else None
    return {
        "asr": item("ASR", asr, asr_endpoint, probe=asr_probe),
        "llm": item("LLM", llm, llm_endpoint, extra={"model": llm_model}, probe=llm_probe),
        "tts": item("TTS", tts, tts_endpoint, probe=tts_probe),
        "runtime_profile": getattr(pipeline, "runtime_profile_id", DEFAULT_RUNTIME_PROFILE),
        "runtime_profile_label": getattr(pipeline, "runtime_profile_label", RUNTIME_PROFILE_LABELS[DEFAULT_RUNTIME_PROFILE]),
        "runtime_profile_kind": getattr(pipeline, "runtime_profile_kind", RUNTIME_PROFILE_KINDS[DEFAULT_RUNTIME_PROFILE]),
        "require_lora": bool(getattr(pipeline, "require_lora", truthy_env("SHIPVOICE_REQUIRE_LORA"))),
        "expected_adapter_sha256": str(getattr(pipeline, "expected_adapter_sha256", os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""))).strip(),
        "updated_at": utc_now_iso(),
    }


def provider_ready_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    components: dict[str, Any] = {}
    require_lora = bool(snapshot.get("require_lora", truthy_env("SHIPVOICE_REQUIRE_LORA")))
    expected_adapter_sha = str(
        snapshot.get("expected_adapter_sha256", os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""))
    ).strip().lower()
    for key in ("asr", "llm", "tts"):
        item = dict(snapshot.get(key, {}))
        reachable = item.get("reachable")
        status = item.get("http_status")
        ready = bool(reachable is True and isinstance(status, int) and 200 <= status < 300)
        if key == "llm" and item.get("model"):
            ready = ready and bool(item.get("model_available"))
            if require_lora:
                ready = ready and item.get("health_reachable") is True and item.get("adapter_loaded") is True
            if expected_adapter_sha:
                actual_adapter_sha = str(item.get("adapter_sha256", "")).strip().lower()
                ready = ready and actual_adapter_sha == expected_adapter_sha
        if not item.get("endpoint"):
            ready = item.get("reachable") is None
        item["ready"] = ready
        if not ready:
            if key == "llm" and item.get("reachable") and not item.get("model_available"):
                item["ready_reason"] = "configured model is not listed by the provider"
            elif key == "llm" and require_lora and item.get("adapter_loaded") is not True:
                item["ready_reason"] = "required LoRA adapter is not confirmed by provider health"
            elif key == "llm" and expected_adapter_sha and str(item.get("adapter_sha256", "")).strip().lower() != expected_adapter_sha:
                item["ready_reason"] = "LoRA adapter SHA does not match SHIPVOICE_LORA_ADAPTER_SHA256"
            elif item.get("reachable") is False:
                item["ready_reason"] = "provider endpoint is not reachable"
            elif isinstance(status, int) and not (200 <= status < 300):
                item["ready_reason"] = f"provider health probe returned HTTP {status}"
            else:
                item["ready_reason"] = "provider readiness could not be confirmed"
        components[key] = item
    ready = all(item.get("ready") for item in components.values())
    return {
        "ready": ready,
        "runtime_profile": snapshot.get("runtime_profile", DEFAULT_RUNTIME_PROFILE),
        "runtime_profile_label": snapshot.get("runtime_profile_label", RUNTIME_PROFILE_LABELS[DEFAULT_RUNTIME_PROFILE]),
        "runtime_profile_kind": snapshot.get("runtime_profile_kind", RUNTIME_PROFILE_KINDS[DEFAULT_RUNTIME_PROFILE]),
        "require_lora": require_lora,
        "components": components,
        "updated_at": snapshot.get("updated_at", utc_now_iso()),
    }


@contextmanager
def temporary_env(overrides: dict[str, str | None]):
    previous = {key: os.environ.get(key) for key in overrides}
    for key, value in overrides.items():
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


def fallback_env_overrides() -> dict[str, str | None]:
    asr_provider = os.environ.get("SHIPVOICE_FALLBACK_ASR_PROVIDER", "text_input").strip() or "text_input"
    tts_provider = os.environ.get("SHIPVOICE_FALLBACK_TTS_PROVIDER", "http_json").strip() or "http_json"
    return {
        "SHIPVOICE_ASR_PROVIDER": asr_provider,
        "SHIPVOICE_ASR_ENDPOINT": os.environ.get("SHIPVOICE_FALLBACK_ASR_ENDPOINT", "").strip(),
        "SHIPVOICE_LLM_PROVIDER": os.environ.get("SHIPVOICE_FALLBACK_LLM_PROVIDER", "openai_compatible").strip() or "openai_compatible",
        "SHIPVOICE_OPENAI_BASE_URL": os.environ.get("SHIPVOICE_FALLBACK_OPENAI_BASE_URL", "").strip(),
        "SHIPVOICE_LLM_MODEL": os.environ.get("SHIPVOICE_FALLBACK_LLM_MODEL", "").strip(),
        "SHIPVOICE_LLM_API_KEY_ENV": "SHIPVOICE_FALLBACK_OPENAI_API_KEY",
        "SHIPVOICE_LLM_THINKING": os.environ.get("SHIPVOICE_FALLBACK_LLM_THINKING", "").strip() or None,
        "SHIPVOICE_LLM_MAX_TOKENS": os.environ.get("SHIPVOICE_FALLBACK_LLM_MAX_TOKENS", "").strip() or None,
        "SHIPVOICE_REQUIRE_LORA": "0",
        "SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING": None,
        "SHIPVOICE_TTS_PROVIDER": tts_provider,
        "SHIPVOICE_TTS_ENDPOINT": os.environ.get("SHIPVOICE_FALLBACK_TTS_ENDPOINT", "").strip(),
        "SHIPVOICE_TTS_VOICE": os.environ.get("SHIPVOICE_FALLBACK_TTS_VOICE", "zh-CN-XiaoxiaoNeural").strip() or "zh-CN-XiaoxiaoNeural",
    }


def profile_metadata(profile: str) -> dict[str, str | bool]:
    return {
        "runtime_profile_id": profile,
        "runtime_profile_label": RUNTIME_PROFILE_LABELS[profile],
        "runtime_profile_kind": RUNTIME_PROFILE_KINDS[profile],
        "require_lora": profile == "gpu_lora" and truthy_env("SHIPVOICE_REQUIRE_LORA"),
        "expected_adapter_sha256": os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", "").strip() if profile == "gpu_lora" else "",
    }


def apply_profile_metadata(pipeline: VoiceQAPipeline, profile: str) -> VoiceQAPipeline:
    for key, value in profile_metadata(profile).items():
        setattr(pipeline, key, value)
    return pipeline


def build_runtime_profile_pipeline(profile: str) -> VoiceQAPipeline:
    profile = normalize_runtime_profile(profile)
    if profile == "gpu_lora":
        return apply_profile_metadata(VoiceQAPipeline(), profile)
    with temporary_env(fallback_env_overrides()):
        return apply_profile_metadata(VoiceQAPipeline(), profile)


def write_config_atomically(raw_text: str) -> tuple[dict[str, Any], VoiceQAPipeline, str]:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail={"error": f"invalid json: {exc}"}) from exc
    formatted = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_path = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.{uuid.uuid4().hex}.tmp")
    backup_path = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.{time.strftime('%Y%m%d%H%M%S')}.bak")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(formatted)
            handle.flush()
            os.fsync(handle.fileno())
        candidate_config = load_config(temp_path)
        candidate_pipeline = VoiceQAPipeline(candidate_config)
        if CONFIG_PATH.exists():
            shutil.copy2(CONFIG_PATH, backup_path)
        os.replace(temp_path, CONFIG_PATH)
        return data, candidate_pipeline, str(backup_path) if backup_path.exists() else ""
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error": f"config validation failed: {exc}"}) from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


def admin_password() -> str:
    configured = os.environ.get("SHIPVOICE_ADMIN_PASSWORD", "").strip()
    if configured:
        return configured
    if truthy_env("SHIPVOICE_ALLOW_DEFAULT_ADMIN_PASSWORD"):
        return DEFAULT_ADMIN_PASSWORD
    raise RuntimeError("SHIPVOICE_ADMIN_PASSWORD must be set before admin login is enabled.")


def admin_auth_mode() -> str:
    if os.environ.get("SHIPVOICE_ADMIN_PASSWORD", "").strip():
        return "configured_password"
    if truthy_env("SHIPVOICE_ALLOW_DEFAULT_ADMIN_PASSWORD"):
        return "default_password_explicitly_allowed"
    return "missing_password"


def admin_session_ttl_seconds() -> int:
    raw_value = os.environ.get("SHIPVOICE_ADMIN_TOKEN_TTL_SECONDS", "").strip()
    if raw_value.isdigit():
        return max(300, int(raw_value))
    return DEFAULT_ADMIN_SESSION_TTL_SECONDS


def admin_session_secret() -> str:
    configured = os.environ.get("SHIPVOICE_ADMIN_SESSION_SECRET", "").strip()
    if configured:
        return configured
    if truthy_env("SHIPVOICE_ALLOW_PATH_DERIVED_ADMIN_SECRET"):
        return f"shipvoice-admin-secret:{CONFIG_PATH}:{WEB_ROOT}"
    return _EPHEMERAL_ADMIN_SESSION_SECRET


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
    default_pipeline = build_runtime_profile_pipeline(DEFAULT_RUNTIME_PROFILE)
    runtime: dict[str, Any] = {
        "pipeline": default_pipeline,
        "pipelines": {DEFAULT_RUNTIME_PROFILE: default_pipeline},
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            for pipeline in list(runtime.get("pipelines", {}).values()):
                pipeline.close()

    app = FastAPI(title="ShipVoice API", version="0.2.0", lifespan=lifespan)
    store = SQLiteAppStore()
    run_semaphore = asyncio.Semaphore(runtime_max_concurrent_runs())
    session_locks: dict[str, asyncio.Lock] = {}
    session_locks_guard = threading.Lock()
    run_cache_lock = threading.Lock()
    run_results: dict[str, dict[str, Any]] = {}
    run_statuses: dict[str, dict[str, Any]] = {}
    run_cancellations: dict[str, threading.Event] = {}

    def current_pipeline(profile: str = "") -> VoiceQAPipeline:
        normalized_profile = normalize_runtime_profile(profile)
        pipelines: dict[str, VoiceQAPipeline] = runtime["pipelines"]
        pipeline = pipelines.get(normalized_profile)
        if pipeline is None:
            try:
                pipeline = build_runtime_profile_pipeline(normalized_profile)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": f"runtime profile {normalized_profile} is not available: {exc}",
                        "runtime_profile": normalized_profile,
                    },
                ) from exc
            pipelines[normalized_profile] = pipeline
        return pipeline

    def replace_pipeline(pipeline: VoiceQAPipeline) -> VoiceQAPipeline:
        pipeline = apply_profile_metadata(pipeline, DEFAULT_RUNTIME_PROFILE)
        previous = runtime.get("pipeline")
        runtime["pipeline"] = pipeline
        runtime["pipelines"][DEFAULT_RUNTIME_PROFILE] = pipeline
        if previous is not None and previous is not pipeline:
            previous.close()
        return pipeline

    def session_lock_for(session_id: str) -> asyncio.Lock:
        with session_locks_guard:
            lock = session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                session_locks[session_id] = lock
            return lock

    def reload_pipeline_from_disk() -> VoiceQAPipeline:
        load_config(CONFIG_PATH)
        fallback = runtime["pipelines"].pop("api_fallback", None)
        if fallback is not None:
            fallback.close()
        return replace_pipeline(VoiceQAPipeline())

    def public_knowledge_summary() -> dict[str, Any]:
        summary = store.knowledge_summary()
        return {
            "record_count": summary.get("record_count", 0),
            "approved_count": summary.get("approved_count", 0),
            "pending_review_count": summary.get("pending_review_count", 0),
            "status_counts": summary.get("status_counts", {}),
            "top_tags": summary.get("top_tags", []),
        }

    def runtime_profile_report(profile: str, *, probe: bool = True) -> dict[str, Any]:
        profile = normalize_runtime_profile(profile)
        base = {
            "id": profile,
            "label": RUNTIME_PROFILE_LABELS[profile],
            "kind": RUNTIME_PROFILE_KINDS[profile],
            "default": profile == DEFAULT_RUNTIME_PROFILE,
        }
        try:
            pipeline = current_pipeline(profile)
            has_real_provider_shape = all(hasattr(pipeline, attr) for attr in ("asr", "llm", "tts"))
            if not probe:
                return {
                    **base,
                    "available": True,
                    "ready": None,
                    "providers": {
                        "asr": getattr(getattr(pipeline, "asr", None), "name", "unprobed"),
                        "llm": getattr(getattr(pipeline, "llm", None), "name", pipeline.__class__.__name__),
                        "tts": getattr(getattr(pipeline, "tts", None), "name", "unprobed"),
                    },
                }
            if not has_real_provider_shape:
                return {
                    **base,
                    "available": True,
                    "ready": True,
                    "components": {},
                    "updated_at": utc_now_iso(),
                }
            report = provider_ready_report(provider_health_snapshot(pipeline))
            return {
                **base,
                "available": True,
                **report,
            }
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
            return {
                **base,
                "available": False,
                "ready": False,
                "error": detail.get("error", str(detail)),
                "components": {},
                "updated_at": utc_now_iso(),
            }

    def runtime_profiles_report(*, probe: bool = True) -> list[dict[str, Any]]:
        return [runtime_profile_report(profile, probe=probe) for profile in RUNTIME_PROFILE_ORDER]

    def require_ready_runtime_profile(profile: str) -> VoiceQAPipeline:
        pipeline = current_pipeline(profile)
        if not all(hasattr(pipeline, attr) for attr in ("asr", "llm", "tts")):
            return pipeline
        report = provider_ready_report(provider_health_snapshot(pipeline))
        if not report["ready"]:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": f"runtime profile {profile} is not ready",
                    "runtime_profile": profile,
                    "components": report["components"],
                },
            )
        return pipeline

    def reserve_run(run_id: str, session_id: str, created_at: str, mode: str) -> dict[str, Any] | None:
        with run_cache_lock:
            if run_id in run_results:
                if run_results[run_id].get("session_id") != session_id:
                    return {"state": "forbidden"}
                return {"state": "completed", "result": run_results[run_id]}
            existing = run_statuses.get(run_id)
            if existing and existing.get("session_id") != session_id:
                return {"state": "forbidden"}
            if existing and existing.get("status") == "running":
                return {"state": "running", **existing}
            run_statuses[run_id] = {
                "status": "running",
                "session_id": session_id,
                "created_at": created_at,
                "mode": mode,
            }
        return None

    def complete_run(run_id: str, payload: dict[str, Any]) -> None:
        with run_cache_lock:
            run_results[run_id] = payload
            run_statuses[run_id] = {
                "status": "completed",
                "session_id": payload.get("session_id", ""),
                "created_at": payload.get("created_at", ""),
                "mode": payload.get("mode", ""),
            }

    def fail_run(run_id: str, session_id: str, created_at: str, mode: str, error: str) -> None:
        with run_cache_lock:
            run_statuses[run_id] = {
                "status": "error",
                "session_id": session_id,
                "created_at": created_at,
                "mode": mode,
                "error": error,
            }

    def cancel_run(run_id: str, session_id: str, created_at: str, mode: str) -> None:
        with run_cache_lock:
            run_statuses[run_id] = {
                "status": "cancelled",
                "session_id": session_id,
                "created_at": created_at,
                "mode": mode,
                "error": "run cancelled",
            }

    def register_cancellation(run_id: str, cancel_event: threading.Event) -> None:
        with run_cache_lock:
            run_cancellations[run_id] = cancel_event

    def unregister_cancellation(run_id: str) -> None:
        with run_cache_lock:
            run_cancellations.pop(run_id, None)

    def request_cancellation(run_id: str, session_id: str = "") -> bool:
        normalized_run_id = normalize_client_request_id(run_id)
        normalized_session_id = normalize_session_id(session_id) if session_id else ""
        with run_cache_lock:
            status = run_statuses.get(normalized_run_id, {})
            cached = run_results.get(normalized_run_id)
            if cached:
                return False
            if normalized_session_id and status and status.get("session_id") != normalized_session_id:
                raise HTTPException(status_code=404, detail={"error": "run not found"})
            event = run_cancellations.get(normalized_run_id)
            if event is None:
                return False
            event.set()
            if status:
                status["status"] = "cancelling"
                status["error"] = "cancel requested"
            return True

    async def run_pipeline_with_limits(
        pipeline: VoiceQAPipeline,
        *args: Any,
        session_id: str = "",
        cancel_event: threading.Event | None = None,
        **kwargs: Any,
    ) -> Any:
        session_lock = session_lock_for(session_id) if session_id else None
        session_acquired = False
        if session_lock is not None:
            try:
                await asyncio.wait_for(session_lock.acquire(), timeout=runtime_queue_wait_seconds())
                session_acquired = True
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "session already has a run in progress",
                        "session_id": session_id,
                    },
                ) from exc
        global_acquired = False
        try:
            try:
                await asyncio.wait_for(run_semaphore.acquire(), timeout=runtime_queue_wait_seconds())
                global_acquired = True
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "server is busy",
                        "max_concurrent_runs": runtime_max_concurrent_runs(),
                    },
                ) from exc
            return await asyncio.wait_for(
                pipeline.run_once(*args, cancel_event=cancel_event, **kwargs),
                timeout=runtime_run_timeout_seconds(),
            )
        except PipelineCancelled as exc:
            raise HTTPException(status_code=499, detail={"error": str(exc) or "run cancelled"}) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "run timed out",
                    "timeout_seconds": runtime_run_timeout_seconds(),
                },
            ) from exc
        finally:
            if global_acquired:
                run_semaphore.release()
            if session_acquired and session_lock is not None:
                session_lock.release()

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
        pipeline = current_pipeline(DEFAULT_RUNTIME_PROFILE)
        return {
            "ok": True,
            "service": "shipvoice-fastapi",
            "default_runtime_profile": DEFAULT_RUNTIME_PROFILE,
            "runtime_profiles": runtime_profiles_report(probe=False),
            "providers": {
                "asr": getattr(getattr(pipeline, "asr", None), "name", "unprobed"),
                "llm": getattr(getattr(pipeline, "llm", None), "name", pipeline.__class__.__name__),
                "tts": getattr(getattr(pipeline, "tts", None), "name", "unprobed"),
            },
            "audit": {
                "recent_runs": store.audit_stats()["total_runs"],
            },
            "runtime": {
                "env_file": os.environ.get("SHIPVOICE_ENV_FILE", ""),
                "max_concurrent_runs": runtime_max_concurrent_runs(),
                "run_timeout_seconds": runtime_run_timeout_seconds(),
            },
            "knowledge": public_knowledge_summary(),
        }

    @app.get("/api/live")
    def live() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "shipvoice-fastapi",
            "status": "live",
            "updated_at": utc_now_iso(),
        }

    @app.get("/api/ready")
    def ready(runtime_profile: str = "") -> JSONResponse:
        profile = normalize_runtime_profile(runtime_profile)
        snapshot = provider_health_snapshot(current_pipeline(profile))
        report = provider_ready_report(snapshot)
        return JSONResponse(
            status_code=200 if report["ready"] else 503,
            content={
                "ok": bool(report["ready"]),
                "service": "shipvoice-fastapi",
                "default_runtime_profile": DEFAULT_RUNTIME_PROFILE,
                "runtime_profiles": runtime_profiles_report(probe=True),
                **report,
            },
        )

    @app.get("/api/sessions")
    def sessions(request: Request, session_id: str = "") -> dict[str, Any]:
        normalized_session_id = normalize_session_id(session_id)
        if normalized_session_id:
            runs = store.session_runs(normalized_session_id, limit=12)
            session_summaries: list[dict[str, Any]] = []
        else:
            require_admin(request)
            runs = store.recent_runs(limit=12)
            session_summaries = store.session_summaries(limit=12)
        return {
            "ok": True,
            "current_session_id": normalized_session_id,
            "sessions": session_summaries,
            "runs": runs,
        }

    @app.post("/api/run")
    async def run_question(request: RunRequest) -> dict[str, Any]:
        pipeline: VoiceQAPipeline | None = None
        run_id = uuid.uuid4().hex[:12]
        created_at = utc_now_iso()
        session_id = request.session_id.strip() or uuid.uuid4().hex[:12]
        question = request.question.strip()
        mode = request.mode
        runtime_profile = normalize_runtime_profile(request.runtime_profile)
        audio_name = request.audio_name.strip()
        transcript = ""
        reserved = False
        cancel_event = threading.Event()
        try:
            prepared = prepare_run_request(request)
            session_id = prepared["session_id"]
            run_id = prepared["client_request_id"] or run_id
            question = prepared["question"]
            mode = prepared["mode"]
            runtime_profile = prepared["runtime_profile"]
            audio_name = prepared["audio_name"]
            pipeline = require_ready_runtime_profile(runtime_profile)
            existing = reserve_run(run_id, session_id, created_at, mode)
            if existing:
                if existing["state"] == "forbidden":
                    raise HTTPException(status_code=404, detail={"error": "run not found"})
                if existing["state"] == "completed":
                    payload = dict(existing["result"])
                    payload["idempotent_replay"] = True
                    return payload
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "request is already running",
                        "run_id": run_id,
                        "session_id": session_id,
                        "created_at": existing.get("created_at", created_at),
                    },
                )
            reserved = True
            register_cancellation(run_id, cancel_event)

            result = await run_pipeline_with_limits(
                pipeline,
                question,
                session_id=session_id,
                cancel_event=cancel_event,
                audio_bytes=prepared["audio_bytes"],
                audio_name=audio_name,
                history=prepared["history"],
                mode=mode,
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
            payload = result_to_payload(run_id, session_id, created_at, result)
            payload["runtime_profile"] = runtime_profile
            complete_run(run_id, payload)
            return payload
        except HTTPException as exc:
            if reserved and session_id:
                detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
                message = str(detail.get("error", exc.detail))
                if exc.status_code == 499:
                    cancel_run(run_id, session_id, created_at, mode)
                else:
                    fail_run(run_id, session_id, created_at, mode, message)
            if isinstance(exc.detail, dict) and exc.detail.get("error") == "missing question":
                store.insert_audit(
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
                exc.detail = {"error": "missing question", "run_id": run_id, "session_id": session_id}
            raise
        except Exception as exc:
            if reserved:
                fail_run(run_id, session_id, created_at, mode, str(exc))
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
            raise HTTPException(
                status_code=500,
                detail={
                    "error": str(exc),
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                },
            ) from exc
        finally:
            if reserved:
                unregister_cancellation(run_id)

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: str, session_id: str = "") -> dict[str, Any]:
        normalized_run_id = normalize_client_request_id(run_id)
        normalized_session_id = normalize_session_id(session_id)
        if not normalized_session_id:
            raise HTTPException(status_code=422, detail={"error": "session_id is required"})
        with run_cache_lock:
            cached = run_results.get(normalized_run_id)
            status = dict(run_statuses.get(normalized_run_id, {}))
        if cached:
            if cached.get("session_id") != normalized_session_id:
                raise HTTPException(status_code=404, detail={"error": "run not found"})
            return cached_or_summary_payload({}, cached_result=cached)
        if status:
            if status.get("session_id") != normalized_session_id:
                raise HTTPException(status_code=404, detail={"error": "run not found"})
            return {"ok": True, "status": status.get("status", "unknown"), "run": status}
        item = store.get_run(normalized_run_id)
        if item and item.get("session_id") == normalized_session_id:
            return cached_or_summary_payload(item)
        raise HTTPException(status_code=404, detail={"error": "run not found"})

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_running_run(run_id: str, payload: ClientTimingPayload) -> dict[str, Any]:
        normalized_run_id = normalize_client_request_id(run_id)
        normalized_session_id = normalize_session_id(payload.session_id)
        if not normalized_session_id:
            raise HTTPException(status_code=422, detail={"error": "session_id is required"})
        requested = request_cancellation(normalized_run_id, normalized_session_id)
        return {
            "ok": True,
            "run_id": normalized_run_id,
            "session_id": normalized_session_id,
            "cancel_requested": requested,
            "status": "cancelling" if requested else "not_running",
        }

    @app.post("/api/runs/{run_id}/client-timing")
    def update_client_timing(run_id: str, payload: ClientTimingPayload) -> dict[str, Any]:
        normalized_run_id = normalize_client_request_id(run_id)
        normalized_session_id = normalize_session_id(payload.session_id)
        if not normalized_session_id:
            raise HTTPException(status_code=422, detail={"error": "session_id is required"})
        run = store.get_run(normalized_run_id)
        with run_cache_lock:
            cached = run_results.get(normalized_run_id)
        cached_session_id = str(cached.get("session_id", "")) if cached else ""
        if run is None and not cached:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        if run is not None and run.get("session_id") != normalized_session_id:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        if cached and cached_session_id != normalized_session_id:
            raise HTTPException(status_code=404, detail={"error": "run not found"})
        sanitized: dict[str, Any] = {}
        numeric_fields = {
            "client_audio_payload_received_ms",
            "client_audio_onplaying_ms",
            "client_request_to_playing_ms",
            "client_recording_stop_to_request_ms",
            "client_recording_stop_to_playing_ms",
        }
        for key in numeric_fields:
            value = payload.metrics.get(key)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or value < 0 or value > 3_600_000:
                raise HTTPException(status_code=422, detail={"error": f"invalid client timing field: {key}"})
            sanitized[key] = int(round(value))
        if payload.metrics.get("client_timing_source"):
            sanitized["client_timing_source"] = str(payload.metrics["client_timing_source"])[:80]
        if not sanitized:
            raise HTTPException(status_code=422, detail={"error": "no valid client timing metrics supplied"})
        updated = store.merge_run_metrics(normalized_run_id, sanitized) if run is not None else None
        with run_cache_lock:
            if normalized_run_id in run_results:
                run_results[normalized_run_id].setdefault("metrics", {}).update(sanitized)
        return {"ok": True, "run_id": normalized_run_id, "metrics": sanitized, "run": updated}

    @app.get("/api/admin/auth/status")
    def admin_auth_status() -> dict[str, Any]:
        return {
            "ok": True,
            "auth": {
                "mode": admin_auth_mode(),
                "token_ttl_seconds": admin_session_ttl_seconds(),
                "session_secret": "configured"
                if os.environ.get("SHIPVOICE_ADMIN_SESSION_SECRET", "").strip()
                else "ephemeral_process",
            },
        }

    @app.post("/api/admin/auth/login")
    def admin_auth_login(payload: AdminLoginPayload) -> dict[str, Any]:
        try:
            expected_password = admin_password()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc
        if not hmac.compare_digest(payload.password, expected_password):
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
        data, pipeline, backup_path = write_config_atomically(payload.raw_text)
        replace_pipeline(pipeline)
        return {
            "ok": True,
            "config": data,
            "backup_path": backup_path,
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
        pipeline: VoiceQAPipeline | None = None
        send_lock = asyncio.Lock()
        run_id = uuid.uuid4().hex[:12]
        created_at = utc_now_iso()
        session_id = ""
        question = ""
        transcript = ""
        audio_name = ""
        mode = "full"
        runtime_profile = DEFAULT_RUNTIME_PROFILE
        reserved = False
        cancel_event = threading.Event()
        cancel_listener: asyncio.Task | None = None
        try:
            raw_payload = await websocket.receive_json()
            request = RunRequest(**raw_payload)
            prepared = prepare_run_request(request)
            session_id = prepared["session_id"]
            run_id = prepared["client_request_id"] or run_id
            question = prepared["question"]
            audio_name = prepared["audio_name"]
            mode = prepared["mode"]
            runtime_profile = prepared["runtime_profile"]
            pipeline = require_ready_runtime_profile(runtime_profile)
            existing = reserve_run(run_id, session_id, created_at, mode)
            if existing:
                if existing["state"] == "forbidden":
                    await websocket.send_json(
                        {
                            "type": "error",
                            "error": "run not found",
                            "run_id": run_id,
                            "session_id": session_id,
                            "created_at": created_at,
                        }
                    )
                    await websocket.close(code=1008)
                    return
                if existing["state"] == "completed":
                    await websocket.send_json(
                        {
                            "type": "accepted",
                            "run_id": run_id,
                            "session_id": session_id,
                            "created_at": existing["result"].get("created_at", created_at),
                            "mode": existing["result"].get("mode", mode),
                            "idempotent_replay": True,
                        }
                    )
                    await websocket.send_json({"type": "result", "result": existing["result"]})
                    await websocket.close(code=1000)
                    return
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "request is already running",
                        "run_id": run_id,
                        "session_id": session_id,
                        "created_at": existing.get("created_at", created_at),
                    }
                )
                await websocket.close(code=1013)
                return
            reserved = True
            register_cancellation(run_id, cancel_event)
            await websocket.send_json(
                {
                    "type": "accepted",
                    "run_id": run_id,
                    "session_id": session_id,
                    "created_at": created_at,
                    "mode": mode,
                    "runtime_profile": runtime_profile,
                }
            )

            async def listen_for_cancel() -> None:
                try:
                    while True:
                        payload = await websocket.receive_json()
                        if payload.get("type") == "cancel":
                            request_cancellation(run_id, session_id)
                            return
                except WebSocketDisconnect:
                    cancel_event.set()
                except RuntimeError:
                    cancel_event.set()

            cancel_listener = asyncio.create_task(listen_for_cancel())

            async def send_ws_payload(payload: dict[str, Any]) -> None:
                async with send_lock:
                    await websocket.send_json(payload)

            async def forward_event(event) -> None:
                try:
                    await send_ws_payload({"type": "event", "event": event.to_dict()})
                except (RuntimeError, WebSocketDisconnect):
                    return

            async def forward_audio_chunk(chunk: dict[str, object]) -> None:
                try:
                    await send_ws_payload(
                        {
                            "type": "audio_chunk",
                            "run_id": run_id,
                            "session_id": session_id,
                            "created_at": created_at,
                            "chunk": chunk,
                        }
                    )
                except (RuntimeError, WebSocketDisconnect):
                    return

            result = await run_pipeline_with_limits(
                pipeline,
                question,
                session_id=session_id,
                cancel_event=cancel_event,
                audio_bytes=prepared["audio_bytes"],
                audio_name=audio_name,
                history=prepared["history"],
                mode=mode,
                on_event=forward_event,
                on_audio_chunk=forward_audio_chunk,
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
            payload = result_to_payload(run_id, session_id, created_at, result)
            payload["runtime_profile"] = runtime_profile
            complete_run(run_id, payload)
            try:
                await websocket.send_json({"type": "result", "result": payload})
                await websocket.close(code=1000)
            except (RuntimeError, WebSocketDisconnect):
                return
        except WebSocketDisconnect:
            if reserved:
                cancel_event.set()
            return
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
            message = str(detail.get("error", "request rejected"))
            if reserved and session_id:
                if exc.status_code == 499:
                    cancel_run(run_id, session_id, created_at, mode)
                else:
                    fail_run(run_id, session_id, created_at, mode, message)
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
                        gate_label="bad_request",
                        answer_preview="",
                        providers={},
                        metrics={},
                        error=message,
                        evidence_titles=[],
                        audio_name=audio_name,
                    )
                )
            try:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": message,
                        "run_id": run_id,
                        "session_id": session_id,
                        "created_at": created_at,
                    }
                )
                await websocket.close(code=1008)
            except RuntimeError:
                pass
        except Exception as exc:
            if reserved and session_id:
                fail_run(run_id, session_id, created_at, mode, str(exc))
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
        finally:
            if cancel_listener is not None:
                cancel_listener.cancel()
            if reserved:
                unregister_cancellation(run_id)

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
