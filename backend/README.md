# 后端说明

这里是 WorkMemory Agent 的 FastAPI 后端。

## 当前能力

- 健康检查：`GET /health`、`GET /api/health`。
- 配置状态：`GET /api/settings/status`，不暴露 API Key。
- SQLite + SQLAlchemy，本地数据目录自动创建。
- 安全上传原始文件，并保存文档元数据。
- 项目创建与文档库管理。
- 手动解析文件到 `data/parsed/`。
- 手动切块到 SQLite `document_chunks`。
- 手动 Embedding + Chroma 索引。
- 向量来源检索：`POST /api/retrieval/search`。
- Stateless RAG Answer：`POST /api/rag/search`。
- 持久化 Chat：`POST /api/chat`。
- 手动结构化 Memory。
- Memory SQLite 词法检索。
- 手动 Conversation Summary。
- 请求级可选 Auto Summary Refresh。

## 启动

必须从项目根目录运行：

```bat
.venv\Scripts\python -m uvicorn backend.app.main:app --reload
```

后端只读取项目根目录的 `.env`。`.env.example` 仅作为示例，不会被运行时加载。

## 本地 smoke 配置

如果只是本地测试完整流程，建议在 `.env` 中使用：

```env
EMBEDDING_PROVIDER=fake
LLM_PROVIDER=fake
AUTO_SUMMARY_ENABLED=true
```

如果使用真实 OpenAI-compatible provider，`EMBEDDING_PROVIDER=openai` 或 `LLM_PROVIDER=openai` 时必须配置 `OPENAI_API_KEY`。

## 删除语义

- 文档归档：只改 `documents.status=archived`。
- 文档恢复：只改 `documents.status=uploaded`。
- 文档硬删除：删除原始文件、parsed 文件、parse/chunk/index 记录、Chroma vectors 和 documents 记录。
- 删除文件前会校验 resolved path 仍在 `data/files` 或 `data/parsed` 下。

## 重要边界

- Conversation Summary 不是 Memory。
- Summary 不进入 Memory 页面。
- Summary 不参与 `/api/memory/search`。
- Summary 不做 Embedding 或 Chroma indexing。
- Memory 不会被 Chat/RAG 自动创建。
- parsed text、chunk content、embedding vector 不通过公开 API 直接返回。
- 没有后台任务队列、流式输出、GraphRAG、多用户权限。

## 数据库迁移说明

当前不引入 Alembic，仍使用 `Base.metadata.create_all()`。

如果开发环境 SQLite 里已经存在旧版不兼容表，例如旧版 `memories` 或 `conversation_summaries`，`create_all()` 不会自动迁移。开发环境可以重置一次性数据库，但代码不会静默删除或改写用户数据。

## 测试

从项目根目录运行：

```bat
.venv\Scripts\python -m pytest backend\app\tests
```

测试应使用测试 SQLite，不应污染 `data/sqlite/workmemory.db`。
