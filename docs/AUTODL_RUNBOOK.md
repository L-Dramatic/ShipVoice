# AutoDL 使用方案

## 什么时候租

现在不要立刻长时间开机训练。先在本机准备好 bundle，然后租 AutoDL 做三件事：

1. 安装依赖并跑 smoke test。
2. 用 Qwen 做 LoRA/QLoRA 小规模训练。
3. 跑微调前后对比评测。

## 推荐机器

首选：

- `1 x RTX 4090 24GB`
- 系统盘/数据盘合计至少 `80GB`
- 镜像选择 PyTorch + CUDA 的官方或社区镜像

理由：4090 24GB 足够做 Qwen 7B 的 4bit LoRA 微调，成本也比 A800 低。AutoDL 官网当前展示 RTX 4090 为 24GB，A800 为 80GB；官网价格会变，租用前以控制台实时价格为准。

备选：

- 如果只是 smoke test 和小模型：`RTX 3090 24GB`
- 如果要跑 14B、更大 batch 或更稳的语音模型：`A800 80GB`

## 创建实例

按 AutoDL 官方快速开始创建实例：

1. 进入控制台。
2. 选择“租用新实例”。
3. 选择计费方式、地区、GPU 型号、GPU 数量。
4. 选择 PyTorch/CUDA 镜像。
5. 创建后等待实例运行。

注意：实例显示“运行中”后开始计费，不用时及时关机。

## 上传项目

本机执行：

```powershell
python scripts\generate_sft_seed.py
python scripts\generate_safety_gate_data.py
python scripts\build_expanded_sft_dataset.py
python scripts\validate_sft_dataset.py
python scripts\make_autodl_bundle.py
```

上传：

```text
results\autodl_bundle.zip
```

AutoDL 上建议解压到：

```bash
mkdir -p /root/autodl-tmp/shipvoice
unzip autodl_bundle.zip -d /root/autodl-tmp/shipvoice
cd /root/autodl-tmp/shipvoice
```

## 远程初始化

```bash
bash remote/autodl_setup.sh /root/autodl-tmp/shipvoice
```

## Smoke test

```bash
bash remote/autodl_smoke_test.sh /root/autodl-tmp/shipvoice
```

必须看到：

```text
VALIDATION OK
Smoke test complete.
```

## LoRA 训练

默认模型：

```bash
bash remote/train_qwen_lora.sh /root/autodl-tmp/shipvoice
```

默认训练配置使用扩展版数据：

```text
TRAIN_FILE=data/training/shipvoice_sft_train_expanded.jsonl
EVAL_QUESTIONS=data/training/shipvoice_sft_eval_holdout.jsonl
OUTPUT_DIR=outputs/qwen_lora_shipvoice_expanded
```

切换模型：

```bash
MODEL_NAME=Qwen/Qwen2.5-3B-Instruct bash remote/train_qwen_lora.sh /root/autodl-tmp/shipvoice
```

输出目录：

```text
outputs/qwen_lora_shipvoice_expanded
```

## 托管流水线

如果希望自动完成安装、smoke test、训练、评测并在结束后关机：

```bash
PROJECT_DIR=/root/autodl-tmp/shipvoice \
PYTHON_BIN=/root/miniconda3/bin/python \
MODEL_NAME=Qwen/Qwen2.5-7B-Instruct \
TRAIN_FILE=data/training/shipvoice_sft_train_expanded.jsonl \
OUTPUT_DIR=outputs/qwen_lora_shipvoice_expanded \
EVAL_QUESTIONS=data/training/shipvoice_sft_eval_holdout.jsonl \
SHUTDOWN_ON_EXIT=1 \
nohup bash remote/run_autodl_pipeline.sh > logs/pipeline.log 2>&1 &
```

状态文件：

```text
remote_status.json
```

主日志：

```text
logs/pipeline.log
logs/setup.log
logs/smoke.log
logs/base_eval.log
logs/train_lora.log
logs/lora_eval.log
```

如果需要人工中断且不希望脚本退出后自动关机，先执行：

```bash
touch /root/autodl-tmp/shipvoice/NO_SHUTDOWN
```

## 下一步验收

训练完成后需要产出：

1. 训练日志。
2. LoRA adapter 目录。
3. 原始模型 vs LoRA 模型的问答对比。
4. 是否值得继续扩大数据和训练规模的结论。
