# 上下文与长期记忆

## 数据与权限

PostgreSQL 保存完整消息、运行记录、结构化摘要、记忆、来源、向量和后台任务。
Redis 只保存可重建缓存、取消信号和 Celery 队列。文档检索继续使用原有 Milvus。

记忆按用户和 Workspace 隔离，`knowledge_base_id` 不为空时仅在该知识库生效。
手动创建及明确的“请记住…”直接生效，自动提取的候选必须确认。
明确指令中的回答偏好默认对整个工作空间生效，其余明确保存内容默认关联当前知识库。
自动提取只能引用用户原文，不能把模型回答、文档或工具输出当成用户事实。
从回答保存为记忆属于用户主动保存，可在抽屉中编辑并选择范围。

记忆是回答偏好和项目背景，不是文档证据。文档引用只对应实际提供给模型的知识库片段。

## 部署与迁移

安装更新的 `backend/requirements.txt`。PostgreSQL 必须支持 pgvector；Compose 已采用 pgvector 镜像。
记忆固定使用 4096 维向量，不创建不支持该维度的普通 vector HNSW 索引。
修改文档 Embedding 的维度不会改变记忆列，修改记忆维度需要后续数据库迁移。

API 启动时执行 Alembic，在 PostgreSQL 中使用事务级 advisory lock 串行化多进程升级。
也可在发布步骤显式执行：

```powershell
$env:PYTHONPATH = 'backend'
python -m alembic -c backend/alembic.ini upgrade head
```

升级前备份现有数据库。初始迁移接纳无 Alembic 版本的旧库，补充新列，按 `(created_at, id)` 回填消息序号。
已有有效记忆只补向量，不扫描历史对话生成候选。迁移依赖安装扩展权限，受限部署应先由管理员安装 `vector` 扩展。
该迁移不提供破坏性降级；回滚应用时关闭功能开关并保留新表。

容器部署：

```powershell
docker compose -f docker-compose.python.yml up -d --build python-api python-worker python-context-worker python-memory-worker python-scheduler
```

其中 `python-worker` 消费文档导入队列，`python-context-worker` 消费摘要及派发队列，
`python-memory-worker` 消费记忆提取及向量队列，`python-scheduler` 每 10 秒投递一次数据库任务扫描。
先确保 API 已完成迁移，再依赖后台任务处理。

本地启动 API 之外，还需启动 Worker 与 Beat：

```powershell
python -m celery -A app.workers.celery_app worker -Q ingestion --loglevel=INFO
python -m celery -A app.workers.celery_app worker -Q context --loglevel=INFO
python -m celery -A app.workers.celery_app worker -Q memory --loglevel=INFO
python -m celery -A app.workers.celery_app beat --loglevel=INFO
```

Windows 本地开发可为各 Worker 加 `--pool=solo`；正式部署使用 Linux 容器。
Worker 和 API 必须使用相同数据库、Redis、环境名称及加密密钥。摘要和提取需要聊天模型凭据，向量化需要 Embedding 凭据。
Redis 使用 AOF、数据卷与 `noeviction`；数据库任务记录保证队列丢失后可重新派发。
更新前已存在的旧 Celery 队列应先排空，因为新版本使用环境隔离的 Key 前缀。

## 配置

| 配置 | 默认值 | 行为 |
| --- | --- | --- |
| `CONTEXT_ENABLED` | `true` | 关闭后跳过摘要和记忆注入，仍保留运行控制、最新历史与预算保护 |
| `SUMMARIES_ENABLED` | `true` | 控制摘要生成与使用 |
| `MEMORY_RECALL_ENABLED` | `true` | 控制回答时召回长期记忆 |
| `MEMORY_EXTRACTION_ENABLED` | `true` | 控制对新成功轮次自动提取候选，不影响明确保存 |
| `CONTEXT_CACHE_ENABLED` | `true` | Redis 缓存和运行信号加速；关闭后直接使用 PostgreSQL |
| `CONTEXT_WINDOW_TOKENS` | `32768` | 默认模型窗口，可由模型配置覆盖 |
| `MAX_OUTPUT_TOKENS` | `4096` | 实际传给模型的输出上限 |
| `MEMORY_EMBEDDING_TIMEOUT_SECONDS` | `2` | 在线记忆查询向量超时；超时改用关键词 |
| `RUN_LEASE_SECONDS` | `120` | 数据库运行租约，流式连接约每秒检查并续期 |

输入预算为窗口减去输出上限及安全余量，32K 默认窗口对应约 24K 输入。
摘要、记忆、最近历史分别最多约 2K、2K、8K，文档使用剩余额度；工具定义也计入预算。
已知模型使用 tiktoken，未知模型按 UTF-8 字节数保守估算。

达到 12 个未摘要成功轮次，或历史超过 5600 Token 时，后台增量更新摘要并保留最新 6 轮。
生成摘要前会限制单次输入；极长会话可能需要后续轮次继续推进覆盖范围。

## API 与界面

原有会话、记忆接口继续可用。新增：

- 消息请求可传 `client_request_id`。相同标识和内容只执行一次；完成后重放已保存答案与引用。
- 同一标识用于不同内容、同会话并发、旧版本编辑返回 `409`。失败或取消后重新执行须使用新标识。
- 记忆新增字段：`knowledge_base_id`、`source_message_id`、`expires_at`、`replaces_id`。
- 编辑请求可传 `version`；确认、拒绝请求可传 `{ "version": 2 }`。兼容旧客户端不传版本。
- `GET /conversations/{id}/context` 返回最近运行的预算、摘要覆盖范围、记忆与文档 ID。
- 删除会话可加 `?include_saved_memories=true`，同时删除来自该会话的主动保存记忆。

新增 SSE：`run_started`、`context_ready`、`memory_saved`、`context_degraded`。
`message_complete` / `agent_complete` 在数据库提交后发送，并包含 `run_id` 和 `message_id`。
这支持请求重放，不提供从某个 Token 位置恢复流式连接的能力。

记忆抽屉支持有效／待确认／其他状态、来源、冲突新旧值、确认拒绝、编辑删除及本轮使用信息。

## 一致性与恢复

- 运行互斥使用 PostgreSQL 会话行锁及部分唯一索引，完成写入校验租约与取消状态。
- 取消请求写入 PostgreSQL，Redis 信号加速传播；缓存故障不影响数据库取消。
- 成功回答与后处理任务在同一事务提交。派发失败留在数据库，Worker 崩溃后租约到期重投。
- 后台结果通过任务租约令牌、记忆版本及清空代次检查，防止旧向量、摘要覆盖新版本。
- 清空记忆递增代次；运行从开始时记录代次，因此清空前启动、清空后完成的轮次也不能重新生成旧候选。删除单条记忆保留无正文的内容哈希及来源消息标识屏蔽，防止在途提取恢复已删内容。
- 主动再次保存同样内容可解除该哈希屏蔽。删除正文时同时删除来源、向量、审计元数据和关联向量任务。
- 删除会话默认移除自动衍生记忆，主动保存的记忆保留但移除来源引用。
- Redis 缓存带版本和 TTL；召回命中后仍校验数据库状态、范围和版本。

任务最多自动尝试 5 次，退避后进入 `failed`，错误写入 `background_jobs.error`。
修复凭据或模型服务后，可通过受控数据库运维将指定失败任务重置为 `pending`、`attempts=0`、`available_at=CURRENT_TIMESTAMP`。
不要批量重放已删除会话、已清空代次或已改变记忆版本对应的任务。

外部 MCP 工具的不可逆操作仍由工具服务保障业务幂等；网络中断或进程崩溃无法回滚已经发生的外部副作用。
相同聊天请求标识不会重新执行工具；新的请求标识代表新的执行请求。

## 验证与观测

```powershell
$env:PYTHONPATH = 'backend'
python -m pytest backend/tests -q -p no:cacheprovider
```

真实存储测试需显式设置有创建测试数据库权限的连接；测试使用随机数据库和 Redis Key 前缀并在结束时清理：

```powershell
$env:CONTEXT_TEST_DATABASE_URL = 'postgresql+psycopg://test-user@127.0.0.1:5432/postgres'
$env:CONTEXT_TEST_REDIS_URL = 'redis://127.0.0.1:6379/15'
python -m pytest backend/tests/test_context_integration.py -q
```

日志记录 `context_ready`、`memory_recall`、`context_job_backlog`、`background_job_complete/failed`，
包含预算分布、缓存命中、召回耗时、降级和各状态任务数量。摘要覆盖范围也可通过上下文接口查看。
生产环境按日志指标关注失败任务、持续积压、摘要覆盖滞后和模型调用失败；先在真实业务语料上测延迟与召回效果，再设置告警阈值。
