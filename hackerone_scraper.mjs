#!/usr/bin/env node
/**
 * Puppeteer-based HackerOne program page scraper.
 * 
 * Called from Python via subprocess. Reads a URL from stdin (or argv[2]),
 * renders the page with Chromium, and outputs JSON to stdout:
 *   { "researcher_count": 6000, "submission_count": 49903 }
 */

import puppeteer from 'puppeteer';

async function scrape(url) {
  const browser = await puppeteer.launch({
    headless: true,
    timeout: 15_000,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 30_000 });
    
    // Extract all visible text from the rendered page
    const text = await page.evaluate(() => document.body.innerText);

    // Researcher count — negative lookahead avoids '#1 hacker-powered'
    const hackerMatch = text.match(/(\d[\d,]*)\s*hackers?(?!-)/i);
    
    // Submission/report count
    const subMatch = text.match(/(\d[\d,]*)\s*(submissions?|reports?)/i);

    return {
      researcher_count: hackerMatch ? parseInt(hackerMatch[1].replace(/,/g, '')) : null,
      submission_count: subMatch ? parseInt(subMatch[1].replace(/,/g, '')) : null,
    };
  } finally {
    await browser.close();
  }
}

// Read URL from argv or stdin
const url = process.argv[2];
if (!url) {
  console.error('Usage: node hackerone_scraper.mjs <url>');
  process.exit(1);
}

const result = await scrape(url);
console.log(JSON.stringify(result));
