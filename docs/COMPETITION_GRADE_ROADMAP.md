# ShipVoice Competition-Grade Roadmap

## Current Reality

The current project is a strong course-project alpha, not yet a competition-grade project.

What exists now:

- Runnable local demo panel.
- Shipyard safety RAG corpus and retrieval script.
- Rule-based safety/domain gate.
- Mock ASR/LLM/TTS cascade with latency simulation.
- Remote Qwen2.5-7B LoRA/QLoRA experiment.
- Base vs LoRA evaluation evidence.
- Real 50-clip ASR benchmark with SenseVoice evaluation evidence.
- Initial report and defense deck.

What is missing for a Da Chuang / innovation competition level project:

- Larger-scale real audio data beyond the current 50-clip benchmark.
- Real streaming voice UX instead of mostly mock latency.
- Stronger domain dataset and safety benchmark.
- A formal evaluation dashboard with measurable indicators.
- A product-level frontend experience.
- A credible innovation claim beyond "we used RAG and LoRA".
- A deployable backend mode with model serving / API abstraction.
- A polished demo video, poster, technical report, and project story.

## Target Positioning

Project title:

> ShipVoice: Safety-Aware Real-Time Voice QA Copilot for Shipyard Operations

Chinese positioning:

> 面向船厂高风险作业的安全感知实时语音问答助手。

Core claim:

> ShipVoice is not a generic voice chatbot. It is a safety-aware, evidence-grounded, domain-adapted voice QA copilot for high-risk shipyard operations.

Competition-level innovation should be framed around:

1. Safety-aware cascade

   The system uses a mandatory pre-generation safety and domain gate, preventing unsafe instructions from reaching open-ended generation.

2. Evidence-grounded answers

   Every allowed answer is grounded in shipyard safety knowledge via retrieval and displays supporting evidence.

3. Domain adaptation experiment

   Qwen LoRA is evaluated as a domain-style adapter, with base-vs-LoRA comparison and known limitations.

4. Real-time voice interaction

   The final product should support real audio input, transcript display, first-response latency tracking, and sentence-level playback.

5. Auditability

   The system logs question, gate decision, retrieved evidence, answer, latency, and refusal reason for after-action review.

## Version Targets

### V0 Course Alpha

Status: mostly complete.

- Local mock cascade.
- RAG corpus.
- Safety rules.
- LoRA proof run.
- Initial report/PPT.

This is enough for a high-score course submission, but not enough for competition.

### V1 Competition Prototype

Goal:

Create a demo that judges can use and understand in 3 minutes.

Must have:

- Product-level web interface.
- Scenario selector for common shipyard tasks.
- Real microphone recording or audio upload path.
- Real ASR integration or at least offline batch ASR evaluation.
- RAG evidence panel.
- Safety gate explanation panel.
- Latency metrics panel.
- Exportable session log.
- One-click demo script.

### V2 Research/Evaluation Version

Goal:

Turn the project into a defensible experimental system.

Must have:

- 100+ domain QA items.
- 100+ unsafe/off-domain/prompt-injection/domain-safe/boundary tests.
- 30+ recorded Chinese audio samples with shipyard terms.
- ASR term accuracy evaluation.
- Retrieval hit-rate and MRR.
- Safety gate precision/recall.
- Base vs RAG vs LoRA vs RAG+LoRA comparison.
- Human-readable evaluation dashboard.

### V3 Competition Package

Goal:

Submit a polished innovation project.

Must have:

- Final report PDF.
- Defense deck.
- Demo video.
- Poster or one-page project card.
- Git-clean source package.
- Data card and model card.
- Deployment/runbook.
- Risk and ethics statement.

## Highest-Value Next Actions

The next step is not more GPU training. The next step is making the project real and measurable.

Priority order:

1. Build a competition-grade evaluation dashboard.
2. Upgrade the demo interface from "course demo panel" to "operator console".
3. Add dataset expansion scripts for QA, safety, prompt-injection, and audio manifest.
4. Add real ASR integration path with audio upload fallback.
5. Add exportable session logs.
6. Create a model card and data card.
7. Create demo video script and poster outline.

## Near-Term Definition of Done

Within the next build cycle, ShipVoice should have:

- `evaluation_dashboard.html` that summarizes retrieval, safety, latency, and LoRA comparison. Done in `deliverables/ShipVoice_Evaluation_Dashboard.html`.
- `data/tests/safety_eval.csv` with explicit unsafe/off-domain/prompt-injection cases. Done for the first 55 cases.
- A repeatable safety gate evaluator with summary artifacts. Done in `scripts/evaluate_safety_gate.py` and `results/safety_gate_eval_*`.
- `data/audio/audio_manifest.csv` as the placeholder schema for real voice samples. Done.
- `deliverables/ShipVoice_Audio_Recording_Pack.html` for distributing exact recording tasks to group members. Done.
- `scripts/evaluate_asr_transcripts.py` for CER/WER/domain-term recall after ASR transcripts are filled. Done.
- A stronger web demo with scenario cards, evidence, gate rationale, and export session log. Done as the first operator-console version.
- `docs/DATA_CARD.md`, `docs/MODEL_CARD.md`, and `docs/DEMO_VIDEO_SCRIPT.md`. Done.

## Current Competition Gap After V1 Upgrade

The project is no longer only a course alpha, but it is still not finished as a competition-grade product.

Remaining gaps:

- Real ASR/audio evaluation has been completed on 50 clips, but the next target should be 100+ clips with more speakers, more dialect variation, and harsher workshop noise.
- Safety benchmark has reached 55 cases for the first competition prototype; next target is a harder 100+ adversarial set with paraphrases and real audio variants.
- Domain QA data is still seed-scale; target should be 100+ high-quality items.
- Frontend is a strong local prototype, but not yet a deployable multi-user product.
- Demo video, poster, final report PDF, and final naming are not complete.

## User Help Needed Later

Not required immediately, but required for true competition quality:

- Expand the current 50 recorded clips to a larger multi-speaker set.
- Provide group names and student IDs.
- Confirm whether the competition requires a poster, video, source zip, or online deployment.
- If possible, provide access to a real shipyard safety handbook or course-approved safety materials.
