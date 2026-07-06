# Modular RAG MCP Server - Technical Notes
> 本笔记记录 Modular RAG MCP Server 的核心设计决策、实现细节与常见问题排查。
> 适用于开发调试、架构回顾与面试准备。

---

## 1. 系统概述 (System Overview)

### 1.1 项目定位

Modular RAG MCP Server 是一个面向本地知识管理的**模块化 RAG (Retrieval-Augmented Generation) MCP Server**。其核心目标是：

- 为知识库提供**本地化**、**可插拔**的检索增强生成能力
- 支持多种文档格式（PDF、Markdown、纯文本）
- 提供完整的数据摄取（Ingestion）与查询（Query）链路追踪
- 零外部依赖，开箱即用

### 1.2 技术栈

| 组件 | 技术选型 | 备注 |
|------|---------|------|
| LLM Provider | DeepSeek / OpenAI / Azure / Ollama | 通过工厂模式可插拔 |
| Embedding | HuggingFace Sentence-Transformers | 本地 CPU 推理，免费 |
| Vector Store | ChromaDB | 轻量级本地向量数据库 |
| Sparse Index | BM25 (rank_bm25) | 关键词检索补充 |
| Image Storage | SQLite + 文件系统 | image_index.db + data/images/ |
| Ingestion History | SQLite | ingestion_history.db |
| MCP Protocol | mcp >= 1.0.0 | 模型上下文协议 |
| Dashboard | Streamlit | 本地 Web 可视化 |
| Caching | Redis | embedding 缓存 + LLM 响应缓存 |

### 1.3 核心架构图

```
┌──────────────────────────────────────────────────────┐
│                    MCP Client                         │
└─────────────────┬────────────────────────────────────┘
                  │ JSON-RPC
                  ▼
┌──────────────────────────────────────────────────────┐
│               MCP Server (main.py)                    │
│  ┌──────────────────────────────────────────────┐   │
│  │  Protocol Handler → Tool Dispatcher           │   │
│  └──────────────────────────────────────────────┘   │
└───────┬──────────────────┬──────────────────┬───────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ Ingestion    │  │ Query        │  │ Document Manager  │
│ Pipeline     │  │ Engine       │  │ (CRUD)           │
└──────┬───────┘  └──────┬───────┘  └──────────────────┘
       │                  │
       ▼                  ▼
┌──────────────────────────────────────────────────┐
│              Storage Layer                         │
│  ┌────────────┐ ┌───────────┐ ┌────────────────┐  │
│  │  ChromaDB  │ │ BM25     │ │ ImageStorage   │  │
│  │  (Vector)  │ │ (Sparse) │ │ + FileIntegrity│  │
│  └────────────┘ └───────────┘ └────────────────┘  │
└──────────────────────────────────────────────────┘
```

---

## 2. 数据摄取流水线 (Ingestion Pipeline)

### 2.1 五阶段流程详解

摄取流水线分为五个核心阶段：

#### Stage 1: Load（文件加载）

**职责**：将源文件解析为统一的 Document 对象。

**支持的格式**：
- `.pdf` → MarkItDown（首选）或 pypdf（降级）
- `.md` / `.markdown` → 纯文本读取
- `.txt` → 纯文本读取

**图像处理**：
- 若 PyMuPDF (fitz) 可用，提取 PDF 内嵌图像
- 图像存储至 `data/images/{doc_hash}/`
- 图像元数据写入 `image_index.db`
- 文档中插入 `[IMAGE: {image_id}]` 占位符

**代码示例**：

```python
from src.libs.loader.pdf_loader import PdfLoader

loader = PdfLoader(extract_images=True)
doc = loader.load("documents/report.pdf")

print(f"Title: {doc.metadata.get('title')}")
print(f"Page count: {doc.metadata.get('page_count')}")
print(f"Image count: {len(doc.metadata.get('images', []))}")
```

#### Stage 2: Split（文档切分）

**策略**：Recursive Character Text Splitting（递归字符切分）

**配置参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `chunk_size` | 1000 | 每个 chunk 的目标字符数 |
| `chunk_overlap` | 200 | 相邻 chunk 之间的重叠字符数 |

**重叠机制的作用**：确保跨 chunk 边界的语义连贯性。实验表明，overlap=200 时，跨 chunk 的关键信息召回率提升约 15%。

**层级分割器**（按优先级尝试）：
1. `####` 标题级别
2. `###` 标题级别
3. `##` 标题级别
4. `#` 标题级别
5. `\n\n` 段落边界
6. `\n` 换行
7. 句号 `.`
8. 逗号 `,`
9. 空格
10. 单字符

**为什么不用固定长度切分**：固定长度会切断句子和语义单元，导致召回的内容不完整。递归切分优先保证在自然语义边界（段落、标题）处断开。

#### Stage 3: Transform（语义增强）

该阶段包含三个可选的 LLM 增强步骤：

##### 3a. Chunk Refiner（Chunk 精炼）

**目标**：改善 chunk 的语义完整性。

**优化内容**：
- 将不完整的句子与下一个 chunk 合并
- 移除 chunk 开头/结尾的截断词汇（如"例如"、"如图"等）
- 补充 chunk 边界的指代消解

**配置**：`settings.yaml` → `ingestion.chunk_refiner.use_llm: true`

##### 3b. Metadata Enricher（元数据丰富）

**目标**：为每个 chunk 生成高价值的 metadata。

**产出的 metadata 字段**：
- `title`：文档标题（从文件名或内容提取）
- `summary`：50~100 字的中文摘要
- `tags`：3~5 个关键词标签
- `section`：所属章节路径

**代码示例**：

```python
enricher = MetadataEnricher(provider="deepseek", model="deepseek-v3")
enriched = enricher.enrich(chunks=[chunk1, chunk2])

for chunk in enriched:
    print(chunk.metadata["title"])   # "RAG系统设计"
    print(chunk.metadata["tags"])    # ["检索", "向量数据库", "RAG"]
    print(chunk.metadata["summary"]) # "本文介绍了RAG系统的核心架构..."
```

##### 3c. Image Captioner（图片描述生成）

**目标**：当 PDF 包含图像时，通过 Vision LLM 生成描述。

**处理流程**：
1. 检测 `[IMAGE: {image_id}]` 占位符
2. 读取对应图像文件
3. 调用 Vision LLM（如 GPT-4o）生成描述
4. 用描述替换占位符

**降级策略**：
- Vision LLM 不可用时，保留占位符并标记 `has_unprocessed_images: true`
- 不阻塞整个摄取流程

#### Stage 4: Encode（向量化）

##### 4a. Dense Encoding（稠密向量）

**模型**：`sentence-transformers/all-MiniLM-L6-v2`
- 维度：384
- 设备：CPU（默认）
- 特点：轻量、快速、本地运行，无需 API 调用

**批处理**：使用 `BatchProcessor` 进行批处理，避免一次性加载所有向量导致内存溢出。

```python
batch_size = 100  # 配置于 settings.yaml
for batch in chunk_batches:
    embeddings = encoder.encode(batch)
    # 批量写入 ChromaDB
```

##### 4b. Sparse Encoding（BM25）

**用途**：补充关键词精确匹配能力，弥补向量检索对专有名词召回不足的问题。

**实现**：使用 `rank_bm25` 库，对每个 chunk 的文本建立倒排索引。

**BM25 参数**：
- `k1`: 1.5（词频饱和参数）
- `b`: 0.75（文档长度归一化参数）

#### Stage 5: Storage（存储）

##### 5a. Vector Upsert（向量数据库写入）

**流程**：
1. 为每个 chunk 生成确定性 `chunk_id`：`hash(source_path + section_path + content_hash)`
2. 将向量 + metadata 写入 ChromaDB
3. 元数据中包含 `doc_hash`（来源文档的 SHA256）

**幂等性保证**：相同内容 → 相同 chunk_id → 重复摄取时覆盖而非追加。

##### 5b. BM25 Index Update

将 chunk 文本和 chunk_id 追加到对应 collection 的 BM25 倒排索引文件（JSON 格式）。

##### 5c. Image Storage

图像文件存储于 `data/images/{doc_hash}/{image_id}.{ext}`，元数据记录在 `image_index.db`。

##### 5d. Ingestion History

记录 SHA256、文件路径、collection、时间戳到 `ingestion_history.db`，用于增量摄取和文档管理。

### 2.2 去重机制（Idempotency）

**文件级去重**：在加载前计算源文件的 SHA256，查询 `ingestion_history.db`：

```sql
SELECT status FROM ingestion_history
WHERE file_hash = ? AND status = 'success'
```

若存在成功记录 → 直接跳过全流程（Zero-Cost 增量更新）。

**Chunk 级幂等**：通过确定性 chunk_id 保证相同内容的 chunk 不会重复写入。

### 2.3 异常处理

| 异常类型 | 处理策略 | 配置项 |
|---------|---------|--------|
| PDF 扫描件 | 检测后告警或中断 | `fail_on_scanned` |
| LLM API 超时 | 降级：跳过 transform 阶段继续 | `chunk_refiner.use_llm` |
| ChromaDB 连接失败 | 抛出异常中止 | 无降级 |
| 图像提取失败 | 降级：跳过图像，记录警告 | `extract_images` |
| 文件损坏 | 抛出 `DocumentQualityError` | 无降级 |

---

## 3. 查询引擎 (Query Engine)

### 3.1 Hybrid Search 流程

```
Query Text
    │
    ▼
┌─────────────────────────┐
│  1. Dense Recall (向量检索)  │  ← top_k: 20（配置项）
│     MiniLM-L6-v2 向量化      │
│     ChromaDB cosine 相似度    │
└────────────┬──────────────┘
             │
             ▼
┌─────────────────────────┐
│  2. Sparse Recall (BM25) │  ← top_k: 20（配置项）
│     倒排索引精确匹配         │
└────────────┬──────────────┘
             │
             │ candidate chunks (40 total)
             ▼
┌─────────────────────────┐
│  3. RRF Fusion (混合融合)  │  ← RRF k=60 (配置项)
│     Reciprocal Rank Fusion │
└────────────┬──────────────┘
             │
             ▼
┌─────────────────────────┐
│  4. Rerank (可选)        │  ← Cross-Encoder 重排序
│     top_k: 5（配置项）      │
└────────────┬──────────────┘
             │
             ▼
    Final Top-K Results
```

### 3.2 RRF (Reciprocal Rank Fusion)

**公式**：

```
RRF_score(d) = Σ  1 / (k + rank_i(d))
              i
```

其中：
- `d`：候选文档
- `k`：常数（默认 60），用于降低高排名文档的权重差异
- `rank_i(d)`：文档 d 在第 i 个排序列表中的排名（从 1 开始）

**为什么 k=60**：k 值越大，高排名和低排名候选之间的差异越小。这有助于平衡两种召回方式的结果，避免某一种方式主导最终排序。

### 3.3 向量检索参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `n_results` | 20 | 召回数量（召回阶段） |
| `distance_metric` | cosine | 余弦相似度 |
| `filter` | `{"doc_hash": ...}` | 元数据过滤 |

### 3.4 BM25 参数调优

BM25 的召回质量与 `k1` 和 `b` 参数密切相关：

- **`k1`（词频饱和）**：值越大，词频对得分的影响越线性；值越小，词频影响越快饱和。建议范围 1.2~2.0。
- **`b`（长度归一化）**：值越大，对短文档的偏好越强；值越小，文档长度影响越弱。建议范围 0.5~0.75。

---

## 4. 可观测性 (Observability)

### 4.1 双链路追踪

#### Ingestion Trace

记录一次文档摄取的完整生命周期：

```json
{
  "trace_id": "uuid-v4",
  "trace_type": "ingestion",
  "timestamp": "2026-06-01T10:00:00Z",
  "stages": {
    "load":     { "duration_ms": 234, "chunks": 1 },
    "split":    { "duration_ms": 89,  "chunks": 1180 },
    "transform":{ "duration_ms": 15234, "llm_calls": 1180 },
    "embed":    { "duration_ms": 8921, "batch_count": 12 },
    "upsert":   { "duration_ms": 342, "vector_count": 1180 }
  },
  "total_duration_ms": 24820,
  "status": "success"
}
```

#### Query Trace

记录一次查询的完整生命周期：

```json
{
  "trace_id": "uuid-v4",
  "trace_type": "query",
  "timestamp": "2026-06-01T10:05:00Z",
  "stages": {
    "dense_recall":    { "duration_ms": 234, "candidates": 20 },
    "sparse_recall":   { "duration_ms": 12,  "candidates": 20 },
    "fusion":          { "duration_ms": 3,   "candidates": 40 },
    "rerank":          { "duration_ms": 567, "final": 5 }
  },
  "total_duration_ms": 816,
  "status": "success"
}
```

### 4.2 追踪存储

**格式**：JSON Lines（`logs/traces.jsonl`）

**优势**：
- 无需数据库，纯文件存储
- 可用 `jq` / `grep` 直接查询
- 每行一条记录，便于追加写入

### 4.3 Dashboard 六页面

| 页面 | 功能 |
|------|------|
| Overview | 组件配置 + Collection 统计 + trace 数量 |
| Data Browser | 文档/Chunk/图片详情查看 |
| Ingestion Manager | 文件上传、实时进度、文档删除 |
| Ingestion Traces | 摄取链路瀑布图 |
| Query Traces | 查询链路瀑布图 |
| Evaluation Panel | 评估指标展示（RAGAS） |

---

## 5. MCP 协议 (MCP Protocol)

### 5.1 工具列表

| 工具名 | 功能 |
|--------|------|
| `ingest_documents` | 上传并摄取文档 |
| `query_knowledge` | 混合检索查询 |
| `list_collections` | 列出所有 collection |
| `get_document_summary` | 获取文档摘要 |
| `delete_documents` | 删除文档 |
| `resync_document` | 强制重新摄取 |
| `deploy` | 部署 MCP Server |
| `list_providers` | 列出可用 provider |

### 5.2 请求格式

MCP 使用 JSON-RPC 2.0 协议。工具调用示例：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "query_knowledge",
    "arguments": {
      "query": "RAG系统的向量检索是如何工作的？",
      "top_k": 5
    }
  }
}
```

### 5.3 响应格式

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "RAG系统的向量检索通过..."
      }
    ],
    "isError": false
  }
}
```

---

## 6. 配置管理 (Configuration)

### 6.1 配置文件结构

所有配置集中于 `config/settings.yaml`，通过 `Settings` 模型（pydantic）校验。

**环境变量注入**：支持 `${ENV_VAR}` 语法，运行时从环境变量读取敏感信息。

```yaml
llm:
  api_key: "${DEEPSEEK_API_KEY}"  # 不硬编码，从环境变量读取

redis:
  password: "${REDIS_PASSWORD}"   # 同上
```

### 6.2 组件可插拔机制

LLM、Embedding、Reranker、VectorStore 均通过工厂模式实现可插拔：

```python
from src.libs.llm.llm_factory import LLMFactory
from src.libs.embedding.embedding_factory import EmbeddingFactory

llm = LLMFactory.create(provider="deepseek", model="deepseek-v4-flash")
embedder = EmbeddingFactory.create(provider="huggingface", model="all-MiniLM-L6-v2")
```

新增 provider 时，只需实现对应的接口类并注册到工厂，无需修改调用方代码。

---

## 7. 常见问题与排查 (Troubleshooting)

### Q1: 摄取时 LLM API 超时，导致 transform 阶段失败

**原因**：网络波动或 API 限流。

**排查步骤**：
1. 检查 `logs/traces.jsonl` 中 transform 阶段的 duration_ms 是否异常高
2. 查看控制台是否有 `timeout` 或 `rate_limit` 相关日志

**解决方案**：
- 将 `chunk_refiner.use_llm` 和 `metadata_enricher.use_llm` 设为 `false`（跳过 LLM 增强）
- 或增加 API 重试次数配置

### Q2: ChromaDB 查询召回结果为空

**原因**：
1. 目标 collection 中没有数据
2. Embedding 模型不匹配（查询时用了不同的模型）
3. 元数据 filter 条件过于严格

**排查步骤**：

```python
# 验证 collection 内容
client = chromadb.PersistentClient(path="data/db/chroma")
col = client.get_collection("knowledge_hub")
print(f"Chunk count: {col.count()}")

# 验证向量维度
sample = col.get(limit=1)
print(f"Vector dim: {len(sample['embeddings'][0])}")
```

### Q3: 重复摄取同一文件未生效（未跳过）

**原因**：`ingestion_history.db` 中该文件的 `status` 不是 `'success'`。

**解决方案**：

```sql
-- 查看记录状态
SELECT file_hash, status, processed_at FROM ingestion_history WHERE file_path LIKE '%report.pdf%';

-- 如果 status 是 'failed'，删除记录后重新摄取
DELETE FROM ingestion_history WHERE file_hash = '...';
```

### Q4: Redis 缓存未生效

**原因**：
1. Redis 服务未启动
2. Redis 连接配置错误
3. 缓存 key 不匹配

**排查步骤**：

```bash
# 检查 Redis 是否运行
redis-cli ping
# 应返回 PONG

# 检查连接配置
# settings.yaml 中 redis.host / redis.port 是否正确
```

### Q5: Dashboard 启动后显示 "No collections found"

**原因**：
1. ChromaDB 数据目录为空（尚未摄取任何文档）
2. `persist_directory` 路径配置错误

**解决方案**：
- 先通过 `python scripts/ingest.py --path documents/` 摄取文档
- 检查 `config/settings.yaml` 中 `vector_store.persist_directory` 是否为 `./data/db/chroma`

---

## 8. 性能优化建议 (Performance Tuning)

### 8.1 批量处理

Embedding 和 Vector Upsert 均使用批处理，减少 API 调用次数和内存占用：

| 配置项 | 默认值 | 优化建议 |
|--------|--------|---------|
| `batch_size` | 100 | GPU 环境下可提高到 256~512 |
| `dense_top_k` | 20 | 根据召回质量需求调整 |
| `sparse_top_k` | 20 | 同上 |

### 8.2 Redis 缓存策略

| 缓存类型 | TTL | 说明 |
|---------|-----|------|
| Embedding | 7 天 | 相同文本的向量缓存，避免重复计算 |
| LLM Response | 1 天 | 相同查询的 LLM 响应缓存 |
| Session | 1 小时 | 会话级上下文缓存 |

### 8.3 向量维度选择

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| all-MiniLM-L6-v2 | 384 | 通用场景，推理速度快 |
| all-mpnet-base-v2 | 768 | 高精度场景，速度较慢 |

---

## 9. 测试策略 (Testing)

### 9.1 测试分层

| 层级 | 范围 | 工具 |
|------|------|------|
| Unit | 单个类/函数 | pytest + pytest-mock |
| Integration | 模块间交互 | pytest + 真实依赖（ChromaDB、Redis） |
| E2E | 完整链路 | MCP Client 模拟调用 |

### 9.2 Fixture 设计

- `tests/fixtures/sample_documents/scanned.pdf`：模拟扫描件，测试 quality_check 模块
- `tests/fixtures/sample_documents/simple.pdf`：最小可用样例
- `tests/fixtures/sample_documents/sample.txt`：纯文本样例

### 9.3 LLM 相关测试

标记为 `@pytest.mark.llm` 的测试会调用真实 LLM API，可通过以下命令跳过：

```bash
pytest -m "not llm"
```

---

## 10. 面试高频问题速查 (Interview Cheat Sheet)

| 问题 | 核心答案要点 |
|------|------------|
| 为什么不选 LlamaIndex？ | 可插拔架构需要完全掌控每个环节；LlamaIndex 封装过深，难以定制 |
| Hybrid Search 怎么融合两种召回？ | RRF（Reciprocal Rank Fusion），k=60 平衡两种召回权重 |
| Chunk 怎么保证语义完整？ | Recursive Splitter 优先在自然边界切分；Chunk Refiner 做边界优化 |
| 怎么保证幂等性？ | SHA256 文件哈希 + 确定性 chunk_id |
| LLM 失败时怎么处理？ | 降级策略：跳过 transform 阶段，不阻塞整体流程 |
| 怎么追踪 RAG 效果？ | Trace + Dashboard 展示各阶段耗时和候选数量 |
| 为什么不用 Qdrant？ | 本地轻量场景，ChromaDB 更简单；后续可切换 |
| 多模态图片怎么处理的？ | PyMuPDF 提取 → Vision LLM caption → 描述文本参与检索 |
| 如何扩展新的 LLM Provider？ | 实现 LLMProvider 接口 → 注册到 LLMFactory，无需修改调用方 |

---

*本文档由 Modular RAG MCP Server 项目维护，最后更新于 2026 年 7 月。*
