# ShipVoice Model Card

## Model Stack

ShipVoice is not a single model. It is a cascaded system:

```text
Input / ASR transcript
  -> safety and domain gate
  -> RAG retrieval over shipyard safety corpus
  -> LLM answer synthesis
  -> optional LoRA domain-style adapter
  -> TTS / playback-oriented output
```

## Base LLM

Remote experiment model:

- `Qwen/Qwen2.5-7B-Instruct`

Use:

- baseline answer generation
- base-vs-LoRA comparison
- optional backend model behind safety gate and RAG

## Completed Fine-Tuned Adapter Experiment

Adapter:

- ShipVoice LoRA/QLoRA adapter
- Training method: 4-bit LoRA/QLoRA
- GPU: RTX 4090 24GB
- SFT seed examples: 63
- Epochs: 2
- Optimizer steps: 14
- Final train loss: 1.7777
- Adapter artifact: `results/remote_autodl_20260608_final/outputs/qwen_lora_shipvoice/adapter_model.safetensors`

This completed run is a proof that the project can execute a real remote GPU fine-tuning workflow. It is not the final recommended model because the training set was intentionally seed-scale.

## Expanded Fine-Tuning Run Prepared

The current higher-quality training plan uses the validated expanded SFT dataset:

- Train file: `data/training/shipvoice_sft_train_expanded.jsonl`
- Holdout eval file: `data/training/shipvoice_sft_eval_holdout.jsonl`
- Train examples: 1000
- Holdout eval examples: 150
- Exact train/eval input overlap: 0
- Default output directory: `outputs/qwen_lora_shipvoice_expanded`
- Default script: `remote/run_autodl_pipeline.sh`

The expanded dataset covers domain QA, safety refusal, prompt injection, off-domain refusal, boundary handling, multi-turn grounding, and ASR term correction. It is suitable for a stronger RTX 4090 LoRA/QLoRA comparison run, but the resulting adapter still remains an optional style/domain component behind safety gate and RAG.

## Evaluation Summary

| Model | Eval Rows | Avg Answer Length | Observed Strength | Observed Risk |
|---|---:|---:|---|---|
| Base Qwen2.5-7B-Instruct | 8 | 196.1 chars | safer off-domain behavior, less repetition | less domain-styled |
| ShipVoice LoRA adapter | 8 | 143.8 chars | concise shipyard safety phrasing | slight domain-template overfitting |

## Recommended Production-Like Use

The LoRA adapter should not be used as a standalone safety authority.

Recommended chain:

```text
safety/domain gate -> RAG evidence -> base model or LoRA style adapter -> answer post-check
```

The safety gate and RAG layer are mandatory. LoRA is optional.

## Safety Behavior

The system should refuse:

- requests to bypass safety checks
- requests to skip hot-work approval
- requests to damage or disable safety equipment
- prompt-injection attempts that ask the model to ignore safety rules
- off-domain requests outside shipyard safety support

## Known Limitations

- LoRA was trained on seed-scale data and can overfit safety templates.
- The expanded 1000-row run is prepared locally but should only be reported as trained after the AutoDL pipeline finishes and produces logs, adapter files, and base-vs-LoRA JSONL results.
- The model does not replace official safety procedures or qualified personnel.
- Real ASR/TTS integration still needs more audio evaluation.
- Fine-tuning evidence is useful for competition/project demonstration, but not enough for deployment claims.

## Competition Framing

Best claim:

> ShipVoice uses fine-tuning as an optional domain-style adaptation component, while safety-critical behavior is enforced through explicit gatekeeping and evidence-grounded RAG.

Claims to avoid:

- "The fine-tuned model is safer than the base model in all cases."
- "The model can replace shipyard safety officers."
- "The system is production-ready for real shipyard deployment."
