from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print(f"\n> {' '.join(command)}")
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the current ShipVoice project state.")
    parser.add_argument("--quick", action="store_true", help="Run quick checks.")
    parser.add_argument("--full", action="store_true", help="Run quick checks and the full benchmark.")
    args = parser.parse_args()

    if not args.quick and not args.full:
        args.quick = True

    run([sys.executable, "scripts/build_knowledge_index.py"])
    run([sys.executable, "scripts/evaluate_retrieval.py"])
    run([sys.executable, "scripts/generate_sft_seed.py"])
    run([sys.executable, "scripts/build_audio_recording_pack.py"])
    run([sys.executable, "scripts/evaluate_asr_transcripts.py"])
    run([sys.executable, "scripts/run_single.py", "密闭舱室动火作业前要检查什么？", "--mode", "full"])
    run([sys.executable, "-m", "compileall", "src", "scripts", "run_demo.py"])
    if args.full:
        run([sys.executable, "scripts/run_benchmark.py"])
    print("\nVALIDATION OK")


if __name__ == "__main__":
    main()
