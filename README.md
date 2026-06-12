# llm-wiki

Domain-agnostic LLM knowledge base builder. Three-layer separation: **private wikis** (your data) → **open-source engine** (this package) → **machine config** (Hermes/env).

**Phase 1 (Collect):** Download TeX/PDF/HTML from ArXiv, extract structure → markdown + JSON  
**Phase 2 (Ingest):** LLM synthesizes polished wiki page from raw files

Harness-agnostic: works with any LLM API (OpenAI, Anthropic, Ollama, etc.) or any agent framework.

## Installation

```bash
# From GitHub (recommended)
pip install git+https://github.com/saidrassai/llm-wiki.git --break-system-packages

# Or local editable
pip install -e /path/to/llm-wiki --break-system-packages
```

### Optional Dependencies

```bash
# Primary PDF extractor (fast, lightweight, no torch)
pip install pymupdf4llm

# Fallback for complex tables/cross-page/scanned PDFs (heavy)
pip install docling

# GitHub enrichment (optional)
export GITHUB_TOKEN="your-token"
```

## Quick Start

```bash
# 1. Configure (once)
export LLM_API_KEY="your-key"
export LLM_MODEL="gpt-4o"
# Optional: export LLM_API_BASE="https://api.openai.com/v1"

# 2. Initialize a new wiki
export LLM_WIKI_WIKI_PATH=~/wikis/rag
llm-wiki init --profile rag

# 3. Collect papers
llm-wiki collect --source arxiv --max 10

# 4. Ingest (create wiki pages)
llm-wiki ingest --max 5

# 5. Enrich with GitHub repos
llm-wiki enrich --all

# 6. Check status
llm-wiki status
```

### Python API

```python
from llm_wiki import Collector, WikiConfig

# Configure wiki
config = WikiConfig(wiki_path="~/wikis/finance")
collector = Collector(config)

# Collect single paper
collector.collect("2404.14618", title="Hybrid LLM", authors="Ding et al.", category="rag")

# Batch collect
collector.collect_from_file("papers.json", max_papers=10)
```

## True Hybrid Extraction Pipeline

```
ArXiv ID
    │
    ├─► download_tex() ──► analyze_tex()
    │
    ├─► download_pdf() ──► analyze_pdf() 
    │
    └─► download_html() ──► analyze_html()
             │
             ▼
    decide_strategy() ───► 7 Strategies
    │
    ├─ tex_only                    # TeX handles everything
    ├─ tex+pymupdf4llm      ◄── HYBRID: TeX text + PDF tables
    ├─ tex+pymupdf4llm+docling     # Hybrid + Docling fallback
    ├─ pymupdf4llm                 # PDF-only fast
    ├─ docling                     # PDF-only complex
    ├─ html                        # ArXiv HTML fallback
    └─ basic                       # PyMuPDF text
             │
             ▼
    merge_structure_with_tables()
             │
             ▼
    build_hybrid_markdown()
```

### Strategy Selection Logic

| Strategy | When Used | Description |
|----------|-----------|-------------|
| `tex_only` | TeX available, simple/no tables | TeX for everything (structure + tables) |
| `tex+pymupdf4llm` | TeX + PDF, tables detected | **TRUE HYBRID**: TeX text/equations/citations + pymupdf4llm tables |
| `tex+pymupdf4llm+docling` | Cross-page tables in PDF | Hybrid + Docling for complex tables |
| `pymupdf4llm` | No TeX, digital PDF with tables | Fast PDF extraction |
| `docling` | Cross-page tables, no TeX | Heavy but accurate |
| `html` | No TeX/PDF, HTML available | ArXiv HTML semantic parsing |
| `basic` | Fallback only | PyMuPDF text extraction |

## Architecture

```
llm_wiki/
├── collectors/           # Phase 1: ArXiv, GitHub, HuggingFace
│   ├── arxiv.py
│   ├── github.py
│   ├── huggingface.py
│   └── __init__.py       # CollectorProtocol
├── enrichment/           # Entity extraction, taxonomy, embeddings (future)
├── storage/              # Manifest, EntityStore, IndexManager
├── plugins/              # Plugin registry
├── detect.py             # Content analysis & strategy decision
├── tables.py             # Table extraction specialists
├── structure.py          # Structure extraction (no tables)
├── merge.py              # Hybrid merger (TeX placeholders + PDF tables)
├── collect.py            # Orchestrator
├── ingest.py             # Phase 2: LLM synthesis
├── core.py               # WikiConfig, WikiPaths (env-driven)
├── cli.py                # Commands: init, collect, ingest, enrich, status, schema
└── templates/            # Wiki templates
```

### Three-Layer Separation

| Layer | What | Where | Git |
|-------|------|-------|-----|
| **Private Wikis** | Your knowledge bases (RAG, SFT, finance, etc.) | `~/wikis/rag/`, `~/wikis/finance/` | Private repo only |
| **Open-Source Engine** | Python package: collectors, enrichers, storage, CLI | `pip install llm-wiki` | GitHub: `saidrassai/llm-wiki` |
| **Machine Config** | Per-machine: env vars, cron jobs, skill symlinks | `~/.llm-wiki/` or `~/.hermes/` | Never shared |

### Your Private Wikis

```
~/wikis/
├── rag/                    # Wiki 1
│   ├── manifest.json
│   ├── entities/
│   ├── raw/papers/
│   └── SCHEMA.md
├── finance/                # Wiki 2
└── sft-rl/                 # Wiki 3
```

Each wiki is **just data** — no code. The engine (`llm-wiki`) is the product.

## Pipeline Architecture

### Phase 1: Collect (Deterministic, Zero LLM Tokens)

```python
from llm_wiki import Collector, WikiConfig

config = WikiConfig(wiki_path="~/wikis/rag")
collector = Collector(config)

# Single paper
result = collector.collect("2404.14618", title="Hybrid LLM", authors="Ding et al.", category="rag")

# Batch from file
collector.collect_from_file("categorized_papers_2024_2026.json", max_papers=10)

# Retry skipped papers
collector.retry_skipped(max_papers=5)
```

**Extraction Flow (per paper):**

1. **Download** TeX / PDF / HTML from ArXiv
2. **Analyze** each source → `ContentProfile` (tables, equations, figures, complexity)
3. **Decide** strategy via `decide_strategy()`
4. **Extract**:
   - TeX → `extract_structure_from_tex()` (sections, equations, citations, figures) + `extract_tables_from_tex()` (placeholder tracking)
   - PDF → `extract_tables_from_pymupdf4llm()` (tables with captions) / `extract_tables_from_docling()` (fallback)
   - HTML → `extract_structure_from_html()` + `extract_tables_from_html()`
5. **Merge** → `merge_structure_with_tables()` matches TeX placeholders to PDF tables via caption proximity
6. **Build** → `build_hybrid_markdown()` outputs final markdown with YAML frontmatter
7. **Save** → Raw files + manifest update

### Phase 2: Ingest (LLM Synthesis)

```python
from llm_wiki import Ingester, WikiConfig

config = WikiConfig(wiki_path="~/wikis/rag")
ingester = Ingester(config, llm_client=my_llm_function)

# Ingest next pending
result = ingester.ingest_next()

# Or batch
ingester.ingest_batch(max_papers=5)
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `llm-wiki init --profile <name>` | Initialize new wiki with profile |
| `llm-wiki collect --source <src> --max <n>` | Collect papers (arxiv, pdf, html) |
| `llm-wiki ingest --max <n>` | Ingest collected papers into wiki |
| `llm-wiki enrich --all` | Enrich entities with GitHub/HF metadata |
| `llm-wiki status` | Show wiki status (pending, ingested, skipped) |
| `llm-wiki schema` | Validate/show SCHEMA.md taxonomy |

## Configuration

### Environment Variables

```bash
export LLM_API_KEY="your-api-key"           # Required for ingest
export LLM_API_BASE="https://api.openai.com/v1"  # Optional custom endpoint
export LLM_MODEL="gpt-4o"                   # Optional, default: gpt-4o
export LLM_WIKI_WIKI_PATH="~/wikis/rag"     # Wiki path (or --wiki-path)
export GITHUB_TOKEN="your-token"            # Optional: GitHub API for enrichment
```

### Collector Profiles

```python
from llm_wiki.collectors import ArxivCollector, GitHubCollector, HuggingFaceCollector

# Use specific collector
arxiv = ArxivCollector()
github = GitHubCollector(token="your-token")

# Plugin custom collector
from llm_wiki.plugins import CollectorProtocol
class MyCollector(CollectorProtocol):
    def collect(self, arxiv_id: str) -> dict: ...
```

## Output Structure

### Raw Files (`~/wikis/rag/raw/papers/`)
```
{date}-{arxiv_id}.md       # Extracted markdown (hybrid or single-source)
{date}-{arxiv_id}.json    # Metadata + structure (tables, equations, sections)
```

### Manifest (`~/wikis/rag/manifest.json`)
```json
{
  "arxiv_id": "2404.14618",
  "title": "Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing",
  "source_type": "tex+pymupdf4llm",
  "collected_at": "2026-06-12",
  "ingested": false,
  "skipped": false,
  "tables_count": 5,
  "strategy": "tex+pymupdf4llm"
}
```

### Wiki Pages (`~/wikis/rag/entities/`)
```
{slug}.md    # Polished wiki page with YAML frontmatter, [[wikilinks]], tags
```

## Key Design Decisions

### Why pymupdf4llm over Docling?

| Factor | pymupdf4llm | Docling |
|--------|-------------|---------|
| Speed (CPU) | **0.1s** | 45s |
| Dependencies | Light (16MB pymupdf_layout) | Heavy (torch, transformers) |
| RAM | ~50MB | 3-4 GB |
| Tables | 41 lines | 38 lines |
| Equations | 3 display + 1 inline | 1 display |

**Decision**: pymupdf4llm is 450× faster, 60× less RAM, zero heavy deps. Docling reserved for fallback only.

### Why Keep Docling?

- Cross-page table continuation (pymupdf4llm splits at page boundaries)
- Complex merged headers (multi-row, colspan)
- Scanned PDF OCR
- High-res figure extraction

### True Hybrid Rationale

pymupdf4llm excels at table extraction but loses semantic structure (citations, equation numbering, cross-refs). TeX preserves perfect semantic structure but table regex is brittle. **Hybrid uses each for its strength:**

- **TeX**: Sections, equations, citations, cross-refs, figure captions → `extract_structure_from_tex()`
- **pymupdf4llm**: Clean markdown tables with captions → `extract_tables_from_pymupdf4llm()`
- **Merge**: Caption/label proximity matching → `merge_structure_with_tables()`

## Cron Jobs (Hermes)

```yaml
# ~/.hermes/cron/llm-wiki-ingest-rag.yaml
- name: llm-wiki-ingest-rag
  schedule: "*/30 * * * *"
  prompt: "llm-wiki ingest --max 1"
  workdir: "/home/ubuntu/wikis/rag"
  skills: ["research:llm-wiki"]
  model: "gpt-4o"

# ~/.hermes/cron/llm-wiki-enrich-rag.yaml
- name: llm-wiki-enrich-rag
  schedule: "0 3 * * *"
  prompt: "llm-wiki enrich --all"
  workdir: "/home/ubuntu/wikis/rag"
  skills: ["research:llm-wiki"]
```

## License

MIT