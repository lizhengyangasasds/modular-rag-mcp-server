# GitHub Pages 部署说明

本目录用于 GitHub Pages 静态站点部署。

## 当前文件

- `dashboard_report.html` — Dashboard 完整 HTML 报告（6 个页面，可折叠展开）

## 启用步骤

### 1. 推送 docs/ 目录到 GitHub

```bash
git add docs/
git commit -m "docs: add dashboard HTML report for GitHub Pages"
git push origin main
```

### 2. 启用 GitHub Pages

1. 打开 https://github.com/lizhengyangasasds/modular-rag-mcp-server/settings/pages
2. **Source** 选择 **Deploy from a branch**
3. **Branch** 选择 `main`，文件夹选择 `/ (root)`
4. 点击 **Save**

### 3. 等待部署（约 1-2 分钟）

访问 `https://lizhengyangasasds.github.io/modular-rag-mcp-server/dashboard_report.html`

## 关于 index.html

如需作为根路径直接访问，可将 `dashboard_report.html` 重命名为 `index.html`，之后直接访问：

```
https://lizhengyangasasds.github.io/modular-rag-mcp-server/
```

## 注意事项

- 报告数据基于 `docs/dashboard_data.json`，如需更新请运行：
  ```bash
  python docs/_collect_dashboard_data.py
  python docs/_gen_html_report.py
  ```
- 数据为静态快照，如需实时数据请访问 http://localhost:8502
