#!/usr/bin/env python3
"""
BoutyHunter — Platform API Client Module

Integrates with bug bounty platform APIs to discover programs dynamically.
Fetches detailed scope info, bounty amounts, and detects special events.

Implemented:
  - Bugcrowd:    /programs endpoint (most useful for discovery)
  - YesWeHack:   Python SDK or OAuth fallback
  - Intigriti:   REST API with program data
  - HackerOne:   No public program listing — skipped

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

logger = logging.getLogger("boutyhunter.api")

# ─── Config Loading ──────────────────────────────────────────────────

def load_config(config_path: str | Path = None) -> dict[str, Any]:
    """Load config from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    import yaml

    with open(config_path) as f:
        return yaml.safe_load(f) or {}

# ─── Base Platform Client ──────────────────────────────────────────────

class BasePlatformClient(ABC):
    """Shared logic for all platform API clients.

    Subclasses only need to implement:
      - get_programs() → list of raw dicts from the API
      - parse_raw()   → convert one raw dict into our standard program format
    Everything else (focus detection, event detection, scope extraction) is shared.
    """

    PLATFORM_KEY: str = "unknown"  # e.g. "bugcrowd", "yeswehack", "intigriti"

    def __init__(self, config: dict[str, Any]):
        self.enabled = config.get("enabled", False)

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

# ─── Bugcrowd API Client ──────────────────────────────────────────────

class BugcrowdClient(BasePlatformClient):
    """Bugcrowd API — has the most useful /programs endpoint for discovery."""

    PLATFORM_KEY = "bugcrowd"
    BASE_URL = "https://api.bugcrowd.com"
    PROGRAMS_ENDPOINT = "/programs"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.token_key = config.get("token_key", "")
        self.token_secret = config.get("token_secret", "")
        self.session = requests.Session()
        self._setup_auth()

    def _setup_auth(self):
        """Set up Bugcrowd token authentication."""
        if not self.enabled or not self.token_key or not self.token_secret:
            return
        auth_token = f"{self.token_key}:{self.token_secret}"
        self.session.headers.update({
            "Authorization": f"Token {auth_token}",
            "Accept": "application/vnd.bugcrowd+json",
            "Content-Type": "application/json",
        })

    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch all programs from Bugcrowd API."""
        if not self.enabled or not self.token_key or not self.token_secret:
            logger.info("Bugcrowd: credentials not configured, skipping")
            return []

        try:
            all_programs = []
            page = 1
            while True:
                resp = self.session.get(
                    f"{self.BASE_URL}{self.PROGRAMS_ENDPOINT}",
                    params={"page[number]": page, "page[size]": 50},
                    timeout=30,
                )

                if resp.status_code != 200:
                    logger.warning("Bugcrowd API error: %s — %s", resp.status_code, resp.text[:200])
                    break

                data = resp.json()
                programs = data.get("data", [])
                if not programs:
                    break

                all_programs.extend(programs)

                links = data.get("links", {})
                next_page = links.get("next")
                if not next_page:
                    break
                page += 1

            logger.info("Bugcrowd: fetched %d programs", len(all_programs))
            return all_programs

        except requests.RequestException as e:
            logger.error("Bugcrowd API request failed: %s", e)
            return []
        except Exception as e:
            logger.error("Bugcrowd unexpected error: %s", e)
            return []

    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a Bugcrowd program into our standard format."""
        attributes = raw.get("attributes", {})
        relationships = raw.get("relationships", {})

        scope_details = self._extract_scope(relationships)
        return {
            "name": attributes.get("name", "Unknown"),
            "platform": self.PLATFORM_KEY,
            "url": f"https://bugcrowd.com/{attributes.get('handle', 'unknown')}",
            "max_payout_usd": self._extract_max_payout(attributes),
            "description": attributes.get("description", "")[:500],
            "scope_details": scope_details,
            "status": attributes.get("status", "unknown"),
        }

    def _extract_scope(self, relationships: dict[str, Any]) -> dict[str, Any]:
        """Extract detailed scope information from Bugcrowd relationships."""
        scope_data = relationships.get("scope", {}).get("data", [])
        assets = []
        descriptions = []

        for s in scope_data:
            attrs = s.get("attributes", {})
            if attrs.get("asset_type"):
                assets.append(attrs["asset_type"])
            desc = attrs.get("description", "")
            if desc:
                descriptions.append(desc)

        return {
            "assets": list(set(assets)),
            "descriptions": descriptions,
            "count": len(scope_data),
        }

    def _extract_max_payout(self, attrs: dict[str, Any]) -> int:
        """Try to extract max payout from Bugcrowd program attributes."""
        if "max_bounty_amount" in attrs:
            try:
                return int(attrs["max_bounty_amount"])
            except (ValueError, TypeError):
                pass

        program_type = attrs.get("program_type", "").lower()
        if "private" in program_type:
            return 50000
        elif "public" in program_type:
            return 25000
        else:
            return 15000

# ─── YesWeHack API Client ─────────────────────────────────────────────

class YesWeHackClient(BasePlatformClient):
    """YesWeHack API — requires CSM approval + OAuth setup."""

    PLATFORM_KEY = "yeswehack"
    BASE_URL = "https://apps.yeswehack.com"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.redirect_uri = config.get("redirect_uri", "")

    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch programs from YesWeHack API."""
        if not self.enabled or not self.client_id or not self.client_secret:
            logger.info("YesWeHack: credentials not configured, skipping")
            return []

        # Try Python SDK first
        try:
            from yeswehack import YesWeHackClient as YWH_SDK

            client = YWH_SDK(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri or "http://localhost",
            )
            programs = client.get_programs()  # type: ignore[attr-defined]
            logger.info("YesWeHack (SDK): fetched %d programs", len(programs))
            return programs

        except ImportError:
            logger.info("YesWeHack SDK not installed. Install with: pip install yeswehack")
        except Exception as e:
            logger.warning("YesWeHack SDK error: %s", e)

        # Fallback to direct API
        return self._api_fallback()

    def _api_fallback(self) -> list[dict[str, Any]]:
        """Fallback to direct OAuth + API calls."""
        try:
            token_resp = requests.post(
                f"{self.BASE_URL}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri or "http://localhost",
                },
                timeout=30,
            )

            if token_resp.status_code != 200:
                logger.warning("YesWeHack OAuth error: %s", token_resp.text[:200])
                return []

            access_token = token_resp.json().get("access_token")
            if not access_token:
                logger.error("No access token from YesWeHack OAuth")
                return []

            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get(
                f"{self.BASE_URL}/api/v1/programs",
                headers=headers,
                timeout=30,
            )

            if resp.status_code != 200:
                logger.warning("YesWeHack programs API error: %s", resp.text[:200])
                return []

            data = resp.json()
            raw_programs = data.get("programs", data) if isinstance(data, dict) else data
            logger.info("YesWeHack (API): fetched %d programs", len(raw_programs))
            return raw_programs

        except requests.RequestException as e:
            logger.error("YesWeHack API request failed: %s", e)
            return []
        except Exception as e:
            logger.error("YesWeHack unexpected error: %s", e)
            return []

    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse a YesWeHack program into our standard format."""
        name = raw.get("name", "Unknown")
        description = (raw.get("description", "") or "")[:500]

        # Extract scope details
        assets = []
        descriptions = []
        for key in ("scope", "targets", "assets", "in_scope"):
            val = raw.get(key)
            if isinstance(val, list):
                assets.extend([str(a).lower() for a in val])
            elif isinstance(val, dict):
                descriptions.append(str(val))

        return {
            "name": name,
            "platform": self.PLATFORM_KEY,
            "url": f"https://app.yeswehack.com/{raw.get('slug', 'unknown')}",
            "max_payout_usd": raw.get("max_bounty_amount", 15000),
            "description": description,
            "scope_details": {
                "assets": list(set(assets)),
                "descriptions": descriptions,
                "count": len(assets) + len(descriptions),
            },
            "status": raw.get("state", "unknown"),
        }

# ─── Intigriti API Client ─────────────────────────────────────────────

class IntigritiClient(BasePlatformClient):
    """Intigriti API — primarily org-facing but has some researcher endpoints."""

    PLATFORM_KEY = "intigriti"
    BASE_URL = "https://api.intigriti.com"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.token = config.get("token", "")

    def get_programs(self) -> list[dict[str, Any]]:
        """Fetch programs from Intigriti API."""
        if not self.enabled or not self.token:
            logger.info("Intigriti: credentials not configured, skipping")
            return []

        try:
            headers = {"Authorization": f"Bearer {self.token}"}

            resp = requests.get(
                f"{self.BASE_URL}/programs",
                headers=headers,
                timeout=30,
            )

            if resp.status_code != 200:
                logger.warning("Intigriti API error: %s — %s", resp.status_code, resp.text[:200])
                return []

            data = resp.json()
            raw_programs = data.get("programs", data) if isinstance(data, dict) else data
            logger.info("Intigriti: fetched %d programs", len(raw_programs))
            return raw_programs

        except requests.RequestException as e:
            logger.error("Intigriti API request failed: %s", e)
            return []
        except Exception as e:
            logger.error("Intigriti unexpected error: %s", e)
            return []

    def parse_raw(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """Parse an Intigriti program into our standard format."""
        name = raw.get("name", "Unknown")
        description = (raw.get("description", "") or "")[:500]

        # Extract scope details
        assets = []
        descriptions = []
        for key in ("scope", "targets", "assets", "in_scope"):
            val = raw.get(key)
            if isinstance(val, list):
                assets.extend([str(a).lower() for a in val])
            elif isinstance(val, dict):
                descriptions.append(str(val))

        return {
            "name": name,
            "platform": self.PLATFORM_KEY,
            "url": f"https://app.intigriti.com/{raw.get('slug', 'unknown')}",
            "max_payout_usd": raw.get("max_bounty_amount", 20000),
            "description": description,
            "scope_details": {
                "assets": list(set(assets)),
                "descriptions": descriptions,
                "count": len(assets) + len(descriptions),
            },
            "status": raw.get("state", "unknown"),
        }

# ─── Unified Platform Client ──────────────────────────────────────────

class PlatformClient:
    """Unified client that queries all configured platforms and merges results."""

    def __init__(self, config: dict[str, Any]):
        self.bugcrowd = BugcrowdClient(config.get("platforms", {}).get("bugcrowd", {}))
        self.yeswehack = YesWeHackClient(config.get("platforms", {}).get("yeswehack", {}))
        self.intigriti = IntigritiClient(config.get("platforms", {}).get("intigriti", {}))

    def discover_programs(
        self,
        focus_filter: list[str] | None = None,
        platform_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Discover programs from all configured APIs with full details."""
        all_programs: list[dict[str, Any]] = []

        # Bugcrowd — most useful for discovery
        if not platform_filter or "bugcrowd" in platform_filter:
            raw = self.bugcrowd.get_programs()
            parsed = [p for p in (self.bugcrowd.parse_program(r) for r in raw) if p]
            all_programs.extend(parsed)

        # YesWeHack — requires CSM approval
        if not platform_filter or "yeswehack" in platform_filter:
            raw = self.yeswehack.get_programs()
            parsed = [p for p in (self.yeswehack.parse_program(r) for r in raw) if p]
            all_programs.extend(parsed)

        # Intigriti — org-facing but may have researcher endpoints
        if not platform_filter or "intigriti" in platform_filter:
            raw = self.intigriti.get_programs()
            parsed = [p for p in (self.intigriti.parse_program(r) for r in raw) if p]
            all_programs.extend(parsed)

        # Apply focus filter
        if focus_filter:
            all_programs = [
                p for p in all_programs
                if any(f in p.get("focus_areas", []) for f in focus_filter)
            ]

        logger.info("API discovery total: %d programs across platforms", len(all_programs))
        return all_programs
