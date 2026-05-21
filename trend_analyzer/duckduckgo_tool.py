"""DuckDuckGo free search tool — no API key required.

Uses the open-source `ddgs` library (formerly `duckduckgo-search`).
Install: pip install ddgs
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def ddg_search(
    query: str,
    *,
    num: int = 8,
    region: str = "wt-wt",
    safesearch: str = "off",
    timelimit: str | None = None,
) -> list[dict[str, str]]:
    """
    Search DuckDuckGo for *query* and return up to *num* results.

    Parameters
    ----------
    query      : search string
    num        : max results to return (1-20)
    region     : DDG region code, e.g. "us-en", "wt-wt" (worldwide)
    safesearch : "on" | "moderate" | "off"
    timelimit  : "d" (day), "w" (week), "m" (month), "y" (year), or None

    Returns
    -------
    list of dicts with keys: title, link, snippet
    Raises RuntimeError on unrecoverable errors.
    """
    try:
        from ddgs import DDGS  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("ddgs is not installed. Run: pip install ddgs") from exc

    num = max(1, min(20, num))
    kwargs: dict[str, Any] = {
        "region": region,
        "safesearch": safesearch,
        "max_results": num,
    }
    if timelimit:
        kwargs["timelimit"] = timelimit

    try:
        with DDGS() as ddgs_client:
            raw: list[dict[str, Any]] = ddgs_client.text(query, **kwargs) or []
    except Exception as exc:
        # Wrap any DDGS error (rate-limit, network, etc.) in a RuntimeError
        raise RuntimeError(f"DuckDuckGo search error: {exc}") from exc

    results: list[dict[str, str]] = []
    for item in raw[:num]:
        results.append(
            {
                "title": str(item.get("title") or ""),
                "link": str(item.get("href") or item.get("url") or ""),
                "snippet": str(item.get("body") or ""),
            }
        )
    return results
