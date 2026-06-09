# wiki-rag Ingest — Generic Cron (Any System)

This is a generic cron definition that can be adapted to any system.

## Schedule
Every 30 minutes

## Steps
1. Read manifest.json from WIKI_PATH
2. Find first entry where "ingested" is false
3. Read the raw markdown file at entry["raw_path"]
4. Read SCHEMA.md for tag taxonomy
5. Call LLM API to synthesize wiki page:
   - Prompt: Paper content + schema tags + existing page titles
   - Model: Configured via LLM_MODEL env var
   - Output: Markdown with YAML frontmatter
6. Save wiki page to entities/{slug}.md
7. Update manifest.json (set ingested: true)
8. Update index.md (add entry, bump count)
9. Append to log.md

## Environment Variables
- LLM_API_KEY: API key
- LLM_API_BASE: API base URL (default: https://api.openai.com/v1)
- LLM_MODEL: Model name (default: gpt-4o)
- WIKI_PATH: Path to wiki directory (default: ~/wiki-rag)

## Python Implementation
See wiki_rag/ingest.py for the reference implementation.
