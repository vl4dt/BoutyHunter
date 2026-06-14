#!/usr/bin/env python3
"""
BoutyHunter — Database Layer

Persistent storage for discovered programs, change tracking, and scan history.
Uses SQLite for zero-dependency local persistence.

Schema:
  - programs: current state of all discovered programs
  - program_changes: history of detected changes (scope added, bounty increased, etc.)
  - scans: metadata about each scan run
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import sqlite3

logger = logging.getLogger("boutyhunter.db")

DB_FILE = Path(__file__).parent / "bounty_hunter.db"

# ─── Schema ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('hackerone','intigriti','bugcrowd','yeswehack')),
    url TEXT UNIQUE NOT NULL,
    focus_areas TEXT DEFAULT '[]',          -- JSON array: ["api","llm"]
    max_payout_usd INTEGER DEFAULT 0,
    description TEXT,
    scope_details TEXT,                     -- JSON: current scope details
    status TEXT DEFAULT 'active',           -- active, paused, ended, etc.
    score REAL DEFAULT 0,
    last_seen TEXT NOT NULL,                -- ISO timestamp of last discovery
    first_seen TEXT NOT NULL,               -- ISO timestamp when first discovered
    updated_at TEXT NOT NULL,               -- ISO timestamp of last update

    -- Temporal signals (what makes a program temporarily attractive)
    is_new_program INTEGER DEFAULT 0,       -- 1 if discovered in last 7 days
    scope_recently_expanded INTEGER DEFAULT 0,  -- 1 if scope changed recently
    bounty_increased INTEGER DEFAULT 0,     -- 1 if max payout went up
    has_active_event INTEGER DEFAULT 0,     -- 1 if there's a hacking contest/bug bash
    event_details TEXT,                     -- JSON: details about active events

    -- Tracking metadata
    scan_count INTEGER DEFAULT 0,           -- how many scans have seen this program
    last_change_type TEXT,                  -- most recent change detected
    last_change_at TEXT                    -- when the most recent change was detected
);

CREATE TABLE IF NOT EXISTS program_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER REFERENCES programs(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL,              -- new_program, scope_added, bounty_increased, etc.
    old_value TEXT,                         -- previous value (if applicable)
    new_value TEXT,                         -- new value (if applicable)
    detected_at TEXT NOT NULL               -- ISO timestamp when change was detected
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_time TEXT NOT NULL,                -- ISO timestamp
    mode TEXT DEFAULT 'all',                -- api, search, all
    programs_found INTEGER DEFAULT 0,       -- total programs discovered this scan
    new_programs INTEGER DEFAULT 0,         -- first-time discoveries
    changes_detected INTEGER DEFAULT 0,     -- program changes detected
    errors TEXT DEFAULT '[]'               -- JSON array of any errors encountered
);

CREATE INDEX IF NOT EXISTS idx_programs_platform ON programs(platform);
CREATE INDEX IF NOT EXISTS idx_programs_focus_areas ON programs(focus_areas);
CREATE INDEX IF NOT EXISTS idx_programs_status ON programs(status);
CREATE INDEX IF NOT EXISTS idx_program_changes_program_id ON program_changes(program_id);
CREATE INDEX IF NOT EXISTS idx_scans_scan_time ON scans(scan_time);
"""

# ─── Connection Helpers ────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    return conn

def init_db():
    """Initialize the database schema if it doesn't exist."""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("Database initialized at %s", DB_FILE)

# ─── Program Operations ────────────────────────────────────────────────

def upsert_program(program: dict[str, Any]) -> int:
    """Insert or update a program. Returns the program ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO programs (name, platform, url, focus_areas, max_payout_usd,
               description, scope_details, status, score, last_seen, first_seen, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                   name = excluded.name,
                   platform = excluded.platform,
                   focus_areas = excluded.focus_areas,
                   max_payout_usd = excluded.max_payout_usd,
                   description = excluded.description,
                   scope_details = excluded.scope_details,
                   status = excluded.status,
                   score = excluded.score,
                   last_seen = excluded.last_seen,
                   updated_at = excluded.updated_at,
                   scan_count = scan_count + 1
               RETURNING id""",
            (
                program["name"],
                program["platform"],
                program["url"],
                json.dumps(program.get("focus_areas", [])),
                program.get("max_payout_usd", 0),
                program.get("description", ""),
                json.dumps(program.get("scope_details", {})),
                program.get("status", "active"),
                program.get("score", 0),
                datetime.now().isoformat(),
                program.get("first_seen", datetime.now().isoformat()),
                datetime.now().isoformat(),
            ),
        )
        return cursor.fetchone()[0]

def get_program_by_url(url: str) -> dict[str, Any] | None:
    """Get a program by its URL."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM programs WHERE url = ?", (url,)
        ).fetchone()
        if not row:
            return None
        return _row_to_dict(row)

def get_all_programs(
    focus_filter: list[str] | None = None,
    platform_filter: list[str] | None = None,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Get all programs with optional filters."""
    query = "SELECT * FROM programs WHERE 1=1"
    params: list[Any] = []

    if focus_filter:
        # Use parameterized queries to avoid SQL injection
        for area in focus_filter:
            query += " AND focus_areas LIKE ?"
            params.append(f"%{area}%")
    if platform_filter:
        placeholders = ",".join("?" * len(platform_filter))
        query += f" AND platform IN ({placeholders})"
        params.extend(platform_filter)
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY score DESC, last_seen DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(r) for r in rows]

def delete_program(url: str) -> bool:
    """Delete a program by URL."""
    with get_connection() as conn:
        result = conn.execute("DELETE FROM programs WHERE url = ?", (url,))
        conn.commit()
        return result.rowcount > 0

# ─── Change Detection ──────────────────────────────────────────────────

CHANGE_TYPES = {
    "new_program": "New program discovered",
    "scope_added": "Scope expanded — new attack surface",
    "bounty_increased": "Max payout increased",
    "status_changed": "Program status changed",
    "event_started": "Hacking contest / bug bash started",
    "vdp_to_paid": "VDP converted to paid program",
}

def detect_changes(program: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect changes for a program by comparing with stored state."""
    old = get_program_by_url(program["url"])
    if not old:
        # Brand new program
        return [{"change_type": "new_program", "detected_at": datetime.now().isoformat()}]

    changes = []
    now = datetime.now()

    # scope_details may be a dict (from DB via _row_to_dict) or string (raw input)
    old_scope_raw = old.get("scope_details") or {}
    if isinstance(old_scope_raw, str):
        try:
            old_scope = json.loads(old_scope_raw)
        except (json.JSONDecodeError, TypeError):
            old_scope = {}
    else:
        old_scope = old_scope_raw

    new_scope = program.get("scope_details", {})
    if _scope_changed(old_scope, new_scope):
        changes.append({
            "change_type": "scope_added",
            "old_value": json.dumps(old_scope),
            "new_value": json.dumps(new_scope),
            "detected_at": now.isoformat(),
        })

    # Check bounty increase
    old_payout = old.get("max_payout_usd", 0) or 0
    new_payout = program.get("max_payout_usd", 0) or 0
    if new_payout > old_payout:
        changes.append({
            "change_type": "bounty_increased",
            "old_value": str(old_payout),
            "new_value": str(new_payout),
            "detected_at": now.isoformat(),
        })

    # Check status change
    old_status = old.get("status", "")
    new_status = program.get("status", "")
    if old_status != new_status:
        changes.append({
            "change_type": "status_changed",
            "old_value": old_status,
            "new_value": new_status,
            "detected_at": now.isoformat(),
        })

    # Check for active events (hacking contests, bug bashes)
    if program.get("has_active_event"):
        old_event_raw = old.get("event_details") or {}
        if isinstance(old_event_raw, str):
            try:
                old_event = json.loads(old_event_raw)
            except (json.JSONDecodeError, TypeError):
                old_event = {}
        else:
            old_event = old_event_raw

        changes.append({
            "change_type": "event_started",
            "old_value": json.dumps(old_event),
            "new_value": json.dumps(program.get("event_details") or {}),
            "detected_at": now.isoformat(),
        })

    return changes

def record_changes(program_id: int, changes: list[dict[str, Any]]):
    """Record detected changes to the database."""
    with get_connection() as conn:
        for change in changes:
            conn.execute(
                "INSERT INTO program_changes (program_id, change_type, old_value, new_value, detected_at) VALUES (?, ?, ?, ?, ?)",
                (
                    program_id,
                    change["change_type"],
                    change.get("old_value"),
                    change.get("new_value"),
                    change["detected_at"],
                ),
            )
        conn.commit()

def get_recent_changes(
    days: int = 7,
    program_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get changes detected in the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    query = "SELECT * FROM program_changes WHERE detected_at >= ?"
    params: list[Any] = [cutoff]

    if program_id is not None:
        query += " AND program_id = ?"
        params.append(program_id)

    query += " ORDER BY detected_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

# ─── Scan Tracking ─────────────────────────────────────────────────────

def record_scan(
    mode: str,
    programs_found: int,
    new_programs: int,
    changes_detected: int,
    errors: list[str] | None = None,
):
    """Record a scan run."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO scans (scan_time, mode, programs_found, new_programs, changes_detected, errors) VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                mode,
                programs_found,
                new_programs,
                changes_detected,
                json.dumps(errors or []),
            ),
        )
        conn.commit()

def get_scan_history(days: int = 30) -> list[dict[str, Any]]:
    """Get scan history for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM scans WHERE scan_time >= ? ORDER BY scan_time DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

# ─── Temporal Scoring Boosts ──────────────────────────────────────────

TEMPORAL_BOOSTS = {
    "new_program": 15,           # First 7 days — least competition
    "scope_added": 10,           # New attack surface not yet tested
    "bounty_increased": 8,       # Program owner investing more
    "event_started": 12,         # Hacking contest = increased payouts
    "vdp_to_paid": 6,            # Less crowded than established programs
}

def get_temporal_boost(program: dict[str, Any], days: int = 7) -> float:
    """Calculate temporal score boost based on recent changes."""
    program_id = None
    old_row = get_program_by_url(program.get("url", ""))
    if old_row:
        program_id = old_row["id"]

    if not program_id:
        # Brand new — maximum boost
        return TEMPORAL_BOOSTS["new_program"]

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT change_type FROM program_changes WHERE program_id = ? AND detected_at >= ?",
            (program_id, cutoff),
        ).fetchall()

    boost = 0.0
    for row in rows:
        change_type = row["change_type"]
        if change_type in TEMPORAL_BOOSTS:
            boost += TEMPORAL_BOOSTS[change_type]

    return boost

# ─── Helpers ────────────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a database row to a dictionary."""
    d = dict(row)
    # Parse JSON fields
    for key in ("focus_areas", "scope_details", "event_details"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d

def _scope_changed(old_scope: dict, new_scope: dict) -> bool:
    """Detect if scope has meaningfully changed."""
    old_assets = set(str(a).lower() for a in old_scope.get("assets", []))
    new_assets = set(str(a).lower() for a in new_scope.get("assets", []))

    # New assets added
    if new_assets - old_assets:
        return True

    # Scope description changed significantly
    old_desc = (old_scope.get("description") or "").strip().lower()
    new_desc = (new_scope.get("description") or "").strip().lower()
    if old_desc and new_desc and len(new_desc) > len(old_desc) * 1.2:
        return True

    return False
