import asyncio
from typing import Any, Dict, List

from .aggregator import LiveAggregator
from .providers import LiveProvider


class LiveService:
    def __init__(
        self,
        aggregator: LiveAggregator,
        providers: List[LiveProvider],
        poll_ms: int,
    ) -> None:
        if not providers:
            raise ValueError("LiveService requires at least one provider")
        self._aggregator = aggregator
        self._providers = providers
        self._poll_interval = max(poll_ms, 100) / 1000.0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def reload(self) -> Dict[str, Any]:
        await self._poll_once()
        return self._aggregator.get_snapshot()

    async def _poll_loop(self) -> None:
        while True:
            await self._poll_once()
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        errors: List[str] = []

        for index, provider in enumerate(self._providers):
            try:
                session = await provider.fetch_current_session()
                timing = await provider.fetch_timing_snapshot(
                    session_key=session.get("session_key")
                )
                await self._aggregator.update(
                    provider_name=provider.name,
                    current_session=session,
                    timing=timing,
                    status="online" if index == 0 else "degraded",
                    error=None if index == 0 else "; ".join(errors),
                )
                return
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")

        await self._aggregator.mark_degraded(
            provider_name=self._providers[0].name,
            error="; ".join(errors) if errors else "No provider configured",
        )
