# WeKnora Python API

本文档对应 `backend/app` 当前实现，所有路径默认带前缀 `/api/v1`。除健康检查外均需要：

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

错误统一使用 FastAPI 格式：

```json
{"detail":"错误描述"}
```

时间字段为 ISO 8601 字符串。ID 均为 UUID 字符串。

## 1. 健康检查

### `GET /health`

无需认证。返回：

```json
{"status":"ok","service":"weknora-python"}
```

### `GET /ready`

检查数据库连接。返回：

```json
{"status":"ready"}
```

数据库不可用时返回 `500`。

## 2. 认证

### `POST /auth/setup`

仅允许在系统还没有用户时调用，用于创建第一个用户和默认 Workspace。

请求：

```json
{"username":"alice","password":"at-least-8-characters"}
```

返回 `200`：

```json
{
  "token":"<jwt>",
  "user":{"id":"user-id","username":"alice"},
  "workspace":{"id":"workspace-id","name":"Personal workspace"}
}
```

已有用户时返回 `409`。

### `POST /auth/login`

请求格式与 `/auth/setup` 相同。返回：

```json
{"token":"<jwt>","user":{"id":"user-id","username":"alice"}}
```

### `GET /auth/me`

返回：

```json
{"id":"user-id","username":"alice"}
```

## 3. Workspace

### `GET /workspaces`

返回当前用户的全部 Workspace：

```json
[
  {"id":"workspace-id","name":"Research","description":"papers"}
]
```

### `POST /workspaces`

请求：

```json
{"name":"Research","description":"papers"}
```

返回：

```json
{"id":"workspace-id","name":"Research","description":"papers"}
```

### `GET /workspaces/{workspace_id}`

返回单个 Workspace，结构同上。

### `PATCH /workspaces/{workspace_id}`

请求字段均可选：

```json
{"name":"Renamed","description":"new description"}
```

返回更新后的 Workspace。

### `DELETE /workspaces/{workspace_id}`

成功返回 `204 No Content`。会级联删除该 Workspace 下的知识库、文档、会话、记忆和配置。

## 4. Knowledge Base

### `GET /knowledge-bases?workspace_id={workspace_id}`

返回：

```json
[
  {"id":"kb-id","name":"Product Docs","description":"manuals"}
]
```

### `POST /knowledge-bases`

请求：

```json
{"workspace_id":"workspace-id","name":"Product Docs","description":"manuals"}
```

返回：

```json
{"id":"kb-id","workspace_id":"workspace-id","name":"Product Docs","description":"manuals"}
```

### `GET /knowledge-bases/{kb_id}`

返回：

```json
{
  "id":"kb-id",
  "workspace_id":"workspace-id",
  "name":"Product Docs",
  "description":"manuals",
  "document_count":12
}
```

### `PATCH /knowledge-bases/{kb_id}`

请求：

```json
{"name":"Updated name","description":"Updated description"}
```

返回更新后的知识库基本信息。

### `DELETE /knowledge-bases/{kb_id}`

成功返回 `204`，级联删除文档、Chunk 和文件记录。

## 5. 文件夹

### `GET /knowledge-bases/{kb_id}/folders/tree`

返回嵌套树：

```json
[
  {
    "id":"folder-id",
    "name":"Architecture",
    "path":"/Architecture",
    "children":[
      {"id":"child-id","name":"API","path":"/Architecture/API","children":[]}
    ]
  }
]
```

### `POST /knowledge-bases/{kb_id}/folders`

请求：

```json
{"name":"Architecture","parent_id":null}
```

`parent_id` 可选。返回：

```json
{"id":"folder-id","name":"Architecture","path":"/Architecture","parent_id":null}
```

### `PATCH /folders/{folder_id}`

请求：

```json
{"name":"New name","parent_id":"parent-folder-id"}
```

返回：

```json
{"id":"folder-id","name":"New name","parent_id":"parent-folder-id"}
```

### `DELETE /folders/{folder_id}`

只允许删除空文件夹。成功返回 `204`；包含子文件夹或文档时返回 `409`。

## 6. 文档和索引

### `POST /knowledge-bases/{kb_id}/documents`

上传 PDF、Markdown、TXT 或 DOCX。为避免强制安装 multipart 运行库，接口接收**原始二进制请求体**：

```http
POST /api/v1/knowledge-bases/{kb_id}/documents?folder_id=<folder-id>
Authorization: Bearer <token>
X-Filename: handbook.pdf
Content-Type: application/pdf

<raw file bytes>
```

也可以使用 `filename` 查询参数代替 `X-Filename`。成功返回：

```json
{"document_id":"document-id","job_id":"job-id","status":"pending"}
```

支持扩展名：`.pdf`、`.md`、`.markdown`、`.txt`、`.docx`。

### `GET /knowledge-bases/{kb_id}/documents`

返回：

```json
[
  {
    "id":"document-id",
    "filename":"handbook.pdf",
    "file_type":".pdf",
    "folder_id":"folder-id",
    "status":"indexed"
  }
]
```

### `GET /documents/{document_id}`

返回文档详情：

```json
{
  "id":"document-id",
  "filename":"handbook.pdf",
  "file_type":".pdf",
  "folder_id":"folder-id",
  "status":"indexed",
  "parse_error":null,
  "file_size":123456,
  "created_at":"2026-10-12T10:00:00Z",
  "updated_at":"2026-10-12T10:01:00Z"
}
```

### `GET /documents/{document_id}/preview`

返回解析后的全文：

```json
{"document_id":"document-id","filename":"handbook.pdf","content":"全文内容"}
```

### `DELETE /documents/{document_id}`

删除文档、Chunk、Milvus 向量和本地源文件。成功返回 `204`。

### `POST /documents/{document_id}/reindex`

同步重新解析并重建该文档索引。返回：

```json
{"document_id":"document-id","status":"indexed"}
```

生产环境可由 Celery Worker 执行同样的 `process_document` 任务。

### `GET /documents/{document_id}/chunks`

返回：

```json
[
  {
    "id":"chunk-id",
    "sequence":0,
    "content":"passage",
    "version":1,
    "page_number":4,
    "char_start":0,
    "char_end":1200,
    "heading_path":["Architecture"],
    "index_status":"indexed"
  }
]
```

### `PATCH /chunks/{chunk_id}`

请求：

```json
{"content":"edited passage","version":1}
```

版本不一致返回 `409`。成功后重建文档索引，返回：

```json
{"id":"chunk-id","version":2,"index_status":"indexed"}
```

### `POST /chunks/{chunk_id}/reindex`

重新索引包含该 Chunk 的文档。返回：

```json
{"chunk_id":"chunk-id","status":"indexed"}
```

### `POST /documents/{document_id}/move?folder_id={folder_id}`

将文档移动到文件夹。`folder_id` 可以为空以移到知识库根目录。返回：

```json
{"document_id":"document-id","folder_id":"folder-id"}
```

### `GET /jobs/{job_id}`

返回 Celery/解析任务状态：

```json
{"id":"job-id","status":"indexed","progress":100,"error":null}
```

状态包括 `pending`、`processing`、`parsed`、`embedding`、`indexed`、`failed`、`deleting`、`deleted`。

## 7. 检索

### `POST /knowledge-bases/{kb_id}/search`

请求：

```json
{
  "workspace_id":"workspace-id",
  "knowledge_base_id":"kb-id",
  "query":"How is hybrid retrieval implemented?",
  "folder_id":null,
  "top_k":8
}
```

返回：

```json
{
  "query":"How is hybrid retrieval implemented?",
  "results":[
    {
      "chunk_id":"chunk-id",
      "document_id":"document-id",
      "content":"passage",
      "score":0.014,
      "page_number":4,
      "heading_path":["Retrieval"]
    }
  ]
}
```

实现使用 Milvus Dense 检索与 PostgreSQL 内容匹配，再用 RRF 合并排名。`top_k` 范围为 1～50。

## 8. 会话和 RAG/Agent

### `POST /chat/{mode}/sessions`

`mode` 为 `rag` 或 `agent`。请求：

```json
{"workspace_id":"workspace-id","knowledge_base_id":"kb-id","model_id":null}
```

返回：

```json
{"id":"session-id","mode":"rag","workspace_id":"workspace-id","knowledge_base_id":"kb-id"}
```

### `POST /rag/sessions`、`POST /agent/sessions`

分别是上一个接口的便捷别名，参数和返回结构相同。

### `GET /{mode}/sessions?workspace_id={workspace_id}`

返回当前用户该模式的会话：

```json
[
  {"id":"session-id","title":"New conversation","mode":"rag","knowledge_base_id":"kb-id","created_at":"2026-10-12T10:00:00Z"}
]
```

### `GET /{mode}/sessions/{session_id}`

返回会话和消息：

```json
{
  "id":"session-id",
  "title":"New conversation",
  "mode":"agent",
  "workspace_id":"workspace-id",
  "knowledge_base_id":"kb-id",
  "messages":[
    {"id":"message-id","role":"user","content":"Question","created_at":"2026-10-12T10:00:00Z"}
  ]
}
```

### `POST /rag/sessions/{session_id}/messages`

请求：

```json
{"content":"Summarize the retrieval pipeline.","model_id":null}
```

返回 `text/event-stream`。每个事件格式：

```text
event: retrieval_result
data: {"type":"retrieval_result","results":[{"chunk_id":"chunk-id","score":0.01}]}

event: token
data: {"type":"token","content":"The"}

event: message_complete
data: {"type":"message_complete","content":"完整回答"}
```

RAG 只执行检索和模型生成，不调用 Agent 工具或 MCP。

### `POST /agent/sessions/{session_id}/messages`

请求格式与 RAG 相同，返回同样是 SSE。Agent 事件包括：

```json
{"type":"agent_start"}
{"type":"planning_status","step":1,"content":"Selecting the next verifiable action"}
{"type":"tool_call_start","name":"search_knowledge_base","arguments":{"query":"..."}}
{"type":"tool_call_result","name":"search_knowledge_base","result":{"results":[]}}
{"type":"token","content":"..."}
{"type":"complete","content":"最终回答"}
```

内置工具为 `search_knowledge_base`、`read_document` 和 `calculator`。单次最多 6 步，每批最多 3 个工具调用。

### `POST /agent/sessions/{session_id}/cancel`

返回 `202`：

```json
{"session_id":"session-id","status":"cancel_requested"}
```

## 9. 长期记忆

### `GET /workspaces/{workspace_id}/memories`

返回：

```json
[
  {"id":"memory-id","type":"preference","content":"Prefer concise answers","status":"active","confidence":0.93}
]
```

### `POST /workspaces/{workspace_id}/memories`

请求：

```json
{"workspace_id":"workspace-id","type":"preference","content":"Prefer concise answers"}
```

返回新建的 active 记忆。

`type` 可选：`profile`、`preference`、`fact`、`task`、`interest`。

### `PATCH /memories/{memory_id}`

请求字段可选：

```json
{"type":"fact","content":"Updated memory"}
```

返回更新后的记忆。

### `POST /memories/{memory_id}/confirm`

将 pending 记忆改为 active：

```json
{"id":"memory-id","status":"active"}
```

### `POST /memories/{memory_id}/reject`

将候选记忆改为 rejected，返回结构同上，状态为 `rejected`。

### `DELETE /memories/{memory_id}`

删除单条记忆和其向量，返回 `204`。

### `DELETE /workspaces/{workspace_id}/memories`

删除 Workspace 的全部记忆，返回 `204`。

## 10. 模型配置

### `GET /workspaces/{workspace_id}/models`

返回模型配置，不返回 API Key：

```json
[
  {"id":"model-id","provider":"openai","model_name":"gpt-4.1-mini","is_default_rag":true,"is_default_agent":false}
]
```

### `POST /workspaces/{workspace_id}/models`

请求：

```json
{
  "workspace_id":"workspace-id",
  "provider":"deepseek",
  "base_url":"https://api.deepseek.com",
  "model_name":"deepseek-chat",
  "api_key":"sk-...",
  "supports_tools":true,
  "supports_reasoning":false,
  "is_default_rag":false,
  "is_default_agent":true
}
```

`provider` 只能是 `openai` 或 `deepseek`。API Key 服务端加密保存。返回结构同列表项。

### `POST /models/{model_id}/test`

调用模型发送 `Reply with OK`，返回：

```json
{"ok":true,"provider":"openai","model":"gpt-4.1-mini","response":"OK"}
```

## 11. MCP

MCP 是 Agent 的扩展工具来源；RAG 不读取 MCP 配置。连接管理通过 `backend/app/services/mcp.py` 的官方 MCP SDK 会话完成：HTTP、Streamable HTTP、SSE 和 stdio 均先执行 `initialize`，连接在进程内复用，断线后下次调用自动重连。工具发现支持分页并以 upsert 方式刷新，已启用工具不会因重新发现而被重置；发现的新工具默认关闭。

HTTP 目标默认拒绝 localhost、内网、回环和链路本地地址；stdio 默认关闭，需通过服务端策略显式打开。MCP 调用会按发现的 input schema 校验参数，并写入 `mcp_call_audits`，不记录认证密钥。

### `GET /workspaces/{workspace_id}/mcp-servers`

返回：

```json
[{"id":"server-id","name":"Linear","transport":"streamable_http","enabled":false}]
```

### `POST /workspaces/{workspace_id}/mcp-servers`

请求：

```json
{
  "workspace_id":"workspace-id",
  "name":"Linear",
  "transport":"streamable_http",
  "command":null,
  "args":[],
  "endpoint":"https://mcp.example.com/mcp",
  "auth_type":"bearer",
  "auth_secret":"secret",
  "enabled":false,
  "timeout_seconds":30
}
```

`transport` 可选 `stdio`、`sse`、`streamable_http`。返回：

```json
{"id":"server-id","name":"Linear","transport":"streamable_http","enabled":false}
```

### `GET /mcp-servers/{server_id}`

返回完整配置，但不返回解密后的 secret：

```json
{"id":"server-id","name":"Linear","transport":"streamable_http","command":null,"args":[],"endpoint":"https://mcp.example.com/mcp","auth_type":"bearer","enabled":false,"timeout_seconds":30}
```

### `PATCH /mcp-servers/{server_id}`

请求结构与创建接口相同。`auth_secret` 省略时保留原 secret。返回服务器摘要。

### `DELETE /mcp-servers/{server_id}`

删除 Server 及其工具目录，返回 `204`。

### `GET /mcp-servers/{server_id}/tools`

返回已发现工具：

```json
[
  {"id":"tool-id","tool_name":"list_issues","description":"List issues","input_schema":{"type":"object"},"enabled":false}
]
```

### `POST /mcp-servers/{server_id}/connect`

启用并连接 MCP Server。返回：

```json
{"server_id":"server-id","status":"connected"}
```

### `POST /mcp-servers/{server_id}/discover`

调用 Server 的 `tools/list`，刷新工具目录。返回：

```json
{
  "server_id":"server-id",
  "tools":[
    {"id":"tool-id","tool_name":"list_issues","description":"List issues","enabled":false}
  ]
}
```

发现的工具默认关闭，必须通过 `PATCH /mcp-tools/{tool_id}?enabled=true` 显式启用。

### `PATCH /mcp-tools/{tool_id}?enabled=true`

启用或禁用单个 MCP 工具。返回：

```json
{"id":"tool-id","enabled":true}
```

## 12. 状态、模型和向量约定

- PostgreSQL 保存用户、Workspace、知识库、文件夹、文档、Chunk、会话、引用、记忆和配置。
- Milvus Collection 默认名为 `weknora_vectors`，向量维度固定为 4096。
- Embedding 默认通过 SiliconFlow OpenAI-compatible API 调用 `Qwen/Qwen3-VL-Embedding-8B`。
- `OPENAI_*` 和 `DEEPSEEK_*` 环境变量提供默认模型；Workspace 模型配置可以覆盖默认值。
- 文档索引任务状态：`pending`、`processing`、`parsed`、`embedding`、`indexed`、`failed`、`deleting`、`deleted`。
- SSE 客户端应忽略未知事件，并在 `error` 或连接断开时显示可恢复状态。

## Runtime UI integration addendum

The KNOWNEST runtime uses the following additional contracts. These endpoints
are documented here because the older sections predate the runtime workbench.

### `GET /auth/setup-status`

Unauthenticated bootstrap probe used by the login screen:

```json
{"initialized":false}
```

`initialized` becomes `true` once at least one user exists. The client only
shows account creation while it is `false`; otherwise it shows normal login.

### `GET /chunks/{chunk_id}/citation`

Returns the authenticated user's source context for a citation button in the
RAG or agent transcript:

```json
{
  "chunk_id":"chunk-id",
  "document_id":"document-id",
  "filename":"handbook.md",
  "content":"The retention policy is seven years.",
  "page_number":3,
  "paragraph_index":2,
  "heading_path":["Policies","Retention"],
  "char_start":10,
  "char_end":48
}
```

The endpoint returns `401` without a bearer token and `404` when the chunk is
missing or belongs to another user's workspace.

### RAG stream citation events

`POST /rag/sessions/{session_id}/messages` emits a rich retrieval event before
model tokens, followed by one `citation` event per retrieved chunk:

```text
event: retrieval_result
data: {"type":"retrieval_result","results":[{"citation_index":1,"document_id":"document-id","filename":"handbook.md","chunk_id":"chunk-id","page_number":3,"char_start":10,"char_end":48,"heading_path":["Policies","Retention"],"quoted_text":"The retention policy is seven years.","score":0.87}]}

event: citation
data: {"type":"citation","citation_index":1,"document_id":"document-id","filename":"handbook.md","chunk_id":"chunk-id","page_number":3,"char_start":10,"char_end":48,"heading_path":["Policies","Retention"],"quoted_text":"The retention policy is seven years.","score":0.87}

event: message_complete
data: {"type":"message_complete","content":"..."}
```

After the assistant message is created, the same citation metadata is stored in
the `citations` table. The UI therefore opens source text from a real chunk and
does not render an unlinked citation placeholder.
