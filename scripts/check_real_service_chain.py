from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402
from shipvoice.pipeline import VoiceQAPipeline  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60, headers: dict[str, str] | None = None) -> dict:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def openai_models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized.removesuffix("/chat/completions") + "/models"
    if normalized.endswith("/v1"):
        return normalized + "/models"
    return normalized + "/v1/models"


def openai_health_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized.removesuffix("/chat/completions")
    if normalized.endswith("/v1"):
        normalized = normalized.removesuffix("/v1")
    return normalized + "/health"


def llm_health_check(
    base_url: str,
    *,
    api_key: str = "",
    required_model_substring: str = "",
    require_lora: bool = False,
    required_adapter_sha256: str = "",
) -> dict:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = openai_models_url(base_url)
    payload = http_json("GET", url, timeout=30, headers=headers)
    models = payload.get("data", []) if isinstance(payload, dict) else []
    model_ids = [str(item.get("id", "")) for item in models if isinstance(item, dict)]
    if required_model_substring and not any(required_model_substring in model_id for model_id in model_ids):
        raise SystemExit(
            f"LLM model check failed: expected a model containing {required_model_substring!r}, got {model_ids}"
        )

    health_payload: dict = {}
    health_url = openai_health_url(base_url)
    try:
        health_payload = http_json("GET", health_url, timeout=30, headers=headers)
    except Exception as exc:
        if require_lora:
            raise SystemExit(f"LoRA health check failed at {health_url}: {exc}") from exc
        health_payload = {"available": False, "error": str(exc)}

    if require_lora:
        if not isinstance(health_payload, dict) or health_payload.get("adapter_loaded") is not True:
            raise SystemExit(f"LoRA adapter is not confirmed by {health_url}: {health_payload}")
    if required_adapter_sha256:
        actual_sha = str(health_payload.get("adapter_sha256", "")).strip().lower()
        expected_sha = required_adapter_sha256.strip().lower()
        if actual_sha != expected_sha:
            raise SystemExit(
                f"LoRA adapter SHA check failed at {health_url}: expected {expected_sha}, got {actual_sha or '<missing>'}"
            )

    return {
        "ok": True,
        "probe_url": url,
        "models": model_ids[:10],
        "health_url": health_url,
        "health": health_payload,
    }


async def run_pipeline(question: str, audio_path: Path, mode: str) -> dict:
    audio_bytes = audio_path.read_bytes()
    pipeline = VoiceQAPipeline()
    result = await pipeline.run_once(
        question,
        audio_bytes=audio_bytes,
        audio_name=audio_path.name,
        mode=mode,
    )
    audio_output = result.audio_output.__dict__.copy()
    audio_base64 = str(audio_output.get("audio_base64", ""))
    if audio_base64:
        audio_output["audio_base64_len"] = len(audio_base64)
        audio_output["audio_base64_sha256"] = hashlib.sha256(audio_base64.encode("ascii")).hexdigest()
        audio_output["audio_base64"] = "<redacted>"
    audio_segments = audio_output.get("audio_segments")
    if isinstance(audio_segments, list) and audio_segments:
        segment_values = [str(item) for item in audio_segments]
        audio_output["audio_segments_count"] = len(segment_values)
        audio_output["audio_segments_base64_lens"] = [len(item) for item in segment_values]
        audio_output["audio_segments_sha256"] = [
            hashlib.sha256(item.encode("ascii")).hexdigest() for item in segment_values
        ]
        audio_output["audio_segments"] = ["<redacted>"] * len(segment_values)

    return {
        "question": result.question,
        "transcript": result.transcript,
        "answer": result.answer,
        "gate": result.gate.__dict__,
        "provider_status": result.provider_status,
        "metrics": result.metrics.to_row(),
        "audio_output": audio_output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the real ShipVoice ASR/LLM/TTS chain.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--sample-id", default="A001")
    parser.add_argument("--mode", default="full")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--asr-endpoint", default=os.environ.get("SHIPVOICE_ASR_ENDPOINT", ""))
    parser.add_argument("--tts-endpoint", default=os.environ.get("SHIPVOICE_TTS_ENDPOINT", ""))
    parser.add_argument("--llm-provider", default=os.environ.get("SHIPVOICE_LLM_PROVIDER", "openai_compatible"))
    parser.add_argument("--llm-base-url", default=os.environ.get("SHIPVOICE_OPENAI_BASE_URL", ""))
    parser.add_argument("--llm-model", default=os.environ.get("SHIPVOICE_LLM_MODEL", ""))
    parser.add_argument("--require-llm-model-substring", default=os.environ.get("SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", ""))
    parser.add_argument("--require-adapter-sha256", default=os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""))
    parser.add_argument("--require-lora", action="store_true", default=os.environ.get("SHIPVOICE_REQUIRE_LORA", "0") in {"1", "true", "yes"})
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "real_chain_smoke.json")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
        if not args.asr_endpoint:
            args.asr_endpoint = os.environ.get("SHIPVOICE_ASR_ENDPOINT", "")
        if not args.tts_endpoint:
            args.tts_endpoint = os.environ.get("SHIPVOICE_TTS_ENDPOINT", "")
        args.llm_provider = os.environ.get("SHIPVOICE_LLM_PROVIDER", args.llm_provider)
        if not args.llm_base_url:
            args.llm_base_url = os.environ.get("SHIPVOICE_OPENAI_BASE_URL", "")
        if not args.llm_model:
            args.llm_model = os.environ.get("SHIPVOICE_LLM_MODEL", "")
        if not args.require_llm_model_substring:
            args.require_llm_model_substring = os.environ.get("SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING", "")
        if not args.require_adapter_sha256:
            args.require_adapter_sha256 = os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", "")
        args.require_lora = args.require_lora or os.environ.get("SHIPVOICE_REQUIRE_LORA", "0") in {"1", "true", "yes"}

    rows = read_csv(args.manifest)
    row = next((item for item in rows if item.get("id") == args.sample_id), None)
    if not row:
        raise SystemExit(f"sample id not found: {args.sample_id}")

    audio_path = ROOT / row["audio_path"]
    if not audio_path.exists():
        raise SystemExit(f"audio file not found: {audio_path}")

    missing = []
    if not args.asr_endpoint:
        missing.append("--asr-endpoint")
    if not args.tts_endpoint:
        missing.append("--tts-endpoint")
    if not args.llm_base_url:
        missing.append("--llm-base-url")
    if not args.llm_model:
        missing.append("--llm-model")
    if missing:
        raise SystemExit(f"real service check requires: {', '.join(missing)}")

    audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    asr_health_url = args.asr_endpoint.rsplit("/", 1)[0] + "/health"
    asr_health = http_json("GET", asr_health_url)
    asr_result = http_json(
        "POST",
        args.asr_endpoint,
        {
            "audio_base64": audio_base64,
            "audio_name": audio_path.name,
        },
    )

    tts_health_url = args.tts_endpoint.rsplit("/", 1)[0] + "/health"
    tts_health = http_json("GET", tts_health_url)
    tts_result = http_json(
        "POST",
        args.tts_endpoint,
        {"text": "ShipVoice 服务检查", "voice": "zh-CN-XiaoxiaoNeural"},
    )
    tts_audio_len = len(tts_result.get("audio_base64", ""))

    if args.require_lora and not args.require_llm_model_substring:
        args.require_llm_model_substring = "shipvoice"
    llm_health = llm_health_check(
        args.llm_base_url,
        api_key=os.environ.get("SHIPVOICE_OPENAI_API_KEY", ""),
        required_model_substring=args.require_llm_model_substring,
        require_lora=args.require_lora,
        required_adapter_sha256=args.require_adapter_sha256,
    )

    os.environ["SHIPVOICE_ASR_PROVIDER"] = "http_json"
    os.environ["SHIPVOICE_ASR_ENDPOINT"] = args.asr_endpoint
    os.environ["SHIPVOICE_TTS_PROVIDER"] = "http_json"
    os.environ["SHIPVOICE_TTS_ENDPOINT"] = args.tts_endpoint
    os.environ["SHIPVOICE_LLM_PROVIDER"] = args.llm_provider
    if args.llm_base_url:
        os.environ["SHIPVOICE_OPENAI_BASE_URL"] = args.llm_base_url
    if args.llm_model:
        os.environ["SHIPVOICE_LLM_MODEL"] = args.llm_model

    pipeline_result = asyncio.run(run_pipeline(str(row["transcript"]), audio_path, args.mode))

    summary = {
        "sample_id": args.sample_id,
        "env_file": os.environ.get("SHIPVOICE_ENV_FILE", ""),
        "audio_path": str(audio_path),
        "asr_health": asr_health,
        "asr_result": asr_result,
        "tts_health": tts_health,
        "tts_audio_base64_len": tts_audio_len,
        "llm_health": llm_health,
        "llm_require_lora": args.require_lora,
        "llm_required_model_substring": args.require_llm_model_substring,
        "llm_required_adapter_sha256": args.require_adapter_sha256,
        "pipeline_result": pipeline_result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        raise SystemExit(f"service check failed: {exc}") from exc
