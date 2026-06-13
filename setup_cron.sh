#!/usr/bin/env bash
# BoutyHunter — Cron Job Setup
# Runs weekly scans (Monday 8 AM) and logs output with change tracking

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
DB_FILE="$SCRIPT_DIR/bounty_hunter.db"

echo "╔══════════════════════════════════════════╗"
echo "║  BoutyHunter — Cron Setup               ║"
echo "╚══════════════════════════════════════════╝"

# Create log directory
mkdir -p "$LOG_DIR"

# Define the cron job command
CRON_CMD="cd $SCRIPT_DIR && python3 opportunity_finder.py --mode all 2>&1 | tee -a $LOG_DIR/scan_\$(date +\%Y\%m\%d).log"

# Check if already set up
if crontab -l 2>/dev/null | grep -q "BoutyHunter"; then
    echo ""
    echo "⚠️  BoutyHunter cron job already exists."
    echo ""
    echo "Current schedule:"
    crontab -l | grep "BoutyHunter"
    echo ""
    read -p "Replace existing? [y/N]: " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# Add the cron job — every Monday at 8 AM
(crontab -l 2>/dev/null | grep -v "BoutyHunter"; echo "0 8 * * 1 $CRON_CMD # BoutyHunter weekly scan") | crontab -

echo ""
echo "✅ Cron job installed: Every Monday at 8:00 AM"
echo ""
echo "📋 What it does:"
echo "   • Discovers programs via API (if credentials configured)"
echo "   • Falls back to web search for new opportunities"
echo "   • Detects changes vs previous scan (new scope, bounty increases)"
echo "   • Stores everything in SQLite database ($DB_FILE)"
echo ""
echo "📁 Logs saved to: $LOG_DIR/"
echo ""
echo "🔍 To check status anytime:"
echo "   python3 opportunity_finder.py --status"
echo ""
echo "🗑️  To remove the cron job:"
echo "   crontab -e  # then delete the BoutyHunter line"
