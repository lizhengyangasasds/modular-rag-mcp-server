# Modular RAG MCP Server

> 基于 Python 的本地私有化 RAG 系统，集成 DeepSeek 大模型，通过 MCP 协议对接 Cursor 等 AI 助手，提供知识库检索与 12 个定制工具。

**作者**: 李政扬  
**仓库**: https://github.com/lizhengyangasasds/modular-rag-mcp-server

---

## 目录

- [项目简介](#项目简介)
- [核心能力](#核心能力)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
  - [1. 克隆与安装](#1-克隆与安装)
  - [2. 配置（密钥管理）](#2-配置密钥管理)
  - [3. 导入文档](#3-导入文档)
  - [4. 查询测试](#4-查询测试)
  - [5. 启动 MCP 服务](#5-启动-mcp-服务)
- [MCP 工具一览](#mcp-工具一览)
- [架构图](#架构图)
- [PDF 质量检查](#pdf-质量检查)
- [检索流程详解](#检索流程详解)
- [高级配置](#高级配置)
  - [Redis 缓存](#启用-redis-缓存降低-api-调用成本)
- [测试与 Fixture](#测试与-fixture)
- [项目结构](#项目结构)

---

## 项目简介

本项目是一个**模块化、可配置**的 RAG（检索增强生成）服务，将文档摄取、混合检索、向量存储与 MCP 工具暴露串联为可运行系统。文档在本地完成解析与向量化，支持对接私有知识库，供 AI 助手通过标准 MCP 协议调用。

**适用场景**: 个人/团队私有文档问答、技术资料检索、与大模型应用开发岗位相关的作品集展示。

---

## 核心能力

| 模块 | 说明 |
|------|------|
| **文档摄取** | PDF → 质量检查 → 分块 → 元数据增强 → 向量化 → 写入 Chroma + BM25 索引 |
| **混合检索** | Dense（语义向量）+ Sparse（BM25）+ RRF 融合，可选 Rerank |
| **MCP Server** | 标准 MCP 协议，暴露 12 个工具，可在 Cursor / Copilot 等客户端中使用 |
| **可插拔架构** | LLM / Embedding / VectorStore 等通过 `config/settings.yaml` 切换 |
| **本地 Embedding** | 默认 HuggingFace `all-MiniLM-L6-v2`，无需上传文档到云端做向量化 |
| **可观测性** | 摄取与查询链路追踪，可选 Streamlit Dashboard 管理 |

---

## 技术栈

- **语言**: Python 3.9+（推荐 3.10+）
- **LLM**: DeepSeek V4（`deepseek-v4-flash` / `deepseek-v4-pro`）或 OpenAI / Azure / Ollama
- **Embedding**: HuggingFace Sentence-Transformers（`all-MiniLM-L6-v2`）
- **向量库**: ChromaDB
- **检索**: BM25 + 稠密向量 + RRF（Reciprocal Rank Fusion）
- **缓存**: Redis（Embedding 向量缓存 / LLM 响应缓存 / 多轮会话记忆）
- **协议**: MCP（Model Context Protocol）
- **文档解析**: pypdf / MarkItDown（自动 fallback）

---

## 快速开始

### 1. 克隆与安装

```bash
git clone https://github.com/lizhengyangasasds/modular-rag-mcp-server.git
cd modular-rag-mcp-server

# 创建虚拟环境（推荐 Python 3.10+）
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

pip install -e .
```

### 2. 配置（密钥管理）

> **安全原则**: 密钥不写入 `settings.yaml`，通过 `.env` 文件管理，永不提交到 Git。

```bash
# 复制环境变量模板并填入真实密钥
cp .env.example .env
```

编辑 `.env`:

```bash
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
VISION_LLM_API_KEY=sk-your-vision-api-key-here  # 可选：多模态用
```

编辑 `config/settings.yaml`（只需修改模型名，密钥已通过 `${DEEPSEEK_API_KEY}` 引用）:

```yaml
llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"          # 推荐：deepseek-v4-flash（快速）/ deepseek-v4-pro（高精度）
  base_url: "https://api.deepseek.com"
  api_key: "${DEEPSEEK_API_KEY}"       # 从 .env 读取，绝不硬编码
  temperature: 0.0
  max_tokens: 4096
```

> **集合名说明**: 配置中默认为 `knowledge_hub`。**命令行脚本和 MCP 工具使用相同的集合名**，请勿混用。

### 3. 导入文档

将 PDF 等文件放入 `documents/`，执行:

```bash
# 首次导入（或添加新文档后）
python scripts/ingest.py --path documents/ --collection knowledge_hub --force

# 查看导入状态
python scripts/query.py --query "测试" --collection knowledge_hub

# 或使用 MCP 工具（在 Cursor 中）:
# 工具: ingest_documents
# 参数: collection="knowledge_hub", force=true
```

**参数说明**:
- `--force`: 强制重新导入（跳过 SHA256 去重检查）
- `--collection`: 集合名称，需与配置保持一致（默认 `knowledge_hub`）

### 4. 查询测试

```bash
# 简单模式（只显示融合结果）
python scripts/query.py --query "深度学习的历史" --collection knowledge_hub

# 详细模式（显示 Dense/Sparse/Fusion 中间过程）
python scripts/query.py --query "深度学习的历史" --collection knowledge_hub --verbose
```

### 5. 启动 MCP 服务

```bash
python main.py
```

在 Cursor 的 MCP 配置（`~/.cursor/mcp.json`）中指向本项目的 Python 与入口，即可在对话中调用上述工具。参考配置示例:

```json
{
  "mcpServers": {
    "modular-rag": {
      "command": "python",
      "args": ["main.py"],
      "cwd": "C:/path/to/modular-rag-mcp-server"
    }
  }
}
```

## MCP 工具一览

### 知识库核心（RAG 主链路）

| 工具 | 功能 | 说明 |
|------|------|------|
| `query_knowledge_hub` | 智能检索与问答 | 混合检索 + RRF 融合 + 引用返回 |
| `ingest_documents` | 文档导入向量库 | 增量导入，支持 force 强制重导入 |
| `list_collections` | 查看集合列表 | 显示集合名 + chunk 数量 |
| `get_document_summary` | 获取文档摘要 | 按 doc_id 查文档元信息 |
| `resync_document` | 文档变更后刷新 | 删旧 chunks + 重新导入 + 验证 diff |

### 扩展工具（辅助能力）

| 工具 | 功能 | 说明 |
|------|------|------|
| `auto_coder` | 自动编码辅助 | 基于 LLM 生成代码 |
| `qa_tester` | 测试用例生成 | 根据代码生成测试 |
| `code_reviewer` | 代码审查 | 调用 LLM 做 code review |
| `resume_writer` | 简历项目经历生成 | 结合项目输出简历 bullet |
| `doc_generator` | 技术文档生成 | 自动生成文档 |
| `setup` | 环境初始化 | 一键初始化开发环境 |
| `package` | 打包辅助 | 项目打包与依赖管理 |
| `deploy` | 部署辅助 | 部署配置生成 |

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Modular RAG MCP Server 架构                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │ documents/ │   ┌──────────────────────┐  ┌────────────────────────────┐  │
│  │  PDF / MD   │──▶│   Ingestion Pipeline  │  │  Stage 1: PDF 解析        │  │
│  └─────────────┘   │   scripts/ingest.py   │  │  Stage 2: 质量检查        │  │
│                    │        或              │  │  Stage 3: 分块 (chunk)   │  │
│  MCP Client        │   MCP: ingest_documents │  │  Stage 4: LLM 元数据增强   │  │
│  (Cursor) ─────────▶│                        │  │  Stage 5: 本地 Embedding  │  │
│                    └──────────┬─────────────┘  │  Stage 6: ChromaDB 存储   │  │
│                                 │              │  Stage 7: BM25 索引      │  │
│                                 │              └─────────────┬──────────────┘  │
│                                 ▼                        │                   │
│                    ┌──────────────────────┐              ▼                   │
│                    │   ChromaDB  +  BM25   │◀─────────────┘                   │
│                    │  ./data/db/chroma     │                                  │
│                    │  ./data/db/bm25/      │                                  │
│                    └──────────────┬────────┘                                  │
│                                   │                                           │
│  ┌─────────────┐                 │              ┌────────────────────────────┐ │
│  │  用户查询    │                 │              │  Query Pipeline            │ │
│  │  自然语言    │─────────────────┼─────────────▶│  Stage 1: Dense 检索 (向量)│ │
│  └─────────────┘                 │              │  Stage 2: Sparse 检索 (BM25)│ │
│                                  │              │  Stage 3: RRF 融合          │ │
│  MCP Client                      │              │  Stage 4: 可选 Rerank       │ │
│  (Cursor) ───────────────────────┴─────────────▶│  Stage 5: LLM 生成回答      │ │
│                                              │  Stage 6: 带引用返回         │ │
│                                              └─────────────┬────────────────┘  │
│                                                                    │           │
│  ┌─────────────┐                                                  │           │
│  │  Cursor /   │                                                  │           │
│  │  Claude App  │◀─────────────────────────────────────────────────┘           │
│  └─────────────┘          MCP 协议 (JSON-RPC over stdio)                       │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  扩展能力层（基于 MCP Tool + LLM）                                        │ │
│  │  auto_coder | qa_tester | code_reviewer | resume_writer | doc_generator │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 架构说明

- **documents/** → PDF 解析 → **质量检查（Stage 2）** → 分块 → LLM 元数据增强 → 本地 Embedding → ChromaDB + BM25
- **用户查询** → Dense 检索（向量相似度）+ Sparse 检索（BM25）→ RRF 融合 → LLM 生成 → 带引用返回
- **MCP 协议** → 通过 stdio 传输 JSON-RPC，支持 Cursor / Claude App 等客户端

---

## PDF 质量检查

在文档被分块、向量化前，系统会先做一轮**文本层质量评估**，识别三类劣质 PDF：

| 类型 | 特征 | 系统反应 |
|------|------|---------|
| **扫描件** | 几乎无可提取文本（有效字符率 < 10%，或全部页都是噪声） | 标记 `is_scanned=True`，建议先 OCR |
| **噪声 PDF** | 文本层损坏（C0/C1 控制字符、Private Use Area 乱码） | 有效字符率 < 80% 触发 `FAIL_NOISE` |
| **低密度** | 页面主要是图片/表格，文字很少 | 文本密度 < 20% 触发 `FAIL_DENSITY` |

### 工作原理

采样 PDF **前 3 页**（可配置）进行评估：

```
有效字符率 = 有效字符 / 总字符
  ├─ 有效 = 空白 + 可打印 ASCII + CJK + 其他正常 Unicode
  └─ 无效 = C0/C1 控制字符 + 0x7F + Private Use Area + Variation Selectors

文本密度 = 有效字符 / (采样页数 × 3000估算容量)

扫描件判定（三路信号 OR）：
  ① 有效字符率 < 10%
  ② 全部采样页 garbage_dominant（噪声字符 ≥ 30%）
  ③ 80%+ 页 is_suspicious
```

### 报告示例

```python
from src.libs.loader import PdfQualityChecker

checker = PdfQualityChecker(min_valid_ratio=0.80, min_text_density=0.20)
report = checker.check("data/some_scan.pdf")

print(report.to_dict())
# {
#   "file_path": "data/some_scan.pdf",
#   "valid_char_ratio": 0.05,
#   "text_density": 0.02,
#   "is_scanned": True,
#   "is_noisy": True,
#   "is_poor_quality": True,
#   "quality_level": "scanned",
#   "recommendation": "FAIL_SCAN - 疑似扫描件，建议先通过 OCR 处理后再摄取",
#   "per_page": [
#     {"page": 1, "valid_char_ratio": 0.04, "is_suspicious": True, "suspicion_reasons": ["garbage_dominant"]},
#     ...
#   ]
# }
```

### Pipeline 集成

质量检查作为 **Stage 2b** 嵌入 `IngestionPipeline.run()`，位于 `load` 和 `split` 之间：

```
Stage 1: integrity   → SHA256 跳过
Stage 2: load        → PdfLoader 解析
Stage 2b: quality_check → PdfQualityChecker 评估  ← 新增
Stage 3: split       → DocumentChunker 分块
Stage 4: transform   → ChunkRefiner + MetadataEnricher + ImageCaptioner
Stage 5: embed       → DenseEncoder + SparseEncoder
Stage 6: upsert      → ChromaDB + BM25
```

低质量 PDF **默认仅记录警告并继续摄取**（避免硬阻塞用户的合法文档）。如果你的资料库只含正常生成的 PDF，可以把 `fail_on_scanned: true` 让扫描件直接失败，强制走 OCR 流程。

### 配置项

```yaml
ingestion:
  quality_check:
    enabled: true                # 设为 false 跳过质量检查
    min_valid_ratio: 0.80        # 有效字符率阈值，低于此值触发 FAIL_NOISE
    min_text_density: 0.20       # 文本密度阈值，低于此值触发 FAIL_DENSITY
    check_first_n_pages: 3       # 采样前 N 页
    fail_on_scanned: false       # 扫描件是否直接抛 DocumentQualityError
```

### 编程接口

```python
from src.libs.loader import PdfQualityChecker, DocumentQualityError

# 方式 1：直接传文件路径（内部用 PyMuPDF 重新解析）
checker = PdfQualityChecker()
report = checker.check("path/to/file.pdf")

# 方式 2：传入已经抽取好的页面文本（推荐，避免重复解析）
pages = [(1, "第一章 ..."), (2, "第二章 ..."), (3, "第三章 ...")]
report = checker.check_text(pages)

# 严格模式：扫描件直接抛异常
strict_checker = PdfQualityChecker(fail_on_scanned=True)
try:
    strict_checker.check("scanned.pdf")
except DocumentQualityError as e:
    print(f"拒绝摄取：{e}")
    print(f"质量报告：{e.report.to_dict()}")
```

---

## 文档更新追踪

当一个文档内容被修改后，**仅仅 `ingest_documents force=true` 不够**——它只绕过 integrity skip 逻辑，会把新 chunks 追加到 vector store，**旧 chunks 仍然存在**，导致同一个文档在库里有两套互相冲突的 chunk。

`resync_document` MCP 工具封装了「删旧 → 重新导入 → 验证」三件套，并返回结构化 diff 让你能一眼看出"是否全部 chunks 都刷新了"。

### 工作流

```text
┌─────────────────────────────────────────────────────────────────────┐
│                    resync_document 工作流                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   1. 读取 source_path 在 disk 上的新内容                              │
│   2. 从 FileIntegrity 库反查旧 hash（按文件路径）                     │
│   3. 计算 new_hash = SHA-256(file)                                  │
│   4. 如果 old_hash == new_hash                                       │
│        → 直接返回 fully_refreshed=True，跳过所有步骤                  │
│   5. 否则按 old_hash 删除 4 个存储后端的所有旧 chunks:                │
│        • ChromaDB    (vector store)                                  │
│        • BM25        (sparse retriever)                             │
│        • ImageStorage (images)                                       │
│        • FileIntegrity (ingestion history)                          │
│   6. IngestionPipeline.run(path, force=True) 重新导入                │
│   7. 验证：新 hash 下 chunks > 0 && 旧 hash 下 chunks == 0          │
│   8. 返回 chunks_before / chunks_deleted / chunks_after /           │
│        fully_refreshed / warnings                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 用法（MCP 客户端）

```json
{
  "tool": "resync_document",
  "arguments": {
    "source_path": "data/employee_handbook.pdf",
    "collection": "knowledge_hub"
  }
}
```

返回示例：

```text
## 文档重同步完成

**文档路径:** data/employee_handbook.pdf
**集合:** knowledge_hub
**旧 hash:** `a3f1c9b27d4e8f60...`
**新 hash:** `b7d92e8f1c4a6500...`

### Chunks 变化
- 删除前旧 chunks: **42**
- 实际删除 chunks: **42**
- 新增 chunks: **38**

### 其他存储
- BM25 删除: **42** (之前 42)
- Images 删除: **3** (之前 3)

**✅ 全部 chunks 已刷新完成**
```

### "全部更新了"的判定标准

工具内部 `fully_refreshed` 字段会自动判定，但你也应该自己核对：

| 检查项 | 期望 |
|--------|------|
| `new_hash != old_hash` | 文件确实改了 |
| `chunks_deleted == chunks_before` | 旧 chunks 真的全删了 |
| `chunks_after > 0` | 新 chunks 进了 |
| `chunks_after` 数量合理 | 与文档变化幅度匹配（删的多 → 加的多） |

如果 `chunks_deleted < chunks_before`，`warnings` 字段会提示 `Only N/M old chunks were deleted — possible orphan chunks remain`，需要手工清理。

### 编程接口

```python
from src.mcp_server.tools.resync_document import ResyncDocumentTool

tool = ResyncDocumentTool()
result = tool.resync_document(
    source_path="data/employee_handbook.pdf",
    collection="knowledge_hub",
)

print(result.to_dict())
# {
#   "file_changed": True,
#   "old_hash": "a3f1c9b27d4e8f60...",
#   "new_hash": "b7d92e8f1c4a6500...",
#   "chunks_before": 42,
#   "chunks_deleted": 42,
#   "chunks_after": 38,
#   "bm25_deleted": 42,
#   "images_deleted": 3,
#   "fully_refreshed": True,
#   "warnings": [],
# }
```

---

## Dashboard

基于 Streamlit 构建的六页面可视化管控平台，覆盖 RAG 系统从数据摄入到检索查询的全生命周期管理。

### 快速启动

```bash
streamlit run src/observability/dashboard/app.py
```

### 功能页面

| 页面 | 说明 |
|------|------|
| **Overview** | 系统总览：组件配置、数据资产统计、核心指标 |
| **Data Browser** | 文档/Chunk/图片详情查看 |
| **Ingestion Manager** | 文件上传、实时进度条、文档删除 |
| **Ingestion Traces** | 摄取链路五阶段耗时瀑布图 |
| **Query Traces** | Dense/Sparse 对比、Rerank 前后分数变化 |
| **Evaluation Panel** | Ragas 指标 + 自定义指标历史趋势 |

### 页面预览

> Dashboard 截图存放在 [`docs/screenshots/`](docs/screenshots/) 目录下，启动后截取即可更新。

![Overview](docs/screenshots/overview.png)
![Query Traces](docs/screenshots/query_traces.png)
![Evaluation Panel](docs/screenshots/evaluation_panel.png)

---

## 检索流程详解

### 混合检索（Hybrid Search）

系统同时使用两种检索策略，取长补短：

| 检索方式 | 算法 | 优势 | 适用场景 |
|---------|------|------|---------|
| **Dense** | 向量相似度（余弦）| 语义理解、近义词匹配 | 概念性问题、意图理解 |
| **Sparse** | BM25 关键词匹配 | 精确术语、专有名词 | 事实查询、具体关键词 |

### RRF 融合

两种检索结果用 **Reciprocal Rank Fusion** 算法融合：

```
RRF_score(d) = Σ 1/(k + rank(d))

其中 k=60，d 为文档，rank(d) 为该文档在各检索结果中的排名
```

这种方式让语义相关和关键词相关的结果都能被保留，避免单一检索的偏差。

---

## 检索效果评估

系统内置了量化评估工具，基于 15 条针对《深度学习》教材的真实查询测试集评估检索质量。

### 运行评估

```bash
python scripts/evaluate.py --collection knowledge_hub --top-k 5
```

### 评估结果

```
AGGREGATE METRICS
hit_rate                 ████████████████████ 1.0000   (15/15 查询均命中)
mrr                      ██████████████████░░ 0.9000   (平均倒数排名)
```

| 指标 | 含义 | 本项目得分 |
|------|------|----------|
| **Hit Rate@5** | Top-5 结果中包含正确答案的查询比例 | **100%** (15/15) |
| **MRR** | 平均倒数排名，越接近 1 越好 | **0.90** |

> 测试集来源：`tests/fixtures/golden_test_set.json`，共 15 条深度学习领域查询，文档库为 `dlbook_cn_v0.5-beta.pdf`（1180 chunks）。

### 测试集维护

编辑 `tests/fixtures/golden_test_set.json` 增减测试用例：

```json
{
  "query": "你的问题",
  "expected_chunk_ids": ["chunk_id_1", "chunk_id_2"],
  "reference_answer": "参考答案（可选，用于LLM-as-Judge评估）"
}
```

---

## 高级配置

### 切换 LLM Provider

**DeepSeek**（默认）:

```yaml
llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  base_url: "https://api.deepseek.com"
  api_key: "${DEEPSEEK_API_KEY}"
```

**OpenAI**:

```yaml
llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"
```

**Ollama（本地，无需 API Key）**:

```yaml
llm:
  provider: "ollama"
  model: "llama3"
  base_url: "http://localhost:11434"
```

### 启用 Rerank（增加延迟，精度更高）

```yaml
rerank:
  enabled: true
  provider: "cross-encoder"
  model: "cross-encoder/ms-marco-MiniLM-L-6-v2"
  top_k: 5
```

### 启用 Redis 缓存（降低 API 调用成本）

```yaml
redis:
  enabled: true
  host: "localhost"
  port: 6379
  db: 0
  password: null                        # 有密码则填入 "${REDIS_PASSWORD}"
  ttl:
    embedding: 604800                  # Embedding 向量缓存（秒），默认 7 天
    llm_response: 86400                # LLM 响应缓存，默认 1 天
    session: 3600                      # 会话记忆滑动 TTL，默认 1 小时
```

**说明**：

| 缓存类型 | 作用 | 命中效果 |
|---------|------|---------|
| Embedding Cache | 相同文本复用向量 | 重复 chunk 导入跳过 Embedding API 调用 |
| LLM Response Cache | 相同 prompt + 文本复用 LLM 结果 | ChunkRefiner / MetadataEnricher 跳过 LLM 调用 |
| Session Memory | 多轮对话历史持久化 | 下次查询可携带上下文（`session_id` 参数） |

> Redis 不可用时所有缓存自动降级为 no-op，不影响系统正常运行。

**快速启动 Redis**（Docker）：

```bash
docker run -d -p 6379:6379 redis
```

启动后 `settings.yaml` 中 `redis.enabled: true` 即可启用全部三层缓存。

### 启用多模态（Vision LLM，用于 PDF 中的图表理解）

```yaml
vision_llm:
  enabled: true
  provider: "openai"
  model: "gpt-4o"
  api_key: "${VISION_LLM_API_KEY}"
```

### 分块参数调优

```yaml
ingestion:
  chunk_size: 1000      # 增大：上下文更完整；减小：检索精度更高
  chunk_overlap: 200     # 块之间重叠 token 数，防止边界切断
```

### PDF 质量检查调优

详见 [PDF 质量检查](#pdf-质量检查) 章节。常用配置：

```yaml
ingestion:
  quality_check:
    enabled: true
    min_valid_ratio: 0.80
    min_text_density: 0.20
    check_first_n_pages: 3
    fail_on_scanned: false
```

### 检索参数调优

```yaml
retrieval:
  dense_top_k: 20        # 初始 Dense 召回数量
  sparse_top_k: 20       # 初始 BM25 召回数量
  fusion_top_k: 10       # RRF 融合后保留数量
  rrf_k: 60              # RRF 公式参数，越大两种检索越平等
```

---

## 测试与 Fixture

项目自带 60+ 个单元 / 集成测试，覆盖 PDF 质量检查、流水线集成、检索查询等核心链路。

### 运行测试

```bash
# 全部单元 + 集成测试
python -m pytest tests/unit/ -v

# 只跑 PDF 质量检查相关（47 个单测 + 9 个集成测试）
python -m pytest tests/unit/test_pdf_quality_checker.py tests/unit/test_pipeline_quality_check_integration.py -v
```

### 测试套件概览

| 测试文件 | 覆盖范围 | 用例数 |
|---------|---------|--------|
| `tests/unit/test_pdf_quality_checker.py` | 字符分类、扫描件检测、噪声判定、5 级质量分级、`DocumentQualityError` 语义 | 47 |
| `tests/unit/test_pipeline_quality_check_integration.py` | Stage 2b 在 `IngestionPipeline` 中的真实集成：清洁 PDF、扫描件、`fail_on_scanned`、禁用、阶段顺序 | 9 |
| `tests/unit/test_pipeline_progress.py` | `IngestionPipeline.run()` 的 6 阶段 `on_progress` 回调 | 6 |

### Fixture 文件说明

`tests/fixtures/sample_documents/` 下的 PDF 均为**程序可重新生成**的产物，便于在 CI 中复现：

| Fixture | 生成脚本 | 用途 |
|---------|---------|------|
| `simple.pdf` | `sample_documents/generate_pdfs.py` | 纯文本最小 PDF，MarkItDown/pypdf 基线测试 |
| `with_images.pdf` | `sample_documents/generate_pdfs.py` | 含图片的 PDF，验证图像抽取 |
| `complex_technical_doc.pdf` | `generate_complex_pdf.py` | 多章节 / 多表格 / 多图 / 中英文混排，覆盖 PDF 解析综合场景 |
| `scanned.pdf` | `generate_scanned_pdf.py` | **真实扫描件** —— 3 页全光栅图像，`pypdf.extract_text()` 返回空串，触发 `is_scanned=True` |
| `blogger_intro.pdf`, `chinese_long_doc.pdf`, `chinese_table_chart_doc.pdf`, `chinese_technical_doc.pdf` | `generate_blogger_intro_pdf.py`, `generate_qa_test_pdfs.py` | 评估测试集对应的真实风格文档 |

### 复现/扩展 Fixture

```bash
# 重新生成所有标准 PDF fixture
python tests/fixtures/sample_documents/generate_pdfs.py
python tests/fixtures/generate_complex_pdf.py
python tests/fixtures/generate_scanned_pdf.py   # 三页全图扫描件，~400 KB

# 重新生成评估测试 PDF
python tests/fixtures/generate_blogger_intro_pdf.py
python tests/fixtures/generate_qa_test_pdfs.py
```

> **设计要点**：所有生成器均无外部网络依赖，使用 `reportlab` + `Pillow` 本地生成，CI 中可一键复现。

---

## 项目结构

```
modular-rag-mcp-server/
├── config/
│   ├── settings.yaml          # 统一配置（密钥通过 ${ENV_VAR} 引用 .env）
│   └── prompts/               # Rerank / System prompts
├── docs/
│   └── screenshots/           # Dashboard 页面截图
├── documents/                 # 待导入文档目录（PDF/MD/TXT）
│   └── .gitkeep
├── src/
│   ├── core/
│   │   ├── settings.py        # 配置加载（含 env var 展开）
│   │   ├── query_engine/      # 混合检索引擎
│   │   │   ├── hybrid_search.py
│   │   │   ├── dense_retriever.py
│   │   │   ├── sparse_retriever.py
│   │   │   ├── reranker.py
│   │   │   └── query_processor.py
│   │   └── response/          # 响应构建（含引用格式）
│   ├── ingestion/
│   │   ├── pipeline.py        # 摄取流水线（集成 PDF 质量检查）
│   │   ├── storage/           # ChromaDB + BM25
│   │   └── splitter/          # 分块策略
│   ├── libs/
│   │   ├── llm/              # LLM 工厂（DeepSeek / OpenAI / Ollama）
│   │   ├── embedding/        # Embedding 工厂（HuggingFace）
│   │   ├── vector_store/     # VectorStore 工厂（ChromaDB）
│   │   ├── loader/           # PDF 加载 + 文本层质量检查
│   │   │   ├── base_loader.py
│   │   │   ├── pdf_loader.py
│   │   │   ├── pdf_quality_checker.py   # 扫描件/噪声/低密度检测
│   │   │   └── file_integrity.py
│   │   └── redis/            # Redis 缓存（Embedding / LLM 响应 / 会话记忆）
│   ├── mcp_server/
│   │   ├── server.py         # MCP 服务入口（stdio）
│   │   ├── protocol_handler.py
│   │   └── tools/            # 12 个 MCP 工具
│   └── observability/         # 日志 + 追踪
├── scripts/
│   ├── ingest.py             # 命令行导入工具
│   └── query.py              # 命令行查询工具
├── tests/
│   ├── fixtures/             # 测试 fixture + 程序化生成器
│   │   ├── generate_complex_pdf.py
│   │   ├── generate_scanned_pdf.py     # 扫描件 PDF 生成器
│   │   ├── generate_blogger_intro_pdf.py
│   │   ├── generate_qa_test_pdfs.py
│   │   ├── golden_test_set.json        # 检索评估测试集
│   │   └── sample_documents/           # 实际 PDF fixture
│   │       ├── generate_pdfs.py
│   │       ├── simple.pdf
│   │       ├── with_images.pdf
│   │       ├── complex_technical_doc.pdf
│   │       └── scanned.pdf             # 三页光栅扫描件
│   └── unit/                 # 单元 / 集成测试（60+ 用例）
│       ├── test_pdf_quality_checker.py            # 47 个单测
│       ├── test_pipeline_quality_check_integration.py  # 9 个集成测试
│       └── test_pipeline_progress.py               # 6 个阶段回调测试
├── main.py                   # MCP 服务入口
├── .env                      # 密钥文件（不提交）
├── .env.example              # 密钥模板
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 许可证

MIT License
