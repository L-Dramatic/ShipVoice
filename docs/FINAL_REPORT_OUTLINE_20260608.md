# Final Report Outline

## 1. Project Overview

Title:

ShipVoice: Shipyard Safety Real-Time Voice QA Assistant

Goal:

Build and evaluate a cascaded voice question-answering assistant for shipyard safety scenarios. The system should be demonstrable, measurable, reproducible, and safer than a naive ASR-LLM-TTS chain.

Core contributions:

- Real-time voice QA system architecture with frontend demo panel.
- Shipyard safety knowledge base and RAG retrieval.
- Domain and safety gate for off-domain, unsafe, and prompt-injection requests.
- Latency and retrieval evaluation scripts.
- Qwen2.5-7B-Instruct LoRA/QLoRA fine-tuning experiment on RTX 4090.
- Base model vs LoRA adapter comparison.

## 2. Assignment Requirement Mapping

Map the A2 cascaded voice QA requirement to our implementation:

| Requirement | Our Implementation |
|---|---|
| Cascaded speech QA | ASR/transcript layer, LLM/RAG answer layer, TTS/playback-oriented response layer |
| Reproduction | runnable local mock demo and documented remote model run |
| Improvement | RAG, safety gate, domain knowledge, prompt-injection handling, LoRA fine-tuning |
| Evaluation | retrieval hit-rate, latency benchmark, base vs LoRA answer comparison |
| Demo | local web panel and scripted test cases |

## 3. System Architecture

Recommended diagram:

```text
User voice / text
  -> transcript normalization
  -> domain and safety gate
  -> hybrid retrieval over shipyard safety corpus
  -> answer generation
  -> evidence display and sentence-level playback
  -> logging and evaluation
```

Explain why this architecture is safer:

- Unsafe requests are blocked before answer generation.
- RAG grounds answers in curated safety knowledge.
- LoRA is optional and cannot bypass the gate.
- Mock fallback keeps the demo runnable without GPU or external APIs.

## 4. Knowledge Base and RAG

Describe:

- `data/knowledge/ship_safety_corpus.jsonl`
- 20 shipyard safety knowledge entries
- categories: confined space, hot work, lifting, pipe pressure test, PPE, emergency response, terminology
- retrieval script: `scripts/build_knowledge_index.py`
- evaluation script: `scripts/evaluate_retrieval.py`

Current evidence:

- quick retrieval check: 5/5 hit@1 and 5/5 hit@3 on representative questions

## 5. Safety Gate

Describe covered risks:

- off-domain questions
- unsafe operational bypass requests
- prompt-injection attempts
- high-risk shipyard procedure questions

Recommended claim:

The safety gate is a mandatory pre-generation control layer. It is not replaced by model fine-tuning.

## 6. LoRA/QLoRA Fine-Tuning Experiment

Remote environment:

- GPU: RTX 4090 24GB
- Base model: Qwen/Qwen2.5-7B-Instruct
- Training method: 4-bit LoRA/QLoRA
- Training records: 63 SFT seed examples
- Training epochs: 2
- Optimizer steps: 14
- Final training loss: 1.7777

Artifacts:

- `results/remote_autodl_20260608_final/results/base_eval.jsonl`
- `results/remote_autodl_20260608_final/results/lora_eval.jsonl`
- `results/remote_autodl_20260608_final/logs/train_lora_rerun.log`
- `results/remote_autodl_20260608_final/outputs/qwen_lora_shipvoice/adapter_model.safetensors`

## 7. Evaluation and Analysis

Base vs LoRA:

| Model | Eval Rows | Avg Answer Length | Observation |
|---|---:|---:|---|
| Base Qwen2.5-7B-Instruct | 8 | 196.1 chars | safer off-domain behavior, less repetition |
| LoRA adapter | 8 | 143.8 chars | more concise and more domain-styled |

Important limitation:

The LoRA adapter shows slight domain-template overfitting on the stock-investment off-domain question. Therefore, the final system should use LoRA only behind the domain and safety gate.

Recommended conclusion:

LoRA is useful as a domain-style adapter, but safety-critical behavior should rely on explicit gate plus RAG evidence, not fine-tuning alone.

## 8. Demo Design

Demo cases:

1. Confined-space hot work safety checklist.
2. Pipe pressure test risk explanation.
3. Ship block lifting pre-check.
4. Off-domain stock question refusal.
5. Unsafe bypass request refusal.
6. Prompt-injection attack refusal.
7. Ballast tank confined-space risk explanation.

Demo narrative:

- show transcription/input
- show gate decision
- show retrieved evidence
- show generated answer
- show latency metrics

## 9. Engineering Reproducibility

Local:

```powershell
python scripts\validate_project.py --quick
python run_demo.py
```

Remote:

```bash
bash remote/autodl_setup.sh /root/autodl-tmp/shipvoice
bash remote/run_resume_lora_eval.sh
```

Evidence:

- logs are saved under `results/remote_autodl_20260608_final/logs`
- adapter and tokenizer are saved under `results/remote_autodl_20260608_final/outputs/qwen_lora_shipvoice`

## 10. Limitations and Future Work

Honest limitations:

- SFT seed data is small.
- LoRA improves style but may overfit templates.
- Full ASR/TTS model integration is represented by a runnable pipeline and mock fallback unless real audio samples are added.
- Safety gate should be expanded with more adversarial tests.

Future improvements:

- collect real shipyard/noisy audio samples
- integrate SenseVoice or FunASR hotword adaptation
- integrate CosyVoice sentence-level streaming TTS
- train a lightweight safety classifier
- expand SFT and DPO data

## 11. Final Conclusion

The project demonstrates a high-quality cascaded speech QA assistant for a safety-critical vertical domain. The key strength is not simply chaining ASR, LLM, and TTS, but adding domain knowledge, safety control, experimental evaluation, and fine-tuning evidence.
