# BoutyHunter — Bug Bounty Opportunity Finder

## Overview

BoutyHunter is a tool that analyzes bug bounty programs and scores them based on multiple factors including:
- Competition level
- Triage speed
- Focus area bonuses (with LLM-based validation)
- Payout amounts

It provides a **terminal UI** for browsing, scanning, and exporting results — no browser needed.

## Key Features

### 1. LLM-Based Scope Analysis
The system uses an LLM to determine whether programs actually award bounties for vulnerabilities in each focus area, rather than relying on brittle substring matching that could produce false positives.

### 2. Smart Scoring Logic
- **Focus Area Bonuses**: Programs get full bonuses when they actually offer bounties for vulnerabilities in their stated focus areas
- **Reduced Bonuses**: Programs that mention a focus area but don't actually pay for it receive reduced bonuses (0.4x reduction)
- **Competition Penalty**: Lower competition = higher scores

### 3. Example Behavior
**Kruidvat Program**:
- Has `focus_areas: ['llm']`
- No actual AI content in description or scope
- Scored with reduced bonus: `Focus: LLM/AI — emerging field, least competition (no bounties in-scope) → +3.2`

**AI Security Test Program**:
- Has `focus_areas: ['llm']`
- Actual AI content in description and scope
- Scored with full bonus: `Focus: LLM/AI — emerging field, least competition → +8`

## Quick Start

```bash
# Launch the TUI (interactive terminal interface)
uv run opportunity_finder.py

# Run a headless scan then exit
uv run opportunity_finder.py --scan

# Check database status
uv run opportunity_finder.py --status
```

## The Terminal UI

The TUI has **5 tabs** accessible with `Tab` / `Shift+Tab`:

| Tab | Description |
|-----|-------------|
| **All Programs** | Ranked table of all discovered programs (score, signals, competition, payout) |
| **Scoring Strategy** | Visual breakdown of scoring weights |
| **Change Tracking** | Log of changes detected between scans |
| **Scan History** | Record of every scan run |
| **Search Programs** | Interactive web search for new programs |

### Keybindings

| Key | Action |
|-----|--------|
| `r` | Run a full scan (background) |
| `d` | Show details for selected program |
| `o` | Export current data to CSV |
| `s` | Print DB status to terminal |
| `q` | Quit |

## Configuration

### Environment Variables

```bash
export LLM_BASE_URL="http://10.74.74.151:1234/v1"  # LM Studio endpoint
export LLM_MODEL="qwen/qwen3-coder-30b"            # Model to use
```

## Usage (Python API)

```python
from scoring import score_program

# Score a single program
program = {
    "name": "Example Program",
    "url": "https://hackerone.com/example",
    "platform": "hackerone",
    "description": "Company with AI security focus",
    "focus_areas": ["llm"],
    "scope_details": {
        "scope": [{"type": "url", "value": "https://api.example.com/*"}],
        "exclusions": []
    },
    "max_payout_usd": 10000
}

score, reasons = score_program(program)
print(f"Score: {score}")
for reason in reasons:
    print(f"  - {reason}")
```

## Implementation Details

### Core Logic

The scoring system now properly distinguishes between programs that:
1. **Mention a focus area but don't actually pay for it** → Gets reduced bonus (0.4x)
2. **Mention a focus area AND actually pay for it** → Gets full bonus

This addresses the original requirement: "Verify that when evaluating the programs the ones who have scopes in my interests also must be awarding bounties in the scope of interest otherwise it should score less than the ones that do."

### LLM Integration

The system:
- Uses your local LM Studio at `http://10.74.74.151:1234/v1` with `qwen/qwen3-coder-30b` model
- Analyzes program description and scope details to determine actual bounty coverage
- Falls back gracefully to keyword checking when LLM is unavailable

## Files

| File | Description |
|------|-------------|
| `opportunity_finder.py` | Entry point — launches TUI or runs headless commands |
| `tui.py` | Terminal UI (Textual framework) |
| `scanner.py` | Scan orchestration (API + web search) |
| `scoring.py` | Core scoring logic with LLM integration |
| `api_client.py` | Platform API clients (Bugcrowd, Intigriti, YesWeHack) |
| `db.py` | SQLite database layer |
| `constants.py` | Shared constants and configuration |

## Requirements

- Python 3.12+
- `uv` for dependency management
- LM Studio server running at `http://10.74.74.151:1234/v1` (optional, for LLM scoring)
- Model `qwen/qwen3-coder-30b` loaded in LM Studio
