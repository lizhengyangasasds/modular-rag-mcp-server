# Modular RAG MCP Server - Deployment Guide
> 本文档提供 Modular RAG MCP Server 的完整部署指南，涵盖本地开发、生产环境和 Docker 部署。
> 版本：v0.1.0 | 最后更新：2026-07-06

---

## 1. 环境准备

### 1.1 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 内存 | 8 GB | 16 GB+ |
| 磁盘 | 10 GB 可用空间 | 50 GB+ NVMe SSD |
| GPU | 可选 | NVIDIA GPU 12GB+ |
| Python | 3.10+ | 3.11 或 3.12 |
| OS | Windows 10+ / macOS 12+ / Ubuntu 20.04+ | Windows 11 / macOS 14 / Ubuntu 22.04 |

### 1.2 安装依赖

```bash
# 克隆项目
git clone https://github.com/your-repo/modular-rag-mcp-server.git
cd modular-rag-mcp-server

# 创建虚拟环境（推荐）
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "from src.ingestion.pipeline import IngestionPipeline; print('OK')"
```

### 1.3 环境变量配置

创建 `.env` 文件（不要提交到 Git）：

```bash
# LLM API Keys（至少配置一个）
DEEPSEEK_API_KEY=sk-your-deepseek-key
OPENAI_API_KEY=sk-your-openai-key
AZURE_OPENAI_KEY=your-azure-key
ANTHROPIC_API_KEY=sk-ant-your-key

# HuggingFace（可选，用于加速模型下载）
HF_TOKEN=hf_your-token

# Redis（可选，用于缓存）
REDIS_PASSWORD=your-redis-password

# MCP Server
MCP_SERVER_HOST=0.0.0.0
MCP_SERVER_PORT=8000
```

---

## 2. 快速启动

### 2.1 启动 Dashboard

```bash
# 方式一：使用项目脚本
python scripts/start_dashboard.py

# 方式二：直接使用 streamlit
streamlit run src/observability/dashboard/app.py \
    --server.headless true \
    --server.port 8501 \
    --theme.base dark
```

访问 `http://localhost:8501` 即可看到 Dashboard。

### 2.2 启动 MCP Server

```bash
# 方式一：使用 MCP CLI
mcp dev python src/mcp_server/main.py

# 方式二：直接运行
python src/mcp_server/main.py --host 0.0.0.0 --port 8000

# 方式三：生产环境使用 uvicorn
uvicorn src.mcp_server.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \
    --log-level info
```

### 2.3 使用 Ingestion CLI

```bash
# 摄入单个文件
python scripts/ingest.py --path documents/report.pdf --collection my_docs

# 摄入整个目录
python scripts/ingest.py --path documents/ --collection my_docs

# 强制重新摄入
python scripts/ingest.py --path documents/report.pdf --force

# 列出文件（不实际处理）
python scripts/ingest.py --path documents/ --dry-run
```

---

## 3. Docker 部署

### 3.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p data/db data/images logs

# 暴露端口
EXPOSE 8501 8000

# 启动命令
CMD ["streamlit", "run", "src/observability/dashboard/app.py", "--server.headless", "true"]
```

### 3.2 docker-compose.yml

```yaml
version: "3.8"

services:
  rag-server:
    build: .
    ports:
      - "8501:8501"   # Dashboard
      - "8000:8000"   # MCP Server
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - REDIS_HOST=redis
      - REDIS_PORT=6379
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped

volumes:
  redis-data:
```

### 3.3 启动 Docker 环境

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f rag-server

# 停止
docker-compose down
```

---

## 4. 生产环境配置

### 4.1 Nginx 反向代理配置

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Dashboard
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # MCP Server API
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # WebSocket 支持（如果使用）
    location /ws {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4.2 HTTPS 配置（Let's Encrypt）

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期（Certbot 自动配置）
sudo systemctl status certbot.timer
```

### 4.3 systemd 服务配置

创建 `/etc/systemd/system/rag-server.service`：

```ini
[Unit]
Description=Modular RAG MCP Server
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/modular-rag-mcp-server
Environment="DEEPSEEK_API_KEY=sk-xxx"
Environment="PATH=/opt/modular-rag-mcp-server/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
ExecStart=/opt/modular-rag-mcp-server/.venv/bin/streamlit run src/observability/dashboard/app.py --server.headless true --server.port 8501
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-server
sudo systemctl start rag-server
sudo systemctl status rag-server
```

---

## 5. 数据管理

### 5.1 数据目录结构

```
data/
├── db/
│   ├── chroma/              # ChromaDB 向量数据库
│   │   ├── chroma.sqlite
│   │   └── ...
│   ├── bm25/               # BM25 倒排索引
│   │   └── knowledge_hub/
│   │       └── index.json
│   ├── ingestion_history.db # 摄取历史
│   └── image_index.db      # 图像索引
├── images/                 # 提取的图像文件
│   └── {doc_hash}/
│       └── {image_id}.png
└── cache/                  # 本地缓存（Redis 不可用时）
```

### 5.2 数据备份

```bash
# 备份整个数据目录
tar -czf backup_$(date +%Y%m%d).tar.gz data/

# 备份 ChromaDB（SQLite 格式）
cp data/db/chroma/chroma.sqlite backup_chroma_$(date +%Y%m%d).sqlite

# 备份 BM25 索引
cp -r data/db/bm25 backup_bm25_$(date +%Y%m%d)/
```

### 5.3 数据恢复

```bash
# 解压恢复
tar -xzf backup_20260706.tar.gz

# 恢复 ChromaDB
cp backup_chroma_20260706.sqlite data/db/chroma/chroma.sqlite

# 恢复 BM25
cp -r backup_bm25_20260706/* data/db/bm25/
```

---

## 6. 安全配置

### 6.1 防火墙设置

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# 只允许本地访问（开发环境）
sudo ufw allow from 127.0.0.1 to any port 8501
sudo ufw allow from 127.0.0.1 to any port 8000
```

### 6.2 API Key 安全

- **永远不要**将 API Key 写入代码或提交到 Git
- 使用环境变量或 `.env` 文件
- 生产环境使用 Vault 或 AWS Secrets Manager 管理密钥
- 定期轮换 API Key

### 6.3 访问控制

```python
# middleware/auth.py
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != os.environ.get("RAG_API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key
```

---

## 7. 运维监控

### 7.1 健康检查

```bash
# Dashboard 健康检查
curl -s http://localhost:8501/_stcore/health

# MCP Server 健康检查
curl -s http://localhost:8000/health

# ChromaDB 连接检查
curl -s http://localhost:8000/api/v1/collections/knowledge_hub/count
```

### 7.2 日志管理

```bash
# 查看最近日志
tail -f logs/traces.jsonl | jq

# 统计错误
grep '"status": "error"' logs/traces.jsonl | jq '.error' | sort | uniq -c

# 分析查询延迟
cat logs/traces.jsonl | jq 'select(.trace_type == "query") | .total_duration_ms' \
    | awk '{sum+=$1; count++} END {print "Avg:", sum/count, "ms, Total:", count}'
```

### 7.3 自动告警脚本

```python
# scripts/health_check.py
import requests
import time
import os
from pathlib import Path

WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK")

def check_system():
    # Check Dashboard
    try:
        r = requests.get("http://localhost:8501/_stcore/health", timeout=5)
        if r.status_code != 200:
            send_alert("Dashboard is down!")
    except:
        send_alert("Dashboard is unreachable!")

    # Check query latency
    from scripts.query import _build_components, _run_query
    # ... measure latency and alert if P99 > threshold

def send_alert(message):
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"text": message})
    print(f"ALERT: {message}")

if __name__ == "__main__":
    check_system()
```

---

## 8. 故障排查

### 8.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| Dashboard 启动失败 | 端口被占用 | `lsof -i :8501` 查看并 `kill` 占用进程 |
| ChromaDB 查询为空 | 尚未摄入任何文档 | 先运行 `scripts/ingest.py` |
| LLM Transform 超时 | API 限流或网络问题 | 设置 `use_llm: false` 跳过 |
| 内存溢出 (OOM) | 文档过大或 batch_size 过大 | 减小 batch_size 或分批处理 |
| 图片提取失败 | PyMuPDF 未安装 | `pip install pymupdf` |

### 8.2 日志调试

```bash
# 启动 DEBUG 模式
export LOG_LEVEL=DEBUG
python scripts/ingest.py --path documents/ --verbose

# 查看特定阶段日志
grep "Stage 5" logs/traces.jsonl | jq

# 追踪单个查询
python scripts/query.py --query "Transformer 是什么" --verbose
```

---

*部署遇到问题？请查看 `docs/troubleshooting.md` 或提交 Issue。*
