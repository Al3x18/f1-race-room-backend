import json
from datetime import datetime, timezone
from typing import AsyncIterator, Dict

from fastapi import Request

from .aggregator import LiveAggregator


class SSEBroadcaster:
    def __init__(self, aggregator: LiveAggregator, heartbeat_sec: int) -> None:
        self._aggregator = aggregator
        self._heartbeat_sec = max(heartbeat_sec, 1)

    @staticmethod
    def _encode_sse(event: str, payload: Dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

    async def stream(self, request: Request) -> AsyncIterator[str]:
        current_version = self._aggregator.version

        while True:
            if await request.is_disconnected():
                break

            snapshot = await self._aggregator.wait_for_new_version(
                current_version=current_version,
                timeout=self._heartbeat_sec,
            )

            if snapshot is None:
                heartbeat = {
                    "version": current_version,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                yield self._encode_sse("heartbeat", heartbeat)
                continue

            current_version = snapshot["version"]
            yield self._encode_sse("update", snapshot)
