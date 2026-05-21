"""
db.py — Trend Analyzer database layer
======================================
Single source of truth for all DB access.

Schema version history:
  1 — initial schema
  2 — chat sessions
  3 — research schedules + runs
  4 — trend_reports table, new settings keys (trend_topics, newsapi_key,
      news_region, news_sources, crawler_enabled)
  12 — repair dangling FK references to dropped table research_runs_old
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from trend_analyzer.config import db_path

SCHEMA_VERSION = 12


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # FastAPI may create/yield/close dependency objects on different worker
    # threads. Allow cross-thread access for request-scoped connections.
    conn = sqlite3.connect(p, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    conn.execute("BEGIN")
    cur = conn.cursor()
    try:
        yield cur
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def init_db(path: Path | None = None) -> Path:
    p = db_path() if path is None else Path(path)
    conn = connect(p)
    cur = conn.cursor()
    cur.executescript(
        """
        -- ── Core meta ────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- ── Business profile ─────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS company_profile (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            name     TEXT,
            sector   TEXT,
            region   TEXT,
            products TEXT,
            notes    TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_instructions (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            body       TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        -- ── Research scheduling ──────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS research_schedules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            label       TEXT,
            frequency   TEXT NOT NULL CHECK (frequency IN ('hourly', 'daily', 'weekly', 'once')),
            weekdays    TEXT,
            time_points TEXT NOT NULL,
            timezone    TEXT NOT NULL DEFAULT 'local',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER REFERENCES research_schedules(id) ON DELETE SET NULL,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            status      TEXT NOT NULL,
            summary     TEXT
        );

        -- ── Discovered trends ────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS discovered_trends (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
            title        TEXT NOT NULL,
            summary      TEXT NOT NULL DEFAULT '',
            category     TEXT NOT NULL DEFAULT 'general',
            source_url   TEXT,
            relevance    INTEGER NOT NULL DEFAULT 50 CHECK (relevance BETWEEN 0 AND 100),
            discovered_at TEXT NOT NULL
        );

        -- ── AI analyses ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS ai_analyses (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
            trend_id       INTEGER REFERENCES discovered_trends(id) ON DELETE SET NULL,
            headline       TEXT NOT NULL,
            recommendation TEXT NOT NULL DEFAULT '',
            confidence     TEXT NOT NULL DEFAULT 'medium'
                               CHECK (confidence IN ('low', 'medium', 'high')),
            visualisation  TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL
        );

        -- ── Trend reports (structured output from run_trend_analysis) ────
        --    Stores the full TrendReport dataclass as decomposed columns
        --    so the UI can query, filter, and sort without JSON parsing.
        CREATE TABLE IF NOT EXISTS trend_reports (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT NOT NULL,
            query_used          TEXT NOT NULL DEFAULT '',
            summary             TEXT NOT NULL DEFAULT '',
            trend_signals       TEXT NOT NULL DEFAULT '[]',   -- JSON list[str]
            recommended_actions TEXT NOT NULL DEFAULT '[]',   -- JSON list[str]
            severity            TEXT NOT NULL DEFAULT 'low'
                                    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
            sources             TEXT NOT NULL DEFAULT '[]',   -- JSON list[str]
            visualisation       TEXT NOT NULL DEFAULT '',
            provider_used       TEXT NOT NULL DEFAULT '',
            run_id              INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
            created_at          TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trend_reports_timestamp
            ON trend_reports (timestamp DESC);

        CREATE INDEX IF NOT EXISTS idx_trend_reports_severity
            ON trend_reports (severity);

        -- ── AI predictions (time-bound forecast registry) ────────────────
        CREATE TABLE IF NOT EXISTS ai_predictions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
            prediction_text TEXT NOT NULL,
            horizon_value   INTEGER NOT NULL,
            horizon_unit    TEXT NOT NULL CHECK (horizon_unit IN ('days','weeks','months','years')),
            target_date     TEXT NOT NULL,
            confidence      TEXT NOT NULL DEFAULT 'medium'
                                CHECK (confidence IN ('low','medium','high')),
            rationale       TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'open'
                                CHECK (status IN ('open','resolved','expired')),
            resolution_note TEXT NOT NULL DEFAULT '',
            sources         TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ai_predictions_target_date
            ON ai_predictions (target_date);
        CREATE INDEX IF NOT EXISTS idx_ai_predictions_status
            ON ai_predictions (status);

        -- ── Chat history ─────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages (session_id, id ASC);
        """
    )

    # ── Migration tracking ───────────────────────────────────────────────────
    row = cur.execute(
        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (SCHEMA_VERSION,)
        )
    elif row["version"] < SCHEMA_VERSION:
        _run_migrations(cur, from_version=row["version"])
        cur.execute(
            "INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )

    # ── Seed singleton rows ──────────────────────────────────────────────────
    now = utc_now_iso()
    if (
        cur.execute("SELECT 1 FROM company_profile WHERE id = 1 LIMIT 1").fetchone()
        is None
    ):
        cur.execute(
            "INSERT INTO company_profile "
            "(id, name, sector, region, products, notes, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (1, "", "", "", "", "", now),
        )

    if (
        cur.execute("SELECT 1 FROM user_instructions WHERE id = 1 LIMIT 1").fetchone()
        is None
    ):
        cur.execute(
            "INSERT INTO user_instructions (id, body, updated_at) VALUES (?,?,?)",
            (1, "", now),
        )

    conn.close()
    return p


def _run_migrations(cur: sqlite3.Cursor, from_version: int) -> None:
    """
    Forward-only migrations for databases created before SCHEMA_VERSION 4.
    Add a new `if from_version < N` block for every future version bump.
    """
    if from_version < 4:
        # Add trend_reports table (may already exist if init_db ran the CREATE above)
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS trend_reports (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           TEXT NOT NULL,
                query_used          TEXT NOT NULL DEFAULT '',
                summary             TEXT NOT NULL DEFAULT '',
                trend_signals       TEXT NOT NULL DEFAULT '[]',
                recommended_actions TEXT NOT NULL DEFAULT '[]',
                severity            TEXT NOT NULL DEFAULT 'low'
                                        CHECK (severity IN ('low','medium','high','critical')),
                sources             TEXT NOT NULL DEFAULT '[]',
                provider_used       TEXT NOT NULL DEFAULT '',
                run_id              INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
                created_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trend_reports_timestamp
                ON trend_reports (timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_trend_reports_severity
                ON trend_reports (severity);

            -- research_schedules gained 'hourly' in v4
            -- SQLite does not support ALTER COLUMN; recreate if the CHECK is too old.
            -- Safe: CREATE TABLE IF NOT EXISTS is a no-op on existing tables.
            """
        )
    if from_version < 5:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_predictions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
                prediction_text TEXT NOT NULL,
                horizon_value   INTEGER NOT NULL,
                horizon_unit    TEXT NOT NULL CHECK (horizon_unit IN ('days','weeks','months','years')),
                target_date     TEXT NOT NULL,
                confidence      TEXT NOT NULL DEFAULT 'medium'
                                    CHECK (confidence IN ('low','medium','high')),
                rationale       TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'open'
                                    CHECK (status IN ('open','resolved','expired')),
                resolution_note TEXT NOT NULL DEFAULT '',
                sources         TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_predictions_target_date
                ON ai_predictions (target_date);
            CREATE INDEX IF NOT EXISTS idx_ai_predictions_status
                ON ai_predictions (status);
            """
        )
    if from_version < 6:
        _add_column_if_missing(
            cur,
            "discovered_trends",
            "run_id",
            "INTEGER REFERENCES research_runs(id) ON DELETE SET NULL",
        )
        _add_column_if_missing(
            cur,
            "ai_analyses",
            "run_id",
            "INTEGER REFERENCES research_runs(id) ON DELETE SET NULL",
        )
    if from_version < 7:
        _add_column_if_missing(
            cur,
            "ai_analyses",
            "visualisation",
            "TEXT NOT NULL DEFAULT ''",
        )
    if from_version < 8:
        _add_column_if_missing(
            cur,
            "trend_reports",
            "visualisation",
            "TEXT NOT NULL DEFAULT ''",
        )
    if from_version < 10:
        # Recreate research_schedules to allow 'once' (and 'hourly') in frequency CHECK
        # (Redoing this in v10 because v9 migration was problematic for some users)
        cur.executescript(
            """
            ALTER TABLE research_schedules RENAME TO research_schedules_old;
            CREATE TABLE research_schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                label       TEXT,
                frequency   TEXT NOT NULL CHECK (frequency IN ('hourly', 'daily', 'weekly', 'once')),
                weekdays    TEXT,
                time_points TEXT NOT NULL,
                timezone    TEXT NOT NULL DEFAULT 'local',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            INSERT INTO research_schedules (id, enabled, label, frequency, weekdays, time_points, timezone, created_at, updated_at)
            SELECT id, enabled, label, frequency, weekdays, time_points, timezone, created_at, updated_at
            FROM research_schedules_old;
            DROP TABLE research_schedules_old;
            """
        )
    if from_version < 11:
        # Fix broken foreign key in research_runs (it was pointing to research_schedules_old)
        cur.executescript(
            """
            PRAGMA foreign_keys = OFF;
            ALTER TABLE research_runs RENAME TO research_runs_old;
            CREATE TABLE research_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER REFERENCES research_schedules(id) ON DELETE SET NULL,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                status      TEXT NOT NULL,
                summary     TEXT
            );
            INSERT INTO research_runs (id, schedule_id, started_at, finished_at, status, summary)
            SELECT id, schedule_id, started_at, finished_at, status, summary
            FROM research_runs_old;
            DROP TABLE research_runs_old;
            PRAGMA foreign_keys = ON;
            """
        )
    if from_version < 12:
        # The v10→v11 migration renamed research_runs temporarily.  SQLite
        # 3.26+ automatically rewrites FK references in child-table schemas
        # when a parent table is renamed — even when PRAGMA foreign_keys is
        # OFF — so discovered_trends, ai_analyses, trend_reports, and
        # ai_predictions all ended up with run_id REFERENCES research_runs_old
        # after research_runs_old was dropped.  Patch the on-disk schema
        # directly to point those FKs back at the correct research_runs table.
        cur.executescript(
            """
            PRAGMA writable_schema = ON;
            UPDATE sqlite_master
                SET sql = REPLACE(
                              REPLACE(sql, '"research_runs_old"', 'research_runs'),
                              'research_runs_old', 'research_runs')
                WHERE type IN ('table', 'trigger')
                  AND sql LIKE '%research_runs_old%';
            PRAGMA writable_schema = OFF;
            """
        )


def _add_column_if_missing(
    cur: sqlite3.Cursor,
    table_name: str,
    column_name: str,
    column_ddl: str,
) -> None:
    cols = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    if any(str(r[1]) == column_name for r in cols):
        return
    cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")


# ---------------------------------------------------------------------------
# Settings keys
# ---------------------------------------------------------------------------

# ── LLM providers ────────────────────────────────────────────────────────────
SETTING_OPENAI_API_KEY = "openai_api_key"
SETTING_GEMINI_API_KEY = "gemini_api_key"
SETTING_LLM_PROVIDER = "llm_provider"  # "openai" | "gemini"
SETTING_GEMINI_MODEL = "gemini_model"

# ── Google Custom Search Engine ───────────────────────────────────────────────
SETTING_GOOGLE_API_KEY = "google_api_key"
SETTING_GOOGLE_CX = "google_cx"
SETTING_GOOGLE_SEARCH_ENABLED = "google_search_enabled"  # "1" | "0"

# ── SerpAPI Search Engine ─────────────────────────────────────────────────────
SETTING_SERPAPI_API_KEY = "serpapi_api_key"
SETTING_SERPAPI_ENGINE = "serpapi_engine"  # e.g. "bing", "google"
SETTING_SERPAPI_SEARCH_ENABLED = "serpapi_search_enabled"  # "1" | "0"

# ── Firecrawl ─────────────────────────────────────────────────────────────────
SETTING_FIRECRAWL_API_KEY = "firecrawl_api_key"
SETTING_FIRECRAWL_SEARCH_ENABLED = "firecrawl_search_enabled"  # "1" | "0"

# ── DuckDuckGo (free, no key required) ───────────────────────────────────────
SETTING_DDG_SEARCH_ENABLED = "ddg_search_enabled"  # "1" | "0"
SETTING_DDG_REGION = "ddg_region"  # e.g. "wt-wt", "us-en"
SETTING_DDG_TIMELIMIT = "ddg_timelimit"  # "d"|"w"|"m"|"y"|""

# Default iterative search depth used by autonomous runs and chat fallback.
# Range: "1".."5"
SETTING_THINKING_LEVEL = "thinking_level"
SETTING_DEEP_READ_ENABLED = "deep_read_enabled"  # "1" | "0"
SETTING_DEEP_READ_MAX_ARTICLES = "deep_read_max_articles"  # "1".."8"

# ── NewsAPI (newsapi.org) ─────────────────────────────────────────────────────
SETTING_NEWSAPI_KEY = "newsapi_key"
# Comma-separated country codes to scope NewsAPI queries, e.g. "ke,gb,us"
SETTING_NEWS_REGION = "news_region"
# Comma-separated domain list to restrict NewsAPI sources, e.g. "bbc.co.uk,nation.africa"
# These mirror your Google CSE site list so both tools draw from the same publishers.
SETTING_NEWS_SOURCES = "news_sources"

# ── Trend watching ────────────────────────────────────────────────────────────
# JSON list[str] of topic strings, e.g. ["fuel prices", "crude oil", "OPEC", "Kenya energy"]
SETTING_TREND_TOPICS = "trend_topics"

# ── Web crawler ───────────────────────────────────────────────────────────────
# "1" | "0" — whether the scheduler may crawl source URLs for full article text
SETTING_CRAWLER_ENABLED = "crawler_enabled"

# ── Local GGUF model ──────────────────────────────────────────────────────────
SETTING_LOCAL_MODEL_PATH = "local_model_path"  # absolute path to .gguf file
SETTING_LOCAL_N_CTX = "local_n_ctx"  # context window size (default 4096)
SETTING_LOCAL_N_GPU_LAYERS = "local_n_gpu_layers"  # GPU layers (0=CPU, -1=all)

# ── Gemini model options ──────────────────────────────────────────────────────
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"]

# ── Default news sources mirroring your Google CSE site list ─────────────────
# Used as the fallback value for SETTING_NEWS_SOURCES when the user hasn't
# configured it explicitly. Keeps CSE + NewsAPI pulling from the same publishers.
DEFAULT_NEWS_DOMAINS = (
    "bbc.co.uk,"
    "aljazeera.com,"
    "globalnews.ca,"
    "citizen.digital,"
    "the-star.co.ke,"
    "kenyans.co.ke,"
    "standardmedia.co.ke,"
    "nation.africa,"
    "capitalfm.co.ke,"
    "businessdailyafrica.com,"
    "kenyanwallstreet.com,"
    "tuko.co.ke"
)


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if value == "":
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE
            SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """Returns all settings as a plain dict. Useful for UI settings pages."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


# ---------------------------------------------------------------------------
# Company profile
# ---------------------------------------------------------------------------


def get_company_profile(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM company_profile WHERE id = 1").fetchone()


def update_company_profile(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    sector: str | None = None,
    region: str | None = None,
    products: str | None = None,
    notes: str | None = None,
) -> None:
    row = get_company_profile(conn)
    if not row:
        return
    conn.execute(
        "UPDATE company_profile "
        "SET name=?, sector=?, region=?, products=?, notes=?, updated_at=? "
        "WHERE id = 1",
        (
            row["name"] if name is None else name,
            row["sector"] if sector is None else sector,
            row["region"] if region is None else region,
            row["products"] if products is None else products,
            row["notes"] if notes is None else notes,
            utc_now_iso(),
        ),
    )


# ---------------------------------------------------------------------------
# User instructions
# ---------------------------------------------------------------------------


def get_user_instructions(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM user_instructions WHERE id = 1").fetchone()


def set_user_instructions(conn: sqlite3.Connection, body: str) -> None:
    conn.execute(
        "UPDATE user_instructions SET body = ?, updated_at = ? WHERE id = 1",
        (body, utc_now_iso()),
    )


# ---------------------------------------------------------------------------
# Trend topics (monitored watch-list)
# ---------------------------------------------------------------------------


def get_trend_topics(conn: sqlite3.Connection) -> list[str]:
    """Returns the list of monitored topic strings."""
    raw = get_setting(conn, SETTING_TREND_TOPICS)
    if not raw:
        return []
    try:
        topics = json.loads(raw)
        return [str(t) for t in topics if t]
    except (json.JSONDecodeError, TypeError):
        return []


def set_trend_topics(conn: sqlite3.Connection, topics: list[str]) -> None:
    """Saves the full topic list, replacing any previous value."""
    set_setting(conn, SETTING_TREND_TOPICS, json.dumps(topics))


def add_trend_topic(conn: sqlite3.Connection, topic: str) -> list[str]:
    """Appends a single topic if not already present. Returns updated list."""
    topics = get_trend_topics(conn)
    if topic and topic not in topics:
        topics.append(topic)
        set_trend_topics(conn, topics)
    return topics


def remove_trend_topic(conn: sqlite3.Connection, topic: str) -> list[str]:
    """Removes a topic if present. Returns updated list."""
    topics = [t for t in get_trend_topics(conn) if t != topic]
    set_trend_topics(conn, topics)
    return topics


# ---------------------------------------------------------------------------
# Research schedules
# ---------------------------------------------------------------------------


def list_schedules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                s.*,
                r.status as last_run_status,
                r.started_at as last_run_at,
                r.summary as last_run_summary
            FROM research_schedules s
            LEFT JOIN (
                SELECT schedule_id, status, started_at, summary,
                       ROW_NUMBER() OVER (PARTITION BY schedule_id ORDER BY id DESC) as rn
                FROM research_runs
            ) r ON s.id = r.schedule_id AND r.rn = 1
            ORDER BY s.id ASC
            """
        ).fetchall()
    )


def schedule_row(conn: sqlite3.Connection, sid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM research_schedules WHERE id = ?", (sid,)
    ).fetchone()


def add_schedule(
    conn: sqlite3.Connection,
    *,
    frequency: str,
    time_points: list[str],
    weekdays: list[int] | None = None,
    label: str | None = None,
    timezone_name: str = "local",
    enabled: bool = True,
) -> int:
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO research_schedules
                (enabled, label, frequency, weekdays, time_points, timezone, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                1 if enabled else 0,
                label or "",
                frequency,
                json.dumps(weekdays or []),
                json.dumps(time_points),
                timezone_name,
                now,
                now,
            ),
        )
        return int(cur.lastrowid or 0)


def update_schedule(conn: sqlite3.Connection, sid: int, **fields: Any) -> None:
    allowed = {"enabled", "label", "frequency", "weekdays", "time_points", "timezone"}
    cols: list[str] = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "enabled":
            v = 1 if v else 0
        elif k in ("weekdays", "time_points") and isinstance(v, list):
            v = json.dumps(v)
        cols.append(f"{k} = ?")
        vals.append(v)
    if not cols:
        return
    cols.append("updated_at = ?")
    vals += [utc_now_iso(), sid]
    conn.execute(f"UPDATE research_schedules SET {', '.join(cols)} WHERE id = ?", vals)


def delete_schedule(conn: sqlite3.Connection, sid: int) -> int:
    cur = conn.execute("DELETE FROM research_schedules WHERE id = ?", (sid,))
    return cur.rowcount


# ---------------------------------------------------------------------------
# Research runs
# ---------------------------------------------------------------------------


def log_run_start(conn: sqlite3.Connection, schedule_id: int | None) -> int:
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO research_runs (schedule_id, started_at, status, summary) "
            "VALUES (?,?,?,?)",
            (schedule_id, utc_now_iso(), "started", None),
        )
        return int(cur.lastrowid or 0)


def log_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    summary: str | None,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE research_runs "
            "SET finished_at = ?, status = ?, summary = ? "
            "WHERE id = ?",
            (utc_now_iso(), status, summary, run_id),
        )


def log_missed_run(
    conn: sqlite3.Connection,
    schedule_id: int,
    scheduled_time: str,
) -> int:
    """Logs a run that was scheduled but never started (misfired)."""
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO research_runs (schedule_id, started_at, finished_at, status, summary) "
            "VALUES (?,?,?,?,?)",
            (
                schedule_id,
                scheduled_time,
                now,
                "missed",
                "Job misfired/missed by scheduler.",
            ),
        )
        return int(cur.lastrowid or 0)


def log_skipped_run(
    conn: sqlite3.Connection,
    schedule_id: int,
    scheduled_time: str,
) -> int:
    """Logs a run that was skipped because max instances were already running."""
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO research_runs (schedule_id, started_at, finished_at, status, summary) "
            "VALUES (?,?,?,?,?)",
            (
                schedule_id,
                scheduled_time,
                now,
                "skipped",
                "Skipped: another instance is already running.",
            ),
        )
        return int(cur.lastrowid or 0)


def log_failed_run(
    conn: sqlite3.Connection,
    schedule_id: int,
    scheduled_time: str,
    error_msg: str,
) -> int:
    """Logs a run that failed to execute due to a scheduler error."""
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO research_runs (schedule_id, started_at, finished_at, status, summary) "
            "VALUES (?,?,?,?,?)",
            (schedule_id, scheduled_time, now, "error", error_msg),
        )
        return int(cur.lastrowid or 0)


def list_recent_runs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM research_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    )


def delete_run(conn: sqlite3.Connection, run_id: int) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM research_runs WHERE id = ?", (run_id,))
        count = conn.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'research_runs'")
        return cur.rowcount


# ---------------------------------------------------------------------------
# Trend reports  (structured output from chat.run_trend_analysis)
# ---------------------------------------------------------------------------


def save_trend_report(
    conn: sqlite3.Connection,
    *,
    timestamp: str,
    query_used: str,
    summary: str,
    trend_signals: list[str],
    recommended_actions: list[str],
    severity: str,
    sources: list[str],
    visualisation: str = "",
    provider_used: str = "",
    run_id: int | None = None,
) -> int:
    """
    Persists a structured trend report.
    All list fields are stored as JSON strings.
    Returns the new row id.
    """
    valid_severities = {"low", "medium", "high", "critical"}
    if severity not in valid_severities:
        severity = "low"

    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO trend_reports
                (timestamp, query_used, summary, trend_signals,
                 recommended_actions, severity, sources, visualisation,
                 provider_used, run_id, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                timestamp,
                query_used,
                summary,
                json.dumps(trend_signals),
                json.dumps(recommended_actions),
                severity,
                json.dumps(sources),
                visualisation or "",
                provider_used,
                run_id,
                now,
            ),
        )
        return int(cur.lastrowid or 0)


def save_trend_report_from_dataclass(
    conn: sqlite3.Connection,
    report: Any,
    *,
    provider_used: str = "",
    run_id: int | None = None,
) -> int:
    """
    Convenience wrapper — accepts a TrendReport dataclass from chat.py directly.
    """
    return save_trend_report(
        conn,
        timestamp=getattr(report, "timestamp", utc_now_iso()),
        query_used=getattr(report, "query_used", ""),
        summary=getattr(report, "summary", ""),
        trend_signals=getattr(report, "trend_signals", []),
        recommended_actions=getattr(report, "recommended_actions", []),
        severity=getattr(report, "severity", "low"),
        sources=getattr(report, "sources", []),
        visualisation=getattr(report, "visualisation", ""),
        provider_used=provider_used,
        run_id=run_id,
    )


def list_trend_reports(
    conn: sqlite3.Connection,
    limit: int = 50,
    severity_filter: str | None = None,
) -> list[sqlite3.Row]:
    """
    Returns recent trend_reports rows, newest first.
    Optionally filtered to a specific severity level.
    """
    if severity_filter:
        return list(
            conn.execute(
                "SELECT * FROM trend_reports WHERE severity = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (severity_filter, limit),
            ).fetchall()
        )
    return list(
        conn.execute(
            "SELECT * FROM trend_reports ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def get_trend_report(conn: sqlite3.Connection, report_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM trend_reports WHERE id = ?", (report_id,)
    ).fetchone()


def delete_trend_report(conn: sqlite3.Connection, report_id: int) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM trend_reports WHERE id = ?", (report_id,))
        count = conn.execute("SELECT COUNT(*) FROM trend_reports").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'trend_reports'")
        return cur.rowcount


def trend_report_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """
    Deserialises a trend_reports row into a plain dict with Python lists.
    Useful for passing to renderer.py or the API layer.
    """
    d = dict(row)
    for field in ("trend_signals", "recommended_actions", "sources"):
        try:
            d[field] = json.loads(d[field]) if d[field] else []
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    return d


# ---------------------------------------------------------------------------
# Discovered trends
# ---------------------------------------------------------------------------


def add_trend(
    conn: sqlite3.Connection,
    *,
    run_id: int | None = None,
    title: str,
    summary: str = "",
    category: str = "general",
    source_url: str | None = None,
    relevance: int = 50,
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO discovered_trends
                (run_id, title, summary, category, source_url, relevance, discovered_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                run_id,
                title,
                summary,
                category,
                source_url,
                max(0, min(100, relevance)),
                utc_now_iso(),
            ),
        )
        return int(cur.lastrowid or 0)


def list_recent_trends(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM discovered_trends ORDER BY relevance DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def get_trend(conn: sqlite3.Connection, trend_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM discovered_trends WHERE id = ?", (trend_id,)
    ).fetchone()


def delete_trend(conn: sqlite3.Connection, trend_id: int) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM discovered_trends WHERE id = ?", (trend_id,))
        count = conn.execute("SELECT COUNT(*) FROM discovered_trends").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'discovered_trends'")
        return cur.rowcount


# ---------------------------------------------------------------------------
# AI analyses
# ---------------------------------------------------------------------------


def add_analysis(
    conn: sqlite3.Connection,
    *,
    run_id: int | None = None,
    headline: str,
    recommendation: str = "",
    confidence: str = "medium",
    trend_id: int | None = None,
    visualisation: str = "",
) -> int:
    conf = confidence if confidence in ("low", "medium", "high") else "medium"
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO ai_analyses
                (run_id, trend_id, headline, recommendation, confidence, visualisation, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                run_id,
                trend_id,
                headline,
                recommendation,
                conf,
                visualisation,
                utc_now_iso(),
            ),
        )
        return int(cur.lastrowid or 0)


def list_recent_analyses(
    conn: sqlite3.Connection, limit: int = 10
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT a.*, t.title AS trend_title
            FROM ai_analyses a
            LEFT JOIN discovered_trends t ON t.id = a.trend_id
            ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    )


def get_analysis(conn: sqlite3.Connection, analysis_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ai_analyses WHERE id = ?", (analysis_id,)
    ).fetchone()


def delete_analysis(conn: sqlite3.Connection, analysis_id: int) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM ai_analyses WHERE id = ?", (analysis_id,))
        count = conn.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ai_analyses'")
        return cur.rowcount


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------


def create_chat_session(
    conn: sqlite3.Connection, title: str = "New Research Thread"
) -> int:
    now = utc_now_iso()
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO chat_sessions (title, created_at, updated_at) VALUES (?,?,?)",
            (title, now, now),
        )
        return int(cur.lastrowid or 0)


def list_chat_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM chat_sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def get_chat_messages(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    )


def add_chat_message(
    conn: sqlite3.Connection, session_id: int, role: str, content: str
) -> None:
    now = utc_now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, created_at) "
            "VALUES (?,?,?,?)",
            (session_id, role, content, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )


def delete_chat_session(conn: sqlite3.Connection, session_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        count = conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'chat_sessions'")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'chat_messages'")


def update_chat_session_title(
    conn: sqlite3.Connection, session_id: int, title: str
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, utc_now_iso(), session_id),
        )


# ---------------------------------------------------------------------------
# Dashboard stats helper (used by renderer.py and API)
# ---------------------------------------------------------------------------


def get_dashboard_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Returns a single dict of counts and last-run info for the dashboard.
    Avoids N separate queries in the UI layer.
    """
    trend_count = conn.execute("SELECT COUNT(*) FROM discovered_trends").fetchone()[0]

    analysis_count = conn.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0]

    report_count = conn.execute("SELECT COUNT(*) FROM trend_reports").fetchone()[0]

    high_conf = conn.execute(
        "SELECT COUNT(*) FROM ai_analyses WHERE confidence = 'high'"
    ).fetchone()[0]

    critical_reports = conn.execute(
        "SELECT COUNT(*) FROM trend_reports WHERE severity IN ('high', 'critical')"
    ).fetchone()[0]

    last_run = conn.execute(
        "SELECT finished_at, status FROM research_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    return {
        "trend_count": trend_count,
        "analysis_count": analysis_count,
        "report_count": report_count,
        "high_confidence": high_conf,
        "critical_reports": critical_reports,
        "last_run_at": last_run["finished_at"] if last_run else None,
        "last_run_status": last_run["status"] if last_run else None,
    }


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------


def add_prediction(
    conn: sqlite3.Connection,
    *,
    prediction_text: str,
    horizon_value: int,
    horizon_unit: str,
    target_date: str,
    confidence: str = "medium",
    rationale: str = "",
    run_id: int | None = None,
    sources: list[str] | None = None,
) -> int:
    conf = confidence if confidence in {"low", "medium", "high"} else "medium"
    unit = (
        horizon_unit
        if horizon_unit in {"days", "weeks", "months", "years"}
        else "weeks"
    )
    hv = max(1, int(horizon_value))
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO ai_predictions
                (run_id, prediction_text, horizon_value, horizon_unit, target_date,
                 confidence, rationale, status, resolution_note, sources, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                prediction_text.strip(),
                hv,
                unit,
                target_date,
                conf,
                rationale.strip(),
                "open",
                "",
                json.dumps(sources or []),
                utc_now_iso(),
            ),
        )
        return int(cur.lastrowid or 0)


def list_recent_predictions(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM ai_predictions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def list_open_predictions(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM ai_predictions WHERE status = 'open' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def delete_prediction(conn: sqlite3.Connection, prediction_id: int) -> int:
    with transaction(conn):
        cur = conn.execute("DELETE FROM ai_predictions WHERE id = ?", (prediction_id,))
        count = conn.execute("SELECT COUNT(*) FROM ai_predictions").fetchone()[0]
        if count == 0:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'ai_predictions'")
        return cur.rowcount


def delete_history_items(
    conn: sqlite3.Connection,
    *,
    run_ids: list[int] | None = None,
    trend_ids: list[int] | None = None,
    analysis_ids: list[int] | None = None,
    prediction_ids: list[int] | None = None,
) -> dict[str, int]:
    """
    Atomically delete a specific set of history items by ID.
    Also deletes any trend_reports whose run_id is in run_ids.
    Returns {table: rows_deleted}.
    """
    counts: dict[str, int] = {}

    def _del(table: str, ids: list[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id IN ({placeholders})",  # noqa: S608
            ids,
        )
        return cur.rowcount

    with transaction(conn):
        counts["ai_predictions"] = _del("ai_predictions", prediction_ids or [])
        counts["ai_analyses"] = _del("ai_analyses", analysis_ids or [])
        counts["discovered_trends"] = _del("discovered_trends", trend_ids or [])
        # Delete trend_reports that belong to the same runs
        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            cur = conn.execute(
                f"DELETE FROM trend_reports WHERE run_id IN ({placeholders})",  # noqa: S608
                run_ids,
            )
            counts["trend_reports"] = cur.rowcount
        else:
            counts["trend_reports"] = 0
        counts["research_runs"] = _del("research_runs", run_ids or [])
    return counts


def purge_research_data(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Deletes all research-generated data while preserving:
      - settings (API keys, provider, search config, etc.)
      - company_profile
      - user_instructions
      - research_schedules
      - schema_migrations

    Returns a dict of {table_name: rows_deleted} for UI confirmation.
    """
    tables = [
        "chat_messages",
        "chat_sessions",
        "ai_predictions",
        "trend_reports",
        "ai_analyses",
        "discovered_trends",
        "research_runs",
    ]
    counts: dict[str, int] = {}
    # Disable FK enforcement for the bulk purge so that the deletion order
    # does not matter and SET NULL cascade actions on already-empty tables
    # don't cause spurious failures (e.g. after a schema migration that left
    # stale FK references).  Re-enable unconditionally in the finally block.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            for table in tables:
                cur = conn.execute(f"DELETE FROM {table}")  # noqa: S608
                counts[table] = cur.rowcount
            # Reset autoincrement sequences so new items start at ID 1
            for table in tables:
                conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return counts
