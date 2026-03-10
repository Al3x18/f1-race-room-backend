from src.telemetry_runtime_config import TelemetryRuntimeConfig


def test_load_runtime_config_from_file(tmp_path, monkeypatch):
    config_path = tmp_path / "telemetry.toml"
    config_path.write_text(
        "\n".join(
            [
                "max_concurrency = 3",
                "max_plot_points = 1500",
                'cache_dir = "./my-cache"',
                "cache_max_docs = 25",
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


def test_load_runtime_config_uses_env_when_file_missing(monkeypatch):
    monkeypatch.setenv("TELEMETRY_CONFIG_FILE", "/tmp/not-existing-telemetry.toml")
    monkeypatch.setenv("TELEMETRY_MAX_CONCURRENCY", "4")
    monkeypatch.setenv("TELEMETRY_MAX_PLOT_POINTS", "1400")
    monkeypatch.setenv("TELEMETRY_CACHE_DIR", "./alt-cache")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_DOCS", "12")

    config = TelemetryRuntimeConfig.load()

    assert config.max_concurrency == 4
    assert config.max_plot_points == 1400
    assert config.cache_dir == "./alt-cache"
    assert config.cache_max_docs == 12
