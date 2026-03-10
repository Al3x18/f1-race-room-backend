import time
from pathlib import Path

from src.telemetry_cache import TelemetryPdfCache


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
    cache = TelemetryPdfCache(cache_dir=str(tmp_path), max_docs=3)

    for idx in range(1, 4):
        path = tmp_path / f"doc_{idx}.pdf"
        path.write_bytes(b"%PDF-1.4 test")
        time.sleep(0.01)

    oldest = tmp_path / "doc_1.pdf"
    assert oldest.exists()

    output_path = cache.prepare_output_path("new_doc.pdf")

    assert output_path.endswith("new_doc.pdf")
    assert not oldest.exists()
    assert len(list(tmp_path.glob("*.pdf"))) == 2
