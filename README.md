# WorkMemory Agent

WorkMemory Agent 是一个本地优先的桌面级工作知识库应用。当前项目已经从工程骨架推进到可运行 MVP：用户可以上传工作资料或粘贴文本，系统会自动解析、切块、索引到 Chroma，然后在 Chat 页面用 RAG 方式提问，并保存本地对话历史。

当前定位仍然是“本地优先 RAG 工作知识库”，不是 autonomous agent。项目刻意保持边界：不做自动执行任务，不做多用户权限，不自动抽取长期记忆，不做 GraphRAG。

## 推荐环境

- Windows 10/11
- Python 3.11
- Node.js 20 LTS 或 22 LTS
- npm workspace

## 技术栈

- 桌面端：Electron + React + TypeScript + Vite
- 后端：Python FastAPI
- 本地数据库：SQLite
- ORM：SQLAlchemy
- 数据库迁移：Alembic
- 向量库：Chroma
- 文件解析：PyMuPDF、python-docx、pandas、openpyxl、xlrd
- Embedding：OpenAI-compatible API 或 fake provider
- LLM：OpenAI-compatible Chat API 或 fake provider
- 前后端通信：HTTP API + Chat SSE streaming

## 当前已实现能力

### 1. 基础工程

- 可以从项目根目录启动后端。
- 后端只读取项目根目录 `.env`，不读取 `.env.example`。
- `.env.example` 只作为示例说明，真实密钥不得提交。
- `init_db()` 使用 Alembic 执行数据库迁移；空数据库会 `upgrade head`，当前完整旧 schema 会安全 `stamp head`。
- 应用启动会确保以下目录存在：
  - `data/`
  - `data/files/`
  - `data/parsed/`
  - `data/sqlite/`
  - `data/vector_db/`
  - `data/logs/`
  - `data/cache/`
- FastAPI CORS 仅允许本地开发地址：
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
- Electron 使用安全默认配置：
  - `nodeIntegration=false`
  - `contextIsolation=true`
  - 使用 `preload.ts`
  - React 渲染进程通过 HTTP API 访问后端，不直接访问 Node.js API

### 2. Settings

Settings 页面可以显示：

- 后端连接状态。
- 应用版本、环境、时区。
- SQLite 状态。
- Alembic migration 状态：current revision、head revision、是否 up to date。
- 数据目录路径。
- Provider 配置摘要。
- Chroma collection、persist path。
- indexed document count、vector count。
- Provider Diagnostics：手动测试 LLM 和 Embedding provider 连通性。
- Index Diagnostics：查看 Chroma dimension、DB dimension、provider/model 分布和最近索引失败。
- Reset Index：安全清理当前 Chroma collection 和 embedding result 元数据。
- Pipeline worker 状态：是否运行、worker id、concurrency、lease timeout。
- 自动摘要相关配置。

Settings 和诊断接口都不会展示 `OPENAI_API_KEY` 明文。

### 3. Projects

已实现：

- 创建项目。
- 查看项目列表。
- 项目名称 trim。
- 空名称返回 400。
- 名称最大 100 字符。
- 描述最大 1000 字符。
- 同名项目返回 409。

未实现：

- 项目编辑。
- 项目删除。
- 项目成员。
- 权限控制。

### 4. Documents

Documents 页面已经支持文档库管理闭环。

已实现：

- 拖拽上传或选择文件上传。
- 粘贴文本入库。
- 上传文件后自动触发后端 Pipeline，执行 Parse、Chunk、Index。
- 粘贴文本后自动保存为本地 `.md` 文档，并触发后端 Pipeline。
- 显示 Pipeline 状态：`queued`、`running`、`succeeded`、`failed`、`canceled`。
- 显示 Pipeline 当前步骤和阶段级进度百分比。
- Pipeline 已改为 SQLite-backed 本地持久任务队列，由后端 worker 轮询领取任务。
- Pipeline job 使用 `locked_by`、`lock_expires_at` 和 `heartbeat_at` 做轻量 lease，降低后端重启或 worker 异常后的卡死风险。
- Pipeline Jobs 面板可以查看任务事件时间线，包括 queued、claimed、step_started、step_completed、failed、succeeded、canceled 等事件。
- queued job 支持调整 priority，priority 越高越优先执行。
- 对 queued/running job 支持取消；running job 不强杀线程，会在当前步骤完成后停止后续步骤。
- 对 failed/canceled job 支持 Retry，会创建一个新的 job。
- 对 succeeded job 支持 Reprocess，会创建一个新的 job，重新执行 Parse -> Chunk -> Index。
- Documents 页面内置 Pipeline Jobs 任务面板，可集中查看最近任务、错误原因、当前步骤、进度和更新时间。
- 支持 `Process missing documents`，批量为 uploaded 且未 indexed 或 index failed 的文档创建 Pipeline job。
- 上传/粘贴前会显示 provider 配置风险，例如 embedding API Key 缺失。
- 上传或粘贴文本时可以选择项目。
- 不选择项目时保存为未归档文档。
- 项目筛选。
- 状态筛选。
- 分页。
- 归档。
- 恢复。
- 永久删除。
- 保留手动 Parse，用于失败后重试。
- 保留手动 Chunk，用于失败后重试。
- 保留手动 Index，用于失败后重试。

说明：`/api/upload` 和 `/api/documents/text` 仍然只负责创建文档记录；Documents 页面随后调用 `/api/documents/{document_id}/pipeline`，由后端统一执行 Parse -> Chunk -> Index。任务中心里的 Retry/Reprocess/Process missing documents 只是创建新的 Pipeline job，不会直接在前端串联调用 Parse、Chunk、Index。

支持文件类型：

- `.txt`
- `.md`
- `.pdf`
- `.docx`
- `.csv`
- `.xlsx`
- `.xls`

文件安全策略：

- 原始文件名只用于展示。
- 原始文件实际保存为 `document_id + 原扩展名`。
- 原始文件保存到 `data/files/YYYY/MM/{document_id}{ext}`。
- parsed text 保存到 `data/parsed/YYYY/MM/{document_id}.txt`。
- 数据库只保存相对 `data/` 的相对路径，不保存机器相关绝对路径。
- 删除原始文件前会校验 resolved path 仍在 `data/files` 下。
- 删除 parsed text 前会校验 resolved path 仍在 `data/parsed` 下。
- 上传时按扩展名白名单校验，扩展名统一转小写。
- MIME 只记录客户端 Content-Type，不作为安全判断依据。
- 文件保存和 SHA256 计算使用分块流式处理。
- 文件系统和数据库写入有补偿清理，避免常规场景下生成孤儿文件。

文档状态：

- `uploaded`
- `archived`

注意：`documents.status` 只表示文档管理状态，不表示 parse/chunk/index 状态。解析状态看 `document_parse_results`，切块状态看 `document_chunk_results`，索引状态看 `document_embedding_results`。

### 5. Parse

已实现解析：

- `POST /api/documents/{document_id}/parse`
- `GET /api/documents/{document_id}/parse`

解析规则：

- archived 文档不允许解析。
- 解析前重新计算原始文件 SHA256。
- 当前原始文件 SHA256 必须等于 `documents.sha256`。
- 已有 `parsed` 且 `source_sha256 == documents.sha256` 时复用结果。
- `failed` 结果允许重试。
- parsed 输出先写临时文件，再 atomic replace 到最终路径。
- 解析失败会 upsert failed parse_result。
- 失败时不返回 Python stack trace，详细错误只写日志。

解析限制：

- `MAX_PARSE_CHARS`
- `MAX_PARSE_PAGES`
- `MAX_PARSE_ROWS`
- `MAX_PARSE_SHEETS`

API 不返回 parsed text 正文。

### 6. Chunking

已实现手动切块：

- `POST /api/documents/{document_id}/chunks`
- `GET /api/documents/{document_id}/chunks`
- `GET /api/chunks`
- `GET /api/chunks/{chunk_id}`

切块规则：

- 只读取已经 parsed 的 parsed text 文件。
- 校验 parsed 文件路径在 `data/parsed` 下。
- 校验 parsed 文件 SHA256 等于 `parse_result.content_sha256`。
- 清洗规则 deterministic v1：
  - 统一换行。
  - 移除控制字符。
  - 去除行尾空白。
  - 压缩过多空行。
- 切块器为 deterministic v2：优先按 Markdown 标题和段落空行边界组块，单个长段落再退回字符边界切分。
- 清洗后文本为空视为成功，`chunk_count=0`。
- 重新 chunk 前删除旧 chunks。
- 删除旧 chunks、插入新 chunks、写 chunk_result 在同一事务里完成。
- 超过 `MAX_CHUNKS_PER_DOCUMENT` 时截断并标记 `truncated=true`。

公开列表 API 默认不返回 chunk 正文。当前为了前端“展开引用查看整块内容”，增加了 `GET /api/chunks/{chunk_id}`，该接口会返回单个 chunk content，但会拒绝 archived 文档对应 chunk。

### 7. Embedding 与 Chroma Index

已实现手动索引：

- `POST /api/documents/{document_id}/index`
- `GET /api/documents/{document_id}/index`
- `GET /api/index/status`
- `GET /api/index/diagnostics`
- `POST /api/index/maintenance/reset`
- `POST /api/providers/embedding/test`
- `POST /api/providers/llm/test`

索引规则：

- 只允许 `uploaded + parsed + chunked` 文档索引。
- 按 `chunk_index asc` 读取 `document_chunks.content`。
- 空 content chunk 不写入 Chroma。
- `chunk_set_sha256` 固定按以下字段计算：
  - `chunk_id`
  - `content_sha256`
  - `chunk_index`
  - `char_start`
  - `char_end`
- 不直接拼接完整 chunk content 计算整体 fingerprint。
- 已 indexed 且 `chunk_set_sha256/provider/model` 一致时复用旧结果。
- fingerprint、provider 或 model 不一致时重新索引。
- 重新索引会清理旧 vectors：
  - 优先使用 `vector_ids_json`。
  - 解析失败时 fallback 到 Chroma metadata filter `document_id`。
- 同一 Chroma collection 不允许混用不同 embedding dimension。
- Chroma upsert 成功但 DB 写入失败时，会尝试删除本次 upsert 的 vector ids。
- Provider 诊断只在用户手动点击时调用真实 provider，不会在启动、上传或 Pipeline 中自动触发。
- DashScope 场景会对 `EMBEDDING_MODEL=qwen3-max` 这类 chat model 错配给出明确提示，建议 embedding 使用 `text-embedding-v4` 等 embedding 模型。
- Reset Index 只清理当前 `CHROMA_COLLECTION_NAME` 对应的 Chroma vectors 和 `document_embedding_results`，不删除 documents、原始文件、parsed text、chunks、对话或 memory。

支持 provider：

- `openai`：OpenAI-compatible embeddings API。
- `fake`：仅用于测试和本地 smoke，不推荐真实使用。

### 8. Retrieval

已实现来源检索：

- `POST /api/retrieval/search`

检索规则：

- 默认只返回 `documents.status == uploaded` 的结果。
- archived 文档不参与检索结果。
- Chroma metadata filter 只作为第一层过滤。
- Chroma 命中后必须回查 SQLite 二次校验：
  - document 存在。
  - document.status == uploaded。
  - chunk 存在。
  - embedding_result.status == indexed。
  - 命中 metadata 中的 `chunk_set_sha256` 与当前 embedding_result 一致。
- 因为二次过滤可能丢弃结果，最终 items 数量允许小于 top_k。
- `score = 1 / (1 + max(distance, 0))` 仅作为 UI 友好分数，不是严格百分比相似度。

Retrieval API 不返回 chunk content、parsed text 或 embedding vector。

### 9. RAG Answer

已实现 stateless RAG Answer：

- `POST /api/rag/search`

行为：

- 基于 Retrieval 结果读取服务端内部 chunk content。
- 可选 query rewrite：当 `RAG_QUERY_REWRITE_ENABLED=true` 时，会先用 LLM 将问题改写为检索 query；provider 未配置或改写失败时自动回退原始 query。
- 构建 RAG prompt。
- 调用 OpenAI-compatible Chat API 或 fake LLM。
- 返回 answer 和 sources。
- 返回 `query_used` 和 `query_rewritten` 供诊断。
- sources 只返回 excerpt，不返回完整 chunk content。
- 无检索来源时直接返回“知识库中没有找到足够依据。”，不调用 LLM。
- Prompt 要求模型只能基于 sources、memory context、conversation context 回答。
- 文档引用使用 `【1】`、`【2】`。
- Memory 引用使用 `【M1】`、`【M2】`。

`POST /api/rag/search` 是 stateless，不保存 conversation/message，不读取 conversation summary。

### 10. Chat

Chat 页面是当前主交互入口。

已实现：

- ChatGPT 风格左侧历史对话列表。
- 中间消息流。
- 底部输入框。
- Enter 发送。
- Shift+Enter 换行。
- 默认调用真实 Chat/RAG，保存对话历史。
- 支持 SSE 流式输出。
- 支持前端 Stop generating；中断时不保存不完整 assistant message。
- AI 思考时有等待动画。
- AI 回答生成中会实时追加文本。
- 回答完成后保存 user message 和 assistant message。
- assistant message 保存 provider、model、sources。
- 支持重新生成当前最新 assistant answer。
- 支持复制 answer。
- 支持复制文档引用和 Memory 引用。
- 支持对话重命名。
- 支持对话删除；会同时删除该 conversation 的 messages 和 summary。
- sources 默认展示紧凑摘要：
  - `【1】：摘要内容--filename.md`
  - `【2】：摘要内容--filename.md`
- 每个引用可以展开查看详细元数据和完整 chunk。
- Memory source 也可以展开查看完整 memory。

后端接口：

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/conversations`
- `GET /api/conversations/{conversation_id}`
- `PATCH /api/conversations/{conversation_id}`
- `DELETE /api/conversations/{conversation_id}`
- `POST /api/conversations/{conversation_id}/regenerate`
- `GET /api/conversations/{conversation_id}/messages`

当前前端主要使用 `/api/chat/stream`。

### 11. Memory

Memory 页面支持手动维护结构化长期记忆。

已实现：

- 创建 memory。
- 编辑 memory。
- 归档。
- 恢复。
- 筛选。
- 分页。
- SQLite 词法检索。

Memory 类型：

- `note`
- `requirement`
- `decision`
- `rule`

Memory 状态：

- `active`
- `archived`

Memory 规则：

- `source_type` 当前固定为 `manual`。
- `source_ref` 当前为 `null`。
- Chat/RAG 不会自动创建 memory。
- Chat/RAG 只有在请求 `include_memory=true` 时才会检索 active memories 并注入 prompt。
- Chat/RAG 不会注入 archived memories。
- Memory context 在 prompt 中被明确声明为用户保存的事实/背景资料，不是系统指令。

后端接口：

- `POST /api/memory`
- `GET /api/memory`
- `GET /api/memory/{memory_id}`
- `PATCH /api/memory/{memory_id}`
- `PATCH /api/memory/{memory_id}/status`
- `POST /api/memory/search`

### 12. Conversation Summary

已实现手动摘要和保守自动刷新策略。

后端接口：

- `POST /api/conversations/{conversation_id}/summary`
- `GET /api/conversations/{conversation_id}/summary`

已实现：

- 手动生成/刷新 summary。
- summary 成功时 status=`summarized`。
- summary 失败时 status=`failed`，保存简短 error_message。
- Chat 继续对话时只注入 status=`summarized` 且 summary 非空的摘要。
- failed summary 不注入 Chat。
- stale summary 可以注入，但会配合最近消息。
- Summary 只服务 Chat，不属于长期 memory。
- Summary 不会进入 Memory 页面。
- Summary 不参与 `/api/memory/search`。
- Summary 不做 embedding 或 Chroma indexing。

自动刷新：

- 默认关闭：`AUTO_SUMMARY_ENABLED=false`。
- 只有 `.env` 中 `AUTO_SUMMARY_ENABLED=true`，且 Chat 请求携带 `auto_summary=true` 时才会尝试自动刷新。
- 自动刷新发生在 Chat 成功保存消息之后。
- 自动刷新失败不会回滚 Chat 消息。

## 当前未实现能力

以下能力尚未实现，不能按已完成功能理解：

- Celery/Redis/APScheduler 等真正持久化后台任务队列。
- 跨进程 Pipeline worker。
- Pipeline 任务暂停/恢复。
- Pipeline 任务强制终止当前步骤。
- 精确到 token/页/行级别的真实进度百分比。
- 消息编辑。
- 消息删除。
- 真正的多轮工具调用 agent。
- 自动写入长期记忆。
- 自动需求提取。
- 自动会议纪要总结。
- 时间解析，例如“昨天”、“上周”、“最近三天”。
- 时间线问答，例如“上周这个项目做了什么”。
- Memory embedding。
- Memory Chroma indexing。
- 语义化 Memory 检索。
- GraphRAG / Graph-lite。
- 多用户。
- 权限。
- 鉴权。
- 文件全文预览页面。
- parsed text 下载。
- chunk 批量浏览和下载。
- embedding vector 展示。
- Electron 打包安装包的完整发布流程。

## 当前不足和需要改进的地方

### 1. Alembic 已接入，但旧库升级策略仍然保守

第十七阶段已经引入 Alembic。现在 `init_db()` 不再把 `Base.metadata.create_all()` 作为主建表机制，而是按以下规则处理：

- 空 SQLite：执行 `alembic upgrade head`，创建完整当前 schema 和 `alembic_version`。
- 已有当前完整 schema、但没有 `alembic_version`：先做 schema 校验，通过后 `stamp head`，不重建、不删除数据。
- 已有 `alembic_version`：执行 `upgrade head`。
- 已有旧表但字段不兼容：拒绝启动并给出清晰错误，不静默补字段、不静默删除用户数据。

需要注意：

- baseline migration 表达的是当前完整 schema，不负责猜测更早开发库的所有历史变更。
- 如果你的本地 SQLite 来自较早阶段，例如缺少 `document_pipeline_jobs.cancel_requested` 或 `document_pipeline_jobs.progress_percent`，后端会明确报 schema incompatible。
- 开发环境可以先备份 `data/sqlite/workmemory.db`，再 reset DB 或手动补迁移。
- 后续所有表结构变化都应该新增 Alembic revision，不再只改 ORM 模型。

### 2. Pipeline 已有 SQLite 持久队列，但仍是单进程本地 worker

当前自动处理已经收敛到后端 Pipeline，并且 job 状态已经持久化到 SQLite。worker 会通过 SQLite 轮询 queued job，用 `locked_by + lock_expires_at` 做轻量 lease。

影响：

- 后端进程重启时，lock 过期的 running job 会恢复为 queued，避免永久卡死。
- lock 未过期的 running job 会等待 lease 到期，不会被立即抢占。
- 当前仍只有本地进程内 worker，不是 Celery/Redis 这类外部队列。
- 默认并发为 1，避免本地多个大文件同时解析和索引造成资源争用。
- 已有任务取消，但只是步骤边界取消：running job 不会强杀当前 parse/chunk/index 步骤。
- 已有进度百分比，但只是阶段级固定映射，不是按页数、行数、token 数精确计算。
- 已有 job event 时间线，并通过 SSE 实时推送；前端仍保留轮询作为兜底。
- failed/canceled/succeeded 后可以创建新 job 重试或重处理，也支持可见任务的批量取消、批量重试。

后续应增加：

- 更强的外部任务队列或独立 worker 进程。
- 任务取消的细粒度协作机制。
- 进度事件 SSE 推送。
- 更细粒度的任务进度事件和任务取消协作。

### 3. Index 依赖 embedding provider 和 Chroma 状态

Index 失败通常不是前端显示问题，而是后端索引条件不满足。

常见原因：

- `.env` 没有配置 `OPENAI_API_KEY`。
- `EMBEDDING_PROVIDER=openai` 但 base_url/model 不支持 embeddings。
- 使用百炼 DashScope 时没有把 `EMBEDDING_MODEL` 设置为 embedding 模型。
- batch size 超过 provider 限制。
- Chroma collection 中已有不同 dimension 的 vectors。

### 4. Chroma collection 不能混用不同 embedding dimension

同一个 `CHROMA_COLLECTION_NAME` 不允许混用不同 embedding dimension。

如果切换 embedding 模型，例如：

- 从 `text-embedding-3-small` 切到 `text-embedding-v4`
- 从 fake provider 切到真实 provider
- 从一个 embedding 模型切到另一个 embedding 模型

建议同时更换：

```env
CHROMA_COLLECTION_NAME=新的_collection_name
```

或者清理 `data/vector_db` 和对应 DB 记录后重建索引。

### 5. Retrieval 和 RAG 质量依赖 chunk 与 embedding

当前 chunker 已经从简单字符切块升级为 deterministic 的 Markdown/段落边界优先切块；它仍然不是完整结构化文档理解。

影响：

- PDF 解析出来的文本可能顺序不理想。
- 表格内容可能丢失结构。
- 超长段落仍可能被字符边界截断。
- 检索命中可能不稳定。

后续应改进：

- 更强的 Markdown/标题层级切块。
- 表格结构保留。
- PDF 页面号和段落位置信息。
- reranker。
- query rewrite 已有可选开关和失败回退；后续可继续优化 prompt 与评估。
- 项目/文档/时间意图识别。

### 6. Chat 流式输出还没有取消和恢复

当前已实现 SSE 流式输出和前端 Stop generating，但还不完整。

不足：

- Stop generating 通过前端中断请求实现；后端不会保存不完整 assistant message。
- 流式中断后没有断点续传。
- 如果 LLM 在输出中途失败，当前 partial answer 不会保存为正式 assistant message。
- SSE error 是事件级错误，不一定表现为 HTTP 4xx。

### 7. Retrieval API 仍保留为后端能力

前端 Chat 页面已经去掉独立 Sources 模式，只保留正常问答体验。

当前行为：

- Chat 页面：检索来源 + 生成回答 + 保存对话。
- 后端仍保留 `POST /api/retrieval/search`，用于调试、测试和后续内部能力复用。

还可以继续优化：

- 回答旁边默认只展示紧凑引用。
- 如果需要调试检索，可以后续做开发者面板，不放在主 Chat 交互里。
- 引用详情可以做更好的折叠和搜索。

### 8. Memory 仍是手动维护

当前 Memory 是结构化手动记录。

没有实现：

- Chat 自动沉淀 memory。
- 会议纪要自动抽取 decision/requirement/rule。
- Memory embedding。
- Memory 与文档来源的自动关联。

这是有意保守设计。自动写 memory 很容易污染长期记忆，后续需要有审核流。

### 9. 没有权限和加密

当前是本地单用户开发应用。

未实现：

- 登录。
- 多用户隔离。
- 数据库加密。
- 文件加密。
- API 鉴权。

如果要处理敏感工作资料，正式使用前需要补安全方案。

### 10. 前端仍然偏 MVP

已经做过一轮布局优化，但仍有不足：

- Documents 表格在文档很多时还不够高效。
- Pipeline Jobs 已有任务面板、任务优先级、批量取消和批量重试；大量任务场景下的筛选和操作效率还可以继续优化。
- Chat 已有停止生成、重新生成、复制、对话重命名和对话删除；仍缺少消息级编辑/删除和更完整的引用侧边栏。
- Memory 页面可以进一步卡片化和提升扫描效率。
- Settings 已有 provider 连通性测试和 index reset，但还没有诊断历史记录。

## 已经踩过的坑和排查方式

### 1. Windows 下 uvicorn `--reload` 可能残留旧进程

已踩坑现象：

- 前端发消息返回 `Request failed with 404`。
- 后端健康检查正常。
- 但 `/api/chat/stream` 返回 404。
- 本地代码里明明已经有 `/api/chat/stream`。

根因：

- Windows 下 `uvicorn --reload` 会有父子进程。
- 旧 reloader 子进程可能残留并继续占用 8000 端口。
- 前端连到的是旧后端实例，所以新路由不存在。

确认方式：

```bat
curl http://127.0.0.1:8000/openapi.json
```

检查输出里是否包含：

```text
/api/chat/stream
```

如果没有，说明当前 8000 端口不是最新后端。

排查端口：

```bat
netstat -ano | findstr :8000
```

查看 Python 进程：

```powershell
Get-Process python -ErrorAction SilentlyContinue
```

开发时更稳定的启动方式：

```bat
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

先不要同时启动多个 `--reload` 后端实例。

### 2. `Invoke-WebRequest` 对 SSE 可能报 NullReference

已踩坑现象：

- PowerShell `Invoke-WebRequest` 请求 `/api/chat/stream` 报：
  - `Object reference not set to an instance of an object.`

这不是后端接口一定坏了。PowerShell 对 `text/event-stream` 支持不稳定。

建议用：

```bat
curl.exe -i -N http://127.0.0.1:8000/api/chat/stream ...
```

或者直接从桌面端验证。

### 3. curl 在 PowerShell 中 JSON 转义容易错

已踩坑现象：

- curl 请求返回 422。
- 错误是 JSON decode error。

原因：

- PowerShell 字符串转义和 curl 参数组合容易把 JSON 引号弄坏。

稳定测试方式：

```powershell
Set-Content -Path data\cache\chat-stream-test.json -Value '{"query":"ping"}' -Encoding ASCII
curl.exe -i -N -X POST "http://127.0.0.1:8000/api/chat/stream" -H "Content-Type: application/json" --data-binary "@data\cache\chat-stream-test.json"
```

### 4. 使用百炼 DashScope 时 Chat 模型和 Embedding 模型不能混用

已踩坑现象：

- Chat 模型配置为 `qwen3-max`。
- 点击 Index 时报：
  - `Embedding request failed.`
  - DashScope `/embeddings` 返回 400。

原因：

- `qwen3-max` 是 chat model，不是 embedding model。
- Index 调的是 `/embeddings`，必须用 embedding model。

百炼示例配置：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen3-max
LLM_PROVIDER=openai

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_BATCH_SIZE=10
CHROMA_COLLECTION_NAME=workmemory_chunks_dashscope
```

注意：

- `OPENAI_API_KEY` 放在 `.env`，不要写入 README 或代码。
- DashScope `text-embedding-v4` 单批文本数有限，建议 `EMBEDDING_BATCH_SIZE=10`。
- 如果之前用其他 embedding 模型索引过，换模型后建议换新的 `CHROMA_COLLECTION_NAME`。

### 5. OpenAI Base URL 只填到 `/v1`

OpenAI-compatible provider 内部会自动拼接：

- Chat：`{OPENAI_BASE_URL}/chat/completions`
- Embedding：`{OPENAI_BASE_URL}/embeddings`

所以 `.env` 应该这样写：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

不要写成：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

也不要写成：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
```

否则 Chat 或 Embedding 会拼出错误 URL。

### 6. Qwen 的 extra_body / enable_thinking 当前未做配置入口

百炼示例里常见：

```python
extra_body={"enable_thinking": True}
```

当前后端 `llm_provider.py` 只实现了标准 OpenAI-compatible Chat 请求：

- `model`
- `messages`
- `temperature`
- `stream`

还没有把 `extra_body` 做成 `.env` 配置项，也没有针对 Qwen thinking mode 做 UI 开关。

影响：

- 可以正常调用兼容接口。
- 但不能在当前 UI 或 `.env` 中开启/关闭 `enable_thinking`。
- 如果后续要精细控制 Qwen3 thinking，需要新增配置，例如 `OPENAI_EXTRA_BODY_JSON` 或更明确的 `QWEN_ENABLE_THINKING=true`。

### 7. Chat 流式输出当前不记录 usage

非流式 Chat API 可以从 provider 响应里拿 usage。

当前 SSE 流式接口为了简化，只实时拼接 delta，并在完成后保存 answer，不保存 token usage。

影响：

- 对话能保存。
- provider/model 能保存。
- usage 当前为 `null`。

后续如果需要成本统计，需要解析 provider 的 stream final chunk，或者额外做一次 usage 汇总。

### 8. Index 点击后仍显示 not indexed

常见原因：

- 后端没有重启，仍在使用旧 `.env`。
- Index 请求失败，但前端列表刷新后仍显示旧状态。
- `EMBEDDING_PROVIDER=openai` 但 API Key 为空。
- DashScope embedding model 配错。
- Chroma collection dimension mismatch。
- 文档未完成 Parse 或 Chunk。
- 文档已 archived。

排查顺序：

1. 打开 Settings，确认 provider 和 index status。
2. 确认文档状态是 `uploaded`。
3. 确认 Parse 是 `parsed`。
4. 确认 Chunks 是 `chunked`。
5. 查看后端终端或 `data/logs` 中的错误。
6. 如果换过 embedding model，换 `CHROMA_COLLECTION_NAME` 后重启后端再重新 Index。

### 9. `.env.example` 不会生效

`.env.example` 只是示例。

真正运行时只读取：

```text
.env
```

修改 `.env` 后必须重启后端。前端热更新不会让后端重新读取 `.env`。

### 10. Alembic baseline 不会自动修复任意旧库

第十七阶段已经引入 Alembic，但 baseline migration 只描述“当前完整 schema”。如果你的本地 SQLite 是更早阶段留下的旧结构，且字段缺失：

- 代码不会静默修改旧表。
- 代码不会自动删除用户数据。
- `init_db()` 会先做 schema 校验，发现缺字段后拒绝启动。

开发环境可以：

- 先备份 `data/sqlite/workmemory.db`。
- 运行 reset 脚本或手动删除开发库重建。
- 或者补一个明确的 Alembic migration，把旧 schema 升级到当前 schema。

正式环境必须走明确 migration，不允许靠删除数据库解决。

### 11. API Key 不要写进代码或 README

真实密钥只放 `.env`。

不要放在：

- README
- `.env.example`
- 前端代码
- 后端代码
- 测试文件
- 截图

Settings 只显示是否配置，不显示明文。

## 环境变量

复制示例文件：

```bat
copy .env.example .env
```

后端只读取 `.env`。修改 `.env` 后请重启后端。

### 本地 smoke 测试配置

不想调用真实模型时：

```env
EMBEDDING_PROVIDER=fake
LLM_PROVIDER=fake
AUTO_SUMMARY_ENABLED=true
```

fake provider 只用于测试，不推荐真实使用。

### OpenAI-compatible 配置

```env
EMBEDDING_PROVIDER=openai
LLM_PROVIDER=openai
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

### 百炼 DashScope / Qwen 配置

```env
OPENAI_API_KEY=你的百炼APIKey
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen3-max
LLM_PROVIDER=openai

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_BATCH_SIZE=10
CHROMA_COLLECTION_NAME=workmemory_chunks_dashscope
```

说明：

- `OPENAI_MODEL` 用于 Chat/RAG/Summary。
- `EMBEDDING_MODEL` 用于 Index/Retrieval。
- 两者不是同一个用途。
- 更换 embedding model 后，不要复用旧 Chroma collection。

## 启动方式

### 安装依赖

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
npm install
```

### 启动后端

推荐开发稳定启动：

```bat
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

如果需要 reload：

```bat
.venv\Scripts\python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

但 Windows 下如遇 404、端口占用或旧路由，请先排查残留进程。

健康检查：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/api/settings/status`

### 数据库迁移命令

第十七阶段开始使用 Alembic。常用命令：

```bat
.venv\Scripts\python backend\scripts\migrate_db.py
.venv\Scripts\python backend\scripts\check_migrations.py
.venv\Scripts\python -m alembic -c backend\alembic.ini upgrade head
```

说明：

- 后端启动时会自动执行安全迁移流程。
- `migrate_db.py` 等价于手动执行 `upgrade head`。
- `check_migrations.py` 会输出 current revision、head revision、是否 up to date。
- 如果已有旧库 schema 不兼容，代码会拒绝启动；请先备份，再 reset 开发库或补迁移。

### 启动桌面端

```bat
npm run desktop:dev
```

或者：

```bat
npm run dev -w apps/desktop
```

### Windows 脚本

```bat
scripts\dev_start_backend.bat
scripts\dev_start_desktop.bat
scripts\dev_start_all.bat
```

脚本会检查 `.venv`、依赖和 `node_modules`。

## 推荐手动测试流程

### 1. 基础连接

1. 启动后端。
2. 启动桌面端。
3. 打开 Settings。
4. 确认后端连接正常。
5. 确认数据库 ok。
6. 确认 provider 配置符合预期。

### 2. 项目和文档

1. 打开 Projects。
2. 创建一个项目。
3. 打开 Documents。
4. 上传 `sample_docs/sample_requirement.md` 或自己的文件。
5. 等待系统自动显示 Uploading -> Parsing -> Chunking -> Indexing。
6. 确认 Index 列变成 `indexed`。
7. 如果 Pipeline 显示 `failed`，先查看任务面板中的错误；修复配置后点击 Retry 重试。
8. 如果只需要修复某一步，可使用表格中的 Parse / Chunk / Index 高级按钮。

### 3. 粘贴文本入库

1. 打开 Documents。
2. 在 `Paste text into knowledge base` 区域粘贴一段文字。
3. 填写标题。
4. 选择项目或留空。
5. 点击 `Add to Knowledge Base`。
6. 确认文档出现在列表中。
7. 确认 Pipeline 最终为 `succeeded`，Parse/Chunk/Index 状态正确。

### 4. Pipeline 任务中心

1. 打开 Documents。
2. 查看 `Pipeline Jobs` 面板。
3. 上传文件后确认任务从 `queued/running` 进入 `succeeded`。
4. 对 queued/running 任务点击 Cancel。queued 会立即变成 `canceled`，running 会显示 cancel requested 并在当前步骤后停止。
5. 对 `failed` 或 `canceled` 任务点击 Retry，确认会创建新的 job。
6. 对 `succeeded` 任务点击 Reprocess，确认会创建新的 job。
7. 点击 `Process missing documents`，确认未索引或索引失败的 uploaded 文档会批量进入队列。
8. 如果 provider 风险提示显示 `OPENAI_API_KEY is not configured`，说明当前真实 embedding provider 不完整，Index 步骤可能失败。

### 5. Provider 和 Index 诊断

1. 打开 Settings。
2. 在 `Provider Diagnostics` 中点击 `Test Embedding`。
3. 确认返回 ok、dimension 和 latency。
4. 点击 `Test LLM`，确认返回 ok 和 response preview。
5. 在 `Index Diagnostics` 中查看 collection dimension、vector count、DB dimensions 和最近失败。
6. 如果切换过 embedding model 导致 dimension mismatch，可以使用 `Reset Index`。
7. Reset 前必须确认当前没有 queued/running pipeline job。
8. Reset 后回到 Documents，点击 `Process missing documents` 重新索引。

### 6. Chat Answer

1. 打开 Chat。
2. 确认底部模式是 `Answer`。
3. 输入问题。
4. 观察 AI 流式输出。
5. 回答完成后查看引用。
6. 点击引用展开，查看来源详情和完整 chunk。

### 7. Memory

1. 打开 Memory。
2. 创建 note/requirement/decision/rule。
3. 编辑 memory。
4. 归档和恢复。
5. 回到 Chat。
6. 打开 Options。
7. Memory 设为 On。
8. 提问，确认回答可引用 `【M1】`。

### 8. Conversation Summary

1. 在 Chat 中进行多轮对话。
2. 打开 Summary 面板。
3. 点击 Generate / Refresh。
4. 查看 summary、stale、new message count、needs refresh。
5. 如果 `.env` 中启用 `AUTO_SUMMARY_ENABLED=true`，再打开 Auto Summary 后继续提问，观察自动刷新。

## 主要后端 API

健康与配置：

- `GET /health`
- `GET /api/health`
- `GET /api/settings/status`

项目：

- `POST /api/projects`
- `GET /api/projects`

文档：

- `POST /api/upload`
- `POST /api/documents/text`
- `GET /api/documents`
- `GET /api/documents/{document_id}`
- `PATCH /api/documents/{document_id}/status`
- `DELETE /api/documents/{document_id}`

解析：

- `POST /api/documents/{document_id}/parse`
- `GET /api/documents/{document_id}/parse`

切块：

- `POST /api/documents/{document_id}/chunks`
- `GET /api/documents/{document_id}/chunks`
- `GET /api/chunks`
- `GET /api/chunks/{chunk_id}`

索引：

- `POST /api/documents/{document_id}/index`
- `GET /api/documents/{document_id}/index`
- `GET /api/index/status`
- `GET /api/index/diagnostics`
- `POST /api/index/maintenance/reset`

Provider 诊断：

- `GET /api/providers/status`
- `POST /api/providers/embedding/test`
- `POST /api/providers/llm/test`

Pipeline：

- `POST /api/documents/{document_id}/pipeline`
- `GET /api/documents/{document_id}/pipeline`
- `POST /api/documents/{document_id}/pipeline/reprocess`
- `GET /api/pipeline/jobs`
- `GET /api/pipeline/jobs/{job_id}`
- `GET /api/pipeline/jobs/{job_id}/events`
- `GET /api/pipeline/status`
- `POST /api/pipeline/jobs/{job_id}/cancel`
- `POST /api/pipeline/jobs/{job_id}/retry`
- `POST /api/pipeline/jobs/{job_id}/priority`
- `POST /api/pipeline/batch/process-missing`

检索和 RAG：

- `POST /api/retrieval/search`
- `POST /api/rag/search`

Chat：

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/conversations`
- `GET /api/conversations/{conversation_id}`
- `GET /api/conversations/{conversation_id}/messages`
- `POST /api/conversations/{conversation_id}/summary`
- `GET /api/conversations/{conversation_id}/summary`

Memory：

- `POST /api/memory`
- `GET /api/memory`
- `GET /api/memory/{memory_id}`
- `PATCH /api/memory/{memory_id}`
- `PATCH /api/memory/{memory_id}/status`
- `POST /api/memory/search`

## 数据库表概览

当前主要表：

- `alembic_version`
- `projects`
- `documents`
- `document_parse_results`
- `document_chunk_results`
- `document_chunks`
- `document_embedding_results`
- `document_pipeline_jobs`
- `document_pipeline_job_events`
- `conversations`
- `messages`
- `conversation_summaries`
- `memories`

说明：

- `alembic_version` 保存当前数据库迁移 revision。
- `documents` 保存原始文件元数据。
- `document_parse_results` 保存解析结果元数据，不保存 parsed text 正文。
- `document_chunks` 保存 chunk content，供后端 embedding/RAG 内部使用。
- `document_embedding_results` 保存 Chroma 索引结果元数据。
- `document_pipeline_jobs` 保存后端 Parse -> Chunk -> Index pipeline 任务状态、取消标记和阶段级进度。
- `document_pipeline_job_events` 保存 pipeline job 的状态变化和步骤事件，不保存正文、向量或密钥。
- `messages.sources_json` 保存回答来源元数据。
- `conversation_summaries` 是 Chat 上下文摘要，不是长期 memory。
- `memories` 是用户手动维护的长期记忆。

## 测试

后端：

```bat
.venv\Scripts\python -m pytest backend\app\tests
```

前端：

```bat
npm run typecheck -w apps/desktop
npm run build -w apps/desktop
```

最近一次实际验证：

- 后端全量 pytest：`161 passed`
- Alembic 迁移检查：`check_migrations.py` 显示 `current_revision=20260518_0003` 且 `up_to_date=True`
- Alembic CLI：`.venv\Scripts\python -m alembic -c backend\alembic.ini upgrade head` 可重复执行
- Python 依赖检查：`pip check` 通过
- 桌面端 typecheck：通过
- 桌面端 build：通过

## 后续建议优先级

### P0：运行稳定性

1. 后续表结构变化必须补 Alembic revision，并逐步补旧开发库的显式迁移。
2. 增加独立 worker 进程或外部任务队列，承接 Parse/Chunk/Index/Summary。
3. 继续增强 Pipeline 更细粒度进度推送和任务取消协作。
4. 增加 Chroma 多 collection 管理。
5. 增加 provider 真实可用性监控和历史诊断记录。

### P1：Chat 体验

1. 消息编辑/删除。
2. 更完整的引用侧边栏。
3. 流式中断后的恢复策略。
4. 更细粒度的 regenerate 入口，例如指定某条 user message。

### P2：RAG 质量

1. 更强的章节层级 chunker。
2. 表格结构化解析。
3. PDF 页码和页内定位。
4. reranker。
5. query rewrite 质量评估和更细粒度开关。
6. 项目/文档/时间过滤意图识别。

### P3：Memory 与长期知识

1. Memory 审核式自动写入。
2. Memory embedding。
3. Memory 与文档来源关联。
4. 时间线查询。
5. “昨天/上周/最近三天”时间解析。

### P4：生产化

1. 数据加密。
2. API 鉴权。
3. 应用自动更新。
4. Electron 打包安装。
5. 日志管理和错误上报。
6. 数据备份和恢复。
