# wiki-rag Ingest — Hermes Agent Cron

wiki-rag ingest one paper from manifest.

STEPS:
1. Read ~/wiki-rag/manifest.json
2. Find first entry where "ingested" is false
3. Read the raw markdown file at entry["raw_path"]
4. Read ~/wiki-rag/SCHEMA.md (first 70 lines for tag taxonomy)
5. Create a wiki entity page at ~/wiki-rag/entities/{slug}.md with:
   - YAML frontmatter (title, created, updated, type, tags, sources, confidence)
   - Overview paragraph (2-3 sentences)
   - Key Contributions (3-5 bullet points)
   - Architecture/Method summary
   - Related Work (1 paragraph)
   - Results/Findings with specific metrics
   - See Also with 2+ [[wikilinks]]
6. Update manifest.json: set "ingested": true for this entry
7. Update ~/wiki-rag/index.md: add to Entities section, bump count
8. Append to ~/wiki-rag/log.md

RULES:
- Only use read_file and write_file tools
- Tags MUST come from SCHEMA.md taxonomy
- Minimum 2 [[wikilinks]] per page
- Keep body under 500 words
- If raw file not found, skip and mark ingested: true with error note
