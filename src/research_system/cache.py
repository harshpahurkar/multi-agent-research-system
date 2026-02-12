from __future__ import annotations

import os
from typing import Protocol

from .models import ResearchBrief


class Cache(Protocol):
    def get(self, key: str) -> ResearchBrief | None:
        ...

    def set(self, key: str, value: ResearchBrief) -> None:
        ...


class InMemoryCache:
    _MAX_SIZE = 256

    def __init__(self) -> None:
        self._items: dict[str, ResearchBrief] = {}

    def get(self, key: str) -> ResearchBrief | None:
        return self._items.get(key)

    def set(self, key: str, value: ResearchBrief) -> None:
        if key not in self._items and len(self._items) >= self._MAX_SIZE:
            oldest = next(iter(self._items))
            del self._items[oldest]
        self._items[key] = value


class RedisCache:
    def __init__(self, url: str | None = None) -> None:
        try:
            import redis  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install the 'redis' extra to use RedisCache.") from exc
        redis_url = url or os.getenv("REDIS_URL")
        if not redis_url:
            raise RuntimeError("REDIS_URL is required when Redis cache backend is enabled.")
        self.client = redis.Redis.from_url(redis_url)

    def get(self, key: str) -> ResearchBrief | None:
        raw = self.client.get(key)
        if not raw:
            return None
        payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return ResearchBrief.model_validate_json(payload)

    def set(self, key: str, value: ResearchBrief) -> None:
        self.client.set(key, value.model_dump_json(), ex=3600)
