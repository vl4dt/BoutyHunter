#!/usr/bin/env python3
"""BoutyHunter — Terminal User Interface for Bug Bounty Opportunity Finder."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    TabPane,
    TabbedContent,
)
from textual.css.query import NoMatches

logger = logging.getLogger("boutyhunter")

# ---------------------------------------------------------------------------
# Import constants at module level so lookups always work
# ---------------------------------------------------------------------------
try:
    from constants import PLATFORMS, FOCUS_AREAS
except ImportError:
    PLATFORMS: dict[str, Any] = {}
    FOCUS_AREAS: dict[str, Any] = {}

# Pre-build lookup maps once at startup
_COMPETITION_MAP = {k: v.get("competition_level", "-") for k, v in PLATFORMS.items()}
_FOCUS_NAME_MAP = {k: v.get("name", k) for k, v in FOCUS_AREAS.items()}


def _focus_display(focus_json: str | None) -> str:
    """Parse JSON focus_areas and return human-readable string."""
    if not focus_json:
        return "-"
    try:
        areas = json.loads(focus_json)
        if isinstance(areas, list):
            names = [_FOCUS_NAME_MAP.get(a, a) for a in areas]
            return ", ".join(names)
    except (json.JSONDecodeError, TypeError):
        pass
    return focus_json


def _escape_markup(text: str) -> str:
    """Escape Textual markup characters in user-supplied data."""
    return text.replace("[", "\\[").replace("]", "\\]")


def _score_color(score: float | None) -> str:
    if score is None or score <= 0:
        return "dim"
    if score >= 25:
        return "bold green"
    if score >= 18:
        return "green"
    if score >= 12:
        return "yellow"
    return "red"


def _competition_color(comp: str) -> str:
    s = comp.lower()
    if s in ("low", "very low"):
        return "bold green"
    if s in ("medium", "moderate"):
        return "yellow"
    if s in ("high", "very high", "extreme"):
        return "red"
    return "default"


def _payout_str(max_payout_usd: int | None) -> str:
    if not max_payout_usd or max_payout_usd <= 0:
        return "-"
    return f"${max_payout_usd:,}"


def _payout_color(max_payout_usd: int | None) -> str:
    if not max_payout_usd or max_payout_usd <= 0:
        return "dim"
    return "bold cyan"


# ---------------------------------------------------------------------------
# Main TUI App
# ---------------------------------------------------------------------------

class _TuiLogHandler(logging.Handler):
    """Routes log messages into the TUI status bar or scan progress screen."""

    def __init__(self, app: BoutyHunterApp) -> None:
        super().__init__()
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Keep last few messages for display
            self._app._log_messages.append(msg)
            if len(self._app._log_messages) > 50:
                self._app._log_messages.pop(0)
            # Route to scan progress screen if active, else status bar
            self._app.call_after_refresh(
                lambda: self._app._route_log_message(msg)
            )
        except Exception:
            pass


class BoutyHunterApp(App):
    """Main application for BoutyHunter."""

    CSS = """
    TabbedContent {
        height: 100%;
    }

    #programs-tab,
    #strategy-tab,
    #changes-tab,
    #history-tab {
        height: 1fr;
    }

    #programs-container {
        layout: vertical;
        height: 100%;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }

    #programs-table,
    #changes-table,
    #history-table {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("r", "scan", "Scan", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("d", "details", "Details", show=True),
        Binding("o", "export", "Export", show=True),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._scanning = False
        # Cache program data for details lookup (name -> row dict)
        self._program_cache: dict[str, dict] = {}
        self._log_messages: list[str] = []
        self._scan_progress_screen: ScanProgressScreen | None = None

    def _update_status(self, text: str) -> None:
        """Push a message into the status bar."""
        try:
            self.query_one("#status-bar", Label).update(text)
        except Exception:
            pass

    def _route_log_message(self, msg: str) -> None:
        """Route log messages to scan progress screen if active, else status bar."""
        if self._scan_progress_screen is not None and self._scanning:
            try:
                self._scan_progress_screen.queue_line(msg)
            except Exception:
                pass
        else:
            self._update_status(f"[dim]{msg}[/]")

    def _on_shutdown(self) -> None:
        """Clean up resources on shutdown."""
        # Cancel all running workers
        self.workers.cancel_all()
        # Kill all child processes (web search, etc.)
        try:
            import os, signal
            my_pid = os.getpid()
            for entry in os.listdir("/proc"):
                if not entry.isdigit() or int(entry) == my_pid:
                    continue
                try:
                    with open(f"/proc/{entry}/status", "r") as f:
                        for line in f:
                            if line.startswith("PPid:") and int(line.split()[1]) == my_pid:
                                os.kill(int(entry), signal.SIGKILL)
                                break
                except (FileNotFoundError, ProcessLookupError, ValueError, PermissionError):
                    pass
        except Exception:
            pass
        # Close DB connections gracefully
        try:
            from db import get_connection
            conn = get_connection()
            conn.close()
        except Exception:
            pass

    # -- Composition --------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(
            "Programs",
            "Strategy",
            "Changes",
            "History",
        ):
            with TabPane("All Programs", id="programs-tab"):
                with Container(id="programs-container"):
                    yield Label("Loading...", id="status-bar")
                    table = DataTable(id="programs-table", zebra_stripes=True, fixed_columns=1)
                    table.add_columns(
                        "#", "Score", "Focus", "Program", "Platform", "Competition", "Payout"
                    )
                    yield table
            with TabPane("Scoring Strategy", id="strategy-tab"):
                yield Label(id="strategy-info")
            with TabPane("Change Tracking", id="changes-tab"):
                changes_table = DataTable(id="changes-table", zebra_stripes=True)
                changes_table.add_columns("Timestamp", "Program", "Change Type")
                yield changes_table
            with TabPane("Scan History", id="history-tab"):
                history_table = DataTable(id="history-table", zebra_stripes=True)
                history_table.add_columns("Scan #", "Timestamp", "Mode", "Programs Found", "New", "Changes")
                yield history_table
        yield Footer()

    # -- Mount ------------------------------------------------------------

    async def on_mount(self) -> None:
        # Remove stderr handler so logs don't paint over the TUI
        for h in logging.root.handlers[:]:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                logging.root.removeHandler(h)
        # Add our TUI handler instead
        handler = _TuiLogHandler(self)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self._load_strategy_tab()
        await self._refresh_all()

    def on_shutdown(self) -> None:
        self._on_shutdown()

    def _load_strategy_tab(self) -> None:
        try:
            from scoring import SCORING_WEIGHTS
        except ImportError:
            SCORING_WEIGHTS = {}

        lines = ["[bold cyan]Scoring Weights[/]\n"]
        for key, weight in SCORING_WEIGHTS.items():
            bar_len = int(weight * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            color = "bold green" if weight >= 0.25 else ("yellow" if weight >= 0.15 else "blue")
            lines.append(f"  [{color}]{bar}[/] {weight:.2f} — {key}")

        self.query_one("#strategy-info", Label).update("\n".join(lines))

    # -- Data loading ------------------------------------------------------

    async def _refresh_all(self) -> None:
        self._refresh_programs()
        self._refresh_changes()
        self._refresh_history()

    def _refresh_programs(self) -> None:
        """Load programs from DB into the DataTable."""
        try:
            from db import get_connection, init_db
            init_db()
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT name, platform, score, focus_areas, max_payout_usd FROM programs "
                "ORDER BY score DESC"
            )
            rows = cur.fetchall()
            conn.close()

            table = self.query_one("#programs-table", DataTable)
            table.clear()
            self._program_cache = {}  # rebuild cache

            for rank, row in enumerate(rows, 1):
                name, platform, score, focus_json, max_payout = row
                comp = _COMPETITION_MAP.get(platform or "", "-")
                focus_display = _focus_display(focus_json)
                payout_display = _payout_str(max_payout)

                table.add_row(
                    str(rank),
                    f"[{_score_color(score)}]{score:.1f}[/]",
                    f"[bold yellow]{focus_display}[/]",
                    f"[bold cyan]{name}[/]",
                    platform or "-",
                    f"[{_competition_color(comp)}]{comp}[/]",
                    f"[{_payout_color(max_payout)}]{payout_display}[/]",
                )

                # Cache for details lookup (store raw row data)
                self._program_cache[name] = {
                    "name": name,
                    "platform": platform,
                    "score": score,
                    "focus_areas": focus_json,
                    "max_payout_usd": max_payout,
                }

            # Build useful summary
            focus_counts = {}
            for _, _, _, fj, _ in rows:
                try:
                    areas = json.loads(fj) if isinstance(fj, str) else (fj or [])
                    for a in areas:
                        name = _FOCUS_NAME_MAP.get(a, a)
                        focus_counts[name] = focus_counts.get(name, 0) + 1
                except Exception:
                    pass
            parts = [f"[bold]{len(rows)}[/]"]
            if focus_counts:
                parts.append(f"Focus: {', '.join(f'{k}: [bold]{v}[/]' for k, v in sorted(focus_counts.items(), key=lambda x: -x[1]))}")
            top_score = rows[0][2] if rows else 0
            parts.append(f"Top score: [{_score_color(top_score)}]{top_score:.1f}[/]")

            status = self.query_one("#status-bar", Label)
            status.update(" | ".join(parts))

        except Exception as e:
            logger.error("Failed to load programs: %s", e, exc_info=True)
            try:
                status = self.query_one("#status-bar", Label)
                status.update(f"[red]Error: {e}[/]")
            except Exception:
                pass

    def _refresh_changes(self) -> None:
        """Load recent changes into the DataTable."""
        try:
            from db import init_db, get_recent_changes, get_all_programs
            init_db()
            changes = get_recent_changes(days=7)
            programs = {p["id"]: p["name"] for p in get_all_programs()}

            table = self.query_one("#changes-table", DataTable)
            table.clear()
            for c in changes:
                prog_name = programs.get(c.get("program_id"), "Unknown")
                change_type = c.get("change_type", "").replace("_", " ").title()
                timestamp = (c.get("detected_at") or "")[:19]
                table.add_row(
                    f"[dim]{timestamp}[/]",
                    f"[bold cyan]{prog_name}[/]",
                    f"[magenta]{change_type}[/]",
                )
        except Exception as e:
            logger.error("Failed to load changes: %s", e, exc_info=True)

    def _refresh_history(self) -> None:
        """Load scan history into the DataTable."""
        try:
            from db import init_db, get_scan_history
            init_db()
            scans = get_scan_history(days=30)

            table = self.query_one("#history-table", DataTable)
            table.clear()
            for idx, s in enumerate(reversed(scans), 1):
                scan_time = (s.get("scan_time") or "")[:19]
                table.add_row(
                    str(idx),
                    f"[dim]{scan_time}[/]",
                    s.get("mode", "-"),
                    str(s.get("programs_found", 0)),
                    str(s.get("new_programs", 0)),
                    str(s.get("changes_detected", 0)),
                )
        except Exception as e:
            logger.error("Failed to load history: %s", e, exc_info=True)

    # -- Actions -----------------------------------------------------------

    def action_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        # Show progress screen before starting scan
        self._scan_progress_screen = ScanProgressScreen()
        self.push_screen(self._scan_progress_screen)
        asyncio.create_task(self._do_scan())

    def _do_scan_work(self) -> None:
        """Worker function that runs the full scan in a background thread."""
        from scanner import run_full_scan

        def progress_callback(phase, current, total, message):
            # Thread-safe: route through log handler which calls queue_line()
            logger.info(f"[PROGRESS:{phase}:{current}:{total}] {message}")

        run_full_scan(progress_callback=progress_callback)

    async def _do_scan(self) -> None:
        try:
            w = self.run_worker(self._do_scan_work, thread=True)
            await w.wait()
            # Yield between refreshes so UI updates can render
            self._refresh_programs()
            await asyncio.sleep(0)
            self._refresh_changes()
            await asyncio.sleep(0)
            self._refresh_history()
            await asyncio.sleep(0)
            if self._scan_progress_screen is not None:
                self._scan_progress_screen.set_complete()
        except Exception as e:
            logger.error("Scan failed: %s", e, exc_info=True)
            self.notify(f"Scan failed: {e}", severity="error")
            if self._scan_progress_screen is not None:
                self._scan_progress_screen.set_error(str(e))
        finally:
            self._scanning = False
            self._scan_progress_screen = None  # clear reference

    def action_details(self) -> None:
        """Show details for the selected program."""
        import re

        # Determine which tab is active and read from the correct table
        tabbed = self.query_one(TabbedContent)
        active_tab_id = tabbed.active

        if active_tab_id == "changes-tab":
            table = self.query_one("#changes-table", DataTable)
            cache_key_col = 1  # Program name is column index 1 in changes table
        elif active_tab_id == "programs-tab":
            table = self.query_one("#programs-table", DataTable)
            cache_key_col = 3  # Program name is column index 3 in programs table
        else:
            self.notify("Details only available on Programs or Change Tracking tabs",
                        severity="warning")
            return

        if not table.ordered_rows:
            self.notify("No data loaded", severity="warning")
            return
        cursor_row = table.cursor_row
        if cursor_row is None or not table.is_valid_row_index(cursor_row):
            self.notify("Select a row first (use arrow keys)", severity="warning")
            return
        row = table.get_row_at(cursor_row)
        if row and len(row) > cache_key_col:
            # Extract plain name from markup like "[bold cyan]Intel®[/]"
            raw_name = re.sub(r'\[/?[^\]]+\]', '', str(row[cache_key_col])).strip()
            self.push_screen(DetailsScreen(raw_name, self._program_cache))

    def action_export(self) -> None:
        """Export current data to CSV."""
        try:
            import csv
            from io import StringIO
            from db import get_connection, init_db

            init_db()
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT name, platform, score, focus_areas, max_payout_usd FROM programs ORDER BY score DESC"
            )
            rows = cur.fetchall()
            conn.close()

            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["Rank", "Program", "Platform", "Score", "Focus Areas", "Max Payout (USD)"])
            for i, row in enumerate(rows, 1):
                name, platform, score, focus_json, max_payout = row
                writer.writerow([i, name, platform, score, focus_json or "", max_payout or 0])

            path = Path("bounty_results.csv")
            path.write_text(output.getvalue())
            self.notify(f"Exported {len(rows)} programs to {path}", severity="success")
        except Exception as e:
            logger.error("Export failed: %s", e, exc_info=True)
            self.notify(f"Export failed: {e}", severity="error")


# ---------------------------------------------------------------------------
# Scan Worker
# ---------------------------------------------------------------------------

from textual.worker import Worker


class ScanWorker(Worker):  # type: ignore[misc]
    def run(self) -> None:  # type: ignore[override]
        from scanner import run_full_scan
        run_full_scan()


# ---------------------------------------------------------------------------
# Scan Progress Screen — shows live progress during scanning
# ---------------------------------------------------------------------------

class ScanProgressScreen(ModalScreen):
    """Modal overlay showing scan progress with live log output."""

    DEFAULT_CSS = """
    #scan-overlay {
        width: 90vw;
        height: 75vh;
        layout: vertical;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }

    #scan-header {
        dock: top;
        width: 100%;
        height: 3;
        content-align: center middle;
        color: $accent;
    }

    #scan-progress-bar {
        dock: top;
        width: 100%;
        margin: 0 2;
    }

    #scan-status {
        dock: top;
        width: 100%;
        height: 2;
        content-align: center middle;
        color: $text-muted;
    }

    #scan-log {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        border: solid $surface;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._pending_lines: list[str] = []
        self._total_messages: int = 0
        self._state: str = "running"
        self._tick_count: int = 0
        self._header_label: Label | None = None
        self._status_label: Label | None = None
        self._progress_bar: ProgressBar | None = None
        # Current phase tracking
        self._current_phase: str = "init"
        self._phase_current: int = 0
        self._phase_total: int | None = None
        self._phase_message: str = "Initializing..."

    def compose(self) -> ComposeResult:
        with Container(id="scan-overlay"):
            yield Label("[bold cyan]⟳ Scanning...[/]")
            yield ProgressBar(total=100, show_percentage=True,
                              id="scan-progress-bar")
            yield Label("Initializing...")
            yield RichLog(wrap=True, markup=True, id="scan-log")

    # -- Public API (main thread only) ------------------------------------

    def set_complete(self) -> None:
        self._state = "complete"
        self._flush_pending()
        if self._header_label is not None:
            self._header_label.update(
                f"[bold green]✓ Scan complete![/]  [dim]{self._total_messages} messages[/]"
            )
        if self._progress_bar is not None:
            self._progress_bar.update(progress=100)
        # Auto-dismiss after 2 seconds
        self.call_after_refresh(self._auto_dismiss)

    def set_error(self, error_msg: str) -> None:
        self._state = "error"
        self._flush_pending()
        if self._header_label is not None:
            self._header_label.update(
                f"[bold red]✗ Failed: {_escape_markup(error_msg)}[/]  [dim]{self._total_messages} messages[/]"
            )

    def queue_line(self, msg: str) -> None:
        """Thread-safe — called from worker thread via log handler."""
        self._pending_lines.append(msg)
        self._total_messages += 1
        # Parse progress markers inline for immediate feedback
        self._parse_progress_marker(msg)
        self.call_after_refresh(self._flush_pending)

    def _parse_progress_marker(self, msg: str) -> None:
        """Extract [PROGRESS:phase:current:total] message from log line."""
        import re as _re
        m = _re.match(r'\[PROGRESS:([^:]+):([^:]*):([^\]]*)\]\s*(.*)', msg)
        if not m:
            return
        phase = m.group(1)
        current_str = m.group(2)
        total_str = m.group(3)
        message = m.group(4).strip()

        self._current_phase = phase
        self._phase_message = message

        try:
            self._phase_current = int(current_str) if current_str else 0
        except ValueError:
            self._phase_current = 0

        try:
            self._phase_total = int(total_str) if total_str else None
        except ValueError:
            self._phase_total = None

    # -- Internal ---------------------------------------------------------

    def _auto_dismiss(self) -> None:
        """Dismiss this screen after a short delay."""
        if self.is_active:
            self.dismiss()

    def on_mount(self) -> None:
        """Capture widget references and start spinner timer."""
        # Force centering — bypass CSS cascade where parent ModalScreen wins
        self.styles.layout = "grid"
        self.styles.grid_size = (1, 1)
        self.styles.align = ("center", "middle")
        try:
            labels = list(self.query("#scan-overlay > Label"))
            if labels:
                self._header_label = labels[0]
            if len(labels) > 1:
                self._status_label = labels[1]
        except Exception:
            pass
        try:
            self._progress_bar = self.query_one("#scan-progress-bar", ProgressBar)
        except Exception:
            pass
        self.set_interval(0.5, self._tick)

    def _flush_pending(self) -> None:
        """Write queued lines into the RichLog (main thread only)."""
        if not self._pending_lines:
            return
        try:
            rich_log = self.query_one("#scan-log", RichLog)
            for msg in self._pending_lines:
                parts = msg.split("] ", 1)
                if len(parts) == 2:
                    ts, text = parts[0] + "]", parts[1]
                    rich_log.write(f"[{ts}] {_escape_markup(text)}")
                else:
                    rich_log.write(_escape_markup(msg))
            self._pending_lines.clear()
        except Exception:
            pass

    def _tick(self) -> None:
        """Update header + progress bar based on current phase state."""
        if self._state != "running":
            return
        self._tick_count += 1
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧"]
        spinner = spinners[self._tick_count % len(spinners)]

        # Update header with spinner + phase name
        if self._header_label is not None:
            phase_display = {
                "init": "Initializing",
                "api_fetch": "Fetching APIs",
                "scoring": "Scoring Programs",
                "web_search": "Web Search",
                "complete": "Complete",
            }.get(self._current_phase, self._current_phase)
            self._header_label.update(
                f"[bold cyan]{spinner} {phase_display}[/]  [dim]({self._total_messages} msgs)[/]"
            )

        # Update progress bar
        if self._progress_bar is not None:
            if self._phase_total and self._phase_total > 0:
                pct = min(100, int(self._phase_current / self._phase_total * 100))
                self._progress_bar.update(progress=pct)
            elif self._current_phase == "complete":
                self._progress_bar.update(progress=100)

        # Update status line with current message
        if self._status_label is not None:
            detail = self._phase_message
            if self._phase_total and self._phase_total > 0:
                detail += f" ({self._phase_current}/{self._phase_total})"
            self._status_label.update(f"[dim]{_escape_markup(detail)}[/]")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()


# ---------------------------------------------------------------------------
# Details Modal Screen — shows actionable info for a program
# ---------------------------------------------------------------------------

class DetailsScreen(ModalScreen):
    """Modal showing full details and strategy for a selected program."""

    DEFAULT_CSS = """
    #details-overlay {
        width: 80%;
        height: 75%;
        layout: grid;
        grid-size: 1;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }

    #details-content {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        border: solid $accent;
        padding: 1 2;
        color: $text;
    }

    .close-btn {
        dock: bottom;
        width: 100%;
        height: 3;
        content-align: center middle;
    }
    """

    def __init__(self, program_name: str, cache: dict[str, dict]) -> None:
        super().__init__()
        self.program_name = program_name
        self._cache = cache

    def compose(self) -> ComposeResult:
        with Container(id="details-overlay"):
            yield Label("Loading details...", id="details-content")
            yield Button("Close", id="close-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.dismiss()

    def on_mount(self) -> None:
        # Force centering — bypass CSS cascade where parent ModalScreen wins
        self.styles.layout = "grid"
        self.styles.grid_size = (1, 1)
        self.styles.align = ("center", "middle")
        asyncio.create_task(self._load_details())

    async def _load_details(self) -> None:
        try:
            from db import get_connection, init_db, get_recent_changes
            init_db()

            # Quick info from cache (already loaded in memory)
            cached = self._cache.get(self.program_name, {})

            # Full data from DB
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM programs WHERE name = ?", (self.program_name,))
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            conn.close()

            if not row:
                self.query_one("#details-content", Label).update("[red]Program not found[/]")
                return

            data = dict(zip(cols, row))
            lines = self._build_details(data, cached)
            content = "\n".join(lines)
            self.query_one("#details-content", Label).update(content)

        except Exception as e:
            logger.error("Failed to load details: %s", e, exc_info=True)
            self.query_one("#details-content", Label).update(f"[red]Error: {_escape_markup(str(e))}[/]")

    def _build_details(self, data: dict, cached: dict) -> list[str]:
        """Build a rich details display with actionable info."""
        lines: list[str] = []
        name = data.get("name", self.program_name)
        score = data.get("score", 0) or 0

        # Header
        lines.append(f"[bold cyan underline]{_escape_markup(name)}[/]")
        lines.append("")

        # Score + why it matters
        lines.append("[bold yellow]Score & Ranking[/]")
        lines.append(f"  Overall score: [{_score_color(score)}]{score:.1f}[/]")
        platform = data.get("platform", "-")
        comp = _COMPETITION_MAP.get(platform, "-")
        lines.append(f"  Platform: {_escape_markup(platform)} ([{_competition_color(comp)}]{_escape_markup(comp)} competition[/])")

        # Payout
        max_payout = data.get("max_payout_usd", 0) or 0
        payout_display = _payout_str(max_payout)
        lines.append(f"  Max payout: [{_payout_color(max_payout)}]{payout_display}[/]")
        lines.append("")

        # Focus areas — WHAT TO TEST
        focus_json = data.get("focus_areas", "[]")
        try:
            focus_areas = json.loads(focus_json) if isinstance(focus_json, str) else focus_json
        except (json.JSONDecodeError, TypeError):
            focus_areas = []

        lines.append("[bold green]What to Test (Focus Areas)[/]")
        if focus_areas:
            for area in focus_areas:
                area_name = _FOCUS_NAME_MAP.get(area, area)
                # Add specific vulnerability types per focus area
                vuln_types = self._get_vuln_types(area)
                lines.append(f"  • [bold]{_escape_markup(area_name)}[/] → {_escape_markup(vuln_types)}")
        else:
            lines.append("  • No specific focus — test everything")
        lines.append("")

        # Description
        desc = data.get("description", "") or ""
        if desc:
            lines.append("[bold yellow]Program Info[/]")
            # Parse description fields (format: "Type: X | Visibility: Y | ...")
            for part in desc.split("|"):
                part = part.strip()
                if ":" in part:
                    key, _, val = part.partition(":")
                    lines.append(f"  {_escape_markup(key.strip())}: [cyan]{_escape_markup(val.strip())}[/]")
            lines.append("")

        # Scope details — attack surface
        scope_raw = data.get("scope_details", "") or ""
        if isinstance(scope_raw, str):
            try:
                scope_data = json.loads(scope_raw)
            except (json.JSONDecodeError, TypeError):
                scope_data = {}
        else:
            scope_data = scope_raw

        assets = scope_data.get("assets", []) if isinstance(scope_data, dict) else []
        if assets:
            lines.append("[bold red]Attack Surface[/]")
            for asset in assets[:10]:
                lines.append(f"  • {_escape_markup(asset)}")
            if len(assets) > 10:
                lines.append(f"  ... and {len(assets) - 10} more")
            lines.append("")

        # Temporal signals — what's new/hot
        signals = []
        if data.get("is_new_program"):
            signals.append("[bold green]NEW PROGRAM[/] (first 7 days = least competition)")
        if data.get("scope_recently_expanded"):
            signals.append("[bold green]SCOPE EXPANDED[/] (new attack surface not yet tested)")
        if data.get("bounty_increased"):
            signals.append("[bold green]BOUNTY INCREASED[/] (program owner investing more)")
        if data.get("has_active_event"):
            signals.append("[bold green]ACTIVE EVENT[/] (hacking contest = increased payouts)")

        if signals:
            lines.append("[bold magenta]⚡ Signals[/]")
            for s in signals:
                lines.append(f"  {s}")
            lines.append("")

        # Recent changes
        try:
            program_id = data.get("id")
            if program_id:
                recent_changes = get_recent_changes(days=30, program_id=program_id)
                if recent_changes:
                    lines.append("[bold yellow]Recent Changes[/]")
                    for c in recent_changes[:5]:
                        ts = (c.get("detected_at") or "")[:19]
                        ctype = c.get("change_type", "").replace("_", " ").title()
                        lines.append(f"  [{_escape_markup(ts)}] {_escape_markup(ctype)}")
                    lines.append("")
        except Exception:
            pass

        # Metadata
        lines.append("[dim]Metadata[/]")
        scan_count = data.get("scan_count", 0) or 0
        first_seen = (data.get("first_seen") or "")[:19]
        last_seen = (data.get("last_seen") or "")[:19]
        status = data.get("status", "-")
        lines.append(f"  Status: {_escape_markup(status)} | Scans seen: {scan_count}")
        lines.append(f"  First seen: {_escape_markup(first_seen)} | Last seen: {_escape_markup(last_seen)}")

        # URL
        url = data.get("url", "") or ""
        if url:
            lines.append("")
            lines.append(f"[dim]{_escape_markup(url)}[/]")

        return lines

    @staticmethod
    def _get_vuln_types(area: str) -> str:
        """Return specific vulnerability types to test for a focus area."""
        vulns = {
            "api": "BOLA/IDOR, Broken Auth, Mass Assignment, Excessive Data Exposure",
            "llm": "Prompt Injection, Data Leakage, Training Data Extraction, Excessive Agency",
            "mobile": "Insecure Storage, SSL Pinning Bypass, Insecure Comms, Root Detection Bypass",
        }
        return vulns.get(area, "General web/app vulnerabilities")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BoutyHunterApp().run()
