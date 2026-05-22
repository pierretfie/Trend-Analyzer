from __future__ import annotations

import json
import signal
import sys
import time

import typer

from trend_analyzer import db as dbmod
from trend_analyzer.config import data_dir, db_path
from trend_analyzer.research_job import run_research_pass
from trend_analyzer.scheduling_daemon import SchedulerDaemon

app = typer.Typer(
    no_args_is_help=True,
    help="Local trend analyzer — SQLite under ~/.Trend_analyzer/ by default.",
    epilog="Override data directory: export TA_DATA_DIR=/path (or TREND_ANALYZER_DATA_DIR).",
)

schedule_app = typer.Typer(no_args_is_help=True, help="Research run times.")
app.add_typer(schedule_app, name="schedule")

_WDAY = {
    "mon": 0,
    "mo": 0,
    "tue": 1,
    "tu": 1,
    "wed": 2,
    "we": 2,
    "thu": 3,
    "th": 3,
    "fri": 4,
    "fr": 4,
    "sat": 5,
    "sa": 5,
    "sun": 6,
    "su": 6,
}


def _parse_weekdays(s: str) -> list[int]:
    if not s.strip():
        return []
    out: list[int] = []
    for part in s.split(","):
        k = part.strip().lower()
        if k not in _WDAY:
            raise typer.BadParameter(f"Unknown weekday {part!r} (use mon..sun)")
        v = _WDAY[k]
        if v not in out:
            out.append(v)
    out.sort()
    return out


def _parse_times(s: str) -> list[str]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        raise typer.BadParameter("Provide at least one HH:MM in --times")
    for p in parts:
        hp = p.split(":")
        if len(hp) != 2:
            raise typer.BadParameter(f"Invalid time {p!r} (use HH:MM)")
        h, m = int(hp[0]), int(hp[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise typer.BadParameter(f"Invalid time {p!r}")
    return parts


def _conn():
    dbmod.init_db()
    return dbmod.connect()


@app.command("init")
def cmd_init():
    """Create ~/.Trend_analyzer/ and SQLite schema."""
    dbmod.init_db()
    typer.echo(f"OK — database at {db_path()}")
    typer.echo(f"Data dir: {data_dir()}")


@app.command("run-once")
def cmd_run_once(
    schedule_id: int | None = typer.Option(None, "--schedule-id", "-s"),
):
    """Run one research pass now (same logging as scheduled runs)."""
    conn = _conn()
    try:
        summary = run_research_pass(conn, schedule_id)
        typer.echo(summary)
    finally:
        conn.close()


@schedule_app.command("add")
def schedule_add(
    frequency: str = typer.Argument(..., help="'daily' or 'weekly'"),
    times: str = typer.Option(..., "--times", "-t", help="Comma-separated times, e.g. 07:00 or 07:00,19:30"),
    label: str = typer.Option("", "--label", "-l"),
    weekdays: str = typer.Option(
        "",
        "--weekdays",
        "-w",
        help="Weekly only: comma days mon,tue,… (Monday-Sunday convention)",
    ),
    tz: str = typer.Option("local", "--tz", help="'local' or IANA e.g. Africa/Nairobi"),
):
    fq = frequency.strip().lower()
    if fq not in ("daily", "weekly"):
        raise typer.BadParameter("frequency must be daily or weekly")
    tp = _parse_times(times)
    wd: list[int] = []
    if fq == "weekly":
        wd = _parse_weekdays(weekdays)
        if not wd:
            raise typer.BadParameter("weekly schedules need --weekdays mon,thu,…")
    conn = _conn()
    try:
        sid = dbmod.add_schedule(
            conn,
            frequency=fq,
            time_points=tp,
            weekdays=wd,
            label=label or None,
            timezone_name=tz,
        )
        typer.echo(f"Added schedule id={sid} ({fq}, times={tp})")
        typer.echo("Restart `trend-analyzer serve` if it is already running.")
    finally:
        conn.close()


@schedule_app.command("list")
def schedule_list():
    conn = _conn()
    try:
        rows = dbmod.list_schedules(conn)
        if not rows:
            typer.echo("(no schedules)")
            return
        for r in rows:
            times = json.loads(r["time_points"])
            wk = json.loads(r["weekdays"] or "[]")
            typer.echo(
                f"[{r['id']}] en={bool(r['enabled'])} {r['frequency']!s} "
                f"times={times} weekdays={wk} tz={r['timezone']!s} "
                f"label={r['label']!r}"
            )
    finally:
        conn.close()


@schedule_app.command("enable")
def schedule_enable(schedule_id: int = typer.Argument(...)):
    conn = _conn()
    try:
        if not dbmod.schedule_row(conn, schedule_id):
            raise typer.BadParameter(f"No schedule {schedule_id}")
        dbmod.update_schedule(conn, schedule_id, enabled=True)
        typer.echo("Enabled. Restart serve if running.")
    finally:
        conn.close()


@schedule_app.command("disable")
def schedule_disable(schedule_id: int = typer.Argument(...)):
    conn = _conn()
    try:
        if not dbmod.schedule_row(conn, schedule_id):
            raise typer.BadParameter(f"No schedule {schedule_id}")
        dbmod.update_schedule(conn, schedule_id, enabled=False)
        typer.echo("Disabled. Restart serve if running.")
    finally:
        conn.close()


@schedule_app.command("remove")
def schedule_remove(
    schedule_id: int = typer.Argument(...),
    force: bool = typer.Option(False, "--force", "-f"),
):
    conn = _conn()
    try:
        if not dbmod.schedule_row(conn, schedule_id):
            raise typer.BadParameter(f"No schedule {schedule_id}")
        if not force:
            typer.confirm(f"Remove schedule {schedule_id}?", abort=True)
        n = dbmod.delete_schedule(conn, schedule_id)
        typer.echo(f"Removed ({n}). Restart serve if running.")
    finally:
        conn.close()


@app.command("serve")
def cmd_serve(
    reload_secs: float = typer.Option(
        60.0,
        "--reload-every",
        "-r",
        help="Reload schedules from DB on this interval (seconds). Use 0 to disable.",
    ),
):
    """
    Run only the background scheduler (no web UI). Uses your local timezone.
    For the full app with UI, use: npm run start (or trend-analyzer web).
    """
    dbmod.init_db()
    daemon = SchedulerDaemon(reload_interval_sec=reload_secs)
    daemon.start()
    typer.echo(
        f"Scheduler running — {daemon.job_count} job(s). DB {db_path()}. Ctrl+C to stop.",
        err=True,
    )

    def shutdown(*_args):
        daemon.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        shutdown()


@app.command("web")
def cmd_web(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8765, "--port"),
):
    """Start the web UI and API (scheduler runs in the server process)."""
    import uvicorn

    from trend_analyzer.server import app as server_app

    typer.echo(f"Open http://{host}:{port}/ in your browser", err=True)
    uvicorn.run(
        server_app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def main():
    app()


if __name__ == "__main__":
    main()
