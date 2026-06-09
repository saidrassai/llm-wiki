# wiki-rag: Two-phase ArXiv → RAG knowledge base

"""
wiki-rag: Harvest ArXiv papers into a structured RAG knowledge base.

Two-phase pipeline:
  Phase 1 (collect): Download TeX/PDF, extract structure → markdown + JSON
  Phase 2 (ingest):  LLM synthesizes wiki page from raw files

Harness-agnostic: works with any LLM API or agent framework.
"""

__version__ = "1.0.0"

from .collect import collect_paper, collect_batch
from .ingest import ingest_paper, build_ingest_prompt
from .config import Config
