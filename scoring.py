#!/usr/bin/env python3
"""BoutyHunter — Program Scoring Module."""

import json
import logging

from constants import FOCUS_AREAS, PLATFORMS, COMPETITION_SCORES

logger = logging.getLogger("boutyhunter.scoring")

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

# ─── LLM Scope Analyzer ──────────────────────────────────────────

def _analyze_scope_with_llm(program_name: str, description: str, scope_details: dict) -> dict[str, bool]:
    """Use an LLM to determine whether a program actually awards bounties for
    vulnerabilities in each focus area. Returns {area_key: True/False}.

    This avoids brittle substring matching that produces false positives
    (e.g. 'jailbreak' under Mobile/out-of-scope sections).
    """
    import os

    # Use local LLM endpoint if available, otherwise fall back to keyword check
    base_url = os.environ.get("LLM_BASE_URL", "http://10.74.74.151:1234/v1")
    
    if not base_url.startswith("http"):
        logger.debug("No LLM endpoint configured - falling back to keyword-based scope check")
        return _keyword_scope_check(description, scope_details)

    prompt = f"""You are a bug bounty analyst. Determine whether the following program ACTUALLY awards bounties for vulnerabilities in each of these focus areas:

Focus areas and their vulnerability types:
- LLM/AI Security: prompt injection, data leakage, training data extraction, excessive agency, sensitive information disclosure, model manipulation, jailbreak (in AI context)
- API Security: BOLA, IDOR, broken object/function level authorization, broken authentication, token manipulation, mass assignment, insecure deserialization
- Mobile App Security: insecure data storage, SSL pinning bypass, certificate validation issues, intent injection, insecure communication, root detection bypass

Program: {program_name}
Description: {description[:1000]}
Scope details: {json.dumps(scope_details)[:2000]}

IMPORTANT: Only count a focus area as bounty-eligible if the program explicitly awards bounties for vulnerabilities in that category. Do NOT count it if:
- The vulnerability type appears only under "Out of Scope" or "Exclusions"
- A keyword like "jailbreak" appears but is clearly about mobile device jailbreaking, not AI/LLM
- The topic is mentioned tangentially (e.g., "we use AI internally") but no bounties are offered for it

Respond with ONLY a JSON object: {{"llm": true/false, "api": true/false, "mobile": true/false}}"""

    try:
        # Use local LM Studio endpoint
        import requests as req
        resp = req.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": os.environ.get("LLM_MODEL", "qwen/qwen3-coder-30b"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "stream": False
            },
            timeout=30,
        )
        if resp.status_code == 200:
            response_data = resp.json()
            # Handle different response formats from LM Studio vs OpenAI
            content = ""
            if 'choices' in response_data and len(response_data['choices']) > 0:
                content = response_data['choices'][0]['message']['content'].strip()
            elif 'response' in response_data:
                content = response_data['response'].strip()
            else:
                # Try to get any text content that might be present
                for key in ['content', 'text', 'message']:
                    if key in response_data:
                        content = str(response_data[key]).strip()
                        break
            
            logger.debug(f"LLM Response content: {content[:200]}...")
            
            if content:
                # Extract JSON from response - be more flexible with parsing
                import re as _re
                # First try to find the exact JSON pattern
                match = _re.search(r'\{[^}]+\}', content)
                if not match:
                    # If no exact match, look for any valid JSON in the response
                    logger.debug("No direct JSON found, trying alternative parsing")
                    # Look for JSON-like content with proper braces
                    import re as re2
                    # Try to find content between curly braces that looks like JSON
                    json_matches = re2.findall(r'\{[^}]*\}', content)
                    if json_matches:
                        # Take the first one that looks valid
                        for potential_json in json_matches:
                            try:
                                result = json.loads(potential_json)
                                return {k: bool(result.get(k, False)) for k in ("llm", "api", "mobile")}
                            except:
                                continue
                
                if match:
                    try:
                        result = json.loads(match.group())
                        return {k: bool(result.get(k, False)) for k in ("llm", "api", "mobile")}
                    except Exception as e:
                        logger.warning(f"Failed to parse JSON from LLM response: {e}")
                        logger.debug(f"Raw content: {content[:500]}")
                        
        else:
            logger.warning("LLM scope analysis failed with status %d", resp.status_code)

    except Exception as e:
        logger.warning("LLM scope analysis failed (%s), falling back to keyword check", e)

    # Fallback
    return _keyword_scope_check(description, scope_details)


def _keyword_scope_check(description: str, scope_details: dict) -> dict[str, bool]:
    """Fallback keyword-based scope check (used when no LLM API is available)."""
    text = (description or "").lower() + " " + json.dumps(scope_details).lower()

    result = {}
    for area_key, area_info in FOCUS_AREAS.items():
        vulns = [v.lower() for v in area_info.get("vulnerabilities", [])]
        # Simple check: any vulnerability keyword present (not perfect but functional)
        result[area_key] = any(v in text for v in vulns)

    return result


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

    # Focus area bonus — only full bonus if the program actually awards bounties
    # for vulnerabilities in that scope. If it mentions the topic but doesn't pay,
    # apply a reduced bonus so it scores less than programs that do.
    focus_bonus_map = {"llm": (8, "LLM/AI — emerging field, least competition"),
                       "mobile": (5, "Mobile — specialized tooling barrier"),
                       "api": (3, "API — backend dev experience advantage")}

    FOCUS_BOUNTY_MISMATCH_REDUCTION = 0.4

    # Parse scope_details if it's a JSON string
    scope_raw = program.get("scope_details", {})
    if isinstance(scope_raw, str):
        try:
            scope_obj = json.loads(scope_raw)
        except (json.JSONDecodeError, TypeError):
            scope_obj = {}
    else:
        scope_obj = scope_raw

    # Determine which focus areas actually have bounties in-scope
    bounty_scope = _analyze_scope_with_llm(
        program.get("name", "Unknown"),
        program.get("description", ""),
        scope_obj,
    )

    focus_areas = program.get("focus_areas", [])
    for area in focus_areas:
        if area not in focus_bonus_map:
            continue
        bonus, label = focus_bonus_map[area]
        bounty_matches = bool(bounty_scope.get(area, False))
        if bounty_matches:
            reasons.append(f"Focus: {label} → +{bonus}")
        else:
            reduced = round(bonus * FOCUS_BOUNTY_MISMATCH_REDUCTION, 1)
            reasons.append(
                f"Focus: {label} (no bounties in-scope) → +{reduced}"
            )

    # Payout bonus (higher max payout = more serious program)
    max_payout = program.get("max_payout_usd", 0) or 0
    payout_bonus = min(5, max_payout / 25000) if max_payout else 0
    reasons.append(f"Payout: ${max_payout:,} max → +{payout_bonus:.1f}")

    # Recompute focus contribution with bounty-scope awareness
    def _focus_contribution(area: str) -> float:
        base = focus_bonus_map.get(area, (0, ""))[0]
        if not base:
            return 0.0
        if bool(bounty_scope.get(area, False)):
            return base
        return round(base * FOCUS_BOUNTY_MISMATCH_REDUCTION, 1)

    total = triage_bonus - comp_score + sum(
        _focus_contribution(a) for a in focus_areas if a in focus_bonus_map
    ) + payout_bonus

    return round(total, 1), reasons
