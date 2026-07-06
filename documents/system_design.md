# Modular RAG MCP Server - System Design
> 本文档描述 Modular RAG MCP Server 的架构设计、模块划分与设计决策。
> 适用于架构讨论、设计评审与面试项目深挖。

---

## 1. 设计目标

### 1.1 核心目标

1. **模块化（Modular）**：各组件（LLM、Embedding、VectorStore、Reranker）均可独立替换，无需修改核心逻辑。
2. **本地化（Local）**：优先使用本地模型和本地存储，零外部依赖，开箱即用。
3. **可观测（Observable）**：Ingestion 和 Query 两条链路全链路追踪，所有中间状态可见。
4. **可插拔（Pluggable）**：通过工厂模式 + 抽象接口，实现组件的热插拔。
5. **幂等性（Idempotent）**：重复摄取同一文件不会产生重复数据。

### 1.2 非目标（边界）

- **不是通用文档管理系统**：不提供权限管理、多用户协作等企业功能。
- **不是向量数据库**：ChromaDB 是存储层，项目本身不实现向量索引算法。
- **不是 LLM Gateway**：不提供 Token 计数、速率限制、费用统计等 API Gateway 能力。

---

## 2. 架构分层

### 2.1 分层总览

```
┌────────────────────────────────────────────────────────────────────┐
│                         Presentation Layer                          │
│   MCP Client → JSON-RPC → MCP Server → Tool Dispatcher              │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                          Business Logic Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐   │
│  │ Ingestion   │  │   Query     │  │   Document Manager     │   │
│  │  Pipeline   │  │   Engine    │  │   (CRUD Operations)    │   │
│  └─────────────┘  └─────────────┘  └────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                           Service Layer                              │
│  ┌───────────┐ ┌────────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │  Dense    │ │  Sparse    │ │   Reranker   │ │  Metadata     │  │
│  │  Encoder  │ │  Encoder   │ │   Service    │ │   Enricher    │  │
│  └───────────┘ └────────────┘ └──────────────┘ └───────────────┘  │
│  ┌───────────┐ ┌────────────┐ ┌──────────────┐ ┌───────────────┐  │
│  │  Chunk    │ │  Image     │ │   Chunk      │ │   Redis       │  │
│  │  Splitter │ │  Captioner │ │   Refiner    │ │   Cache       │  │
│  └───────────┘ └────────────┘ └──────────────┘ └───────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                          Storage Layer                               │
│  ┌──────────────┐  ┌────────────┐  ┌───────────────┐  ┌────────┐  │
│  │  ChromaDB    │  │   BM25     │  │   ImageStore  │  │ SQLite │  │
│  │  (Vectors)   │  │  (Sparse)  │  │  (Files+DB)   │  │(Meta)  │  │
│  └──────────────┘  └────────────┘  └───────────────┘  └────────┘  │
└────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                          Infrastructure Layer                         │
│  Config (YAML) │ Logging │ Tracing │ Redis │ FileSystem           │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 分层职责

| 层级 | 职责 | 关键原则 |
|------|------|---------|
| Presentation | MCP 协议解析、工具分发 | 无状态，请求级别处理 |
| Business Logic | Pipeline 编排、Query 编排 | 不直接操作存储 |
| Service | 单个原子操作（编码、切分、丰富） | 单一职责，可独立测试 |
| Storage | 数据的持久化与查询 | 抽象接口，支持多种后端 |
| Infrastructure | 配置、日志、追踪、缓存 | 基础设施，与业务解耦 |

### 2.3 层间依赖规则

```
Presentation → Business Logic → Service → Storage
                  ↑                           ↓
                  └───────────────────────────┘
                           (通过抽象接口)
```

**核心规则**：
- 每层只能依赖其下层，不能反向依赖
- Storage 层对外暴露抽象接口（ABC），Business Logic 通过接口操作存储
- Service 层不直接访问 Storage，而是通过 Storage 层暴露的接口

---

## 3. 核心模块设计

### 3.1 工厂模式与可插拔架构

#### 问题

项目中存在多个可选的组件实现：
- LLM：DeepSeek / OpenAI / Azure / Ollama
- Embedding：HuggingFace / OpenAI / Azure
- Reranker：Cross-Encoder / None
- VectorStore：ChromaDB（当前唯一）

如果每个组件都硬编码具体实现，新增 Provider 时需要修改大量调用方代码。

#### 方案：工厂模式 + 抽象接口

```
Abstract Base Class (ABC)
        │
        ├── LLMProvider (ABC)
        │       ├── DeepSeekLLM
        │       ├── OpenAILLM
        │       ├── AzureLLM
        │       └── OllamaLLM
        │
        ├── BaseEmbedding (ABC)
        │       ├── HuggingFaceEmbedding
        │       ├── OpenAIEmbedding
        │       └── AzureEmbedding
        │
        ├── BaseReranker (ABC)
        │       ├── LLMReranker
        │       └── CrossEncoderReranker
        │
        └── BaseVectorStore (ABC)
                └── ChromaStore
```

#### 实现示例

```python
# 抽象接口
class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        pass

# 具体实现
class DeepSeekLLM(BaseLLM):
    def generate(self, prompt: str, **kwargs) -> str:
        # DeepSeek API 调用逻辑
        ...

# 工厂
class LLMFactory:
    _registry: dict[str, type[BaseLLM]] = {}

    @classmethod
    def register(cls, name: str, cls_: type[BaseLLM]):
        cls._registry[name] = cls_

    @classmethod
    def create(cls, provider: str, **kwargs) -> BaseLLM:
        if provider not in cls._registry:
            raise ValueError(f"Unknown provider: {provider}")
        return cls._registry[provider](**kwargs)
```

#### 好处

1. **新增 Provider 零修改调用方**：只需实现接口 + 注册工厂
2. **运行时配置**：通过 `settings.yaml` 指定 provider，代码无需改动
3. **易于测试**：可以用 Mock 替换任意组件

---

### 3.2 Ingestion Pipeline 编排

#### 设计决策

不使用 Pipeline 框架（如 Luigi、Airflow），原因：
- 本项目 Pipeline 是库级复用，不是作业调度
- Pipeline 逻辑需要嵌入 CLI、Dashboard、测试多个入口
- 引入外部框架增加不必要的复杂度

#### Pipeline 结构

```python
class IngestionPipeline:
    def __init__(self, settings: Settings, collection: str, force: bool):
        self.loader = PdfLoader()
        self.chunker = DocumentChunker(chunk_size, chunk_overlap)
        self.refiner = ChunkRefiner()      # 可选
        self.enricher = MetadataEnricher() # 可选
        self.captioner = ImageCaptioner()  # 可选
        self.dense_encoder = DenseEncoder()
        self.sparse_encoder = SparseEncoder()
        self.upsert = VectorUpserter()
        self.bm25 = BM25Indexer()
        self.integrity = SQLiteIntegrityChecker()

    def run(self, file_path: str, trace=None) -> PipelineResult:
        # 1. Integrity check
        # 2. Load → Document
        # 3. Split → Chunks
        # 4. Transform (refine → enrich → caption)
        # 5. Encode (dense + sparse)
        # 6. Storage (upsert → bm25 → images → history)
        # 每个阶段记录 trace
```

#### 为什么不把 Pipeline 设计成异步？

- **Python GIL 限制**：即使使用 async，CPU 密集型操作（Embedding）无法真正并行
- **调试复杂度**：异步 Pipeline 的错误追踪比同步困难得多
- **当前规模够用**：单文档摄取速度瓶颈在 LLM API（网络），不在 CPU

未来如果需要处理大量文件（批处理），可以考虑：
- 使用 `concurrent.futures.ThreadPoolExecutor` 并行处理多个文件
- 或引入 Ray / Dask 做分布式处理

---

### 3.3 Query Engine 编排

#### Hybrid Search 的必要性

**向量检索的局限**：
- 对专有名词（"BM25"、"RRF"）的召回依赖训练语料中是否包含相似上下文
- 对精确匹配（代码片段、公式）能力弱

**BM25 的局限**：
- 无法理解语义相似性（"深度学习" vs "神经网络" 语义相近但字面不同）
- 对同义词、多义词处理能力弱

**Hybrid = 向量 + BM25 = 语义 + 关键词 = 全覆盖**

#### Fusion 算法选择

备选方案比较：

| 算法 | 优点 | 缺点 |
|------|------|------|
| **RRF (Reciprocal Rank Fusion)** | 简单、无需训练、对排名敏感 | 无法利用分数绝对值 |
| Score-based Weighted | 可加权调节两种召回的贡献 | 需要调参、对分数分布敏感 |
| Learning to Rank | 精度最高 | 需要训练数据、计算量大 |

**最终选择 RRF**：
- 无需训练，零配置上线
- 对排名稳定，不受两种召回分数尺度差异影响
- k=60 是经验值，对大多数场景有效

---

### 3.4 文档生命周期管理

#### 问题

文档存在于多个存储后端：
- ChromaDB（向量）
- BM25 Index（倒排）
- ImageStorage（图片文件 + SQLite）
- IngestionHistory（SQLite）

删除文档时，必须同时清理所有后端，否则会产生"孤儿数据"（orphan data）。

#### 方案：DocumentManager 协调删除

```python
class DocumentManager:
    def delete_document(self, source_hash):
        # 1. 从 ChromaDB 删除向量
        self.chroma.delete_by_metadata({"doc_hash": source_hash})

        # 2. 从 BM25 删除倒排索引
        self.bm25.remove_document(source_hash)

        # 3. 从 ImageStorage 删除图片
        for img in self.images.list_images(doc_hash=source_hash):
            self.images.delete_image(img["image_id"])

        # 4. 从 FileIntegrity 删除记录
        self.integrity.remove_record(source_hash)
```

#### 部分失败的处理

```python
result = DeleteResult(success=True)
try:
    self.chroma.delete_by_metadata({"doc_hash": source_hash})
except Exception as e:
    result.errors.append(f"ChromaDB delete failed: {e}")

try:
    self.bm25.remove_document(source_hash)
except Exception as e:
    result.errors.append(f"BM25 remove failed: {e}")

# errors 不为空时 success=False，但尽力清理
result.success = len(result.errors) == 0
```

---

### 3.5 向量存储选型

#### 为什么选 ChromaDB

| 维度 | ChromaDB | Qdrant | Milvus | Weaviate |
|------|----------|--------|--------|----------|
| 部署复杂度 | ⭐ 单文件 | ⭐⭐ Docker | ⭐⭐⭐ K8s | ⭐⭐ Docker |
| 本地运行 | ✅ | ❌ 需要服务 | ❌ 需要服务 | ❌ 需要服务 |
| Python SDK | ✅ | ✅ | ✅ | ✅ |
| Metadata 过滤 | ✅ | ✅ | ✅ | ✅ |
| 性能 | 中等 | 高 | 高 | 高 |
| 成熟度 | 较新 | 成熟 | 成熟 | 成熟 |

**决策**：本地 + 轻量 → ChromaDB 是最优解。未来如需分布式部署，可迁移至 Qdrant。

---

### 3.6 缓存策略

#### Redis 三层缓存

```
Query Request
    │
    ├── Step 1: LLM Response Cache (TTL=1天)
    │           Key: hash(query + top_k + collection)
    │           命中 → 直接返回缓存结果
    │
    ├── Step 2: Embedding Cache (TTL=7天)
    │           Key: hash(query_text)
    │           命中 → 跳过 Embedding 计算
    │
    └── Step 3: 未命中 → 执行完整 Query Pipeline
```

#### 缓存失效策略

- **LLM Response Cache**：TTL=1天，命中后立即返回，无副作用
- **Embedding Cache**：TTL=7天，相同文本的向量长期稳定
- **Session Cache**：TTL=1小时，用于多轮对话的上下文累积

#### 降级策略

当 Redis 不可用时：
- 自动降级为"无缓存"模式
- 所有请求直接访问底层存储
- 不影响核心功能，只是性能下降

---

## 4. 可观测性设计

### 4.1 为什么不用专业追踪平台（LangSmith / LangFuse）

| 维度 | 专业平台 | 本项目方案 |
|------|---------|-----------|
| 部署 | 需要账号 + 网络 | 零依赖，本地 |
| 成本 | 免费额度有限 | 完全免费 |
| 数据隐私 | 数据上传到第三方 | 完全本地 |
| 复杂度 | SDK 集成 | 结构化日志 + Streamlit |
| 定制化 | 受平台限制 | 完全可控 |

**本项目的追踪需求**：
- 记录各阶段耗时（毫秒级）
- 记录候选数量（召回阶段）
- 记录成功/失败状态

这些需求用 JSON Lines + Streamlit 完全可以满足，不需要引入第三方平台的复杂度。

### 4.2 Trace 数据模型

#### TraceContext 显式注入

```python
with TraceContext("ingestion") as trace:
    trace.metadata["source_path"] = file_path

    doc = self.loader.load(file_path)
    trace.record_stage("load", duration_ms=234, chunks=1)

    chunks = self.chunker.split(doc)
    trace.record_stage("split", duration_ms=89, chunks=len(chunks))
```

**显式注入的好处**：
- 追踪逻辑与业务逻辑分离
- 可以选择性开启/关闭追踪
- 比装饰器模式更灵活（可附加额外 metadata）

### 4.3 Dashboard 数据流

```
logs/traces.jsonl
       │
       ├── TraceService.read_traces(trace_type="ingestion")
       │         │
       │         ▼
       │    [list of Trace objects]
       │         │
       │         ▼
       ├── ingestion_traces.py → Streamlit UI
       │
       └── query_traces.py → Streamlit UI

ChromaDB (via DataService)
       │
       ├── DocumentManager.list_documents()
       ├── DocumentManager.get_document_detail()
       └── DataService.get_collection_stats()
              │
              ▼
         overview.py + data_browser.py
```

---

## 5. 配置管理设计

### 5.1 配置分层

```
CLI Args / Environment Variables
            │
            ▼
    config/settings.yaml
            │
            ▼
      Settings (pydantic)
            │
    ┌───────┼───────┐
    │       │       │
    ▼       ▼       ▼
  LLM    Embedding  VectorStore
 Config  Config    Config
```

### 5.2 环境变量注入

```yaml
# settings.yaml
llm:
  api_key: "${DEEPSEEK_API_KEY}"  # 运行时替换
```

```python
# settings.py
import os, re

def _resolve_env_vars(value):
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value

class Settings(BaseSettings):
    ...
```

**好处**：
- 敏感信息（API Key）不写入配置文件
- 不同环境（dev / staging / prod）使用不同环境变量

---

## 6. 扩展性设计

### 6.1 新增 LLM Provider

步骤：
1. 在 `src/libs/llm/` 下实现新 Provider 类，继承 `BaseLLM`
2. 在 `src/libs/llm/llm_factory.py` 中注册
3. 在 `settings.yaml` 中添加配置

示例：新增 Anthropic Provider：

```python
# src/libs/llm/anthropic_llm.py
class AnthropicLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet"):
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, **kwargs) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", 4096),
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

# llm_factory.py
LLMFactory.register("anthropic", AnthropicLLM)
```

### 6.2 新增文档格式支持

步骤：
1. 在 `src/libs/loader/` 下实现 `BaseLoader` 子类
2. 在 `scripts/ingest.py` 的 `SUPPORTED_EXTENSIONS` 中添加扩展名
3. 在 Pipeline 的 loader 选择逻辑中注册新 loader

示例：新增 Word 文档支持：

```python
# src/libs/loader/docx_loader.py
class DocxLoader(BaseLoader):
    def load(self, file_path: str | Path) -> Document:
        from docx import Document as DocxDocument
        doc = DocxDocument(file_path)
        text = "\n".join([p.text for p in doc.paragraphs])
        return Document(text=text, metadata={"source_path": str(file_path)})
```

### 6.3 新增 VectorStore 后端

步骤：
1. 在 `src/libs/vector_store/` 下实现 `BaseVectorStore` 子类
2. 在 `src/libs/vector_store/vector_store_factory.py` 中注册
3. 在 `settings.yaml` 中切换 `provider`

---

## 7. 安全性设计

### 7.1 API Key 管理

- **不硬编码**：所有 API Key 通过 `${ENV_VAR}` 语法从环境变量读取
- **不写入日志**：Trace 日志中不记录 API Key
- **不提交到 Git**：`config/settings.yaml` 在 `.gitignore` 中

### 7.2 文件路径安全

- 所有文件路径通过 `Path.resolve()` 转为绝对路径
- 禁止路径穿越（`../`）攻击
- 文件读取前验证文件存在且为普通文件（非 symlink、非 device）

### 7.3 输入验证

- 通过 Pydantic 模型对所有配置进行类型校验
- API 请求参数通过 MCP 协议层校验
- 禁止执行动态代码（无 `eval` / `exec`）

---

## 8. 性能基准参考

以下数据基于 `all-MiniLM-L6-v2` + `DeepSeek-v4-flash` 测试环境（CPU 推理）：

| 操作 | 耗时 | 说明 |
|------|------|------|
| 加载 PDF（100页） | ~2s | MarkItDown 解析 |
| Split（100页→1180 chunks） | ~0.5s | 递归切分 |
| Embedding（1180 chunks, batch=100） | ~45s | CPU 推理 |
| ChromaDB Upsert（1180 vectors） | ~3s | 批量写入 |
| Query（Dense+Sparse+RRF） | ~200ms | 含 Embedding |
| Query（缓存命中） | ~50ms | Embedding 缓存命中 |

**关键优化建议**：
- Embedding 是瓶颈，建议 GPU 环境下使用 CUDA 加速
- Query 延迟目标 <500ms 时，建议开启 Redis 缓存
- 大规模文档（>10k chunks）建议使用 GPU Embedding + Qdrant

---

## 9. 未来演进方向

### Phase 1：当前版本（v0.1.0）
- [x] 本地 RAG 基础链路
- [x] Hybrid Search
- [x] MCP 协议接口
- [x] 可视化 Dashboard

### Phase 2：近期规划
- [ ] GPU Embedding 加速
- [ ] 多文档联合索引（跨 Collection 检索）
- [ ] 增量更新优化（基于文件修改时间戳）
- [ ] 支持更多 Embedding 模型（e5-mistral、BGE）

### Phase 3：长期规划
- [ ] 分布式部署（Qdrant 集群）
- [ ] 多租户支持
- [ ] 增量向量更新（无需全量重摄）
- [ ] 主动学习（基于用户反馈优化检索）

---

*文档版本：v0.1.0 | 作者：Modular RAG Team | 最后更新：2026-07-06*
