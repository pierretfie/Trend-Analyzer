"""
renderer.py — Trend Analyzer HTML report renderer
==================================================
Converts stored DB rows (from ai_analyses + discovered_trends) and
TrendReport dataclass instances from chat.py into styled HTML cards
ready to embed in your UI.

Depends on:
  trend_analyzer/db.py   — list_recent_analyses(), list_recent_trends(),
                           add_trend(), add_analysis()
  trend_analyzer/chat.py — TrendReport dataclass

No external dependencies — plain Python stdlib only.
"""

from __future__ import annotations

import html
import json
import sqlite3
from typing import Any

from trend_analyzer import db as dbmod

# ---------------------------------------------------------------------------
# Shared CSS injected once per page (call render_styles() in your base template)
# ---------------------------------------------------------------------------

STYLES = """
<style>
:root {
  --tr-bg:        #ffffff;
  --tr-bg2:       #f7f6f3;
  --tr-border:    rgba(0,0,0,0.10);
  --tr-text:      #1a1a18;
  --tr-muted:     #6b6a65;
  --tr-radius:    10px;
  --tr-radius-sm: 6px;

  --sev-low-bg:      #eaf3de;
  --sev-low-text:    #3b6d11;
  --sev-med-bg:      #faeeda;
  --sev-med-text:    #854f0b;
  --sev-high-bg:     #faece7;
  --sev-high-text:   #993c1d;
  --sev-crit-bg:     #fcebeb;
  --sev-crit-text:   #a32d2d;

  --conf-low-bg:     #f1efe8;
  --conf-low-text:   #5f5e5a;
  --conf-med-bg:     #faeeda;
  --conf-med-text:   #854f0b;
  --conf-high-bg:    #eaf3de;
  --conf-high-text:  #3b6d11;
}

@media (prefers-color-scheme: dark) {
  :root {
    --tr-bg:      #1e1e1c;
    --tr-bg2:     #28281f;
    --tr-border:  rgba(255,255,255,0.10);
    --tr-text:    #e0dfd8;
    --tr-muted:   #9c9a92;

    --sev-low-bg:      #27500a;  --sev-low-text:    #c0dd97;
    --sev-med-bg:      #633806;  --sev-med-text:    #fac775;
    --sev-high-bg:     #712b13;  --sev-high-text:   #f0997b;
    --sev-crit-bg:     #791f1f;  --sev-crit-text:   #f09595;

    --conf-low-bg:     #444441;  --conf-low-text:   #d3d1c7;
    --conf-med-bg:     #633806;  --conf-med-text:   #fac775;
    --conf-high-bg:    #27500a;  --conf-high-text:  #c0dd97;
  }
}

.tr-card {
  background: var(--tr-bg);
  border: 0.5px solid var(--tr-border);
  border-radius: var(--tr-radius);
  padding: 1rem 1.25rem;
  margin-bottom: 12px;
  font-family: sans-serif;
  color: var(--tr-text);
}

.tr-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.tr-headline {
  font-size: 15px;
  font-weight: 500;
  line-height: 1.4;
  margin: 0;
}

.tr-meta {
  font-size: 12px;
  color: var(--tr-muted);
  margin: 4px 0 0;
}

.tr-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 500;
  padding: 3px 9px;
  border-radius: var(--tr-radius-sm);
  white-space: nowrap;
  flex-shrink: 0;
}

.tr-badge-low      { background: var(--sev-low-bg);  color: var(--sev-low-text); }
.tr-badge-medium   { background: var(--sev-med-bg);  color: var(--sev-med-text); }
.tr-badge-high     { background: var(--sev-high-bg); color: var(--sev-high-text); }
.tr-badge-critical { background: var(--sev-crit-bg); color: var(--sev-crit-text); }

.tr-conf-low    { background: var(--conf-low-bg);  color: var(--conf-low-text); }
.tr-conf-medium { background: var(--conf-med-bg);  color: var(--conf-med-text); }
.tr-conf-high   { background: var(--conf-high-bg); color: var(--conf-high-text); }

.tr-section-label {
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--tr-muted);
  margin: 12px 0 6px;
}

.tr-summary {
  font-size: 14px;
  line-height: 1.6;
  color: var(--tr-text);
  margin: 0;
}

.tr-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.tr-list li {
  font-size: 13px;
  line-height: 1.5;
  color: var(--tr-text);
  padding: 5px 0 5px 18px;
  border-bottom: 0.5px solid var(--tr-border);
  position: relative;
}

.tr-list li:last-child {
  border-bottom: none;
}

.tr-list li::before {
  content: attr(data-bullet);
  position: absolute;
  left: 0;
  color: var(--tr-muted);
  font-size: 12px;
}

.tr-sources {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 0.5px solid var(--tr-border);
}

.tr-source-link {
  display: inline-block;
  font-size: 11px;
  color: var(--tr-muted);
  text-decoration: none;
  margin-right: 8px;
  margin-bottom: 4px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.tr-source-link:hover {
  text-decoration: underline;
}

.tr-divider {
  border: none;
  border-top: 0.5px solid var(--tr-border);
  margin: 10px 0;
}

.tr-empty {
  text-align: center;
  color: var(--tr-muted);
  font-size: 13px;
  padding: 2rem 0;
}

.tr-report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin: 10px 0;
}

.tr-metric {
  background: var(--tr-bg2);
  border-radius: var(--tr-radius-sm);
  padding: 10px 12px;
}

.tr-metric-label {
  font-size: 11px;
  color: var(--tr-muted);
  margin: 0 0 4px;
}

.tr-metric-value {
  font-size: 20px;
  font-weight: 500;
  margin: 0;
  color: var(--tr-text);
}
</style>
"""


def render_styles() -> str:
    """Return the shared CSS block. Call once in your base template <head>."""
    return STYLES


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _e(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text or ""), quote=True)


def _severity_badge(severity: str) -> str:
    s = severity.lower()
    label_map = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "critical": "Critical",
    }
    label = label_map.get(s, s.title())
    return f'<span class="tr-badge tr-badge-{s}">{_e(label)}</span>'


def _confidence_badge(confidence: str) -> str:
    c = confidence.lower()
    label_map = {
        "low": "Low confidence",
        "medium": "Med confidence",
        "high": "High confidence",
    }
    label = label_map.get(c, c.title())
    return f'<span class="tr-badge tr-conf-{c}">{_e(label)}</span>'


def _bullet_list(items: list[str], bullet: str = "–") -> str:
    if not items:
        return '<p class="tr-summary" style="color:var(--tr-muted)">None recorded.</p>'
    lis = "".join(f'<li data-bullet="{_e(bullet)}">{_e(item)}</li>' for item in items)
    return f'<ul class="tr-list">{lis}</ul>'


def _action_list(items: list[str]) -> str:
    if not items:
        return '<p class="tr-summary" style="color:var(--tr-muted)">No actions recorded.</p>'
    lis = "".join(
        f'<li data-bullet="{i + 1}.">{_e(item)}</li>' for i, item in enumerate(items)
    )
    return f'<ul class="tr-list">{lis}</ul>'


def _source_links(sources: list[str]) -> str:
    if not sources:
        return ""
    links = "".join(
        f'<a class="tr-source-link" href="{_e(url)}" target="_blank" rel="noopener">'
        f"{_e(_shorten_url(url))}</a>"
        for url in sources
        if url
    )
    if not links:
        return ""
    return (
        f'<div class="tr-sources"><p class="tr-section-label">Sources</p>{links}</div>'
    )


def _shorten_url(url: str, max_len: int = 55) -> str:
    url = url.replace("https://", "").replace("http://", "")
    return url if len(url) <= max_len else url[:max_len] + "…"


def _format_ts(ts: str) -> str:
    """Turn an ISO timestamp into a readable string."""
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%-d %b %Y, %H:%M UTC")
    except Exception:
        return ts


# ---------------------------------------------------------------------------
# Render a TrendReport dataclass (from chat.run_trend_analysis)
# ---------------------------------------------------------------------------


def render_trend_report(report: Any) -> str:
    """
    Accepts a TrendReport dataclass instance from chat.py.
    Returns a self-contained HTML card string (no <html>/<body>).
    """
    severity = getattr(report, "severity", "low")
    timestamp = getattr(report, "timestamp", "")
    summary = getattr(report, "summary", "")
    signals = getattr(report, "trend_signals", [])
    actions = getattr(report, "recommended_actions", [])
    sources = getattr(report, "sources", [])
    query = getattr(report, "query_used", "")

    ts_display = _format_ts(timestamp) if timestamp else ""
    query_display = f"Query: <em>{_e(query)}</em>" if query else ""

    parts = [
        f'<div class="tr-card">',
        f'  <div class="tr-card-header">',
        f"    <div>",
        f'      <p class="tr-headline">Trend Analysis Report</p>',
        f'      <p class="tr-meta">{_e(ts_display)}'
        + (f" &nbsp;·&nbsp; {query_display}" if query_display else "")
        + "</p>",
        f"    </div>",
        f"    {_severity_badge(severity)}",
        f"  </div>",
    ]

    if summary:
        parts += [
            '<p class="tr-section-label">Summary</p>',
            f'<p class="tr-summary">{_e(summary)}</p>',
        ]

    if signals:
        parts += [
            '<p class="tr-section-label">Signals detected</p>',
            _bullet_list(signals, bullet="◆"),
        ]

    if actions:
        parts += [
            '<p class="tr-section-label">Recommended actions</p>',
            _action_list(actions),
        ]

    parts.append(_source_links(sources))
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Render a single ai_analyses row (as returned by db.list_recent_analyses)
# ---------------------------------------------------------------------------


def render_analysis_card(row: sqlite3.Row) -> str:
    """
    Renders one row from ai_analyses (joined with discovered_trends).
    Columns used: headline, recommendation, confidence, created_at,
                  trend_title (from JOIN), trend_id.
    """
    headline = row["headline"] or ""
    recommendation = row["recommendation"] or ""
    confidence = row["confidence"] or "medium"
    created_at = row["created_at"] or ""
    trend_title = row["trend_title"] if "trend_title" in row.keys() else None

    parts = [
        '<div class="tr-card">',
        '  <div class="tr-card-header">',
        f"    <div>",
        f'      <p class="tr-headline">{_e(headline)}</p>',
    ]

    meta_parts = []
    if created_at:
        meta_parts.append(_e(_format_ts(created_at)))
    if trend_title:
        meta_parts.append(f"Re: <em>{_e(trend_title)}</em>")
    if meta_parts:
        parts.append(
            f'      <p class="tr-meta">{" &nbsp;·&nbsp; ".join(meta_parts)}</p>'
        )

    parts += [
        "    </div>",
        f"    {_confidence_badge(confidence)}",
        "  </div>",
    ]

    if recommendation:
        parts += [
            '<p class="tr-section-label">Recommendation</p>',
            f'<p class="tr-summary">{_e(recommendation)}</p>',
        ]

    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Render a single discovered_trends row
# ---------------------------------------------------------------------------


def render_trend_card(row: sqlite3.Row) -> str:
    """
    Renders one row from discovered_trends.
    Columns: title, summary, category, source_url, relevance, discovered_at.
    """
    title = row["title"] or ""
    summary = row["summary"] or ""
    category = row["category"] or "general"
    source_url = row["source_url"] or ""
    relevance = int(row["relevance"] or 50)
    discovered_at = row["discovered_at"] or ""

    # Map relevance 0-100 to a severity-style badge
    if relevance >= 80:
        sev = "high"
    elif relevance >= 50:
        sev = "medium"
    else:
        sev = "low"

    parts = [
        '<div class="tr-card">',
        '  <div class="tr-card-header">',
        "    <div>",
        f'      <p class="tr-headline">{_e(title)}</p>',
        f'      <p class="tr-meta">{_e(_format_ts(discovered_at))}'
        f" &nbsp;·&nbsp; {_e(category.title())}"
        f" &nbsp;·&nbsp; Relevance: {relevance}%</p>",
        "    </div>",
        f"    {_severity_badge(sev)}",
        "  </div>",
    ]

    if summary:
        parts.append(f'<p class="tr-summary">{_e(summary)}</p>')

    if source_url:
        parts.append(
            f'<div class="tr-sources">'
            f'<a class="tr-source-link" href="{_e(source_url)}" target="_blank" rel="noopener">'
            f"{_e(_shorten_url(source_url))}</a></div>"
        )

    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Dashboard summary card (metrics overview)
# ---------------------------------------------------------------------------


def render_dashboard_summary(conn: sqlite3.Connection) -> str:
    """
    Returns a small metrics grid showing total trends, analyses, and last run time.
    Reads directly from DB — call this at the top of your dashboard page.
    """
    trend_count = conn.execute("SELECT COUNT(*) FROM discovered_trends").fetchone()[0]

    analysis_count = conn.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0]

    last_run = conn.execute(
        "SELECT finished_at, status FROM research_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if last_run and last_run["finished_at"]:
        last_run_display = _format_ts(last_run["finished_at"])
        last_run_status = last_run["status"] or "unknown"
    else:
        last_run_display = "Never"
        last_run_status = "—"

    high_count = conn.execute(
        "SELECT COUNT(*) FROM ai_analyses WHERE confidence = 'high'"
    ).fetchone()[0]

    return f"""
<div class="tr-report-grid">
  <div class="tr-metric">
    <p class="tr-metric-label">Trends discovered</p>
    <p class="tr-metric-value">{trend_count}</p>
  </div>
  <div class="tr-metric">
    <p class="tr-metric-label">Analyses run</p>
    <p class="tr-metric-value">{analysis_count}</p>
  </div>
  <div class="tr-metric">
    <p class="tr-metric-label">High-confidence findings</p>
    <p class="tr-metric-value">{high_count}</p>
  </div>
  <div class="tr-metric">
    <p class="tr-metric-label">Last run</p>
    <p class="tr-metric-value" style="font-size:13px;padding-top:4px">
      {_e(last_run_display)}<br>
      <span style="font-size:11px;color:var(--tr-muted)">{_e(last_run_status)}</span>
    </p>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Full feed renderers (lists of cards)
# ---------------------------------------------------------------------------


def render_analyses_feed(conn: sqlite3.Connection, limit: int = 20) -> str:
    """Renders the last N ai_analyses rows as a vertical card feed."""
    rows = dbmod.list_recent_analyses(conn, limit=limit)
    if not rows:
        return '<p class="tr-empty">No analyses recorded yet.</p>'
    return "\n".join(render_analysis_card(row) for row in rows)


def render_trends_feed(conn: sqlite3.Connection, limit: int = 20) -> str:
    """Renders the last N discovered_trends rows as a vertical card feed."""
    rows = dbmod.list_recent_trends(conn, limit=limit)
    if not rows:
        return '<p class="tr-empty">No trends discovered yet.</p>'
    return "\n".join(render_trend_card(row) for row in rows)


# ---------------------------------------------------------------------------
# Save a TrendReport back to DB using existing db.py helpers
# ---------------------------------------------------------------------------


def save_report_to_db(conn: sqlite3.Connection, report: Any) -> tuple[int, int]:
    """
    Persists a TrendReport to the existing schema:
      - Each trend_signal → discovered_trends row
      - summary + recommended_actions → ai_analyses row (linked to first trend)

    Returns (trend_id_of_first_signal, analysis_id).
    Uses db.add_trend() and db.add_analysis() so all the transaction
    and validation logic stays in one place.
    """
    severity = getattr(report, "severity", "low")
    summary = getattr(report, "summary", "")
    signals = getattr(report, "trend_signals", [])
    actions = getattr(report, "recommended_actions", [])
    sources = getattr(report, "sources", [])
    query = getattr(report, "query_used", "")
    run_id = getattr(report, "run_id", None)

    # Map severity → relevance score for discovered_trends
    relevance_map = {"low": 30, "medium": 55, "high": 80, "critical": 95}
    relevance = relevance_map.get(severity, 50)

    # Map severity → confidence for ai_analyses
    confidence_map = {
        "low": "low",
        "medium": "medium",
        "high": "high",
        "critical": "high",
    }
    confidence = confidence_map.get(severity, "medium")

    # Per-signal metadata (text, relevance, source_url) supplied by the new
    # structured prompt. Falls back to report-level values when absent.
    signal_meta: list[dict] = getattr(report, "trend_signal_meta", []) or []

    first_trend_id: int | None = None
    for idx, signal in enumerate(signals):
        meta = signal_meta[idx] if idx < len(signal_meta) else {}

        # Per-signal relevance from the model; fall back to severity-mapped score.
        try:
            signal_relevance = max(0, min(100, int(meta.get("relevance") or relevance)))
        except (TypeError, ValueError):
            signal_relevance = relevance

        # Per-signal source_url from the model; fall back to round-robin pool.
        signal_source = str(meta.get("source_url") or "").strip()
        if not signal_source:
            signal_source = sources[idx % len(sources)] if sources else ""
        source_url = signal_source or None

        trend_id = dbmod.add_trend(
            conn,
            run_id=run_id,
            title=signal[:200],
            summary=summary,
            category=_infer_category(query),
            source_url=source_url,
            relevance=signal_relevance,
        )
        if first_trend_id is None:
            first_trend_id = trend_id

    if not first_trend_id and summary:
        # No signals but still have a summary — create a placeholder trend
        first_trend_id = dbmod.add_trend(
            conn,
            run_id=run_id,
            title=(summary[:100] + "…") if len(summary) > 100 else summary,
            summary=summary,
            category=_infer_category(query),
            source_url=sources[0] if sources else None,
            relevance=relevance,
        )

    # Combine recommended actions into one recommendation string
    recommendation = (
        "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions)) if actions else ""
    )

    analysis_id = dbmod.add_analysis(
        conn,
        run_id=run_id,
        headline=_build_analysis_headline(signals, summary, query),
        recommendation=recommendation,
        confidence=confidence,
        trend_id=first_trend_id,
    )

    return first_trend_id or 0, analysis_id


def _infer_category(query: str) -> str:
    """
    Simple keyword-based category inference from the search query.
    Extend this list to match your business domains.
    """
    q = query.lower()
    if any(w in q for w in ("fuel", "oil", "gas", "energy", "petroleum", "opec")):
        return "energy"
    if any(
        w in q
        for w in ("price", "inflation", "cost", "market", "stock", "forex", "rate")
    ):
        return "economic"
    if any(w in q for w in ("regulation", "law", "policy", "government", "tax")):
        return "regulatory"
    if any(w in q for w in ("supply", "demand", "shortage", "logistics", "chain")):
        return "supply_chain"
    if any(w in q for w in ("tech", "ai", "software", "digital", "cyber")):
        return "technology"
    return "general"


def _build_analysis_headline(
    signals: list[str],
    summary: str,
    query: str,
) -> str:
    """
    Generate a concise, readable headline from report content.
    Avoid dumping full query strings into the UI title.
    """
    base = ""
    if signals:
        base = str(signals[0] or "").strip()
    if not base:
        base = str(summary or "").strip()
    if not base:
        base = str(query or "").strip()
    if not base:
        return "Trend analysis"

    # Keep only first sentence/segment and normalize spacing.
    for sep in (". ", " — ", " | ", "; "):
        if sep in base:
            base = base.split(sep, 1)[0]
            break
    base = " ".join(base.split())
    base = base.strip(" -|:;,.")

    return f"Trend analysis — {base}"
