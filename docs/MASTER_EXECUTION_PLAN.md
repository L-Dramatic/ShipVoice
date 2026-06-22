# ShipVoice 主执行计划

当前执行计划以真实 provider 为唯一主线。

## 阶段 1：真实链路恢复

1. 启动远端 ASR、LLM、TTS。
2. 建立本地端口连接。
3. 启动 `run_app.py`。
4. 检查后台 provider health。
5. 运行 `scripts/check_real_service_chain.py`。

## 阶段 2：真实评测扩展

1. 使用现有 50 条录音清单做端到端采样。
2. 增加 30 条以上新录音。
3. 统计 ASR、RAG、LLM、TTS 和总耗时。
4. 更新看板、报告和 PPT。

## 阶段 3：企业级增强

1. 数据库升级。
2. 后台权限升级。
3. 评测任务队列。
4. 监控告警。
5. 更快的中文 TTS。
