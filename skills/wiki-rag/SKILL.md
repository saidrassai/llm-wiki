---
name: wiki-rag
description: Two-phase pipeline for building a RAG knowledge base from ArXiv papers. Phase 1 collects papers via Python script. Phase 2 uses LLM to synthesize wiki pages. Harness-agnostic.
---

# wiki-rag Skill

## Overview

Two-phase pipeline for building a structured RAG knowledge base from ArXiv papers.

**Phase 1 (Collect):** Download TeX/PDF from ArXiv, extract structure → markdown + JSON
**Phase 2 (Ingest):** LLM synthesizes polished wiki page from raw files

## Quick Start

### 1. Install

```bash
pip install wiki-rag
```

### 2. Configure

```bash
export LLM_API_KEY="your-key"
export LLM_API_BASE="https://api.openai.com/v1"  # or any OpenAI-compatible API
export LLM_MODEL="gpt-4o"
export WIKI_PATH="~/wiki-rag"
```

### 3. Collect Papers

```bash
# From command line
wiki-rag-collect --arxiv-id 2604.26176

# Or Python
from wiki_rag import Collector
c = Collector("~/wiki-rag")
c.collect("2604.26176", title="CacheRAG", authors="Yushi Sun, Lei Chen")
```

### 4. Ingest (Create Wiki Pages)

```bash
# Single paper
wiki-rag-ingest --raw-path ~/wiki-rag/raw/papers/2026-06-09-2604.26176.md

# Batch (all pending)
wiki-rag-ingest --all
```

### 5. Set Up Cron (Automated)

See `cron/` directory for framework-specific cron definitions.

## Pipeline Details

### Phase 1: Collect

**Input:** ArXiv ID
**Output:** Raw markdown + JSON in `raw/papers/`

Three-tier source detection:
1. **TeX source** (best) — Downloads `.tar.gz`, extracts `.tex`, converts to markdown
2. **Digital PDF** (fast) — PyMuPDF in-memory text extraction
3. **Scanned PDF** (skip) — Rare for ArXiv, would need OCR

**Key functions:**
- `collect_paper(arxiv_id)` — Single paper
- `Collector(wiki_path).collect(arxiv_id)` — Stateful with manifest

### Phase 2: Ingest

**Input:** Raw markdown file from Phase 1
**Output:** Polished wiki page in `entities/`

Uses LLM to synthesize:
- YAML frontmatter (title, tags, confidence)
- Overview paragraph
- Key contributions (3-5 bullets)
- Architecture/method summary
- Related work
- Results with specific metrics
- Wikilinks to related concepts

**Key functions:**
- `ingest_paper(raw_path)` — Single paper
- `Ingester(wiki_path).ingest_next()` — Next pending paper
- `Ingester(wiki_path).ingest_all()` — All pending papers

## File Structure

```
~/wiki-rag/
├── SCHEMA.md              # Tag taxonomy
├── index.md               # Wiki page catalog
├── log.md                 # Action log
├── manifest.json          # Collection/ingest tracking
├── raw/papers/            # Phase 1 output
│   ├── YYYY-MM-DD-{id}.md
│   └── YYYY-MM-DD-{id}.json
├── entities/              # Phase 2 output (wiki pages)
├── concepts/
├── comparisons/
└── queries/
```

## Configuration

All via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | (required) | API key |
| `LLM_API_BASE` | OpenAI | API base URL |
| `LLM_MODEL` | gpt-4o | Model name |
| `WIKI_PATH` | ~/wiki-rag | Wiki directory |

## Supported LLM Providers

Any OpenAI-compatible API:
- OpenAI (default)
- Anthropic (via proxy)
- Ollama (local)
- vLLM (local)
- Any custom endpoint

## Examples

### Standalone (No Agent)

```python
from wiki_rag import Collector, Ingester

# Phase 1: Collect
c = Collector("~/wiki-rag")
c.collect("2604.26176", title="CacheRAG", authors="Yushi Sun")

# Phase 2: Ingest
i = Ingester("~/wiki-rag")
result = i.ingest_next()
print(result["wiki_page"])
```

### With Custom LLM Client

```python
from wiki_rag import ingest_paper

def my_llm(prompt):
    # Your custom LLM call
    return llm.complete(prompt)

result = ingest_paper("raw/papers/2026-06-09-2604.26176.md", llm_client=my_llm)
```

### With Hermes Agent

See `cron/hermes.md` for Hermes-specific cron setup.

## References

- `references/technical-reference.md` — Implementation details
- `references/pipeline-architecture.md` — Architecture diagrams
