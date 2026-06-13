# Bug Bounty Platform APIs — Research & Integration Guide

## Overview

All four major bug bounty platforms have APIs, but their usefulness for **researcher-side program discovery** varies significantly. The `api_client.py` module implements integration with the three most useful ones.

### Current Status

| Platform | API Integrated? | Discovery Quality | Setup Required |
|----------|----------------|-------------------|----------------|
| Bugcrowd | ✅ Yes | Best — `/programs` endpoint lists all accessible programs | Token key + secret |
| YesWeHack | ✅ Yes (SDK + fallback) | Good — read-only program access | CSM approval + OAuth setup |
| Intigriti | ✅ Yes | Partial — org-facing but may have researcher endpoints | Bearer token |
| HackerOne | ❌ No | Not useful — no public listing endpoint | N/A |

---

## 1. HackerOne

| Field | Value |
|-------|-------|
| API URL | `https://api.hackerone.com/` |
| Docs | https://docs.hackerone.com/en/articles/8544782-api-tokens |
| Auth | HTTP Basic (API token identifier as username, token value as password) |
| Rate Limit | Not publicly documented |

### ⚠️ Key Limitation for Researchers

HackerOne's API is **org-facing** — it's designed for program owners to manage their programs. The main endpoints are:
- `GET /v1/reports` — Pull vulnerability reports (for your own org)
- `POST /v1/programs/:handle/bounties` — Award bounties
- `POST /v1/reports` — Import external findings

**There is no public "list all bug bounty programs" endpoint for researchers.** You'd need an organization-level API token to access program data, and even then you only see your own org's programs.

### Workaround
Use web scraping or the curated list approach in `opportunity_finder.py`. HackerOne's website lists programs publicly at `hackerone.com/programs` but there's no official API for this.

---

## 2. Bugcrowd ✅ Best for Program Discovery

| Field | Value |
|-------|-------|
| API URL | `https://api.bugcrowd.com` |
| Docs | https://docs.bugcrowd.com/api/getting-started/ |
| Auth | Token header: `Authorization: Token <key>:<secret>` |
| Rate Limit | 60 requests/min per IP |

### ✅ Key Feature for Researchers

Bugcrowd has a **`GET /programs`** endpoint that lists all programs accessible by your user. This is the most useful API for program discovery among all platforms.

```bash
curl --include \
  --header "Accept: application/vnd.bugcrowd+json" \
  --header "Authorization: Token YOUR_KEY:YOUR_SECRET" \
  'https://api.bugcrowd.com/programs'
```

The API follows the JSON API spec with filtering, sorting, and pagination. You can filter by program type, status, etc.

### Bonus: MCP Server
There's a community Bugcrowd MCP server on GitHub that exposes all endpoints as LLM tools: https://github.com/mohdhaji87/Bugcrowd-MCP

---

## 3. Intigriti ✅ Good for Program Data

| Field | Value |
|-------|-------|
| API URL | `https://api.intigriti.com` (exact base varies) |
| Docs | https://kb.intigriti.com/en/articles/6117846-intigriti-api |
| Auth | Token-based with configurable scopes |
| Rate Limit | Not publicly documented |

### Features for Researchers

- RESTful API with read and write access depending on permissions/scopes
- Has webhooks management API
- Supports OAuth-like token flow with redirect URIs
- You can create API tokens from Admin > Integrations (requires Company Admin role)

The API is primarily designed for organizations to integrate their internal systems, but the program data endpoints should be accessible if you have researcher-level permissions.

---

## 4. YesWeHack ✅ Has Python SDK!

| Field | Value |
|-------|-------|
| API URL | `https://apps.yeswehack.com` |
| Docs | https://apps.yeswehack.com/doc (Swagger/OpenAPI) |
| Auth | OAuth 2.0 authorization code flow |
| Rate Limit | Not publicly documented |

### ✅ Key Features for Researchers

- **Read-only access** to all programs you're invited to
- Full Swagger/OpenAPI documentation at `apps.yeswehack.com/doc`
- **Python SDK available**: `pip install yeswehack` (on PyPI!)
- OAuth 2.0 with token refresh support

### ⚠️ Setup Requirement

You must contact your CSM first and provide your username to request API access. They'll set the necessary permissions before you can create an "API app" in your profile.

```bash
# Install the Python SDK
pip install yeswehack

# Then use it in your code:
from yeswehack import YesWeHackClient
client = YesWeHackClient(client_id="...", client_secret="...")
programs = client.get_programs()  # or similar — check SDK docs
```

---

## How It Works

The `api_client.py` module provides three platform-specific clients:

### BugcrowdClient
- Uses the `/programs` endpoint with JSON API pagination
- Parses program attributes to auto-detect focus areas (API, LLM, mobile)
- Estimates max payout based on program type

### YesWeHackClient  
- Tries Python SDK first (`pip install yeswehack`) if available
- Falls back to direct OAuth + REST API calls
- Requires CSM approval before you can create an API app

### IntigritiClient
- Uses Bearer token authentication
- Queries `/programs` endpoint (availability depends on your permissions)

### Unified PlatformClient
The `PlatformClient` class orchestrates all three clients, merges results, and applies focus/platform filters. If no credentials are configured, it returns empty lists gracefully — the main tool then falls back to web search.

## Quick Start Commands

```bash
# Full scan: API discovery + web search (works without credentials)
python3 opportunity_finder.py

# Only API discovery (requires credentials in config.yaml)
python3 opportunity_finder.py --mode api

# Only web search (no credentials needed)
python3 opportunity_finder.py --mode search

# Filter by focus area and platform
python3 opportunity_finder.py -p intigriti yeswehack -f api llm

# Quiet mode, save to file
python3 opportunity_finder.py -q -o my_results.json
```
