"""
Generate a standalone HTML report that mirrors all 6 Dashboard pages
using the data collected by _collect_dashboard_data.py.
"""

import json, os
from pathlib import Path

BASE = Path(__file__).parent
DATA_FILE = BASE / "dashboard_data.json"
OUT_FILE = BASE / "dashboard_report.html"

with open(DATA_FILE, encoding="utf-8") as f:
    data = json.load(f)

collections = data.get("collections", [])
docs = data.get("documents", [])
coll_stats = data.get("collection_stats", {})
doc_details = data.get("document_details", [])
ingestion_traces = data.get("ingestion_traces", [])
query_traces = data.get("query_traces", [])
component_cards = data.get("component_cards", [])

# Sample chunks for display (first 5 and last 5)
all_chunks = []
for dd in doc_details:
    for c in dd.get("chunks", []):
        all_chunks.append(c)

SAMPLE_CHUNKS = all_chunks[:5] + all_chunks[-5:] if len(all_chunks) > 10 else all_chunks[:10]


def esc(s):
    if s is None:
        return ""
    return (str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))

def truncate(text, length=300):
    t = str(text)
    return t[:length] + ("..." if len(t) > length else "")

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Modular RAG Dashboard Report</title>
<style>
  :root {
    --bg: #0f172a;
    --surface: #1e293b;
    --border: #334155;
    --accent: #38bdf8;
    --accent2: #818cf8;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --green: #4ade80;
    --yellow: #fbbf24;
    --red: #f87171;
    --purple: #c084fc;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  /* ── Sidebar nav ── */
  nav {
    position: fixed; top: 0; left: 0; width: 220px; height: 100vh;
    background: var(--surface); border-right: 1px solid var(--border);
    overflow-y: auto; padding: 1rem 0; z-index: 100;
  }
  nav h2 { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); padding: 0 1rem 0.5rem; }
  nav a { display: block; padding: 0.6rem 1rem; color: var(--text); font-size: 0.9rem; border-left: 3px solid transparent; }
  nav a:hover { background: rgba(255,255,255,0.05); text-decoration: none; }
  nav a.active { border-left-color: var(--accent); background: rgba(56,189,248,0.1); color: var(--accent); }

  /* ── Main content ── */
  main { margin-left: 220px; padding: 2rem 3rem 4rem; max-width: 1100px; }

  section { margin-bottom: 4rem; }
  h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: 0.25rem; color: var(--accent); }
  .subtitle { color: var(--muted); font-size: 0.9rem; margin-bottom: 2rem; }
  h2 { font-size: 1.2rem; font-weight: 600; margin: 2rem 0 1rem; color: var(--text); border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
  h3 { font-size: 1rem; font-weight: 600; color: var(--accent2); margin: 1rem 0 0.5rem; }

  /* ── Cards ── */
  .card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 1.2rem; transition: border-color 0.2s;
  }
  .card:hover { border-color: var(--accent); }
  .card h4 { font-size: 0.95rem; margin-bottom: 0.4rem; }
  .card p { font-size: 0.8rem; color: var(--muted); margin: 0.2rem 0; }
  .card .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 99px; font-size: 0.7rem; background: rgba(56,189,248,0.15); color: var(--accent); }

  /* ── Metric tiles ── */
  .metric-row { display: flex; gap: 1rem; flex-wrap: wrap; }
  .metric {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.8rem 1.4rem; text-align: center; min-width: 120px;
  }
  .metric .val { font-size: 1.8rem; font-weight: 700; color: var(--accent); }
  .metric .lbl { font-size: 0.75rem; color: var(--muted); margin-top: 0.2rem; text-transform: uppercase; letter-spacing: 0.05em; }

  /* ── Tables ── */
  .tbl { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 0.5rem 0; }
  .tbl th { text-align: left; padding: 0.5rem 0.8rem; background: rgba(255,255,255,0.04); color: var(--accent); border-bottom: 1px solid var(--border); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .tbl td { padding: 0.5rem 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: top; }
  .tbl tr:hover td { background: rgba(255,255,255,0.02); }
  .tbl code { font-size: 0.75rem; color: var(--purple); background: rgba(192,132,252,0.1); padding: 0.1rem 0.3rem; border-radius: 3px; }

  /* ── Expanders (collapsed by default) ── */
  details { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin: 0.5rem 0; overflow: hidden; }
  summary { padding: 0.7rem 1rem; cursor: pointer; font-weight: 600; font-size: 0.9rem; list-style: none; display: flex; align-items: center; gap: 0.5rem; }
  summary::-webkit-details-marker { display: none; }
  summary:before { content: "▸"; transition: transform 0.2s; }
  details[open] summary:before { transform: rotate(90deg); }
  details[open] { border-color: var(--accent); }
  details .inner { padding: 0.8rem 1rem 1rem; border-top: 1px solid var(--border); }

  /* ── Code / text blocks ── */
  pre, .text-block {
    background: rgba(0,0,0,0.3); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.8rem; font-size: 0.8rem;
    font-family: 'Consolas', monospace; white-space: pre-wrap;
    word-break: break-word; max-height: 250px; overflow-y: auto; color: #d1d5db;
  }

  /* ── Alerts ── */
  .info-box { padding: 0.8rem 1rem; border-radius: 6px; font-size: 0.85rem; margin: 0.5rem 0; border-left: 3px solid; }
  .info-box.info { background: rgba(56,189,248,0.08); border-color: var(--accent); color: #7dd3fc; }
  .info-box.warn { background: rgba(251,191,36,0.08); border-color: var(--yellow); color: #fcd34d; }
  .info-box.success { background: rgba(74,222,128,0.08); border-color: var(--green); color: #86efac; }

  /* ── Charts (text-based) ── */
  .bar-chart { margin: 0.5rem 0; }
  .bar-row { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; margin: 0.3rem 0; }
  .bar-label { width: 120px; flex-shrink: 0; color: var(--muted); }
  .bar-track { flex: 1; background: rgba(255,255,255,0.05); border-radius: 3px; height: 16px; }
  .bar-fill { height: 100%; border-radius: 3px; background: var(--accent); transition: width 0.4s; }
  .bar-val { width: 60px; text-align: right; color: var(--text); font-size: 0.75rem; }

  /* ── Footer ── */
  footer { text-align: center; color: var(--muted); font-size: 0.75rem; padding: 2rem; border-top: 1px solid var(--border); margin-left: 220px; }
</style>
</head>
<body>

<!-- ── Sidebar ── -->
<nav>
  <h2>Pages</h2>
  <a href="#overview">📊 System Overview</a>
  <a href="#data-browser">🔍 Data Browser</a>
  <a href="#ingestion-manager">📥 Ingestion Manager</a>
  <a href="#ingestion-traces">🔬 Ingestion Traces</a>
  <a href="#query-traces">🔎 Query Traces</a>
  <a href="#evaluation-panel">📏 Evaluation Panel</a>
</nav>

<!-- ── Main ── -->
<main>

"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 1: System Overview
# ═══════════════════════════════════════════════════════════════════
html += """
<section id="overview">
  <h1>📊 System Overview</h1>
  <p class="subtitle">Component configuration, collection statistics, and trace metrics</p>

  <h2>🔧 Component Configuration</h2>
  <div class="card-grid">
"""

for card in component_cards:
    extra_rows = "".join(f"<p>{esc(k)}: <code>{esc(str(v))}</code></p>" for k, v in card.get("extra", {}).items())
    html += f"""
    <div class="card">
      <h4>🔗 {esc(card['name'])}</h4>
      <p><span class="badge">{esc(card['provider'])}</span></p>
      <p>Model: <code>{esc(card['model'])}</code></p>
      {extra_rows}
    </div>
"""

html += """
  </div>

  <h2>📁 Collection Statistics</h2>
  <div class="metric-row">
"""

for col_name, stats in coll_stats.items():
    cc = stats.get("chunk_count", 0)
    html += f"""
    <div class="metric">
      <div class="val">{cc:,}</div>
      <div class="lbl">{esc(col_name)}</div>
    </div>
"""

html += """
  </div>
"""

# Fake trace stats
trace_file = BASE / "logs" / "traces.jsonl"
trace_count = 0
if trace_file.exists():
    with open(trace_file, encoding="utf-8") as f:
        trace_count = sum(1 for _ in f)

html += f"""
  <h2>📈 Trace Statistics</h2>
  <div class="metric-row">
    <div class="metric">
      <div class="val">{trace_count}</div>
      <div class="lbl">Total Traces</div>
    </div>
    <div class="metric">
      <div class="val">{len(ingestion_traces)}</div>
      <div class="lbl">Ingestion Traces</div>
    </div>
    <div class="metric">
      <div class="val">{len(query_traces)}</div>
      <div class="lbl">Query Traces</div>
    </div>
  </div>
"""

# Stage timing bar chart (from first ingestion trace if available)
if ingestion_traces:
    trace = ingestion_traces[0]
    timings_key = "stages"
    if timings_key in trace:
        stages = trace[timings_key]
        if isinstance(stages, list):
            html += """
  <h2>⏱️ Latest Ingestion Pipeline — Stage Timing Waterfall</h2>
  <div class="bar-chart">
"""
            max_ms = max((s.get("elapsed_ms", 0) for s in stages), default=1)
            for s in stages:
                ms = s.get("elapsed_ms", 0)
                pct = max(1, int(ms / max_ms * 100))
                html += f"""
    <div class="bar-row">
      <div class="bar-label">{esc(s.get('stage_name', '?'))}</div>
      <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
      <div class="bar-val">{ms:.1f} ms</div>
    </div>
"""
            html += "  </div>\n"

html += """
</section>
"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 2: Data Browser
# ═══════════════════════════════════════════════════════════════════
html += """
<section id="data-browser">
  <h1>🔍 Data Browser</h1>
  <p class="subtitle">Browse ingested documents, chunks, and images</p>

  <h2>Available Collections</h2>
  <p><span class="badge">""" + "</span> <span class='badge'>".join(f"{esc(c)}" for c in collections) + """</span></p>

  <h2>📄 Documents</h2>
"""

if not docs:
    html += '<div class="info-box info">No documents found in this collection.</div>\n'
else:
    html += f'<p style="color:var(--muted);font-size:0.9rem;margin-bottom:1rem">{len(docs)} document(s) found</p>\n'
    html += '<table class="tbl"><thead><tr><th>Source</th><th>Collection</th><th>Chunks</th><th>Images</th><th>Processed</th></tr></thead><tbody>\n'
    for d in docs:
        src = Path(d["source_path"]).name
        html += f"""<tr>
  <td><code>{esc(src)}</code></td>
  <td><span class="badge">{esc(d.get('collection',''))}</span></td>
  <td>{d['chunk_count']:,}</td>
  <td>{d['image_count']}</td>
  <td>{esc(d.get('processed_at','')[:19])}</td>
</tr>\n"""
    html += '</tbody></table>\n'

# Sample chunks
if SAMPLE_CHUNKS:
    html += """
  <h2>📦 Sample Chunks (first 5 + last 5)</h2>
  <p class="info-box info" style="margin-bottom:1rem">Showing 10 of """ + f"{len(all_chunks):,}" + """ total chunks for readability</p>
"""
    for i, chunk in enumerate(SAMPLE_CHUNKS):
        cid = chunk.get("id", "")
        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        html += f"""
<details>
  <summary>Chunk {i+1} — <code>{esc(cid[-16:])}</code> · {len(text):,} chars</summary>
  <div class="inner">
    <pre>{esc(text[:800])}</pre>
    <h3>Metadata</h3>
    <pre>{esc(json.dumps(meta, ensure_ascii=False, indent=2)[:500])}</pre>
  </div>
</details>
"""

html += """
</section>
"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 3: Ingestion Manager
# ═══════════════════════════════════════════════════════════════════
html += """
<section id="ingestion-manager">
  <h1>📥 Ingestion Manager</h1>
  <p class="subtitle">Upload files, trigger ingestion, manage documents</p>

  <h2>📤 Upload &amp; Ingest</h2>
  <div class="info-box info">
    <strong>Upload a file</strong> (PDF, TXT, MD, DOCX) → Select collection → Click <strong>🚀 Start Ingestion</strong>
  </div>

  <h2>🗑️ Manage Documents</h2>
"""

if not docs:
    html += '<div class="info-box info">No documents ingested yet. Upload a file above.</div>\n'
else:
    for d in docs:
        src = Path(d["source_path"]).name
        html += f"""
<div class="card" style="margin:0.5rem 0">
  <h4>📄 {esc(src)}</h4>
  <p>Collection: <span class="badge">{esc(d.get('collection',''))}</span> · Chunks: {d['chunk_count']:,} · Images: {d['image_count']}</p>
  <p style="margin-top:0.5rem; font-size:0.75rem; color:var(--muted)">
    Hash: <code>{d['source_hash'][:32]}…</code> · Processed: {esc(d.get('processed_at','')[:19])}
  </p>
</div>
"""

html += """
</section>
"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 4: Ingestion Traces
# ═══════════════════════════════════════════════════════════════════
html += """
<section id="ingestion-traces">
  <h1>🔬 Ingestion Traces</h1>
  <p class="subtitle">Browse ingestion trace history with per-stage detail</p>
"""

if not ingestion_traces:
    html += '<div class="info-box info">No ingestion traces recorded yet. Run an ingestion first!</div>\n'
else:
    html += f'<p style="color:var(--muted);margin-bottom:1rem">{len(ingestion_traces)} trace(s)</p>\n'
    for i, trace in enumerate(ingestion_traces[:10]):  # cap at 10
        tid = trace.get("trace_id", "unknown")
        started = trace.get("started_at", "—")
        total_ms = trace.get("elapsed_ms", 0)
        meta = trace.get("metadata", {})
        sp = meta.get("source_path", "—")
        fname = Path(sp).name if sp != "—" else "—"
        html += f"""
<details{' open' if i == 0 else ''}>
  <summary>📄 <strong>{esc(fname)}</strong> · {total_ms:.0f} ms · {esc(started[:19])}</summary>
  <div class="inner">
    <p><strong>Source:</strong> <code>{esc(sp)}</code></p>
    <p><strong>Collection:</strong> <span class="badge">{esc(meta.get('collection',''))}</span></p>
    <p><strong>Trace ID:</strong> <code>{esc(tid)}</code></p>
"""

        # Stage timings table
        stages = trace.get("stages", [])
        if stages:
            html += """
    <h3>⏱️ Stage Timings</h3>
    <div class="bar-chart">
"""
            max_ms = max((s.get("elapsed_ms", 0) for s in stages), default=1)
            for s in stages:
                ms = s.get("elapsed_ms", 0)
                pct = max(1, int(ms / max_ms * 100))
                html += f"""
      <div class="bar-row">
        <div class="bar-label">{esc(s.get('stage_name','?'))}</div>
        <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
        <div class="bar-val">{ms:.1f} ms</div>
      </div>
"""
            html += "    </div>\n"

            html += """
    <table class="tbl">
      <thead><tr><th>Stage</th><th>Elapsed (ms)</th></tr></thead><tbody>
"""
            for s in stages:
                html += f"<tr><td>{esc(s.get('stage_name','?'))}</td><td>{s.get('elapsed_ms',0):.2f}</td></tr>\n"
            html += "</tbody></table>\n"

        html += "  </div>\n</details>\n"

html += """
</section>
"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 5: Query Traces
# ═══════════════════════════════════════════════════════════════════
html += """
<section id="query-traces">
  <h1>🔎 Query Traces</h1>
  <p class="subtitle">Browse query trace history with stage waterfall and Ragas evaluation</p>
"""

if not query_traces:
    html += '<div class="info-box info">No query traces recorded yet. Run a query first!</div>\n'
else:
    html += f'<p style="color:var(--muted);margin-bottom:1rem">{len(query_traces)} trace(s)</p>\n'
    for i, trace in enumerate(query_traces[:10]):
        tid = trace.get("trace_id", "unknown")
        started = trace.get("started_at", "—")
        total_ms = trace.get("elapsed_ms", 0)
        meta = trace.get("metadata", {})
        query = meta.get("query", "")
        source = meta.get("source", "unknown")
        top_k = meta.get("top_k", "—")
        collection = meta.get("collection", "—")

        q_preview = query[:60] + "…" if len(query) > 60 else query

        html += f"""
<details{' open' if i == 0 else ''}>
  <summary>🔍 <strong>"{esc(q_preview)}"</strong> · {total_ms:.0f} ms · {esc(started[:19])}</summary>
  <div class="inner">
    <h3>💬 Query</h3>
    <div class="text-block" style="margin-bottom:1rem">{esc(query)}</div>
    <p>Source: <span class="badge">{esc(source)}</span> · Top-K: <code>{esc(str(top_k))}</code> · Collection: <span class="badge">{esc(collection)}</span></p>
"""

        # Stage timings
        stages = trace.get("stages", [])
        if stages:
            html += """
    <h3>⏱️ Stage Timings</h3>
    <div class="bar-chart">
"""
            max_ms = max((s.get("elapsed_ms", 0) for s in stages), default=1)
            for s in stages:
                ms = s.get("elapsed_ms", 0)
                pct = max(1, int(ms / max_ms * 100))
                html += f"""
      <div class="bar-row">
        <div class="bar-label">{esc(s.get('stage_name','?'))}</div>
        <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
        <div class="bar-val">{ms:.1f} ms</div>
      </div>
"""
            html += "    </div>\n"

            html += """
    <table class="tbl">
      <thead><tr><th>Stage</th><th>Elapsed (ms)</th></tr></thead><tbody>
"""
            for s in stages:
                html += f"<tr><td>{esc(s.get('stage_name','?'))}</td><td>{s.get('elapsed_ms',0):.2f}</td></tr>\n"
            html += "</tbody></table>\n"

        html += "  </div>\n</details>\n"

html += """
</section>
"""

# ═══════════════════════════════════════════════════════════════════
# PAGE 6: Evaluation Panel
# ═══════════════════════════════════════════════════════════════════
golden_path = BASE.parent / "tests" / "fixtures" / "golden_test_set.json"
golden_exists = golden_path.exists()

html += """
<section id="evaluation-panel">
  <h1>📏 Evaluation Panel</h1>
  <p class="subtitle">Run RAG evaluation against a golden test set</p>

  <h2>⚙️ Configuration</h2>
  <div class="card-grid">
    <div class="card">
      <h4>Evaluator Backend</h4>
      <p><span class="badge">custom</span> <span class="badge">ragas</span> <span class="badge">composite</span></p>
      <p style="margin-top:0.5rem">Select which evaluator backend to use</p>
    </div>
    <div class="card">
      <h4>Top-K</h4>
      <div class="val" style="font-size:1.5rem">10</div>
      <p>Chunks to retrieve per query</p>
    </div>
    <div class="card">
      <h4>Golden Test Set</h4>
"""
if golden_exists:
    html += '<div class="info-box success">✅ Found: tests/fixtures/golden_test_set.json</div>\n'
else:
    html += '<div class="info-box warn">⚠️ Not found</div>\n'
html += """    </div>
  </div>

  <h2>▶️ Run Evaluation</h2>
  <div class="info-box info">
    Select evaluator backend, configure Top-K, provide answers for RAGAS, then click <strong>Run Evaluation</strong>.
    Results include per-query metrics (hit_rate, MRR, faithfulness, answer_relevancy) and aggregate scores.
  </div>

  <h2>📈 Evaluation History</h2>
  <div class="info-box info">No evaluation history yet. Run an evaluation to see results here.</div>
</section>

"""

# ── Footer ──
html += f"""
</main>
<footer>
  Modular RAG MCP Server · Dashboard Report · Generated from live data<br>
  Collections: {len(collections)} · Documents: {len(docs)} · Total Chunks: {sum(d.get('chunk_count',0) for d in docs):,}
</footer>
</body>
</html>
"""

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(html)

print(f"[OK] Report written to {OUT_FILE}")
print(f"      Size: {os.path.getsize(OUT_FILE):,} bytes")
