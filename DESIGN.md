# 个人知识库问答系统 — 设计方案（v1.1 评审修订版）

> 本文档为该项目的完整技术设计方案，供下一个 AI/开发者基于此文档完成代码编写。
>
> **v1.1 修订说明**：本版在 v1.0 基础上完成了一轮设计评审，主要修正：
> - 移除 `unstructured` 依赖（Windows 构建困难且对 Markdown 冗余），改用 LangChain Community Loaders
> - 明确「端点统一同步 `def` + 线程池」的并发约定，避免阻塞事件循环
> - 前端 SSE 改用 `fetch` + `ReadableStream` / `@microsoft/fetch-event-source`（axios 不支持 SSE）
> - 明确流式问答中 **assistant 消息由后端持久化**，前端只负责渲染
> - 修正检索度量：ChromaDB 显式 `cosine` 空间，阈值默认 0.5（原 0.3 语义错误）
> - 统一响应包裹格式、`document_count` 改为动态计算、`updated_at` 增加刷新机制
> - 补齐安全（路径穿越/魔数校验/默认绑定 127.0.0.1/可选鉴权）、CORS、健康检查、测试策略与 Docker 化
>
> 与 v1.0 的逐条差异见文末「附录 A：修订对照表」。

---

## 1. 项目概述

### 1.1 项目名称
**PersonalKB-QA** — 个人知识库智能问答系统

### 1.2 项目目标
构建一个本地可运行的个人知识库问答系统。用户可以上传文档（PDF、TXT、Markdown、Word 等），系统自动解析、分块、向量化存储，然后用户可以用自然语言提问，系统基于 RAG（检索增强生成）技术从知识库中检索相关内容并结合 LLM 生成回答。

### 1.3 核心价值
- 私有化部署，数据不出本地
- 支持多种文档格式
- 智能语义检索 + AI 生成回答
- 知识库可持久化管理

---

## 2. 技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端框架** | React 18 + TypeScript | SPA 单页应用 |
| **UI 组件库** | Ant Design 5 | 高质量 React 组件库 |
| **构建工具** | Vite | 快速开发和构建 |
| **后端框架** | Python 3.11+ FastAPI | 高性能 Web 框架，端点统一同步 `def` |
| **向量数据库** | ChromaDB 0.5.x（`PersistentClient` 嵌入式模式） | 轻量级向量存储，显式 cosine 度量 |
| **Embedding 模型** | sentence-transformers（`text2vec-base-chinese`）或 OpenAI 兼容 API | 输出归一化向量 |
| **LLM** | 支持 OpenAI 兼容 API / 本地 Ollama 模型 | 灵活切换大模型 |
| **文档解析** | LangChain Community Loaders（PyPDF / TextLoader / Docx2txt） | 支持 PDF/TXT/MD/DOCX |
| **数据存储** | SQLite（Python 标准库 `sqlite3`，**不使用 ORM**） | 参数化查询防注入 |

> **说明（重要）**：
> 1. **不引入 `unstructured`**：Markdown 本质是纯文本，直接用 `TextLoader`（或 `Path.read_text`）解析；PDF 用 `pypdf`、DOCX 用 `docx2txt` 即可。`unstructured` 依赖重且在 Windows 上构建困难，去掉它可显著降低安装成本。
> 2. **不用 SQLAlchemy ORM**：数据模型简单（4 张表），用标准库 `sqlite3` + 手写 SQL 更轻量、无依赖负担，且与 §6 的原始 DDL 保持一致。`models/` 目录只放 Pydantic schema（请求/响应模型）。

### 2.1 Embedding 与 LLM 可配置说明
系统通过 `config.yaml` 统一配置：
- **Embedding 模式**：`local`（本地 `text2vec-base-chinese` 模型）或 `openai`（API）
- **LLM 模式**：`openai`（兼容 API）、`ollama`（本地部署）

> **命名统一**：全文统一使用 `shibing624/text2vec-base-chinese`（模型小、下载快、中文效果好），不再混用 `large` 变体。

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    前端 (React + Ant Design)           │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│   │ 知识库管理│  │ 文档上传  │  │ 问答对话  │           │
│   └──────────┘  └──────────┘  └──────────┘           │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP REST API + SSE (CORS)
┌──────────────────────┴───────────────────────────────┐
│                  后端 (FastAPI)                        │
│                                                        │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐   │
│  │文档处理  │ │向量化    │ │检索引擎   │ │LLM 调用   │   │
│  │模块      │ │模块      │ │模块      │ │模块       │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬──────┘   │
│       │             │             │             │         │
│  ┌────┴─────────────┴─────────────┴─────────────┴────┐  │
│  │                   数据层                            │  │
│  │    ┌──────────┐    ┌──────────┐    ┌──────────┐   │  │
│  │    │ ChromaDB │    │  SQLite  │    │ 文件存储  │   │  │
│  │    │(向量存储) │    │(元数据)   │    │(原始文件) │   │  │
│  │    └──────────┘    └──────────┘    └──────────┘   │  │
│  └────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 4. 功能模块详述

### 4.1 知识库管理模块

#### 4.1.1 功能列表
| 功能 | API 路由 | 描述 |
|------|----------|------|
| 创建知识库 | `POST /api/knowledge-bases` | 新建知识库 |
| 获取知识库列表 | `GET /api/knowledge-bases` | 列出所有知识库 |
| 获取知识库详情 | `GET /api/knowledge-bases/{kb_id}` | 查看单个知识库信息与文档数 |
| 删除知识库 | `DELETE /api/knowledge-bases/{kb_id}` | 删除知识库及所有文档、向量、Collection |

#### 4.1.2 数据模型
```
KnowledgeBase:
  - id: str (UUID)
  - name: str (知识库名称)
  - description: str (描述)
  - created_at: datetime
  - updated_at: datetime
  - document_count: int (文档数量)   ← 动态计算：COUNT(documents WHERE kb_id=id)，不入库
```

> **注意**：`document_count` **不存储在表中**（见 §6.2），在 API 响应时通过 `SELECT COUNT(*) FROM documents WHERE kb_id=?` 动态计算，避免数据不一致。

#### 4.1.3 删除知识库的完整动作（重要）
删除知识库时需依次：
1. 删除该 KB 下所有文档的原始文件（`./data/uploads/{kb_id}/` 目录）
2. 删除 SQLite 中的 `documents`、`chat_sessions`、`chat_messages`（靠外键 `ON DELETE CASCADE`）
3. **删除 ChromaDB Collection**：`client.delete_collection(f"kb_{kb_id}")`
4. 最后删除 `knowledge_bases` 记录

---

### 4.2 文档管理模块

#### 4.2.1 功能列表
| 功能 | API 路由 | 描述 |
|------|----------|------|
| 上传文档 | `POST /api/knowledge-bases/{kb_id}/documents` | 上传并处理文档 |
| 文档列表 | `GET /api/knowledge-bases/{kb_id}/documents` | 获取知识库中文档列表 |
| 删除文档 | `DELETE /api/documents/{doc_id}` | 删除文档、原始文件及其向量数据 |
| 重新处理 | `POST /api/documents/{doc_id}/reprocess` | 重新解析和向量化（**先清旧向量再入库**） |

#### 4.2.2 数据模型
```
Document:
  - id: str (UUID)
  - kb_id: str (所属知识库 ID)
  - filename: str (原始文件名)
  - file_path: str (存储路径)
  - file_type: str (pdf/txt/md/docx)
  - file_size: int (字节)
  - chunk_count: int (分块数量)
  - status: str (processing / completed / failed)
  - error_message: str | null
  - created_at: datetime
```

#### 4.2.3 文档处理流水线

```
上传文件 → 校验(类型+大小) → 保存原始文件 → 解析文本 → 文本分块 → 向量化 → 存入 ChromaDB → 更新状态
```

**分块策略**：
- 分块大小（chunk_size）：500 字符
- 重叠大小（chunk_overlap）：50 字符
- 使用 LangChain `RecursiveCharacterTextSplitter`，并**显式指定中文友好分隔符**：
  ```python
  separators = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
  ```
  （默认分隔符是英文导向的，对中文切分质量差，必须覆盖。）

**支持的文件格式及解析器**：

| 格式 | 解析器 | 说明 |
|------|--------|------|
| `.pdf` | `PyPDFLoader` | 依赖 `pypdf` |
| `.txt` | `TextLoader` | — |
| `.md` | `TextLoader`（或 `Path.read_text`） | Markdown 按纯文本处理，**不引入 unstructured** |
| `.docx` | `Docx2txtLoader` | 依赖 `docx2txt` |

**文件校验（安全）**：
- **扩展名白名单**：仅允许 `pdf/txt/md/docx`
- **魔数（Magic Bytes）校验**：不能只信扩展名，需校验文件头（如 PDF 以 `%PDF` 开头、DOCX 以 `PK\x03\x04` 开头）
- **大小限制**：`max_file_size_mb`（默认 50），超限返回 413
- **文件名安全**：剥离路径（`os.path.basename`）、过滤 `../` 与非法字符，落盘时用 `{uuid}_{safe_filename}` 重命名

#### 4.2.4 重新处理（reprocess）流程（重要）
```
1. 校验文档存在且状态非 processing
2. collection.delete(where={"document_id": doc_id})   ← 先删旧向量，避免重复
3. 置 status=processing
4. 重新走「解析 → 分块 → 向量化 → 入库」流水线
5. 更新 status=completed/failed 与 chunk_count
```

---

### 4.3 问答模块

#### 4.3.1 功能列表
| 功能 | API 路由 | 描述 |
|------|----------|------|
| 提问（普通） | `POST /api/knowledge-bases/{kb_id}/chat` | 问答，返回完整回答 |
| 提问（流式） | `POST /api/knowledge-bases/{kb_id}/chat/stream` | 流式 SSE 问答 |
| 聊天历史 | `GET /api/knowledge-bases/{kb_id}/sessions` | 获取会话列表 |
| 某会话记录 | `GET /api/sessions/{session_id}/messages` | 获取历史消息 |

#### 4.3.2 RAG 问答流程

```
用户提问
  ↓
问题向量化 (Embedding)
  ↓
ChromaDB 语义检索 (Top-K 相关文档片段，cosine 度量)
  ↓
过滤 similarity < similarity_threshold 的结果
  ↓
【空检索兜底】若过滤后为 0 条：直接返回「知识库中暂无相关信息」，不调用 LLM
  ↓
构建 Prompt：

  你是一个知识库助手。请根据以下参考资料回答用户问题。
  如果参考资料中没有相关信息，请如实告知。

  参考资料：
  {retrieved_chunks}

  用户问题：{user_question}

  请回答：
  ↓
调用 LLM 生成回答（支持流式 SSE）
  ↓
返回回答 + 引用来源
```

#### 4.3.3 检索参数配置（config.yaml）

```yaml
retrieval:
  top_k: 5                              # 检索返回的片段数
  similarity_threshold: 0.5             # 余弦相似度阈值，低于此值的结果丢弃
  metric: cosine                        # 检索度量：cosine
```

> **度量与阈值说明**：ChromaDB 建 Collection 时显式指定 `hnsw:space = "cosine"`。注意 Chroma 的 `query` 返回的 `distances` 是**余弦距离**（= `1 - cosine_similarity`），因此**相似度 = `1 - distance`**。默认阈值 0.5 表示丢弃余弦相似度 < 0.5 的片段（原 v1.0 的 0.3 过低，会塞入大量无关内容；且若用默认 L2 度量，该阈值语义完全错误）。

#### 4.3.4 数据模型
```
ChatSession:
  - id: str (UUID)
  - kb_id: str (所属知识库)
  - title: str (会话标题，取第一个问题前30字)
  - created_at: datetime
  - updated_at: datetime

ChatMessage:
  - id: str (UUID)
  - session_id: str
  - role: str (user / assistant)
  - content: str (消息内容)
  - sources: list[dict] (引用来源，仅 assistant 消息有)
    每个 source: { content: str, document_name: str, similarity: float }
  - created_at: datetime
```

> **source 字段来源映射**：`source.content` 取自检索结果的 `documents[i]`（chunk 原文），`document_name` 取自 `metadatas[i]["document_name"]`，`similarity = 1 - distances[i]`。

---

### 4.4 系统配置模块

`config.yaml` 结构：

```yaml
# ===== Embedding 配置 =====
embedding:
  mode: local        # local | openai
  local:
    model_name: shibing624/text2vec-base-chinese
    device: cpu
    normalize_embeddings: true   # 输出归一化向量，配合 cosine 度量
  openai:
    api_key: ${OPENAI_API_KEY}   # 支持从环境变量读取，避免明文入库
    base_url: https://api.openai.com/v1
    model: text-embedding-ada-002

# ===== LLM 配置 =====
llm:
  mode: ollama       # openai | ollama
  openai:
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    temperature: 0.7
    max_tokens: 2000
  ollama:
    base_url: http://localhost:11434
    model: qwen2.5:7b
    temperature: 0.7

# ===== 检索配置 =====
retrieval:
  top_k: 5
  similarity_threshold: 0.5
  metric: cosine

# ===== 文档处理配置 =====
document:
  chunk_size: 500
  chunk_overlap: 50
  supported_types: [pdf, txt, md, docx]
  max_file_size_mb: 50

# ===== 服务配置 =====
server:
  host: 127.0.0.1            # 默认仅本机访问；需局域网共享时改 0.0.0.0 并启用鉴权
  port: 8000
  cors_origins: ["http://localhost:5173"]   # Vite 开发服务器跨域白名单

# ===== 安全配置 =====
security:
  api_key: ""                # 留空则不启用；启用后前端需带 X-API-Key 请求头

# ===== 存储配置 =====
storage:
  chroma_persist_dir: ./data/chroma
  upload_dir: ./data/uploads
  sqlite_path: ./data/kb.db
```

> **密钥管理**：`api_key` 支持 `${ENV_VAR}` 形式从环境变量读取，`config.yaml` 不入库真实密钥，避免误提交。

---

## 5. 完整 API 接口设计

### 5.0 统一约定

**统一响应包裹**（所有非流式接口均返回此结构，包括列表/详情）：

```json
// 成功
{
  "code": 0,
  "data": { ... },        // 或 [ ... ]
  "message": "success"
}

// 失败
{
  "code": -1,
  "data": null,
  "message": "错误描述"
}
```

> 前端 API 层（axios）统一解包 `data` 字段；`code !== 0` 时统一抛错提示。下方接口表中的「响应」列均指 **`data` 字段的内容**。

### 5.1 知识库

| 方法 | 路径 | 请求体 | 响应(data) | 描述 |
|------|------|--------|------|------|
| `POST` | `/api/knowledge-bases` | `{name, description?}` | `KnowledgeBase` | 创建 |
| `GET` | `/api/knowledge-bases` | — | `[KnowledgeBase]` | 列表 |
| `GET` | `/api/knowledge-bases/{kb_id}` | — | `KnowledgeBase` | 详情 |
| `DELETE` | `/api/knowledge-bases/{kb_id}` | — | `{ok: true}` | 删除（含 Collection） |

### 5.2 文档

| 方法 | 路径 | 请求体 | 响应(data) | 描述 |
|------|------|--------|------|------|
| `POST` | `/api/knowledge-bases/{kb_id}/documents` | FormData(file) | `Document` | 上传 |
| `GET` | `/api/knowledge-bases/{kb_id}/documents` | — | `[Document]` | 列表 |
| `DELETE` | `/api/documents/{doc_id}` | — | `{ok: true}` | 删除 |
| `POST` | `/api/documents/{doc_id}/reprocess` | — | `Document` | 重新处理 |

### 5.3 问答

| 方法 | 路径 | 请求体 | 响应(data) | 描述 |
|------|------|--------|------|------|
| `POST` | `/api/knowledge-bases/{kb_id}/chat` | `{question, session_id?}` | `ChatMessage`(assistant) | 问答 |
| `POST` | `/api/knowledge-bases/{kb_id}/chat/stream` | `{question, session_id?}` | SSE Stream | 流式问答 |
| `GET` | `/api/knowledge-bases/{kb_id}/sessions` | — | `[ChatSession]` | 会话列表 |
| `GET` | `/api/sessions/{session_id}/messages` | — | `[ChatMessage]` | 历史消息 |

### 5.4 系统

| 方法 | 路径 | 描述 |
|------|------|------|
| `GET` | `/health` | 健康检查：返回服务状态、DB 连接、Chroma 连接、Embedding 模型加载状态 |

### 5.5 流式响应格式（SSE）

```
data: {"type": "thinking", "content": ""}
data: {"type": "token", "content": "根据"}
data: {"type": "token", "content": "参考资料"}
...
data: {"type": "sources", "content": [...]}
data: {"type": "done", "content": "", "message_id": "xxx", "session_id": "xxx"}
```

补充事件类型：

```
data: {"type": "error", "content": "LLM 调用失败：..."}   # 流式中途出错时发送，前端据此提示并终止
```

> **持久化职责（明确约定）**：流式问答中，**后端在 `done` 前自行累积全部 token、将 assistant 消息（含 sources）写入 SQLite**，并在 `done` 事件返回 `message_id` / `session_id`。前端仅负责逐步渲染 token，**不负责持久化**。这样历史记录、会话切换数据才完整。

### 5.6 鉴权（可选）

当 `security.api_key` 非空时，所有 `/api/*` 请求需携带请求头 `X-API-Key`，后端中间件校验，不匹配返回 401。默认关闭。

### 5.7 分页说明（当前版）

- 文档列表 / 会话列表 / 历史消息当前**一次性全量返回**（个人知识库数据量小，可接受）。
- 预留扩展：后续数据量大时，为列表接口增加 `?page=&page_size=` 参数并返回 `{items, total}`。本期不实现。

---

## 6. 数据库设计（SQLite）

### 6.1 ER 图（文字描述）

```
KnowledgeBase  1 ──── N  Document
KnowledgeBase  1 ──── N  ChatSession
ChatSession    1 ──── N  ChatMessage
```

### 6.2 DDL

```sql
CREATE TABLE knowledge_bases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documents (
    id            TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_type     TEXT NOT NULL,
    file_size     INTEGER DEFAULT 0,
    chunk_count   INTEGER DEFAULT 0,
    status        TEXT DEFAULT 'processing',
    error_message TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_sessions (
    id         TEXT PRIMARY KEY,
    kb_id      TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title      TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    sources    TEXT DEFAULT '[]',   -- JSON 序列化的 list[dict]
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

> **`updated_at` 刷新机制**：SQLite 的 `DEFAULT CURRENT_TIMESTAMP` 仅在 INSERT 时生效，UPDATE 时**不会自动更新**。实现时要么在 service 层每次 UPDATE 显式 `SET updated_at = CURRENT_TIMESTAMP`，要么建触发器：
> ```sql
> CREATE TRIGGER trg_kb_updated AFTER UPDATE ON knowledge_bases
> BEGIN UPDATE knowledge_bases SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id; END;
> ```
> （`chat_sessions` 同理。推荐 service 层显式更新，更直观。）
>
> **`document_count` 不入库**：`knowledge_bases` 表**不含** `document_count` 列，该值在 API 层动态 `COUNT`（见 §4.1.2）。
>
> **`sources` 字段**：SQLite 无法存列表，`sources` 以 JSON 字符串存储（`json.dumps` / `json.loads`）。

### 6.3 ChromaDB 使用规范

- **Collection 命名**：每个知识库对应一个 Collection：`kb_{kb_id}`
- **度量空间**：创建时显式指定余弦：
  ```python
  client = chromadb.PersistentClient(path=config.storage.chroma_persist_dir)
  collection = client.get_or_create_collection(
      name=f"kb_{kb_id}",
      metadata={"hnsw:space": "cosine"}
  )
  ```
- **入库**：**必须显式传入 `embeddings=`**（用 `embedding_service` 计算），否则 Chroma 会使用其默认模型（自动联网下载，破坏本地一致性）：
  ```python
  collection.add(
      ids=[chunk_id, ...],
      embeddings=[vec, ...],          # 必须显式
      documents=[chunk_text, ...],
      metadatas=[{"document_id": doc_id, "document_name": filename}, ...]
  )
  ```
- **检索**：`similarity = 1 - distance`（cosine 空间下 `distances` 为余弦距离）：
  ```python
  res = collection.query(query_embeddings=[q_vec], n_results=top_k)
  # res["distances"][0][i] → 余弦距离；相似度 = 1 - 距离
  ```
- **按文档删除**：`collection.delete(where={"document_id": doc_id})`（删除文档 / reprocess 前使用）
- **删除知识库**：`client.delete_collection(f"kb_{kb_id}")`

---

## 7. 前端页面设计

### 7.1 路由结构

```
/                          → 重定向到 /knowledge-bases
/knowledge-bases           → 知识库列表页
/knowledge-bases/:id       → 知识库详情页（文档列表 + 问答入口）
/knowledge-bases/:id/chat  → 问答对话页
```

### 7.2 页面设计

#### 7.2.1 知识库列表页
- 顶部导航栏，左侧 Logo + 标题"个人知识库问答"
- 卡片网格展示知识库，每张卡片显示：名称、描述、文档数、创建时间
- "新建知识库"按钮 → 弹出 Modal，填写名称和描述
- 点击卡片进入知识库详情页
- 卡片上支持删除操作（二次确认）

#### 7.2.2 知识库详情页
- 左侧面板：文档列表
  - 支持上传文档（拖拽 + 点击上传）
  - 显示文档名、类型、状态（processing/completed/failed）、分块数、上传时间
  - 支持删除文档
  - 上传进度条
- 右侧面板：问答入口 + 近期会话列表
  - "开始提问"按钮 → 进入问答页
  - 历史会话列表，点击可继续对话

#### 7.2.3 问答对话页
- 左侧边栏：当前知识库的历史会话列表（可切换、新建）
- 右侧主区域：Chat 界面
  - 消息列表（用户消息靠右，AI 消息靠左，带引用来源折叠展示）
  - 流式输出效果（逐字显示）
  - 底部输入框 + 发送按钮
  - 支持 Enter 发送，Shift+Enter 换行
- 顶部显示当前知识库名称，可返回知识库详情

### 7.3 组件树

```
App
├── Layout (Ant Design Layout)
│   ├── Header (Logo + 标题 + 导航)
│   └── Content
│       ├── KnowledgeBaseList (知识库列表)
│       │   ├── KnowledgeBaseCard[] (知识库卡片)
│       │   └── CreateKBModal (新建弹窗)
│       │
│       ├── KnowledgeBaseDetail (知识库详情)
│       │   ├── DocumentPanel (文档面板)
│       │   │   ├── UploadArea (上传区域)
│       │   │   └── DocumentList (文档列表)
│       │   │       └── DocumentItem[] (文档项)
│       │   └── QuickStartPanel (快速开始面板)
│       │       └── SessionList (会话列表)
│       │
│       └── ChatPage (问答页)
│           ├── SessionSidebar (会话侧边栏)
│           ├── MessageList (消息列表)
│           │   └── MessageBubble[] (消息气泡)
│           └── InputArea (输入区域)
```

### 7.4 流式 SSE 前端实现（重要）

axios **不支持** SSE 增量流式读取，前端使用以下方案之一：

- **方案 A（推荐）**：`@microsoft/fetch-event-source`（支持 POST + SSE，API 简洁）
- **方案 B**：原生 `fetch` + `ReadableStream` + `TextDecoder`，手动按行解析 `data:` 事件

> REST 接口继续用 axios；仅流式问答接口用上述方案。前端收到 `type: "error"` 时终止渲染并提示。

---

## 8. 后端项目结构

```
backend/
├── main.py                    # FastAPI 入口：注册路由、CORS、鉴权中间件、/health
├── config.py                  # 配置加载（读取 config.yaml，支持 ${ENV_VAR} 展开）
├── config.yaml                # 配置文件
├── requirements.txt           # Python 依赖
├── database.py                # SQLite 连接 & 初始化（sqlite3 标准库，非 ORM）
│
├── models/                    # Pydantic 模型（请求/响应 schema）
│   ├── __init__.py
│   ├── knowledge_base.py      # 知识库 schema
│   ├── document.py            # 文档 schema
│   ├── chat.py                # 聊天 schema
│   └── common.py              # 统一响应包裹 ApiResponse
│
├── routers/                   # API 路由（端点统一同步 def）
│   ├── __init__.py
│   ├── knowledge_base.py      # /api/knowledge-bases
│   ├── document.py            # /api/knowledge-bases/{kb_id}/documents
│   ├── chat.py                # /api/knowledge-bases/{kb_id}/chat
│   └── system.py              # /health
│
├── services/                  # 业务逻辑
│   ├── __init__.py
│   ├── kb_service.py          # 知识库 CRUD
│   ├── document_service.py    # 文档处理流水线
│   ├── embedding_service.py   # Embedding 服务
│   ├── retrieval_service.py   # 检索服务
│   └── llm_service.py         # LLM 调用服务
│
├── middlewares/               # 中间件
│   ├── __init__.py
│   └── auth.py                # 可选 API Key 鉴权
│
├── utils/                     # 工具函数
│   ├── __init__.py
│   └── file_utils.py          # 文件处理 + 魔数校验 + 文件名清洗
│
├── tests/                     # 单元/集成测试
│   ├── __init__.py
│   ├── test_kb_service.py
│   ├── test_document_service.py
│   ├── test_retrieval.py
│   └── test_chat.py
│
└── data/                      # 数据存储目录
    ├── chroma/                # ChromaDB 持久化
    ├── uploads/               # 上传文件
    └── kb.db                  # SQLite 数据库
```

---

## 9. 前端项目结构

```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts             # 含 dev proxy 到 http://127.0.0.1:8000（或直接用 CORS）
│
├── src/
│   ├── main.tsx                   # 入口
│   ├── App.tsx                    # 根组件 + 路由
│   ├── api/                       # API 调用层
│   │   ├── client.ts             # axios 实例（统一解包 data、附加 X-API-Key）
│   │   ├── stream.ts             # SSE 流式客户端（fetch-event-source）
│   │   ├── knowledgeBase.ts      # 知识库 API
│   │   ├── document.ts           # 文档 API
│   │   └── chat.ts               # 问答 API
│   │
│   ├── types/                     # TypeScript 类型定义
│   │   └── index.ts
│   │
│   ├── pages/                     # 页面组件
│   │   ├── KnowledgeBaseList/
│   │   │   └── index.tsx
│   │   ├── KnowledgeBaseDetail/
│   │   │   └── index.tsx
│   │   └── ChatPage/
│   │       └── index.tsx
│   │
│   ├── components/                # 通用组件
│   │   ├── Layout/
│   │   │   └── index.tsx         # 全局布局
│   │   ├── DocumentUpload/
│   │   │   └── index.tsx         # 文档上传组件
│   │   ├── MessageBubble/
│   │   │   └── index.tsx         # 消息气泡
│   │   ├── ChatInput/
│   │   │   └── index.tsx         # 聊天输入框
│   │   └── SessionSidebar/
│   │       └── index.tsx         # 会话侧边栏
│   │
│   └── styles/
│       └── global.css             # 全局样式
```

---

## 10. 关键实现细节

### 10.0 并发约定（全项目统一，重要）

- **所有路由端点统一使用同步 `def`**（而非 `async def`）。FastAPI 会将同步端点自动放进线程池执行，从而 ChromaDB、SQLite、`openai`/`requests`、torch embedding 等**阻塞调用不会卡住事件循环**。
- 需要并行的阻塞调用时才使用 `await asyncio.to_thread(...)`。
- **禁止**在 `async def` 端点里直接调用同步阻塞代码（会导致整个服务串行卡死）。

### 10.1 文档上传处理流程

```
1. 前端 POST FormData（multipart/form-data）上传文件
2. 后端校验：扩展名白名单 + 魔数校验 + 文件大小
3. 文件名清洗（basename + 过滤非法字符），保存到 ./data/uploads/{kb_id}/{uuid}_{safe_filename}
4. 创建 Document 记录，status=processing
5. 用 BackgroundTasks 启动同步后台任务（在 threadpool 执行，不阻塞响应）：
   a. 根据文件类型选择 Loader 解析文本
   b. RecursiveCharacterTextSplitter（中文分隔符）分块
   c. Embedding 模型向量化（显式传 embeddings）
   d. 存入 ChromaDB Collection（kb_{kb_id}）
   e. 更新 Document status=completed, chunk_count=N
6. 处理成功/失败均更新 status（失败写 error_message）
```

### 10.2 问答流程（非流式）

```
1. 接收 question + session_id（可选）
2. 如果无 session_id，创建新 ChatSession，title=question[:30]
3. 存储用户消息（role=user）
4. 调用 embedding_service.embed(question) → 问题向量
5. 调用 retrieval_service.search(kb_id, vector, top_k) → 检索结果
6. 计算 similarity = 1 - distance，过滤低于 similarity_threshold 的结果
7. 若过滤后为 0 条 → 直接返回「知识库中暂无相关信息」，不调用 LLM
8. 构建 Prompt（见 4.3.2）
9. 调用 llm_service.chat(prompt) → 回答文本
10. 存储助手消息（role=assistant, sources）
11. 返回完整 ChatMessage
```

### 10.3 问答流程（流式 SSE）

```
1~8 同 10.2（含空检索兜底）
9. 设置 SSE response headers（EventSourceResponse）
10. 调用 llm_service.chat_stream(prompt) → 逐 token yield
11. 每收到 token，向后端累积并向前端推送：
    event: token
    data: {"type":"token","content":"xxx"}
12. 全部 tokens 完成后：
    a. 后端将累积的完整回答 + sources 写入 assistant 消息（SQLite）
    b. 推送 sources 事件
    c. 推送 done 事件（含 message_id / session_id）
13. 中途异常：推送 {"type":"error","content":"..."} 并终止；前端据此提示
14. 前端仅渲染，不持久化
```

### 10.4 错误处理

| 场景 | HTTP 状态 | 提示 |
|------|-----------|------|
| 文件类型不支持（扩展名/魔数） | 400 | 支持的文件格式：pdf/txt/md/docx |
| 文件过大 | 413 | 文件超过大小限制 |
| 文档解析失败 | — | Document.status=failed + error_message |
| Embedding 失败 | 500 | 模型配置或加载问题 |
| LLM 调用失败 | 500 | 检查 API Key 或服务状态 |
| ChromaDB 错误 | 500 | 向量数据库异常 |
| 未鉴权（启用时） | 401 | API Key 无效 |

- 所有错误均走统一响应包裹 `{code:-1, data:null, message:...}`。
- 流式接口中途错误走 SSE 的 `error` 事件。

---

## 11. 依赖清单

### 11.1 Python (requirements.txt)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9
chromadb==0.5.5
langchain==0.3.0
langchain-community==0.3.0
langchain-text-splitters==0.3.0
pypdf==4.3.1
docx2txt==0.8
sentence-transformers==3.0.1
openai==1.45.0
httpx==0.27.0
pyyaml==6.0.2
python-dotenv==1.0.1
aiofiles==24.1.0
sse-starlette==2.1.0
pytest==8.3.0            # 仅测试用
```

> **已移除**：`unstructured`（Windows 构建困难且对本项目冗余）、`sqlalchemy`（改用标准库 sqlite3）。
>
> **安装提示**：`sentence-transformers` 会连带安装 `torch`，体积较大（CPU 版约 2GB+）；本地 `local` embedding 模式首次运行会下载 `text2vec-base-chinese` 模型（约 400MB）。若仅用 `openai` embedding 模式，可将 `sentence-transformers` 改为可选依赖。

### 11.2 前端 (package.json dependencies)

```json
{
  "react": "^18.3.1",
  "react-dom": "^18.3.1",
  "react-router-dom": "^6.26.0",
  "antd": "^5.20.0",
  "@ant-design/icons": "^5.4.0",
  "axios": "^1.7.0",
  "@microsoft/fetch-event-source": "^2.0.1",
  "dayjs": "^1.11.12"
}
```

---

## 12. 开发顺序建议

| 阶段 | 任务 | 预估工作量 |
|------|------|-----------|
| **Phase 1** | 项目初始化：后端 FastAPI 骨架（含 CORS、/health、统一响应包裹）+ 前端 Vite 项目 | 小 |
| **Phase 2** | 配置系统（含 `${ENV_VAR}` 展开）+ SQLite 初始化 + 知识库 CRUD API（含动态 document_count） | 中 |
| **Phase 3** | 文档上传 + 校验（魔数/大小/文件名）+ 解析 + 中文分块 + 向量化 + ChromaDB（cosine） | 大 |
| **Phase 4** | RAG 检索（余弦阈值过滤 + 空检索兜底）+ LLM 调用 + 问答 API（含流式 SSE） | 大 |
| **Phase 5** | 前端知识库管理页面（列表 + 详情 + 上传） | 中 |
| **Phase 6** | 前端问答对话页面（fetch-event-source 流式） | 中 |
| **Phase 7** | 联调 + 错误处理完善 + 单元测试（pytest）+ 端到端验证 | 中 |

---

## 13. 非功能性需求

1. **性能**：文档处理在后台线程池异步执行，不阻塞 API 响应；端点统一同步 `def` 避免阻塞事件循环
2. **扩展性**：Embedding 和 LLM 通过接口抽象，方便切换不同实现；检索层预留混合检索/重排接口（见 §14.2）
3. **可维护性**：代码分层清晰（router → service → model），类型声明完整，Pydantic schema 统一
4. **安全性**：
   - 文件上传：扩展名 + 魔数双重校验 + 大小限制 + 文件名清洗（防路径穿越）
   - SQL 使用参数化查询防注入
   - 默认绑定 `127.0.0.1`；需局域网共享时提供可选 API Key 鉴权
   - 密钥支持环境变量，不入库
5. **用户体验**：文档上传显示进度，问答支持流式输出，界面响应式适配，空检索给明确反馈

---

## 14. 工程化补充

### 14.1 测试策略

| 层级 | 工具 | 覆盖内容 |
|------|------|----------|
| 单元测试 | pytest | `kb_service`、`document_service`（分块/文件校验）、`file_utils`（魔数/文件名清洗）、统一响应包裹 |
| 检索验证 | pytest + 小样本语料 | 用固定中文语料构建临时 Chroma 集合，验证「检索召回 + 阈值过滤 + 空检索兜底」 |
| 接口测试 | FastAPI TestClient | 知识库/文档/问答各接口的 200/400/404/413/500 路径 |

> 检索质量建议额外做一次**手工/脚本抽检**：准备 10~20 条中文问题，核对 Top-K 召回的 chunk 是否相关，据此微调 `chunk_size` / `similarity_threshold`。

### 14.2 后续增强项（本期不实现，预留接口）

- **混合检索**：向量检索 + BM25 关键词检索融合（适合含精确术语/编号/代码的知识库）
- **重排（Rerank）**：对 Top-K 结果用重排模型精排，提升排序质量
- **分页**：列表接口加 `page/page_size`（§5.7）
- **文档增量更新**：文件内容变更检测

### 14.3 部署（Docker，可选）

本地直接 `uvicorn main:app` 即可运行；如需容器化：

```dockerfile
FROM python:3.11-slim
# 前端构建产物由 Vite build 后放入 backend/static，由 FastAPI 托管（或用 nginx）
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> 注意：`torch` 体积大，建议 Docker 镜像使用分层缓存；生产部署建议 GPU 版 torch（`local` embedding 模式下）。

---

## 附录 A：v1.1 修订对照表

| # | v1.0 问题 | v1.1 修正 |
|---|-----------|-----------|
| 1 | 用 `unstructured` 解析 Markdown，Windows 构建困难 | 移除 `unstructured`，Markdown 用 `TextLoader` |
| 2 | 未约定异步/同步，阻塞调用可能卡事件循环 | 明确「端点统一同步 `def` + 线程池」约定（§10.0） |
| 3 | axios 不支持 SSE | 前端改用 `fetch-event-source`（§7.4、§11.2） |
| 4 | 流式 assistant 消息持久化责任矛盾 | 明确后端持久化、前端只渲染（§5.5、§10.3） |
| 5 | `similarity_threshold: 0.3` 语义错误（默认 L2） | 显式 cosine 度量，阈值默认 0.5，相似度=1-distance（§4.3.3、§6.3） |
| 6 | ChromaDB 版本 API 未说明 | 明确 `PersistentClient` + 显式 `embeddings=`（§6.3） |
| 7 | `document_count` 模型有、表无 | 改为动态 `COUNT`，不入库（§4.1.2、§6.2） |
| 8 | 统一响应包裹与接口表裸对象矛盾 | 明确所有非流式接口统一包裹（§5.0） |
| 9 | `text2vec-large` 与 `base` 混用 | 统一为 `text2vec-base-chinese` |
| 10 | 依赖列了 SQLAlchemy 但用原生 DDL | 移除 SQLAlchemy，用标准库 sqlite3，models/ 仅放 Pydantic schema |
| 11 | `updated_at` 不会自动刷新 | 补充触发器/显式更新机制（§6.2） |
| 12 | 分块分隔符英文导向 | 显式中文分隔符（§4.2.3） |
| 13 | reprocess 未清旧向量 | 明确先 `collection.delete(where=...)`（§4.2.4） |
| 14 | 删除 KB 未提删 Collection | 明确 `delete_collection`（§4.1.3） |
| 15 | 无空检索兜底 | 增加「0 条则不调 LLM」（§4.3.2） |
| 16 | source.content 来源未说明 | 明确来自检索结果 documents 字段（§4.3.4） |
| 17 | 无鉴权 + 绑定 0.0.0.0 | 默认 127.0.0.1 + 可选 API Key（§4.4、§5.6） |
| 18 | 文件名校验不足 | 魔数 + 路径穿越防护（§4.2.3） |
| 19 | SSE 缺 error 事件 | 补充 `error` 事件（§5.5） |
| 20 | 无 CORS 配置 | 增加 `cors_origins` + 中间件（§4.4、§8） |
| 21 | 无健康检查 | 增加 `/health`（§5.4） |
| 22 | 无测试策略 | 增加 §14.1 测试策略 + tests/ 目录 |
| 23 | 无部署方案 | 增加 §14.3 Docker（可选） |
| 24 | 无混合检索/重排规划 | 增加 §14.2 后续增强项（预留接口） |
