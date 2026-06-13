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

# ─── Focus Areas ────────────────────────────────────────────────────────

FOCUS_AREAS = {
    "api": {
        "name": "API Security",
        "tags": ["api", "rest", "graphql", "grpc"],
        "vulnerabilities": [
            "BOLA", "IDOR", "broken object level authorization",
            "BFLA", "broken function level authorization",
            "broken authentication", "token manipulation",
            "mass assignment", "insecure deserialization",
        ],
    },
    "llm": {
        "name": "LLM / AI Security",
        "tags": ["ai", "ml", "llm", "chatbot", "copilot", "assistant"],
        "vulnerabilities": [
            "prompt injection", "data leakage", "training data extraction",
            "excessive agency", "sensitive information disclosure",
            "model manipulation", "jailbreak",
        ],
    },
    "mobile": {
        "name": "Mobile App Security",
        "tags": ["android", "ios", "mobile", "apk", "ipa"],
        "vulnerabilities": [
            "insecure data storage", "ssl pinning bypass",
            "certificate validation", "intent injection",
            "insecure communication", "root detection bypass",
        ],
    },
}

# ─── Platform Metadata (for scoring) ────────────────────────────────────

PLATFORMS = {
    "hackerone": {
        "name": "HackerOne",
        "site": "hackerone.com",
        "competition_level": "extreme",
        "triage_speed_days": 5,
    },
    "intigriti": {
        "name": "Intigriti",
        "site": "intigriti.com",
        "competition_level": "low",
        "triage_speed_days": 1,
    },
    "bugcrowd": {
        "name": "Bugcrowd",
        "site": "bugcrowd.com",
        "competition_level": "moderate",
        "triage_speed_days": 3,
    },
    "yeswehack": {
        "name": "YesWeHack",
        "site": "yeswehack.com",
        "competition_level": "low",
        "triage_speed_days": 3,
    },
}

COMPETITION_SCORES = {
    "extreme": 10, "high": 7, "moderate": 4, "low": 2, "very_low": 1,
}

# ─── Web Search Queries ────────────────────────────────────────────────

SEARCH_QUERIES = [
    # New program launches — platform-specific
    ("site:hackerone.com \"bug bounty\" api security", "Platform: HackerOne"),
    ("site:intigriti.com \"bug bounty\" api security", "Platform: Intigriti"),
    ("site:bugcrowd.com \"bug bounty\" api security", "Platform: Bugcrowd"),
    ("site:yeswehack.com \"bug bounty\" api security", "Platform: YesWeHack"),

    # LLM/AI focus — platform-specific
    ("site:hackerone.com \"bug bounty\" llm ai prompt injection", "LLM: HackerOne"),
    ("site:intigriti.com \"bug bounty\" llm ai prompt injection", "LLM: Intigriti"),
    ("site:bugcrowd.com \"bug bounty\" llm ai prompt injection", "LLM: Bugcrowd"),
    ("site:yeswehack.com \"bug bounty\" llm ai prompt injection", "LLM: YesWeHack"),

    # Mobile focus — platform-specific
    ("site:hackerone.com \"bug bounty\" mobile app security", "Mobile: HackerOne"),
    ("site:intigriti.com \"bug bounty\" mobile app security", "Mobile: Intigriti"),
    ("site:bugcrowd.com \"bug bounty\" mobile app security", "Mobile: Bugcrowd"),
    ("site:yeswehack.com \"bug bounty\" mobile app security", "Mobile: YesWeHack"),

    # General — new launches and beginner-friendly
    ("new bug bounty programs launched 2025 2026 api llm mobile", "New Programs"),
    ("best bug bounty programs for beginners api security 2025", "Beginner-Friendly"),
]

# ─── Helpers ────────────────────────────────────────────────────────────

def find_platform_key(url_or_name: str) -> str | None:
    """Find which platform a URL or name belongs to."""
    text = (url_or_name or "").lower()
    for key, plat in PLATFORMS.items():
        if plat["site"] in text or plat["name"].lower() in text:
            return key
    for key in PLATFORMS:
        if key in text:
            return key
    return None

def score_program(program: dict) -> float:
    """Score a program. Higher = better opportunity."""
    platform_key = find_platform_key(program.get("url", "")) or find_platform_key(program.get("platform", ""))
    if not platform_key:
        return 0

    platform = PLATFORMS[platform_key]

    # Competition penalty (lower competition = higher score)
    comp_score = COMPETITION_SCORES.get(platform["competition_level"], 5)

    # Triage speed bonus (faster triage = higher score)
    triage_bonus = max(0, 10 - platform["triage_speed_days"])

    # Focus area bonus: LLM/AI is hottest opportunity right now
    focus_bonus_map = {"llm": 8, "mobile": 5, "api": 3}
    focus_bonus = sum(focus_bonus_map.get(area, 0) for area in program.get("focus_areas", []))

    # Payout bonus (higher max payout = more serious program)
    max_payout = program.get("max_payout_usd", 0) or 0
    payout_bonus = min(5, max_payout / 25000) if max_payout else 0

    return triage_bonus + focus_bonus - comp_score + payout_bonus

# ─── Web Search Mode ──────────────────────────────────────────────────

def filter_search_queries(platform_filter):
    """Filter search queries by platform. If no filter, return all."""
    if not platform_filter:
        return SEARCH_QUERIES

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

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in results:
        if r.get("url") not in seen:
            seen.add(r["url"])
            unique.append(r)

    logger.info("Web search found %d unique results", len(unique))
    return unique

# ─── Output Formatting ────────────────────────────────────────────────

def print_header():
    import sys
    print()
    print("╔══════════════════════════════════════════════════════════╗", flush=True)
    print("║       🎯 BoutyHunter — Bug Bounty Opportunity Finder     ║", flush=True)
    print("╠══════════════════════════════════════════════════════════╣", flush=True)
    print("║  Focus: API | LLM/AI | Mobile (Web excluded)           ║", flush=True)
    print("╚══════════════════════════════════════════════════════════╝", flush=True)
    sys.stdout.flush()

def comp_label(level):
    return {
        "extreme": "🔴 EXTREME", "high": "🟠 HIGH",
        "moderate": "🟡 MODERATE", "low": "🟢 LOW",
        "very_low": "🟢 VERY LOW",
    }.get(level, "?")

def print_programs(programs):
    """Print ranked programs with temporal signals."""
    if not programs:
        print("\n  No programs found.")
        return

    print()
    print("=" * 72)
    print("  📋 DISCOVERED PROGRAMS (Ranked by opportunity quality)")
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

# ─── Main ──────────────────────────────────────────────────────────────

def main():
    import argparse

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
    parser.add_argument(
        "--mode", "-m",
        choices=["all", "api", "search"],
        default="all",
        help="Scan mode (default: all)",
    )
    parser.add_argument(
        "--focus", "-f",
        nargs="+",
        choices=list(FOCUS_AREAS.keys()),
        help="Filter by focus area(s): api, llm, mobile",
    )
    parser.add_argument(
        "--platform", "-p",
        nargs="+",
        choices=list(PLATFORMS.keys()),
        help="Filter by platform(s): hackerone, intigriti, bugcrowd, yeswehack",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path for JSON results",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress log messages (show only results)",
    )
    parser.add_argument(
        "--status", "-s",
        action="store_true",
        help="Show database status: stored programs, recent changes, scan history",
    )

    args = parser.parse_args()

    # Adjust logging level based on quiet flag
    if args.quiet:
        logging.getLogger("boutyhunter").setLevel(logging.WARNING)

    print_header()

    # ─── Status Mode ──────────────────────────────────────────────
    if args.status:
        from db import init_db, get_all_programs, get_recent_changes, get_scan_history
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
                prog = get_all_programs()[:]
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

        return  # Exit after status display

    # ─── Initialize Database ──────────────────────────────────────
    from db import (
        init_db, upsert_program, get_all_programs, detect_changes,
        record_changes, get_recent_changes, record_scan, get_temporal_boost,
    )

    init_db()

    all_data = {
        "scan_date": datetime.now().isoformat(),
        "api_programs": [],
        "web_search_results": [],
        "changes_detected": 0,
        "new_programs": 0,
    }

    total_changes = 0
    new_count = 0

    # ─── Mode 1: API Discovery ────────────────────────────────────
    if args.mode in ("all", "api"):
        logger.info("Starting API-based program discovery...")
        from api_client import PlatformClient, load_config

        config = load_config(CONFIG_FILE)
        client = PlatformClient(config)
        programs = client.discover_programs(focus_filter=args.focus, platform_filter=args.platform)

        # Process each discovered program: detect changes, store, score with temporal boosts
        scored = []
        for p in programs:
            # Detect changes vs stored state
            changes = detect_changes(p)
            if changes:
                total_changes += len(changes)
                new_count += 1 if "new_program" in [c["change_type"] for c in changes] else 0

            # Store/update program with first_seen tracking
            existing = get_all_programs()
            old_row = None
            for ep in existing:
                if ep.get("url") == p.get("url"):
                    old_row = ep
                    break

            if old_row:
                p["first_seen"] = old_row.get("first_seen", datetime.now().isoformat())
            else:
                p["first_seen"] = datetime.now().isoformat()

            # Calculate base score + temporal boost
            base_score = score_program(p)
            temporal_boost = get_temporal_boost(p, days=7)
            final_score = round(base_score + temporal_boost, 1)

            # Set temporal signal flags for display
            p["score"] = final_score
            p["is_new_program"] = (datetime.now() - datetime.fromisoformat(p.get("first_seen", datetime.now().isoformat()))).days <= 7 if changes and "new_program" in [c["change_type"] for c in changes] else False

            # Store in DB
            prog_id = upsert_program(p)

            # Record changes
            if changes:
                record_changes(prog_id, changes)

            # Attach recent changes to display
            p["recent_changes"] = get_recent_changes(days=7, program_id=prog_id)[:5]

            scored.append(p)

        # Sort by score (highest first)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        print_programs(scored)
        all_data["api_programs"] = scored

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
    record_scan(
        mode=args.mode,
        programs_found=len(all_data.get("api_programs", [])),
        new_programs=new_count,
        changes_detected=total_changes,
    )

    all_data["changes_detected"] = total_changes
    all_data["new_programs"] = new_count

    # ─── Save to File ─────────────────────────────────────────────
    output_path = args.output or f"opportunity_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    print()
    print(f"  📄 Results saved to: {output_path}")
    if total_changes > 0:
        print(f"  🔄 Changes detected: {total_changes} ({new_count} new programs)")

if __name__ == "__main__":
    main()
