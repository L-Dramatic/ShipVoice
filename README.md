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
当前接口也支持 `history` 多轮上下文字段，便于把 Part 1 的对话能力接到 Part 2 的语音链路中。
用户端支持三种输入方式：文本提问、音频文件上传、浏览器麦克风直接录音。直接录音使用浏览器 MediaRecorder 生成音频，再按和上传文件相同的 `audio_base64` 协议送入后端 ASR。
回答结果会展示 RAG 证据引用，包括知识条目 ID、来源、风险级别、置信度、标签和匹配词，便于说明答案不是模型凭空生成。

运行 mock 延迟实验：

```powershell
python scripts\run_benchmark.py
```

输出文件：

```text
results\latency_metrics.csv
```

生成课程验收报告：

```powershell
python scripts\build_acceptance_report.py
```

输出文件：

```text
results\project_acceptance_report.md
results\project_acceptance_report.json
```

## 接入真实 ASR / LLM / TTS

当前版本已经支持通过环境变量切换 provider，并在 `/api/health` 与前端界面中显示当前实际使用的链路。

### 1. 真实 LLM

```powershell
$env:SHIPVOICE_LLM_PROVIDER="openai_compatible"
$env:SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
$env:SHIPVOICE_LLM_MODEL="qwen2.5:7b-instruct"
python run_demo.py
```

### 2. 真实 ASR

后端支持 `http_json` ASR provider。约定向 ASR 服务发送：

```json
{
  "audio_base64": "...",
  "audio_name": "sample.wav",
  "transcript_hint": "可选文本提示"
}
```

并从响应 JSON 的 `text` 字段读取转写结果。

```powershell
$env:SHIPVOICE_ASR_PROVIDER="http_json"
$env:SHIPVOICE_ASR_ENDPOINT="http://127.0.0.1:8001/asr"
python run_demo.py
```

### 3. 真实 TTS

后端支持 `http_json` TTS provider。约定向 TTS 服务发送：

```json
{
  "text": "要合成的回答",
  "voice": "alloy"
}
```

并从响应 JSON 的 `audio_base64` 与 `mime_type` 字段读取音频结果。

```powershell
$env:SHIPVOICE_TTS_PROVIDER="http_json"
$env:SHIPVOICE_TTS_ENDPOINT="http://127.0.0.1:8002/tts"
python run_demo.py
```

如果真实服务不可用，系统仍保留 fallback，便于答辩现场兜底；但课程冲分阶段的主叙事必须切换到真实链路。

### 4. 远端一键启动真实 ASR + TTS

仓库已经提供远端服务脚本：

- `remote/serve_funasr_asr.py`
- `remote/serve_edge_tts.py`
- `remote/start_shipvoice_real_services.sh`
- `remote/stop_shipvoice_real_services.sh`

在 GPU 机器上完成依赖安装后，可直接启动：

```bash
bash remote/autodl_setup_asr.sh /root/autodl-tmp/shipvoice
bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果 `edge-tts` 对中文播报不稳定，可直接切换备用中文 backend：

```bash
TTS_BACKEND=gtts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果需要真正的本地中文 TTS 模型，可进一步切到 `ChatTTS`：

```bash
TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果远端机器访问官方 Hugging Face 不稳定，建议显式指定镜像：
```bash
HF_ENDPOINT=https://hf-mirror.com CHATTTS_SOURCE=huggingface TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

然后在本地演示机上配置：

```powershell
$env:SHIPVOICE_ASR_PROVIDER="http_json"
$env:SHIPVOICE_ASR_ENDPOINT="http://<server-ip>:8001/asr"
$env:SHIPVOICE_TTS_PROVIDER="http_json"
$env:SHIPVOICE_TTS_ENDPOINT="http://<server-ip>:8002/tts"
python run_demo.py
```

### 已验证的真实语音链路

2026-06-12 已完成一轮远端真实链路验证，结果归档于 `results/remote_real_chain_20260612_chattts_48359/`：

- 远端 ASR：`FunASR / SenseVoiceSmall`
- 远端 TTS：`ChatTTS`
- 验证样本：`A001-A003` 共 3 条真实录音
- 平均 ASR：`158 ms`
- 平均检索：`165.67 ms`
- 平均端到端首音：`15238.67 ms`

这轮验证证明系统已经具备真实语音输入与真实语音输出能力；当前瓶颈是 `ChatTTS` 首音延迟较高，而不是 ASR 或检索。

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

## 最新验收材料

- 课程高分评分证据：[docs/PHASE1_SCORECARD.md](docs/PHASE1_SCORECARD.md)
- 演示与运维操作手册：[docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md)
- 一键验收报告：[results/project_acceptance_report.md](results/project_acceptance_report.md)
