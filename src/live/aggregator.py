import asyncio
import copy
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class LiveAggregator:
    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._condition = asyncio.Condition()
        self._version = 0
        self._provider = "none"
        self._status = "starting"
        self._current_session: Dict[str, Any] = {}
        self._timing: Dict[str, Any] = {}
        self._last_error: Optional[str] = None
        self._last_updated: Optional[str] = None

    def _snapshot_unlocked(self) -> Dict[str, Any]:
        return {
            "version": self._version,
            "provider": self._provider,
            "status": self._status,
            "current_session": copy.deepcopy(self._current_session),
            "timing": copy.deepcopy(self._timing),
            "last_error": self._last_error,
            "last_updated": self._last_updated,
        }

    def get_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return self._snapshot_unlocked()

    async def update(
        self,
        provider_name: str,
        current_session: Dict[str, Any],
        timing: Dict[str, Any],
        status: str,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        changed = False
        with self._state_lock:
            if (
                self._provider != provider_name
                or self._status != status
                or self._last_error != error
                or self._current_session != current_session
                or self._timing != timing
            ):
                self._provider = provider_name
                self._status = status
                self._last_error = error
                self._current_session = copy.deepcopy(current_session)
                self._timing = copy.deepcopy(timing)
                self._last_updated = datetime.now(timezone.utc).isoformat()
                self._version += 1
                changed = True

            snapshot = self._snapshot_unlocked()

        if changed:
            async with self._condition:
                self._condition.notify_all()

        return snapshot

    async def mark_degraded(self, provider_name: str, error: str) -> Dict[str, Any]:
        return await self.update(
            provider_name=provider_name,
            current_session={},
            timing={},
            status="degraded",
            error=error,
        )

    @property
    def version(self) -> int:
        with self._state_lock:
            return self._version

    async def wait_for_new_version(
        self, current_version: int, timeout: float
    ) -> Optional[Dict[str, Any]]:
        if self.version > current_version:
            return self.get_snapshot()

        async def _wait() -> None:
            async with self._condition:
                await self._condition.wait_for(lambda: self.version > current_version)

        try:
            await asyncio.wait_for(_wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

        return self.get_snapshot()
