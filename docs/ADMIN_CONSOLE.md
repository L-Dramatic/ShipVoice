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

后台需要管理员登录。密码来自环境变量 `SHIPVOICE_ADMIN_PASSWORD`；未设置时使用开发默认值 `shipvoice-admin`。答辩前建议显式设置密码后再启动服务。

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
   - 按 case 状态和严重度筛选
   - 搜索 `session_id`、问题文本、错误信息
   - 给异常记录标记 `open`、`investigating`、`resolved` 等处理状态
   - 记录严重度、问题类型、负责人、复盘人和处理备注
   - 导出 CSV / JSONL 作为后续改进台账
   - 清理 smoke 测试日志和乱码历史记录

4. 评测监控
   - ASR 评测表：`asr_eval`
   - 多轮问答评测表：`multiturn_eval`
   - 延迟评测表：`latency_metrics`
   - 真实链路样本表：`real_chain_samples`
   - 支持重新从 `results/` 导入这些数据
   - 支持从后台发起异步评测任务，并查看任务状态和日志

5. 配置管理
   - 直接查看 `configs/pipeline.json`
   - 后台编辑并保存
   - 保存后热重载 provider 配置

6. Provider 健康检查
   - 显示 ASR / LLM / TTS 当前是 `mock` 还是真实服务
   - 检查配置的 HTTP 端点是否可达
   - 便于演示前快速确认“当前是不是在跑真链路”

## 对应后端接口

- `GET /api/admin/auth/status`
- `POST /api/admin/auth/login`
- `GET /api/admin/auth/session`
- `GET /api/admin/overview`
- `GET /api/admin/provider-health`
- `GET /api/admin/jobs`
- `GET /api/admin/jobs/<job_id>`
- `POST /api/admin/evaluations/run`
- `GET /api/admin/knowledge`
- `GET /api/admin/knowledge/<record_id>`
- `POST /api/admin/knowledge`
- `PUT /api/admin/knowledge/<record_id>`
- `DELETE /api/admin/knowledge/<record_id>`
- `POST /api/admin/reindex`
- `GET /api/admin/runs`
- `GET /api/admin/runs/export`
- `PUT /api/admin/runs/<run_id>/case`
- `POST /api/admin/runs/cleanup`
- `GET /api/admin/evaluations`
- `GET /api/admin/evaluations/<dataset_name>`
- `POST /api/admin/evaluations/reload`
- `GET /api/admin/config`
- `POST /api/admin/config`
- `POST /api/admin/config/reload`

## 当前边界

1. 当前是单管理员 token 认证，还不是多用户 RBAC。
2. 知识库主文件仍然是 `jsonl`，但已经具备 CRUD、版本历史、状态字段和索引重建能力。
3. 审计日志同时保存在 `SQLite` 与 `results/runtime/session_audit.jsonl`。
4. 后台任务当前是本地异步执行，企业级版本应迁移到独立任务队列。
5. 若继续工程化，下一步应补齐 RBAC、对象存储、PostgreSQL 和集中化监控。
