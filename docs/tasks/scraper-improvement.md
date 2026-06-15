# Scraper Improvement Tasks

## Goal
Improve `scraper.py` to extract researcher counts from Intigriti and HackerOne program pages.

## Current State
- **Intigriti scraper**: Returns `null` — JSON-LD only contains env config, no program stats
- **HackerOne scraper**: Returns `null` — Playwright fails (no browser), static HTML has no stats
- Both platforms are SPAs — stats require JS rendering

## Tasks

### [ ] Task 1: Test Playwright availability and fix HackerOne scraping
- Check if playwright browsers are installed (`playwright install chromium`)
- If yes, test `scrape_hackerone()` with Playwright on a real program page
- If no, install browsers or document the limitation

### [ ] Task 2: Fix Intigriti scraper — try Playwright rendering
- Add Playwright fallback to `scrape_intigriti()` (currently only static HTML)
- Look for stats in rendered DOM: "X hackers", submission counts, etc.

### [ ] Task 3: Try alternative data sources
- Check if Intigriti has any server-rendered pages with stats (e.g., `/programs/{slug}/detail` vs other paths)
- Check HackerOne program pages for meta tags or og:description with stats
- Look for any public leaderboard/statistics endpoints

### [ ] Task 4: Improve heuristic fallback in scoring.py
- If scraping consistently fails, make `_estimate_researcher_pressure()` more robust
- Consider using program age + bounty amount + scope size as stronger signals

## Notes from Research
- Intigriti Company API `/v2/programs/{id}/researchers` exists but requires company auth (401)
- HackerOne API requires valid credentials (ours return 401)
- Bugcrowd API requires auth, no public listing
- No platform exposes researcher counts publicly via API
