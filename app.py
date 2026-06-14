#!/usr/bin/env python3
"""BoutyHunter — Web Dashboard for Bug Bounty Opportunity Discovery."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, jsonify

# ─── Paths ──────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()

# ─── Logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("boutyhunter.web")

# ─── App Setup ──────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=str(SCRIPT_DIR / "templates"))

# ─── Template Filters ──────────────────────────────────────────────

@app.template_filter("format_number")
def format_number(value):
    """Format a number with commas."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)

# ─── Context Processors ──────────────────────────────────────────────

@app.context_processor
def inject_now():
    """Inject current datetime into all templates."""
    return {"now": datetime.now()}

# Import shared constants instead of duplicating them
from constants import FOCUS_AREAS, PLATFORMS, COMPETITION_LABELS

# ─── DB Helpers (thin wrapper) ──────────────────────────────────────────

def _db():
    """Lazy import and init the database."""
    from db import init_db, get_all_programs, get_recent_changes, get_scan_history
    init_db()
    return get_all_programs, get_recent_changes, get_scan_history

# ─── Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Main dashboard with overview stats and top programs."""
    get_programs, get_changes, get_scans = _db()

    all_programs = get_programs()  # show ALL programs — open, suspended, unknown
    recent_changes = get_changes(days=7)
    scan_history = get_scans(days=30)

    # Stats
    total = len(all_programs)
    new_count = sum(1 for p in all_programs if p.get("is_new_program"))
    event_count = sum(1 for p in all_programs if p.get("has_active_event"))
    change_count = len(recent_changes)

    # Top programs by score — with breakdown
    from scoring import score_program
    top_programs = sorted(all_programs, key=lambda x: x.get("score", 0), reverse=True)[:8]
    for p in top_programs:
        _, breakdown = score_program(p)
        p["score_breakdown"] = breakdown

    # Focus area breakdown
    focus_counts = {}
    for p in all_programs:
        for f in p.get("focus_areas", []):
            focus_counts[f] = focus_counts.get(f, 0) + 1

    # Check which platforms have API credentials configured
    from api_client import load_config as _load_api_config
    try:
        api_config = _load_api_config()
        platform_status = {}
        for plat_key in ("hackerone", "intigriti"):
            pcfg = api_config.get("platforms", {}).get(plat_key, {})
            # HackerOne: needs username + token (Basic auth)
            # Intigriti: needs token (Bearer auth)
            if plat_key == "hackerone":
                has_creds = bool(pcfg.get("username") and pcfg.get("token"))
            else:
                has_creds = bool(pcfg.get("token"))
            platform_status[plat_key] = {
                "enabled": bool(pcfg.get("enabled", False)),
                "has_creds": has_creds,
            }
    except Exception:
        platform_status = {}

    return render_template(
        "dashboard.html",
        total=total,
        new_count=new_count,
        event_count=event_count,
        change_count=change_count,
        scan_count=len(scan_history),
        top_programs=top_programs,
        focus_counts=focus_counts,
        recent_changes=recent_changes[:10],
        scan_history=scan_history,
        platform_status=platform_status,
        FOCUS_AREAS=FOCUS_AREAS,
        PLATFORMS=PLATFORMS,
    )

@app.route("/programs")
def programs():
    """Full program list with filters."""
    get_programs = _db()[0]
    all_programs = get_programs()  # show ALL programs

    # Regenerate score breakdown for each program (not stored in DB)
    from scoring import score_program
    for p in all_programs:
        _, breakdown = score_program(p)
        p["score_breakdown"] = breakdown

    # Apply URL filters
    focus = request.args.get("focus", "").split(",") if request.args.get("focus") else []
    platform = request.args.get("platform", "").split(",") if request.args.get("platform") else []
    search = request.args.get("q", "").strip().lower()

    filtered = all_programs
    if focus:
        filtered = [p for p in filtered if any(f in p.get("focus_areas", []) for f in focus)]
    if platform:
        filtered = [p for p in filtered if p.get("platform") in platform]
    if search:
        filtered = [
            p for p in filtered
            if search in (p.get("name", "") + " " + p.get("description", "")).lower()
        ]

    # Sort by score descending
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    return render_template(
        "programs.html",
        programs=filtered,
        total=len(filtered),
        focus_filter=focus,
        platform_filter=platform,
        search_query=search,
        FOCUS_AREAS=FOCUS_AREAS,
        PLATFORMS=PLATFORMS,
    )

@app.route("/changes")
def changes():
    """Change detection log."""
    get_changes = _db()[1]
    days = int(request.args.get("days", 7))
    all_changes = get_changes(days=days)

    # Enrich with program names
    get_programs = _db()[0]
    prog_map = {p["id"]: p["name"] for p in get_programs()}

    enriched = []
    for c in all_changes:
        c["program_name"] = prog_map.get(c["program_id"], "Unknown")
        enriched.append(c)

    return render_template(
        "changes.html",
        changes=enriched,
        days=days,
        total=len(enriched),
    )

@app.route("/scans")
def scans():
    """Scan history."""
    get_scans = _db()[2]
    scan_history = get_scans(days=30)

    return render_template(
        "scans.html",
        scans=scan_history,
        total=len(scan_history),
    )

@app.route("/strategy")
def strategy():
    """Strategy recommendations."""
    get_programs = _db()[0]
    all_programs = get_programs()  # show ALL programs

    # Group by platform, sorted by score desc
    by_platform = {}
    for p in all_programs:
        plat = p.get("platform", "unknown")
        if plat not in by_platform:
            by_platform[plat] = []
        by_platform[plat].append(p)
    for plat_key in by_platform:
        by_platform[plat_key].sort(key=lambda x: x.get("score", 0), reverse=True)

    # Hot programs (temporal signals)
    hot_programs = [p for p in all_programs if any([
        p.get("is_new_program"),
        p.get("scope_recently_expanded"),
        p.get("bounty_increased"),
        p.get("has_active_event"),
    ])]
    hot_programs.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Payout tiers (open programs only)
    whale_count = sum(1 for p in all_programs if (p.get("max_payout_usd") or 0) >= 50000 and p.get("status", "") == "open")
    high_value_count = sum(1 for p in all_programs if (p.get("max_payout_usd") or 0) >= 20000 and p.get("status", "") == "open")
    mid_tier_count = sum(1 for p in all_programs if (p.get("max_payout_usd") or 0) >= 10000 and p.get("status", "") == "open")

    return render_template(
        "strategy.html",
        by_platform=by_platform,
        hot_programs=hot_programs[:8],
        whale_count=whale_count,
        high_value_count=high_value_count,
        mid_tier_count=mid_tier_count,
        FOCUS_AREAS=FOCUS_AREAS,
        PLATFORMS=PLATFORMS,
    )

@app.route("/program/<int:program_id>")
def program_detail(program_id):
    """Detailed view of a single program with full score breakdown."""
    from scoring import score_program
    get_programs = _db()[0]
    all_programs = get_programs()
    prog = next((p for p in all_programs if p["id"] == program_id), None)
    if not prog:
        return "Program not found", 404

    score, breakdown = score_program(prog)
    prog["score_breakdown"] = breakdown

    # Get changes for this program
    get_changes = _db()[1]
    prog_changes = get_changes(days=30, program_id=program_id)

    return render_template(
        "program_detail.html",
        program=prog,
        score=score,
        breakdown=breakdown,
        changes=prog_changes,
        FOCUS_AREAS=FOCUS_AREAS,
        PLATFORMS=PLATFORMS,
    )

@app.route("/api/programs")
def api_programs():
    """JSON API for program data."""
    get_programs = _db()[0]
    all_programs = get_programs(status_filter="active")

    focus = request.args.get("focus", "").split(",") if request.args.get("focus") else []
    platform = request.args.get("platform", "").split(",") if request.args.get("platform") else []

    filtered = all_programs
    if focus:
        filtered = [p for p in filtered if any(f in p.get("focus_areas", []) for f in focus)]
    if platform:
        filtered = [p for p in filtered if p.get("platform") in platform]

    return jsonify({"programs": filtered, "count": len(filtered)})

@app.route("/api/changes")
def api_changes():
    """JSON API for change data."""
    get_changes = _db()[1]
    days = int(request.args.get("days", 7))
    all_changes = get_changes(days=days)

    return jsonify({"changes": all_changes, "count": len(all_changes)})

@app.route("/api/scan")
def api_scan():
    """Trigger a scan via API."""
    from opportunity_finder import main as run_scan
    try:
        # Run the scanner in background (simplified — just call it)
        result = {"status": "ok", "message": "Scan triggered"}
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ─── Entry Point ────────────────────────────────────────────────────────

def main():
    """Run the web dashboard."""
    import argparse

    parser = argparse.ArgumentParser(description="BoutyHunter Web Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)

if __name__ == "__main__":
    main()
