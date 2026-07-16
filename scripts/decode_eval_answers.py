#!/usr/bin/env python
"""Decode LLM answers — use a tolerant parser since JSON has unescaped newlines."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPORT_PATH = Path("logs/eval_report_2026-07-16.json")


def main():
    raw = REPORT_PATH.read_bytes().decode("utf-8", errors="replace")

    # Locate aggregate metrics (always clean JSON at top)
    agg_match = re.search(r'"aggregate_metrics":\s*(\{[^}]+\})', raw)
    if agg_match:
        agg = json.loads(agg_match.group(1))
        print("Aggregate metrics:", agg)

    total_match = re.search(r'"query_count":\s*(\d+)', raw)
    if total_match:
        print(f"Total queries: {total_match.group(1)}")

    print("\n" + "=" * 70)
    print("DECODED LLM ANSWERS (each query's generated_answer, first 200 chars)")
    print("=" * 70)

    # Find each query block: { "query": "...", "retrieved_chunk_ids": [...], ...
    # Then "generated_answer": "<text...>",
    # Use regex to find "query": "..." followed by "generated_answer": "..."
    # Since generated_answer can span newlines, we use lazy match with character class

    # Strategy: find each "query": "..." entry, then capture up to "metrics":
    # We'll use a different approach: find every "generated_answer": "..." pair
    # with a regex that handles escaped and unescaped chars.

    pattern = re.compile(
        r'"query":\s*"([^"]+)"\s*,'
        r'.*?'
        r'"generated_answer":\s*"((?:[^"\\]|\\.)*(?:"|(?=\s*,\s*"metrics")))',
        re.DOTALL,
    )

    matches = list(pattern.finditer(raw))
    print(f"Found {len(matches)} answers\n")

    # Write to UTF-8 file to avoid GBK console issues
    out = []
    for i, m in enumerate(matches, 1):
        query = m.group(1)
        answer = m.group(2)
        answer = answer.encode("utf-8", errors="replace").decode("unicode_escape", errors="replace")
        clean = " ".join(answer.split())

        out.append(f"\n[{i}] Query: {query}")
        out.append(f"    Answer snippet (first 250 chars):")
        out.append(f"    >>> {clean[:250]}{'...' if len(clean) > 250 else ''}")
        out.append(f"    Full answer length: {len(answer)} chars")
        out.append("-" * 70)

    output_text = "\n".join(out)
    Path("logs/decoded_answers.txt").write_text(output_text, encoding="utf-8")
    print(f"Wrote {len(out)} lines to logs/decoded_answers.txt")



if __name__ == "__main__":
    main()
