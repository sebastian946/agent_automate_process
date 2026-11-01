"""Rate limit en memoria por clave (cliente_id). Suficiente para 1 réplica; en multi-réplica usar Redis."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self.max = max_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, clave: str) -> bool:
        ahora = time.monotonic()
        with self._lock:
            q = self._hits[clave]
            while q and ahora - q[0] > 60:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(ahora)
            return True
