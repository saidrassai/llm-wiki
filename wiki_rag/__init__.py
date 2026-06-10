# wiki-rag: Two-phase ArXiv → RAG knowledge base

__version__ = "1.0.0"

from .collect import process_paper, Collector, main as collect_main
from .ingest import ingest_paper, build_ingest_prompt, Ingester
from .repos import enrich_paper_with_repos, get_hf_paper_metadata, get_github_stars
from .config import Config
