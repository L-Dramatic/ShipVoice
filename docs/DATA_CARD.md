# ShipVoice Data Card

## Dataset Purpose

ShipVoice data is designed for a shipyard safety voice QA assistant. It supports:

- RAG retrieval over shipyard safety knowledge.
- Safety/domain gate evaluation.
- LoRA/QLoRA supervised fine-tuning seed generation.
- ASR evaluation with real Chinese voice samples.

## Data Assets

| Asset | Path | Current Size | Purpose |
|---|---:|---:|---|
| Shipyard safety corpus | `data/knowledge/ship_safety_corpus.jsonl` | 20 records | RAG knowledge base |
| Retrieval eval questions | `data/tests/eval_questions.csv` | 8 records | RAG and answer behavior test |
| Safety eval questions | `data/tests/safety_eval.csv` | 55 records | off-domain, unsafe, prompt-injection, domain-safe, boundary tests |
| SFT seed data | `data/training/sft_seed.jsonl` | 63 records | LoRA/QLoRA seed fine-tuning |
| Safety gate seed data | `data/training/safety_gate_seed.jsonl` | 32 records | lightweight classifier/rule-gate training seed |
| Audio manifest | `data/audio/audio_manifest.csv` | 50 recording tasks | schema for real voice sample collection and ASR evaluation |
| ASR evaluation results | `results/asr_eval_summary.json` | 50 evaluated clips, corrected CER/WER 0.00%, term recall 100.00%; raw baseline kept in `results/asr_eval_raw_summary.json` | CER, WER, and domain-term recall |

## Domain Coverage

Current knowledge topics include:

- confined space and sealed cabin work
- hot work and welding
- ship block lifting
- pipe pressure testing
- ballast tank maintenance
- PPE
- emergency response
- shipyard terminology

## Safety Coverage

The current safety benchmark includes:

- off-domain questions
- unsafe bypass requests
- safety-device sabotage requests
- prompt-injection attempts
- authority-pressure boundary cases
- emergency-response questions

## Known Limitations

- Current domain corpus is seed-scale, not production-scale.
- SFT data is generated from curated knowledge, not collected from real shipyard conversations.
- Real audio has been collected from 3 speakers, but the sample scale is still small and not yet shipyard-field data.
- Some safety policies are rule-based and should later be validated against expert-reviewed procedures.

## Next Data Expansion Targets

For a competition-grade version:

- 100+ domain QA pairs.
- 100+ unsafe/off-domain/prompt-injection/domain-safe/boundary questions with paraphrases.
- 100+ real Chinese voice samples with more speakers, more paraphrases, and harsher noise.
- At least 3 noise conditions: quiet, classroom, workshop-like background noise.
- Human review labels for answer correctness, refusal correctness, and evidence relevance.

## Collection Guidance For Audio

Record each transcript in `data/audio/audio_manifest.csv`.

Recommended format:

- `.wav`, mono, 16 kHz or 24 kHz.
- 3-8 seconds per clip.
- Include different speakers.
- Keep original transcript unchanged.
- Do not record private personal information.

After recording:

- Update `speaker` and `status`.
- Fill `asr_transcript` and `asr_provider` after running the selected ASR model.
- Run `python scripts/evaluate_asr_transcripts.py`.
- Use `results/asr_eval_summary.json` and `results/asr_eval_report.md` as evidence.

## Responsible Use

ShipVoice is a safety assistant prototype. It must not be used as the sole authority for real shipyard work. Final operational decisions should follow official procedures and qualified safety personnel.
