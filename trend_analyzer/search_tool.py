"""Web search tools (Google CSE + SerpAPI via stdlib HTTP)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
SERPAPI_SEARCH_URL = "https://serpapi.com/search"
_UA = "TrendAnalyzerBot/1.0 (+https://localhost)"


def google_search(
    query: str,
    api_key: str,
    cx: str,
    *,
    num: int = 8,
    date_restrict: str | None = "y1",  # last year by default
) -> list[dict[str, str]]:
    """
    Call the Google Custom Search JSON API.

    Returns a list of dicts with keys: title, link, snippet.
    Raises RuntimeError on API errors.
    """
    params: dict[str, Any] = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": max(1, min(10, num)),
    }
    if date_restrict:
        params["dateRestrict"] = date_restrict

    url = GOOGLE_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = (err.get("error") or {}).get("message") or raw[:400]
        except json.JSONDecodeError:
            msg = raw[:400]
        raise RuntimeError(f"Google Search API error {e.code}: {msg}") from e

    items = data.get("items") or []
    results: list[dict[str, str]] = []
    for item in items:
        results.append(
            {
                "title": str(item.get("title") or ""),
                "link": str(item.get("link") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
        )
    return results


def serpapi_search(
    query: str,
    api_key: str,
    *,
    engine: str = "google",
    num: int = 8,
) -> list[dict[str, str]]:
    """
    Call SerpAPI search endpoint for a specific engine.

    Returns a list of dicts with keys: title, link, snippet.
    Raises RuntimeError on API errors.
    """
    params: dict[str, Any] = {
        "api_key": api_key,
        "engine": engine,
        "q": query,
        "num": max(1, min(20, num)),
    }
    url = SERPAPI_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
            msg = err.get("error") or raw[:400]
            if isinstance(msg, dict):
                msg = json.dumps(msg)
        except json.JSONDecodeError:
            msg = raw[:400]
        raise RuntimeError(f"SerpAPI error {e.code}: {msg}") from e

    if data.get("error"):
        raise RuntimeError(f"SerpAPI error: {data.get('error')}")

    items = data.get("organic_results") or []
    results: list[dict[str, str]] = []
    for item in items[: max(1, min(20, num))]:
        results.append(
            {
                "title": str(item.get("title") or ""),
                "link": str(item.get("link") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
        )
    return results


def format_results_for_prompt(results: list[dict[str, str]], query: str) -> str:
    """Render search results as a compact markdown block for LLM context.

    When results come from multiple tools each item may carry a ``_tool`` key
    (set by ``_run_enabled_search_tools``).  The header reflects the actual
    mix and each result is tagged with its source tool.
    """
    if not results:
        return f"[No results found for: {query}]"

    # Derive a header from the distinct tools that contributed results.
    tools_present: list[str] = []
    seen_tools: set[str] = set()
    for r in results:
        t = str(r.get("_tool") or "").strip()
        if t and t not in seen_tools:
            seen_tools.add(t)
            tools_present.append(t)
    if tools_present:
        tools_label = " + ".join(tools_present)
        header = f"**Web search results ({tools_label}) for: {query}**"
    else:
        header = f"**Web search results for: {query}**"

    lines = [header, ""]
    for i, r in enumerate(results, 1):
        tool_tag = f" [{r['_tool']}]" if r.get("_tool") else ""
        lines.append(f"{i}. **{r['title']}**{tool_tag}")
        lines.append(f"   {r['snippet']}")
        article_excerpt = str(r.get("article_excerpt") or "").strip()
        if article_excerpt:
            lines.append(f"   Article excerpt: {article_excerpt}")
        lines.append(f"   Source: {r['link']}\n")
    return "\n".join(lines)
