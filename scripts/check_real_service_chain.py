from __future__ import annotations

import argparse
import asyncio
import base64
import csv
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


def llm_health_check(base_url: str, api_key: str = "") -> dict:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = openai_models_url(base_url)
    payload = http_json("GET", url, timeout=30, headers=headers)
    models = payload.get("data", []) if isinstance(payload, dict) else []
    return {
        "ok": True,
        "probe_url": url,
        "models": [str(item.get("id", "")) for item in models if isinstance(item, dict)][:10],
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
    return {
        "question": result.question,
        "transcript": result.transcript,
        "answer": result.answer,
        "gate": result.gate.__dict__,
        "provider_status": result.provider_status,
        "metrics": result.metrics.to_row(),
        "audio_output": result.audio_output.__dict__,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the real ShipVoice ASR/LLM/TTS chain.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "audio" / "audio_manifest.csv")
    parser.add_argument("--sample-id", default="A001")
    parser.add_argument("--mode", default="full")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--asr-endpoint", default=os.environ.get("SHIPVOICE_ASR_ENDPOINT", ""))
    parser.add_argument("--tts-endpoint", default=os.environ.get("SHIPVOICE_TTS_ENDPOINT", ""))
    parser.add_argument("--llm-provider", default=os.environ.get("SHIPVOICE_LLM_PROVIDER", "mock"))
    parser.add_argument("--llm-base-url", default=os.environ.get("SHIPVOICE_OPENAI_BASE_URL", ""))
    parser.add_argument("--llm-model", default=os.environ.get("SHIPVOICE_LLM_MODEL", ""))
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "real_chain_smoke.json")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
        if not args.asr_endpoint:
            args.asr_endpoint = os.environ.get("SHIPVOICE_ASR_ENDPOINT", "")
        if not args.tts_endpoint:
            args.tts_endpoint = os.environ.get("SHIPVOICE_TTS_ENDPOINT", "")
        if args.llm_provider == "mock":
            args.llm_provider = os.environ.get("SHIPVOICE_LLM_PROVIDER", "mock")
        if not args.llm_base_url:
            args.llm_base_url = os.environ.get("SHIPVOICE_OPENAI_BASE_URL", "")
        if not args.llm_model:
            args.llm_model = os.environ.get("SHIPVOICE_LLM_MODEL", "")

    rows = read_csv(args.manifest)
    row = next((item for item in rows if item.get("id") == args.sample_id), None)
    if not row:
        raise SystemExit(f"sample id not found: {args.sample_id}")

    audio_path = ROOT / row["audio_path"]
    if not audio_path.exists():
        raise SystemExit(f"audio file not found: {audio_path}")

    if args.asr_endpoint:
        audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        asr_health_url = args.asr_endpoint.rsplit("/", 1)[0] + "/health"
        asr_health = http_json("GET", asr_health_url)
        asr_result = http_json(
            "POST",
            args.asr_endpoint,
            {
                "audio_base64": audio_base64,
                "audio_name": audio_path.name,
                "transcript_hint": row.get("transcript", ""),
            },
        )
    else:
        asr_health = {"ok": False, "service": "not_configured"}
        asr_result = {"text": row.get("transcript", ""), "provider": "not_configured"}

    if args.tts_endpoint:
        tts_health_url = args.tts_endpoint.rsplit("/", 1)[0] + "/health"
        tts_health = http_json("GET", tts_health_url)
        tts_result = http_json(
            "POST",
            args.tts_endpoint,
            {"text": "ShipVoice 服务检查", "voice": "zh-CN-XiaoxiaoNeural"},
        )
        tts_audio_len = len(tts_result.get("audio_base64", ""))
    else:
        tts_health = {"ok": False, "service": "not_configured"}
        tts_audio_len = 0

    if args.llm_provider != "mock" and args.llm_base_url:
        llm_health = llm_health_check(args.llm_base_url, api_key=os.environ.get("SHIPVOICE_OPENAI_API_KEY", ""))
    else:
        llm_health = {"ok": False, "service": "not_configured"}

    os.environ["SHIPVOICE_ASR_PROVIDER"] = "http_json" if args.asr_endpoint else "transcript_fallback"
    if args.asr_endpoint:
        os.environ["SHIPVOICE_ASR_ENDPOINT"] = args.asr_endpoint
    os.environ["SHIPVOICE_TTS_PROVIDER"] = "http_json" if args.tts_endpoint else "mock"
    if args.tts_endpoint:
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
