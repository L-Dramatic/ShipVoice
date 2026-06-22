from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shipvoice.config import load_env_file  # noqa: E402


def run(command: list[str]) -> None:
    print(f"\n> {' '.join(command)}")
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the current ShipVoice project state.")
    parser.add_argument("--quick", action="store_true", help="Run quick checks.")
    parser.add_argument("--full", action="store_true", help="Run quick checks and the full benchmark.")
    parser.add_argument("--remote-smoke", action="store_true", help="Run checks that do not require previously collected remote artifacts.")
    parser.add_argument("--with-services", action="store_true", help="Also run checks that call live ASR/LLM/TTS services.")
    parser.add_argument("--env-file", default="", help="Load provider environment before running child checks.")
    args = parser.parse_args()

    if not args.quick and not args.full and not args.remote_smoke:
        args.quick = True
    if args.env_file:
        load_env_file(args.env_file)

    run([sys.executable, "scripts/validate_real_only.py"])
    run([sys.executable, "scripts/build_knowledge_index.py"])
    run([sys.executable, "scripts/evaluate_retrieval.py"])
    run([sys.executable, "scripts/generate_sft_seed.py"])
    run([sys.executable, "scripts/build_expanded_sft_dataset.py"])
    run([sys.executable, "scripts/validate_sft_dataset.py"])
    run([sys.executable, "scripts/build_audio_recording_pack.py"])
    run([sys.executable, "scripts/evaluate_asr_transcripts.py"])
    run([sys.executable, "scripts/evaluate_safety_gate.py", "--gate-only", "--fail-on-critical"])
    run([sys.executable, "-m", "compileall", "src", "scripts", "run_app.py"])
    if args.with_services:
        run([sys.executable, "scripts/evaluate_multiturn.py"])
        run([sys.executable, "scripts/evaluate_citation_quality.py", "--fail-on-threshold"])
        run([sys.executable, "scripts/run_single.py", "密闭舱室动火作业前要检查什么？", "--mode", "full"])
        env_file = args.env_file or "configs/runtime.real.env"
        smoke_command = [sys.executable, "scripts/smoke_fastapi_backend.py"]
        if args.env_file:
            smoke_command.extend(["--env-file", args.env_file])
        run(smoke_command)
        run([sys.executable, "scripts/check_real_service_chain.py", "--env-file", env_file, "--sample-id", "A001", "--require-lora"])
    else:
        print("\nLIVE SERVICE CHECKS SKIPPED")
        print("Run with --with-services after ASR, ShipVoice LoRA LLM, and TTS are online.")
    if args.remote_smoke:
        print("\nREMOTE SMOKE VALIDATION OK")
        return
    run([sys.executable, "scripts/build_evaluation_dashboard.py"])
    run([sys.executable, "scripts/build_acceptance_report.py"])
    run([sys.executable, "scripts/build_final_report.py"])
    if args.full:
        run([sys.executable, "scripts/run_benchmark.py"])
    print("\nVALIDATION OK")


if __name__ == "__main__":
    main()
