"""research_job.py — executes one trend analysis cycle."""

import sqlite3
import datetime
from typing import Any, Callable
from trend_analyzer import db as dbmod
from trend_analyzer.chat_llm import run_trend_analysis
from trend_analyzer.renderer import save_report_to_db


def run_research_pass(
    conn: sqlite3.Connection,
    schedule_id: int | None,
    progress_cb: Callable[[str, dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> str:
    run_id = dbmod.log_run_start(conn, schedule_id)
    
    # If it's a "once" schedule, disable it IMMEDIATELY so we don't re-trigger it
    # if the scheduler polls while we are still running.
    if schedule_id:
        row = dbmod.schedule_row(conn, schedule_id)
        if row and row["frequency"] == "once":
            dbmod.update_schedule(conn, schedule_id, enabled=False)

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    try:
        raw_level = dbmod.get_setting(conn, dbmod.SETTING_THINKING_LEVEL)
        try:
            thinking_level = int(raw_level) if raw_level is not None else 2
        except ValueError:
            thinking_level = 2
        thinking_level = max(1, min(5, thinking_level))

        report = run_trend_analysis(
            conn,
            thinking_level=thinking_level,
            progress_cb=progress_cb,
            cancel_check=cancel_check,
        )
        if _cancelled():
            raise RuntimeError("Run cancelled by user.")

        dbmod.save_trend_report_from_dataclass(
            conn, report, run_id=run_id,
            provider_used=getattr(report, "_provider_used", ""),
        )
        for p in getattr(report, "predictions", []) or []:
            if _cancelled():
                raise RuntimeError("Run cancelled by user.")
            try:
                hv = max(1, int(p.get("horizon_value") or 1))
            except (TypeError, ValueError):
                hv = 1
            unit = str(p.get("horizon_unit") or "weeks").strip().lower()
            if unit not in {"days", "weeks", "months", "years"}:
                unit = "weeks"
            now = datetime.datetime.now(datetime.timezone.utc)
            if unit == "days":
                td = now + datetime.timedelta(days=hv)
            elif unit == "weeks":
                td = now + datetime.timedelta(weeks=hv)
            elif unit == "months":
                td = now + datetime.timedelta(days=30 * hv)
            else:
                td = now + datetime.timedelta(days=365 * hv)
            dbmod.add_prediction(
                conn,
                run_id=run_id,
                prediction_text=str(p.get("prediction_text") or "").strip(),
                horizon_value=hv,
                horizon_unit=unit,
                target_date=td.replace(microsecond=0).isoformat(),
                confidence=str(p.get("confidence") or "medium"),
                rationale=str(p.get("rationale") or ""),
                sources=list(p.get("sources") or []),
            )
        # Keep Overview feeds in sync: populate discovered_trends + ai_analyses.
        if _cancelled():
            raise RuntimeError("Run cancelled by user.")
        setattr(report, "run_id", run_id)
        save_report_to_db(conn, report)

        if report.severity in ("high", "critical"):
            from trend_analyzer.renderer import render_trend_report
            alert_html = render_trend_report(report)
            # pass alert_html to your email/notification sender
            # e.g. send_alert_email(alert_html) — not implemented yet

        summary = (
            f"[{report.severity.upper()}] {report.summary[:120]}"
            if report.summary else "Analysis complete — no summary."
        )
        dbmod.log_run_finish(conn, run_id, "ok", summary)
        return summary

    except Exception as e:
        msg = f"error: {e}"
        dbmod.log_run_finish(conn, run_id, "error", msg)
        raise
