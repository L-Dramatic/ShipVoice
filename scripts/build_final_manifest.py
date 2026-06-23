from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "results" / "final_manifest_draft.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def file_entry(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.exists():
        return {"path": relative_path, "exists": False}
    return {
        "path": relative_path,
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_json_summary(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.exists():
        return {"path": relative_path, "exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"path": relative_path, "exists": True, "error": f"invalid json: {exc}"}
    return {
        "path": relative_path,
        "exists": True,
        "sha256": sha256_file(path),
        "summary": payload,
    }


def build_manifest() -> dict[str, Any]:
    status = run_git(["status", "--short"])
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git": {
            "commit": run_git(["rev-parse", "HEAD"]),
            "branch": run_git(["branch", "--show-current"]),
            "dirty": bool(status),
            "status_short": status.splitlines(),
        },
        "configuration": {
            "pipeline": file_entry("configs/pipeline.json"),
            "runtime_examples": [
                file_entry("configs/runtime.real.env.example"),
                file_entry("configs/runtime.lora.env.example"),
                file_entry("configs/runtime.vllm.env.example"),
            ],
        },
        "data": {
            "knowledge_corpus": file_entry("data/knowledge/ship_safety_corpus.jsonl"),
            "knowledge_index": file_entry("data/knowledge/ship_safety_index.json"),
            "audio_manifest": file_entry("data/audio/audio_manifest.csv"),
            "safety_eval": file_entry("data/tests/safety_eval.csv"),
            "multiturn_eval": file_entry("data/tests/multiturn_eval.jsonl"),
            "retrieval_eval": file_entry("data/tests/eval_questions.csv"),
        },
        "results": {
            "safety_gate": read_json_summary("results/safety_gate_eval_summary.json"),
            "asr_historical": read_json_summary("results/asr_eval_summary.json"),
            "asr_online_20260623": read_json_summary("results/asr_online_20260623/summary.json"),
            "asr_online_report_20260623": file_entry("results/asr_online_20260623/report.md"),
            "multiturn": read_json_summary("results/multiturn_eval_summary.json"),
            "citation_quality": read_json_summary("results/citation_quality_summary.json"),
            "real_chain_smoke": read_json_summary("results/real_chain_smoke.json"),
            "real_chain_smoke_streaming": read_json_summary("results/real_chain_smoke_streaming.json"),
            "lora_adapter_attestation_20260623": read_json_summary("results/lora_adapter_attestation_20260623.json"),
            "server_real_batch_baseline_20260623": read_json_summary("results/server_real_batch_baseline_20260623/summary.json"),
            "server_real_batch_streaming_20260623": read_json_summary("results/server_real_batch_streaming_20260623/summary.json"),
            "server_real_batch_comparison_20260623": read_json_summary("results/server_real_batch_comparison_20260623.json"),
            "server_real_repeated_20260623": read_json_summary("results/server_real_repeated_20260623/summary.json"),
            "server_real_repeated_report_20260623": file_entry("results/server_real_repeated_20260623/summary.md"),
            "browser_onplaying_streamable_20260623": read_json_summary("results/browser_onplaying_streamable_20260623.json"),
            "browser_onplaying_streamable_screenshot_20260623": file_entry("results/browser_onplaying_streamable_20260623.png"),
        },
        "final_gate": {
            "status": "draft",
            "notes": [
                "This manifest is a local draft until git.dirty is false and report/PPT/dashboard are regenerated from it.",
                "The 2026-06-23 online evidence includes LoRA adapter SHA attestation, online ASR evaluation, 30x2x5 repeated latency evaluation, and browser audio.onplaying timing.",
                "Do not label reports FINAL while git.dirty is true or generated deliverables are stale.",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a draft ShipVoice final experiment manifest.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Manifest JSON output path.")
    parser.add_argument("--fail-if-dirty", action="store_true", help="Exit non-zero when the git worktree is dirty.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest()
    if args.fail_if_dirty and manifest["git"]["dirty"]:
        print("Refusing to write final manifest because git worktree is dirty.")
        return 2
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
