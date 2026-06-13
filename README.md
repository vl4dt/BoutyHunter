# BoutyHunter — Bug Bounty Opportunity Finder

Discovers, scores, and tracks bug bounty programs across HackerOne, Intigriti, Bugcrowd, and YesWeHack. Focuses on the **top 3 most profitable security risks** from each OWASP category:

- **OWASP Top 10 Web**: A01 (Broken Access Control), A02 (Cryptographic Failures), A07 (XSS)
- **OWASP API Top 10**: API1 (BOLA), API2 (Broken Auth), API3 (Object Injection)  
- **OWASP LLM Top 10**: LLM01 (Prompt Injection), LLM02 (Data Leakage), LLM06 (Excessive Agency)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 opportunity_finder.py                │
│              Main orchestrator & CLI                  │
├──────────┬──────────────┬──────────────┬────────────┤
│          │              │              │            │
│  API     │   Web        │   Change    │   Temporal │
│  Client  │   Search     │   Detection │   Scoring  │
│ (api_    │   (SearXNG)  │   (db.py)   │   (db.py)  │
│  client. │              │              │            │
│  py)     │              │              │            │
├──────────┴──────────────┴──────────────┴────────────┤
│                    db.py                             │
│         SQLite: programs, changes, scans             │
└─────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Full scan (API discovery + web search) — works without credentials
python3 opportunity_finder.py

# Only API discovery (requires credentials in config.yaml)
python3 opportunity_finder.py --mode api

# Filter by focus area and platform
python3 opportunity_finder.py -f api llm -p intigriti bugcrowd

# Check database status (stored programs, changes, scan history)
python3 opportunity_finder.py --status

# Quiet mode + save to file
python3 opportunity_finder.py -q -o results.json

# Set up weekly automated scans (Monday 8 AM)
./setup_cron.sh
```

## How It Works

### 1. API Discovery (when credentials configured)
Queries platform APIs directly for real-time program data:
- **Bugcrowd**: `/programs` endpoint — most comprehensive listing
- **YesWeHack**: Python SDK or OAuth fallback
- **Intigriti**: Bearer token REST API

Each program is parsed with full details: scope assets, max payout, status, and event detection (hacking contests, bounty increases).

### 2. Web Search Fallback
When APIs aren't configured or return no results, searches via SearXNG for:
- New program launches on each platform
- LLM/AI security programs
- Mobile app security programs
- Beginner-friendly opportunities

### 3. Change Detection (across scans)
Every scan compares discovered programs against stored state and detects:
- 🆕 **New programs** — first-time discoveries (+15 score boost for 7 days)
- 📈 **Scope expansions** — new attack surface not yet tested (+10 boost)
- 💰 **Bounty increases** — program owner investing more (+8 boost)
- 🔥 **Active events** — hacking contests, bug bashes (+12 boost)

### 4. Temporal Scoring
Base score considers: competition level (lower = better), triage speed (faster = better), focus area bonus (LLM > mobile > API), and payout amount. Recent changes add temporal boosts that decay after 7 days, making temporarily attractive programs rise to the top.

## Setup

### Optional: Configure API Credentials
Edit `config.yaml` with your platform credentials for real-time discovery:

```yaml
platforms:
  bugcrowd:
    enabled: true
    token_key: "your_token_key"
    token_secret: "your_token_secret"
  yeswehack:
    enabled: true
    client_id: "your_client_id"
    client_secret: "your_client_secret"
    redirect_uri: "http://localhost"
  intigriti:
    enabled: true
    token: "your_bearer_token"
```

### Optional: Install YesWeHack SDK
```bash
pip install yeswehack
```

## Files

| File | Purpose |
|------|---------|
| `opportunity_finder.py` | Main scanner with CLI interface |
| `api_client.py` | Platform API clients (Bugcrowd, YesWeHack, Intigriti) |
| `db.py` | SQLite database: programs, change tracking, scan history |
| `config.yaml` | Scan settings and API credentials |
| `setup_cron.sh` | Cron job setup for weekly scans |
| `API_INTEGRATION.md` | Platform API research details |
| `STRATEGY.md` | Attack strategy guide leveraging your dev experience |

## Database Schema

```sql
programs          -- Current state of all discovered programs (21 columns)
program_changes   -- History of detected changes per program
scans             -- Metadata about each scan run
```

Run `python3 opportunity_finder.py --status` to view stored data.
