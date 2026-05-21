"""Firecrawl search and scrape tool (stdlib HTTP only)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
logger = logging.getLogger(__name__)
FIRECRAWL_BASE = "https://api.firecrawl.dev"


def _post(
    url: str, payload: dict[str, Any], api_key: str, *, timeout: float = 60.0
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = err.get("error") or err.get("message") or raw[:400]
        except json.JSONDecodeError:
            msg = raw[:400]
        raise RuntimeError(f"Firecrawl API error {e.code}: {msg}") from e


def firecrawl_search(
    query: str,
    api_key: str,
    *,
    num: int = 8,
    scrape_content: bool = True,
) -> list[dict[str, str]]:
    """
    Call Firecrawl /v1/search and return results as list of
    {title, link, snippet, article_excerpt?} dicts.

    When scrape_content=True, the markdown content of each result is
    included as article_excerpt (Firecrawl returns it natively — no
    extra fetch needed).
    """
    payload: dict[str, Any] = {
        "query": query,
        "limit": max(1, min(10, num)),
    }
    if scrape_content:
        payload["scrapeOptions"] = {"formats": ["markdown"]}

    data = _post(f"{FIRECRAWL_BASE}/v1/search", payload, api_key)

    results: list[dict[str, str]] = []
    for item in data.get("data") or []:
        metadata = item.get("metadata") or {}
        title = str(metadata.get("title") or item.get("title") or "").strip()
        url = str(
            metadata.get("url") or metadata.get("sourceURL") or item.get("url") or ""
        ).strip()
        desc = str(metadata.get("description") or item.get("description") or "").strip()
        md = str(item.get("markdown") or "").strip()

        if not url:
            continue

        entry: dict[str, str] = {
            "title": title,
            "link": url,
            "snippet": desc or md[:200],
        }
        if md:
            # Truncate to ~2500 chars — Firecrawl returns clean markdown so
            # we can afford more context than the raw HTML scraper.
            cap = 2500
            entry["article_excerpt"] = md[:cap].rsplit(" ", 1)[0] + (
                "…" if len(md) > cap else ""
            )
        results.append(entry)

    return results


def firecrawl_scrape(
    url: str,
    api_key: str,
    *,
    timeout: float = 20.0,
    max_chars: int = 1000,
) -> str:
    """
    Scrape a single URL via Firecrawl /v1/scrape and return clean markdown.
    Returns empty string on failure.
    """
    try:
        data = _post(
            f"{FIRECRAWL_BASE}/v1/scrape",
            {"url": url, "formats": ["markdown"]},
            api_key,
            timeout=timeout,
        )
        md = str((data.get("data") or {}).get("markdown") or "").strip()
        if not md:
            return ""
        if len(md) > max_chars:
            md = md[:max_chars].rsplit(" ", 1)[0] + "…"
        return md
    except Exception:
        return ""


def enrich_results_with_firecrawl(
    results: list[dict[str, str]],
    api_key: str,
    *,
    max_articles: int = 3,
    excerpt_chars: int = 2000,
    on_reading=None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:  # return type updated to match reading_tool
    """
    Ensures up to max_articles results have article_excerpt content.
    - Results that already carry article_excerpt from firecrawl_search() are
      counted and surfaced to on_reading as 'completed' (content was already
      fetched inline — no extra HTTP call needed).
    - Results without article_excerpt are scraped via /v1/scrape.
    Drop-in replacement for reading_tool.enrich_results_with_article_excerpts.

    Returns (enriched_copies, summary) — input dicts are not mutated.
    """
    enriched: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "enrichment_complete": False,
    }
    fetched = 0
    for r in results:
        copy = dict(r)  # don't mutate caller's dicts
        if fetched < max_articles:
            link = str(r.get("link") or r.get("url") or "").strip()
            if link:
                title = str(r.get("title") or "").strip()
                existing = str(r.get("article_excerpt") or "").strip()
                if existing:
                    if on_reading:
                        try:
                            on_reading({
                                "phase": "reading",
                                "status": "completed",
                                "title": title,
                                "url": link,
                                "chars": len(existing),
                                "words": len(existing.split()),
                            })
                        except Exception:
                            logger.warning("on_reading callback raised for %s", link)
                    fetched += 1
                    summary["succeeded"] += 1
                else:
                    summary["attempted"] += 1
                    if on_reading:
                        try:
                            on_reading({"phase": "reading", "status": "started", "title": title, "url": link})
                        except Exception:
                            logger.warning("on_reading callback raised for %s", link)
                    md = firecrawl_scrape(link, api_key, max_chars=excerpt_chars)
                    if md:
                        copy["article_excerpt"] = md
                        if on_reading:
                            try:
                                on_reading({
                                    "phase": "reading",
                                    "status": "completed",
                                    "title": title,
                                    "url": link,
                                    "chars": len(md),
                                    "words": len(md.split()),
                                })
                            except Exception:
                                logger.warning("on_reading callback raised for %s", link)
                        fetched += 1
                        summary["succeeded"] += 1
                    else:
                        copy["article_excerpt_failure"] = "empty"
                        summary["failed"] += 1
                        if on_reading:
                            try:
                                on_reading({"phase": "reading", "status": "skipped", "title": title, "url": link})
                            except Exception:
                                logger.warning("on_reading callback raised for %s", link)
        enriched.append(copy)

    summary["enrichment_complete"] = fetched >= max_articles
    return enriched, summary