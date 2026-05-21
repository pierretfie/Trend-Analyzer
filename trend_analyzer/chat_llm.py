"""
chat.py — Trend Analyzer AI engine
====================================
Responsibilities:
  - Build context-rich system prompts from business profile + instructions
  - Route to OpenAI or Gemini providers
  - Inject live search results in search mode
  - Support proactive trend analysis via run_trend_analysis()
  - Return structured TrendReport objects for storage and UI rendering

Companion files this module depends on:
  trend_analyzer/db.py          — all DB read/write helpers + settings keys
  trend_analyzer/search_tool.py — google_search(), format_results_for_prompt()
  trend_analyzer/news_tool.py   — fetch_news() using NewsAPI or RSS (NEW)
  trend_analyzer/scheduler.py   — APScheduler jobs that call run_trend_analysis() (NEW)
  trend_analyzer/renderer.py    — HTML/CSS trend report rendering (NEW)
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Literal

from trend_analyzer import db as dbmod
from trend_analyzer import (
    duckduckgo_tool,
    firecrawl_tool,
    local_llm,
    reading_tool,
    search_tool,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ChatMode = Literal["chat", "analysis", "search"]
ChatRole = Literal["user", "assistant"]
ProviderName = Literal["openai", "gemini", "local"]
ProviderOverride = Literal["openai", "gemini", "local", "auto"] | None

OPENAI_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"


@dataclass
class TrendReport:
    """
    Structured output from a proactive trend analysis run.
    Stored in DB and rendered as HTML by renderer.py.
    """

    timestamp: str  # ISO-8601
    query_used: str  # what was searched
    raw_results: list[dict[str, str]]  # search hits
    summary: str  # LLM narrative
    trend_signals: list[str]  # bullet-point signals detected
    recommended_actions: list[str]  # specific advice for this business
    severity: Literal["low", "medium", "high", "critical"] = "low"
    trend_signal_meta: list[dict[str, Any]] = field(
        default_factory=list
    )  # per-signal {text, relevance, source_url}
    sources: list[str] = field(default_factory=list)  # URLs cited
    predictions: list[dict[str, Any]] = field(default_factory=list)
    visualisation: str = ""


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(raw or e.reason) from e
        raise RuntimeError(_extract_api_error(err)) from e


def _extract_api_error(body: dict[str, Any]) -> str:
    if "error" in body and isinstance(body["error"], dict):
        e = body["error"]
        if isinstance(e.get("message"), str):
            return e["message"]
    return json.dumps(body)[:800]


# ---------------------------------------------------------------------------
# Provider resolution (single source of truth)
# ---------------------------------------------------------------------------


def _resolve_gemini_model(conn: sqlite3.Connection) -> str:
    raw = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_MODEL)
    return raw if raw in dbmod.GEMINI_MODELS else dbmod.GEMINI_MODEL_DEFAULT


def _resolve_provider(
    conn: sqlite3.Connection,
    override: ProviderOverride,
) -> tuple[ProviderName, str]:
    """
    Returns (provider, credential).
    For openai/gemini, credential is the API key.
    For local, credential is the model file path.
    Normalises 'auto'/None here so callers never have to.
    Priority: explicit override → user preference setting → first available key.
    """
    if override in ("auto", None):
        override = None

    oa = dbmod.get_setting(conn, dbmod.SETTING_OPENAI_API_KEY)
    gm = dbmod.get_setting(conn, dbmod.SETTING_GEMINI_API_KEY)
    local_path = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_MODEL_PATH)

    if override == "openai":
        if not oa:
            raise ValueError(
                "OpenAI API key is not configured. Add it under Model setup."
            )
        return "openai", oa
    if override == "gemini":
        if not gm:
            raise ValueError(
                "Gemini API key is not configured. Add it under Model setup."
            )
        return "gemini", gm
    if override == "local":
        if not local_path:
            raise ValueError(
                "Local model path is not configured. Set it under Model setup."
            )
        return "local", local_path

    pref = dbmod.get_setting(conn, dbmod.SETTING_LLM_PROVIDER)
    if pref == "openai" and oa:
        return "openai", oa
    if pref == "gemini" and gm:
        return "gemini", gm
    if pref == "local" and local_path:
        return "local", local_path
    if oa:
        return "openai", oa
    if gm:
        return "gemini", gm
    if local_path:
        return "local", local_path

    raise ValueError(
        "No LLM configured. Add an OpenAI or Gemini key, or set a local model path "
        "under Model setup."
    )


# ---------------------------------------------------------------------------
# LLM call wrappers
# ---------------------------------------------------------------------------


def _openai_messages(
    system: str, turns: list[tuple[ChatRole, str]]
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [{"role": "system", "content": system}]
    for role, content in turns:
        out.append({"role": role, "content": content})
    return out


def call_openai(api_key: str, system: str, turns: list[tuple[ChatRole, str]]) -> str:
    payload = {
        "model": OPENAI_MODEL,
        "messages": _openai_messages(system, turns),
        # Lower temperature reduces rambling and "AI-y" filler.
        "temperature": 0.2,
    }
    data = _http_post_json(
        OPENAI_URL,
        payload,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise RuntimeError("Unexpected OpenAI response shape.")
    content = (choices[0].get("message") or {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Empty reply from OpenAI.")
    return content.strip()


def call_gemini(
    api_key: str,
    system: str,
    turns: list[tuple[ChatRole, str]],
    model: str,
) -> str:
    contents = [
        {
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": content}],
        }
        for role, content in turns
    ]
    url = (
        f"{GEMINI_BASE}{model}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    data = _http_post_json(
        url,
        {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "temperature": 0.2,
            },
        },
    )
    cands = data.get("candidates")
    if not cands or not isinstance(cands, list):
        raise RuntimeError("Unexpected Gemini response shape.")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "\n".join(
        p["text"]
        for p in parts
        if isinstance(p, dict) and isinstance(p.get("text"), str)
    ).strip()
    if not text:
        raise RuntimeError("Empty reply from Gemini.")
    return text


def _local_n_ctx(conn: sqlite3.Connection) -> int:
    raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_CTX)
    try:
        return max(512, int(raw)) if raw else 4096
    except ValueError:
        return 4096


def _local_n_gpu_layers(conn: sqlite3.Connection) -> int:
    raw = dbmod.get_setting(conn, dbmod.SETTING_LOCAL_N_GPU_LAYERS)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def _call_provider(
    conn: sqlite3.Connection,
    provider: ProviderName,
    key: str,
    system: str,
    turns: list[tuple[ChatRole, str]],
) -> str:
    """Single dispatch — no duplicated model-resolution logic."""
    if provider == "openai":
        return call_openai(key, system, turns)
    if provider == "local":
        n_ctx = _local_n_ctx(conn)
        n_gpu = _local_n_gpu_layers(conn)
        return local_llm.call_local(key, system, turns, n_ctx=n_ctx, n_gpu_layers=n_gpu)
    return call_gemini(key, system, turns, _resolve_gemini_model(conn))


def call_openai_stream(
    api_key: str, system: str, turns: list[tuple[ChatRole, str]]
) -> Generator[str, None, None]:
    """Yield text token chunks from OpenAI streaming API."""
    import http.client
    import ssl

    payload = json.dumps(
        {
            "model": OPENAI_MODEL,
            "messages": _openai_messages(system, turns),
            "temperature": 0.2,
            "stream": True,
        }
    ).encode("utf-8")
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("api.openai.com", context=ctx, timeout=120)
    try:
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        resp = conn.getresponse()
        if resp.status != 200:
            body = resp.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI stream error {resp.status}: {body[:400]}")
        buf = b""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line or line == b"data: [DONE]":
                    continue
                if line.startswith(b"data: "):
                    try:
                        obj = json.loads(line[6:])
                        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield text
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
    finally:
        conn.close()


def call_gemini_stream(
    api_key: str,
    system: str,
    turns: list[tuple[ChatRole, str]],
    model: str,
) -> Generator[str, None, None]:
    """Yield text token chunks from Gemini streaming API."""
    import http.client
    import ssl
    import urllib.parse as _up

    contents = [
        {
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": content}],
        }
        for role, content in turns
    ]
    payload = json.dumps(
        {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.2},
        }
    ).encode("utf-8")
    path = f"/v1beta/models/{model}:streamGenerateContent?alt=sse&key={_up.quote(api_key, safe='')}"
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(
        "generativelanguage.googleapis.com", context=ctx, timeout=120
    )
    try:
        conn.request(
            "POST",
            path,
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        if resp.status != 200:
            body = resp.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini stream error {resp.status}: {body[:400]}")
        buf = b""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                if line.startswith(b"data: "):
                    try:
                        obj = json.loads(line[6:])
                        parts = (
                            (obj.get("candidates") or [{}])[0].get("content") or {}
                        ).get("parts") or []
                        for p in parts:
                            if isinstance(p, dict) and isinstance(p.get("text"), str):
                                yield p["text"]
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
    finally:
        conn.close()


def _call_provider_stream(
    conn: sqlite3.Connection,
    provider: ProviderName,
    key: str,
    system: str,
    turns: list[tuple[ChatRole, str]],
) -> Generator[str, None, None]:
    """Stream token chunks from the appropriate provider."""
    if provider == "openai":
        yield from call_openai_stream(key, system, turns)
    elif provider == "local":
        n_ctx = _local_n_ctx(conn)
        n_gpu = _local_n_gpu_layers(conn)
        yield from local_llm.call_local_stream(
            key, system, turns, n_ctx=n_ctx, n_gpu_layers=n_gpu
        )
    else:
        yield from call_gemini_stream(key, system, turns, _resolve_gemini_model(conn))


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _business_context(conn: sqlite3.Connection) -> str:
    row = dbmod.get_company_profile(conn)
    if not row:
        return ""
    parts = []
    for label, key in (
        ("Name", "name"),
        ("Sector", "sector"),
        ("Region", "region"),
        ("Products & services", "products"),
        ("Notes", "notes"),
    ):
        v = str(dict(row).get(key) or "").strip()
        if v:
            parts.append(f"{label}: {v}")
    return "\n".join(parts)


def _instructions_context(conn: sqlite3.Connection) -> str:
    row = dbmod.get_user_instructions(conn)
    if not row:
        return ""
    # sqlite3.Row behaves like a mapping via row["col"], but it doesn't
    # implement .get(). Use safe access to avoid runtime crashes.
    try:
        body = row["body"]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        body = ""
    return str(body or "").strip()


def _should_include_visual_caps(text: str) -> bool:
    # Always include visual capabilities for analysis — visuals are the default.
    return True


def _should_include_html_brief(text: str) -> bool:
    """
    Heuristic: include an HTML visual brief whenever the response would benefit
    from a structured visual layout — trends, analysis, data, comparisons, etc.
    Defaults to True for analysis/search mode (caller sets text="" to force True).
    """
    # Empty string sentinel: always include (used by analysis mode)
    if not text:
        return True
    t = text.lower()
    # Exclude purely casual / conversational messages
    casual = len(t) <= 60 and not any(
        k in t
        for k in (
            "trend",
            "market",
            "data",
            "analysis",
            "forecast",
            "risk",
            "growth",
            "revenue",
            "compet",
            "price",
            "rate",
            "sector",
            "industry",
            "outlook",
            "impact",
            "signal",
            "report",
        )
    )
    if casual:
        return False
    return True


def extract_html_brief(raw: str) -> tuple[str, str]:
    """
    Extract a fenced ```html ... ``` block from an LLM reply.
    Returns (reply_without_html_block, html_fragment).
    """
    text = (raw or "").strip()
    if not text:
        return "", ""

    m = re.search(r"```html\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if m:
        html = m.group(1).strip()
        before = text[: m.start()].rstrip()
        after = text[m.end() :].lstrip()
        cleaned = "\n\n".join([p for p in (before, after) if p]).strip()
        return cleaned, html

    # Fallback: if the model omitted fences but produced raw HTML, salvage it.
    tag = re.search(r"(?is)(<div\b|<section\b|<main\b|<article\b|<style\b)", text)
    if tag:
        before = text[: tag.start()].rstrip()
        html = text[tag.start() :].strip()
        return before, html

    return text, ""


def _trend_watch_context(conn: sqlite3.Connection) -> str:
    """
    Returns a formatted list of the business's monitored trend topics.
    Stored in DB as a JSON list under the SETTING_TREND_TOPICS key (NEW setting).
    Example: ["fuel prices", "crude oil", "OPEC", "Kenya energy sector"]
    """
    raw = dbmod.get_setting(conn, dbmod.SETTING_TREND_TOPICS)
    if not raw:
        return ""
    try:
        topics: list[str] = json.loads(raw)
        if topics:
            return "Monitored topics: " + ", ".join(topics)
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------


def _system_prompt(
    conn: sqlite3.Connection,
    mode: ChatMode,
    *,
    include_visual_caps: bool,
    include_html_brief: bool,
    has_search_results: bool | None = None,
) -> str:
    """
    Assembles the system prompt from modular sections.
    Sections are only included when they have real content — no placeholder strings.
    """
    dc = _current_date_context()
    sections: list[str] = []

    # --- Core identity ---
    sections.append(
        "You are Trend Analyzer. "
        "You analyze market trends and explain what they mean for the business. "
        "Focus on decisions: what changed, why it matters, and what to do next."
    )

    mode_label = "analysis" if mode in {"analysis", "search"} else "chat"

    # --- Mode-specific behaviour ---
    if mode_label == "analysis":
        sections.append(
            f"Today is {dc['date']} ({dc['day_of_week']}, {dc['quarter']}). "
            f"Current month: {dc['month_year']}. You are operating in analysis/search mode.\n"
            "Structured search results are provided below inside <search_results> tags.\n"
            "Rules:\n"
            "1. Treat search results as your primary source for current facts, prices, and events.\n"
            "2. When citing evidence, use plain source URLs in text (e.g. `(source: https://...)`).\n"
            "3. If results are missing or insufficient, briefly state that evidence is limited.\n"
            "4. Do not contradict a result unless you have strong evidence it is wrong.\n"
            "5. Prefer recent results over older ones when they conflict.\n"
            "6. Provide a natural, conversational, and highly readable response. Weave the insights together fluidly.\n"
            "7. Ensure you still provide concrete business impact and actionable next steps where appropriate, but integrate them naturally into the dialogue rather than using rigid templates."
        )

        # When Google search is unavailable, force the model to avoid numbers/hallucination.
        if has_search_results is False:
            sections.append(
                "Search data status: NO search results were available for this request.\n"
                "In this case:\n"
                "1. Do NOT provide prices, dates, percentages, or any numbers.\n"
                "2. If a chart/graph is requested, include only an empty chart JSON (e.g. `data: []`).\n"
                "3. Use only business-safe guidance: what to monitor, who should act, and next steps.\n"
                "4. Keep the reply concise and practical."
            )

        sections.append(
            "VISUAL OUTPUT — REQUIRED:\n"
            "Every analysis response MUST include at least one visual. Choose the most appropriate:\n"
            "\n"
            "A) DATA CHART (preferred for numeric trends, comparisons, time-series, rankings):\n"
            "   Emit a fenced ```json block with this shape:\n"
            "   {\n"
            '     "type": "bar" | "line" | "area" | "pie" | "doughnut",\n'
            '     "title": "...",\n'
            '     "data": [...],\n'
            '     "xKey": "...",\n'
            '     "yKey": "..."   // or "series": [{"key": ..., "label": ...}] for multi-series\n'
            "   }\n"
            "   Good triggers: price movements, growth rates, market-share splits, competitor comparisons,\n"
            "   forecast ranges, adoption curves, risk scores, survey results.\n"
            "\n"
            "B) MERMAID DIAGRAM (preferred for flows, timelines, relationships, org-charts):\n"
            "   Emit a fenced ```mermaid block.\n"
            "   Good triggers: supply chains, decision trees, product roadmaps, event timelines,\n"
            "   competitive landscapes, regulatory flows.\n"
            "\n"
            "RULES:\n"
            "- Default to a chart when numeric data exists in the search results.\n"
            "- Use a mermaid diagram when relationships or sequences are clearer than numbers.\n"
            "- You MAY include both if the response covers distinct aspects (e.g. a trend chart + a flow diagram).\n"
            "- Never invent datapoints. If source data is missing or uncertain, still include the visual\n"
            '  but use the real figures you have and label uncertain estimates clearly (e.g. "est.").\n'
            "- Place the visual(s) naturally within the prose — after the section they illustrate.\n"
        )

        if include_html_brief:
            sections.append(
                "HTML VISUAL BRIEF — REQUIRED FOR THIS RESPONSE:\n"
                "Append a polished HTML brief after the main prose. Return it fenced exactly as:\n"
                "```html\n"
                "<div>...</div>\n"
                "```\n"
                "The brief must contain ALL of the following that are relevant:\n"
                "- KPI / metric cards (key numbers, rates, prices with deltas and directional arrows)\n"
                "- Ranked insight cards (trend or signal title, severity badge, 1-line impact, source link)\n"
                "- A 90-day action table (action | owner | priority | deadline)\n"
                "- A confidence / data-quality note at the foot\n"
                "Rules:\n"
                '- Inline CSS only (style="...") or a single <style> tag at the top of the block.\n'
                "- Dark-theme palette: background #0f172a, cards #1e293b, accent #6366f1, text #e2e8f0.\n"
                "- No JavaScript. No external resources.\n"
                "- Cite sources as <a> links inside the cards.\n"
            )
    else:
        sections.append(
            f"Today is {dc['date']} ({dc['day_of_week']}, {dc['quarter']}). "
            f"Current month: {dc['month_year']}. You are operating in chat mode.\n"
            "Rules:\n"
            "1. Be natural, helpful, and conversational.\n"
            "2. Keep it short and business-focused. No apologies or long explanations.\n"
            "3. If you do not have source-backed facts, state that evidence is limited and give reasonable actions.\n"
            "4. Keep transitions smooth and readable with short paragraphs and concise bullets.\n"
        )

        if include_html_brief:
            sections.append(
                "If the user asks for a dashboard or visual report, append a polished HTML brief at the end "
                "inside a fenced ```html block (inline CSS only, no JavaScript)."
            )

    # --- Business context (omit if empty) ---
    biz = _business_context(conn)
    if biz:
        sections.append(f"Business context:\n{biz}")

    # --- Trend watch topics (omit if none configured) ---
    watch = _trend_watch_context(conn)
    if watch:
        sections.append(watch)

    # --- Standing instructions (omit if empty) ---
    instr = _instructions_context(conn)
    if instr:
        sections.append(f"Standing instructions from the user:\n{instr}")

    # --- Analysis framing for trend mode ---
    sections.append(
        "When presenting trend findings, always include:\n"
        "- What the trend is and where it was detected\n"
        "- Why it matters to this business specifically\n"
        "- Recommended actions, ranked by urgency\n"
        "- Confidence level (high / medium / low) based on source quality\n"
        "Use concrete numbers and timeframes wherever possible.\n"
        "Regional weighting policy:\n"
        "- Allocate roughly 70% of analysis attention to the business region/local market.\n"
        "- Allocate roughly 30% to global/macro drivers that affect the region.\n"
        "- If global and local signals conflict, prioritize local regulatory, tax, price, and demand evidence.\n"
        "- Chronological Priority: Prioritize and list all findings (trends, signals, predictions) starting from the most recent events or data points discovered. Always lead with the newest information."
    )

    # --- Visual Capabilities (chat mode) ---
    # Always appended so the model knows what formats the UI can render.
    if include_visual_caps:
        sections.append(
            "VISUAL CAPABILITIES:\n"
            "The UI can render the following — use them proactively whenever data or structure warrants it:\n"
            "- Data charts: fenced ```json block with keys: type (bar/line/area/pie/doughnut), title, data, xKey, yKey or series.\n"
            "- Diagrams: fenced ```mermaid block for flows, timelines, org-charts, relationships.\n"
            "When presenting any numeric comparison, trend, forecast, or ranking — default to a chart.\n"
            "When presenting a process, timeline, or relationship — default to a mermaid diagram.\n"
            "Safety: never invent datapoints. Use real figures from context; label estimates clearly."
        )

    return "\n\n".join(sections)


def _trend_analysis_system_prompt(conn: sqlite3.Connection) -> str:
    """
    Stricter system prompt used for scheduled/autonomous trend analysis runs.
    Output must be structured JSON so TrendReport can be populated programmatically.
    """
    dc = _current_date_context()
    biz = _business_context(conn)
    watch = _trend_watch_context(conn)
    instr = _instructions_context(conn)

    sections: list[str] = [
        "You are Trend Analyzer running in autonomous analysis mode. "
        f"Today is {dc['date']} ({dc['day_of_week']}, {dc['quarter']}). "
        f"Current month: {dc['month_year']}.",
        "You will receive search results inside <search_results> tags. "
        "Analyse them for trends, signals, and risks relevant to the business below.",
    ]

    if biz:
        sections.append(f"Business context:\n{biz}")
    if watch:
        sections.append(watch)
    if instr:
        sections.append(f"Standing instructions:\n{instr}")
    open_preds = dbmod.list_open_predictions(conn, limit=12)
    if open_preds:
        pred_lines: list[str] = []
        for p in open_preds:
            pred_lines.append(
                f"- [{p['id']}] {p['prediction_text']} | horizon: {p['horizon_value']} {p['horizon_unit']} | "
                f"target_date: {p['target_date']} | confidence: {p['confidence']} | status: {p['status']}"
            )
        sections.append(
            "Existing open predictions (avoid duplicate forecasts and update direction when evidence changes):\n"
            + "\n".join(pred_lines)
        )

    sections.append(
        "Respond ONLY with a valid JSON object — no markdown fences, no preamble. "
        "Schema:\n"
        "{\n"
        '  "summary": "<2-3 sentence plain-English overview>",\n'
        '  "trend_signals": [\n'
        '    {"text": "<signal description>", "relevance": <0-100 integer>, "source_url": "<url most specific to this signal or empty string>"},\n'
        "    ...\n"
        "  ],\n"
        '  "recommended_actions": ["<action 1>", "<action 2>", ...],\n'
        '  "severity": "low" | "medium" | "high" | "critical",\n'
        '  "sources": ["<url1>", "<url2>", ...],\n'
        '  "predictions": [\n'
        "    {\n"
        '      "prediction_text": "<falsifiable forecast>",\n'
        '      "horizon_value": <integer>,\n'
        '      "horizon_unit": "days" | "weeks" | "months" | "years",\n'
        '      "confidence": "low" | "medium" | "high",\n'
        '      "rationale": "<why this forecast follows from evidence>",\n'
        '      "sources": ["<url1>", "<url2>"]\n'
        "    }\n"
        "  ],\n"
        '  "visualisation": {\n'
        '    "type": "mermaid" | "json",\n'
        '    "code": "<diagram or chart code>"\n'
        "  }\n"
        "}\n\n"
        "severity guide:\n"
        "  low      — awareness only, no immediate action needed\n"
        "  medium   — monitor closely, prepare contingencies\n"
        "  high     — act within days\n"
        "  critical — act immediately, significant business impact likely\n\n"
        "trend_signals relevance guide (score each signal independently 0-100):\n"
        "  90-100 — immediate, direct financial or operational impact\n"
        "  70-89  — significant impact within days/weeks, action needed\n"
        "  50-69  — moderate relevance, worth monitoring\n"
        "  30-49  — low relevance, background context only\n"
        "  0-29   — marginal signal, minimal business impact\n"
        "List signals ordered from highest relevance to lowest.\n\n"
        "Regional weighting policy:\n"
        "- Focus about 70% on region-local evidence and business impacts.\n"
        "- Use global signals (~30%) mainly as causal context for local effects.\n"
        "- Prioritize local tax, policy, inflation, FX, supply, and customer-demand changes.\n"
        "Prediction rules:\n"
        "- Every prediction must be evidence-backed by provided search results; no pure guesses.\n"
        "- Prefer 1-3 high-value predictions with clear horizon and falsifiable direction.\n"
        "- Before adding a new prediction, check if an open prediction already covers the same metric/topic.\n"
        "- Chronological Priority: Prioritize and list all findings (trends, signals, predictions) starting from the most recent events or data points discovered. Always lead with what happened 'today' or 'this week' before moving to older context.\n"
        "- Horizon selection guide (choose the shortest horizon the evidence actually supports):\n"
        "    days   -> use when search results show an event, price change, or policy taking effect THIS WEEK or within the next 1-14 days.\n"
        "    weeks  -> use when evidence points to a shift developing over the next 2-8 weeks (e.g. supply tightening, seasonal pattern, scheduled announcement).\n"
        "    months -> use when the evidence supports a sustained trend over 1-12 months.\n"
        "    years  -> use only for structural/long-cycle shifts (infrastructure, regulation, technology adoption).\n"
        "- Always include at least one short-horizon prediction (days or weeks) if the search results contain any near-term price, supply, policy, or demand signal.\n\n"
        "Visualisation rules — REQUIRED:\n"
        "- You MUST always populate the visualisation field. Never leave it empty.\n"
        "- Choose the type that best represents the key insight from this run:\n"
        "    json  → use when you have numeric data: prices, rates, volumes, percentages,\n"
        "            comparisons, rankings, time-series, forecast ranges, or market shares.\n"
        "    mermaid → use when a flow, timeline, sequence, or relationship is clearer\n"
        "              than numbers: supply chains, decision trees, event timelines,\n"
        "              regulatory flows, competitive landscapes.\n"
        "- Default to json whenever numeric evidence exists in the search results.\n"
        "- For json type, code must be a valid JSON string with this shape:\n"
        '    {\\"type\\": \\"bar\\" | \\"line\\" | \\"area\\" | \\"pie\\" | \\"doughnut\\",\n'
        '     \\"title\\": \\"...\\",\n'
        '     \\"data\\": [{\\"label\\": \\"...\\", \\"value\\": <number>}, ...],\n'
        '     \\"xKey\\": \\"label\\", \\"yKey\\": \\"value\\"}\n'
        "- For mermaid type, code must be a valid Mermaid diagram string (no fences).\n"
        "- Never invent datapoints. Use only figures present in the search results.\n"
        "- Label uncertain estimates with (est.) in the data label.\n"
        "- Chart type guide:\n"
        "    bar      → comparisons, rankings, side-by-side price differences\n"
        "    line     → trends over discrete time points (monthly, quarterly)\n"
        "    area     → cumulative values, forecast ranges, volume over time\n"
        "    pie      → proportional breakdown (market share, cost composition)\n"
        "    doughnut → same as pie but emphasises the centre metric"
    )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Search pipeline
# ---------------------------------------------------------------------------


def _current_date_context() -> dict[str, str]:
    """Returns a dict of useful date fragments for prompt and query injection."""
    now = datetime.datetime.now()
    return {
        "date": now.strftime("%Y-%m-%d"),  # 2025-06-14
        "month_year": now.strftime("%B %Y"),  # June 2025
        "year": str(now.year),  # 2025
        "next_year": str(now.year + 1),  # 2026
        "quarter": f"Q{(now.month - 1) // 3 + 1} {now.year}",  # Q2 2025
        "day_of_week": now.strftime("%A"),  # Saturday
    }


def _build_search_query(
    turns: list[tuple[ChatRole, str]],
    biz_context: str,
) -> str:
    """
    Derives a search query from the conversation without an extra LLM round-trip.
    Uses the last user message, capped at 120 chars, optionally enriched with
    the first line of business context (e.g. 'Sector: fuel distribution').
    Always appends the current year so search engines surface recent results.
    """
    last_user = next((c for r, c in reversed(turns) if r == "user"), "").strip()
    dc = _current_date_context()

    if not last_user:
        return f"latest market trends {dc['month_year']}"

    query = last_user[:120].strip()

    # Always anchor the query to the current year unless the user has already
    # included an explicit year or explicitly asked for historical data.
    lower_user = last_user.lower()
    historical_keywords = (
        "last year",
        "in 2023",
        "in 2022",
        "in 2021",
        "history",
        "historical",
    )
    wants_history = any(k in lower_user for k in historical_keywords)
    if not wants_history and dc["year"] not in query and dc["next_year"] not in query:
        # Forward-looking questions get both current and next year.
        if any(
            p in lower_user
            for p in (
                "next 12 months",
                "next year",
                "coming year",
                "outlook",
                "forecast",
                "prediction",
            )
        ):
            query = f"{query} {dc['year']} {dc['next_year']}".strip()
        else:
            query = f"{query} {dc['month_year']}".strip()

    # Enrich short queries with BUSINESS CONTEXT that is searchable:
    # - Avoid company name (often not on Google / ambiguous / can match unrelated pop culture)
    # - Prefer Sector/Region/Products which improve relevance
    sector = ""
    region = ""
    products = ""
    for line in (biz_context or "").splitlines():
        l = line.strip()
        if l.lower().startswith("sector:"):
            sector = l.split(":", 1)[1].strip()
        elif l.lower().startswith("region:"):
            region = l.split(":", 1)[1].strip()
        elif l.lower().startswith("products & services:"):
            products = l.split(":", 1)[1].strip()

    enrich_parts: list[str] = []
    if sector:
        enrich_parts.append(sector)
    if region:
        enrich_parts.append(region)
    # products can get long; keep it short
    if products:
        enrich_parts.append(products[:60])

    if enrich_parts and len(query) < 80:
        query = f"{query} " + " ".join(enrich_parts[:2]).strip()

    return query


def _looks_like_trivial_message(text: str) -> bool:
    """
    Used to avoid absurd searches like 'hello ...' that produce irrelevant results.
    """
    t = " ".join((text or "").lower().split())
    if not t:
        return True
    if len(t) < 10:
        return True
    greetings = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "test",
    }
    return t in greetings


def _should_auto_search(text: str) -> bool:
    """
    Web search is mandatory for the assistant.
    This function now only guards against empty input.
    """
    return bool((text or "").strip())


def build_fallback_search_queries(
    *,
    conn: sqlite3.Connection,
    user_message: str,
    max_queries: int = 2,
) -> list[str]:
    """
    Always returns at least 1 safe query string, avoiding the company name.
    If the user's message is trivial (e.g. 'hello'), use sector/region/products instead.
    """
    max_queries = max(1, min(4, int(max_queries)))
    biz = _business_context(conn)
    sector = ""
    region = ""
    products = ""
    for line in (biz or "").splitlines():
        l = line.strip()
        if l.lower().startswith("sector:"):
            sector = l.split(":", 1)[1].strip()
        elif l.lower().startswith("region:"):
            region = l.split(":", 1)[1].strip()
        elif l.lower().startswith("products & services:"):
            products = l.split(":", 1)[1].strip()

    y = datetime.datetime.now().year
    base_ctx = " ".join(p for p in (sector, region) if p).strip() or "market trends"

    um = " ".join((user_message or "").split()).strip()
    if _looks_like_trivial_message(um):
        q1 = f"{base_ctx} {y} {y + 1}".strip()
        q2 = f"{base_ctx} customer trends {y}".strip()
    else:
        # Keep the user's intent, but don't append Name: ...
        head = um[:90]
        q1 = f"{head} {base_ctx} {y} {y + 1}".strip()
        # Add a second angle for actionable numbers if possible
        prod_hint = products.split(",")[0].strip() if products else ""
        q2 = f"{sector or 'industry'} {region or ''} {prod_hint} outlook {y} {y + 1}".strip()
        q2 = " ".join(q2.split())

    out: list[str] = []
    for q in (q1, q2):
        q = " ".join((q or "").split()).strip()
        if not q:
            continue
        if len(q) > 90:
            q = q[:90].rstrip() + "…"
        if q not in out:
            out.append(q)
        if len(out) >= max_queries:
            break
    return out or [f"{base_ctx} {y} {y + 1}".strip()]


def _generate_search_query(
    conn: sqlite3.Connection,
    turns: list[tuple[ChatRole, str]],
) -> str:
    """
    Backwards-compatible wrapper used by api_routes logging.
    (api_routes expects this symbol to exist.)
    """
    return _build_search_query(turns, _business_context(conn))


def _collapse_ws(s: Any) -> str:
    return " ".join(str(s or "").split())


def normalize_thinking_level(value: int | None, *, default: int = 2) -> int:
    """
    Clamp thinking level to [1..5].
    Level 1 means one-shot search; higher levels allow more refinement rounds.
    """
    if value is None:
        return default
    return max(1, min(5, int(value)))


def _build_trend_search_queries(conn: sqlite3.Connection) -> list[str]:
    """
    Builds the list of search queries for a scheduled trend analysis run.
    Combines monitored topics with business sector/region for targeted results.
    """
    biz = _business_context(conn)
    region = ""
    sector = ""
    products = ""
    for line in biz.splitlines():
        if line.lower().startswith("region:"):
            region = line.split(":", 1)[1].strip()
        if line.lower().startswith("sector:"):
            sector = line.split(":", 1)[1].strip()
        if line.lower().startswith("products & services:"):
            products = line.split(":", 1)[1].strip()

    raw = dbmod.get_setting(conn, dbmod.SETTING_TREND_TOPICS)
    topics: list[str] = []
    if raw:
        try:
            topics = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    y = datetime.datetime.now().year
    next_y = y + 1
    local_focus = f"{sector} {region}".strip() or (region or sector or "local market")
    prod_hint = products.split(",")[0].strip() if products else ""

    # 70% local/regional query lane
    local_queries: list[str] = []
    local_queries.append(f"{local_focus} trends {y} {next_y}".strip())
    local_queries.append(f"{local_focus} prices costs inflation taxes {y}".strip())
    local_queries.append(f"{local_focus} regulation policy tax changes {y}".strip())
    if prod_hint:
        local_queries.append(
            f"{local_focus} {prod_hint} demand supply outlook {y} {next_y}".strip()
        )
    for topic in topics:
        local_queries.append(
            f"{topic} {region}".strip() if region else str(topic).strip()
        )

    # 30% global context lane
    global_queries: list[str] = []
    if sector:
        global_queries.append(f"global {sector} outlook {y} {next_y}".strip())
    global_queries.append(
        f"global commodity prices shipping FX interest rates outlook {y} {next_y}"
    )
    global_queries.append(
        f"global geopolitical and trade policy risks market outlook {y} {next_y}"
    )

    out: list[str] = []
    for q in local_queries + global_queries:
        q = " ".join((q or "").split()).strip()
        if not q or q in out:
            continue
        out.append(q)

    return out or ["market trends today"]


def _is_truthy_setting(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list_enabled_search_tools(conn: sqlite3.Connection) -> list[str]:
    tools: list[str] = []

    google_enabled = _is_truthy_setting(
        dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_SEARCH_ENABLED),
        default=True,
    )
    google_key = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_API_KEY)
    google_cx = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_CX)
    if google_enabled and google_key and google_cx:
        tools.append("google")

    serpapi_enabled = _is_truthy_setting(
        dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_SEARCH_ENABLED),
        default=False,
    )
    serpapi_key = dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_API_KEY)
    if serpapi_enabled and serpapi_key:
        tools.append("serpapi")

    firecrawl_enabled = _is_truthy_setting(
        dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
        default=False,
    )
    firecrawl_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
    if firecrawl_enabled and firecrawl_key:
        tools.append("firecrawl")

    ddg_enabled = _is_truthy_setting(
        dbmod.get_setting(conn, dbmod.SETTING_DDG_SEARCH_ENABLED),
        default=False,
    )
    if ddg_enabled:
        tools.append("ddg")

    return tools


def _deep_read_config(conn: sqlite3.Connection) -> tuple[bool, int]:
    raw_enabled = dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_ENABLED)
    enabled = (
        True
        if raw_enabled is None
        else raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
    )
    raw_max = dbmod.get_setting(conn, dbmod.SETTING_DEEP_READ_MAX_ARTICLES)
    try:
        max_articles = max(1, min(8, int(raw_max) if raw_max is not None else 3))
    except ValueError:
        max_articles = 3
    return enabled, max_articles


def _run_one_tool(
    conn: sqlite3.Connection,
    tool: str,
    query: str,
    num: int,
) -> list[dict[str, str]]:
    """Execute a single named search tool and return tagged results."""
    if tool == "google":
        key = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_API_KEY) or ""
        cx = dbmod.get_setting(conn, dbmod.SETTING_GOOGLE_CX) or ""
        try:
            return [
                {**r, "_tool": "Google"}
                for r in search_tool.google_search(query, key, cx, num=num)
            ]
        except Exception as exc:
            logger.warning("Google search failed for query %r: %s", query, exc)
            return []

    if tool == "serpapi":
        serpapi_key = dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_API_KEY) or ""
        engine = (
            dbmod.get_setting(conn, dbmod.SETTING_SERPAPI_ENGINE) or "bing"
        ).strip() or "bing"
        try:
            return [
                {**r, "_tool": f"SerpAPI/{engine}"}
                for r in search_tool.serpapi_search(
                    query, serpapi_key, engine=engine, num=num
                )
            ]
        except Exception as exc:
            logger.warning("SerpAPI search failed for query %r: %s", query, exc)
            return []

    if tool == "firecrawl":
        fc_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY) or ""
        try:
            return [
                {**r, "_tool": "Firecrawl"}
                for r in firecrawl_tool.firecrawl_search(query, fc_key, num=num)
            ]
        except Exception as exc:
            logger.warning("Firecrawl search failed for query %r: %s", query, exc)
            return []

    if tool == "ddg":
        ddg_region = (
            dbmod.get_setting(conn, dbmod.SETTING_DDG_REGION) or "wt-wt"
        ).strip() or "wt-wt"
        ddg_timelimit = (
            dbmod.get_setting(conn, dbmod.SETTING_DDG_TIMELIMIT) or ""
        ).strip() or None
        try:
            return [
                {**r, "_tool": "DuckDuckGo"}
                for r in duckduckgo_tool.ddg_search(
                    query, num=num, region=ddg_region, timelimit=ddg_timelimit
                )
            ]
        except Exception as exc:
            logger.warning("DuckDuckGo search failed for query %r: %s", query, exc)
            return []

    return []


def _run_enabled_search_tools(
    conn: sqlite3.Connection,
    query: str,
    *,
    num: int = 8,
) -> list[dict[str, str]]:
    """Run all enabled search tools for a single query and merge results.

    Each tool gets an equal share of the *num* budget so the combined total
    never exceeds *num* regardless of how many tools are active.  Results are
    deduplicated by URL and each carries a ``_tool`` key for attribution.
    """
    query = (query or "").strip()
    if not query:
        return []

    enabled_tools = _list_enabled_search_tools(conn)
    if not enabled_tools:
        return []

    n_tools = len(enabled_tools)
    per_tool = max(3, -(-num // n_tools))  # ceiling div, min 3 per tool

    seen_links: set[str] = set()
    combined: list[dict[str, str]] = []
    for tool in enabled_tools:
        for item in _run_one_tool(conn, tool, query, per_tool):
            link = str(item.get("link") or "").strip()
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            combined.append(item)
    return combined


def _run_tools_for_queries(
    conn: sqlite3.Connection,
    queries: list[str],
    *,
    num_per_query: int = 6,
) -> list[tuple[str, list[dict[str, str]]]]:
    """Distribute a list of queries across enabled tools for maximum diversity.

    Strategy
    --------
    - With 1 tool  : all queries go to that tool (unchanged behaviour).
    - With N tools : queries are round-robin assigned to tools so each tool
      handles a *different* query.  Any extra queries beyond N are broadcast
      to all tools (they act as catch-all depth queries).

    Returns a list of ``(query, results)`` pairs in query order so callers
    can emit per-query status events.
    """
    queries = [q.strip() for q in queries if (q or "").strip()]
    if not queries:
        return []

    enabled_tools = _list_enabled_search_tools(conn)
    if not enabled_tools:
        return [(q, []) for q in queries]

    n_tools = len(enabled_tools)

    # Build (query, tool_or_None) assignment list.
    # First N queries → one tool each (round-robin).
    # Remaining queries → all tools (broad coverage).
    assignments: list[tuple[str, str | None]] = []
    for i, q in enumerate(queries):
        if i < n_tools:
            assignments.append((q, enabled_tools[i]))
        else:
            assignments.append((q, None))  # None = broadcast to all tools

    seen_links: set[str] = set()
    output: list[tuple[str, list[dict[str, str]]]] = []

    for q, tool in assignments:
        if tool is not None:
            # Assigned to one specific tool — full budget for that query.
            raw = _run_one_tool(conn, tool, q, num_per_query)
        else:
            # Broadcast: split budget across all tools.
            per_tool = max(3, -(-num_per_query // n_tools))
            raw = []
            for t in enabled_tools:
                raw.extend(_run_one_tool(conn, t, q, per_tool))

        # Deduplicate across the whole session.
        fresh: list[dict[str, str]] = []
        for item in raw:
            link = str(item.get("link") or "").strip()
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            fresh.append(item)
        output.append((q, fresh))

    return output


def _fetch_search_results(
    conn: sqlite3.Connection,
    turns: list[tuple[ChatRole, str]],
    biz_context: str,
    reading_cb: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, str]], str, str]:
    """
    Performs enabled web searches and returns (raw_results, formatted_xml_block, query_used).
    Errors are surfaced in the block rather than swallowed.
    """
    query = _build_search_query(turns, biz_context)
    try:
        results = _run_enabled_search_tools(conn, query, num=8)
        if not results:
            return [], "", query
        deep_read_enabled, deep_read_max = _deep_read_config(conn)
        if deep_read_enabled:
            fc_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
            fc_enabled = _is_truthy_setting(
                dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
                default=False,
            )
            if fc_enabled and fc_key:
                results, _ = firecrawl_tool.enrich_results_with_firecrawl(
                    results,
                    fc_key,
                    max_articles=deep_read_max,
                    excerpt_chars=900,
                    on_reading=reading_cb,
                )
            else:
                results, _ = reading_tool.enrich_results_with_article_excerpts(
                    results,
                    max_articles=deep_read_max,
                    excerpt_chars=900,
                    on_reading=reading_cb,
                )
        ctx = search_tool.format_results_for_prompt(results, query)
        block = (
            f'\n\n<search_results query="{query}">\n{ctx}\n</search_results>'
            if ctx
            else ""
        )
        return results, block, query
    except Exception as exc:
        logger.warning("Search failed for query %r: %s", query, exc)
        block = f'\n\n<search_results query="{query}">\n[Search failed: {exc}]\n</search_results>'
        return [], block, query


def _enrich_and_format(
    conn: sqlite3.Connection,
    results: list[dict[str, str]],
    query: str,
    *,
    excerpt_chars: int = 700,
    reading_cb: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Apply deep-read enrichment then format results into an XML block.

    Shared by every fetch helper so enrichment + formatting logic lives in
    one place.
    """
    deep_read_enabled, deep_read_max = _deep_read_config(conn)
    if deep_read_enabled and results:
        fc_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
        fc_enabled = _is_truthy_setting(
            dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
            default=False,
        )
        if fc_enabled and fc_key:
            results, _ = firecrawl_tool.enrich_results_with_firecrawl(
                results,
                fc_key,
                max_articles=deep_read_max,
                excerpt_chars=excerpt_chars,
                on_reading=reading_cb,
            )
        else:
            results, _ = reading_tool.enrich_results_with_article_excerpts(
                results,
                max_articles=deep_read_max,
                excerpt_chars=excerpt_chars,
                on_reading=reading_cb,
            )
    ctx = search_tool.format_results_for_prompt(results, query)
    block = (
        f'\n\n<search_results query="{query}">\n{ctx}\n</search_results>' if ctx else ""
    )
    return results, block


def _fetch_search_results_for_query(
    conn: sqlite3.Connection,
    query: str,
    *,
    num: int = 6,
    reading_cb: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Search a single query across all enabled tools and return
    (raw_results, formatted_xml_block).
    """
    query = (query or "").strip()
    if not query:
        return [], ""
    try:
        results = _run_enabled_search_tools(conn, query, num=num)
        if not results:
            return [], ""
        return _enrich_and_format(conn, results, query, reading_cb=reading_cb)
    except Exception as exc:
        logger.warning("Search failed for query %r: %s", query, exc)
        block = f'\n\n<search_results query="{query}">\n[Search failed: {exc}]\n</search_results>'
        return [], block


def _fetch_multi_search_results(
    conn: sqlite3.Connection,
    queries: list[str],
    reading_cb: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, str]], str]:
    """Distribute *queries* across enabled tools, merge and return results.

    Used by scheduled trend analysis and Overview to cast a wide net.
    Queries are assigned round-robin across tools (via _run_tools_for_queries)
    so every tool covers a different angle instead of every tool re-running
    every query.
    """
    pairs = _run_tools_for_queries(conn, queries, num_per_query=6)
    seen_urls: set[str] = set()
    all_results: list[dict[str, str]] = []
    for _q, res in pairs:
        for r in res:
            url = str(r.get("link") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    if not all_results:
        return [], ""

    deep_read_enabled, deep_read_max = _deep_read_config(conn)
    if deep_read_enabled:
        fc_key = dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_API_KEY)
        fc_enabled = _is_truthy_setting(
            dbmod.get_setting(conn, dbmod.SETTING_FIRECRAWL_SEARCH_ENABLED),
            default=False,
        )
        if fc_enabled and fc_key:
            all_results, _ = firecrawl_tool.enrich_results_with_firecrawl(
                all_results,
                fc_key,
                max_articles=min(8, deep_read_max + 1),
                excerpt_chars=800,
                on_reading=reading_cb,
            )
        else:
            all_results, _ = reading_tool.enrich_results_with_article_excerpts(
                all_results,
                max_articles=min(8, deep_read_max + 1),
                excerpt_chars=800,
                on_reading=reading_cb,
            )
    combined_query = " | ".join(q for q, _ in pairs)
    ctx = search_tool.format_results_for_prompt(all_results, combined_query)
    block = f'\n\n<search_results query="{combined_query}">\n{ctx}\n</search_results>'
    return all_results, block


def suggest_refinement_queries(
    conn: sqlite3.Connection,
    turns: list[tuple[ChatRole, str]],
    results: list[dict[str, str]],
    *,
    max_queries: int = 2,
    provider_override: ProviderOverride = None,
    already_run_queries: list[str] | None = None,
) -> list[str]:
    """
    Ask the model for up to N follow-up search queries to improve coverage.
    This is NOT chain-of-thought; it returns only queries.

    already_run_queries: every query already executed this session so the
    model can avoid rephrasing them.
    """
    if max_queries <= 0 or not results:
        return []

    already_run = already_run_queries or []

    # Summarise what topics are already covered from ALL results (not just 8).
    # Group by tool so the model sees breadth of coverage.
    covered_titles: list[str] = []
    for r in results:
        title = str(r.get("title") or "").strip()
        if title and title not in covered_titles:
            covered_titles.append(title)
    # Show at most 20 titles to stay within token budget
    coverage_preview = "\n".join(f"- {t}" for t in covered_titles[:20])
    if len(covered_titles) > 20:
        coverage_preview += f"\n… and {len(covered_titles) - 20} more articles"

    last_user_msg = next((c for r, c in reversed(turns) if r == "user"), "").strip()
    biz = _business_context(conn)

    already_run_block = (
        "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(already_run))
        if already_run
        else "  (none)"
    )

    dc = _current_date_context()
    system = (
        "You are a search strategist. Your job is to propose refinement queries\n"
        "that explore GENUINELY NEW angles not yet covered by previous searches.\n"
        "Return ONLY valid JSON, no markdown.\n"
        'Schema: {"queries": ["..."]}\n'
        f"Today's date: {dc['date']} ({dc['day_of_week']}, {dc['quarter']})\n"
        f"Current month/year: {dc['month_year']}\n"
        f"Rules:\n"
        f"- Provide 0 to {max_queries} queries. Prefer fewer, higher-quality queries.\n"
        "- Each query must be <= 90 characters.\n"
        "- STRICT: Every query must be semantically distinct from ALL already-run queries listed below.\n"
        "  A query is a duplicate if it asks the same question with different words — reject it.\n"
        "- Target only UNCOVERED angles. Ask yourself: what important question do the covered titles NOT answer?\n"
        "  Good new angles: specific price figures, upcoming policy dates, competitor behaviour,\n"
        "  currency/FX impact, specific sub-regions, consumer sentiment, infrastructure bottlenecks.\n"
        f"- Prefer current/future timeframes ({dc['month_year']}, {dc['next_year']}) unless history is needed.\n"
        "- Weight coverage roughly 70% regional/local and 30% global context.\n"
        '- If all key angles are already covered, return {"queries": []} — do NOT force extra queries.\n'
    )
    user = (
        "Business context:\n"
        f"{biz or '(none)'}\n\n"
        "Already-run queries (DO NOT rephrase or duplicate any of these):\n"
        f"{already_run_block}\n\n"
        "Topics already covered by retrieved articles:\n"
        f"{coverage_preview}\n\n"
        "What NEW angles are still missing? Propose queries only for genuine gaps.\n"
    )

    try:
        provider, key = _resolve_provider(conn, provider_override)
        raw = _call_provider(conn, provider, key, system, [("user", user)])
    except Exception as exc:
        logger.warning("refinement query planning failed: %s", exc)
        return []
    try:
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        qs = parsed.get("queries", [])
        if not isinstance(qs, list):
            return []
        out: list[str] = []
        for q in qs:
            if not isinstance(q, str):
                continue
            q = " ".join(q.split()).strip()
            if not q:
                continue
            if len(q) > 90:
                q = q[:90].rstrip() + "…"
            if q not in out:
                out.append(q)
        return out[:max_queries]
    except Exception:
        return []


def suggest_initial_search_queries(
    conn: sqlite3.Connection,
    turns: list[tuple[ChatRole, str]],
    *,
    max_queries: int = 2,
    provider_override: ProviderOverride = None,
) -> list[str]:
    """
    Ask the model to propose the FIRST set of search queries (before any search runs).
    This makes search model-driven instead of eager/heuristic-only.
    Returns only query strings (no chain-of-thought).
    """
    last_user_msg = next((c for r, c in reversed(turns) if r == "user"), "").strip()
    if not last_user_msg or max_queries <= 0:
        return []

    biz = _business_context(conn)
    watch = _trend_watch_context(conn)

    dc = _current_date_context()
    system = (
        "You are a search strategist for a business intelligence assistant.\n"
        "Return ONLY valid JSON. No markdown.\n"
        'Schema: {"queries": ["..."]}\n'
        f"Today's date: {dc['date']} ({dc['day_of_week']}, {dc['quarter']})\n"
        f"Current month/year: {dc['month_year']}\n"
        f"Rules:\n"
        f"- If necessary, return up to {max_queries} queries.\n"
        "- Each query must be <= 90 characters.\n"
        "- Prefer Sector/Region/Products over the company name.\n"
        "- Avoid ambiguous brand terms unless the user explicitly asked about the company.\n"
        f"- Bias to current/near-future timeframes ({dc['month_year']}, {dc['quarter']}, {dc['next_year']}).\n"
        f'- Include the current month/year in queries where recency matters (e.g. "... {dc["month_year"]}").\n'
        "- Keep a 70/30 mix: mostly local/regional queries, plus a smaller global context set.\n"
    )
    user = (
        "User message:\n"
        f"{last_user_msg}\n\n"
        "Business context:\n"
        f"{biz or '(none)'}\n\n"
        f"{watch}\n"
    )

    try:
        provider, key = _resolve_provider(conn, provider_override)
        raw = _call_provider(conn, provider, key, system, [("user", user)])
    except Exception as exc:
        logger.warning("initial query planning failed: %s", exc)
        return []
    try:
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        if not isinstance(parsed, dict):
            return []
        qs = parsed.get("queries", [])
        if not isinstance(qs, list):
            return []
        out: list[str] = []
        for q in qs:
            if not isinstance(q, str):
                continue
            q = " ".join(q.split()).strip()
            if not q:
                continue
            if len(q) > 90:
                q = q[:90].rstrip() + "…"
            if q not in out:
                out.append(q)
        return out[:max_queries]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Interactive chat entry point
# ---------------------------------------------------------------------------


def run_chat(
    conn: sqlite3.Connection,
    *,
    turns: list[tuple[ChatRole, str]],
    mode: ChatMode,
    provider_override: ProviderOverride = None,
    search_results_override: list[dict[str, str]] | None = None,
    search_block_override: str | None = None,
) -> tuple[str, str, ProviderName, list[dict[str, str]]]:
    """
    Main entry point for interactive chat.

    Returns:
        (reply_text, provider_used, raw_search_results)
    """
    if not turns:
        raise ValueError("No messages provided.")

    biz_context = _business_context(conn)
    effective_mode: Literal["chat", "analysis"] = (
        "analysis" if mode in {"analysis", "search"} else "chat"
    )
    search_results: list[dict[str, str]] = search_results_override or []
    search_block = search_block_override or ""

    if (
        effective_mode == "analysis"
        and search_results_override is None
        and search_block_override is None
    ):
        last_role, last_content = turns[-1]
        # Web search is mandatory; we only skip if empty.
        if (
            last_role == "user"
            and last_content.strip()
            and _should_auto_search(last_content)
        ):
            search_results, search_block, _ = _fetch_search_results(
                conn, turns, biz_context
            )

    last_user_msg = next((c for r, c in reversed(turns) if r == "user"), "")
    # Businesses expect visuals by default: always enable chart/diagram capabilities.
    include_visual_caps = True
    # In analysis/search mode always include the HTML brief (pass sentinel "");
    # in chat mode use the heuristic against the actual user message.
    include_html_brief = _should_include_html_brief(
        "" if effective_mode == "analysis" else last_user_msg
    )
    has_search_results: bool | None = (
        bool(search_results) if effective_mode == "analysis" else None
    )
    system = (
        _system_prompt(
            conn,
            effective_mode,
            include_visual_caps=include_visual_caps,
            include_html_brief=include_html_brief,
            has_search_results=has_search_results,
        )
        + search_block
    )
    provider, key = _resolve_provider(conn, provider_override)
    raw_reply = _call_provider(conn, provider, key, system, turns)
    reply_text, html = extract_html_brief(raw_reply)

    return reply_text, html, provider, search_results


# ---------------------------------------------------------------------------
# Autonomous trend analysis entry point (called by scheduler)
# ---------------------------------------------------------------------------


def run_trend_analysis(
    conn: sqlite3.Connection,
    *,
    provider_override: ProviderOverride = None,
    thinking_level: int = 2,
    progress_cb: Callable[[str, dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> TrendReport:
    """
    Proactive scheduled analysis. Searches across all monitored topics,
    asks the LLM to return a structured JSON TrendReport, and returns it
    for storage and rendering.

    Called by scheduler.py on a user-configured schedule (e.g. every 6 hours).
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    thinking_level = normalize_thinking_level(thinking_level, default=2)

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def _emit(event: str, payload: dict[str, Any]) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(event, payload)
        except Exception:
            logger.debug("Trend analysis progress callback failed.", exc_info=True)

    queries = _build_trend_search_queries(conn)
    all_results: list[dict[str, str]] = []
    blocks: list[str] = []
    seen_urls: set[str] = set()
    _emit(
        "status",
        {"phase": "thinking", "message": "Planning regional and global searches..."},
    )
    # Distribute initial queries across tools (round-robin) for maximum diversity.
    pairs = _run_tools_for_queries(conn, queries, num_per_query=6)
    for q, res in pairs:
        if _cancelled():
            raise RuntimeError("Run cancelled by user.")
        tool_names = sorted({str(r.get("_tool") or "") for r in res if r.get("_tool")})
        tool_label = f" via {', '.join(tool_names)}" if tool_names else ""
        _emit(
            "status",
            {
                "phase": "searching",
                "query": q,
                "message": f"Calling Tool: Web Search{tool_label} (Query: {q})",
            },
        )
        # Deep-read enrichment per query.
        enriched, blk = _enrich_and_format(
            conn,
            res,
            q,
            excerpt_chars=700,
            reading_cb=lambda meta: _emit("reading", meta),
        )
        if blk:
            blocks.append(blk)
        fresh: list[dict[str, str]] = []
        for r in enriched:
            u = str(r.get("link") or r.get("url") or "").strip()
            if u and u not in seen_urls:
                seen_urls.add(u)
                all_results.append(r)
                fresh.append(r)
        if fresh:
            _emit("sources", {"results": fresh})

    # Optional refinement rounds for autonomous runs.
    # thinking_level 1 => no refinement, 5 => up to 4 rounds.
    max_rounds = max(0, thinking_level - 1)
    # Track every query executed so the refinement planner can avoid rephrasing them.
    all_queries_run: list[str] = list(queries)
    if all_results and max_rounds > 0:
        for _ in range(max_rounds):
            if _cancelled():
                raise RuntimeError("Run cancelled by user.")
            pseudo_turns: list[tuple[ChatRole, str]] = [
                (
                    "user",
                    "Autonomous trend analysis. Refine search coverage for business-relevant trends.",
                )
            ]
            refinements = suggest_refinement_queries(
                conn,
                pseudo_turns,
                all_results,
                max_queries=2,
                provider_override=provider_override,
                already_run_queries=all_queries_run,
            )
            if not refinements:
                break
            # Register the new queries immediately so subsequent rounds
            # don't re-propose the same ones.
            all_queries_run.extend(refinements)
            _emit(
                "status",
                {
                    "phase": "thinking",
                    "message": "Ranking evidence and detecting conflicts...",
                },
            )
            round_new = 0
            # Distribute refinement queries across tools as well.
            ref_pairs = _run_tools_for_queries(conn, refinements, num_per_query=5)
            for q, res in ref_pairs:
                if _cancelled():
                    raise RuntimeError("Run cancelled by user.")
                tool_names = sorted(
                    {str(r.get("_tool") or "") for r in res if r.get("_tool")}
                )
                tool_label = f" via {', '.join(tool_names)}" if tool_names else ""
                _emit(
                    "status",
                    {
                        "phase": "searching",
                        "query": q,
                        "message": f"Calling Tool: Web Search{tool_label} (Query: {q})",
                    },
                )
                enriched, blk = _enrich_and_format(
                    conn,
                    res,
                    q,
                    excerpt_chars=700,
                    reading_cb=lambda meta: _emit("reading", meta),
                )
                if blk:
                    blocks.append(blk)
                refined_fresh: list[dict[str, str]] = []
                for r in enriched:
                    u = str(r.get("link") or r.get("url") or "").strip()
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        all_results.append(r)
                        refined_fresh.append(r)
                        round_new += 1
                if refined_fresh:
                    _emit("sources", {"results": refined_fresh})
            if round_new == 0:
                break

    _emit(
        "status",
        {
            "phase": "thinking",
            "message": "Writing advice, predictions, and chart output...",
        },
    )
    if _cancelled():
        raise RuntimeError("Run cancelled by user.")
    system = _trend_analysis_system_prompt(conn) + "".join(blocks)
    prompt_turn: list[tuple[ChatRole, str]] = [
        (
            "user",
            "Analyse the search results above. Identify trends, assess their impact on "
            "this business, and return the structured JSON report as instructed.",
        )
    ]

    provider, key = _resolve_provider(conn, provider_override)
    raw_reply = _call_provider(conn, provider, key, system, prompt_turn)
    if _cancelled():
        raise RuntimeError("Run cancelled by user.")

    # Parse structured JSON from LLM
    try:
        # Strip accidental markdown fences the model may add despite instructions
        clean = raw_reply.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed: dict[str, Any] = json.loads(clean)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Trend analysis: could not parse LLM JSON response: %s", exc)
        # Graceful degradation — wrap the raw reply in a minimal report
        return TrendReport(
            timestamp=now.isoformat(),
            query_used=" | ".join(queries),
            raw_results=all_results,
            summary=raw_reply,
            trend_signals=[],
            trend_signal_meta=[],
            recommended_actions=[],
            severity="low",
            sources=[
                str(r.get("link") or r.get("url") or "")
                for r in all_results
                if (r.get("link") or r.get("url"))
            ],
            predictions=[],
            visualisation="",
        )

    valid_severities = {"low", "medium", "high", "critical"}
    severity = parsed.get("severity", "low")
    if severity not in valid_severities:
        severity = "low"

    raw_summary = parsed.get("summary", "")
    cleaned_summary = _collapse_ws(raw_summary) if isinstance(raw_summary, str) else ""
    if not cleaned_summary:
        cleaned_summary = "No summary returned."

    raw_signals = parsed.get("trend_signals", [])
    cleaned_signals: list[str] = []
    cleaned_signal_meta: list[dict[str, Any]] = []
    if isinstance(raw_signals, list):
        for item in raw_signals:
            if isinstance(item, str):
                # backward-compat: plain string signals
                signal = _collapse_ws(item)
                if signal:
                    cleaned_signals.append(signal)
                    cleaned_signal_meta.append(
                        {"text": signal, "relevance": 50, "source_url": ""}
                    )
            elif isinstance(item, dict):
                # new structured format: {text, relevance, source_url}
                signal = _collapse_ws(str(item.get("text") or ""))
                if not signal:
                    continue
                try:
                    rel = max(0, min(100, int(item.get("relevance") or 50)))
                except (TypeError, ValueError):
                    rel = 50
                src = _collapse_ws(str(item.get("source_url") or ""))
                cleaned_signals.append(signal)
                cleaned_signal_meta.append(
                    {"text": signal, "relevance": rel, "source_url": src}
                )
    if not cleaned_signals:
        cleaned_signals.append("No explicit trend signals were returned.")
        cleaned_signal_meta.append(
            {
                "text": "No explicit trend signals were returned.",
                "relevance": 0,
                "source_url": "",
            }
        )

    raw_actions = parsed.get("recommended_actions", [])
    cleaned_actions: list[str] = []
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if isinstance(item, str):
                action = _collapse_ws(item)
                if action:
                    cleaned_actions.append(action)
    if not cleaned_actions:
        cleaned_actions.append(
            "Review the latest trend evidence and define immediate next steps."
        )
    raw_sources = parsed.get("sources", [])
    cleaned_sources: list[str] = []
    if isinstance(raw_sources, list):
        for u in raw_sources:
            if not isinstance(u, str):
                continue
            u = _collapse_ws(u)
            if u and u not in cleaned_sources:
                cleaned_sources.append(u)
    raw_predictions = parsed.get("predictions", [])
    cleaned_predictions: list[dict[str, Any]] = []
    if isinstance(raw_predictions, list):
        for p in raw_predictions[:6]:
            if not isinstance(p, dict):
                continue
            text = _collapse_ws(p.get("prediction_text"))
            if not text:
                continue
            unit = str(p.get("horizon_unit") or "weeks").strip().lower()
            if unit not in {"days", "weeks", "months", "years"}:
                unit = "weeks"
            try:
                hv = max(1, int(p.get("horizon_value") or 1))
            except (TypeError, ValueError):
                hv = 1
            conf = str(p.get("confidence") or "medium").strip().lower()
            if conf not in {"low", "medium", "high"}:
                conf = "medium"
            rationale = _collapse_ws(p.get("rationale"))
            ps: list[str] = []
            srcs = p.get("sources", [])
            if isinstance(srcs, list):
                for s in srcs:
                    if isinstance(s, str):
                        su = _collapse_ws(s)
                        if su and su not in ps:
                            ps.append(su)
            cleaned_predictions.append(
                {
                    "prediction_text": text,
                    "horizon_value": hv,
                    "horizon_unit": unit,
                    "confidence": conf,
                    "rationale": rationale,
                    "sources": ps or cleaned_sources[:2],
                }
            )
    raw_vis = parsed.get("visualisation", "")
    if isinstance(raw_vis, dict):
        raw_vis = json.dumps(raw_vis)
    cleaned_visualisation = str(raw_vis).strip()

    return TrendReport(
        timestamp=now.isoformat(),
        query_used=" | ".join(queries),
        raw_results=all_results,
        summary=cleaned_summary,
        trend_signals=cleaned_signals,
        trend_signal_meta=cleaned_signal_meta,
        recommended_actions=cleaned_actions,
        severity=severity,
        sources=cleaned_sources,
        predictions=cleaned_predictions,
        visualisation=cleaned_visualisation,
    )


# ---------------------------------------------------------------------------
# Utility: one-shot question against a trend report (for UI drill-down)
# ---------------------------------------------------------------------------


def ask_about_report(
    conn: sqlite3.Connection,
    report: TrendReport,
    question: str,
    *,
    provider_override: ProviderOverride = None,
) -> str:
    """
    Lets the user ask follow-up questions about a stored TrendReport
    without re-running the full search. Injects the report as context.
    """
    report_context = (
        f"Trend report from {report.timestamp}:\n"
        f"Summary: {report.summary}\n"
        f"Signals: {'; '.join(report.trend_signals)}\n"
        f"Recommended actions: {'; '.join(report.recommended_actions)}\n"
        f"Severity: {report.severity}"
    )
    include_visual_caps = _should_include_visual_caps(question)
    system = (
        _system_prompt(
            conn,
            "chat",
            include_visual_caps=include_visual_caps,
            include_html_brief=False,
        )
        + f"\n\n<trend_report>\n{report_context}\n</trend_report>"
    )
    turns: list[tuple[ChatRole, str]] = [("user", question)]
    provider, key = _resolve_provider(conn, provider_override)
    return _call_provider(conn, provider, key, system, turns)
