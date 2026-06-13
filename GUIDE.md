# BoutyHunter — Complete User Guide

> **For dummies level.** If you've never used a terminal before, this will walk you through everything step by step.

---

## Table of Contents

1. [What Is This Thing?](#what-is-this-thing)
2. [Before You Start: Prerequisites](#before-you-start-prerequisites)
3. [Installation (5 Minutes)](#installation-5-minutes)
4. [Your First Scan](#your-first-scan)
5. [The Web Dashboard](#the-web-dashboard)
6. [Understanding the Results](#understanding-the-results)
7. [Configuring API Credentials (Optional but Recommended)](#configuring-api-credentials-optional-but-recommended)
8. [Automating Scans with Cron](#automating-scans-with-cron)
9. [Every Command You Need to Know](#every-command-you-need-to-know)
10. [Troubleshooting](#troubleshooting)

---

## What Is This Thing?

BoutyHunter is a tool that helps you find the **best bug bounty programs** across four major platforms:

| Platform | Website |
|----------|---------|
| HackerOne | hackerone.com |
| Intigriti | intigriti.com |
| Bugcrowd | bugcrowd.com |
| YesWeHack | yeswehack.com |

It focuses on the **most profitable security risks** from three OWASP categories:

- **Web**: Broken Access Control, Cryptographic Failures, XSS
- **API**: BOLA (Broken Object Level Authorization), Broken Authentication, Object Injection
- **LLM/AI**: Prompt Injection, Data Leakage, Excessive Agency

### What Makes It Special?

1. **Discovers programs** — via platform APIs or web search
2. **Scores them** — based on competition level, payout, focus area bonus
3. **Tracks changes over time** — new programs, scope expansions, bounty increases
4. **Gives you strategy recommendations** — where to focus your efforts

Think of it as a **radar** that tells you: *"Hey, this program just expanded its scope and nobody's tested the new stuff yet."*

---

## Before You Start: Prerequisites

You need three things on your computer:

### 1. Python 3.12+

Check if you have it:

```bash
python3 --version
```

If it says `Python 3.12.x` or higher, you're good. If not, install it from [python.org](https://python.org).

### 2. uv (Python package manager)

This manages dependencies and virtual environments for us:

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Then restart your terminal or run:
source ~/.bashrc   # or source ~/.zshrc if you use zsh
```

Verify it works:

```bash
uv --version
```

### 3. Git (for cloning the repo)

```bash
git --version
```

If not installed, install it via your package manager (`sudo apt install git` on Ubuntu/Debian).

---

## Installation (5 Minutes)

### Step 1: Clone the Repository

Open a terminal and run:

```bash
cd ~/Projects   # or wherever you keep your projects
git clone https://github.com/vl4dt/BoutyHunter.git
cd BoutyHunter
```

### Step 2: Install Dependencies

This creates an isolated virtual environment and installs everything needed:

```bash
uv sync
```

That's it. No `pip install`, no manual setup, no system pollution.

### Step 3: Verify It Works

Run a quick test:

```bash
uv run python3 opportunity_finder.py --status -q
```

You should see something like:

```
╔══════════════════════════════════════════════════════════╗
║       🎯 BoutyHunter — Bug Bounty Opportunity Finder     ║
╠══════════════════════════════════════════════════════════╣
║  Focus: API | LLM/AI | Mobile (Web excluded)           ║
╚══════════════════════════════════════════════════════════╝

  📊 DATABASE STATUS
  ────────────────
  Active programs: 0
  Recent changes (7d): 0
  Scans (30d): 0
```

If you see this, **you're set up**. The database is empty because we haven't run a scan yet — that's normal.

---

## Your First Scan

### Option A: Full Scan (Recommended for Beginners)

This uses both API discovery and web search to find programs:

```bash
uv run python3 opportunity_finder.py --mode all
```

**What happens:**
1. It tries to query platform APIs (if you've configured credentials — see below)
2. Falls back to web search via SearXNG to find new opportunities
3. Stores everything in a local SQLite database
4. Shows you the results ranked by score

### Option B: API-Only Scan

If you have API credentials configured:

```bash
uv run python3 opportunity_finder.py --mode api
```

### Option C: Web Search Only

If you don't have API credentials yet:

```bash
uv run python3 opportunity_finder.py --mode search
```

### Filtering by Focus Area

Want to see only LLM/AI security programs?

```bash
uv run python3 opportunity_finder.py -f llm
```

Or combine focus areas:

```bash
uv run python3 opportunity_finder.py -f api llm
```

Available focus areas: `api`, `llm`, `mobile`

### Filtering by Platform

Want to see only HackerOne programs?

```bash
uv run python3 opportunity_finder.py -p hackerone
```

Or combine platforms:

```bash
uv run python3 opportunity_finder.py -p intigriti bugcrowd
```

Available platforms: `hackerone`, `intigriti`, `bugcrowd`, `yeswehack`

### Combining Filters

HackerOne LLM programs only?

```bash
uv run python3 opportunity_finder.py -p hackerone -f llm
```

### Quiet Mode + Save to File

Don't want log messages cluttering your screen and want results in a file:

```bash
uv run python3 opportunity_finder.py --mode all -q -o my_results.json
```

---

## The Web Dashboard

The web dashboard gives you a visual interface to explore everything. It's much easier than reading terminal output.

### Starting the Dashboard

```bash
uv run python3 app.py --port 9080
```

Then open your browser and go to: **http://127.0.0.1:9080**

> **Why port 9080?** Port 8080 is often used by other tools (like SearXNG). If you don't have anything on 8080, use that instead — it's the default.

### Dashboard Pages Explained

#### 📊 Dashboard (`/`)

The home page. Shows:
- **5 stat cards** at the top: active programs, new this week, active events, changes (7d), scans (30d)
- **Top Programs by Score**: ranked list of best opportunities on the left
- **Recent Changes**: what's changed since your last scan on the right
- **Focus Area Breakdown**: how many programs per category (API/LLM/Mobile)
- **Quick Actions**: shortcut links to filtered views

#### 🎯 Programs (`/programs`)

Full list of all discovered programs with:
- **Filter chips** at the top — click "🔌 API Security" or "HackerOne" to filter
- **Search bar** on the right — type a program name to find it
- **Table** showing: rank, program name + description, platform badge, focus area icons, max payout, temporal signals (NEW/SCOPE+/UP/EVENT), and score

#### 🔄 Changes (`/changes`)

Log of everything that changed between scans:
- **Time range filter**: 7d / 14d / 30d buttons at the top
- **Grouped by change type**: New Programs, Scope Expansions, Bounty Increases, Events
- Each entry shows which program changed and when

#### 📈 Scan History (`/scans`)

Records of every scan you've run:
- Date/time, mode (API/SEARCH/ALL), programs found, new programs discovered, changes detected
- Useful for seeing if your scans are finding more over time

#### 💡 Strategy (`/strategy`)

Where to focus your efforts:
- **Hot Programs**: programs with active temporal signals (newly discovered, scope expanded, etc.) — these are your best bets right now
- **By Platform**: cards showing programs grouped by HackerOne, Intigriti, Bugcrowd, YesWeHack
- **By Focus Area**: cards showing programs grouped by API, LLM/AI, Mobile

### Dashboard CLI Options

```bash
# Default (port 8080)
uv run python3 app.py

# Custom port
uv run python3 app.py --port 9080

# Debug mode (auto-reloads when you edit files — useful during development)
uv run python3 app.py --debug

# Bind to all interfaces (accessible from other devices on your network)
uv run python3 app.py --host 0.0.0.0
```

---

## Understanding the Results

### The Score System

Every program gets a **score** that tells you how attractive it is:

| Score Range | Meaning | Color |
|-------------|---------|-------|
| ≥ 15 | 🔥 Hot — very low competition, high payout, or temporal signal active | Green |
| 8–14 | 👍 Good — worth investigating | Blue |
| < 8 | 😐 Meh — probably too competitive or low payout | Gray |

### What Goes Into the Score?

```
Base Score = Competition Bonus + Payout Bonus + Focus Area Bonus
              (lower competition = higher bonus)   (higher payout = higher bonus)
                                                    (LLM > Mobile > API)

Final Score = Base Score + Temporal Boosts
                              (new program, scope expansion, etc.)
```

### Temporal Signals — The Secret Weapon

These are **time-sensitive opportunities** that give you an edge:

| Signal | Badge | What It Means | Why It Matters |
|--------|-------|---------------|----------------|
| 🆕 NEW | `NEW` | Program discovered for the first time in this scan | Least competition — nobody's tested it yet |
| 📈 SCOPE+ | `SCOPE+` | New attack surface added (new domains, APIs) | Fresh targets that haven't been explored |
| 💰 UP | `UP` | Bounty amount increased | Program owner is investing more — bugs are valuable here |
| 🔥 EVENT | `EVENT` | Hacking contest or bug bash active | Time-limited bonus payouts |

**These signals decay after 7 days.** A program that was "hot" last week might be normal now. That's why regular scans matter.

### Reading a Program Entry

Example from the terminal output:

```
#1 [HackerOne] Acme Corp API — Score: +18.5 🆕 NEW 📈 SCOPE+
    Focus: 🔌 API Security | Payout: $25,000 | Competition: LOW
```

Translation: *"This is the #1 ranked program on HackerOne. It's an API security target paying up to $25K. It was just discovered (NEW) and its scope expanded (SCOPE+), meaning there's fresh attack surface nobody has tested yet. Low competition means fewer hunters competing for bugs."*

---

## Configuring API Credentials (Optional but Recommended)

Without credentials, BoutyHunter uses web search to find programs — which works fine but is less precise. With credentials, it queries platform APIs directly and gets **real-time data**.

### Step 1: Edit the Config File

Open `config.yaml` in your text editor:

```bash
nano config.yaml    # or vim, code, etc.
```

### Step 2: Add Your Credentials

#### Bugcrowd (Most Useful — Best API)

You need a **Token Key** and **Token Secret**. Get them from [Bugcrowd's developer portal](https://bugcrowd.com/developer):

```yaml
platforms:
  bugcrowd:
    enabled: true
    token_key: "your_token_key_here"
    token_secret: "your_token_secret_here"
```

#### YesWeHack (Optional)

You need a **Client ID** and **Client Secret**. Get them from [YesWeHack's developer portal](https://www.yeswehack.com/developer):

```yaml
platforms:
  yeswehack:
    enabled: true
    client_id: "your_client_id_here"
    client_secret: "your_client_secret_here"
    redirect_uri: "http://localhost"
```

You'll also need the YesWeHack Python SDK:

```bash
uv pip install yeswehack
```

#### Intigriti (Optional)

You need a **Bearer Token**. Get it from your [Intigriti account settings](https://app.intigriti.com):

```yaml
platforms:
  intigriti:
    enabled: true
    token: "your_bearer_token_here"
```

### Step 3: Test It

Run an API scan:

```bash
uv run python3 opportunity_finder.py --mode api
```

If credentials are correct, you'll see programs being discovered. If not, it will log a message like `Bugcrowd: credentials not configured, skipping`.

> **⚠️ Security Note:** Never commit your real credentials to Git! The `.gitignore` already excludes the database file, but `config.yaml` is tracked. Consider using environment variables or a separate untracked config file for production use.

---

## Automating Scans with Cron

Running scans manually works, but **automated weekly scans** are where BoutyHunter really shines — because change detection only works when you compare against previous scan data.

### Quick Setup Script

```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

This installs a cron job that runs every **Monday at 8:00 AM**. It will:
1. Run a full scan (API + web search)
2. Detect changes vs the previous week's data
3. Save logs to `logs/scan_YYYYMMDD.log`

### Manual Cron Setup (If You Prefer)

```bash
crontab -e
```

Add this line:

```cron
0 8 * * 1 cd /path/to/BoutyHunter && uv run python3 opportunity_finder.py --mode all 2>&1 | tee -a logs/scan_$(date +\%Y\%m\%d).log # BoutyHunter weekly scan
```

This means: **At minute 0, hour 8 (8 AM), every day of the month, every month, on Mondays** — run the full scan.

### Checking Your Cron Jobs

```bash
crontab -l | grep BoutyHunter
```

### Removing the Cron Job

```bash
crontab -e   # delete the BoutyHunter line and save
```

---

## Every Command You Need to Know

### CLI Scanner (`opportunity_finder.py`)

| What you want | Command |
|---------------|---------|
| Full scan (API + web search) | `uv run python3 opportunity_finder.py --mode all` |
| API-only scan | `uv run python3 opportunity_finder.py --mode api` |
| Web search only | `uv run python3 opportunity_finder.py --mode search` |
| Filter by focus area | `uv run python3 opportunity_finder.py -f llm` |
| Filter by platform | `uv run python3 opportunity_finder.py -p hackerone` |
| Combine filters | `uv run python3 opportunity_finder.py -p intigriti -f api llm` |
| Quiet mode (no logs) | `uv run python3 opportunity_finder.py --mode all -q` |
| Save results to file | `uv run python3 opportunity_finder.py --mode all -o results.json` |
| Check database status | `uv run python3 opportunity_finder.py --status` |

### Web Dashboard (`app.py`)

| What you want | Command |
|---------------|---------|
| Start dashboard (default port 8080) | `uv run python3 app.py` |
| Custom port | `uv run python3 app.py --port 9080` |
| Debug mode (auto-reload on changes) | `uv run python3 app.py --debug` |
| Access from other devices | `uv run python3 app.py --host 0.0.0.0` |

### General

| What you want | Command |
|---------------|---------|
| Install dependencies | `uv sync` |
| Add a new Python package | `uv pip install <package_name>` |
| Check installed packages | `uv pip list` |
| View git history | `git log --oneline` |

---

## Troubleshooting

### "Module not found" errors

You're probably running the script without `uv run`. Always use:

```bash
# Wrong — uses system Python, no virtual env
python3 opportunity_finder.py

# Right — uses uv's managed environment
uv run python3 opportunity_finder.py
```

### Web dashboard won't start (port already in use)

Something else is using port 8080. Use a different port:

```bash
uv run python3 app.py --port 9080
```

Or find what's using the port and stop it:

```bash
lsof -i :8080    # shows what process uses port 8080
kill <PID>       # kill that process
```

### "No programs found" after a scan

This is normal if you don't have API credentials configured. The web search might not find specific program pages depending on SearXNG's availability and indexing. Try:

1. Running the scan again (sometimes results vary)
2. Configuring Bugcrowd API credentials (most reliable source)
3. Checking that your SearXNG instance is running (`curl http://localhost:8080`)

### Database file not found or corrupted

The database is created automatically on first run. If it gets corrupted, just delete it and start fresh:

```bash
rm bounty_hunter.db
uv run python3 opportunity_finder.py --mode all   # recreates the DB
```

> **Note:** This erases your scan history and change tracking data. Only do this if necessary.

### Cron job not running

Check that cron is enabled:

```bash
systemctl status cron    # Debian/Ubuntu
# or
systemctl status crond   # RHEL/CentOS/Fedora
```

Start it if needed:

```bash
sudo systemctl start cron
sudo systemctl enable cron
```

Check the logs directory for output:

```bash
ls -la logs/
cat logs/scan_*.log | tail -20
```

### uv not found after installation

You might need to restart your terminal or source your shell config:

```bash
source ~/.bashrc    # bash users
# or
source ~/.zshrc     # zsh users
```

Or add uv's bin directory to your PATH manually:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## Quick Start Checklist

- [ ] Install Python 3.12+ and `uv`
- [ ] Clone the repo: `git clone https://github.com/vl4dt/BoutyHunter.git && cd BoutyHunter`
- [ ] Install deps: `uv sync`
- [ ] Run first scan: `uv run python3 opportunity_finder.py --mode all`
- [ ] Start dashboard: `uv run python3 app.py --port 9080` → open http://127.0.0.1:9080
- [ ] (Optional) Add Bugcrowd API credentials to `config.yaml`
- [ ] (Optional) Set up weekly cron: `./setup_cron.sh`

---

## What's Next?

Once you've found programs, the next step is actually **hunting**. Check out the [`STRATEGY.md`](STRATEGY.md) file in this repo for attack strategies tailored to your 20 years of development experience. It covers how to approach each vulnerability type with a developer's mindset — which gives you a huge advantage over typical bug hunters who only know how to use tools without understanding what they're testing against.
