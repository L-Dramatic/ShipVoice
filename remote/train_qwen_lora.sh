#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-7B-Instruct}"
PYTHON_BIN="${PYTHON_BIN:-python}"
TRAIN_FILE="${TRAIN_FILE:-data/training/shipvoice_sft_train_expanded.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/qwen_lora_shipvoice_expanded}"
EPOCHS="${EPOCHS:-2}"
BATCH_SIZE="${BATCH_SIZE:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"

cd "$PROJECT_DIR"

$PYTHON_BIN remote/train_qwen_lora.py \
  --model "$MODEL_NAME" \
  --train-file "$TRAIN_FILE" \
  --output-dir "$OUTPUT_DIR" \
  --load-in-4bit \
  --epochs "$EPOCHS" \
  --batch-size "$BATCH_SIZE" \
  --grad-accum "$GRAD_ACCUM"
