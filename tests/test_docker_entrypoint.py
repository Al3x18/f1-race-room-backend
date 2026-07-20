from types import SimpleNamespace

import docker_entrypoint
import pytest


def test_prepare_cache_directory_creates_path_for_non_root(tmp_path, monkeypatch):
    cache_dir = tmp_path / "data" / "telemetry-pdfs"
    monkeypatch.setattr(docker_entrypoint.os, "geteuid", lambda: 1000)

    docker_entrypoint.prepare_cache_directory(str(cache_dir))

    assert cache_dir.is_dir()


def test_build_server_command_uses_railway_port():
    command = docker_entrypoint.build_server_command("4321")

    assert command[0] == docker_entrypoint.sys.executable
    assert command[1:4] == ["-m", "uvicorn", "src.server:server"]
    assert command[command.index("--port") + 1] == "4321"
    assert command[command.index("--workers") + 1] == "1"


def test_railway_rejects_missing_api_key(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.delenv("API_REQUEST_KEY", raising=False)

    with pytest.raises(SystemExit, match="API_REQUEST_KEY"):
        docker_entrypoint.validate_railway_configuration()


def test_railway_rejects_placeholder_api_key(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project-id")
    monkeypatch.setenv(
        "API_REQUEST_KEY",
        "replace-with-a-long-random-secret",
    )

    with pytest.raises(SystemExit, match="API_REQUEST_KEY"):
        docker_entrypoint.validate_railway_configuration()


def test_railway_accepts_wildcard_origin_with_private_api_key(monkeypatch):
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project-id")
    monkeypatch.setenv("API_REQUEST_KEY", "a" * 32)
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    docker_entrypoint.validate_railway_configuration()


def test_railway_accepts_private_api_key(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "service-id")
    monkeypatch.setenv("API_REQUEST_KEY", "a" * 32)
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.com")

    docker_entrypoint.validate_railway_configuration()


def test_drop_privileges_sets_appuser_environment(monkeypatch):
    user = SimpleNamespace(
        pw_name="appuser",
        pw_dir="/home/appuser",
        pw_uid=1001,
        pw_gid=1002,
    )
    calls = []
    monkeypatch.setattr(docker_entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(docker_entrypoint.pwd, "getpwnam", lambda _: user)
    monkeypatch.setattr(
        docker_entrypoint.os,
        "initgroups",
        lambda name, gid: calls.append(("initgroups", name, gid)),
    )
    monkeypatch.setattr(
        docker_entrypoint.os,
        "setgid",
        lambda gid: calls.append(("setgid", gid)),
    )
    monkeypatch.setattr(
        docker_entrypoint.os,
        "setuid",
        lambda uid: calls.append(("setuid", uid)),
    )

    docker_entrypoint.drop_privileges()

    assert docker_entrypoint.os.environ["HOME"] == "/home/appuser"
    assert docker_entrypoint.os.environ["USER"] == "appuser"
    assert calls == [
        ("initgroups", "appuser", 1002),
        ("setgid", 1002),
        ("setuid", 1001),
    ]
