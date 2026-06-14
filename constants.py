#!/usr/bin/env python3
"""BoutyHunter — Shared Constants and Configuration."""

# ─── Focus Areas ──────────────────────────────────────────────────────

FOCUS_AREAS = {
    "api": {
        "name": "API Security",
        "icon": "🔌",
        "tags": ["api", "rest", "graphql", "grpc"],
        "vulnerabilities": [
            "BOLA", "IDOR", "broken object level authorization",
            "BFLA", "broken function level authorization",
            "broken authentication", "token manipulation",
            "mass assignment", "insecure deserialization",
        ],
    },
    "llm": {
        "name": "LLM / AI Security",
        "icon": "🤖",
        "tags": ["ai", "ml", "llm", "chatbot", "copilot", "assistant"],
        "vulnerabilities": [
            "prompt injection", "data leakage", "training data extraction",
            "excessive agency", "sensitive information disclosure",
            "model manipulation", "jailbreak",
        ],
    },
    "mobile": {
        "name": "Mobile App Security",
        "icon": "📱",
        "tags": ["android", "ios", "mobile", "apk", "ipa"],
        "vulnerabilities": [
            "insecure data storage", "ssl pinning bypass",
            "certificate validation", "intent injection",
            "insecure communication", "root detection bypass",
        ],
    },
}

# ─── Focus Area Keywords (for API client parsing) ──────────────────────

FOCUS_KEYWORDS = {
    "api": [
        "api", "rest", "graphql", "grpc", "endpoint", "webhook",
        "bola", "idor", "authorization", "authentication",
    ],
    "llm": [
        "ai", "ml", "llm", "chatbot", "copilot", "assistant",
        "prompt injection", "generative ai", "gemini", "claude",
        "gpt", "openai", "anthropic",
    ],
    "mobile": [
        "android", "ios", "mobile", "apk", "ipa", "app store",
        "play store", "native app", "flutter", "react native",
    ],
}

# ─── Platform Metadata (for scoring) ──────────────────────────────────

PLATFORMS = {
    "hackerone": {
        "name": "HackerOne",
        "site": "hackerone.com",
        "competition_level": "extreme",
        "triage_speed_days": 5,
    },
    "intigriti": {
        "name": "Intigriti",
        "site": "intigriti.com",
        "competition_level": "low",
        "triage_speed_days": 1,
    },
    "bugcrowd": {
        "name": "Bugcrowd",
        "site": "bugcrowd.com",
        "competition_level": "moderate",
        "triage_speed_days": 3,
        "has_researcher_api": False,  # Only org-facing API
    },
    "yeswehack": {
        "name": "YesWeHack",
        "site": "yeswehack.com",
        "competition_level": "low",
        "triage_speed_days": 3,
        "has_researcher_api": False,  # Requires CSM approval, org-facing only
    },
}

COMPETITION_SCORES = {
    "extreme": 10, "high": 7, "moderate": 4, "low": 2, "very_low": 1,
}

# ─── Event Detection Keywords ────────────────────────────────────────

EVENT_KEYWORDS = {
    "hacking_contest": [
        "contest", "hackathon", "bug bash", "hacking contest",
        "time-limited", "limited time", "special event",
    ],
    "bounty_increase": [
        "increased bounty", "higher payout", "raised reward",
        "bonus program", "double bounty",
    ],
}

# ─── Competition Labels (for display) ────────────────────────────────

COMPETITION_LABELS = {
    "extreme": ("EXTREME", "danger"),
    "high": ("HIGH", "warning"),
    "moderate": ("MODERATE", "info"),
    "low": ("LOW", "success"),
    "very_low": ("VERY LOW", "success"),
}
