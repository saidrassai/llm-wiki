#!/usr/bin/env python3
"""
Example: Standalone usage (no agent framework).

Requires:
    pip install wiki-rag
    export LLM_API_KEY="your-key"
"""

import os
from wiki_rag import Collector, Ingester

# Configuration via environment
# LLM_API_KEY, LLM_API_BASE, LLM_MODEL, WIKI_PATH

WIKI_PATH = os.path.expanduser("~/wiki-rag")

# Phase 1: Collect papers
print("=== Phase 1: Collect ===")
collector = Collector(WIKI_PATH)

papers = [
    {"id": "2604.26176", "title": "CacheRAG", "authors": "Yushi Sun, Lei Chen"},
    {"id": "2605.19735", "title": "ContextRAG", "authors": "Roman Prosvirnin"},
    {"id": "2606.06044", "title": "IA-RAG", "authors": "Xiaoman Wang"},
]

for p in papers:
    result = collector.collect(p["id"], title=p["title"], authors=p["authors"])
    status = "✓" if result["success"] else "✗"
    print(f"  {status} {p['id']}: {result.get('source_type', 'failed')}")

# Phase 2: Ingest papers
print("\n=== Phase 2: Ingest ===")
ingester = Ingester(WIKI_PATH)

pending = ingester.get_pending()
print(f"Pending: {len(pending)}")

for _ in range(min(3, len(pending))):
    result = ingester.ingest_next()
    if result["success"]:
        fm = result.get("frontmatter", {})
        print(f"  ✓ {fm.get('title', 'unknown')}")
    else:
        print(f"  ✗ {result.get('error', 'unknown error')}")
