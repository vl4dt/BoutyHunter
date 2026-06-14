#!/usr/bin/env python3
"""
BoutyHunter — Bug Bounty Opportunity Finder

Discovers bug bounty programs dynamically via platform APIs (Bugcrowd, YesWeHack,
Intigriti) and falls back to web search. Programs are stored in a local SQLite
database for change tracking over time. Scores include temporal boosts for
newly discovered programs, scope expansions, bounty increases, and active events.

Usage:
    python3 opportunity_finder.py                          # Full scan (API + web search)
    python3 opportunity_finder.py --focus api llm          # Only API + LLM programs
    python3 opportunity_finder.py --platform bugcrowd      # Only Bugcrowd programs
    python3 opportunity_finder.py -q                       # Quiet mode
    python3 opportunity_finder.py -o results.json          # Save to file

Setup:
  1. Edit config.yaml with your API credentials (optional — web search works without them)
  2. Run the scanner anytime — it tracks changes across runs automatically
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.yaml"
SEARCH_SCRIPT = "/home/vl4dt/.pi/agent/skills/re-search/scripts/search.py"

# ─── Logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("boutyhunter")

# ─── Web Search Queries (target program pages only) ──────────────

SEARCH_QUERIES = [
    # HackerOne — program listing and individual programs
    ('site:hackerone.com "bug bounty" inurl:/programs', "Platform: HackerOne"),
    ('site:hackerone.com/bug-bounty-programs', "Platform: HackerOne"),
    ('site:hackerone.com "api security" OR "API testing" bug bounty program', "Platform: HackerOne"),

    # Intigriti — program pages only
    ('site:intigriti.com/programs bug bounty api', "Platform: Intigriti"),
    ('site:app.intigriti.com/programs bug bounty', "Platform: Intigriti"),

    # Bugcrowd — engagement pages only
    ('site:bugcrowd.com/engagements bug bounty api', "Platform: Bugcrowd"),
    ('site:bugcrowd.com "api security" OR "API testing" program', "Platform: Bugcrowd"),

    # YesWeHack — program pages only
    ('site:yeswehack.com/programs bug bounty api', "Platform: YesWeHack"),
    ('site:yeswehack.com "bug bounty" program listing', "Platform: YesWeHack"),
]

# ─── URL Filters (exclude non-program content) ──────────────────────

URL_EXCLUDE_PATTERNS = [
    # Blog posts and articles
    "/blog/", "/blogs/", "/article/", "/articles/",
    "/researcher/", "/researchers/", "/resources/",
    "/levelup/", "/glossary/", "/learn/",
    # Vulnerability reports
    "/reports/", "/report/",
]

def is_program_url(url: str) -> bool:
    """Check if a URL points to an actual bug bounty program (not blog/report/article)."""
    url_lower = url.lower()

    for pattern in URL_EXCLUDE_PATTERNS:
        if pattern.lower() in url_lower:
            return False

    # HackerOne: /<program-slug> (top-level path segment, not /reports/ or /blog/)
    if "hackerone.com" in url_lower:
        if "/bug-bounty-programs" in url_lower:
            return False
        path = url_lower.split("hackerone.com", 1)[-1]
        if path and not path.startswith(("/reports/", "/blog/", "/resources/", "/learn/", "/programs")):
            return True

    # Intigriti: /programs/<slug>
    if "intigriti.com" in url_lower and ("/programs/" in url_lower or "/program/" in url_lower):
        return True

    # Bugcrowd: /engagements/<slug>
    if "bugcrowd.com" in url_lower and ("/engagements/" in url_lower or "/engagement/" in url_lower):
        return True

    # YesWeHack: /programs/<slug> or /program/
    if "yeswehack.com" in url_lower and ("/programs/" in url_lower or "/program/" in url_lower):
        return True

    return False

# ─── Web Search Mode ──────────────────────────────────────────────

def filter_search_queries(platform_filter):
    """Filter search queries by platform. If no filter, return all."""
    if not platform_filter:
        return SEARCH_QUERIES

    from constants import PLATFORMS

    filtered = []
    for query, category in SEARCH_QUERIES:
        for plat_key in platform_filter:
            site = PLATFORMS[plat_key]["site"]
            name_lower = PLATFORMS[plat_key]["name"].lower()
            if site in query.lower() or plat_key in category.lower():
                filtered.append((query, category))
                break
    return filtered

def run_web_search(platform_filter=None):
    """Search the web for new opportunities."""
    search_path = Path(SEARCH_SCRIPT)
    if not search_path.exists():
        logger.warning("re-search skill not found at %s. Skipping web search.", search_path)
        return []

    queries = filter_search_queries(platform_filter)
    results = []

    for query, category in queries:
        try:
            proc = subprocess.run(
                ["python3", str(search_path), query, "--max-results", "5"],
                capture_output=True, text=True, timeout=45,
            )
            if proc.returncode != 0:
                continue

            import re as regex_module
            lines = proc.stdout.strip().split("\n")
            current = None
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Found"):
                    continue
                match = regex_module.match(r"##\s*\[(\d+)\]\s+(.+)", line)
                if match:
                    current = {"title": match.group(2).strip(), "category": category}
                    continue
                if (line.startswith("**URL:**") or line.startswith("URL:")) and current is not None:
                    url_val = line.replace("**URL:**", "").replace("URL:", "").strip()
                    current["url"] = url_val
                    results.append(current)
                    current = None
                    continue

        except subprocess.TimeoutExpired:
            logger.warning("Web search timed out for query: %s", query[:50])
        except Exception as e:
            logger.error("Web search error for '%s': %s", query[:50], e)

    # Filter: keep only actual program URLs
    filtered = [r for r in results if is_program_url(r.get("url", ""))]
    excluded_count = len(results) - len(filtered)
    if excluded_count > 0:
        logger.info("Filtered out %d non-program results (blogs, reports, articles)", excluded_count)

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in filtered:
        if r.get("url") not in seen:
            seen.add(r["url"])
            unique.append(r)

    logger.info("Web search found %d program results (after filtering)", len(unique))
    return unique

# ─── Output Formatting ──────────────────────────────────────────────

def print_header():
    import sys
    from constants import FOCUS_AREAS

    focus_names = " | ".join(FOCUS_AREAS[f]["name"] for f in ("api", "llm", "mobile"))
    print()
    print("╔════════════════════════════════════════════════════════════════╗", flush=True)
    print("║       🎯 BoutyHunter — Bug Bounty Opportunity Finder           ║", flush=True)
    print("╠════════════════════════════════════════════════════════════════╣", flush=True)
    print(f"║  Focus: {focus_names}                                    ║", flush=True)
    print("╚════════════════════════════════════════════════════════════════╝", flush=True)
    sys.stdout.flush()

def comp_label(level):
    return {
        "extreme": "🔴 EXTREME", "high": "🟠 HIGH",
        "moderate": "🟡 MODERATE", "low": "🟢 LOW",
        "very_low": "🟢 VERY LOW",
    }.get(level, "?")

def print_programs(programs):
    """Print ranked programs with temporal signals and score breakdown."""
    from constants import FOCUS_AREAS, PLATFORMS
    from scoring import find_platform_key

    if not programs:
        print("\n  No programs found.")
        return

    print()
    print("=" * 72)
    print("  📋 DISCOVERED PROGRAMS (Ranked by opportunity quality)")
    print("     Higher score = better opportunity — see breakdown below each")
    print("=" * 72)

    for i, p in enumerate(programs, 1):
        focus_tags = ", ".join(FOCUS_AREAS[f]["name"] for f in p.get("focus_areas", []) if f in FOCUS_AREAS)
        platform_key = find_platform_key(p.get("url", "")) or find_platform_key(p.get("platform", ""))
        comp_level = PLATFORMS[platform_key]["competition_level"] if platform_key else "unknown"

        # Temporal signals
        temporal_signals = []
        if p.get("is_new_program"):
            temporal_signals.append("🆕 NEW")
        if p.get("scope_recently_expanded"):
            temporal_signals.append("📈 SCOPE EXPANDED")
        if p.get("bounty_increased"):
            temporal_signals.append("💰 BOUNTY UP")
        if p.get("has_active_event"):
            event = p.get("event_details", {}) or {}
            event_type = event.get("type", "EVENT").replace("_", " ").upper()
            temporal_signals.append(f"🔥 {event_type}")

        signal_str = f" [{', '.join(temporal_signals)}]" if temporal_signals else ""

        print(f"\n  #{i} [{p['score']:+.1f}]{signal_str} {p['name']}")
        print(f"      Platform: {PLATFORMS[platform_key]['name'] if platform_key else 'Unknown'} | Focus: {focus_tags}")
        print(f"      Competition: {comp_label(comp_level)}")
        print(f"      Max Payout: ${p.get('max_payout_usd', 0):,} USD")

        # Score breakdown — WHY this rank
        reasons = p.get("score_breakdown", [])
        if reasons:
            print(f"      ── Why #{i}? ──")
            for reason in reasons:
                print(f"         • {reason}")

        # Show scope details if available
        scope = p.get("scope_details", {}) or {}
        if scope.get("assets"):
            assets_str = ", ".join(scope["assets"][:5])
            if len(scope["assets"]) > 5:
                assets_str += f" (+{len(scope['assets']) - 5} more)"
            print(f"      Scope: {assets_str}")

        # Show event details if available
        if p.get("has_active_event") and p.get("event_details"):
            ed = p["event_details"]
            if isinstance(ed, dict):
                print(f"      Event: {ed.get('type', 'unknown').replace('_', ' ').title()} — {ed.get('source_text', '')[:100]}")

        # Show recent changes if available
        recent_changes = p.get("recent_changes", [])
        if recent_changes:
            change_strs = [f"{c['change_type'].replace('_', ' ').title()}" for c in recent_changes[:3]]
            print(f"      Recent Changes: {', '.join(change_strs)}")

        if p.get("description"):
            desc = p["description"][:120] + "..." if len(p["description"]) > 120 else p["description"]
            print(f"      Notes: {desc}")

        print(f"      URL: {p['url']}")

def print_search_results(results):
    """Print web search results."""
    if not results:
        print("\n  No new opportunities found via web search.")
        return

    print()
    print("=" * 72)
    print("  🔍 WEB SEARCH — New Opportunities & Articles")
    print("=" * 72)

    for i, r in enumerate(results, 1):
        category = r.get("category", "General")
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        print(f"\n  #{i} [{category}] {title}")
        if url:
            print(f"      URL: {url}")

def print_strategy(programs):
    """Print strategy recommendations."""
    from constants import FOCUS_AREAS, PLATFORMS
    from scoring import find_platform_key

    if not programs:
        return

    print()
    print("=" * 72)
    print("  🎯 STRATEGY RECOMMENDATIONS")
    print("=" * 72)

    # Group by platform
    intigriti = [p for p in programs if find_platform_key(p.get("url", "")) == "intigriti"]
    llm_progs = [p for p in programs if "llm" in p.get("focus_areas", [])]
    api_progs = [p for p in programs if "api" in p.get("focus_areas", [])]
    mobile_progs = [p for p in programs if "mobile" in p.get("focus_areas", [])]

    # Hot signals — programs with temporal boosts
    hot_programs = [p for p in programs if any([
        p.get("is_new_program"),
        p.get("scope_recently_expanded"),
        p.get("bounty_increased"),
        p.get("has_active_event"),
    ])]

    print()
    if intigriti:
        print("  ✅ START HERE — Intigriti (lowest competition, fastest triage):")
        for p in intigriti[:5]:
            print(f"     • {p['name']} → ${p.get('max_payout_usd', 0):,}")

    if hot_programs:
        print()
        print("  🔥 HOT SIGNALS — Temporarily attractive programs:")
        for p in hot_programs[:5]:
            signals = []
            if p.get("is_new_program"):
                signals.append("new")
            if p.get("scope_recently_expanded"):
                signals.append("scope expanded")
            if p.get("bounty_increased"):
                signals.append("bounty up")
            if p.get("has_active_event"):
                ed = p.get("event_details", {}) or {}
                signals.append(f"event: {ed.get('type', 'unknown').replace('_', ' ')}")
            print(f"     • {p['name']} ({', '.join(signals)}) → ${p.get('max_payout_usd', 0):,}")

    if llm_progs:
        print()
        print("  🤖 LLM/AI OPPORTUNITIES (emerging field, least competition):")
        for p in llm_progs[:5]:
            plat = find_platform_key(p.get("url", ""))
            plat_name = PLATFORMS[plat]["name"] if plat else "Unknown"
            print(f"     • {p['name']} ({plat_name}) → ${p.get('max_payout_usd', 0):,}")

    if api_progs:
        print()
        print("  🔌 API OPPORTUNITIES (your backend dev experience is a massive advantage):")
        for p in api_progs[:5]:
            plat = find_platform_key(p.get("url", ""))
            plat_name = PLATFORMS[plat]["name"] if plat else "Unknown"
            print(f"     • {p['name']} ({plat_name}) → ${p.get('max_payout_usd', 0):,}")

    if mobile_progs:
        print()
        print("  📱 MOBILE OPPORTUNITIES (specialized tooling barrier = fewer hunters):")
        for p in mobile_progs[:5]:
            plat = find_platform_key(p.get("url", ""))
            plat_name = PLATFORMS[plat]["name"] if plat else "Unknown"
            print(f"     • {p['name']} ({plat_name}) → ${p.get('max_payout_usd', 0):,}")

# ─── Scan Orchestration ──────────────────────────────────────────────

def run_api_scan(client, args_focus=None, args_platform=None):
    """Run the API-based program discovery and return scored programs."""
    from db import (
        init_db, upsert_program, get_all_programs, detect_changes,
        record_changes, get_recent_changes, record_scan, get_temporal_boost,
    )
    from scoring import score_program

    init_db()

    programs = client.discover_programs(focus_filter=args_focus, platform_filter=args_platform)

    scored = []
    total_changes = 0
    new_count = 0

    for p in programs:
        # Detect changes vs stored state
        changes = detect_changes(p)
        if changes:
            total_changes += len(changes)
            new_count += 1 if "new_program" in [c["change_type"] for c in changes] else 0

        # Track first_seen
        existing = get_all_programs()
        old_row = next((ep for ep in existing if ep.get("url") == p.get("url")), None)
        p["first_seen"] = old_row.get("first_seen", datetime.now().isoformat()) if old_row else datetime.now().isoformat()

        # Calculate base score + temporal boost
        base_score, breakdown = score_program(p)
        temporal_boost = get_temporal_boost(p, days=7)
        final_score = round(base_score + temporal_boost, 1)

        p["score_breakdown"] = breakdown
        if temporal_boost > 0:
            p["score_breakdown"].append(f"Temporal boost: active signal → +{temporal_boost:.1f}")

        p["score"] = final_score
        is_new = changes and "new_program" in [c["change_type"] for c in changes]
        if is_new:
            p["is_new_program"] = (datetime.now() - datetime.fromisoformat(p.get("first_seen", datetime.now().isoformat()))).days <= 7

        # Store in DB
        prog_id = upsert_program(p)

        # Record changes
        if changes:
            record_changes(prog_id, changes)

        p["recent_changes"] = get_recent_changes(days=7, program_id=prog_id)[:5]
        scored.append(p)

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored, total_changes, new_count

# ─── Main ──────────────────────────────────────────────────────────────

def main():
    import argparse
    from constants import FOCUS_AREAS, PLATFORMS

    parser = argparse.ArgumentParser(
        description="Find and rank bug bounty opportunities.",
        epilog="""
Examples:
  %(prog)s                                    # Full scan (API + web search)
  %(prog)s --mode api                         # Only API discovery
  %(prog)s --mode search                      # Only web search for new programs
  %(prog)s --focus api llm                    # Filter by focus area
  %(prog)s --platform intigriti yeswehack     # Filter by platform
  %(prog)s -p hackerone -f llm                # HackerOne LLM programs only
  %(prog)s -o results.json                    # Save to file
        """,
    )
    parser.add_argument("--mode", "-m", choices=["all", "api", "search"], default="all")
    parser.add_argument("--focus", "-f", nargs="+", choices=list(FOCUS_AREAS.keys()))
    parser.add_argument("--platform", "-p", nargs="+", choices=list(PLATFORMS.keys()))
    parser.add_argument("--output", "-o", help="Output file path for JSON results")
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument("--status", "-s", action="store_true")

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger("boutyhunter").setLevel(logging.WARNING)

    print_header()

    # ─── Status Mode ──────────────────────────────────────────────
    if args.status:
        _print_status(args)
        return

    all_data = {
        "scan_date": datetime.now().isoformat(),
        "api_programs": [],
        "web_search_results": [],
        "changes_detected": 0,
        "new_programs": 0,
    }

    # ─── Mode 1: API Discovery ────────────────────────────────────
    if args.mode in ("all", "api"):
        logger.info("Starting API-based program discovery...")
        from api_client import PlatformClient, load_config

        config = load_config(CONFIG_FILE)
        client = PlatformClient(config)
        scored, total_changes, new_count = run_api_scan(client, args.focus, args.platform)

        print_programs(scored)
        all_data["api_programs"] = scored
        all_data["changes_detected"] = total_changes
        all_data["new_programs"] = new_count

    # ─── Mode 2: Web Search ───────────────────────────────────────
    if args.mode in ("all", "search"):
        logger.info("Starting web search for new opportunities...")
        results = run_web_search(args.platform)
        print_search_results(results)
        all_data["web_search_results"] = results

    # ─── Strategy Recommendations ─────────────────────────────────
    if all_data["api_programs"]:
        print_strategy(all_data["api_programs"])

    # ─── Record Scan Metadata ─────────────────────────────────────
    from db import record_scan
    record_scan(
        mode=args.mode,
        programs_found=len(all_data.get("api_programs", [])),
        new_programs=all_data["new_programs"],
        changes_detected=all_data["changes_detected"],
    )

    # ─── Save to File ─────────────────────────────────────────────
    output_path = args.output or f"opportunity_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print()
    print(f"  📄 Results saved to: {output_path}")
    if all_data["changes_detected"] > 0:
        print(f"  🔄 Changes detected: {all_data['changes_detected']} ({all_data['new_programs']} new programs)")

def _print_status(args):
    """Print database status (extracted from main for clarity)."""
    from db import init_db, get_all_programs, get_recent_changes, get_scan_history
    from constants import FOCUS_AREAS

    init_db()

    programs = get_all_programs(status_filter="active")
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
            print(f"    [{s['scan_time'][:19]}] mode={s['mode']} | found={s['programs_found']} | new={s['new_programs']} | changes={s['changes_detected']}")

if __name__ == "__main__":
    main()
