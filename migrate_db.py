#!/usr/bin/env python3
"""
BoutyHunter — Database Migration Script

Migrates bounty_hunter.db to the latest schema:
  - Removes restrictive CHECK(platform IN ('hackerone','intigriti'))
  - Backfills temporal signal flags from historical changes
  - Preserves all existing data and indexes

Usage:
    python3 migrate_db.py
"""

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_FILE = Path(__file__).parent / "bounty_hunter.db"


def migrate():
    conn = sqlite3.connect(str(DB_FILE))
    conn.execute("PRAGMA journal_mode=WAL")

    # ── 0. Ensure old table has all columns (schema evolved over time) ──
    print("Ensuring old schema is complete...")
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(programs)").fetchall()}
    missing_cols = [
        ("researcher_count", "INTEGER DEFAULT NULL"),
        ("is_new_program", "INTEGER DEFAULT 0"),
        ("scope_recently_expanded", "INTEGER DEFAULT 0"),
        ("bounty_increased", "INTEGER DEFAULT 0"),
        ("has_active_event", "INTEGER DEFAULT 0"),
        ("event_details", "TEXT"),
        ("last_change_type", "TEXT"),
        ("last_change_at", "TEXT"),
    ]
    for col, coltype in missing_cols:
        if col not in existing_cols:
            print(f"  Adding missing column: {col}")
            conn.execute(f"ALTER TABLE programs ADD COLUMN {col} {coltype}")
    conn.commit()

    # ── 1. Create new tables (no CHECK constraint) ────────────────
    print("Creating new schema...")
    create_stmts = [
        """CREATE TABLE programs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            focus_areas TEXT DEFAULT '[]',
            max_payout_usd INTEGER DEFAULT 0,
            description TEXT,
            scope_details TEXT,
            status TEXT DEFAULT 'active',
            score REAL DEFAULT 0,
            last_seen TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_new_program INTEGER DEFAULT 0,
            scope_recently_expanded INTEGER DEFAULT 0,
            bounty_increased INTEGER DEFAULT 0,
            has_active_event INTEGER DEFAULT 0,
            event_details TEXT,
            researcher_count INTEGER DEFAULT NULL,
            scan_count INTEGER DEFAULT 0,
            last_change_type TEXT,
            last_change_at TEXT
        )""",
        """CREATE TABLE program_changes_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER REFERENCES programs(id) ON DELETE CASCADE,
            change_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            detected_at TEXT NOT NULL
        )""",
        """CREATE TABLE scans_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL,
            mode TEXT DEFAULT 'all',
            programs_found INTEGER DEFAULT 0,
            new_programs INTEGER DEFAULT 0,
            changes_detected INTEGER DEFAULT 0,
            errors TEXT DEFAULT '[]'
        )""",
    ]
    for stmt in create_stmts:
        conn.execute(stmt)
    conn.commit()

    # ── 2. Copy data ──────────────────────────────────────────────
    print("Copying programs...")
    conn.execute("""
        INSERT INTO programs_new (id, name, platform, url, focus_areas, max_payout_usd,
            description, scope_details, status, score, last_seen, first_seen, updated_at,
            is_new_program, scope_recently_expanded, bounty_increased, has_active_event,
            event_details, researcher_count, scan_count, last_change_type, last_change_at)
        SELECT id, name, platform, url, focus_areas, max_payout_usd,
            description, scope_details, status, score, last_seen, first_seen, updated_at,
            is_new_program, scope_recently_expanded, bounty_increased, has_active_event,
            event_details, researcher_count, scan_count, last_change_type, last_change_at
        FROM programs
    """)

    print("Copying program_changes...")
    conn.execute("""
        INSERT INTO program_changes_new (id, program_id, change_type, old_value, new_value, detected_at)
        SELECT id, program_id, change_type, old_value, new_value, detected_at
        FROM program_changes
    """)

    print("Copying scans...")
    conn.execute("""
        INSERT INTO scans_new (id, scan_time, mode, programs_found, new_programs, changes_detected, errors)
        SELECT id, scan_time, mode, programs_found, new_programs, changes_detected, errors
        FROM scans
    """)
    conn.commit()

    # ── 3. Backfill temporal signals from historical changes ───────
    print("Backfilling temporal signal flags...")
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()

    new_count = conn.execute(
        "UPDATE programs_new SET is_new_program = 1 WHERE first_seen >= ? AND is_new_program != 1",
        (cutoff,)
    ).rowcount
    print(f"  is_new_program: {new_count} updated")

    scope_ids = conn.execute(
        "SELECT DISTINCT program_id FROM program_changes_new WHERE change_type = 'scope_added' AND detected_at >= ?",
        (cutoff,)
    ).fetchall()
    if scope_ids:
        ph = ",".join("?" * len(scope_ids))
        conn.execute(f"UPDATE programs_new SET scope_recently_expanded = 1 WHERE id IN ({ph}) AND scope_recently_expanded != 1",
                     [r[0] for r in scope_ids])
    print(f"  scope_recently_expanded: {len(scope_ids)} updated")

    bounty_ids = conn.execute(
        "SELECT DISTINCT program_id FROM program_changes_new WHERE change_type = 'bounty_increased' AND detected_at >= ?",
        (cutoff,)
    ).fetchall()
    if bounty_ids:
        ph = ",".join("?" * len(bounty_ids))
        conn.execute(f"UPDATE programs_new SET bounty_increased = 1 WHERE id IN ({ph}) AND bounty_increased != 1",
                     [r[0] for r in bounty_ids])
    print(f"  bounty_increased: {len(bounty_ids)} updated")

    event_ids = conn.execute(
        "SELECT DISTINCT program_id FROM program_changes_new WHERE change_type IN ('event_started', 'vdp_to_paid') AND detected_at >= ?",
        (cutoff,)
    ).fetchall()
    if event_ids:
        ph = ",".join("?" * len(event_ids))
        conn.execute(f"UPDATE programs_new SET has_active_event = 1 WHERE id IN ({ph}) AND has_active_event != 1",
                     [r[0] for r in event_ids])
    print(f"  has_active_event: {len(event_ids)} updated")

    # last_change_type / last_change_at: most recent change per program
    conn.execute("""
        UPDATE programs_new SET
            last_change_type = (
                SELECT pc.change_type FROM program_changes_new pc
                WHERE pc.program_id = programs_new.id
                ORDER BY pc.detected_at DESC LIMIT 1
            ),
            last_change_at = (
                SELECT pc.detected_at FROM program_changes_new pc
                WHERE pc.program_id = programs_new.id
                ORDER BY pc.detected_at DESC LIMIT 1
            )
        WHERE id IN (SELECT DISTINCT program_id FROM program_changes_new)
    """)
    changed_count = conn.execute(
        "SELECT COUNT(*) FROM programs_new WHERE last_change_type IS NOT NULL"
    ).fetchone()[0]
    print(f"  last_change_*: {changed_count} updated")
    conn.commit()

    # ── 4. Swap tables ────────────────────────────────────────────
    print("Swapping tables...")
    conn.execute("DROP TABLE programs")
    conn.execute("ALTER TABLE programs_new RENAME TO programs")
    conn.execute("DROP TABLE program_changes")
    conn.execute("ALTER TABLE program_changes_new RENAME TO program_changes")
    conn.execute("DROP TABLE scans")
    conn.execute("ALTER TABLE scans_new RENAME TO scans")
    conn.commit()

    # ── 5. Recreate indexes (SQLite auto-renames them on table rename,
    #     but since we didn't create any on _new tables, build fresh) ──
    print("Recreating indexes...")
    for stmt in [
        "CREATE INDEX idx_programs_platform ON programs(platform)",
        "CREATE INDEX idx_programs_focus_areas ON programs(focus_areas)",
        "CREATE INDEX idx_programs_status ON programs(status)",
        "CREATE INDEX idx_program_changes_program_id ON program_changes(program_id)",
        "CREATE INDEX idx_scans_scan_time ON scans(scan_time)",
    ]:
        conn.execute(stmt)
    conn.commit()

    # ── 6. Verify ─────────────────────────────────────────────────
    print("\nVerification:")
    for table in ("programs", "program_changes", "scans"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='programs' AND type='table'"
    ).fetchone()[0]
    if "CHECK" in schema:
        print("  WARNING: CHECK constraint still present!")
        sys.exit(1)
    else:
        print("  CHECK constraint removed ✓")

    # Verify columns
    cols = [r[1] for r in conn.execute("PRAGMA table_info(programs)").fetchall()]
    expected = ["id", "name", "platform", "url", "focus_areas", "max_payout_usd",
                "description", "scope_details", "status", "score", "last_seen",
                "first_seen", "updated_at", "is_new_program", "scope_recently_expanded",
                "bounty_increased", "has_active_event", "event_details",
                "researcher_count", "scan_count", "last_change_type", "last_change_at"]
    if cols == expected:
        print(f"  programs columns: {len(cols)} ✓")
    else:
        print(f"  WARNING: column mismatch!")
        print(f"    expected: {expected}")
        print(f"    got:      {cols}")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
