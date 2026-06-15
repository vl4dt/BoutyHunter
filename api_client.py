#!/usr/bin/env python3
"""
BoutyHunter — Platform API Client Module

Integrates with bug bounty platform APIs to discover programs dynamically.
Fetches detailed scope info, bounty amounts, and detects special events.

Implemented (researcher-facing APIs):
  - Intigriti:   /external/researcher/v1/programs (Bearer token)
  - HackerOne:   /v1/programs (Basic auth — username + API token)

Not implemented (no researcher-facing program listing API):
  - Bugcrowd:    Only org-facing API exists
  - YesWeHack:   Requires CSM approval, only org-facing

Usage:
    from api_client import PlatformClient, load_config
    client = PlatformClient(load_config())
    programs = client.discover_programs()
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from rate_limiter import retry_request

logger = logging.getLogger("boutyhunter.api")

# ─── Config Loading ──────────────────────────────────────────────────

def load_config(config_path: str | Path = None) -> dict[str, Any]:
    """Load config from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    import yaml

    with open(config_path) as f:
        return yaml.safe_load(f) or {}


class BasePlatformClient(ABC):
    """Shared logic for all platform API clients.

    Subclasses only need to implement:
      - get_programs() → list of raw dicts from the API
      - parse_raw()   → convert one raw dict into our standard program format
    Everything else (focus detection, event detection) is shared.
    """

    PLATFORM_KEY: str = "unknown"  # e.g. "intigriti", "hackerone"

    def __init__(self, config: dict[str, Any]):
        self.enabled = bool(config.get("enabled", False))

    @abstractmethod
    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch raw program data from the platform API."""
        ...

    @abstractmethod
    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Convert one raw API response into our standard program dict.

        Must return a dict with at least: name, description (str), scope_details (dict).
        The base class will add focus_areas and event detection automatically.
        """
        ...

    def parse_program(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a program — delegates to subclass then enriches with shared logic."""
        try:
            parsed = self.parse_raw(raw)
            if parsed is None:
                return None

            # Enrich with focus areas and event detection (shared across all platforms)
            description = (parsed.get("description", "") or "").lower()
            scope_details = parsed.get("scope_details", {})
            combined_text = description + " " + json.dumps(scope_details).lower()

            parsed["focus_areas"] = self._detect_focus(combined_text)
            parsed["has_active_event"] = False
            parsed["event_details"] = None

            event_info = self._detect_events(description, scope_details)
            if event_info:
                parsed["has_active_event"] = True
                parsed["event_details"] = event_info

            return parsed

        except Exception as e:
            logger.debug("Parse error for program %s on %s: %s", raw.get("id"), self.PLATFORM_KEY, e)
            return None

    @staticmethod
    def _detect_focus(combined_text: str) -> list[str]:
        """Detect focus areas from combined text using keyword matching."""
        from constants import FOCUS_KEYWORDS

        focus_areas = []
        for area, keywords in FOCUS_KEYWORDS.items():
            if any(kw in combined_text for kw in keywords):
                focus_areas.append(area)
        return focus_areas or ["api"]  # default to api

    @staticmethod
    def _detect_events(
        description: str, scope_details: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Detect special events like hacking contests or bounty increases."""
        from constants import EVENT_KEYWORDS

        for event_type, keywords in EVENT_KEYWORDS.items():
            if any(kw in description.lower() for kw in keywords):
                return {
                    "type": event_type,
                    "detected_at": datetime.now().isoformat(),
                    "source_text": description[:200],
                }

        # Large scope = potential opportunity
        if scope_details.get("count", 0) > 15:
            return {
                "type": "large_scope",
                "detected_at": datetime.now().isoformat(),
                "asset_count": scope_details["count"],
            }

        return None

# ─── Intigriti Researcher API Client ──────────────────────────────────

class IntigritiClient(BasePlatformClient):
    """Intigriti Researcher API — /external/researcher/v1/programs (Bearer token)."""

    PLATFORM_KEY = "intigriti"
    BASE_URL = "https://api.intigriti.com/external/researcher"
    PROGRAMS_ENDPOINT = "/v1/programs"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token", "")
        self.session = requests.Session()
        self._setup_auth()

    def _setup_auth(self):
        """Set up Intigriti Bearer token authentication."""
        if not self.enabled or not self.token:
            return
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        })

    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch all programs from Intigriti Researcher API (paginated)."""
        if not self.enabled or not self.token:
            logger.info("Intigriti: credentials not configured, skipping")
            return []

        try:
            # Fetch in batches to handle large result sets
            all_records = []
            offset = 0
            page_size = 100

            while True:
                resp = retry_request(
                    self.session.get,
                    f"{self.BASE_URL}{self.PROGRAMS_ENDPOINT}",
                    platform=self.PLATFORM_KEY,
                    params={"limit": page_size, "offset": offset},
                    timeout=30,
                )

                if resp.status_code != 200:
                    logger.warning("Intigriti API error: %s — %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                records = data.get("records", [])
                max_count = data.get("maxCount", len(all_records) + len(records))

                if not records:
                    break

                all_records.extend(records)
                offset += page_size

                # Stop if we've fetched everything
                if len(all_records) >= max_count:
                    break

            logger.info("Intigriti: fetched %d programs (total available: %d)", len(all_records), max_count)
            return all_records

        except requests.RequestException as e:
            logger.error("Intigriti API request failed: %s", e)
            return []
        except Exception as e:
            logger.error("Intigriti unexpected error: %s", e)
            return []

    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse an Intigriti program into our standard format."""
        name = raw.get("name", "Unknown")
        handle = raw.get("handle", "unknown")

        # Extract bounty info
        max_bounty_obj = raw.get("maxBounty", {})
        min_bounty_obj = raw.get("minBounty", {})
        max_payout = int(max_bounty_obj.get("value", 0)) if isinstance(max_bounty_obj, dict) else 0

        # Extract status and type
        status_obj = raw.get("status", {})
        status_value = status_obj.get("value", "Unknown") if isinstance(status_obj, dict) else str(raw.get("status", ""))

        type_obj = raw.get("type", {})
        program_type = type_obj.get("value", "") if isinstance(type_obj, dict) else str(raw.get("type", ""))

        confidentiality_obj = raw.get("confidentialityLevel", {})
        confidentiality = confidentiality_obj.get("value", "Unknown") if isinstance(confidentiality_obj, dict) else str(raw.get("confidentialityLevel", ""))

        industry = raw.get("industry", "")

        # Build description from available fields
        description_parts = []
        if program_type:
            description_parts.append(f"Type: {program_type}")
        if confidentiality:
            description_parts.append(f"Visibility: {confidentiality}")
        if status_value:
            description_parts.append(f"Status: {status_value}")
        if industry:
            description_parts.append(f"Industry: {industry}")

        return {
            "name": name,
            "platform": self.PLATFORM_KEY,
            "url": f"https://app.intigriti.com/programs/{handle}/{handle}/detail",
            "max_payout_usd": max_payout,
            "description": " | ".join(description_parts),
            "scope_details": {
                "assets": [],
                "descriptions": description_parts,
                "count": len(description_parts),
            },
            "status": status_value.lower() if isinstance(status_value, str) else "unknown",
        }

# ─── HackerOne Researcher API Client ──────────────────────────────────

class HackerOneClient(BasePlatformClient):
    """HackerOne Researcher API — /v1/programs (Basic auth: username + API token)."""

    PLATFORM_KEY = "hackerone"
    BASE_URL = "https://api.hackerone.com/v1"
    PROGRAMS_ENDPOINT = "/hackers/programs"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.username = config.get("username", "")
        self.token = config.get("token", "")
        self.session = requests.Session()
        self._setup_auth()

    def _setup_auth(self):
        """Set up HackerOne Basic authentication (username:API_token)."""
        if not self.enabled or not self.username or not self.token:
            return
        # HackerOne uses Basic auth where username is your API username and password is the token
        import base64
        creds = f"{self.username}:{self.token}"
        encoded = base64.b64encode(creds.encode()).decode()
        self.session.headers.update({
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
        })

    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch all programs from HackerOne Researcher API (paginated)."""
        if not self.enabled or not self.username or not self.token:
            logger.info("HackerOne: credentials not configured (need username + token), skipping")
            return []

        try:
            all_programs = []
            page_size = 50
            page_number = 1

            while True:
                resp = retry_request(
                    self.session.get,
                    f"{self.BASE_URL}{self.PROGRAMS_ENDPOINT}",
                    platform=self.PLATFORM_KEY,
                    params={"page[size]": page_size, "page[number]": page_number},
                    timeout=30,
                )

                if resp.status_code != 200:
                    logger.warning("HackerOne API error: %s — %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                programs = data.get("data", []) if isinstance(data, dict) else data

                if not programs:
                    break

                all_programs.extend(programs)

                # Check for next page link
                links = data.get("links", {})
                if not links.get("next"):
                    break
                page_number += 1

            logger.info("HackerOne: fetched %d programs", len(all_programs))
            return all_programs

        except requests.RequestException as e:
            logger.error("HackerOne API request failed: %s", e)
            return []
        except Exception as e:
            logger.error("HackerOne unexpected error: %s", e)
            return []

    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a HackerOne program into our standard format."""
        # JSON:API format — attributes are nested under "attributes"
        attrs = raw.get("attributes", {}) if isinstance(raw, dict) else {}

        name = attrs.get("name", attrs.get("title", "Unknown"))
        description = (attrs.get("description", "") or "")[:500]

        # Extract scope details from relationships or attributes
        relationships = raw.get("relationships", {}) if isinstance(raw, dict) else {}
        scope_data = []
        for rel_key in ("scope", "programs", "targets"):
            rel_val = relationships.get(rel_key, {}).get("data", [])
            if isinstance(rel_val, list):
                scope_data.extend(rel_val)

        # Extract max payout from attributes
        max_payout = 0
        for key in ("max_bounty_amount", "bounty_range_max", "max_reward"):
            val = attrs.get(key)
            if val is not None:
                try:
                    max_payout = int(val)
                    break
                except (ValueError, TypeError):
                    pass

        # Extract status and program type
        status = attrs.get("status", "unknown")
        program_type = attrs.get("program_type", "")

        return {
            "name": name,
            "platform": self.PLATFORM_KEY,
            "url": f"https://hackerone.com/{attrs.get('handle', 'unknown')}",
            "max_payout_usd": max_payout,
            "description": description or "",
            "scope_details": {
                "assets": [],
                "descriptions": [f"Type: {program_type}"] if program_type else [],
                "count": len(scope_data),
            },
            "status": status.lower() if isinstance(status, str) else "unknown",
        }

# ─── Unified Platform Client ──────────────────────────────────────────

def _cb(callback, phase, current, total, message):
    """Safe callback invoker."""
    if callback is not None:
        try:
            callback(phase, current, total, message)
        except Exception:
            pass

class PlatformClient:
    """Unified client that queries all configured platforms and merges results."""

    def __init__(self, config: dict[str, Any]):
        platforms = config.get("platforms", {})
        self.intigriti = IntigritiClient(platforms.get("intigriti", {}))
        self.hackerone = HackerOneClient(platforms.get("hackerone", {}))

    def discover_programs(
        self,
        focus_filter: list[str] | None = None,
        platform_filter: list[str] | None = None,
        progress_callback=None,  # callable(phase, current, total, message)
    ) -> list[dict[str, Any]]:
        """Discover programs from all configured APIs with full details."""
        all_programs: list[dict[str, Any]] = []

        # Intigriti — researcher API confirmed working
        if not platform_filter or "intigriti" in platform_filter:
            _cb(progress_callback, "api_fetch", 0, None, "Fetching Intigriti programs...")
            raw = self.intigriti.get_programs()
            parsed = [p for p in (self.intigriti.parse_program(r) for r in raw) if p]
            all_programs.extend(parsed)
            _cb(progress_callback, "api_fetch", len(parsed), None,
                f"Intigriti: {len(parsed)} programs fetched")

        # HackerOne — researcher API with Basic auth
        if not platform_filter or "hackerone" in platform_filter:
            _cb(progress_callback, "api_fetch", 0, None, "Fetching HackerOne programs...")
            raw = self.hackerone.get_programs()
            parsed = [p for p in (self.hackerone.parse_program(r) for r in raw) if p]
            all_programs.extend(parsed)
            _cb(progress_callback, "api_fetch", len(parsed), None,
                f"HackerOne: {len(parsed)} programs fetched")

        # Apply focus filter
        if focus_filter:
            all_programs = [
                p for p in all_programs
                if any(f in p.get("focus_areas", []) for f in focus_filter)
            ]

        logger.info("API discovery total: %d programs across platforms", len(all_programs))
        _cb(progress_callback, "api_fetch", len(all_programs), None,
            f"Total API programs discovered: {len(all_programs)}")
        return all_programs
