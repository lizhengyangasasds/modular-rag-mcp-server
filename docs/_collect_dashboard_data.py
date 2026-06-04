import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))

from src.observability.dashboard.services.data_service import DataService
from src.core.settings import load_settings, resolve_path

ds = DataService()
collections = ds.list_collections()
docs = ds.list_documents()

report = {
    "collections": collections,
    "documents": docs,
    "collection_stats": {},
    "document_details": []
}

# Collection stats
for col in collections:
    try:
        stats = ds.get_collection_stats(col)
        report["collection_stats"][col] = stats
    except Exception as e:
        report["collection_stats"][col] = {"error": str(e)}

# Document details
for doc in docs:
    detail = ds.get_document_detail(doc['source_hash'])
    chunks = ds.get_chunks(doc['source_hash'])
    images = ds.get_images(doc['source_hash'])
    report["document_details"].append({
        "detail": detail,
        "chunks": chunks,
        "images": images
    })

# Traces
from src.observability.dashboard.services.trace_service import TraceService
ts = TraceService()
ingestion_traces = ts.list_traces(trace_type="ingestion")
query_traces = ts.list_traces(trace_type="query")
report["ingestion_traces"] = ingestion_traces
report["query_traces"] = query_traces

# Config
from src.observability.dashboard.services.config_service import ConfigService
cs = ConfigService()
cards = cs.get_component_cards()
report["component_cards"] = [{"name": c.name, "provider": c.provider, "model": c.model, "extra": c.extra} for c in cards]

output_path = os.path.join(os.path.dirname(__file__), "dashboard_data.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"Written to {output_path}")
