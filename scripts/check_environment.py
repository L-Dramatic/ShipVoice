from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return completed.returncode, completed.stdout.strip()
    except Exception as exc:
        return 1, str(exc)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def main() -> None:
    report: dict[str, object] = {
        "commands": {name: command_exists(name) for name in ["python", "conda", "git", "node", "npm", "ollama", "ffmpeg", "nvidia-smi"]},
    }
    if command_exists("nvidia-smi"):
        _, output = run(["nvidia-smi"], timeout=10)
        report["nvidia_smi"] = output
    if command_exists("conda"):
        _, output = run(["conda", "env", "list"], timeout=20)
        report["conda_envs"] = output
        code = (
            "import importlib.util, json; "
            "mods=['torch','torchaudio','transformers','modelscope','funasr','peft','datasets','sentence_transformers']; "
            "print(json.dumps({m: bool(importlib.util.find_spec(m)) for m in mods}, ensure_ascii=False)); "
            "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), getattr(torch.version, 'cuda', None)); "
            "print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
        )
        _, output = run(["conda", "run", "-n", "pytorch_GPU", "python", "-c", code], timeout=40)
        report["pytorch_gpu_env"] = output
    out_path = ROOT / "results" / "environment_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["commands"], ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())

