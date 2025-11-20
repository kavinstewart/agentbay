from __future__ import annotations


class _LazyRuntimeRegistry:
    def __init__(self) -> None:
        self._instance = None

    def _ensure(self):
        if self._instance is None:
            from app.db import AsyncSessionLocal
            from app.services.runtime import RuntimeRegistry

            self._instance = RuntimeRegistry(AsyncSessionLocal)
        return self._instance

    def __getattr__(self, item):
        return getattr(self._ensure(), item)


runtime_registry = _LazyRuntimeRegistry()
