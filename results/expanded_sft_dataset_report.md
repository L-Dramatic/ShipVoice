# ShipVoice Expanded SFT Dataset Report

本报告由 `scripts/build_expanded_sft_dataset.py` 自动生成，用于说明扩展训练数据的规模、类别和边界。

## Summary

- Train examples: 1000
- Eval examples: 150
- Exact train/eval input overlap: 0
- Train avg input chars: 29.8
- Train avg output chars: 159.3

## Train By Category

- asr_term_correction: 208
- domain_qa: 460
- domain_tag_prompt: 33
- multiturn_grounding: 72
- safety_boundary: 20
- safety_off_domain: 44
- safety_prompt_injection: 40
- safety_unsafe: 60
- seed_sft: 63

## Eval By Category

- asr_term_correction: 20
- domain_qa: 60
- multiturn_grounding: 20
- safety_boundary: 5
- safety_domain_safe: 12
- safety_off_domain: 11
- safety_prompt_injection: 10
- safety_unsafe: 12

## Usage Boundary

这批数据适合用于课程项目中的 QLoRA/LoRA 领域风格适配实验。它可以让模型更像船厂安全语音助手，但不能单独证明模型具备生产级安全能力。正式系统仍应使用安全门控、RAG 证据引用、术语后处理和运行审计来保证边界。
