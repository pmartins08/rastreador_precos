from __future__ import annotations

from bs4 import BeautifulSoup

import scraper


RETRYABLE_CODES = {401, 403, 429, 500, 502, 503, 504}
CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verify you are human",
    "access denied",
    "robot check",
    "are you a robot",
    "captcha",
)


def _looks_like_xml(response) -> bool:
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "xml" in content_type:
        return True
    prefix = str(response.text or "").lstrip()[:120].lower()
    return prefix.startswith("<?xml") or prefix.startswith("<urlset") or prefix.startswith("<sitemapindex")


def classify(response) -> tuple[str, bool]:
    if response is None:
        return "no_response", True
    code = int(response.status_code)
    if code in RETRYABLE_CODES:
        return f"http_{code}", True
    if code == 404:
        return "http_404", False

    if not _looks_like_xml(response):
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            title = scraper.norm(soup.title.get_text(" ", strip=True) if soup.title else "")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()
            visible = scraper.norm(" ".join(soup.stripped_strings))[:20000]
            if any(marker in title or marker in visible for marker in CHALLENGE_MARKERS) or "cf-chl-" in title:
                return "challenge", True
        except Exception:
            pass
    return (f"http_{code}", False) if code >= 400 else ("http_success", False)
