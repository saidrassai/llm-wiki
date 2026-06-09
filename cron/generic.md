# wiki-rag Ingest — Generic Cron (Any System)

## Dependencies

```bash
pip install wiki-rag[cron]
# or
pip install croniter
```

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

## Python Scheduler (using croniter)

```python
from wiki_rag.scheduler import CronSchedule
from wiki_rag import Ingester

schedule = CronSchedule("*/30 * * * *")
ingester = Ingester("~/wiki-rag")

# Check if due
if schedule.is_due():
    result = ingester.ingest_next()
    if result["success"]:
        print(f"Ingested: {result['frontmatter'].get('title')}")

# Get next 5 runs
for t in schedule.next_runs(5):
    print(f"Next run: {t}")
```

## System Crontab

```bash
# Edit crontab
crontab -e

# Add wiki-rag ingest (every 30 min)
*/30 * * * * cd /home/user && python3 -c "
from wiki_rag import Ingester
i = Ingester('~/wiki-rag')
result = i.ingest_next()
print(result)
" >> /tmp/wiki-rag.log 2>&1
```

## APScheduler Example

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from wiki_rag import Ingester

ingester = Ingester("~/wiki-rag")
scheduler = BlockingScheduler()

@scheduler.scheduled_job('cron', minute='*/30')
def ingest_paper():
    result = ingester.ingest_next()
    if result["success"]:
        print(f"Ingested: {result['frontmatter'].get('title', 'unknown')}")

scheduler.start()
```

## Schedule Presets

```python
from wiki_rag.scheduler import get_schedule_presets

presets = get_schedule_presets()
# {
#     "every_30_min": "*/30 * * * *",
#     "every_hour": "0 * * * *",
#     "daily_9am": "0 9 * * *",
#     "weekly_monday_6am": "0 6 * * 1",
#     ...
# }
```

## Human-Readable Expressions

```python
from wiki_rag.scheduler import CronSchedule

print(CronSchedule.human_readable("*/30 * * * *"))
# Output: "every 30 minutes"

print(CronSchedule.human_readable("0 9 * * 1-5"))
# Output: "at 9:00 on weekdays"
```
