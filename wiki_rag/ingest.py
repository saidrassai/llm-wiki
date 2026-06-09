"""
Phase 2: LLM-powered wiki page synthesis.

Takes raw markdown + JSON from Phase 1 and produces a polished wiki page.
Works with any LLM API — OpenAI, Anthropic, Ollama, or custom.
"""

import json
import re
from pathlib import Path
from .config import Config

__all__ = ["ingest_paper", "build_ingest_prompt", "Ingester"]


DEFAULT_SYSTEM_PROMPT = """You are a research assistant that creates wiki pages from academic papers.
Your task is to read raw paper content and produce a structured wiki page in markdown format.

The wiki page should have:
1. YAML frontmatter with: title, created, updated, type, tags, sources, confidence
2. A concise Overview paragraph (2-3 sentences)
3. Key Contributions (3-5 bullet points)
4. Architecture/Method summary
5. Related Work (1 paragraph)
6. Results/Findings with specific metrics
7. See Also section with [[wikilinks]] to related concepts

Keep the total body under 500 words. Be specific and technical."""


def build_ingest_prompt(raw_markdown: str, schema_tags: list = None, existing_pages: list = None) -> str:
    """
    Build the prompt for LLM ingestion.
    
    Args:
        raw_markdown: The raw paper content from Phase 1
        schema_tags: List of valid tags from SCHEMA.md
        existing_pages: List of existing wiki page titles for wikilink suggestions
    
    Returns:
        Complete prompt string for the LLM
    """
    tags_hint = ""
    if schema_tags:
        tags_hint = f"\n\nValid tags (use 3-5): {', '.join(schema_tags[:30])}"
    
    wikilinks_hint = ""
    if existing_pages:
        wikilinks_hint = f"\n\nExisting wiki pages for [[wikilinks]]: {', '.join(existing_pages[:20])}"
    
    return f"""Create a wiki page from this paper content.

RAW PAPER CONTENT:
---
{raw_markdown[:8000]}
---
{tags_hint}{wikilinks_hint}

OUTPUT FORMAT:
---
title: "Paper Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity
tags: [tag1, tag2, tag3]
sources: [raw/path/to/file.md]
confidence: high | medium | low
---

## Overview
[2-3 sentence summary of the paper's core contribution]

## Key Contributions
- [Specific contribution 1]
- [Specific contribution 2]
- [Specific contribution 3]

## Architecture / Method
[1 paragraph describing the approach]

## Related Work
[1 paragraph positioning against prior work]

## Results / Findings
[Key metrics and findings]

## See Also
- [[Related Concept 1]]
- [[Related Concept 2]]
"""


def call_llm_api(prompt: str, system_prompt: str = None, config: Config = None) -> str:
    """
    Call LLM API. Supports OpenAI, Anthropic, Ollama, or any OpenAI-compatible API.
    
    Environment variables:
        LLM_API_KEY: API key
        LLM_API_BASE: API base URL (default: https://api.openai.com/v1)
        LLM_MODEL: Model name (default: gpt-4o)
    
    Returns:
        LLM response text
    """
    if config is None:
        config = Config()
    
    system = system_prompt or DEFAULT_SYSTEM_PROMPT
    
    # Try OpenAI-compatible API
    try:
        import openai
        client = openai.OpenAI(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_API_BASE if config.LLM_API_BASE != "https://api.openai.com/v1" else None
        )
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        return response.choices[0].message.content
    except ImportError:
        pass
    
    # Try raw HTTP
    import urllib.request
    payload = json.dumps({
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2000,
        "temperature": 0.3
    }).encode()
    
    req = urllib.request.Request(
        f"{config.LLM_API_BASE}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.LLM_API_KEY}",
            "Content-Type": "application/json"
        }
    )
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    
    return data["choices"][0]["message"]["content"]


def parse_llm_output(output: str) -> dict:
    """Parse LLM output into structured wiki page."""
    result = {"frontmatter": {}, "body": "", "full": output}
    
    # Extract YAML frontmatter
    fm_match = re.search(r'^---\s*\n(.*?)\n---', output, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        for line in fm_text.split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val.startswith('[') and val.endswith(']'):
                    val = [v.strip() for v in val[1:-1].split(',')]
                result["frontmatter"][key] = val
    
    # Extract body (after frontmatter)
    body_start = output.find('\n---\n', output.find('---'))
    if body_start > 0:
        result["body"] = output[body_start + 4:].strip()
    
    return result


def ingest_paper(raw_path: str, llm_client: callable = None, config: Config = None) -> dict:
    """
    Ingest a single paper. Phase 2 of the pipeline.
    
    Args:
        raw_path: Path to raw markdown file from Phase 1
        llm_client: Optional custom LLM function(prompt) -> str
        config: Optional Config object
    
    Returns:
        {
            "success": bool,
            "wiki_page": str,      # Full markdown with frontmatter
            "frontmatter": dict,
            "body": str,
            "error": str | None
        }
    """
    if config is None:
        config = Config()
    
    result = {"success": False, "wiki_page": "", "frontmatter": {}, "body": "", "error": None}
    
    # Read raw content
    raw_path = Path(raw_path)
    if not raw_path.exists():
        result["error"] = f"Raw file not found: {raw_path}"
        return result
    
    raw_markdown = raw_path.read_text()
    
    # Read schema tags
    schema_tags = []
    if config.SCHEMA_PATH.exists():
        schema_content = config.SCHEMA_PATH.read_text()
        # Extract tags from taxonomy sections
        for match in re.finditer(r'-\s+([\w-]+)', schema_content):
            schema_tags.append(match.group(1))
    
    # Read existing pages for wikilinks
    existing_pages = []
    if config.ENTITIES_DIR.exists():
        for f in config.ENTITIES_DIR.glob("*.md"):
            existing_pages.append(f.stem)
    
    # Build prompt
    prompt = build_ingest_prompt(raw_markdown, schema_tags, existing_pages)
    
    # Call LLM
    try:
        if llm_client:
            output = llm_client(prompt)
        else:
            output = call_llm_api(prompt, config=config)
    except Exception as e:
        result["error"] = f"LLM call failed: {e}"
        return result
    
    # Parse output
    parsed = parse_llm_output(output)
    
    result["success"] = True
    result["wiki_page"] = output
    result["frontmatter"] = parsed["frontmatter"]
    result["body"] = parsed["body"]
    
    return result


class Ingester:
    """Stateful ingester with manifest tracking."""
    
    def __init__(self, wiki_path: Path = None, llm_client: callable = None):
        self.config = Config()
        if wiki_path:
            self.config.WIKI_PATH = Path(wiki_path)
        self.llm_client = llm_client
        self.manifest = self._load_manifest()
    
    def _load_manifest(self) -> list:
        if self.config.MANIFEST_PATH.exists():
            return json.loads(self.config.MANIFEST_PATH.read_text())
        return []
    
    def _save_manifest(self):
        self.config.MANIFEST_PATH.write_text(json.dumps(self.manifest, indent=2))
    
    def get_pending(self) -> list:
        """Get list of uningested papers."""
        return [e for e in self.manifest if not e.get("ingested", False)]
    
    def ingest_next(self) -> dict:
        """Ingest the next pending paper."""
        pending = self.get_pending()
        if not pending:
            return {"success": False, "error": "No pending papers"}
        
        entry = pending[0]
        raw_path = entry.get("raw_path", "")
        
        result = ingest_paper(raw_path, llm_client=self.llm_client, config=self.config)
        
        if result["success"]:
            # Save wiki page
            slug = Path(raw_path).stem
            entity_path = self.config.ENTITIES_DIR / f"{slug}.md"
            entity_path.write_text(result["wiki_page"], encoding="utf-8")
            
            # Update manifest
            entry["ingested"] = True
            entry["entity_path"] = str(entity_path)
            self._save_manifest()
        
        return result
    
    def ingest_all(self) -> list:
        """Ingest all pending papers."""
        results = []
        while True:
            result = self.ingest_next()
            if not result["success"] and result.get("error") == "No pending papers":
                break
            results.append(result)
        return results
