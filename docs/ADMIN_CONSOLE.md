# ShipVoice Admin Console

## 入口

先启动本地服务：

```powershell
python run_app.py
```

默认地址：

```text
http://127.0.0.1:8022
```

管理后台：

```text
http://127.0.0.1:8022/admin.html
```

如果 `8022` 被占用，服务会自动顺延到后续端口，以终端输出为准。

## 现在能做什么

1. 查看项目总览
   - 知识条目数
   - 最近运行数
   - 多轮门控准确率
   - 真实链路首音延迟

2. 管理知识库
   - 搜索标题、标签、正文
   - 按高频标签筛选
   - 新建知识条目
   - 编辑知识条目
   - 删除知识条目
   - 保存后自动重建 `data/knowledge/ship_safety_index.json`

3. 运行复盘
   - 查看最近问答运行记录
   - 按成功/失败筛选
   - 搜索 `session_id`、问题文本、错误信息
   - 清理 smoke 测试日志和乱码历史记录

4. 评测监控
   - ASR 评测表：`asr_eval`
   - 多轮问答评测表：`multiturn_eval`
   - 延迟评测表：`latency_metrics`
   - 真实链路样本表：`real_chain_samples`
   - 支持重新从 `results/` 导入这些数据

5. 配置管理
   - 直接查看 `configs/pipeline.json`
   - 后台编辑并保存
   - 保存后热重载 provider 配置

6. Provider 健康检查
   - 显示 ASR / LLM / TTS 当前是 `mock` 还是真实服务
   - 检查配置的 HTTP 端点是否可达
   - 便于演示前快速确认“当前是不是在跑真链路”

## 对应后端接口

- `GET /api/admin/overview`
- `GET /api/admin/knowledge`
- `GET /api/admin/knowledge/<record_id>`
- `POST /api/admin/knowledge`
- `PUT /api/admin/knowledge/<record_id>`
- `DELETE /api/admin/knowledge/<record_id>`
- `POST /api/admin/reindex`
- `GET /api/admin/runs`
- `POST /api/admin/runs/cleanup`
- `GET /api/admin/evaluations`
- `GET /api/admin/evaluations/<dataset_name>`
- `POST /api/admin/evaluations/reload`
- `GET /api/admin/provider-health`
- `GET /api/admin/config`
- `POST /api/admin/config`
- `POST /api/admin/config/reload`

## 当前边界

1. 这是单机本地后台，还没有用户权限体系。
2. 知识库主文件仍然是 `jsonl`，但已经具备基础 CRUD 和索引重建能力。
3. 审计日志同时保存在 `SQLite` 与 `results/runtime/session_audit.jsonl`。
4. 若继续工程化，下一步应补齐认证、任务队列、对象存储和 `PostgreSQL`。
