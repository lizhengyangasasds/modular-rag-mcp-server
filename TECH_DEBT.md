# Technical Debt & Known Limitations

This file tracks known design / implementation trade-offs that are acceptable
for the current scope but should be revisited when scale, latency, or
correctness requirements change.

Each entry follows:

```
### [TD-NNN] Short title
- **Discovered**: YYYY-MM-DD
- **Component**: file / module path
- **Impact**: what hurts today (perf / correctness / ops)
- **Trigger to revisit**: condition under which we MUST fix it
- **Proposed fix**: concrete next step
- **Effort**: S/M/L
```

---

## TD-001: BM25 倒排索引不是「真增量」，是文档级增量

- **Discovered**: 2026-07-05
- **Component**: `src/ingestion/storage/bm25_indexer.py::BM25Indexer.add_documents`
- **Impact**:
  - 接口叫 `add_documents`，看起来是增量；但实现是 `O(N_total_corpus)`：
    1. 从已有 postings 反推 `term_stats`
    2. 与新 stats 合并后调 `self.build(combined, ...)`
    3. `build` 内部重算全部 term 的 IDF 和 `avg_doc_length`
    4. 整个 JSON 文件 `_save` 覆盖重写
  - 幂等性 OK（重传同文档通过 `doc_id` 清理 stale posting）
  - 正确性 OK（merge 后重算，IDF 一致）
  - **性能问题**：corpus 大于 ~10 万 chunk 时，每次 ingest 一个文件都触发全量重算
- **Trigger to revisit**:
  - 单一 collection chunk 数 > 50k
  - 或：单次 ingest 耗时 P95 > 30s
  - 或：磁盘 I/O 成为 ingest 瓶颈（每次整个 JSON 重写）
- **Proposed fix** (三种递进方案):
  1. **S**：保留 JSON 结构，缓存 IDF/avg_doc_length 到独立 `*.meta.json`，增量更新时只 append posting，IDF 用增量公式
  2. **M**：用 SQLite 存倒排表 + 内存 mmap，posting list append-only + 周期性 vacuum
  3. **L**：替换为 Lucene / Tantivy / Whoosh 库，使用真正的 segment-merge 架构
- **Effort**: S / M / L
- **Resume-safe phrasing**: 当前实现对未变更的 doc/chunk 跳过重处理（文档级增量）；BM25 层接口幂等，但底层是 O(N_total) rebuild；生产规模可平滑迁移到 Lucene 类引擎。
- **Related**: `src/ingestion/pipeline.py` 调用方无须改动；接口稳定。

---

## TD-002 (placeholder)

_未发现其他明确技术债。后续发现请追加在此文件。_