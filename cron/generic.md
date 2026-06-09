# wiki-rag Ingest — Generic Cron (Any System)

## Standard Cron Syntax

wiki-rag uses standard 5-field cron expressions:

```
minute hour day-of-month month day-of-week
```

## Schedule Examples

| Schedule | Cron Expression |
|----------|----------------|
| Every 30 minutes | `*/30 * * * *` |
| Every hour | `0 * * * *` |
| Every 2 hours | `0 */2 * * *` |
| Daily at 9am | `0 9 * * *` |
| Daily at 6am | `0 6 * * *` |
| Weekly (Monday 6am) | `0 6 * * 1` |
| Weekdays at 9am | `0 9 * * 1-5` |

## System Crontab Example

```bash
# Edit crontab
crontab -e

# Add wiki-rag ingest (every 30 min)
*/30 * * * * cd /home/user && /usr/bin/python3 -c "
import json
from pathlib import Path
from wiki_rag import Ingester

wiki_path = Path.home() / 'wiki-rag'
i = Ingester(wiki_path)
result = i.ingest_next()
if result['success']:
    print(f'Ingested: {result[\"frontmatter\"].get(\"title\", \"unknown\")}')
" >> /tmp/wiki-rag.log 2>&1
```

## Python Schedule Example

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from wiki_rag import Ingester

ingester = Ingester("~/wiki-rag")
scheduler = BlockingScheduler()

@scheduler.scheduled_job('cron', minute='*/30')
def ingest_paper():
    result = ingester.ingest_next()
    if result['success']:
        print(f"Ingested: {result['frontmatter'].get('title', 'unknown')}")

scheduler.start()
```

## Notes
- Each run processes 1 paper from the manifest queue
- Requires LLM_API_KEY environment variable
- Raw papers must be collected first (Phase 1)
