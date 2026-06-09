# Final Delivery Plan 2026-06-08

## Current Decision

Do not rent more GPU for now.

The project already has enough evidence for the advanced fine-tuning part:

- Qwen2.5-7B-Instruct base evaluation completed.
- 4-bit LoRA/QLoRA fine-tuning completed on RTX 4090.
- LoRA evaluation completed.
- Adapter, logs, and JSONL comparison results have been retrieved locally.

The highest-score path now is not more training. It is turning the current work into a polished, defensible, reproducible course project.

## Final Project Positioning

Project name:

> ShipVoice: Shipyard Safety Real-Time Voice QA Assistant

Main technical chain:

```text
Voice/Input
  -> ASR transcript or typed transcript fallback
  -> domain and safety gate
  -> shipyard safety RAG retrieval
  -> answer synthesis
  -> sentence-level playback / demo panel
  -> experiment logging
```

How to present LoRA:

```text
LoRA is an advanced domain-adaptation experiment.
It improves domain style and concise safety phrasing, but it should not replace the safety gate or RAG evidence layer.
```

This is the safest academic framing because the real experiment showed:

- Base model is safer on off-domain refusal.
- LoRA is more domain-styled and concise.
- LoRA has slight domain-template overfitting on off-domain questions.

So the final claim should be:

> We built a cascaded safety QA system and evaluated LoRA as an optional domain-style adapter. The production-oriented design keeps gate and RAG as mandatory safety layers.

## Immediate Next Work

1. Final report outline

   Create a formal report structure with:

   - assignment requirement mapping
   - system design
   - implementation details
   - RAG knowledge base
   - safety gate
   - LoRA fine-tuning experiment
   - base vs LoRA evaluation
   - limitations and future work

2. Evidence pack

   Consolidate local evidence:

   - demo screenshots
   - latency CSV
   - retrieval hit-rate
   - remote LoRA logs
   - base and LoRA JSONL outputs
   - adapter artifact manifest

3. Demo hardening

   Ensure one-click local demo still works without GPU:

   - `python run_demo.py`
   - browser opens `http://127.0.0.1:8010`
   - sample questions cover safe, unsafe, off-domain, prompt-injection, and terminology cases

4. PPT and speaking script

   Make slides around a strong story:

   - problem: shipyard safety voice QA has domain terms and high safety risk
   - solution: cascaded voice QA with safety gate and RAG
   - highlight: remote Qwen LoRA fine-tuning experiment
   - evidence: metrics, screenshots, example outputs
   - conclusion: safe-by-design system beats naive model chaining

5. Final package

   Prepare a clean submission directory:

   - source code
   - README
   - report
   - PPT
   - result evidence
   - optional demo video

## User Input Needed Later

Not needed right now, but required before final submission:

- group member names and student IDs
- teacher's required file naming format, if any
- whether the group can record several real Chinese voice samples
- whether the final submission needs `.docx`, `.pdf`, `.pptx`, or only source package

## Next Agent Action

Start with the final report outline and evidence table, then update the demo and produce the PPT/report artifacts.
