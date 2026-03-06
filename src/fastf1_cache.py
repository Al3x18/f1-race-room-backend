from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import fastf1 as ff1


_KNOWN_CACHE_DIRS = (
    Path("/tmp/fastf1-cache"),
    Path("/tmp/.cache/fastf1"),
    Path.home() / ".cache" / "fastf1",
    Path.cwd() / "custom_cache",
)


def disable_fastf1_cache() -> None:
    ff1.Cache.set_disabled()


def purge_fastf1_cache() -> None:
    for cache_dir in _KNOWN_CACHE_DIRS:
        shutil.rmtree(cache_dir, ignore_errors=True)


@contextmanager
def fastf1_cache_guard() -> Iterator[None]:
    disable_fastf1_cache()
    purge_fastf1_cache()
    try:
        yield
    finally:
        disable_fastf1_cache()
        purge_fastf1_cache()
