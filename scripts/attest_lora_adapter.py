from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_real_service_chain import openai_health_url, openai_models_url  # noqa: E402
from shipvoice.config import load_env_file  # noqa: E402


def http_json(url: str, timeout: int = 30) -> dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record and optionally verify ShipVoice LoRA adapter attestation.")
    parser.add_argument("--env-file", default=os.environ.get("SHIPVOICE_ENV_FILE", ""))
    parser.add_argument("--llm-base-url", default=os.environ.get("SHIPVOICE_OPENAI_BASE_URL", ""))
    parser.add_argument("--expected-sha256", default=os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", ""))
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "lora_adapter_attestation_20260623.json")
    args = parser.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
        if not args.llm_base_url:
            args.llm_base_url = os.environ.get("SHIPVOICE_OPENAI_BASE_URL", "")
        if not args.expected_sha256:
            args.expected_sha256 = os.environ.get("SHIPVOICE_LORA_ADAPTER_SHA256", "")
    if not args.llm_base_url:
        raise SystemExit("LLM base URL is required")

    models_url = openai_models_url(args.llm_base_url)
    health_url = openai_health_url(args.llm_base_url)
    models = http_json(models_url)
    health = http_json(health_url)
    actual_sha = str(health.get("adapter_sha256", "")).strip().lower()
    expected_sha = str(args.expected_sha256).strip().lower()
    if expected_sha and actual_sha != expected_sha:
        raise SystemExit(f"adapter SHA mismatch: expected {expected_sha}, got {actual_sha or '<missing>'}")
    if not health.get("adapter_loaded"):
        raise SystemExit(f"adapter is not loaded according to {health_url}: {health}")
    if not actual_sha:
        raise SystemExit(f"adapter SHA is missing from {health_url}: {health}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm_base_url": args.llm_base_url,
        "models_url": models_url,
        "health_url": health_url,
        "models": models,
        "health": health,
        "adapter_loaded": health.get("adapter_loaded") is True,
        "adapter_sha256": actual_sha,
        "expected_adapter_sha256": expected_sha,
        "sha_match": not expected_sha or actual_sha == expected_sha,
        "adapter_hash_algorithm": health.get("adapter_hash_algorithm", ""),
        "adapter_file_count": health.get("adapter_file_count", 0),
        "adapter_bytes": health.get("adapter_bytes", 0),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
