# wiki-rag

Two-phase pipeline for building a RAG knowledge base from ArXiv papers.

**Phase 1 (Collect):** Download TeX/PDF from ArXiv, extract structure → markdown + JSON  
**Phase 2 (Ingest):** LLM synthesizes polished wiki page from raw files

Harness-agnostic: works with any LLM API (OpenAI, Anthropic, Ollama, etc.) or any agent framework.

## Installation

```bash
pip install wiki-rag
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

## Pipeline

```
ArXiv ID → TeX/PDF Download → Structure Extraction → Markdown + JSON → Wiki Page
```

## License

MIT
