# Modular RAG MCP Server - API Reference
> 本文档详细描述 MCP Server 各工具的请求参数、响应格式与使用示例。
> 版本：v0.1.0

---

## 目录

1. [Ingestion Tools](#1-ingestion-tools)
2. [Query Tools](#2-query-tools)
3. [Management Tools](#3-management-tools)
4. [System Tools](#4-system-tools)

---

## 1. Ingestion Tools

### 1.1 `ingest_documents`

上传并摄取文档到指定 Collection。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `file_paths` | `string[]` | 是 | — | 要摄取的文件路径列表，支持 `.pdf`、`.md`、`.txt`、`.markdown` |
| `collection` | `string` | 否 | `"knowledge_hub"` | 目标 Collection 名称 |
| `force` | `boolean` | 否 | `false` | 设为 `true` 时强制重新处理，跳过去重检查 |
| `quality_check_enabled` | `boolean` | 否 | `true` | 是否启用 PDF 质量检查 |
| `fail_on_scanned` | `boolean` | 否 | `false` | 扫描件检测到时是否抛出异常中断 |

#### 响应格式

```json
{
  "results": [
    {
      "file_path": "documents/report.pdf",
      "success": true,
      "doc_id": "sha256-hash-of-file",
      "chunk_count": 42,
      "image_count": 3,
      "stages": {
        "load": { "duration_ms": 234, "status": "success" },
        "split": { "duration_ms": 89, "chunk_count": 42 },
        "transform": { "duration_ms": 15234, "llm_calls": 42 },
        "embed": { "duration_ms": 8921, "batch_count": 1 },
        "upsert": { "duration_ms": 342, "status": "success" }
      },
      "skipped": false,
      "error": null
    }
  ],
  "total_files": 1,
  "successful": 1,
  "failed": 0
}
```

#### 使用示例

**Python 调用**：

```python
from mcp.client import MCPClient

client = MCPClient("http://localhost:8000")
result = await client.call_tool("ingest_documents", {
    "file_paths": ["documents/technical_notes.md", "documents/api_reference.pdf"],
    "collection": "knowledge_hub",
    "force": False
})
print(result["total_files"], "files ingested")
```

**MCP JSON-RPC 调用**：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "ingest_documents",
    "arguments": {
      "file_paths": ["documents/technical_notes.md"],
      "collection": "knowledge_hub"
    }
  }
}
```

#### 错误码

| 错误类型 | 说明 | 处理建议 |
|---------|------|---------|
| `FILE_NOT_FOUND` | 指定路径的文件不存在 | 检查文件路径 |
| `UNSUPPORTED_FORMAT` | 文件格式不支持 | 仅支持 pdf/md/txt/markdown |
| `DOCUMENT_QUALITY_ERROR` | PDF 质量检查失败（如扫描件） | 设置 `fail_on_scanned=false` 继续 |
| `PIPELINE_ERROR` | Pipeline 内部错误 | 检查日志 `logs/traces.jsonl` |
| `ALREADY_EXISTS` | 文件已成功摄取（SHA256 命中） | 设置 `force=true` 强制重摄 |

---

### 1.2 `resync_document`

强制重新摄取文档。用于文件内容已更新、需要重新处理时。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | `string` | 是 | 要重新处理的文件路径 |
| `collection` | `string` | 否 | Collection 名称（默认 `knowledge_hub`） |

#### 响应格式

```json
{
  "file_path": "documents/report.pdf",
  "success": true,
  "doc_id": "new-sha256-hash",
  "chunk_count": 45,
  "previous_doc_id": "old-sha256-hash",
  "status": "resynced"
}
```

#### 工作原理

1. 从 `ingestion_history.db` 中删除旧记录
2. 删除 ChromaDB 中 `doc_hash == old_hash` 的所有向量
3. 从 BM25 索引中移除旧文档
4. 执行完整的 `ingest_documents` 流程

---

## 2. Query Tools

### 2.1 `query_knowledge`

执行混合检索查询，返回融合排序后的 Top-K 结果。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | `string` | 是 | — | 自然语言查询文本 |
| `top_k` | `integer` | 否 | `5` | 返回的最终结果数量（Fusion 之后的数量） |
| `collection` | `string` | 否 | `"knowledge_hub"` | 查询的 Collection |
| `use_rerank` | `boolean` | 否 | `false` | 是否启用 Cross-Encoder 重排序 |
| `rerank_top_k` | `integer` | 否 | `5` | Rerank 阶段召回数量 |
| `filter_metadata` | `object` | 否 | `null` | 元数据过滤条件 |

#### 响应格式

```json
{
  "query": "RAG系统的向量检索是如何工作的？",
  "results": [
    {
      "chunk_id": "hash-of-chunk",
      "content": "向量检索通过将查询文本转换为向量表示...",
      "score": 0.847,
      "source": "documents/technical_notes.md",
      "metadata": {
        "title": "技术笔记",
        "section": "查询引擎 > Hybrid Search",
        "tags": ["向量检索", "RRF", "混合搜索"]
      }
    }
  ],
  "trace": {
    "dense_candidates": 20,
    "sparse_candidates": 20,
    "fusion_candidates": 40,
    "final_candidates": 5,
    "total_duration_ms": 234
  }
}
```

#### 内部流程

```
query_knowledge
    │
    ▼ Dense Recall (top_k=20)
    ▼ Sparse Recall (top_k=20)
    ▼ RRF Fusion (k=60, candidates=40)
    ▼ [Optional] Rerank (Cross-Encoder, top_k=rerank_top_k)
    ▼ Final Return (top_k)
```

#### 使用示例

**基础查询**：

```python
result = await client.call_tool("query_knowledge", {
    "query": "如何配置 DeepSeek 作为 LLM Provider？",
    "top_k": 5,
    "collection": "knowledge_hub"
})

for r in result["results"]:
    print(f"[{r['score']:.3f}] {r['content'][:100]}...")
```

**带元数据过滤**：

```python
result = await client.call_tool("query_knowledge", {
    "query": "BM25 参数调优",
    "filter_metadata": {"tags": {"$contains": "BM25"}}
})
```

**启用 Rerank**：

```python
result = await client.call_tool("query_knowledge", {
    "query": "ChromaDB 和 Qdrant 的区别",
    "use_rerank": True,
    "rerank_top_k": 10
})
```

---

### 2.2 `get_document_summary`

获取指定文档的摘要信息。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_id` | `string` | 是 | 文档 ID（SHA256 哈希） |
| `collection` | `string` | 否 | Collection 名称 |

#### 响应格式

```json
{
  "doc_id": "sha256-hash",
  "file_path": "documents/technical_notes.md",
  "collection": "knowledge_hub",
  "chunk_count": 118,
  "image_count": 0,
  "processed_at": "2026-06-01T10:00:00Z",
  "metadata": {
    "title": "技术笔记",
    "tags": ["RAG", "向量检索", "MCP"],
    "estimated_pages": 20
  }
}
```

---

## 3. Management Tools

### 3.1 `list_collections`

列出所有 Collection 及其统计信息。

#### 响应格式

```json
{
  "collections": [
    {
      "name": "knowledge_hub",
      "chunk_count": 1298,
      "document_count": 4,
      "image_count": 0,
      "created_at": "2026-05-30T12:20:20Z",
      "last_updated": "2026-07-06T10:00:00Z"
    },
    {
      "name": "test_complex_doc",
      "chunk_count": 12,
      "document_count": 1,
      "image_count": 0
    }
  ]
}
```

---

### 3.2 `delete_documents`

从所有存储后端删除指定文档。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | `string` | 是 | 要删除的文档路径 |
| `collection` | `string` | 否 | Collection 名称 |

#### 响应格式

```json
{
  "success": true,
  "file_path": "documents/report.pdf",
  "chunks_deleted": 42,
  "bm25_removed": true,
  "images_deleted": 3,
  "integrity_removed": true,
  "errors": []
}
```

#### 删除范围

此操作会同时清理以下存储：

| 存储 | 清理内容 |
|------|---------|
| ChromaDB | 所有 `doc_hash == file_hash` 的向量记录 |
| BM25 Index | 对应文档的所有倒排索引条目 |
| ImageStorage | `data/images/{doc_hash}/` 目录下的所有文件 |
| FileIntegrity | `ingestion_history.db` 中的记录 |

---

### 3.3 `get_ingestion_status`

查询文档的当前摄取状态。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_hash` | `string` | 否 | 文档 SHA256 哈希 |
| `file_path` | `string` | 否 | 文档路径（二选一） |

#### 响应格式

```json
{
  "file_hash": "sha256-hash",
  "file_path": "documents/report.pdf",
  "collection": "knowledge_hub",
  "status": "success",
  "processed_at": "2026-06-01T10:00:00Z",
  "updated_at": "2026-06-01T10:00:00Z",
  "error_msg": null
}
```

#### 状态枚举

| 状态值 | 说明 |
|--------|------|
| `success` | 成功完成，可直接使用 |
| `failed` | 处理失败，可通过 `resync_document` 重试 |
| `pending` | 处理中（罕见，通常极快完成） |

---

## 4. System Tools

### 4.1 `list_providers`

列出当前配置下可用的 LLM / Embedding Provider。

#### 响应格式

```json
{
  "llm": {
    "available": ["deepseek", "openai", "azure", "ollama"],
    "configured": "deepseek",
    "model": "deepseek-v4-flash"
  },
  "embedding": {
    "available": ["huggingface", "openai", "azure"],
    "configured": "huggingface",
    "model": "all-MiniLM-L6-v2"
  },
  "rerank": {
    "available": ["cross-encoder", "none"],
    "configured": "none"
  }
}
```

---

### 4.2 `get_system_stats`

获取系统运行统计信息。

#### 响应格式

```json
{
  "vector_store": {
    "persist_directory": "./data/db/chroma",
    "collections": 5,
    "total_vectors": 3558
  },
  "ingestion_history": {
    "database": "./data/db/ingestion_history.db",
    "total_documents": 3,
    "successful": 3,
    "failed": 0
  },
  "image_storage": {
    "directory": "./data/images",
    "total_images": 0
  },
  "redis": {
    "enabled": true,
    "connection": "localhost:6379",
    "embedding_cache_keys": 42,
    "llm_response_cache_keys": 12
  },
  "observability": {
    "trace_file": "./logs/traces.jsonl",
    "total_traces": 156
  }
}
```

---

### 4.3 `deploy`

启动 MCP Server。

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `host` | `string` | 否 | `"0.0.0.0"` | 监听地址 |
| `port` | `integer` | 否 | `8000` | 监听端口 |
| `config` | `string` | 否 | `"config/settings.yaml"` | 配置文件路径 |

#### 响应格式

```json
{
  "status": "starting",
  "host": "0.0.0.0",
  "port": 8000,
  "config": "config/settings.yaml",
  "pid": 12345
}
```

---

## 附录：错误码速查表

| 错误码 | HTTP Status | 说明 |
|--------|-------------|------|
| `FILE_NOT_FOUND` | 404 | 文件不存在 |
| `COLLECTION_NOT_FOUND` | 404 | Collection 不存在 |
| `UNSUPPORTED_FORMAT` | 415 | 文件格式不支持 |
| `DOCUMENT_QUALITY_ERROR` | 422 | 文档质量检查失败 |
| `PIPELINE_ERROR` | 500 | Pipeline 内部错误 |
| `VECTOR_STORE_ERROR` | 500 | ChromaDB 操作失败 |
| `LLM_API_ERROR` | 502 | LLM API 调用失败 |
| `REDIS_ERROR` | 503 | Redis 连接失败 |

---

*API 版本：v0.1.0 | 最后更新：2026-07-06*
