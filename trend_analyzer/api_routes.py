"""HTTP API for the desktop UI — same SQLite and scheduler as the CLI."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
from collections.abc import Generator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from trend_analyzer import db as dbmod
from trend_analyzer.chat_llm import normalize_thinking_level, run_chat
from trend_analyzer.config import data_dir, db_path
from trend_analyzer.research_job import run_research_pass

router = APIRouter(prefix="/api", tags=["api"])

_LLM_PROVIDERS = frozenset({"none", "openai", "gemini", "local"})


def _mask_secret(raw: str | None) -> str | None:
    if not raw:
        return None
    tail = raw[-4:] if len(raw) >= 4 else raw
    return f"••••{tail}"


def _normalize_provider(v: str | None) -> str:
    if v in _LLM_PROVIDERS:
        return v
    return "none"


def _is_truthy(v: str | None, *, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def get_db() -> Generator[sqlite3.Connection, None, None]:
    dbmod.init_db()
    conn = dbmod.connect()
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _schedule_decode(row: sqlite3.Row) -> dict[str, Any]:
    d = _row_to_dict(row)
    d["enabled"] = bool(d["enabled"])
    d["time_points"] = json.loads(d["time_points"])
    d["weekdays"] = json.loads(d["weekdays"] or "[]")
    return d


def _validate_time_points(time_points: list[str]) -> None:
    for t in time_points:
        # Try full ISO first (used for "once" schedules from the frontend)
        try:
            datetime.fromisoformat(t.replace(" ", "T"))
            continue
        except ValueError:
            pass

        # Fallback to HH:MM (standard recurring schedules)
        parts = t.split(":")
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid time {t!r} (use HH:MM or ISO datetime)",
            )
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid time {t!r} (use HH:MM or ISO datetime)",
            ) from exc
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise HTTPException(status_code=400, detail=f"Invalid time {t!r}")


def _validate_weekdays(weekdays: list[int]) -> None:
    if any((d < 0 or d > 6) for d in weekdays):
        raise HTTPException(status_code=400, detail="Weekdays must be in range 0..6")


@router.get("/model-setup")
def get_model_setup(conn: Db) -> dict[str, Any]:
    openai = dbmod.get_setting(conn, dbmod.SETTING_OPENAI_API_KEY)
    gemini = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_API_KEY)
    provider = _normalize_provider(dbmod.get_setting(conn, dbmod.SETTING_LLM_PROVIDER))
    google_key = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_API_KEY)
    google_cx = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_CX)
    serpapi_key = dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_API_KEY)
    serpapi_engine = (
        dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_ENGINE) or "bing"
    ).strip() or "bing"
    google_search_enabled = (
        dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_SEARCH_ENABLED) or "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    serpapi_search_enabled = (
        dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_SEARCH_ENABLED) or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    firecrawl_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
    firecrawl_search_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
        default=False,
    )
    ddg_search_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_DDG_SEARCH_ENABLED),
        default=False,
    )
    ddg_region = (
        dbmod.get_setting(conn, dbmod.SETTING_DDG_REGION) or "wt-wt"
    ).strip() or "wt-wt"
    ddg_timelimit = (dbmod.get_setting(conn, dbmod.SETTING_DDG_TIMELIMIT) or "").strip()
    raw_thinking = dbmod.get_setting(conn, dbmod.SETTING_THINKING_LEVEL)
    deep_read_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_ENABLED),
        default=True,
    )
    raw_deep_read_max = dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_MAX_ARTICLES)
    try:
        thinking_level = normalize_thinking_level(
            int(raw_thinking) if raw_thinking is not None else None, default=2
        )
    except ValueError:
        thinking_level = 2
    try:
        deep_read_max_articles = max(
            1, min(8, int(raw_deep_read_max) if raw_deep_read_max is not None else 3)
        )
    except ValueError:
        deep_read_max_articles = 3
    raw_model = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_MODEL)
    gemini_model = (
        raw_model if raw_model in dbmod.GEMINI_MODELS else dbmod.GEMINI_MODEL_DEFAULT
    )
    local_model_path = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_MODEL_PATH) or ""
    local_n_ctx_raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_CTX)
    local_n_gpu_layers_raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_GPU_LAYERS)
    try:
        local_n_ctx = max(512, int(local_n_ctx_raw)) if local_n_ctx_raw else 4096
    except ValueError:
        local_n_ctx = 4096
    try:
        local_n_gpu_layers = (
            int(local_n_gpu_layers_raw) if local_n_gpu_layers_raw else 0
        )
    except ValueError:
        local_n_gpu_layers = 0
    return {
        "llm_provider": provider,
        "openai_configured": bool(openai),
        "openai_masked": _mask_secret(openai),
        "gemini_configured": bool(gemini),
        "gemini_masked": _mask_secret(gemini),
        "gemini_model": gemini_model,
        "google_configured": bool(google_key),
        "google_masked": _mask_secret(google_key),
        "google_cx": google_cx or "",
        "google_search_enabled": google_search_enabled,
        "serpapi_configured": bool(serpapi_key),
        "serpapi_masked": _mask_secret(serpapi_key),
        "serpapi_engine": serpapi_engine,
        "serpapi_search_enabled": serpapi_search_enabled,
        "firecrawl_configured": bool(firecrawl_key),
        "firecrawl_masked": _mask_secret(firecrawl_key),
        "firecrawl_search_enabled": firecrawl_search_enabled,
        "ddg_search_enabled": ddg_search_enabled,
        "ddg_region": ddg_region,
        "ddg_timelimit": ddg_timelimit,
        "thinking_level": thinking_level,
        "deep_read_enabled": deep_read_enabled,
        "deep_read_max_articles": deep_read_max_articles,
        "local_model_path": local_model_path,
        "local_n_ctx": local_n_ctx,
        "local_n_gpu_layers": local_n_gpu_layers,
    }


class ModelSetupPatch(BaseModel):
    llm_provider: Literal["none", "openai", "gemini", "local"] | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    google_api_key: str | None = None
    google_cx: str | None = None
    google_search_enabled: bool | None = None
    serpapi_api_key: str | None = None
    serpapi_engine: str | None = None
    serpapi_search_enabled: bool | None = None
    firecrawl_api_key: str | None = None
    firecrawl_search_enabled: bool | None = None
    ddg_search_enabled: bool | None = None
    ddg_region: str | None = None
    ddg_timelimit: str | None = None
    thinking_level: int | None = Field(default=None, ge=1, le=5)
    deep_read_enabled: bool | None = None
    deep_read_max_articles: int | None = Field(default=None, ge=1, le=8)
    local_model_path: str | None = None
    local_n_ctx: int | None = Field(default=None, ge=512, le=131072)
    local_n_gpu_layers: int | None = Field(default=None, ge=-1, le=999)


@router.patch("/model-setup")
def patch_model_setup(payload: ModelSetupPatch, conn: Db) -> dict[str, Any]:
    if payload.llm_provider is not None:
        dbmod.set_setting(conn, dbmod.SETTING_LLM_PROVIDER, payload.llm_provider)
    if payload.openai_api_key is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_OPENAI_API_KEY, payload.openai_api_key.strip()
        )
    if payload.gemini_api_key is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_GEMINI_API_KEY, payload.gemini_api_key.strip()
        )
    if payload.gemini_model is not None and payload.gemini_model in dbmod.GEMINI_MODELS:
        dbmod.set_setting(conn, dbmod.SETTING_GEMINI_MODEL, payload.gemini_model)
    if payload.google_api_key is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_GOOGLE_API_KEY, payload.google_api_key.strip()
        )
    if payload.google_cx is not None:
        dbmod.set_setting(conn, dbmod.SETTING_GOOGLE_CX, payload.google_cx.strip())
    if payload.google_search_enabled is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_GOOGLE_SEARCH_ENABLED,
            "1" if payload.google_search_enabled else "0",
        )
    if payload.serpapi_api_key is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_SERPAPI_API_KEY, payload.serpapi_api_key.strip()
        )
    if payload.serpapi_engine is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_SERPAPI_ENGINE, payload.serpapi_engine.strip() or "bing"
        )
    if payload.serpapi_search_enabled is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_SERPAPI_SEARCH_ENABLED,
            "1" if payload.serpapi_search_enabled else "0",
        )
    if payload.firecrawl_api_key is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_FIRECRAWL_API_KEY, payload.firecrawl_api_key.strip()
        )
    if payload.firecrawl_search_enabled is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED,
            "1" if payload.firecrawl_search_enabled else "0",
        )
    if payload.ddg_search_enabled is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_DDG_SEARCH_ENABLED,
            "1" if payload.ddg_search_enabled else "0",
        )
    if payload.ddg_region is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_DDG_REGION,
            payload.ddg_region.strip() or "wt-wt",
        )
    if payload.ddg_timelimit is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_DDG_TIMELIMIT,
            payload.ddg_timelimit.strip(),
        )
    if payload.thinking_level is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_THINKING_LEVEL,
            str(normalize_thinking_level(payload.thinking_level)),
        )
    if payload.deep_read_enabled is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_DEEP_READ_ENABLED,
            "1" if payload.deep_read_enabled else "0",
        )
    if payload.deep_read_max_articles is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_DEEP_READ_MAX_ARTICLES,
            str(max(1, min(8, payload.deep_read_max_articles))),
        )
    if payload.local_model_path is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_LOCAL_MODEL_PATH, payload.local_model_path.strip()
        )
        # Unload cached model so next call picks up the new path
        try:
            from trend_analyzer import local_llm

            local_llm.unload()
        except Exception:
            pass
    if payload.local_n_ctx is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_LOCAL_N_CTX, str(max(512, payload.local_n_ctx))
        )
    if payload.local_n_gpu_layers is not None:
        dbmod.set_setting(
            conn, dbmod.SETTING_LOCAL_N_GPU_LAYERS, str(payload.local_n_gpu_layers)
        )
    openai = dbmod.get_setting(conn, dbmod.SETTING_OPENAI_API_KEY)
    gemini = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_API_KEY)
    provider = _normalize_provider(dbmod.get_setting(conn, dbmod.SETTING_LLM_PROVIDER))
    google_key = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_API_KEY)
    google_cx = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_CX)
    serpapi_key = dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_API_KEY)
    serpapi_engine = (
        dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_ENGINE) or "bing"
    ).strip() or "bing"
    google_search_enabled = (
        dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_SEARCH_ENABLED) or "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    serpapi_search_enabled = (
        dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_SEARCH_ENABLED) or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    firecrawl_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
    firecrawl_search_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
        default=False,
    )
    ddg_search_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_DDG_SEARCH_ENABLED),
        default=False,
    )
    ddg_region = (
        dbmod.get_setting(conn, dbmod.SETTING_DDG_REGION) or "wt-wt"
    ).strip() or "wt-wt"
    ddg_timelimit = (dbmod.get_setting(conn, dbmod.SETTING_DDG_TIMELIMIT) or "").strip()
    raw_thinking = dbmod.get_setting(conn, dbmod.SETTING_THINKING_LEVEL)
    deep_read_enabled = _is_truthy(
        dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_ENABLED),
        default=True,
    )
    raw_deep_read_max = dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_MAX_ARTICLES)
    try:
        thinking_level = normalize_thinking_level(
            int(raw_thinking) if raw_thinking is not None else None, default=2
        )
    except ValueError:
        thinking_level = 2
    try:
        deep_read_max_articles = max(
            1, min(8, int(raw_deep_read_max) if raw_deep_read_max is not None else 3)
        )
    except ValueError:
        deep_read_max_articles = 3
    raw_model = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_MODEL)
    gemini_model = (
        raw_model if raw_model in dbmod.GEMINI_MODELS else dbmod.GEMINI_MODEL_DEFAULT
    )
    local_model_path = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_MODEL_PATH) or ""
    local_n_ctx_raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_CTX)
    local_n_gpu_layers_raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_GPU_LAYERS)
    try:
        local_n_ctx = max(512, int(local_n_ctx_raw)) if local_n_ctx_raw else 4096
    except ValueError:
        local_n_ctx = 4096
    try:
        local_n_gpu_layers = (
            int(local_n_gpu_layers_raw) if local_n_gpu_layers_raw else 0
        )
    except ValueError:
        local_n_gpu_layers = 0
    return {
        "llm_provider": provider,
        "openai_configured": bool(openai),
        "openai_masked": _mask_secret(openai),
        "gemini_configured": bool(gemini),
        "gemini_masked": _mask_secret(gemini),
        "gemini_model": gemini_model,
        "google_configured": bool(google_key),
        "google_masked": _mask_secret(google_key),
        "google_cx": google_cx or "",
        "google_search_enabled": google_search_enabled,
        "serpapi_configured": bool(serpapi_key),
        "serpapi_masked": _mask_secret(serpapi_key),
        "serpapi_engine": serpapi_engine,
        "serpapi_search_enabled": serpapi_search_enabled,
        "firecrawl_configured": bool(firecrawl_key),
        "firecrawl_masked": _mask_secret(firecrawl_key),
        "firecrawl_search_enabled": firecrawl_search_enabled,
        "ddg_search_enabled": ddg_search_enabled,
        "ddg_region": ddg_region,
        "ddg_timelimit": ddg_timelimit,
        "thinking_level": thinking_level,
        "deep_read_enabled": deep_read_enabled,
        "deep_read_max_articles": deep_read_max_articles,
        "local_model_path": local_model_path,
        "local_n_ctx": local_n_ctx,
        "local_n_gpu_layers": local_n_gpu_layers,
    }


@router.get("/local-models")
def list_local_models(directory: str = "") -> dict[str, Any]:
    """Scan a directory for .gguf files and return their paths."""
    from pathlib import Path

    search_dir = Path(directory).expanduser() if directory.strip() else Path.home()
    results: list[dict[str, str | float]] = []

    if not search_dir.exists() or not search_dir.is_dir():
        return {"directory": str(search_dir), "models": []}

    try:
        for entry in sorted(search_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".gguf":
                results.append(
                    {
                        "name": entry.name,
                        "path": str(entry.resolve()),
                        "size_mb": round(entry.stat().st_size / (1024 * 1024), 1),
                    }
                )
    except PermissionError:
        pass

    return {"directory": str(search_dir), "models": results}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=16000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=48)
    mode: Literal["chat", "analysis", "search"] = "analysis"
    provider: Literal["auto", "openai", "gemini", "local"] = "auto"
    session_id: int | None = None
    thinking_level: int | None = Field(default=None, ge=1, le=5)


@router.get("/chat/sessions")
def get_chat_sessions(conn: Db, limit: int = 50) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in dbmod.list_chat_sessions(conn, limit)]


@router.post("/chat/sessions")
def create_chat_session(conn: Db) -> dict[str, Any]:
    sid = dbmod.create_chat_session(conn)
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (sid,)).fetchone()
    assert row
    return _row_to_dict(row)


@router.get("/chat/sessions/{session_id}/messages")
def get_session_messages(session_id: int, conn: Db) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in dbmod.get_chat_messages(conn, session_id)]


@router.delete("/chat/sessions/{session_id}")
def delete_session(session_id: int, conn: Db) -> dict[str, str]:
    dbmod.delete_chat_session(conn, session_id)
    return {"ok": "true"}


@router.post("/chat")
def chat_turn(payload: ChatBody, conn: Db) -> dict[str, Any]:
    turns: list[tuple[Literal["user", "assistant"], str]] = [
        (m.role, m.content.strip()) for m in payload.messages
    ]
    if any(not content for _, content in turns):
        raise HTTPException(status_code=400, detail="Empty message content.")
    try:
        reply, html, used, results = run_chat(
            conn,
            turns=turns,
            mode=payload.mode,
            provider_override=payload.provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"reply": reply, "html": html, "provider": used, "search_results": results}


@router.post("/chat/stream")
def chat_stream(payload: ChatBody, conn: Db) -> StreamingResponse:
    """SSE endpoint — emits status events then the final reply."""
    turns: list[tuple[Literal["user", "assistant"], str]] = [
        (m.role, m.content.strip()) for m in payload.messages
    ]
    if any(not content for _, content in turns):
        raise HTTPException(status_code=400, detail="Empty message content.")

    def _generate() -> Generator[str, None, None]:
        early_results: list[dict[str, str]] | None = None
        early_block: str | None = None
        aggregated_results: list[dict[str, str]] = []
        blocks: list[str] = []
        seen_urls: set[str] = set()
        pending_reading_events: list[dict[str, Any]] = []
        process_seq = 0

        def emit_process(
            message: str, *, phase: str = "thinking"
        ) -> Generator[str, None, None]:
            nonlocal process_seq
            process_seq += 1
            payload = {"seq": process_seq, "phase": phase, "message": message}
            yield "event: process\ndata: " + json.dumps(payload) + "\n\n"

        def push_reading(meta: dict[str, Any]) -> None:
            pending_reading_events.append(meta)

        def flush_reading_events() -> Generator[str, None, None]:
            while pending_reading_events:
                evt = pending_reading_events.pop(0)
                yield "event: reading\ndata: " + json.dumps(evt) + "\n\n"
                title = str(evt.get("title") or evt.get("url") or "article")
                status = str(evt.get("status") or "")
                if status == "started":
                    yield from emit_process(
                        f"Reading mode: opening {title}", phase="reading"
                    )
                elif status == "completed":
                    words = evt.get("words")
                    if isinstance(words, int):
                        yield from emit_process(
                            f"Reading mode: extracted {words} words from {title}",
                            phase="reading",
                        )
                    else:
                        yield from emit_process(
                            f"Reading mode: extracted from {title}", phase="reading"
                        )
                else:
                    yield from emit_process(
                        f"Reading mode: skipped {title}", phase="reading"
                    )

        raw_default_level = dbmod.get_setting(conn, dbmod.SETTING_THINKING_LEVEL)
        try:
            default_level = normalize_thinking_level(
                int(raw_default_level) if raw_default_level is not None else None,
                default=2,
            )
        except ValueError:
            default_level = 2
        effective_level = normalize_thinking_level(
            payload.thinking_level, default=default_level
        )

        # Save user's last message if session exists
        if payload.session_id:
            last = payload.messages[-1]
            dbmod.add_chat_message(conn, payload.session_id, last.role, last.content)
            # Auto-title if it's the first message
            msgs = dbmod.get_chat_messages(conn, payload.session_id)
            if len(msgs) == 1:
                title = last.content[:40] + ("..." if len(last.content) > 40 else "")
                dbmod.update_chat_session_title(conn, payload.session_id, title)

        # Phase 1 — Model-driven search planning + optional early search
        if payload.mode == "search" and turns:
            yield (
                "event: status\ndata: "
                + json.dumps(
                    {
                        "phase": "thinking",
                        "message": "Analyzing request & planning research...",
                    }
                )
                + "\n\n"
            )

            last_role, last_content = turns[-1]
            if last_role == "user" and last_content.strip():
                key = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_API_KEY)
                cx = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_CX)
                google_enabled = (
                    dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_SEARCH_ENABLED) or "1"
                ).strip().lower() in {"1", "true", "yes", "on"}
                serpapi_enabled = (
                    dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_SEARCH_ENABLED) or "0"
                ).strip().lower() in {"1", "true", "yes", "on"}
                serpapi_key = dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_API_KEY)
                firecrawl_enabled = (
                    dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED)
                    or "0"
                ).strip().lower() in {"1", "true", "yes", "on"}
                firecrawl_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
                ddg_enabled = (
                    dbmod.get_setting(conn, dbmod.SETTING_DDG_SEARCH_ENABLED) or "0"
                ).strip().lower() in {"1", "true", "yes", "on"}
                has_any_enabled_tool = (
                    (google_enabled and key and cx)
                    or (serpapi_enabled and serpapi_key)
                    or (firecrawl_enabled and firecrawl_key)
                    or ddg_enabled
                )
                if has_any_enabled_tool:
                    from trend_analyzer import reading_tool as _reading_tool
                    from trend_analyzer import search_tool as _search_tool
                    from trend_analyzer.chat_llm import (
                        _run_tools_for_queries,
                        build_fallback_search_queries,
                        suggest_initial_search_queries,
                        suggest_refinement_queries,
                    )

                    def _execute_queries(
                        queries: list[str],
                        num: int,
                    ) -> Generator[str, None, None]:
                        """Run queries via _run_tools_for_queries, emit SSE events,
                        and accumulate into aggregated_results / blocks."""
                        nonlocal process_seq
                        pairs = _run_tools_for_queries(conn, queries, num_per_query=num)
                        for q, res in pairs:
                            # Emit a per-query searching status.
                            tool_names = sorted(
                                {
                                    str(r.get("_tool") or "")
                                    for r in res
                                    if r.get("_tool")
                                }
                            )
                            tool_label = (
                                f" via {', '.join(tool_names)}" if tool_names else ""
                            )
                            yield (
                                "event: status\ndata: "
                                + json.dumps(
                                    {
                                        "phase": "searching",
                                        "query": q,
                                        "message": f"Calling Tool: Web Search{tool_label} (Query: {q})",
                                    }
                                )
                                + "\n\n"
                            )
                            if not res:
                                continue
                            # Deep-read enrichment (reuse existing logic)
                            from trend_analyzer.chat_llm import (
                                _deep_read_config,
                                _is_truthy_setting,
                            )

                            deep_enabled, deep_max = _deep_read_config(conn)
                            if deep_enabled:
                                fc_key_dr = dbmod.get_setting(
                                    conn, dbmod.SETTING_FIRECRAWL_API_KEY
                                )
                                fc_en_dr = _is_truthy_setting(
                                    dbmod.get_setting(
                                        conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED
                                    ),
                                    default=False,
                                )
                                from trend_analyzer import firecrawl_tool as _fc_tool

                                if fc_en_dr and fc_key_dr:
                                    res, _enrich_summary = _fc_tool.enrich_results_with_firecrawl(
                                        res,
                                        fc_key_dr,
                                        max_articles=max(1, deep_max - 1),
                                        excerpt_chars=1500,
                                        on_reading=push_reading,
                                    )
                                else:
                                    res, _enrich_summary = _reading_tool.enrich_results_with_article_excerpts(
                                        res,
                                        max_articles=max(1, deep_max - 1),
                                        excerpt_chars=1500,
                                        on_reading=push_reading,
                                    )
                            yield from flush_reading_events()
                            ctx = _search_tool.format_results_for_prompt(res, q)
                            blk = (
                                f'\n\n<search_results query="{q}">\n{ctx}\n</search_results>'
                                if ctx
                                else ""
                            )
                            if blk:
                                blocks.append(blk)
                            fresh = []
                            for r in res:
                                u = str(r.get("link") or r.get("url") or "").strip()
                                if u and u not in seen_urls:
                                    seen_urls.add(u)
                                    fresh.append(r)
                            aggregated_results.extend(res)
                            if fresh:
                                yield (
                                    "event: sources\ndata: "
                                    + json.dumps({"results": fresh})
                                    + "\n\n"
                                )

                    yield (
                        "event: status\ndata: "
                        + json.dumps(
                            {
                                "phase": "thinking",
                                "message": "Model is deciding what to search...",
                            }
                        )
                        + "\n\n"
                    )
                    try:
                        initial_queries = suggest_initial_search_queries(
                            conn,
                            turns,
                            max_queries=2,
                            provider_override=payload.provider,
                        )
                    except Exception as exc:
                        initial_queries = []
                        yield (
                            "event: status\ndata: "
                            + json.dumps(
                                {
                                    "phase": "thinking",
                                    "message": f"Search planner unavailable ({exc}). Using fallback queries.",
                                }
                            )
                            + "\n\n"
                        )

                    if not initial_queries:
                        initial_queries = build_fallback_search_queries(
                            conn=conn,
                            user_message=last_content,
                            max_queries=2,
                        )

                    yield from _execute_queries(initial_queries, num=6)

                    yield (
                        "event: status\ndata: "
                        + json.dumps(
                            {
                                "phase": "thinking",
                                "message": f"Search complete — {len(aggregated_results)} result(s). Planning response...",
                            }
                        )
                        + "\n\n"
                    )

                    # ── Refinement loop ──────────────────────────────────────
                    combined_results = list(aggregated_results)
                    max_rounds = max(0, effective_level - 1)
                    for rnd in range(max_rounds):
                        if not combined_results:
                            break
                        yield (
                            "event: status\ndata: "
                            + json.dumps(
                                {
                                    "phase": "thinking",
                                    "message": f"Planning refinement {rnd + 1}/{max_rounds}...",
                                }
                            )
                            + "\n\n"
                        )
                        try:
                            refinements = suggest_refinement_queries(
                                conn,
                                turns,
                                combined_results,
                                max_queries=2,
                                provider_override=payload.provider,
                            )
                        except Exception as exc:
                            refinements = []
                            yield (
                                "event: status\ndata: "
                                + json.dumps(
                                    {
                                        "phase": "thinking",
                                        "message": f"Refinement planner unavailable ({exc}). Continuing with current evidence.",
                                    }
                                )
                                + "\n\n"
                            )
                        if not refinements:
                            break
                        prev_len = len(aggregated_results)
                        yield from _execute_queries(refinements, num=5)
                        combined_results.extend(aggregated_results[prev_len:])
                        yield (
                            "event: status\ndata: "
                            + json.dumps(
                                {
                                    "phase": "thinking",
                                    "message": "Refinement complete. Updating plan...",
                                }
                            )
                            + "\n\n"
                        )

                else:
                    yield (
                        "event: status\ndata: "
                        + json.dumps(
                            {
                                "phase": "thinking",
                                "message": "Web search skipped: no enabled search tool is fully configured.",
                            }
                        )
                        + "\n\n"
                    )

        # Phase 2 — synthesizing
        yield (
            "event: status\ndata: "
            + json.dumps(
                {"phase": "thinking", "message": "Synthesizing research results..."}
            )
            + "\n\n"
        )

        try:
            from trend_analyzer.chat_llm import (
                _call_provider_stream,
                _resolve_provider,
                _should_include_html_brief,
                _system_prompt,
                extract_html_brief,
            )

            search_results_override = aggregated_results or early_results
            search_block_override = "".join(blocks) if blocks else early_block

            last_user_msg = next((c for r, c in reversed(turns) if r == "user"), "")
            # In analysis/search mode always include the HTML brief (sentinel "");
            # in chat mode use the heuristic against the actual user message.
            _effective_mode = (
                "analysis" if payload.mode in ("analysis", "search") else "chat"
            )
            include_html_brief = _should_include_html_brief(
                "" if _effective_mode == "analysis" else last_user_msg
            )
            has_search_results: bool | None = (
                bool(search_results_override)
                if payload.mode in ("analysis", "search")
                else None
            )
            system = _system_prompt(
                conn,
                "analysis" if payload.mode in ("analysis", "search") else "chat",
                include_visual_caps=True,
                include_html_brief=include_html_brief,
                has_search_results=has_search_results,
            ) + (search_block_override or "")
            used, key = _resolve_provider(conn, payload.provider)

            accumulated = ""
            for token_text in _call_provider_stream(conn, used, key, system, turns):
                accumulated += token_text
                yield "event: token\ndata: " + json.dumps({"text": token_text}) + "\n\n"

            reply, html = extract_html_brief(accumulated)

            if payload.session_id:
                dbmod.add_chat_message(conn, payload.session_id, "assistant", reply)

            yield (
                "event: done\ndata: "
                + json.dumps({"reply": reply, "html": html, "provider": used})
                + "\n\n"
            )
        except ValueError as exc:
            yield "event: error\ndata: " + json.dumps({"detail": str(exc)}) + "\n\n"
        except RuntimeError as exc:
            yield "event: error\ndata: " + json.dumps({"detail": str(exc)}) + "\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
def api_status(request: Request) -> dict[str, Any]:
    sched = getattr(request.app.state, "scheduler", None)
    sc = getattr(sched, "_sched", None) if sched else None
    return {
        "db_path": str(db_path()),
        "data_dir": str(data_dir()),
        "scheduler_running": sc is not None,
        "scheduler_jobs": getattr(sched, "job_count", 0) if sched else 0,
    }


class CompanyPatch(BaseModel):
    name: str | None = None
    sector: str | None = None
    region: str | None = None
    products: str | None = None
    notes: str | None = None


@router.get("/company")
def get_company(conn: Db) -> dict[str, Any]:
    row = dbmod.get_company_profile(conn)
    if not row:
        raise HTTPException(status_code=404)
    return _row_to_dict(row)


@router.patch("/company")
def patch_company(payload: CompanyPatch, conn: Db) -> dict[str, Any]:
    dbmod.update_company_profile(
        conn,
        name=payload.name,
        sector=payload.sector,
        region=payload.region,
        products=payload.products,
        notes=payload.notes,
    )
    row = dbmod.get_company_profile(conn)
    assert row
    return _row_to_dict(row)


@router.get("/instructions")
def get_instructions(conn: Db) -> dict[str, Any]:
    row = dbmod.get_user_instructions(conn)
    assert row
    return _row_to_dict(row)


class InstructionsBody(BaseModel):
    body: str = ""


@router.put("/instructions")
def put_instructions(payload: InstructionsBody, conn: Db) -> dict[str, Any]:
    dbmod.set_user_instructions(conn, payload.body)
    row = dbmod.get_user_instructions(conn)
    assert row
    return _row_to_dict(row)


@router.get("/schedules")
def list_schedules_http(conn: Db) -> list[dict[str, Any]]:
    return [_schedule_decode(r) for r in dbmod.list_schedules(conn)]


class ScheduleCreate(BaseModel):
    frequency: Literal["hourly", "daily", "weekly", "once"]
    time_points: list[str] = Field(..., min_length=1)
    weekdays: list[int] = Field(default_factory=list)
    label: str = ""
    timezone: str = "local"
    enabled: bool = True


@router.post("/schedules", status_code=201)
def create_schedule(
    payload: ScheduleCreate, conn: Db, request: Request
) -> dict[str, Any]:
    if payload.frequency == "weekly" and not payload.weekdays:
        raise HTTPException(
            status_code=400,
            detail="weekly schedules require at least one weekday (0=Mon … 6=Sun)",
        )
    _validate_weekdays(payload.weekdays)
    _validate_time_points(payload.time_points)
    sid = dbmod.add_schedule(
        conn,
        frequency=payload.frequency,
        time_points=payload.time_points,
        weekdays=payload.weekdays,
        label=payload.label or None,
        timezone_name=payload.timezone,
        enabled=payload.enabled,
    )
    row = dbmod.schedule_row(conn, sid)
    assert row
    _reload_scheduler_safe(request.app)
    return _schedule_decode(row)


class SchedulePatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    frequency: Literal["hourly", "daily", "weekly", "once"] | None = None
    time_points: list[str] | None = None
    weekdays: list[int] | None = None
    timezone: str | None = None


@router.patch("/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: int, payload: SchedulePatch, conn: Db, request: Request
):
    row = dbmod.schedule_row(conn, schedule_id)
    if not row:
        raise HTTPException(status_code=404)
    fields: dict[str, Any] = {}
    if payload.enabled is not None:
        fields["enabled"] = payload.enabled
    if payload.label is not None:
        fields["label"] = payload.label
    if payload.frequency is not None:
        fields["frequency"] = payload.frequency
    if payload.time_points is not None:
        fields["time_points"] = payload.time_points
    if payload.weekdays is not None:
        fields["weekdays"] = payload.weekdays
    if payload.timezone is not None:
        fields["timezone"] = payload.timezone
    fq = payload.frequency if payload.frequency is not None else row["frequency"]
    wk = (
        payload.weekdays
        if payload.weekdays is not None
        else json.loads(row["weekdays"] or "[]")
    )
    _validate_weekdays(wk)
    if fq == "weekly" and not wk:
        raise HTTPException(status_code=400, detail="weekly schedules need weekdays")
    if payload.time_points is not None:
        _validate_time_points(payload.time_points)
    if fields:
        dbmod.update_schedule(conn, schedule_id, **fields)
    row = dbmod.schedule_row(conn, schedule_id)
    assert row
    _reload_scheduler_safe(request.app)
    return _schedule_decode(row)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, conn: Db, request: Request) -> dict[str, str]:
    if not dbmod.schedule_row(conn, schedule_id):
        raise HTTPException(status_code=404)
    dbmod.delete_schedule(conn, schedule_id)
    _reload_scheduler_safe(request.app)
    return {"ok": "true"}


class RunBody(BaseModel):
    schedule_id: int | None = None
    thinking_level: int | None = Field(default=None, ge=1, le=5)


@router.post("/research/run-once")
def research_run(payload: RunBody, conn: Db) -> dict[str, Any]:
    if payload.schedule_id is not None:
        if not dbmod.schedule_row(conn, payload.schedule_id):
            raise HTTPException(status_code=404, detail="Unknown schedule")
    # Optional override for manual "Run now" requests.
    if payload.thinking_level is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_THINKING_LEVEL,
            str(normalize_thinking_level(payload.thinking_level)),
        )
    try:
        summary = run_research_pass(conn, payload.schedule_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"summary": summary}


@router.post("/research/run-once/stream")
def research_run_stream(payload: RunBody, conn: Db) -> StreamingResponse:
    if payload.schedule_id is not None:
        if not dbmod.schedule_row(conn, payload.schedule_id):
            raise HTTPException(status_code=404, detail="Unknown schedule")
    if payload.thinking_level is not None:
        dbmod.set_setting(
            conn,
            dbmod.SETTING_THINKING_LEVEL,
            str(normalize_thinking_level(payload.thinking_level)),
        )

    def _generate() -> Generator[str, None, None]:
        events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        finished = threading.Event()
        cancelled = threading.Event()
        process_seq = 0

        def emit_process(message: str, *, phase: str = "thinking") -> None:
            nonlocal process_seq
            process_seq += 1
            events.put(
                ("process", {"seq": process_seq, "phase": phase, "message": message})
            )

        def progress_cb(event_type: str, payload_obj: dict[str, Any]) -> None:
            if cancelled.is_set():
                raise RuntimeError("Run cancelled by user.")
            if event_type == "status":
                msg = str(payload_obj.get("message") or "").strip()
                if msg:
                    emit_process(msg, phase=str(payload_obj.get("phase") or "thinking"))
            elif event_type == "reading":
                title = str(
                    payload_obj.get("title") or payload_obj.get("url") or "article"
                )
                status = str(payload_obj.get("status") or "")
                if status == "started":
                    emit_process(f"Reading mode: opening {title}", phase="reading")
                elif status == "completed":
                    words = payload_obj.get("words")
                    if isinstance(words, int):
                        emit_process(
                            f"Reading mode: extracted {words} words from {title}",
                            phase="reading",
                        )
                    else:
                        emit_process(
                            f"Reading mode: extracted from {title}", phase="reading"
                        )
                else:
                    emit_process(f"Reading mode: skipped {title}", phase="reading")
            events.put((event_type, payload_obj))

        def worker() -> None:
            try:
                summary = run_research_pass(
                    conn,
                    payload.schedule_id,
                    progress_cb=progress_cb,
                    cancel_check=cancelled.is_set,
                )
                if cancelled.is_set():
                    events.put(
                        (
                            "error",
                            {"detail": "Run cancelled by user.", "status_code": 499},
                        )
                    )
                    return
                events.put(("done", {"summary": summary}))
            except ValueError as exc:
                events.put(("error", {"detail": str(exc), "status_code": 400}))
            except RuntimeError as exc:
                events.put(("error", {"detail": str(exc), "status_code": 502}))
            except Exception as exc:
                events.put(("error", {"detail": str(exc), "status_code": 500}))
            finally:
                finished.set()

        threading.Thread(target=worker, daemon=True).start()
        try:
            while not (finished.is_set() and events.empty()):
                try:
                    evt_type, evt_payload = events.get(timeout=0.25)
                except queue.Empty:
                    continue
                yield f"event: {evt_type}\ndata: {json.dumps(evt_payload)}\n\n"
        finally:
            cancelled.set()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/scheduler/reload")
def scheduler_reload(request: Request) -> dict[str, Any]:
    sched = getattr(request.app.state, "scheduler", None)
    if not sched:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    n = sched.reload_jobs_now()
    return {"scheduler_jobs": n}


@router.get("/runs")
def list_runs(conn: Db, limit: int = 50) -> list[dict[str, Any]]:
    rows = dbmod.list_recent_runs(conn, limit=min(limit, 200))
    return [_row_to_dict(r) for r in rows]


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, conn: Db) -> dict[str, str]:
    if dbmod.delete_run(conn, run_id) == 0:
        raise HTTPException(status_code=404)
    return {"ok": "true"}


class HistoryDeleteBody(BaseModel):
    run_ids: list[int] = Field(default_factory=list)
    trend_ids: list[int] = Field(default_factory=list)
    analysis_ids: list[int] = Field(default_factory=list)
    prediction_ids: list[int] = Field(default_factory=list)


@router.post("/history/delete")
def delete_history_bulk(payload: HistoryDeleteBody, conn: Db) -> dict[str, Any]:
    """
    Bulk-delete a set of history items in a single atomic transaction.
    Also cascades to trend_reports that share the same run_ids.
    """
    counts = dbmod.delete_history_items(
        conn,
        run_ids=payload.run_ids or None,
        trend_ids=payload.trend_ids or None,
        analysis_ids=payload.analysis_ids or None,
        prediction_ids=payload.prediction_ids or None,
    )
    total = sum(counts.values())
    return {"ok": "true", "deleted": counts, "total": total}


def _reload_scheduler_safe(app) -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched:
        try:
            sched.reload_jobs_now()
        except Exception:
            pass


# ── Trends ────────────────────────────────────────────────────────────────────


class TrendCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    summary: str = ""
    category: str = "general"
    source_url: str | None = None
    relevance: int = Field(default=50, ge=0, le=100)


@router.get("/trends")
def list_trends(conn: Db, limit: int = 10) -> list[dict[str, Any]]:
    rows = dbmod.list_recent_trends(conn, limit=min(limit, 100))
    return [_row_to_dict(r) for r in rows]


@router.post("/trends", status_code=201)
def create_trend(payload: TrendCreate, conn: Db) -> dict[str, Any]:
    tid = dbmod.add_trend(
        conn,
        title=payload.title,
        summary=payload.summary,
        category=payload.category,
        source_url=payload.source_url,
        relevance=payload.relevance,
    )
    row = conn.execute(
        "SELECT * FROM discovered_trends WHERE id = ?", (tid,)
    ).fetchone()
    assert row
    return _row_to_dict(row)


@router.delete("/trends/{trend_id}")
def delete_trend(trend_id: int, conn: Db) -> dict[str, str]:
    if dbmod.delete_trend(conn, trend_id) == 0:
        raise HTTPException(status_code=404)
    return {"ok": "true"}


# ── AI analyses ───────────────────────────────────────────────────────────────


class AnalysisCreate(BaseModel):
    headline: str = Field(..., min_length=1, max_length=300)
    recommendation: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    trend_id: int | None = None


@router.get("/analyses")
def list_analyses(conn: Db, limit: int = 10) -> list[dict[str, Any]]:
    rows = dbmod.list_recent_analyses(conn, limit=min(limit, 100))
    return [_row_to_dict(r) for r in rows]


@router.get("/predictions")
def list_predictions(conn: Db, limit: int = 10) -> list[dict[str, Any]]:
    rows = dbmod.list_recent_predictions(conn, limit=min(limit, 100))
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        try:
            d["sources"] = json.loads(d.get("sources") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["sources"] = []
        out.append(d)
    return out


@router.delete("/predictions/{prediction_id}")
def delete_prediction(prediction_id: int, conn: Db) -> dict[str, str]:
    if dbmod.delete_prediction(conn, prediction_id) == 0:
        raise HTTPException(status_code=404)
    return {"ok": "true"}


@router.post("/analyses", status_code=201)
def create_analysis(payload: AnalysisCreate, conn: Db) -> dict[str, Any]:
    if payload.trend_id is not None:
        exists = conn.execute(
            "SELECT 1 FROM discovered_trends WHERE id = ?", (payload.trend_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="trend_id not found")
    aid = dbmod.add_analysis(
        conn,
        headline=payload.headline,
        recommendation=payload.recommendation,
        confidence=payload.confidence,
        trend_id=payload.trend_id,
    )
    row = conn.execute(
        """SELECT a.*, t.title as trend_title FROM ai_analyses a
           LEFT JOIN discovered_trends t ON t.id = a.trend_id WHERE a.id = ?""",
        (aid,),
    ).fetchone()
    assert row
    return _row_to_dict(row)


@router.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: int, conn: Db) -> dict[str, str]:
    if dbmod.delete_analysis(conn, analysis_id) == 0:
        raise HTTPException(status_code=404)
    return {"ok": "true"}


# GET /api/trend-reports — list stored reports for the UI
@router.get("/trend-reports")
def list_trend_reports(
    conn: Db,
    limit: int = 50,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    rows = dbmod.list_trend_reports(
        conn,
        limit=min(limit, 200),
        severity_filter=severity or None,
    )
    return [dbmod.trend_report_to_dict(r) for r in rows]


# DELETE /api/trend-reports — wipe ALL reports and their associated run data
@router.delete("/trend-reports")
def delete_all_trend_reports(conn: Db) -> dict[str, Any]:
    """
    Delete all trend reports and every piece of data that belongs to the same
    runs: discovered_trends, ai_analyses, ai_predictions, and research_runs.
    Settings, schedules, business profile, and chat history are kept.
    """
    # Collect every run_id referenced by a trend_report so we can cascade.
    run_ids: list[int] = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT run_id FROM trend_reports WHERE run_id IS NOT NULL"
        ).fetchall()
    ]
    counts: dict[str, int] = {}
    with dbmod.transaction(conn):
        cur = conn.execute("DELETE FROM trend_reports")
        counts["trend_reports"] = cur.rowcount
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", ("trend_reports",))
        if run_ids:
            ph = ",".join("?" * len(run_ids))
            counts["ai_predictions"] = conn.execute(
                f"DELETE FROM ai_predictions WHERE run_id IN ({ph})",
                run_ids,  # noqa: S608
            ).rowcount
            counts["ai_analyses"] = conn.execute(
                f"DELETE FROM ai_analyses WHERE run_id IN ({ph})",
                run_ids,  # noqa: S608
            ).rowcount
            counts["discovered_trends"] = conn.execute(
                f"DELETE FROM discovered_trends WHERE run_id IN ({ph})",
                run_ids,  # noqa: S608
            ).rowcount
            counts["research_runs"] = conn.execute(
                f"DELETE FROM research_runs WHERE id IN ({ph})",
                run_ids,  # noqa: S608
            ).rowcount
        else:
            counts.update(
                {
                    "ai_predictions": 0,
                    "ai_analyses": 0,
                    "discovered_trends": 0,
                    "research_runs": 0,
                }
            )
    total = sum(counts.values())
    return {"ok": "true", "deleted": counts, "total": total}


# GET /api/trend-reports/{id} — single report for drill-down
@router.get("/trend-reports/{report_id}")
def get_trend_report(report_id: int, conn: Db) -> dict[str, Any]:
    row = dbmod.get_trend_report(conn, report_id)
    if not row:
        raise HTTPException(status_code=404)
    return dbmod.trend_report_to_dict(row)


# GET /api/trend-reports/{id}/predictions — predictions belonging to the same run
@router.get("/trend-reports/{report_id}/predictions")
def get_trend_report_predictions(report_id: int, conn: Db) -> list[dict[str, Any]]:
    row = dbmod.get_trend_report(conn, report_id)
    if not row:
        raise HTTPException(status_code=404)
    report = dbmod.trend_report_to_dict(row)
    run_id = report.get("run_id")
    if run_id is None:
        return []
    rows = conn.execute(
        "SELECT * FROM ai_predictions WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        try:
            d["sources"] = json.loads(d.get("sources") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["sources"] = []
        out.append(d)
    return out


# GET /api/dashboard — summary stats for the dashboard header
@router.get("/dashboard")
def get_dashboard(conn: Db) -> dict[str, Any]:
    return dbmod.get_dashboard_stats(conn)


# DELETE /api/trend-reports/{id}
@router.delete("/trend-reports/{report_id}")
def delete_trend_report(report_id: int, conn: Db) -> dict[str, str]:
    if not dbmod.get_trend_report(conn, report_id):
        raise HTTPException(status_code=404)
    dbmod.delete_trend_report(conn, report_id)
    return {"ok": "true"}


@router.delete("/research-data")
def purge_research_data(conn: Db, request: Request) -> dict[str, Any]:
    """
    Wipes all research-generated data (runs, trends, analyses, predictions,
    trend reports, chat sessions/messages) while keeping settings, business
    profile, instructions, and schedules intact.
    """
    counts = dbmod.purge_research_data(conn)
    # Reload scheduler so stale job references are cleared.
    _reload_scheduler_safe(request.app)
    total = sum(counts.values())
    return {"ok": "true", "deleted": counts, "total": total}
