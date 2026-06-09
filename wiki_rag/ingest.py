"""
Phase 2: LLM-powered wiki page synthesis.

Takes raw markdown + JSON from Phase 1 and produces a polished wiki page.
Works with any LLM API — OpenAI, Anthropic, Ollama, or custom.

Environment variables:
    LLM_API_KEY: API key (required)
    LLM_API_BASE: API base URL (default: https://api.openai.com/v1)
    LLM_MODEL: Model name (default: gpt-4o)
"""

import json, re
from pathlib import Path

DEFAULT_SYSTEM = """You are a research assistant that creates wiki pages from academic papers.
Produce a structured wiki page with: YAML frontmatter, Overview, Key Contributions,
Architecture/Method, Related Work, Results/Findings, and See Also with [[wikilinks]].
Keep the body under 500 words. Be specific and technical."""


def build_ingest_prompt(raw_markdown: str, schema_tags: list = None, existing_pages: list = None, domain: str = "research") -> str:
    """Build LLM prompt. Domain-aware."""
    
    domain_hints = {
        "rag": "Focus on retrieval techniques, indexing, generation methods, evaluation metrics.",
        "sft": "Focus on training data, fine-tuning methods, loss functions, benchmarks.",
        "rl": "Focus on reward modeling, policy optimization, training stability.",
        "agentic": "Focus on agent architectures, tool use, planning, multi-step reasoning.",
    }
    hint = domain_hints.get(domain, "")
    
    tags_section = f"\n\nValid tags: {', '.join(schema_tags[:30])}" if schema_tags else ""
    pages_section = f"\n\nExisting pages: {', '.join(existing_pages[:20])}" if existing_pages else ""
    
    return f"""Create a wiki page from this paper.{tags_section}{pages_section}

DOMAIN HINT: {hint}

PAPER:
---
{raw_markdown[:8000]}
---

OUTPUT:
---
title: "Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity
tags: [tag1, tag2, tag3]
sources: [raw/path.md]
confidence: high
---

## Overview
[2-3 sentences]

## Key Contributions
- [Contribution 1]
- [Contribution 2]
- [Contribution 3]

## Architecture / Method
[1 paragraph]

## Related Work
[1 paragraph]

## Results / Findings
[Key metrics]

## See Also
- [[Related Concept 1]]
- [[Related Concept 2]]
"""


def ingest_paper(raw_path: Path, llm_client: callable = None, schema_tags: list = None,
                 existing_pages: list = None, domain: str = "research") -> dict:
    """
    Ingest a single paper. Returns {success, wiki_page, frontmatter, error}.
    
    Args:
        raw_path: Path to raw markdown from Phase 1
        llm_client: Function(prompt: str) -> str. If None, uses env vars.
        schema_tags: Valid tags from SCHEMA.md
        existing_pages: Existing wiki page titles for wikilinks
        domain: Domain hint for prompt (rag, sft, rl, agentic, etc.)
    """
    result = {"success": False, "wiki_page": "", "frontmatter": {}, "error": None}
    
    if not raw_path.exists():
        result["error"] = f"File not found: {raw_path}"
        return result
    
    prompt = build_ingest_prompt(raw_path.read_text(), schema_tags, existing_pages, domain)
    
    try:
        if llm_client:
            output = llm_client(prompt)
        else:
            output = _call_api(prompt)
    except Exception as e:
        result["error"] = f"LLM error: {e}"
        return result
    
    # Parse frontmatter
    fm = {}
    m = re.search(r'^---\s*\n(.*?)\n---', output, re.DOTALL)
    if m:
        for line in m.group(1).split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                fm[k] = v
    
    result.update({"success": True, "wiki_page": output, "frontmatter": fm})
    return result


def _call_api(prompt: str) -> str:
    """Call LLM API from env vars."""
    import os, urllib.request
    
    api_key = os.getenv("LLM_API_KEY", "")
    api_base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    model = os.getenv("LLM_MODEL", "gpt-4o")
    
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": DEFAULT_SYSTEM},
                     {"role": "user", "content": prompt}],
        "max_tokens": 2000, "temperature": 0.3
    }).encode()
    
    req = urllib.request.Request(f"{api_base}/chat/completions", data=payload,
                                  headers={"Authorization": f"Bearer {api_key}",
                                           "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]
