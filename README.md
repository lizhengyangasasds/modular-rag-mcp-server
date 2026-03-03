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
- [检索流程详解](#检索流程详解)
- [高级配置](#高级配置)
- [项目结构](#项目结构)

---

## 项目简介

本项目是一个**模块化、可配置**的 RAG（检索增强生成）服务，将文档摄取、混合检索、向量存储与 MCP 工具暴露串联为可运行系统。文档在本地完成解析与向量化，支持对接私有知识库，供 AI 助手通过标准 MCP 协议调用。

**适用场景**: 个人/团队私有文档问答、技术资料检索、与大模型应用开发岗位相关的作品集展示。

---

## 核心能力

| 模块 | 说明 |
|------|------|
| **文档摄取** | PDF → 分块 → 元数据增强 → 向量化 → 写入 Chroma + BM25 索引 |
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
│  └─────────────┘   │   scripts/ingest.py   │  │  Stage 2: 分块 (chunk)   │  │
│                    │        或              │  │  Stage 3: LLM 元数据增强   │  │
│  MCP Client        │   MCP: ingest_documents │  │  Stage 4: 本地 Embedding  │  │
│  (Cursor) ─────────▶│                        │  │  Stage 5: ChromaDB 存储   │  │
│                    └──────────┬─────────────┘  │  Stage 6: BM25 索引      │  │
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

- **documents/** → PDF 解析 → 分块 → LLM 元数据增强 → 本地 Embedding → ChromaDB + BM25
- **用户查询** → Dense 检索（向量相似度）+ Sparse 检索（BM25）→ RRF 融合 → LLM 生成 → 带引用返回
- **MCP 协议** → 通过 stdio 传输 JSON-RPC，支持 Cursor / Claude App 等客户端

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

### 检索参数调优

```yaml
retrieval:
  dense_top_k: 20        # 初始 Dense 召回数量
  sparse_top_k: 20       # 初始 BM25 召回数量
  fusion_top_k: 10       # RRF 融合后保留数量
  rrf_k: 60              # RRF 公式参数，越大两种检索越平等
```

---

## 项目结构

```
modular-rag-mcp-server/
├── config/
│   ├── settings.yaml          # 统一配置（密钥通过 ${ENV_VAR} 引用 .env）
│   └── prompts/               # Rerank / System prompts
├── documents/                # 待导入文档目录（PDF/MD/TXT）
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
│   │   ├── pipeline.py        # 摄取流水线
│   │   ├── storage/           # ChromaDB + BM25
│   │   └── splitter/          # 分块策略
│   ├── libs/
│   │   ├── llm/              # LLM 工厂（DeepSeek / OpenAI / Ollama）
│   │   ├── embedding/        # Embedding 工厂（HuggingFace）
│   │   └── vector_store/     # VectorStore 工厂（ChromaDB）
│   ├── mcp_server/
│   │   ├── server.py         # MCP 服务入口（stdio）
│   │   ├── protocol_handler.py
│   │   └── tools/            # 12 个 MCP 工具
│   └── observability/         # 日志 + 追踪
├── scripts/
│   ├── ingest.py             # 命令行导入工具
│   └── query.py              # 命令行查询工具
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
