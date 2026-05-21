"""Background APScheduler wired to SQLite — shared by CLI `serve` and FastAPI lifespan."""

from __future__ import annotations

import threading

from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED, EVENT_JOB_ERROR
from tzlocal import get_localzone

from trend_analyzer import db as dbmod
from trend_analyzer.schedule_builder import register_schedule_jobs


class SchedulerDaemon:
    def __init__(self, *, reload_interval_sec: float = 60.0):
        self._reload_interval_sec = reload_interval_sec
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._sched = None
        self._last_job_count = 0

    def start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler

        dbmod.init_db()
        self._sched = BackgroundScheduler(timezone=get_localzone())

        def reload_jobs_impl() -> int:
            conn = dbmod.connect()
            try:
                return register_schedule_jobs(self._sched, conn)
            finally:
                conn.close()

        self._last_job_count = reload_jobs_impl()
        
        def on_event(event):
            if event.code in (EVENT_JOB_MISSED, EVENT_JOB_MAX_INSTANCES):
                # job_id is ta_{sid}_{i}
                jid = str(event.job_id)
                if not jid.startswith("ta_"):
                    return
                parts = jid.split("_")
                if len(parts) < 2:
                    return
                try:
                    sid = int(parts[1])
                except ValueError:
                    return
                
                conn = dbmod.connect()
                try:
                    # JobEvent has scheduled_run_time; JobSubmissionEvent (max instances) has scheduled_run_times (list)
                    s_time = getattr(event, "scheduled_run_time", None)
                    if s_time is None:
                        s_times = getattr(event, "scheduled_run_times", [])
                        if s_times:
                            s_time = s_times[0]
                    
                    sched_time = (
                        s_time.replace(microsecond=0).isoformat()
                        if s_time else dbmod.utc_now_iso()
                    )
                    
                    if event.code == EVENT_JOB_MISSED:
                        dbmod.log_missed_run(conn, sid, sched_time)
                    elif event.code == EVENT_JOB_ERROR:
                        exc = getattr(event, "exception", "Unknown error")
                        dbmod.log_failed_run(conn, sid, sched_time, f"Job failed: {exc}")
                    else:
                        dbmod.log_skipped_run(conn, sid, sched_time)
                    
                    # If it's a "once" schedule, disable it so we don't keep missing/skipping it
                    row = dbmod.schedule_row(conn, sid)
                    if row and row["frequency"] == "once":
                        dbmod.update_schedule(conn, sid, enabled=False)
                finally:
                    conn.close()

        self._sched.add_listener(on_event, EVENT_JOB_MISSED | EVENT_JOB_MAX_INSTANCES | EVENT_JOB_ERROR)
        self._sched.start()

        def poll():
            while not self._stop.wait(timeout=self._reload_interval_sec):
                self._last_job_count = reload_jobs_impl()

        if self._reload_interval_sec > 0:
            self._poll_thread = threading.Thread(target=poll, daemon=True)
            self._poll_thread.start()

    def reload_jobs_now(self) -> int:
        if not self._sched:
            raise RuntimeError("Scheduler not running")
        conn = dbmod.connect()
        try:
            self._last_job_count = register_schedule_jobs(self._sched, conn)
            return self._last_job_count
        finally:
            conn.close()

    @property
    def job_count(self) -> int:
        return self._last_job_count

    def shutdown(self) -> None:
        self._stop.set()
        if self._sched:
            try:
                self._sched.shutdown(wait=False)
            except Exception:
                pass
            self._sched = None
