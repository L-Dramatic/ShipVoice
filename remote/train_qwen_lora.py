from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)


SYSTEM_PROMPT = "你是船厂安全语音问答助手。回答必须保守、专业、可执行，并适合语音播报。"


def patch_optimizer_mode_methods() -> None:
    """Keep Accelerate optimizer wrappers compatible with torch AdamW."""
    optimizer_cls = torch.optim.Optimizer
    if not hasattr(optimizer_cls, "train"):
        optimizer_cls.train = lambda self: None  # type: ignore[attr-defined]
    if not hasattr(optimizer_cls, "eval"):
        optimizer_cls.eval = lambda self: None  # type: ignore[attr-defined]


@dataclass
class TrainExample:
    instruction: str
    input: str
    output: str


def read_jsonl(path: Path) -> list[TrainExample]:
    rows: list[TrainExample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            rows.append(
                TrainExample(
                    instruction=str(item.get("instruction", SYSTEM_PROMPT)),
                    input=str(item["input"]),
                    output=str(item["output"]),
                )
            )
    return rows


def build_prompt(example: TrainExample) -> str:
    return (
        "<|im_start|>system\n"
        f"{example.instruction or SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"{example.input}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def main() -> None:
    patch_optimizer_mode_methods()

    parser = argparse.ArgumentParser(description="Train a Qwen LoRA adapter for ShipVoice SFT data.")
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--train-file", default="data/training/sft_seed.jsonl")
    parser.add_argument("--output-dir", default="outputs/qwen_lora_shipvoice")
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--load-in-4bit", action="store_true")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization_config = None
    if args.load_in_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        trust_remote_code=True,
        device_map="auto",
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        quantization_config=quantization_config,
    )
    if args.load_in_4bit:
        model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    examples = read_jsonl(Path(args.train_file))

    def encode(example: TrainExample) -> dict[str, list[int]]:
        prompt = build_prompt(example)
        answer = f"{example.output}<|im_end|>"
        prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
        answer_ids = tokenizer(answer, add_special_tokens=False).input_ids
        input_ids = (prompt_ids + answer_ids)[: args.max_length]
        labels = ([-100] * len(prompt_ids) + answer_ids)[: args.max_length]
        attention_mask = [1] * len(input_ids)
        return {"input_ids": input_ids, "labels": labels, "attention_mask": attention_mask}

    dataset = Dataset.from_list([encode(example) for example in examples])
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        logging_steps=5,
        save_steps=50,
        save_total_limit=2,
        bf16=torch.cuda.is_available(),
        report_to="none",
        remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True),
    )
    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"saved LoRA adapter -> {args.output_dir}")


if __name__ == "__main__":
    main()
