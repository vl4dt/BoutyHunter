#!/usr/bin/env python3
"""
BoutyHunter — Bug Bounty Opportunity Finder (CLI Entry Point)

Usage:
    uv run opportunity_finder.py              # Launch TUI
    uv run opportunity_finder.py --scan       # Run scan headlessly then exit
    uv run opportunity_finder.py --status     # Show DB status then exit
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("boutyhunter")


def main() -> None:
    args = sys.argv[1:]

    # Headless modes
    if "--scan" in args or ("-s" in args and "--status" not in args):
        from scanner import headless_scan
        headless_scan(args)
        return

    if "--status" in args:
        from scanner import print_status
        print_status()
        return

    # Launch TUI
    from tui import BoutyHunterApp
    app = BoutyHunterApp()
    app.run()


if __name__ == "__main__":
    main()
