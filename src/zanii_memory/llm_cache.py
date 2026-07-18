"""Exact-request LLM/embedding response cache.

Keyed by sha256 of (endpoint, model, full request payload) — an identical
request replays free; ANY change to prompts, model, or params is an automatic
miss, so cached benchmark runs stay scientifically honest. Off by default;
enable with ZANII_LLM_CACHE_PATH (the benchmark harness enables it
automatically to stop re-paying for unchanged ingestion).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .types import now_ms


class LLMCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, kind TEXT NOT NULL, value TEXT NOT NULL, created_at INTEGER NOT NULL)"
        )
        self.db.commit()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key_for(kind: str, model: str, payload: dict[str, Any]) -> str:
        blob = json.dumps({"kind": kind, "model": model, "payload": payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self.db.execute("SELECT value FROM responses WHERE key = ?", (key,)).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(row[0])

    def put(self, key: str, kind: str, value: Any) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO responses (key, kind, value, created_at) VALUES (?, ?, ?, ?)",
                (key, kind, json.dumps(value, ensure_ascii=False), now_ms()),
            )
            self.db.commit()

    def close(self) -> None:
        with self._lock:
            self.db.close()
