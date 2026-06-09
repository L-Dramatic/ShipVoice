#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-7B-Instruct}"
PYTHON_BIN="${PYTHON_BIN:-python}"

cd "$PROJECT_DIR"

$PYTHON_BIN remote/train_qwen_lora.py \
  --model "$MODEL_NAME" \
  --train-file data/training/sft_seed.jsonl \
  --output-dir outputs/qwen_lora_shipvoice \
  --load-in-4bit \
  --epochs 2 \
  --batch-size 1 \
  --grad-accum 8

