import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from trend_analyzer import db as dbmod
from trend_analyzer.research_job import run_research_pass

# APScheduler accepts mon..sun; our DB stores 0=Monday .. 6=Sunday (Python weekday).
_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time (use HH:MM): {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid time: {s!r}")
    return h, m


def _timezone_for_row(tz_name: str):
    if not tz_name or tz_name == "local":
        return None
    return ZoneInfo(tz_name)


def register_schedule_jobs(
    scheduler: BackgroundScheduler, conn: sqlite3.Connection
) -> int:
    """Register jobs from DB. Only adds/removes changed jobs to avoid interrupting runs."""
    current_jobs = {job.id: job for job in scheduler.get_jobs() if str(job.id).startswith("ta_")}
    desired_job_ids = set()

    count = 0
    for row in dbmod.list_schedules(conn):
        if not row["enabled"]:
            continue
        sid = row["id"]
        freq = row["frequency"]
        times: list[str] = json.loads(row["time_points"])
        weekdays: list[int] = json.loads(row["weekdays"] or "[]")
        tz = _timezone_for_row(row["timezone"] or "local")

        if freq == "weekly" and not weekdays:
            continue

        for i, t in enumerate(times):
            job_id = f"ta_{sid}_{i}"
            if freq == "hourly":
                # Hourly jobs run every hour at the specified minute.
                _, minute = _parse_hhmm(t)
                trigger = CronTrigger(minute=minute, timezone=tz)
            elif freq == "daily":
                hour, minute = _parse_hhmm(t)
                trigger = CronTrigger(hour=hour, minute=minute, timezone=tz)
            elif freq == "weekly":
                hour, minute = _parse_hhmm(t)
                for w in weekdays:
                    if w < 0 or w > 6:
                        continue
                    dname = _WEEKDAY_NAMES[w]
                    jid = f"ta_{sid}_{i}_w{w}"
                    trigger = CronTrigger(
                        day_of_week=dname,
                        hour=hour,
                        minute=minute,
                        timezone=tz,
                    )
                    scheduler.add_job(
                        _make_runner(sid),
                        trigger=trigger,
                        id=jid,
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                        misfire_grace_time=3600,
                    )
                    desired_job_ids.add(jid)
                    count += 1
                continue
            elif freq == "once":
                from apscheduler.triggers.date import DateTrigger
                try:
                    # Try full ISO first
                    run_at = datetime.fromisoformat(t.replace(" ", "T"))
                except ValueError:
                    # Fallback to HH:MM (assume today)
                    h, m = _parse_hhmm(t)
                    run_at = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
                
                trigger = DateTrigger(run_date=run_at, timezone=tz)
                scheduler.add_job(
                    _make_runner(sid),
                    trigger=trigger,
                    id=f"ta_{sid}_{i}",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=3600,
                )
                desired_job_ids.add(f"ta_{sid}_{i}")
                count += 1
                continue
            else:
                continue

            scheduler.add_job(
                _make_runner(sid),
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )
            desired_job_ids.add(job_id)
            count += 1

    # Remove jobs that are no longer in DB
    for jid in current_jobs:
        if jid not in desired_job_ids:
            scheduler.remove_job(jid)

    return count


def _make_runner(schedule_id: int):
    def runner():
        path = dbmod.db_path()
        conn = dbmod.connect(path)
        try:
            run_research_pass(conn, schedule_id)
        finally:
            conn.close()

    return runner
