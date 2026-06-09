# 零准备启动方案

你们现在不需要先准备完整模型、数据集、服务器或 API key。项目按“从无到有”的方式推进。

## 当前本机条件

已确认可用：

- Windows 本机。
- `conda`：已有 `base`、`pytorch_GPU`、`pytorch_env`。
- GPU：NVIDIA GeForce RTX 4060 Laptop GPU，8GB 显存。
- `pytorch_GPU` 环境：PyTorch 2.7.0 + CUDA 可用。
- `git`、`node`、`python` 可用。

暂未准备：

- Ollama 服务不可达。
- `pytorch_GPU` 里缺少 `transformers`、`modelscope`、`funasr`、`peft`、`datasets`、`sentence_transformers`。
- 还没有真实音频测试集。
- 还没有远程 GPU 或 API key。

## 结论

不是“没法做”，而是按三层推进：

1. **本机立即可做**：RAG、前后端、实验脚本、报告材料、mock 演示、数据集构造。
2. **本机可小规模做**：轻量模型推理、ASR/TTS 单样本验证、术语纠错、少量评测。
3. **建议云 GPU 做**：Qwen 7B/14B LoRA 微调、完整 ASR/TTS 模型部署、大批量实验。

## 现在默认路线

### 路线 A：不用你准备账号，先继续本机开发

我继续做：

- 后端 API。
- 前端演示面板。
- 造船安全知识库。
- RAG 检索。
- SFT/DPO 数据生成。
- 安全门控训练集。
- 实验表和报告结构。

这个阶段不需要你额外提供东西。

### 路线 B：接入真实 LLM

二选一：

1. 安装 Ollama，本机跑 1.5B/3B/7B 量化模型。
2. 使用远程 OpenAI-compatible API。

本机 RTX 4060 8GB 更适合跑小模型或量化模型，不适合高质量 14B 微调。

### 路线 C：微调与高质量模型实验

后面需要租云 GPU：

- 推荐最低：RTX 4090 24GB。
- 更稳：A40/A100/A800。
- 用于 Qwen LoRA/QLoRA、批量评测和模型对比。

## 你们目前只需要做的事

短期只需要准备三件事：

1. 组员录音：每人录 5-10 条造船安全问题，后面作为 ASR 测试音频。
2. 确认组员分工和组长姓名学号，用于报告和提交包。
3. 决定是否愿意装 Ollama，或是否有可用 API/服务器。

如果这些还没准备，也不影响我继续推进代码和数据部分。

## 下一步我会继续做

1. 生成更大的 SFT 训练集草稿。
2. 生成安全门控训练集。
3. 增加环境检查脚本。
4. 准备 Ollama/vLLM 接入说明。
5. 开始 ASR/TTS 接入前的依赖方案。

