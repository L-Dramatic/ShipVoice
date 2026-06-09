#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"

cd "$PROJECT_DIR"

echo "[1/5] Python and CUDA"
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

echo "[2/5] Ensure ffmpeg"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
fi
command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version | head -n 1 || true

echo "[3/5] Upgrade pip"
$PYTHON_BIN -m pip install -U pip setuptools wheel

echo "[4/5] Install ASR dependencies"
if ! $PYTHON_BIN -m pip install --no-cache-dir -U "git+https://github.com/modelscope/FunASR.git"; then
  echo "GitHub install failed, falling back to PyPI funasr"
  $PYTHON_BIN -m pip install --no-cache-dir -U "funasr"
fi

$PYTHON_BIN -m pip install --no-cache-dir -U \
  "modelscope" \
  "huggingface_hub<1.0" \
  "soundfile" \
  "librosa" \
  "ffmpeg-python"

$PYTHON_BIN -m pip install --no-cache-dir \
  "torchaudio==2.1.2" \
  --index-url https://download.pytorch.org/whl/cu118

echo "[5/5] Validate imports"
$PYTHON_BIN - <<'PY'
import importlib.util
mods = ["funasr", "modelscope", "soundfile", "librosa"]
for mod in mods:
    print(mod, bool(importlib.util.find_spec(mod)))
print("torchaudio", bool(importlib.util.find_spec("torchaudio")))
PY

echo "AutoDL ASR setup complete."
