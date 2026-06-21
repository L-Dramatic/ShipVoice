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
- Train examples: 1000
- Holdout evaluation examples: 150
- Epochs: 2
- Optimizer steps: 250
- Final train loss: 0.1677
- Train runtime: 724 seconds
- Adapter artifact: `results/remote_autodl_20260621_expanded/extracted/outputs/qwen_lora_shipvoice_expanded/adapter_model.safetensors`

This completed run proves that ShipVoice can execute a real remote GPU fine-tuning workflow on an expanded domain dataset. It is still not the final recommended standalone model because safety-critical behavior should be controlled by explicit gatekeeping and evidence retrieval, not by a fine-tuned model alone.

## Expanded Fine-Tuning Dataset

The completed higher-quality training run uses the validated expanded SFT dataset:

- Train file: `data/training/shipvoice_sft_train_expanded.jsonl`
- Holdout eval file: `data/training/shipvoice_sft_eval_holdout.jsonl`
- Train examples: 1000
- Holdout eval examples: 150
- Exact train/eval input overlap: 0
- Default output directory: `outputs/qwen_lora_shipvoice_expanded`
- Default script: `remote/run_autodl_pipeline.sh`

The expanded dataset covers domain QA, safety refusal, prompt injection, off-domain refusal, boundary handling, multi-turn grounding, and ASR term correction. The resulting adapter remains an optional style/domain component behind safety gate and RAG.

## Evaluation Summary

| Model | Eval Rows | Avg Answer Length | Observed Strength | Observed Risk |
|---|---:|---:|---|---|
| Base Qwen2.5-7B-Instruct | 150 | 211.2 chars | broader general response style | off-domain refusal only 1/10 in the holdout subset |
| ShipVoice LoRA adapter | 150 | 161.2 chars | stronger ShipVoice-style refusal templates; off-domain refusal 10/10 | should still be gated by explicit safety/RAG controls |

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

- LoRA can still overfit safety templates even after the expanded 1000-row run.
- The expanded run is completed and archived locally, but it is still course-scale data generated from curated assets rather than real shipyard expert dialogue.
- The model does not replace official safety procedures or qualified personnel.
- Real ASR/TTS integration has been validated on limited samples and still needs more field-like audio evaluation.
- Fine-tuning evidence is useful for competition/project demonstration, but not enough for deployment claims.

## Competition Framing

Best claim:

> ShipVoice uses fine-tuning as an optional domain-style adaptation component, while safety-critical behavior is enforced through explicit gatekeeping and evidence-grounded RAG.

Claims to avoid:

- "The fine-tuned model is safer than the base model in all cases."
- "The model can replace shipyard safety officers."
- "The system is production-ready for real shipyard deployment."
