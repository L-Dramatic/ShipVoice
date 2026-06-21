#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$PROJECT_DIR"

echo "[1/4] Python and CUDA"
$PYTHON_BIN - <<'PY'
import sys
print(sys.version)
try:
    import torch
    print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.version.cuda)
    if torch.cuda.is_available():
        print(torch.cuda.get_device_name(0))
except Exception as exc:
    print("torch check failed:", exc)
PY

echo "[2/4] Upgrade pip"
$PYTHON_BIN -m pip install -U pip setuptools wheel

echo "[3/4] Install training dependencies"
$PYTHON_BIN - <<'PY'
import torch
assert torch.cuda.is_available(), "CUDA is not visible before dependency install"
print("keeping existing torch:", torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
PY

cat > /tmp/shipvoice_pip_constraints.txt <<'EOF'
torch==2.1.2+cu118
EOF

$PYTHON_BIN -m pip install --no-cache-dir -U -c /tmp/shipvoice_pip_constraints.txt \
  "transformers==4.45.2" \
  "datasets==2.20.0" \
  "accelerate==0.33.0" \
  "peft==0.12.0" \
  "trl==0.9.6" \
  "bitsandbytes==0.43.3" \
  "sentencepiece" \
  "protobuf<5" \
  "safetensors>=0.4.5" \
  "modelscope" \
  "soundfile" \
  "fastapi" \
  "uvicorn" \
  "websockets>=12"

$PYTHON_BIN - <<'PY'
import importlib.util, json, torch
mods = ["torch", "transformers", "datasets", "peft", "accelerate", "bitsandbytes"]
print(json.dumps({m: bool(importlib.util.find_spec(m)) for m in mods}, ensure_ascii=False, indent=2))
print("torch after install:", torch.__version__, torch.cuda.is_available(), torch.version.cuda)
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no cuda")
PY

echo "[4/4] Validate project scripts"
$PYTHON_BIN scripts/validate_project.py --remote-smoke

echo "AutoDL setup complete."
