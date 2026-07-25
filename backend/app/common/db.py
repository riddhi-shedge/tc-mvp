"""Thread-local Supabase clients.

FastAPI runs sync (`def`) endpoints in an anyio threadpool, so one repo instance
is used from many worker threads at once. supabase-py wraps a single
`httpx.Client` + connection pool that is NOT safe to share across threads —
concurrent requests intermittently fail with `httpx.ReadError: [Errno 35]
Resource temporarily unavailable`, surfacing to the browser as 500s / "Failed to
fetch". Giving each thread its own client (created lazily, then reused for that
thread's lifetime) removes the shared state while keeping per-thread pooling.
"""

from __future__ import annotations

import threading
from typing import Any


class ThreadLocalSupabase:
    def __init__(self, url: str, key: str) -> None:
        self._url = url
        self._key = key
        self._local = threading.local()

    @property
    def client(self) -> Any:
        client = getattr(self._local, "client", None)
        if client is None:
            from supabase import create_client

            client = create_client(self._url, self._key)
            self._local.client = client
        return client
