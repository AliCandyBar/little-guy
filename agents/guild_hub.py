import asyncio
import re
import time
from typing import Any

import aiohttp


class GuildAgentHub:
    API_URL = "https://api.guild.ai/v1/agents"
    CACHE_SECONDS = 900
    MAX_CANDIDATES = 8

    def __init__(self):
        self._catalog: list[dict[str, str]] = []
        self._catalog_loaded_at = 0.0
        self._lock = asyncio.Lock()

    def _cache_is_fresh(self) -> bool:
        return (
            self._catalog_loaded_at > 0
            and time.monotonic() - self._catalog_loaded_at < self.CACHE_SECONDS
        )

    async def _load_catalog(
        self,
        force_refresh: bool = False,
        allow_stale: bool = True,
    ) -> list[dict[str, str]]:
        if not force_refresh and self._cache_is_fresh():
            return self._catalog

        async with self._lock:
            if not force_refresh and self._cache_is_fresh():
                return self._catalog

            timeout = aiohttp.ClientTimeout(total=12)
            params = {
                "published_only": "true",
                "is_public": "true",
                "limit": "5000",
            }
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        self.API_URL,
                        params=params,
                    ) as response:
                        response.raise_for_status()
                        payload: dict[str, Any] = await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if allow_stale and self._catalog_loaded_at > 0:
                    return self._catalog
                raise

            if not isinstance(payload, dict):
                raise ValueError("Guild returned an invalid agent catalog.")

            catalog = []
            for item in payload.get("items", []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                description = str(item.get("description") or "").strip()
                url = str(item.get("public_profile_url") or "").strip()
                if not name or not description:
                    continue
                if not url.startswith("https://app.guild.ai/hub/agents/"):
                    url = ""
                category = item.get("category") or {}
                catalog.append(
                    {
                        "name": name,
                        "description": description[:1000],
                        "url": url,
                        "category": str(
                            category.get("display_name") or ""
                        ).strip(),
                        "installs": str(item.get("installs_count") or 0),
                    }
                )

            self._catalog = catalog
            self._catalog_loaded_at = time.monotonic()
            return catalog

    async def verify_listing(self, name: str, url: str) -> bool:
        catalog = await self._load_catalog(
            force_refresh=True,
            allow_stale=False,
        )
        return any(
            item["name"] == name and item["url"] == url
            for item in catalog
        )

    @staticmethod
    def _terms(text: str) -> set[str]:
        ignored = {
            "agent", "and", "for", "from", "that", "the", "this",
            "their", "them", "they", "with", "want", "will", "into",
            "have", "make", "user", "users", "using", "create",
        }
        return {
            word
            for word in re.findall(r"[a-z0-9]+", text.lower())
            if len(word) > 2 and word not in ignored
        }

    async def find_candidates(self, request: str) -> list[dict[str, str]]:
        catalog = await self._load_catalog()
        request_terms = self._terms(request)
        if not request_terms:
            return []

        ranked = []
        for item in catalog:
            name_terms = self._terms(item["name"].replace("-", " "))
            description_terms = self._terms(item["description"])
            category_terms = self._terms(item["category"])
            score = (
                4 * len(request_terms & name_terms)
                + 2 * len(request_terms & description_terms)
                + len(request_terms & category_terms)
            )
            if score:
                ranked.append((score, int(item["installs"]), item))

        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [item for _, _, item in ranked[: self.MAX_CANDIDATES]]
