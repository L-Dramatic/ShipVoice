#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$PROJECT_DIR"

echo "[smoke] GPU"
nvidia-smi || true

echo "[smoke] Python packages"
$PYTHON_BIN - <<'PY'
import importlib.util
mods = ["torch", "transformers", "datasets", "peft", "accelerate", "bitsandbytes"]
for mod in mods:
    print(mod, bool(importlib.util.find_spec(mod)))
PY

echo "[smoke] ShipVoice quick validation"
$PYTHON_BIN scripts/validate_project.py --quick

echo "[smoke] One question"
$PYTHON_BIN scripts/run_single.py "密闭舱室动火作业前要检查什么？" --mode full

echo "Smoke test complete."

