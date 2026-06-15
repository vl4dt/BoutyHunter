#!/usr/bin/env python3
"""
BoutyHunter — Scan Orchestration & Web Search

Coordinates API scans, web search fallback, and produces scored results.
Imported by the TUI and CLI entry point.
"""

from __future__ import annotations

import json
import logging
import os
import re as _re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("boutyhunter.scanner")

# ─── Paths & Config ──────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
SEARCH_SCRIPT = Path("/home/vl4dt/.pi/agent/skills/re-search/scripts/search.py")

# ─── Web Search Queries ──────────────────────────────────────────────

SEARCH_QUERIES: list[tuple[str, str]] = [
    ('site:hackerone.com "bug bounty" inurl:/programs', "Platform: HackerOne"),
    ('site:hackerone.com/bug-bounty-programs', "Platform: HackerOne"),
    ('site:hackerone.com "api security" OR "API testing" bug bounty program', "Platform: HackerOne"),
    ('site:intigriti.com/programs bug bounty api', "Platform: Intigriti"),
    ('site:app.intigriti.com/programs bug bounty', "Platform: Intigriti"),
]

URL_EXCLUDE_PATTERNS = [
    "/blog/", "/blogs/", "/article/", "/articles/",
    "/researcher/", "/researchers/", "/resources/",
    "/levelup/", "/glossary/", "/learn/",
    "/reports/", "/report/",
]


def _cb(callback, phase, current, total, message):
    """Safe callback invoker."""
    if callback is not None:
        try:
            callback(phase, current, total, message)
        except Exception:
            pass


def is_program_url(url: str) -> bool:
    """Return True if the URL looks like a bug bounty program page."""
    url_lower = url.lower()
    for pattern in URL_EXCLUDE_PATTERNS:
        if pattern.lower() in url_lower:
            return False
    if "hackerone.com" in url_lower:
        if "/bug-bounty-programs" in url_lower:
            return False
        path = url_lower.split("hackerone.com", 1)[-1]
        if path and not path.startswith(("/reports/", "/blog/", "/resources/", "/learn/", "/programs")):
            return True
    if "intigriti.com" in url_lower and ("/programs/" in url_lower or "/program/" in url_lower):
        return True
    if "bugcrowd.com" in url_lower and ("/engagements/" in url_lower or "/engagement/" in url_lower):
        return True
    return False


def filter_search_queries(platform_filter: list[str] | None) -> list[tuple[str, str]]:
    """Filter web search queries by platform."""
    if not platform_filter:
        return SEARCH_QUERIES
    from constants import PLATFORMS

    filtered: list[tuple[str, str]] = []
    for query, category in SEARCH_QUERIES:
        for plat_key in platform_filter:
            site = PLATFORMS[plat_key]["site"]
            name_lower = PLATFORMS[plat_key]["name"].lower()
            if site in query.lower() or plat_key in category.lower():
                filtered.append((query, category))
                break
    return filtered


# ─── Web Search ──────────────────────────────────────────────────────

def run_web_search(platform_filter: list[str] | None = None, progress_callback=None) -> list[dict]:
    """Run web search for bug bounty programs. Returns filtered unique results."""
    import os
    search_path = Path(SEARCH_SCRIPT)
    if not search_path.exists():
        logger.warning("re-search skill not found at %s. Skipping web search.", search_path)
        return []

    queries = filter_search_queries(platform_filter)
    results: list[dict] = []

    for idx, (query, category) in enumerate(queries, 1):
        _cb(progress_callback, "web_search", idx, len(queries),
            f"Searching [{idx}/{len(queries)}] {category}...")
        try:
            # Use Popen with process group so we can kill on shutdown
            proc = subprocess.Popen(
                ["python3", str(search_path), query, "--max-results", "5"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True,
            )
            try:
                stdout, _ = proc.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                # Kill the entire process group
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                logger.warning("Web search timed out for query: %s", query[:50])
                continue

            if proc.returncode != 0:
                continue

            lines = stdout.strip().split("\n")
            current: dict | None = None
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Found"):
                    continue
                match = _re.match(r"##\s*\[(\d+)\]\s+(.+)", line)
                if match:
                    current = {"title": match.group(2).strip(), "category": category}
                    continue
                if (line.startswith("**URL:**") or line.startswith("URL:")) and current is not None:
                    url_val = line.replace("**URL:**", "").replace("URL:", "").strip()
                    current["url"] = url_val
                    results.append(current)
                    current = None
        except subprocess.TimeoutExpired:
            logger.warning("Web search timed out for query: %s", query[:50])
        except Exception as e:
            logger.error("Web search error for '%s': %s", query[:50], e)

    # Deduplicate and filter
    filtered = [r for r in results if is_program_url(r.get("url", ""))]
    seen: set[str] = set()
    unique: list[dict] = []
    for r in filtered:
        url = r.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(r)

    logger.info("Web search found %d program results (after filtering)", len(unique))
    return unique


# ─── Scan Orchestration ──────────────────────────────────────────────

def run_api_scan(
    client,
    focus_filter: list[str] | None = None,
    platform_filter: list[str] | None = None,
    progress_callback=None,  # callable(phase, current, total, message)
) -> tuple[list[dict], int, int]:
    """Run API-based program discovery. Returns (scored_programs, total_changes, new_count)."""
    from db import (
        init_db, upsert_program, get_all_programs, detect_changes,
        record_changes, get_recent_changes, get_temporal_boost,
    )
    from scoring import score_program

    init_db()
    programs = client.discover_programs(
        focus_filter=focus_filter,
        platform_filter=platform_filter,
        progress_callback=progress_callback,
    )
    _cb(progress_callback, "scoring", 0, len(programs),
        f"Scoring {len(programs)} programs...")

    scored: list[dict] = []
    total_changes = 0
    new_count = 0

    for idx, p in enumerate(programs, 1):
        _cb(progress_callback, "scoring", idx, len(programs),
            f"Processing [{idx}/{len(programs)}] {p.get('name', '?')}...")

        changes = detect_changes(p)
        if changes:
            total_changes += len(changes)
            change_types = [c["change_type"] for c in changes]
            new_count += 1 if "new_program" in change_types else 0

        existing = get_all_programs()
        old_row = next((ep for ep in existing if ep.get("url") == p.get("url")), None)
        p["first_seen"] = (
            old_row.get("first_seen", datetime.now().isoformat()) if old_row
            else datetime.now().isoformat()
        )

        base_score, breakdown = score_program(p)
        temporal_boost = get_temporal_boost(p, days=7)
        final_score = round(base_score + temporal_boost, 1)

        p["score_breakdown"] = breakdown
        if temporal_boost > 0:
            p["score_breakdown"].append(f"Temporal boost: active signal → +{temporal_boost:.1f}")

        p["score"] = final_score
        is_new = changes and "new_program" in change_types
        if is_new:
            first_dt = datetime.fromisoformat(p.get("first_seen", datetime.now().isoformat()))
            p["is_new_program"] = (datetime.now() - first_dt).days <= 7

        prog_id = upsert_program(p)
        if changes:
            record_changes(prog_id, changes)

        p["recent_changes"] = get_recent_changes(days=7, program_id=prog_id)[:5]
        scored.append(p)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    _cb(progress_callback, "scoring", len(programs), len(programs),
        f"Scored {len(scored)} programs ({new_count} new, {total_changes} changes)")
    return scored, total_changes, new_count


def run_full_scan(
    mode: str = "all",
    focus_filter: list[str] | None = None,
    platform_filter: list[str] | None = None,
    progress_callback=None,  # callable(phase, current, total, message)
) -> dict[str, Any]:
    """Run a full scan and return all data."""
    from api_client import PlatformClient, load_config

    result: dict[str, Any] = {
        "scan_date": datetime.now().isoformat(),
        "api_programs": [],
        "web_search_results": [],
        "changes_detected": 0,
        "new_programs": 0,
    }

    if mode in ("all", "api"):
        _cb(progress_callback, "init", 0, None, "Initializing scan...")
        config = load_config(CONFIG_FILE)
        client = PlatformClient(config)
        scored, total_changes, new_count = run_api_scan(
            client, focus_filter, platform_filter,
            progress_callback=progress_callback,
        )
        result["api_programs"] = scored
        result["changes_detected"] = total_changes
        result["new_programs"] = new_count

    if mode in ("all", "search"):
        _cb(progress_callback, "web_search", 0, None, "Starting web search...")
        web_results = run_web_search(platform_filter, progress_callback=progress_callback)
        result["web_search_results"] = web_results
        _cb(progress_callback, "web_search", len(web_results), None,
            f"Web search complete: {len(web_results)} results")

    # Record scan metadata
    from db import record_scan
    record_scan(
        mode=mode,
        programs_found=len(result.get("api_programs", [])),
        new_programs=result["new_programs"],
        changes_detected=result["changes_detected"],
    )

    _cb(progress_callback, "complete", None, None,
        f"Scan complete: {len(result['api_programs'])} programs, "
        f"{result['new_programs']} new, {result['changes_detected']} changes")
    return result


# ─── Headless CLI Helpers ────────────────────────────────────────────

def headless_scan(argv: list[str]) -> None:
    """Run a scan headlessly (no TUI) and print results."""
    import argparse
    from constants import FOCUS_AREAS, PLATFORMS

    clean_argv = [a for a in argv if a != "--scan"]

    parser = argparse.ArgumentParser(description="BoutyHunter — Headless Scan")
    parser.add_argument("--mode", "-m", choices=["all", "api", "search"], default="all")
    parser.add_argument("--focus", "-f", nargs="+", choices=list(FOCUS_AREAS.keys()))
    parser.add_argument("--platform", "-p", nargs="+", choices=list(PLATFORMS.keys()))
    parser.add_argument("--output", "-o", help="Output file path for JSON results")
    args = parser.parse_args(clean_argv)

    print("\n🎯 BoutyHunter — Running scan...")
    data = run_full_scan(mode=args.mode, focus_filter=args.focus, platform_filter=args.platform)

    programs = data.get("api_programs", [])
    if programs:
        print(f"\n{'=' * 60}")
        print(f"  Found {len(programs)} programs ({data['new_programs']} new)")
        print(f"{'=' * 60}")
        for i, p in enumerate(programs[:15], 1):
            signals = []
            if p.get("is_new_program"):
                signals.append("NEW")
            if p.get("has_active_event"):
                signals.append("EVENT")
            sig_str = f" [{', '.join(signals)}]" if signals else ""
            print(f"  #{i} [{p['score']:+.1f}]{sig_str} {p['name']} — ${p.get('max_payout_usd', 0):,}")
        if len(programs) > 15:
            print(f"  ... and {len(programs) - 15} more")

    output_path = args.output or f"opportunity_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n📄 Results saved to: {output_path}")


def print_status() -> None:
    """Print database status and exit."""
    from db import init_db, get_all_programs, get_recent_changes, get_scan_history
    from constants import FOCUS_AREAS

    init_db()
    programs = get_all_programs()
    changes = get_recent_changes(days=7)
    history = get_scan_history(days=30)

    print(f"\n  📊 DATABASE STATUS")
    print(f"  ────────────────")
    print(f"  Active programs: {len(programs)}")
    print(f"  Recent changes (7d): {len(changes)}")
    print(f"  Scans (30d): {len(history)}")

    if programs:
        print(f"\n  📋 STORED PROGRAMS")
        for i, p in enumerate(programs[:15], 1):
            focus = ", ".join(FOCUS_AREAS[f]["name"] for f in p.get("focus_areas", []) if f in FOCUS_AREAS)
            print(f"    {i}. {p['name']} ({p['platform']}) — ${p.get('max_payout_usd', 0):,} | {focus}")
        if len(programs) > 15:
            print(f"    ... and {len(programs) - 15} more")

    if changes:
        print(f"\n  🔄 RECENT CHANGES (last 7 days)")
        for c in changes[:20]:
            prog_name = "Unknown"
            for p in programs:
                if p.get("id") == c["program_id"]:
                    prog_name = p["name"]
                    break
            print(f"    [{c['detected_at'][:19]}] {prog_name}: {c['change_type'].replace('_', ' ').title()}")

    if history:
        print(f"\n  📈 SCAN HISTORY (last 30 days)")
        for s in history[:10]:
            print(
                f"    [{s['scan_time'][:19]}] mode={s['mode']} | "
                f"found={s['programs_found']} | new={s['new_programs']} | changes={s['changes_detected']}"
            )
