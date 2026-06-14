#!/usr/bin/env python3
"""BoutyHunter — Program Scoring Module."""

from constants import PLATFORMS, COMPETITION_SCORES

# ─── Platform Lookup ──────────────────────────────────────────────

def find_platform_key(url_or_name: str) -> str | None:
    """Find which platform a URL or name belongs to."""
    text = (url_or_name or "").lower()
    for key, plat in PLATFORMS.items():
        if plat["site"] in text or plat["name"].lower() in text:
            return key
    for key in PLATFORMS:
        if key in text:
            return key
    return None

# ─── Scoring ──────────────────────────────────────────────────────

def score_program(program: dict) -> tuple[float, list[str]]:
    """Score a program. Returns (score, breakdown_reasons).

    Higher score = better opportunity.
    breakdown_reasons is a list of human-readable strings explaining why this
    program ranks where it does — each reason shows the factor and its contribution.
    """
    platform_key = find_platform_key(program.get("url", "")) or find_platform_key(program.get("platform", ""))
    if not platform_key:
        return 0, ["Unknown platform — no score"]

    platform = PLATFORMS[platform_key]
    reasons: list[str] = []

    # Competition penalty (lower competition = higher score)
    comp_level = platform["competition_level"]
    comp_score = COMPETITION_SCORES.get(comp_level, 5)
    comp_bonus = -comp_score
    comp_labels = {
        "extreme": "EXTREME — many hunters competing", "high": "HIGH — crowded",
        "moderate": "MODERATE — some competition", "low": "LOW — fewer hunters",
        "very_low": "VERY LOW — almost no competition",
    }
    reasons.append(f"Competition: {comp_labels.get(comp_level, comp_level)} → {comp_bonus:+.0f}")

    # Triage speed bonus (faster triage = higher score)
    triage_days = platform["triage_speed_days"]
    triage_bonus = max(0, 10 - triage_days)
    reasons.append(f"Triage speed: {triage_days}d turnaround → +{triage_bonus}")

    # Focus area bonus: LLM/AI is hottest opportunity right now
    focus_bonus_map = {"llm": (8, "LLM/AI — emerging field, least competition"),
                       "mobile": (5, "Mobile — specialized tooling barrier"),
                       "api": (3, "API — backend dev experience advantage")}
    focus_areas = program.get("focus_areas", [])
    for area in focus_areas:
        if area in focus_bonus_map:
            bonus, label = focus_bonus_map[area]
            reasons.append(f"Focus: {label} → +{bonus}")

    # Payout bonus (higher max payout = more serious program)
    max_payout = program.get("max_payout_usd", 0) or 0
    payout_bonus = min(5, max_payout / 25000) if max_payout else 0
    reasons.append(f"Payout: ${max_payout:,} max → +{payout_bonus:.1f}")

    total = triage_bonus - comp_score + sum(
        focus_bonus_map.get(a, (0, ""))[0] for a in focus_areas if a in focus_bonus_map
    ) + payout_bonus

    return round(total, 1), reasons
