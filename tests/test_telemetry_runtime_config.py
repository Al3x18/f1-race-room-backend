from src.telemetry_runtime_config import TelemetryRuntimeConfig


def test_default_cache_limits(tmp_path, monkeypatch):
    config_path = tmp_path / "empty-telemetry.toml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("TELEMETRY_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("TELEMETRY_CACHE_MAX_DOCS", raising=False)
    monkeypatch.delenv("TELEMETRY_CACHE_MAX_MB", raising=False)

    config = TelemetryRuntimeConfig.load()

    assert config.cache_max_docs == 100
    assert config.cache_max_mb == 500


def test_load_runtime_config_from_file(tmp_path, monkeypatch):
    config_path = tmp_path / "telemetry.toml"
    config_path.write_text(
        "\n".join(
            [
                "max_concurrency = 3",
                "max_plot_points = 1500",
                'cache_dir = "./my-cache"',
                "cache_max_docs = 25",
                "cache_max_mb = 400",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEMETRY_CONFIG_FILE", str(config_path))

    config = TelemetryRuntimeConfig.load()

    assert config.max_concurrency == 3
    assert config.max_plot_points == 1500
    assert config.cache_dir == "./my-cache"
    assert config.cache_max_docs == 25
    assert config.cache_max_mb == 400


def test_load_runtime_config_uses_env_when_file_missing(monkeypatch):
    monkeypatch.setenv("TELEMETRY_CONFIG_FILE", "/tmp/not-existing-telemetry.toml")
    monkeypatch.setenv("TELEMETRY_MAX_CONCURRENCY", "4")
    monkeypatch.setenv("TELEMETRY_MAX_PLOT_POINTS", "1400")
    monkeypatch.setenv("TELEMETRY_CACHE_DIR", "./alt-cache")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_DOCS", "12")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_MB", "350")

    config = TelemetryRuntimeConfig.load()

    assert config.max_concurrency == 4
    assert config.max_plot_points == 1400
    assert config.cache_dir == "./alt-cache"
    assert config.cache_max_docs == 12
    assert config.cache_max_mb == 350


def test_environment_overrides_file_values(tmp_path, monkeypatch):
    config_path = tmp_path / "telemetry.toml"
    config_path.write_text(
        "\n".join(
            [
                "max_concurrency = 2",
                "max_plot_points = 1800",
                'cache_dir = "./file-cache"',
                "cache_max_docs = 20",
                "cache_max_mb = 500",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEMETRY_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("TELEMETRY_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("TELEMETRY_MAX_PLOT_POINTS", "1200")
    monkeypatch.setenv("TELEMETRY_CACHE_DIR", "/data/telemetry-pdfs")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_DOCS", "100")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_MB", "500")

    config = TelemetryRuntimeConfig.load()

    assert config.max_concurrency == 1
    assert config.max_plot_points == 1200
    assert config.cache_dir == "/data/telemetry-pdfs"
    assert config.cache_max_docs == 100
    assert config.cache_max_mb == 500
