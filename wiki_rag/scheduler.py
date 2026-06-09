"""
Cron scheduling utilities for wiki-rag.

Uses croniter for parsing cron expressions and computing next run times.
Works with any cron expression supported by croniter.

Installation:
    pip install croniter

Usage:
    from wiki_rag.scheduler import CronSchedule
    
    schedule = CronSchedule("*/30 * * * *")
    next_run = schedule.next_run()
    print(f"Next run: {next_run}")
"""

from datetime import datetime, timedelta
from typing import Optional

try:
    from croniter import croniter
    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False


class CronSchedule:
    """Parse and compute cron schedule times."""
    
    def __init__(self, expression: str, base_time: datetime = None):
        """
        Initialize with a cron expression.
        
        Args:
            expression: Standard 5-field cron expression (e.g., "*/30 * * * *")
            base_time: Base time for computing next run (default: now)
        
        Raises:
            ImportError: If croniter is not installed
            ValueError: If expression is invalid
        """
        if not CRONITER_AVAILABLE:
            raise ImportError(
                "croniter is required for scheduling. "
                "Install with: pip install croniter"
            )
        
        self.expression = expression
        self.base_time = base_time or datetime.now()
        
        if not croniter.is_valid(expression):
            raise ValueError(f"Invalid cron expression: {expression}")
        
        self._cron = croniter(expression, self.base_time)
    
    def next_run(self, base_time: datetime = None) -> datetime:
        """Get the next scheduled run time."""
        if base_time:
            self._cron = croniter(self.expression, base_time)
        return self._cron.get_next(datetime)
    
    def next_runs(self, count: int = 5) -> list:
        """Get the next N scheduled run times."""
        runs = []
        cron = croniter(self.expression, datetime.now())
        for _ in range(count):
            runs.append(cron.get_next(datetime))
        return runs
    
    def is_due(self, last_run: datetime = None, tolerance_seconds: int = 60) -> bool:
        """Check if a job is due to run."""
        now = datetime.now()
        if last_run is None:
            return True
        
        next_run = self.next_run(base_time=last_run)
        return (now - next_run).total_seconds() >= -tolerance_seconds
    
    @staticmethod
    def validate(expression: str) -> bool:
        """Validate a cron expression."""
        if not CRONITER_AVAILABLE:
            raise ImportError("croniter is required")
        return croniter.is_valid(expression)
    
    @staticmethod
    def human_readable(expression: str) -> str:
        """Convert cron expression to human-readable description."""
        parts = expression.split()
        if len(parts) != 5:
            return expression
        
        minute, hour, dom, month, dow = parts
        
        descriptions = []
        
        # Minute
        if minute == "*":
            descriptions.append("every minute")
        elif minute.startswith("*/"):
            m = int(minute[2:])
            descriptions.append(f"every {m} minutes")
        elif minute.isdigit():
            descriptions.append(f"at minute {minute}")
        
        # Hour
        if hour == "*":
            pass  # Already covered by minute
        elif hour.startswith("*/"):
            h = int(hour[2:])
            descriptions.append(f"every {h} hours")
        elif hour.isdigit():
            descriptions.append(f"at {hour}:00")
        
        # Day of week
        if dow != "*":
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            if dow.isdigit():
                descriptions.append(f"on {days[int(dow) % 7]}")
            elif dow == "1-5":
                descriptions.append("on weekdays")
        
        return " ".join(descriptions) if descriptions else expression


def get_schedule_presets() -> dict:
    """Get common schedule presets."""
    return {
        "every_30_min": "*/30 * * * *",
        "every_hour": "0 * * * *",
        "every_2_hours": "0 */2 * * *",
        "daily_9am": "0 9 * * *",
        "daily_6am": "0 6 * * *",
        "weekly_monday_6am": "0 6 * * 1",
        "weekdays_9am": "0 9 * * 1-5",
    }
