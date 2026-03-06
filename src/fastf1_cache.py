from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fastf1 as ff1


_RUNTIME_CACHE_DIR = Path("/tmp/fastf1-cache")
_KNOWN_CACHE_DIRS = (
    _RUNTIME_CACHE_DIR,
    Path("/tmp/fastf1-cache"),
    Path("/tmp/.cache/fastf1"),
    Path.home() / ".fastf1",
    Path.home() / ".cache" / "fastf1",
    Path.cwd() / "custom_cache",
)


def disable_fastf1_cache() -> None:
    ff1.Cache.set_disabled()


def route_fastf1_cache_to_tmp() -> None:
    _RUNTIME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ff1.Cache.enable_cache(str(_RUNTIME_CACHE_DIR))


def purge_fastf1_cache() -> None:
    for cache_dir in _KNOWN_CACHE_DIRS:
        shutil.rmtree(cache_dir, ignore_errors=True)


@contextmanager
def fastf1_cache_guard() -> Iterator[None]:
    purge_fastf1_cache()
    route_fastf1_cache_to_tmp()
    try:
        yield
    finally:
        purge_fastf1_cache()
        disable_fastf1_cache()
