# 船厂安全实时语音问答助手

本项目对应信息安全基础期末项目 A2：级联式语音问答系统的复现与改进。

目标不是只把 ASR、LLM、TTS 串起来，而是做成一个可演示、可测量、可扩展的船厂安全语音助手：

- 低延迟：流式 ASR、流式 LLM、句级 TTS、首句优先播放。
- 领域增强：造船安全知识库、RAG 检索、术语热词、LLM LoRA/QLoRA 微调。
- 安全增强：领域门控、危险/恶意输入短路拒答、提示注入检测。
- 实验闭环：基线、改进、消融、延迟统计、术语识别与安全拦截评测。

## 快速运行当前演示版

当前版本先提供不依赖外部模型的 mock 演示，用于确认界面、流水线和实验记录格式。

```powershell
python run_demo.py
```

打开：

```text
http://127.0.0.1:8010
```

演示面板会调用本地后端 `/api/run`，因此后续把 mock provider 替换为真实 ASR/LLM/TTS 后，面板仍然复用。

运行 mock 延迟实验：

```powershell
python scripts\run_benchmark.py
```

输出文件：

```text
results\latency_metrics.csv
```

## 目录结构

```text
configs/                 系统配置、门控策略、延迟目标
data/knowledge/          造船安全知识库种子材料
data/tests/              固定评测问题集
docs/                    架构、实施计划、报告素材
experiments/             后续实验记录
results/                 自动生成的指标表
scripts/                 实验脚本
src/shipvoice/           级联式语音问答核心代码
web/static/              答辩演示面板
```

## 后续真实模型接入路线

1. ASR：SenseVoice/FunASR，先接热词和术语纠错，再评估微调。
2. LLM：Qwen 系列，先接 RAG，再做 LoRA/QLoRA SFT，最后做 DPO/安全偏好优化。
3. TTS：CosyVoice，优先完成句级流式播报与首句优先播放。
4. 安全：先规则门控，再训练轻量分类器，最后加入提示注入与越权请求测试集。

## 托管执行文档

- 总规划：[docs/MASTER_EXECUTION_PLAN.md](docs/MASTER_EXECUTION_PLAN.md)
- 任务看板：[docs/TASK_BOARD.md](docs/TASK_BOARD.md)
- 运行手册：[docs/RUNBOOK.md](docs/RUNBOOK.md)
- 零准备启动方案：[docs/ZERO_PREP_BOOTSTRAP.md](docs/ZERO_PREP_BOOTSTRAP.md)
- AutoDL 使用方案：[docs/AUTODL_RUNBOOK.md](docs/AUTODL_RUNBOOK.md)
- 高质量路线：[docs/HIGHEST_QUALITY_PLAN.md](docs/HIGHEST_QUALITY_PLAN.md)
- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
