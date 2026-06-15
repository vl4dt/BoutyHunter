# BoutyHunter — Complete User Guide

> **For dummies level.** If you've never used a terminal before, this will walk you through everything step by step.

---

## Table of Contents

1. [What Is This Thing?](#what-is-this-thing)
2. [Before You Start: Prerequisites](#before-you-start-prerequisites)
3. [Installation (5 Minutes)](#installation-5-minutes)
4. [Your First Scan](#your-first-scan)
5. [The Terminal UI](#the-terminal-ui)
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

It focuses on the **most profitable security risks** from three categories:

- **API**: BOLA (Broken Object Level Authorization), Broken Authentication, Mass Assignment
- **LLM/AI**: Prompt Injection, Data Leakage, Excessive Agency
- **Mobile**: Insecure Data Storage, SSL Pinning Bypass, Insecure Communication

### What Makes It Special?

1. **Discovers programs** — via platform APIs or web search
2. **Scores them** — based on competition level, payout, focus area bonus
3. **Tracks changes over time** — new programs, scope expansions, bounty increases
4. **Gives you strategy recommendations** — where to focus your efforts

Think of it as a **radar** that tells you: *"Hey, this program just expanded its scope and nobody's testing the new stuff yet."*

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
uv run opportunity_finder.py --status
```

You should see something like:

```
  📊 DATABASE STATUS
  ────────────────
  Active programs: 0
  Recent changes (7d): 802
  Scans (30d): 9

  🔄 RECENT CHANGES (last 7 days)
    [2026-06-14T01:30:14] Unknown: New Program
    ...
```

If you see this, **you're set up**. The database has data from the initial scan.

---

## Your First Scan

### Option A: Launch the TUI (Recommended)

The Terminal UI gives you everything in one place:

```bash
uv run opportunity_finder.py
```

This opens an interactive interface with tabs for programs, strategy, changes, history, and search. Press `r` inside to start a scan.

### Option B: Headless Scan

Run a scan from the command line without the TUI:

```bash
uv run opportunity_finder.py --scan
```

**What happens:**
1. It tries to query platform APIs (if you've configured credentials — see below)
2. Falls back to web search via SearXNG to find new opportunities
3. Stores everything in a local SQLite database
4. Shows results ranked by score

### Option C: Check Database Status

```bash
uv run opportunity_finder.py --status
```

---

## The Terminal UI

The TUI is your main interface. It replaces the need for a web browser — everything runs right in your terminal.

### Starting the TUI

```bash
uv run opportunity_finder.py
```

### Tabs (navigate with `Tab` / `Shift+Tab`)

#### 📊 All Programs

The home tab. Shows:
- **Ranked table** of all discovered programs sorted by score
- Columns: Rank, Score (color-coded), Signals count, Program name, Platform, Competition level, Payout range
- Status bar at bottom showing program count and last scan time

#### 💡 Scoring Strategy

Visual breakdown of how scores are calculated:
- **Scoring weights** shown as progress bars — see which factors matter most
- Helps you understand why certain programs rank higher

#### 🔄 Change Tracking

Log of everything that changed between scans:
- Columns: Timestamp, Program name, Change type (NEW/SCOPE+/UP/EVENT), Details
- Shows what's new since your last scan

#### 📈 Scan History

Records of every scan you've run:
- Columns: Scan #, Timestamp, Programs found, Top score, Duration
- Useful for seeing if your scans are finding more over time

#### 🔍 Search Programs

Interactive web search for discovering new programs:
- **Input field** at the top — type a query and press Enter
- Results table below showing matching programs with platform and URL

### Keybindings (always available)

| Key | Action | When to Use |
|-----|--------|-------------|
| `r` | Run full scan | Start a background scan without leaving the TUI |
| `d` | Program details | Show detailed info for the selected program row |
| `o` | Export CSV | Save current programs table to `bounty_results.csv` |
| `s` | DB status | Print database statistics to terminal |
| `q` | Quit | Exit the TUI |

### Navigation Tips

- **Arrow keys** — Move up/down in tables
- **Tab / Shift+Tab** — Switch between tabs
- **Page Up / Page Down** — Scroll through long tables
- **Home / End** — Jump to first/last row

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

Example from the TUI table:

```
#1  [green]18[/]  [magenta]3[/]  [cyan]Acme Corp API[/]  hackerone  LOW  $25,000
```

Translation: *"This is the #1 ranked program on HackerOne. It has a score of 18 (hot!), 3 temporal signals, and pays up to $25K with low competition."*

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

Run a scan (headless or via TUI `r` keybinding):

```bash
uv run opportunity_finder.py --scan
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
0 8 * * 1 cd /path/to/BoutyHunter && uv run opportunity_finder.py --scan 2>&1 | tee -a logs/scan_$(date +\%Y\%m\%d).log # BoutyHunter weekly scan
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

### Main Entry Point (`opportunity_finder.py`)

| What you want | Command |
|---------------|---------|
| Launch TUI (interactive) | `uv run opportunity_finder.py` |
| Run headless scan then exit | `uv run opportunity_finder.py --scan` |
| Check database status | `uv run opportunity_finder.py --status` |

### Inside the TUI

| What you want | Key |
|---------------|-----|
| Start a scan (background) | `r` |
| View program details | `d` (on selected row) |
| Export to CSV | `o` |
| Print DB status | `s` |
| Switch tabs | `Tab` / `Shift+Tab` |
| Quit | `q` |

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
uv run opportunity_finder.py
```

### TUI stuck on "Loading..."

This can happen if a database query fails silently. Try:

1. Check the terminal for error messages (the TUI may have crashed)
2. Verify your database is intact: `uv run opportunity_finder.py --status`
3. If DB is corrupted, delete and recreate: `rm bounty_hunter.db`

### "No programs found" after a scan

This is normal if you don't have API credentials configured. The web search might not find specific program pages depending on SearXNG's availability and indexing. Try:

1. Running the scan again (sometimes results vary)
2. Configuring Bugcrowd API credentials (most reliable source)
3. Checking that your SearXNG instance is running (`curl http://localhost:8080`)

### Database file not found or corrupted

The database is created automatically on first run. If it gets corrupted, just delete it and start fresh:

```bash
rm bounty_hunter.db
uv run opportunity_finder.py --scan   # recreates the DB
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
- [ ] Launch TUI: `uv run opportunity_finder.py` → press `r` to scan
- [ ] (Optional) Add Bugcrowd API credentials to `config.yaml`
- [ ] (Optional) Set up weekly cron: `./setup_cron.sh`

---

## What's Next?

Once you've found programs, the next step is actually **hunting**. Check out the [`STRATEGY.md`](STRATEGY.md) file in this repo for attack strategies tailored to your 20 years of development experience. It covers how to approach each vulnerability type with a developer's mindset — which gives you a huge advantage over typical bug hunters who only know how to use tools without understanding what they're testing against.
