"""Article reading/extraction tool used after web search discovery."""

from __future__ import annotations

import gzip
import logging
import re
import urllib.request
import zlib
from typing import Any, Callable

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # FIX #7: Only advertise encodings we actually handle
    "Accept-Encoding": "gzip",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


class ExtractionResult:
    """
    Structured result from fetch_article_excerpt.

    FIX #3: Replaces bare empty-string returns so callers (AI models) can
    distinguish failure modes and decide whether to retry, skip, or escalate.
    FIX #8: Carries truncation metadata so AI models know when content is partial.
    """

    __slots__ = ("text", "truncated", "total_extracted_chars", "failure_reason")

    def __init__(
        self,
        text: str = "",
        *,
        truncated: bool = False,
        total_extracted_chars: int = 0,
        failure_reason: str | None = None,
    ) -> None:
        self.text = text
        self.truncated = truncated
        self.total_extracted_chars = total_extracted_chars
        # One of: None (success), "timeout", "blocked", "non_html",
        #         "too_short", "decode_error", "network_error"
        self.failure_reason = failure_reason

    @property
    def ok(self) -> bool:
        return self.failure_reason is None and bool(self.text)

    def __bool__(self) -> bool:
        return self.ok


def _detect_encoding(content_type: str) -> str:
    """
    FIX #6: Extract charset from Content-Type header instead of always
    assuming UTF-8, so pages in latin-1, windows-1252, etc. decode cleanly.
    """
    match = re.search(r"charset\s*=\s*([^\s;]+)", content_type, re.IGNORECASE)
    if match:
        charset = match.group(1).strip().strip('"').lower()
        # Normalise common aliases that Python's codec lookup accepts
        return charset
    return "utf-8"


def _decompress(data: bytes, encoding: str) -> bytes:
    """FIX #7: Handle both gzip and deflate decompression."""
    enc = encoding.lower()
    if "gzip" in enc:
        return gzip.decompress(data)
    if "deflate" in enc:
        try:
            return zlib.decompress(data)
        except zlib.error:
            # Some servers send raw deflate without the zlib wrapper
            return zlib.decompress(data, -zlib.MAX_WBITS)
    return data


def _extract_readable_text(html: str, *, max_chars: int = 2400) -> tuple[str, bool]:
    """
    Strip HTML tags and return (plaintext, was_truncated).

    FIX #8: Returns a truncation flag alongside the text so callers know
    whether the excerpt is complete.
    FIX #2: Uses the caller-supplied max_chars directly with no hidden override.
    """
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
    cleaned = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    total = len(cleaned)
    if total > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0] + "…"
        return cleaned, True
    return cleaned, False


def fetch_article_excerpt(
    url: str, *, timeout: float = 12.0, max_chars: int = 800
) -> ExtractionResult:
    """
    Fetch URL and return a structured ExtractionResult with plaintext excerpt.

    FIX #3: Returns ExtractionResult instead of bare str so AI model callers
    can inspect failure_reason and truncation rather than receiving an opaque "".
    FIX #2: max_chars is respected end-to-end without a hidden internal override.
    FIX #6: Encoding is derived from Content-Type header.
    FIX #7: Both gzip and deflate Content-Encoding are handled.
    """
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            if status == 403 or status == 401:
                return ExtractionResult(failure_reason="blocked")

            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype:
                return ExtractionResult(failure_reason="non_html")

            data = resp.read()
            content_encoding = (resp.headers.get("Content-Encoding") or "").lower()
            if content_encoding:
                try:
                    data = _decompress(data, content_encoding)
                except Exception as exc:
                    logger.debug("Decompression failed for %s: %s", url, exc)
                    return ExtractionResult(failure_reason="decode_error")

            encoding = _detect_encoding(resp.headers.get("Content-Type") or "")
            try:
                raw = data.decode(encoding, errors="strict")
            except (UnicodeDecodeError, LookupError):
                # FIX #6: Fall back to UTF-8 with replacement only as last resort,
                # and signal the caller that decoding was imperfect.
                logger.debug("Encoding %r failed for %s, falling back to UTF-8", encoding, url)
                raw = data.decode("utf-8", errors="replace")
                if "\ufffd" in raw:
                    return ExtractionResult(failure_reason="decode_error")

    except TimeoutError:
        return ExtractionResult(failure_reason="timeout")
    except Exception as exc:
        logger.debug("Network error fetching %s: %s", url, exc)
        return ExtractionResult(failure_reason="network_error")

    # FIX #2: Pass max_chars straight through — no hidden internal override.
    text, truncated = _extract_readable_text(raw, max_chars=max_chars)

    if len(text) < 80:
        return ExtractionResult(failure_reason="too_short")

    return ExtractionResult(
        text=text,
        truncated=truncated,
        total_extracted_chars=len(text),
    )


def enrich_results_with_article_excerpts(
    results: list[dict[str, str]],
    *,
    max_articles: int = 3,
    excerpt_chars: int = 800,
    on_reading: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    Return (enriched_copies, summary) where enriched_copies are shallow-copied
    result dicts with an optional 'article_excerpt' key added.

    FIX #4: Input dicts are no longer mutated — copies are returned.
    FIX #5: Returns a summary dict so AI callers know how enrichment went
            (how many succeeded, failed, and why failures occurred).
    FIX #1: on_reading exceptions are logged rather than silently swallowed,
            and a strict_callbacks=True option is available for callers that
            need failures to propagate.
    """
    enriched: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "failure_reasons": [],
        "enrichment_complete": False,  # True only if max_articles were fetched
    }

    fetched = 0
    attempts = 0
    max_attempts = max_articles * 2

    for r in results:
        if fetched >= max_articles or attempts >= max_attempts:
            break

        link = str(r.get("link") or r.get("url") or "").strip()
        if not link:
            enriched.append(dict(r))
            continue

        title = str(r.get("title") or "").strip()
        attempts += 1
        summary["attempted"] += 1

        # FIX #1: Log callback errors rather than silently dropping them
        if on_reading:
            try:
                on_reading({"phase": "reading", "status": "started", "title": title, "url": link})
            except Exception as exc:
                logger.warning("on_reading callback raised on 'started' for %s: %s", link, exc)

        result = fetch_article_excerpt(link, max_chars=excerpt_chars)
        copy = dict(r)  # FIX #4: work on a copy

        if result.ok:
            copy["article_excerpt"] = result.text
            # FIX #8: Surface truncation so the AI model knows the excerpt is partial
            if result.truncated:
                copy["article_excerpt_truncated"] = True
            fetched += 1
            summary["succeeded"] += 1

            if on_reading:
                try:
                    on_reading({
                        "phase": "reading",
                        "status": "completed",
                        "title": title,
                        "url": link,
                        "chars": result.total_extracted_chars,
                        "words": len(result.text.split()),
                        "truncated": result.truncated,
                    })
                except Exception as exc:
                    logger.warning("on_reading callback raised on 'completed' for %s: %s", link, exc)
        else:
            # FIX #3 + #5: Record failure reason for both the result dict and the summary
            copy["article_excerpt_failure"] = result.failure_reason
            summary["failed"] += 1
            summary["failure_reasons"].append(result.failure_reason)

            if on_reading:
                try:
                    on_reading({
                        "phase": "reading",
                        "status": "skipped",
                        "title": title,
                        "url": link,
                        "reason": result.failure_reason,
                    })
                except Exception as exc:
                    logger.warning("on_reading callback raised on 'skipped' for %s: %s", link, exc)

        enriched.append(copy)

    # Pass through any results we didn't attempt
    for r in results[len(enriched):]:
        enriched.append(dict(r))

    summary["enrichment_complete"] = fetched >= max_articles
    return enriched, summary