import time
from pathlib import Path

from src.telemetry.cache import TelemetryPdfCache


def test_single_filename_format(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=20)
    name = cache.single_filename(
        year=2026,
        track_name="Australian Grand Prix",
        session="R",
        driver_name="VER",
    )
    assert name == "ver_australian_grand_prix_race_2026.pdf"


def test_compare_filename_format(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=20)
    name = cache.comparison_filename(
        year=2026,
        track_name="Australian Grand Prix",
        session="R",
        driver_a="VER",
        driver_b="LEC",
    )
    assert name == "ver_vs_lec_australian_grand_prix_race_2026.pdf"


def test_enforce_limit_eviction(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=3)

    for idx in range(1, 4):
        path = tmp_path / f"doc_{idx}.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        time.sleep(0.01)

    cache.enforce_limit()

    assert len(list(tmp_path.glob("*.pdf"))) == 3


def test_prepare_output_path_evicts_oldest_when_full(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=3, max_bytes=1024)

    for idx in range(1, 4):
        path = tmp_path / f"doc_{idx}.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        time.sleep(0.01)

    oldest = tmp_path / "doc_1.pdf"
    assert oldest.exists()

    output_path = Path(cache.prepare_output_path("new_doc.pdf"))
    output_path.write_bytes(b"%PDF-1.4 new")
    final_path = cache.commit_output("new_doc.pdf", output_path)

    assert final_path.endswith("new_doc.pdf")
    assert not oldest.exists()
    assert len(list(tmp_path.glob("*.pdf"))) == 3


def test_enforce_limit_evicts_by_total_bytes(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=10, max_bytes=30)

    for idx in range(1, 4):
        path = tmp_path / f"doc_{idx}.pdf"
        path.write_bytes(b"%PDF-" + bytes([idx]) * 10)
        time.sleep(0.01)

    cache.enforce_limit()

    assert not (tmp_path / "doc_1.pdf").exists()
    assert len(list(tmp_path.glob("*.pdf"))) == 2
    assert cache.stats()["bytes"] == 30


def test_cache_hit_updates_lru_order(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=2, max_bytes=1024)
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-first")
    time.sleep(0.01)
    second.write_bytes(b"%PDF-second")
    time.sleep(0.01)

    assert cache.get_cached_path("first.pdf") == str(first)
    staged = Path(cache.prepare_output_path("third.pdf"))
    staged.write_bytes(b"%PDF-third")
    cache.commit_output("third.pdf", staged)

    assert first.exists()
    assert not second.exists()
    assert (tmp_path / "third.pdf").exists()


def test_incomplete_pdf_is_removed_and_treated_as_miss(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=2, max_bytes=1024)
    incomplete = tmp_path / "broken.pdf"
    incomplete.write_bytes(b"")

    assert cache.get_cached_path("broken.pdf") is None
    assert not incomplete.exists()


def test_generated_pdf_larger_than_limit_is_rejected(tmp_path: Path):
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=2, max_bytes=8)
    staged = Path(cache.prepare_output_path("large.pdf"))
    staged.write_bytes(b"%PDF-too-large")

    try:
        cache.commit_output("large.pdf", staged)
    except RuntimeError as exc:
        assert "above cache limit" in str(exc)
    else:
        raise AssertionError("Expected oversized PDF to be rejected")

    assert not staged.exists()
    assert not (tmp_path / "large.pdf").exists()
