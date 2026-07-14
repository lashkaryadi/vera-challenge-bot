"""
Simple in-memory context store.

Rules from the challenge brief we follow here:
  - Context pushes are idempotent by (scope, context_id, version).
  - Re-posting the same version is a no-op.
  - A HIGHER version replaces the previous one atomically.

Swap this for Redis/Postgres later if you want persistence across restarts —
the interface (upsert/get) stays the same either way.
"""

import threading
from typing import Any, Optional


class ContextStore:
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def upsert(
        self,
        scope: str,
        context_id: str,
        version: int,
        payload: dict[str, Any],
        delivered_at: str,
    ) -> tuple[bool, Optional[int]]:
        """Store payload if version is newer.

        Returns:
            (stored, current_version)
        """
        key = (scope, context_id)
        with self._lock:
            existing = self._data.get(key)
            if existing is not None and existing["version"] > version:
                return False, existing["version"]  # older or duplicate version -> no-op
            self._data[key] = {
                "version": version,
                "payload": payload,
                "delivered_at": delivered_at,
            }
            return True, version

    def get(self, scope: str, context_id: str) -> Optional[dict[str, Any]]:
        return self._data.get((scope, context_id))

    def all_in_scope(self, scope: str) -> dict[str, dict[str, Any]]:
        return {cid: v for (s, cid), v in self._data.items() if s == scope}


# One shared store for the whole process.
store = ContextStore()
