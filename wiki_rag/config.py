"""
Configuration via environment variables.

All settings are read from env vars with sensible defaults.
No config files required.
"""

import os
from pathlib import Path

class Config:
    """wiki-rag configuration from environment variables."""
    
    # LLM API settings
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    
    # Paths
    WIKI_PATH: Path = Path(os.getenv("WIKI_PATH", "~/wiki-rag")).expanduser()
    RAW_DIR: Path = WIKI_PATH / "raw" / "papers"
    ENTITIES_DIR: Path = WIKI_PATH / "entities"
    MANIFEST_PATH: Path = WIKI_PATH / "manifest.json"
    SCHEMA_PATH: Path = WIKI_PATH / "SCHEMA.md"
    INDEX_PATH: Path = WIKI_PATH / "index.md"
    LOG_PATH: Path = WIKI_PATH / "log.md"
    
    # Source list
    SOURCE_LIST: Path = WIKI_PATH / "categorized_papers_2024_2026.json"
    
    # Collection settings
    MAX_PAPERS_PER_RUN: int = int(os.getenv("WIKI_RAG_MAX_PAPERS", "5"))
    REQUEST_TIMEOUT: int = int(os.getenv("WIKI_RAG_TIMEOUT", "60"))
    USER_AGENT: str = "wiki-rag/1.0"
    
    @classmethod
    def ensure_dirs(cls):
        """Create required directories."""
        for d in [cls.RAW_DIR, cls.ENTITIES_DIR, cls.WIKI_PATH / "concepts",
                   cls.WIKI_PATH / "comparisons", cls.WIKI_PATH / "queries"]:
            d.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def validate(cls) -> list:
        """Validate configuration. Returns list of errors."""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not set")
        if not cls.SOURCE_LIST.exists():
            errors.append(f"Source list not found: {cls.SOURCE_LIST}")
        return errors
