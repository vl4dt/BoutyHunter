#!/usr/bin/env python3
"""
BoutyHunter — Web Scraping for Program Metrics

Scrapes public program pages on HackerOne and Intigriti to extract metrics
not available via the researcher APIs.  Currently extracts:

  - **researcher_count**: number of active/recent researchers (Intigriti only,
    from embedded JSON-LD ``lastActivity`` — a lower-bound estimate)
  - **submission_count**: total submissions on the program (Intigriti)
  - **accepted_submission_count**: accepted/valid submissions (Intigriti)

HackerOne requires full JS rendering for its stats, so scraping uses Puppeteer
(Node.js + Chromium) as primary strategy with Playwright (Python) as fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("boutyhunter.scraper")

# ─── Shared helpers ──────────────────────────────────────────────────

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}


def _fetch_page(url: str, timeout: int = 20) -> BeautifulSoup | None:
    """Fetch a URL and return parsed soup, or None on failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, e)
        return None


def _parse_number(text: str) -> int | None:
    """Extract an integer from a string like '1,234' or '~500'."""
    if not text:
        return None
    cleaned = re.sub(r"[^0-9]", "", text.strip())
    if cleaned:
        return int(cleaned)
    return None


# ─── Puppeteer helper (Node.js + Chromium via subprocess) ──────────

_PUPPETEER_SCRIPT = Path(__file__).parent / "hackerone_scraper.mjs"
_PUPPETEER_AVAILABLE: bool | None = None  # cached after first check


def _is_puppeteer_available() -> bool:
    """Check if Puppeteer can actually run (node + chromium)."""
    global _PUPPETEER_AVAILABLE
    if _PUPPETEER_AVAILABLE is not None:
        return _PUPPETEER_AVAILABLE
    try:
        result = subprocess.run(
            ["node", str(_PUPPETEER_SCRIPT), "https://hackerone.com/security"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            json.loads(result.stdout)
            _PUPPETEER_AVAILABLE = True
        else:
            logger.debug("Puppeteer test failed: %s", result.stderr[:200])
            _PUPPETEER_AVAILABLE = False
    except FileNotFoundError:
        logger.debug("Puppeteer not available: node or script missing")
        _PUPPETEER_AVAILABLE = False
    except Exception as e:
        logger.debug("Puppeteer test failed: %s", e)
        _PUPPETEER_AVAILABLE = False
    return _PUPPETEER_AVAILABLE


def _try_puppeteer(url: str) -> dict[str, Any] | None:
    """Scrape a HackerOne program page via Puppeteer subprocess."""
    if not _is_puppeteer_available():
        logger.debug("Puppeteer skipped for %s (not available)", url)
        return None
    try:
        result = subprocess.run(
            ["node", str(_PUPPETEER_SCRIPT), url],
            capture_output=True, text=True, timeout=45,
        )
        if result.returncode != 0:
            logger.debug("Puppeteer failed for %s: %s", url, result.stderr[:200])
            return None
        data = json.loads(result.stdout)
        logger.info("Puppeteer %s: %s", url, data)
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.debug("Puppeteer error for %s: %s", url, e)
        return None


# ─── Playwright helper (optional, activated when browsers exist) ─────

_PLAYWRIGHT_AVAILABLE: bool | None = None  # cached after first check


def _is_playwright_available() -> bool:
    """Check if Playwright can actually launch a browser."""
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Try launching headless — this will fail on unsupported platforms
            browser = p.chromium.launch(headless=True, timeout=10000)
            browser.close()
        _PLAYWRIGHT_AVAILABLE = True
    except Exception as e:
        logger.debug("Playwright not available: %s", e)
        _PLAYWRIGHT_AVAILABLE = False
    return _PLAYWRIGHT_AVAILABLE


def _try_playwright(url: str, timeout_ms: int = 30_000) -> BeautifulSoup | None:
    """Render a page with Playwright and return parsed soup.

    Returns None if Playwright is unavailable or the request fails.
    """
    if not _is_playwright_available():
        logger.debug("Playwright skipped for %s (not available)", url)
        return None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            soup = BeautifulSoup(page.content(), "lxml")
            browser.close()
            return soup
    except Exception as e:
        logger.debug("Playwright failed for %s: %s", url, e)
        return None


# ─── HackerOne Scraper ──────────────────────────────────────────────

def scrape_hackerone(url: str) -> dict[str, Any]:
    """Scrape a HackerOne program page.

    HackerOne is a JS-heavy SPA — stats (researcher count, etc.) are only
    available after JavaScript rendering.  We try Playwright first, then fall
    back to extracting whatever signals we can from the static HTML meta tags
    and embedded script data.

    Returns dict with keys:
      - researcher_count: int | None
      - submission_count: int | None
    """
    result: dict[str, Any] = {"researcher_count": None, "submission_count": None}

    # Strategy 1: Puppeteer (Node.js + Chromium) — works on Ubuntu 26.04
    puppeteer_data = _try_puppeteer(url)
    if puppeteer_data:
        result["researcher_count"] = puppeteer_data.get("researcher_count")
        result["submission_count"] = puppeteer_data.get("submission_count")
        logger.info("HackerOne %s (puppeteer): %s", url, result)
        return result

    # Strategy 2: Playwright (Python) — fallback for other systems
    soup = _try_playwright(url)
    if soup is not None:
        full_text = soup.get_text()

        # Look for "X hackers" pattern in rendered content
        # Negative lookahead avoids matching "#1 hacker-powered"
        match = re.search(r"(\d[\d,]*)\s*hackers?(?!-)", full_text, re.IGNORECASE)
        if match:
            result["researcher_count"] = _parse_number(match.group(1))

        # Look for submission/report counts
        sub_match = re.search(
            r"(\d[\d,]*)\s*(submissions?|reports?)", full_text, re.IGNORECASE
        )
        if sub_match:
            result["submission_count"] = _parse_number(sub_match.group(1))

        logger.info("HackerOne %s (playwright): %s", url, result)
        return result

    # Strategy 2: Static HTML — meta tags + embedded script data
    soup = _fetch_page(url)
    if soup is not None:
        desc = ""
        for meta in soup.find_all("meta"):
            name = (meta.get("property", "") or meta.get("name", "")).lower()
            if "description" in name:
                desc = meta.get("content", "") or ""
                break

        # Look for hacker counts in description
        # Negative lookahead avoids matching "#1 hacker-powered"
        match = re.search(r"(\d[\d,]*)\s*hackers?(?!-)", desc, re.IGNORECASE)
        if match:
            result["researcher_count"] = _parse_number(match.group(1))

        # Strategy 2b: Look for embedded JSON in script tags (not just JSON-LD)
        for script in soup.find_all("script"):
            text = script.get_text() or ""
            if not text or len(text) > 50_000:
                continue
            # Try to find embedded program data objects
            try:
                data = json.loads(text)
                _extract_hackerone_from_json(data, result)
            except (json.JSONDecodeError, ValueError):
                pass

    logger.info("HackerOne %s (static): %s", url, result)
    return result


def _extract_hackerone_from_json(data: Any, result: dict[str, Any]) -> None:
    """Extract HackerOne stats from embedded JSON data."""
    if isinstance(data, dict):
        # Look for researcher/hacker counts
        for key in ("researcherCount", "hackersCount", "numHackers"):
            if key in data and isinstance(data[key], (int, float)):
                val = int(data[key])
                if val > 0 and result["researcher_count"] is None:
                    result["researcher_count"] = val

        # Look for submission/report counts
        for key in ("submissionCount", "reportCount", "numSubmissions"):
            if key in data and isinstance(data[key], (int, float)):
                val = int(data[key])
                if val > 0 and result["submission_count"] is None:
                    result["submission_count"] = val

        # Recurse
        for value in data.values():
            _extract_hackerone_from_json(value, result)
    elif isinstance(data, list):
        for item in data:
            _extract_hackerone_from_json(item, result)


# ─── Intigriti Scraper ──────────────────────────────────────────────

def scrape_intigriti(url: str) -> dict[str, Any]:
    """Scrape an Intigriti program page.

    Intigriti embeds Next.js serialized API responses in ``<script type="application/json">``
    blocks.  Each chunk has shape ``{b: <body>, u: <url>, s: <status>}`` where the body
    contains program details including::

      - **lastContributors**: recent researchers (userId, userName)
      - **lastActivity**: activity log with researcher info and timestamps
      - **submissionCount**: total submissions on the program
      - **acceptedSubmissionCount**: accepted/valid submissions

    Some programs return a full data payload (~60 KB JSON) while others are blocked
    by Cloudflare/WAF and return only env config (~1.5 KB).  We detect this via page
    size heuristics.

    Returns dict with extracted metrics.
    """
    result: dict[str, Any] = {
        "researcher_count": None,
        "submission_count": None,
        "accepted_submission_count": None,
    }

    soup = _fetch_page(url)
    if soup is None:
        return result

    # Check if the page was blocked (Forbidden / Cloudflare challenge)
    h1 = soup.find("h1")
    if h1 and "forbidden" in h1.get_text().lower():
        logger.debug("Intigriti %s: page blocked (Forbidden), skipping", url)
        return result

    # Strategy 1: Parse embedded JSON-LD for program stats
    total_json_size = 0
    for script in soup.find_all("script", type="application/json"):
        text = script.get_text() or ""
        if not text:
            continue
        total_json_size += len(text)
        try:
            data = json.loads(text)
            _extract_from_json(data, result)
        except Exception as e:
            logger.debug("Intigriti JSON parse error for %s: %s", url, e)

    # If we got very little JSON (< 5KB), the page was likely blocked
    if total_json_size < 5000 and not any(
        v is not None for k, v in result.items() if k != "researcher_count"
    ):
        logger.debug(
            "Intigriti %s: minimal JSON (%d bytes), likely blocked by WAF",
            url,
            total_json_size,
        )

    # Strategy 2: Count "last contributors" divs as a fallback lower-bound
    if result["researcher_count"] is None:
        researcher_divs = soup.find_all("div", class_="researcher")
        if researcher_divs:
            count = len(researcher_divs)
            # Only use this if we got at least some contributors (not 0)
            result["researcher_count"] = count

    logger.info("Intigriti %s: %s", url, result)
    return result


# Mapping from camelCase API keys → our snake_case result keys
_SUBMISSION_KEY_MAP: dict[str, str] = {
    "submissionCount": "submission_count",
    "acceptedSubmissionCount": "accepted_submission_count",
}


def _extract_from_json(data: Any, result: dict[str, Any]) -> None:
    """Recursively search JSON data for program stats.

    Handles both flat dicts and Next.js serialized chunks (numeric keys with
    ``{b: <body>, u: <url>, s: <status>}`` shape).  Extracts submission counts,
    researcher lists from ``lastContributors`` / ``lastActivity``, and recurses
    into all nested structures.
    """
    if isinstance(data, dict):
        # ── Submission counts (camelCase → snake_case) ─────────────
        for camel_key, result_key in _SUBMISSION_KEY_MAP.items():
            if camel_key in data and isinstance(data[camel_key], (int, float)):
                val = int(data[camel_key])
                if val > 0:
                    old = result.get(result_key)
                    if old is None or val > old:
                        result[result_key] = val

        # ── Researcher count from lastContributors (preferred) ─────
        if "lastContributors" in data and isinstance(data["lastContributors"], list):
            seen_users: set[str] = set()
            for entry in data["lastContributors"]:
                user_id = entry.get("userId") or entry.get("userName")
                if user_id:
                    seen_users.add(user_id)
            if seen_users and result["researcher_count"] is None:
                result["researcher_count"] = len(seen_users)

        # ── Researcher count from lastActivity (fallback) ──────────
        if "lastActivity" in data and isinstance(data["lastActivity"], list):
            seen_users: set[str] = set()
            for entry in data["lastActivity"]:
                researcher = entry.get("researcher", {})
                user_id = (
                    researcher.get("userId") or researcher.get("userName")
                )
                if user_id:
                    seen_users.add(user_id)
            # Only use lastActivity if lastContributors didn't give us data
            if seen_users and result["researcher_count"] is None:
                result["researcher_count"] = len(seen_users)

        # ── Recurse into all values (handles Next.js chunk bodies) ─
        for value in data.values():
            _extract_from_json(value, result)

    elif isinstance(data, list):
        for item in data:
            _extract_from_json(item, result)


# ─── Unified entry point ──────────────────────────────────────────────

def scrape_program(url: str, platform: str) -> dict[str, Any]:
    """Scrape a program page and return extracted metrics.

    Args:
        url: The public program URL.
        platform: One of 'hackerone', 'intigriti'.

    Returns:
        Dict with scraped metrics (e.g., researcher_count).
    """
    if platform == "hackerone":
        return scrape_hackerone(url)
    elif platform == "intigriti":
        return scrape_intigriti(url)
    else:
        logger.warning("No scraper for platform '%s'", platform)
        return {}


def scrape_programs(
    programs: list[dict[str, Any]],
    progress_callback=None,
) -> list[dict[str, Any]]:
    """Scrape all programs and enrich them with scraped metrics.

    Iterates through programs, scrapes each public page, and merges the
    scraped data back into the program dict.  Returns the enriched list.
    """
    total = len(programs)
    for idx, prog in enumerate(programs, 1):
        if progress_callback:
            try:
                progress_callback(
                    "scraping", idx, total,
                    f"Scraping [{idx}/{total}] {prog.get('name', '?')}...",
                )
            except Exception:
                pass

        platform = prog.get("platform", "")
        url = prog.get("url", "")
        if not platform or not url:
            continue

        try:
            scraped = scrape_program(url, platform)
            for key, value in scraped.items():
                if value is not None:
                    prog[key] = value
        except Exception as e:
            logger.debug("Scrape error for %s (%s): %s", url, platform, e)

    if progress_callback:
        try:
            progress_callback(
                "scraping", total, total, f"Scraped {total} programs"
            )
        except Exception:
            pass

    return programs
