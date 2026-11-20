"""
Idempotency Key Manager for Academiaai Voicebot Agentic Workflow Engine.
Workstream: W4 (Agentic Workflow) - Team SDE 2
Author: Karthik N M

Days 15-16 Deliverable:
Guarantees:
1. Operations with the same idempotency key are executed at most once.
2. Subsequent calls with an existing key return cached results without re-executing tools.
3. Deterministic key derivation from (plan_id, step_id, tool_name, arguments).
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Dict, Optional


class IdempotencyStore:
    """
    Thread-safe in-memory cache of tool execution results keyed by idempotency tokens.
    Can be serialized / restored via checkpoints.
    """

    def __init__(self, initial_entries: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, Any] = dict(initial_entries or {})

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = value

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._store)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @staticmethod
    def compute_key(
        plan_id: str,
        step_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """
        Computes a deterministic SHA-256 idempotency key based on execution context.
        """
        payload = {
            "plan_id": plan_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "arguments": arguments,
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"idemp-{digest[:16]}"

