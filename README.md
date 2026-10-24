<div align="center">

# KNOWNEST

### 知识有巢，答案有据。

把分散的文档，变成可检索、可对话、可追溯的知识空间。

**文档知识库 · 混合检索 RAG · Agent 研究 · 原文溯源**

[开始运行](#quickstart) · [技术架构](#architecture) · [核心原理](#principles) · [配置指南](#configuration) · [常见问题](#faq)

</div>

---

## 先看 KNOWNEST 如何工作

从进入工作空间，到向文档提问，再到核对原文，三个画面展示一条完整的使用路径。

### 01 / 进入知识空间

![KNOWNEST 登录页面：账号访问、首次初始化入口与本地运行状态](docs/images/knownest-login.png)

**从一个本地账号开始，建立自己的知识工作区。** 登录页同时展示服务状态与账号初始化状态：首次使用时创建第一个用户，并自动建立默认工作空间；已有账号时直接登录。左侧介绍文档检索、知识问答和引用证据等主要能力，右侧帮助确认当前服务是否就绪。

### 02 / 让文档参与回答

![KNOWNEST 知识问答工作台：左侧知识库与会话、中间跨文档回答、右侧来源证据](docs/images/knownest-knowledge-workspace.png)

**把“找资料、读资料、整理结论”放进同一个工作台。** 左侧管理工作空间、知识库、文档与对话；中间可选择“普通 RAG”或“智能回答”，对当前知识库提问；右侧展示检索命中的文档片段、来源文件和排名。图中以多份课程与项目材料为例，比较不同文档中的共同概念，以及各自的讨论角度。

### 03 / 从回答回到原文

<p align="center">
  <img src="docs/images/knownest-source-preview.png" alt="KNOWNEST 原文预览：打开来源文档并高亮定位命中的文本" width="480" />
</p>

**看到结论，也能检查支撑结论的文字。** 从来源卡片打开原文预览后，页面根据片段的字符位置定位并高亮相关内容，帮助核对上下文。这里的“原文”是从文件中提取的文本，不保证保留 DOCX、PDF 的原始版式。截图为实际使用示例，文件名、文档数量和回答内容随知识库变化。

---

## 阅读导航

- [项目定位与功能](#overview)
- [启动运行：从克隆到第一次回答](#quickstart)
- [环境变量与模型配置](#configuration)
- [技术栈与系统架构](#architecture)
- [核心知识点与设计理由](#principles)
- [开发、验证与评测](#development)
- [部署、持久化与升级](#deployment)
- [常见问题](#faq)
- [项目目录与许可](#repository)

<a id="overview"></a>

## 一、项目定位与功能

**KNOWNEST 是一个以文档证据为中心的知识问答应用。** 它把文件导入、文本解析、分块索引、混合检索、大模型回答和来源核对串联起来，适合个人资料整理、课程学习、论文阅读、项目研究与团队文档查询。

文件和业务记录保存在部署环境中；使用默认模型服务配置时，待向量化的文本、重排候选片段及回答所需上下文会发送给对应模型服务商。“本地运行”描述的是应用与数据存储方式，默认配置仍需要联网调用模型。

| 能力 | 当前实现 |
| --- | --- |
| 工作空间与知识库 | 按工作空间组织知识库、文件夹、文档与对话，并校验资源归属 |
| 文档导入 | 支持 `.pdf`、`.docx`、`.md`、`.markdown`、`.txt`，默认单文件上限 50 MB |
| 文档切分 | 支持自动、标题、启发式、递归及兼容策略，可配置大小、重叠与父子块 |
| 普通 RAG | 检索当前知识库，以命中证据作为上下文生成回答 |
| 智能回答 | 在知识库证据基础上使用有边界的 Agent 工具循环，支持算术计算与已启用的 MCP 工具 |
| 来源核对 | 展示命中文档、片段、检索排名与字符位置，支持打开全文并定位 |
| 连续对话 | 保存会话和引用，支持历史查看、重命名、删除及回答模式切换 |
| 模型与扩展 | 后端支持 OpenAI / DeepSeek 兼容模型配置、MCP 服务和工具管理 |
| 工作空间记忆 | 提供记忆记录的增删改查、确认与拒绝接口，前端展示已保存记录 |
| 检索评测 | 提供固定测试语料、数据完整性检查、真实模型评测与检索诊断工具 |

当前主程序是 **Python 后端 + Vue 前端**。以下部署步骤、参数与原理说明以仓库中的 `backend/app`、`frontend/src` 和 `docker-compose.python.yml` 为依据。

<a id="quickstart"></a>

## 二、启动运行：从克隆到第一次回答

### 2.1 准备环境

| 依赖 | 建议版本 / 用途 |
| --- | --- |
| Git | 克隆与更新代码 |
| Docker + Docker Compose v2 | 启动数据库、向量库、队列、后端 API 与 Worker |
| Node.js | 推荐 22.12+ 的 Node 22 LTS，配合 npm 安装并运行前端 |
| Python | 本地开发后端时推荐 3.12；后端容器与 CI 使用 3.12 |
| 模型服务凭据 | 完整问答建议配置聊天模型与 SiliconFlow Embedding；重排可单独配置 |

Docker Desktop 用户先启动 Docker 引擎，并确保使用 Linux 容器。完整依赖包含 PostgreSQL、Redis、Milvus、etcd 和 MinIO，需为 Docker 留出足够内存与磁盘；首次运行需要下载镜像。使用默认远程模型服务时，无需在本机部署大模型或准备 GPU。

下面以 **Windows PowerShell** 为例；macOS / Linux 将 `npm.cmd` 换成 `npm`，环境变量与虚拟环境命令见后文。

### 2.2 获取项目并准备配置

```powershell
git clone https://github.com/yuanqi975/KNOWNEST.git
cd KNOWNEST

# 仅在不存在配置文件时创建，保留已有安装的配置。
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

macOS / Linux 在克隆并进入项目后，用以下命令准备配置：

```bash
if [ ! -f .env ]; then
  cp .env.example .env
fi
```

编辑根目录 `.env`，至少设置以下内容。示例中的占位值需替换成自己的配置：

```dotenv
SECRET_KEY=<至少32字符的随机密钥>

# 默认聊天入口；模型名称需与所使用的服务兼容。
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=<聊天服务的API密钥>
OPENAI_MODEL=gpt-4.1-mini

# 文档与查询向量化。
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_API_KEY=<SiliconFlow的API密钥>
EMBEDDING_MODEL=Qwen/Qwen3-VL-Embedding-8B
EMBEDDING_DIMENSION=4096

# 默认使用同一 SiliconFlow 密钥，也可另配 RERANK_API_KEY。
RERANK_BASE_URL=https://api.siliconflow.cn/v1
RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_ENABLED=true
```

本地安装了 Python 时，可以用以下命令生成随机密钥，再将结果填入 `.env`：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

不要把真实密钥提交到仓库。`SECRET_KEY` 同时用于令牌签名和已保存模型密钥的加密，已有安装应保持该值稳定。

> **先区分两种运行目标：** 不填模型密钥也可以查看界面、初始化账号和进行开发联调；聊天会返回开发提示，Embedding 会使用确定性模拟向量。验证真实检索和回答效果需要配置真实模型。默认启动步骤使用模板中的模型地址；更换模型地址或运行参数时，容器配置还需按 [配置传递说明](#container-config) 补充。

### 2.3 推荐方式：容器运行后端，本机运行前端

在项目根目录启动基础依赖：

```powershell
docker compose -f docker-compose.python.yml up -d postgres redis milvus
docker compose -f docker-compose.python.yml ps
```

该命令会一并启动 Milvus 依赖的 etcd 和 MinIO。首次启动时等待数据库和 Milvus 完成初始化，再启动 API 与索引 Worker：

```powershell
docker compose -f docker-compose.python.yml up -d --build python-api python-worker
docker compose -f docker-compose.python.yml logs --tail 80 python-api python-worker
```

API 启动时会连接 PostgreSQL，创建数据表并补充部分兼容字段，无需手动执行初始化 SQL。如果依赖尚未就绪导致服务退出，先检查依赖日志，再重新执行上面的启动命令。需要长期保存索引时，先阅读 [持久化边界](#deployment)，再导入正式资料。

然后在**另一个终端**进入前端目录：

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

这里使用锁文件安装依赖。仓库的 Compose **没有前端服务**，所以还需要单独启动 Vite。前端默认请求 `http://localhost:8000/api/v1`；本机使用默认端口时无需额外配置。

| 地址 | 用途 |
| --- | --- |
| [登录页](http://127.0.0.1:5173/login) | 首次初始化与账号登录 |
| [知识工作台](http://127.0.0.1:5173/runtime) | 登录后进入知识库与对话界面 |
| [普通 RAG](http://127.0.0.1:5173/runtime/rag) | 文档检索与回答 |
| [智能回答](http://127.0.0.1:5173/runtime/agent) | Agent 模式 |
| [交互式 API 文档](http://127.0.0.1:8000/docs) | 查看与调试 FastAPI 接口 |

可以在 PowerShell 检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
```

`health` 返回 `status: ok`；`ready` 返回 `status: ready`，表示数据库连接检查通过。**这两个接口不验证 Embedding、重排和聊天模型是否可用**，还应完成一次真实文档问答。

### 2.4 完成第一次文档问答

1. 打开登录页。尚无用户时，选择“首次初始化”，设置用户名与密码；系统会建立默认工作空间。
2. 用户名长度为 3～120 个字符，密码长度为 8～72 个字符。已有用户时直接登录，初始化入口会关闭。
3. 在工作空间中新建知识库，按需要创建文件夹。
4. 在“文档处理”中确认切分配置。初次使用可保留 `auto`、子块 512 字符、重叠 80 字符、父块 4096 字符与父子切分开启。
5. 上传一份有可提取文字的 PDF、DOCX、Markdown 或 TXT，等待文档状态变成 `indexed`。可从文档详情和任务接口查看处理错误。
6. 选择“普通 RAG”，提出能在该文档中找到答案的问题，例如“这份方案的目标、方法和限制分别是什么？”。
7. 查看右侧来源卡片，打开完整片段或整份原文，核对回答与证据是否一致。
8. 需要计算或外部工具时，切换“智能回答”；MCP 工具需先配置服务、建立连接、发现工具并显式启用。

修改切分策略不会自动重建已有索引。已有文档需要重新索引；若曾使用模拟 Embedding，补齐真实密钥后也应重建这些文档的索引。

### 2.5 开发方式：在本机运行 Python 后端

调试 Python 时，可以只用 Docker 运行依赖，本机启动 API。**不要同时让容器 API 与本机 API 占用 8000 端口。** 已按推荐方式启动的用户先停止容器应用服务：

```powershell
docker compose -f docker-compose.python.yml stop python-api python-worker
docker compose -f docker-compose.python.yml up -d postgres milvus

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

$env:PYTHONPATH = 'backend'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果 PowerShell 阻止激活脚本，可直接使用虚拟环境解释器，例如 `.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt`，并用同一路径替换启动命令中的 `python`。

macOS / Linux 对应命令为：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
export PYTHONPATH=backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

本机 API 使用根目录 `.env` 中的 `localhost` 连接地址。默认 Compose 暴露 PostgreSQL 的 `5432` 和 Milvus 的 `19530`，**不暴露 Redis 的 `6379`**：

- 只调试 API 时，如果任务入队失败，当前上传接口会在线程中处理文档，并等待处理结束后返回；这会增加上传请求耗时。
- 如果 Redis 可以入队但没有消费任务的 Worker，任务会停留在队列中，不会触发上述回退。
- 需要完整异步索引时，给 Redis 增加仅绑定本机的端口映射，或使用已有本机 Redis，再单独启动本机 Worker。API 与 Worker 必须使用相同的数据库、向量集合和文件目录。

Redis 映射可写入自建的 `docker-compose.local.yml`：

```yaml
services:
  redis:
    ports:
      - "127.0.0.1:6379:6379"
```

应用映射后，在另一个已安装 Python 依赖、设置 `PYTHONPATH=backend` 的终端启动 Worker：

```powershell
docker compose -f docker-compose.python.yml -f docker-compose.local.yml up -d redis
python -m celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo
```

`--pool=solo` 适合 Windows 本机调试；Linux 容器 Worker 使用 Compose 中的默认启动命令。前端仍按 2.3 节单独运行。

<a id="configuration"></a>

## 三、环境变量与模型配置

### 3.1 配置文件与优先级

直接运行 Python 时，配置从高到低依次为：

```text
进程环境变量 > backend/.env > 项目根目录 .env > 代码默认值
```

根目录 `.env.example` 面向本机连接，`backend/.env.example` 中的 `postgres`、`redis`、`milvus` 是容器网络主机名。一般只需要复制根目录模板；不要直接将容器连接地址用于本机 Python。

### 3.2 基础运行参数

| 参数 | 默认值 / 示例 | 作用 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://knownest:knownest@localhost:5432/knownest` | 本机 Python 连接的 PostgreSQL 地址 |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery 消息代理与结果后端 |
| `MILVUS_URI` | `http://localhost:19530` | 向量库地址 |
| `MILVUS_COLLECTION` | `knownest_vectors` | 向量集合；已有安装需保持原值 |
| `REQUIRE_MILVUS` | `false` | 开发时允许连接失败后使用进程内向量存储；持久化运行建议设为 `true` |
| `STORAGE_PATH` | `./data/uploads` | 本机上传文件目录；容器内使用 `/data/uploads` |
| `ENVIRONMENT` | `development` | `staging`、`production` 会校验密钥和 Milvus 必需设置 |
| `SECRET_KEY` | 安装时生成 | JWT 签名及凭据加密的基础密钥 |
| `ACCESS_TOKEN_MINUTES` | `60` | 登录令牌有效期，单位分钟 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许访问 API 的浏览器来源，逗号分隔 |
| `MAX_UPLOAD_MB` | `50` | 单个上传文件大小上限 |
| `VITE_PYTHON_API_BASE` | `http://localhost:8000/api/v1` | 前端 API 基地址，需包含 `/api/v1` |

修改前端地址时，在 `frontend/.env.local` 中设置 `VITE_PYTHON_API_BASE`，然后重启 Vite。部署构建时，该值会进入前端产物，需要重新构建才能生效。浏览器访问远程服务器时，应使用浏览器能够访问的地址。

### 3.3 聊天、Embedding 与重排各自负责什么

| 模型角色 | 配置参数 | 默认模型 / 行为 |
| --- | --- | --- |
| 默认聊天模型 | `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` | `gpt-4.1-mini`，负责依据上下文生成回答 |
| DeepSeek 聊天 | `DEEPSEEK_BASE_URL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` | `deepseek-chat`；需显式选择对应模型配置 |
| 推理模型名称 | `DEEPSEEK_REASONER_MODEL` | `deepseek-reasoner`；配置该名称本身不会切换当前会话模型 |
| 文本向量化 | `SILICONFLOW_BASE_URL`、`SILICONFLOW_API_KEY`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSION` | `Qwen/Qwen3-VL-Embedding-8B`，4096 维 |
| 候选重排 | `RERANK_BASE_URL`、`RERANK_API_KEY`、`RERANK_MODEL`、`RERANK_ENABLED` | `BAAI/bge-reranker-v2-m3`，调用 `/rerank` |

这三个环节可以使用不同服务。向量模型把文本转成可比较的数值表示；重排模型比较问题与候选片段的相关程度；聊天模型组织最终答案。只配置聊天密钥，不等于已经获得真实的语义检索能力。

`RERANK_API_KEY` 为空时复用 `SILICONFLOW_API_KEY`。设为 `RERANK_ENABLED=false` 可以关闭重排；重排失败、超时或关闭时，检索回退到融合排名，并记录降级状态。

**使用 DeepSeek 的两种方式：**

- 希望当前前端默认就使用 DeepSeek：把 `OPENAI_BASE_URL` 改为 `https://api.deepseek.com`，将 `OPENAI_API_KEY` 填成对应 DeepSeek 密钥，并将 `OPENAI_MODEL` 改为 `deepseek-chat`，通过兼容聊天接口调用。
- 希望保留多个模型：通过 `POST /api/v1/workspaces/{workspace_id}/models` 创建 `provider: deepseek` 的模型配置，并在创建会话时显式传入该模型的 `model_id`。当前页面没有完整模型配置表单，可通过 API 集成。

没有指定会话模型时，当前聊天路由使用 `OPENAI_*`。仅填写 `DEEPSEEK_API_KEY` 或标记模型默认字段，不应视为已经完成会话模型切换。Agent 需要模型支持兼容的工具调用协议。

**更换 Embedding 模型时，向量维度必须匹配模型输出。** 已有 Milvus 集合不会因修改 `.env` 自动更改维度；应使用匹配的新集合并重建文档索引。不要在同一集合混用不同模型或模拟向量。

<a id="container-config"></a>

### 3.4 容器中的配置如何生效

Compose 读取根目录 `.env` 用于变量插值，但**不会自动把全部变量传入容器**。当前 Compose 已传入 API/Worker 所需的数据库、Redis、Milvus、文件路径、密钥和部分模型参数；自定义模型基地址、模型名称、`ENVIRONMENT`、`REQUIRE_MILVUS` 等，需要在 Compose 的 `environment` 中显式添加。

例如，创建或合并到自己的 `docker-compose.local.yml`，给 API 和 Worker 同时补充自定义模型与运行参数：

```yaml
x-runtime-settings: &runtime-settings
  ENVIRONMENT: ${ENVIRONMENT:-development}
  REQUIRE_MILVUS: ${REQUIRE_MILVUS:-true}
  OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.openai.com/v1}
  OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4.1-mini}
  DEEPSEEK_BASE_URL: ${DEEPSEEK_BASE_URL:-https://api.deepseek.com}
  DEEPSEEK_MODEL: ${DEEPSEEK_MODEL:-deepseek-chat}
  DEEPSEEK_REASONER_MODEL: ${DEEPSEEK_REASONER_MODEL:-deepseek-reasoner}
  SILICONFLOW_BASE_URL: ${SILICONFLOW_BASE_URL:-https://api.siliconflow.cn/v1}
  EMBEDDING_MODEL: ${EMBEDDING_MODEL:-Qwen/Qwen3-VL-Embedding-8B}
  EMBEDDING_DIMENSION: ${EMBEDDING_DIMENSION:-4096}
  CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173}
  MAX_UPLOAD_MB: ${MAX_UPLOAD_MB:-50}
  ACCESS_TOKEN_MINUTES: ${ACCESS_TOKEN_MINUTES:-60}
  MCP_ALLOW_PRIVATE_HOSTS: ${MCP_ALLOW_PRIVATE_HOSTS:-false}
  MCP_ALLOW_STDIO: ${MCP_ALLOW_STDIO:-false}

services:
  python-api:
    environment: *runtime-settings
  python-worker:
    environment: *runtime-settings
```

Compose 会按键合并基础文件已有的环境变量。使用覆盖文件时，后续部署命令都应带上它：

```powershell
docker compose -f docker-compose.python.yml -f docker-compose.local.yml config --quiet
docker compose -f docker-compose.python.yml -f docker-compose.local.yml up -d --build
```

`DATABASE_URL` 用于本机 Python；容器使用 Compose 构造的服务内地址，或使用 `COMPOSE_DATABASE_URL` 覆盖。数据库初始化凭据可通过根目录 `.env` 中的 `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB` 调整。修改这些变量不会自动修改已有数据库中的用户和密码。

<a id="architecture"></a>

## 四、技术栈与系统架构

### 4.1 技术选型与职责

| 层次 | 技术 | 在 KNOWNEST 中的职责与选型理由 |
| --- | --- | --- |
| 前端 | Vue 3.5、Vue Router 4 | 用组件与响应式状态组织知识库树、聊天、证据栏和抽屉，通过路由区分回答模式 |
| 类型与构建 | TypeScript 6、Vite 7、vue-tsc | 为 API 数据和页面状态提供类型检查，提供开发热更新与静态资源构建 |
| Web API | Python、FastAPI、Uvicorn | 用类型化接口承载认证、上传、检索与异步流式输出，自动提供 OpenAPI 文档 |
| 参数配置 | Pydantic 2、pydantic-settings | 校验上传限制、切分参数与运行配置，集中管理环境变量 |
| 业务存储 | PostgreSQL 16、SQLAlchemy 2、psycopg 3 | 用事务保存用户、资源归属、文档元数据、任务、消息、引用和模型配置 |
| 向量存储 | Milvus 2.4、pymilvus、COSINE | 持久化 Embedding 并按工作空间、知识库过滤相似度检索 |
| 队列与任务 | Redis 7、Celery 5 | 将文档解析和向量化移出正常上传请求，支持任务状态与失败重试 |
| 文档解析 | pypdf、python-docx | 提取 PDF 文本、DOCX 段落和表格，统一进入文本处理链路 |
| 模型访问 | HTTPX、OpenAI / DeepSeek 兼容接口 | 分离模型调用和业务逻辑，支持异步请求、流式输出和供应商配置 |
| 检索排序 | BM25、加权 RRF、Rerank | 结合字面匹配与语义匹配，再对有限候选进行精细排序 |
| 工具扩展 | MCP Python SDK、JSON Schema | 统一发现与调用外部工具，检查输入并控制启用范围 |
| 认证与凭据 | PyJWT、bcrypt、cryptography / Fernet | 验证身份、保存密码哈希、加密持久化的模型与服务凭据 |
| 工程验证 | pytest、GitHub Actions、Docker Compose | 验证后端行为、前端构建和容器配置，提供可重复的开发入口 |

前端当前主要依赖 Vue 和 Vue Router，界面由项目自身组件与样式实现。Compose 使用带 pgvector 扩展的 PostgreSQL 镜像，但**当前向量检索实现使用 Milvus**，并未将 pgvector 当作第二套检索引擎。

API 启动时执行 Alembic 版本化迁移，兼容已有数据库并回填历史消息序号。上下文预算、会话摘要、Redis 缓存和 PostgreSQL 长期记忆的配置与部署见 [上下文与长期记忆](docs/CONTEXT_MEMORY.md)；启用后台处理还需启动 `python-context-worker`、`python-memory-worker` 和 `python-scheduler`。

### 4.2 组件如何协作

```mermaid
flowchart TD
    Browser["Vue 工作台：文档 / 对话 / 来源"] --> API["FastAPI API"]
    API --> PG[("PostgreSQL：业务记录与文本块")]
    API --> Files["共享上传目录"]
    API --> Redis["Redis：任务队列"]
    Redis --> Worker["Celery Worker"]
    Worker --> Parser["文本提取与父子切分"]
    Files --> Parser
    Parser --> PG
    Parser --> Embedding["Embedding 服务"]
    Embedding --> Milvus[("Milvus：向量索引")]
    API --> Retrieval["BM25 + 向量召回 + RRF + 重排"]
    PG --> Retrieval
    Milvus --> Retrieval
    Retrieval --> Answer["RAG / Agent 与聊天模型"]
    Answer --> Tools["计算器 / 已启用的 MCP 工具"]
    Answer --> SSE["SSE：答案、引用与工具事件"]
    SSE --> Browser
```

Milvus 的运行依赖由 etcd 和 MinIO 提供。Compose 中的 API 与 Worker 挂载同一个上传文件卷，保证 Worker 能读取 API 保存的原文件；MinIO 在当前编排中服务于 Milvus，并非应用上传文件的直接存储接口。

<a id="principles"></a>

## 五、核心知识点与设计理由

### 5.1 RAG：先检索证据，再生成回答

传统聊天模型依靠训练知识和当前输入回答，无法自然掌握部署环境中新上传的文件。RAG（检索增强生成）把知识更新放到文档索引中：

```text
文档入库：文件 → 文本提取 → 切分 → Embedding → 保存文本块与向量
问题回答：问题 → 查询规划 → 混合召回 → 融合与重排 → 证据上下文 → 模型回答
```

这样可以在不重新训练聊天模型的情况下引入资料，并把检索结果与来源一起展示。它改善了回答的依据，但结果仍取决于文本提取质量、候选召回、排序与模型是否遵循证据，因此需要保留人工核对入口。

### 5.2 父子切分：检索要精确，阅读要有上下文

短片段有利于匹配具体问题，却可能丢掉定义、条件或结论所在的上下文；长片段内容完整，又容易稀释检索主题。KNOWNEST 默认将两者分开：

| 参数 | 当前默认值 | 设计考虑 |
| --- | --- | --- |
| `strategy` | `auto` | 尝试标题、启发式和递归候选，并检查切分结果 |
| `chunk_size` | 512 字符 | 控制检索子块或单层块的大小 |
| `chunk_overlap` | 80 字符 | 缓解句子或语义跨越切分边界的问题 |
| `enable_parent_child` | `true` | 小块用于检索，大块补充回答上下文 |
| `parent_chunk_size` | 4096 字符 | 在命中子块后提供更完整的上下文 |

**这些大小按字符计，不是模型 token 数。** 父块与子块使用同一策略分别切分；只有 `single` / `child` 块进入向量索引，`parent` 块保存在业务库中。检索命中子块后附加父块内容，同一父块在上下文中合并展示，引用仍指向具体命中的子块。

Markdown 资料可以利用 `#` 标题结构；缺少明确标题时使用启发式或递归窗口处理。`legacy` 是兼容策略值。FAQ 可尝试更小块并关闭父子切分，长篇论述可适当增大块与重叠；调整效果应通过同一批问题比较，不应把某个默认值当作所有资料的最优值。

切分配置保存版本号，旧文档会被标记为需要重新索引，避免“配置已改，实际向量仍对应旧切分”的状态被忽略。

### 5.3 混合检索：兼顾意思相近与字面准确

向量检索擅长发现不同表述中的相近含义；BM25 擅长寻找专有名词、编号和具体词语。KNOWNEST 将两条路径合并：

1. 问题向量在 Milvus 中执行相似度检索，取最多 24 个 Dense 候选。
2. 从 PostgreSQL 读取当前范围内已索引的文本块，在 Python 中计算 BM25；中文查询同时使用连续汉字与双字组合参与词法匹配。
3. 按加权 RRF 合并两组排名，截取最多 24 个重排候选。
4. 调用 Rerank 模型，对“问题—片段”对进行相关性评分。
5. 普通问题默认取 10 条最终证据，复合或研究类问题的查询规划通常扩大为 12 条；独立搜索接口允许在 1～50 范围内指定数量。

当前融合公式为：

```text
fusion_score = 0.6 / (60 + dense_rank) + 0.4 / (60 + lexical_rank)
```

某一路未命中时，该项为零。RRF 使用排名而不是直接比较不同检索器的原始分数，避免余弦相似度与 BM25 分数尺度不同。**融合分数与重排分数都不应解释为“答案正确率”。**

当前 BM25 在应用进程中计算，没有单独部署 Elasticsearch 或 PostgreSQL 全文检索索引。这样实现直接、便于理解和调试；代价是大知识库下需要读取并遍历更多文本块，后续扩展可考虑专门的词法索引。

查询规划采用确定性规则识别简单、复合与研究类问题，避免为每次规划额外调用模型。它用于检索范围和数量规划，**不会自动把用户选择的普通 RAG 切换为 Agent**。

### 5.4 RAG 与 Agent：按任务复杂度使用工具

| 对比项 | 普通 RAG | 智能回答 / Agent |
| --- | --- | --- |
| 适用任务 | 文档查询、摘要、基于资料的解释与对比 | 需要计算或调用外部工具的研究任务 |
| 基本路径 | 检索 → 组织上下文 → 生成 | 检索证据 → 模型选择行动 → 执行工具 → 继续或结束 |
| 外部工具 | 不调用 MCP | 仅使用当前可用且已启用的工具 |
| 可观察内容 | 回答、检索结果与引用 | 回答、检索证据、工具动作与结果 |

Agent 采用有界 ReAct 工具循环。代码定义的内置工具为 `search_knowledge_base`、`read_document` 和 `calculator`；若路由已提供初始检索证据，当前运行会移除重复的搜索与读文档工具，减少不必要的额外模型轮次。

当前 `backend/app/services/agent.py` 的主要限制为：

| 限制 | 当前值 |
| --- | --- |
| 最大 Agent 轮次 | 4 |
| 每轮最多工具调用 | 3 |
| 单次工具超时 | 12 秒 |
| Agent 运行时间预算 | 80 秒 |
| 单轮模型流超时上限 | 60 秒，同时受剩余运行预算约束 |
| 单次工具结果文本上限 | 20,000 字符 |

这些边界用于限制工具循环成本与等待时间。计算器使用受限 AST 处理算术表达式；浏览器展示可验证的工具行为与结果，不展示模型的隐藏推理内容。

### 5.5 SSE 与引用：回答过程和依据都可见

聊天接口使用 SSE（服务端发送事件）持续传递文本、检索结果、引用、工具调用与结束状态。前端通过 `fetch` 读取事件流，既能携带认证头和 POST 请求体，也能逐步呈现生成内容。

引用信息包括文档 ID、Chunk ID、引用序号、检索排名、引文和可用的位置字段。用户打开来源时，前端通过接口获取片段或提取后的全文，并用字符范围定位。这使回答与证据建立可检查的关联，也让历史会话可以恢复已保存的来源。

### 5.6 异步索引与分层存储：不同工作交给不同组件

文档解析、远程向量化和索引写入耗时较长，正常路径由 API 保存上传记录并投递任务，Celery Worker 执行处理。任务有进度与错误字段，失败最多重试 3 次，并使用递增等待间隔。

PostgreSQL 保存业务数据、会话摘要、长期记忆及其 pgvector 向量；Milvus 保存文档检索向量；共享文件目录保存原文件；Redis 负责活跃会话缓存、运行信号与任务消息。上下文和记忆后台任务另有 PostgreSQL 可靠记录，Redis 故障后可以重新派发。备份和迁移需覆盖相应存储，API 与 Worker 的连接和文件路径必须一致。

### 5.7 MCP、认证与密钥：让扩展有明确边界

MCP（模型上下文协议）为 Agent 提供统一的外部工具接入方式。KNOWNEST 将服务连接、工具发现和工具启用分开处理，调用前检查输入结构，并保存调用成功状态、耗时与错误等审计信息。

默认禁止访问私有 MCP 主机与启动 stdio 服务；本地集成可显式配置 `MCP_ALLOW_PRIVATE_HOSTS=true`，stdio 需要 `MCP_ALLOW_STDIO=true`。容器部署也必须显式传入这些设置。容器内的 `localhost` 指容器本身，不能直接代表宿主机上的 MCP 服务。

账号密码通过 SHA-256 预处理后交给 bcrypt；访问令牌使用 JWT；数据库中的模型密钥与服务凭据使用 Fernet 加密。资源接口检查用户与工作空间的归属。这些机制服务于当前账号与工作空间模型，不能据此推断项目已经实现完整的企业 SSO、细粒度 RBAC 或组织成员协作系统。

<a id="development"></a>

## 六、开发、验证与评测

### 6.1 常用验证命令

在项目根目录、已安装后端依赖的 Python 环境中执行：

```powershell
$env:PYTHONPATH = 'backend'
python -m pytest backend/tests -q
python -m app.evaluation_cli --validate-only
docker compose -f docker-compose.python.yml config --quiet
```

前端验证：

```powershell
cd frontend
npm.cmd ci
npm.cmd run type-check
npm.cmd run build
```

前端产物生成在 `frontend/dist/`。`build` 已包含 Vue / TypeScript 检查，单独执行 `type-check` 便于开发时快速定位类型错误。

### 6.2 真实模型联通检查

```powershell
python backend/scripts/verify_model_chain.py
```

脚本会实际请求聊天、DeepSeek、Embedding 和 Rerank 服务，并检查隔离的检索—回答链路。执行前需配置相应密钥，调用可能产生服务商费用；未配置的可选服务探针会报告失败。链路检查使用隔离的 SQLite 与内存向量，不修改已有业务文档，也不能代替对部署中 Milvus 和 Worker 的检查。

### 6.3 评测回答质量，而不仅是检查接口是否通

`dataset/evaluation/` 提供固定的 **120 条 QA 样例**与 **16 个独立场景**，覆盖简单问题、跨文档综合、无答案、冲突版本、表格计算、多轮、工具与降级行为。

```powershell
$env:PYTHONPATH = 'backend'

# 检查数据清单、文件哈希与样例结构，不调用真实模型。
python -m app.evaluation_cli --validate-only

# 仅验证指标计算流程，不代表真实模型质量通过。
python -m app.evaluation_cli --diagnostic-mocks
```

真实评测需要独立的数据库、Milvus 集合、Redis 数据库与上传目录，设置 `KNOWNEST_EVAL_ENV=isolated` 及专用 `KNOWNEST_EVAL_TOKEN` 后运行。使用 `python -m app.evaluation_cli --help` 查看真实评测与历史报告对比参数；评测完成后，还需人工核对高风险失败样例和来源支持程度。评测报告保存在 `output/evaluation/`；样例与评测工具的存在不代表项目已经达到某个准确率或延迟承诺。

### 6.4 接口调试入口

完整路径默认以 `/api/v1` 为前缀。健康与初始化状态等公开入口外，业务请求需携带 `Authorization: Bearer <token>`。

| 用途 | 主要接口 |
| --- | --- |
| 初始化与登录 | `GET /auth/setup-status`、`POST /auth/setup`、`POST /auth/login` |
| 工作空间与知识库 | `/workspaces`、`/knowledge-bases` |
| 切分设置 | `GET /knowledge-bases/{kb_id}/chunking-config`、`PUT /knowledge-bases/{kb_id}/chunking-config` |
| 切分预览 | `POST /chunker/preview` |
| 上传与处理进度 | `POST /knowledge-bases/{kb_id}/documents`、`GET /jobs/{job_id}` |
| 文档重新索引 | `POST /documents/{document_id}/reindex` |
| 搜索与来源 | `POST /knowledge-bases/{kb_id}/search`、`GET /chunks/{chunk_id}/citation` |
| 连续对话 | `/conversations` 及会话消息接口 |
| 独立回答模式 | `/rag/sessions`、`/agent/sessions` 及各自消息接口 |
| 模型、记忆、MCP | `/workspaces/{workspace_id}/models`、`/memories`、`/mcp-servers` 等资源接口 |

上传接口接收**原始文件二进制请求体**，使用 `filename` 查询参数或 `X-Filename` 请求头传递文件名，不能直接按 `multipart/form-data` 的接口示例调用。参数详情参考 [API 文档](backend/API.md)，当前运行版本也可以在 [OpenAPI 页面](http://127.0.0.1:8000/docs) 查看。

<a id="deployment"></a>

## 七、部署、持久化与升级

### 7.1 开发启动与长期部署的区别

当前 Compose 是便于开发的服务编排入口。长期运行前，需要结合实际环境补齐以下内容：

- 设置 `ENVIRONMENT=production`、`REQUIRE_MILVUS=true` 和至少 32 字符的随机 `SECRET_KEY`，并按 3.4 节传入容器。
- 使用自己的数据库凭据，保留既有安装的连接信息、集合名、文件目录与 Compose 项目名。
- 构建前端，使用 Web 服务器托管 `frontend/dist/`；为前端 History 路由配置回退到 `index.html`，为 `/api` 配置反向代理。
- 同域部署可在构建前设置 `VITE_PYTHON_API_BASE=/api/v1`；若前后端分域，则填写实际 API 地址并配置 `CORS_ORIGINS`。
- 对 SSE 接口关闭代理缓冲，并设置适当的流式请求超时，以免浏览器等到生成结束才一次性收到内容。
- 持久化并备份 PostgreSQL、上传目录、Milvus 及其依赖数据，按需求开启 Redis 持久化；部署 HTTPS，并限制基础服务端口的访问范围。

### 7.2 当前 Compose 的持久化边界

基础文件已为上传目录、PostgreSQL、etcd 和 MinIO 配置命名卷，**尚未为 Milvus 自身的 `/var/lib/milvus` 和 Redis 数据配置持久卷**。需要长期保存索引和队列时，可将下面内容合并到自己的覆盖文件：

```yaml
services:
  milvus:
    volumes:
      - knownest-milvus:/var/lib/milvus
  redis:
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - knownest-redis:/data

volumes:
  knownest-milvus:
  knownest-redis:
```

在首次正式入库前完成卷配置更稳妥。已有 Milvus 数据的安装应先备份并迁移容器目录，再切换挂载；直接挂载空卷会使原目录中的数据不可见。多个覆盖片段应合并到同一份 YAML 的 `services` / `volumes` 下，不要重复声明同名顶层键。

### 7.3 常用运行命令

```powershell
# 查看服务与最近日志。
docker compose -f docker-compose.python.yml ps
docker compose -f docker-compose.python.yml logs --tail 100 python-api python-worker

# 停止或恢复已有容器。
docker compose -f docker-compose.python.yml stop
docker compose -f docker-compose.python.yml start

# 代码更新后重新构建应用服务。
docker compose -f docker-compose.python.yml up -d --build python-api python-worker
```

使用了覆盖文件时，所有命令保持相同的 `-f` 文件组合。停机建议使用 `stop`；在补齐持久化前，不要把删除或重建容器当作数据无损操作。不要用删除数据卷的方式解决连接或品牌迁移问题。

### 7.4 从已有版本升级

保留已有 `.env`、`SECRET_KEY`、数据库、上传文件与 Milvus 集合。保留原 `COMPOSE_PROJECT_NAME`，以继续使用已有命名卷；修改项目显示名称不会自动迁移数据库或集合。

后端保留旧密码哈希的验证兼容，升级后可以继续使用原账号。浏览器中的新存储键使用 `knownest_` 前缀，升级后可能需要重新登录。历史 SQLite 数据可使用 `backend/scripts/migrate_sqlite_to_postgres.py` 导入 PostgreSQL，导入前先备份数据，并通过该脚本的 `--help` 核对来源文件与目标连接参数。当前本地运行和容器运行均使用 PostgreSQL，SQLite 只用于隔离测试、诊断及旧数据导入。

<a id="faq"></a>

## 八、常见问题

| 现象 | 排查方向 |
| --- | --- |
| API 启动报数据库连接失败 | 确认 PostgreSQL 已初始化、5432 端口可达；本机连接用 `localhost`，容器内连接用服务名；已有数据库凭据不会被新的环境变量自动改写 |
| 首次启动 API 或 Worker 退出 | Compose 的依赖顺序不等于服务已就绪，查看 PostgreSQL / Milvus 日志后重新启动应用服务 |
| 前端能打开，但请求失败 | 检查 `VITE_PYTHON_API_BASE`、API 端口及 CORS；修改前端环境变量后重启或重新构建 |
| Vite 提示 5173 被占用 | `--strictPort` 会直接报错；停止旧开发服务，或选择新端口并同步配置 CORS |
| 只收到“未配置模型 API Key”提示 | 默认会话使用 `OPENAI_*`；检查实际传入 API 的聊天配置，不要只填写 `DEEPSEEK_API_KEY` |
| 上传后长期停留在 `pending` | Redis 入队成功但没有 Worker 消费时不会回退；确认 `python-worker` 已运行，并使用相同 Redis 与数据库 |
| 本机上传特别慢 | 默认 Compose 不映射 Redis，入队失败后会等待线程处理；完整异步运行需配置本机可达的 Redis 和 Worker |
| 文档变成 `failed` | 查看文档 `parse_error`、任务错误及 Worker 日志；确认文件可解析、Embedding 权限、余额、模型名称与维度正确 |
| 扫描版 PDF 没有可用内容 | 当前使用 pypdf 提取文字，没有 OCR 管线；先将扫描文件转换成含文本的 PDF 或文本文件 |
| DOCX 格式看起来变了 | 当前预览展示提取后的段落和表格文本，不是 Office 版式渲染 |
| 提示重排不可用 | 检查 `/rerank` 地址、密钥、模型和 8 秒检索重排超时；回退排名仍可展示，但排序效果可能变化 |
| 重启后检索效果改变 | 检查是否在 Milvus 不可用时启用了进程内向量回退，或是否重建了未持久化的容器；修复连接后重新索引 |
| 更换切分或 Embedding 后效果不对 | 参数修改不会自动重建所有文档；确认集合维度匹配、没有混用向量，并重建索引 |
| 无法再次“首次初始化” | 系统已经存在用户；初始化仅用于创建首个账号，之后使用登录 |
| MCP 本地服务连接失败 | 检查私有地址访问设置、容器到宿主机的网络地址，以及服务传输类型；连接成功后还需发现并启用工具 |

<a id="repository"></a>

## 九、项目目录与许可

```text
KNOWNEST/
├── backend/
│   ├── app/
│   │   ├── api/routes.py             # HTTP API、聊天流与资源操作
│   │   ├── core/                     # 配置、数据库、凭据加密
│   │   ├── models/                   # SQLAlchemy 数据模型
│   │   ├── services/
│   │   │   ├── parser.py             # 文本提取、切分与预览
│   │   │   ├── ingestion.py          # 文档入库处理
│   │   │   ├── retrieval.py          # 查询规划、BM25、RRF 与重排
│   │   │   ├── vector_store.py       # Milvus 与开发回退
│   │   │   ├── providers.py          # 聊天、Embedding、Rerank 访问
│   │   │   ├── agent.py              # 有边界的工具执行循环
│   │   │   ├── auth.py               # 账号认证
│   │   │   └── mcp.py                # MCP 连接与调用
│   │   ├── workers.py                # Celery 任务入口
│   │   ├── evaluation_cli.py         # 评测入口
│   │   └── retrieval_diagnostic_cli.py
│   ├── scripts/                      # 联通验证、启动与旧数据导入
│   ├── tests/                        # 后端行为测试
│   ├── API.md                        # 接口文档
│   └── requirements.txt
├── frontend/
│   ├── src/api/python-runtime.ts     # API 客户端与事件流处理
│   ├── src/router/                   # 登录与回答模式路由
│   ├── src/components/               # 可复用界面组件
│   ├── src/views/LoginView.vue
│   ├── src/views/python/RuntimeApp.vue
│   └── package.json
├── dataset/evaluation/               # 固定评测语料与质量检查
├── docs/images/                      # README 产品截图
├── docker-compose.python.yml         # 后端及基础依赖编排
├── .env.example                      # 本机环境配置模板
└── README.md
```

项目仓库：[yuanqi975/KNOWNEST](https://github.com/yuanqi975/KNOWNEST)。后端开发入口见 [后端说明](backend/README.md)，接口细节见 [API 文档](backend/API.md)。

项目许可与版权声明以 [LICENSE](LICENSE) 为准，第三方许可文本见 [licenses/](licenses/)。KNOWNEST 的项目名称不改变原有版权归属及第三方许可要求。

---

<p align="center"><strong>KNOWNEST · 让知识留下来，让答案找得到出处。</strong></p>
