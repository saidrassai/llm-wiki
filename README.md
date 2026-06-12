# wiki-rag

Two-phase pipeline for building a RAG knowledge base from ArXiv papers.

**Phase 1 (Collect):** Download TeX/PDF from ArXiv, extract structure → markdown + JSON  
**Phase 2 (Ingest):** LLM synthesizes polished wiki page from raw files

Harness-agnostic: works with any LLM API (OpenAI, Anthropic, Ollama, etc.) or any agent framework.

## Installation

```bash
pip install wiki-rag
```

### Optional Dependencies

```bash
# Primary PDF extractor (fast, lightweight, no torch)
pip install pymupdf4llm

# Fallback for complex tables/cross-page/scanned PDFs (heavy)
pip install docling
```

## Quick Start

```bash
# Configure
export LLM_API_KEY="your-key"
export LLM_MODEL="gpt-4o"

# Collect a paper
python -c "
from wiki_rag import Collector
c = Collector('~/wiki-rag')
c.collect('2604.26176', title='CacheRAG', authors='Yushi Sun, Lei Chen')
"

# Ingest (create wiki page)
python -c "
from wiki_rag import Ingester
i = Ingester('~/wiki-rag')
result = i.ingest_next()
print(result['wiki_page'])
"
```

## Pipeline Architecture

```
ArXiv ID
    │
    ├─► TeX available? ──YES──► strip_latex() → Done (Best structure)
    │
    └─► NO ──► Download PDF
                    │
                    ├─► is_digital_pdf()? ──YES──► pymupdf4llm (Primary)
                    │                           │
                    │                           ├─► Cross-page tables? ──YES──► Docling fallback
                    │                           │
                    │                           ├─► Complex headers? ──YES──► Docling fallback
                    │                           │
                    │                           └─► NO ──► Done (Fast, markdown with tables/eqs)
                    │
                    └─► NO (scanned) ──► Skip / Docling OCR
```

### Three-Tier Extraction

| Tier | Source | Method | Speed | Output |
|------|--------|--------|-------|--------|
| 1 | TeX source | `strip_latex()` | ~0.05s | Perfect structure, tables, equations |
| 2 | Digital PDF | `pymupdf4llm.to_markdown()` | **~0.1s** | Markdown + tables + equations |
| 3 | Complex/scanned | `docling` CLI | ~45s | Rich markdown + base64 images |

### Automatic Fallback Logic

The pipeline automatically detects when pymupdf4llm may miss content:

| Trigger | Detection | Fallback |
|---------|-----------|----------|
| **Cross-page tables** | Single row, >15 columns spanning page break | Docling |
| **Complex headers** | `header.external=True` (merged multi-row headers) | Docling |

## Configuration

### Environment Variables

```bash
export LLM_API_KEY="your-api-key"      # Required for ingest
export LLM_API_BASE="https://api.openai.com/v1"  # Optional
export LLM_MODEL="gpt-4o"              # Optional, default: gpt-4o
```

### Collector Options

```python
from wiki_rag import Collector

c = Collector('~/wiki-rag')

# Single paper
c.collect('2604.26176', title='CacheRAG', authors='Yushi Sun, Lei Chen', category='rag')

# Batch from file
c.collect_from_file('papers.json', max_papers=10)

# Retry skipped
c.retry_skipped(max_papers=5)
```

## CLI Usage

```bash
# Collect up to N papers
python -m wiki_rag.collect --max 10 --source papers.json

# Retry previously skipped papers
python -m wiki_rag.collect --retry-skipped --max 5
```

## Ingest Options

```python
from wiki_rag import ingest_paper, Ingester

# Single paper
result = ingest_paper(
    'raw/papers/2026-06-12-2604.26176.md',
    llm_client=my_llm_function,
    domain='rag'
)

# Auto-ingest next pending
i = Ingester('~/wiki-rag')
result = i.ingest_next()
```

## Output Structure

### Raw Files (`~/wiki-rag/raw/papers/`)
```
{date}-{arxiv_id}.md       # Extracted markdown
{date}-{arxiv_id}.json    # Metadata + structure
```

### Manifest (`~/wiki-rag/manifest.json`)
```json
{
  "arxiv_id": "2604.26176",
  "source_type": "tex | pdf-pymupdf4llm | pdf-docling-fallback",
  "collected_at": "2026-06-12",
  "ingested": false,
  "skipped": false
}
```

### Wiki Pages (`~/wiki-rag/wiki/`)
```
{title}.md    # Polished wiki page with YAML frontmatter
```

## Design Decisions

### Why pymupdf4llm over Docling?

| Factor | pymupdf4llm | Docling |
|--------|-------------|---------|
| Speed (CPU) | **0.1s** | 45s |
| Dependencies | Light (16MB) | Heavy (torch, transformers) |
| RAM | ~50MB | 3-4 GB |
| Tables | 41 lines | 38 lines |
| Equations | 3 display + 1 inline | 1 display |

**Decision**: pymupdf4llm is 450× faster, 60× less RAM, zero heavy deps. Docling reserved for fallback only.

### Why Keep Docling?

- Cross-page table continuation (pymupdf4llm splits at page boundaries)
- Complex merged headers (multi-row, colspan)
- Scanned PDF OCR
- High-res figure extraction

## License

MIT