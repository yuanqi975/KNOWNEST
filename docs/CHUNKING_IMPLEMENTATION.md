# 文档切分策略后端实施方案

本文档是文档切分改造的执行清单。目标是让 `docs/CHUNKING.md` 中描述的策略真正进入 Python 上传链路，并为后续前端配置面板提供稳定 API。

## 1. 目标

- 以知识库为粒度保存切分配置。
- 支持 `auto`、`heading`、`heuristic`、`recursive`/`legacy`。
- 默认使用 512 字符 chunk、80 字符 overlap，而不是旧的 2400/320。
- 上传、重新索引和预览使用同一个切分器。
- 保存策略、标题路径、字符范围、页码和 parent-child 关系。
- 配置变化不隐式重切旧文档，用户显式重新索引后才生效。

## 2. 配置契约

```json
{
  "strategy": "auto",
  "chunk_size": 512,
  "chunk_overlap": 80,
  "separators": ["\n\n", "\n", "。", "！", "？", ";", "；"],
  "token_limit": 0,
  "languages": [],
  "enable_parent_child": true,
  "parent_chunk_size": 4096,
  "child_chunk_size": 384
}
```

`chunk_size`、`chunk_overlap` 是字符数；`token_limit=0` 表示关闭近似 token 限制。配置更新时校验范围，避免 overlap 大于 chunk size、父块小于子块等非法组合。

## 3. 后端实施步骤

1. 在 `app/services/parser.py` 增加配置模型、文档画像、递归/标题/启发式切分和结果统计。
2. 在 `KnowledgeBase` 增加 JSON 配置、配置版本和待重新索引标记；在 `DocumentChunk` 增加策略、层级和父块字段。
3. 在知识库 API 增加配置读取、配置更新和预览接口；创建知识库时使用默认配置。
4. 修改 ingestion：读取知识库配置，将配置传入统一切分器；parent-child 只对 child 生成向量。
5. 保留旧 `split_text(text, target_chars, overlap)` 签名作为兼容包装。
6. 对已有数据库在启动时补齐新增列；新数据库由 `create_all` 创建。
7. 增加 parser、API 和 ingestion 回归测试。

## 4. 策略语义

- `heading`：识别 Markdown 标题并维护标题 breadcrumb，章节超长时递归降级。
- `heuristic`：识别分页符、编号章节、中文章节、Chapter/Section、全大写行和视觉分隔符。
- `recursive`：按配置 separators 从高优先级到低优先级递归拆分，最后使用字符窗口。
- `auto`：根据文档画像依次尝试 heading、heuristic、recursive，并拒绝明显的异常结果。
- `legacy`：API 兼容名称，内部使用改进后的 recursive 实现。

## 5. API

- `GET /api/v1/knowledge-bases/{kb_id}/chunking-config`
- `PUT /api/v1/knowledge-bases/{kb_id}/chunking-config`
- `POST /api/v1/chunker/preview`

配置更新只标记知识库需要重新索引，不改已有 chunk。现有的文档重新索引接口会读取新配置。

## 6. 后续前端阶段

前端在知识库设置中增加策略选择、参数表单、预览和重新索引提示。本阶段不修改前端。

