# wiki-rag Ingest — Hermes Agent Cron

## Create the cron job

```bash
# Every 30 minutes
hermes cron create "*/30 * * * *" "wiki-rag ingest one paper from manifest.

STEPS:
1. Read ~/wiki-rag/manifest.json
2. Find first entry where ingested is false
3. Read the raw markdown file at raw_path
4. Read ~/wiki-rag/SCHEMA.md (first 70 lines for tag taxonomy)
5. Create a wiki entity page at ~/wiki-rag/entities/{slug}.md with:
   - YAML frontmatter (title, created, updated, type, tags, sources, confidence)
   - Overview paragraph (2-3 sentences)
   - Key Contributions (3-5 bullet points)
   - Architecture/Method summary
   - Related Work (1 paragraph)
   - Results/Findings with specific metrics
   - See Also with 2+ [[wikilinks]]
6. Update manifest.json: set ingested to true for this entry
7. Update ~/wiki-rag/index.md: add to Entities section, bump count
8. Append to ~/wiki-rag/log.md

RULES:
- Only use read_file and write_file tools
- Tags MUST come from SCHEMA.md taxonomy
- Minimum 2 [[wikilinks]] per page
- Keep body under 500 words
- If raw file not found, skip and mark ingested: true with error note"

# Check status
hermes cron list

# Trigger manually
hermes cron run wiki-rag-hourly-backfill

# Pause/resume
hermes cron pause wiki-rag-hourly-backfill
hermes cron resume wiki-rag-hourly-backfill
```

## Schedule Options

| Schedule | Cron Expression | Description |
|----------|----------------|-------------|
| Every 30 min | `*/30 * * * *` | Default |
| Every hour | `0 * * * *` | Hourly |
| Every 2 hours | `0 */2 * * *` | Twice daily |
| Daily 9am | `0 9 * * *` | Once daily |
| Weekly Monday 6am | `0 6 * * 1` | Weekly |

## Notes
- Uses standard 5-field cron syntax (minute, hour, day, month, weekday)
- Each run processes 1 paper from the manifest queue
- Runs in a fresh agent session (no conversation history)
- Requires gateway running: `hermes gateway start`
