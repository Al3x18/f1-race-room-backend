from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path


DEFAULT_CACHE_DIR = "/data/telemetry-pdfs"
DEFAULT_PORT = "5050"
APP_USER = "appuser"
RAILWAY_ENVIRONMENT_MARKERS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)
INSECURE_API_KEYS = {
    "",
    "change-me",
    "changeme",
    "replace-me",
    "replace-with-a-long-random-secret",
}
INSECURE_ALLOWED_ORIGINS = {
    "",
    "*",
    "https://your-frontend.example",
}


def validate_railway_configuration() -> None:
    if not any(os.getenv(name) for name in RAILWAY_ENVIRONMENT_MARKERS):
        return

    api_key = os.getenv("API_REQUEST_KEY", "").strip()
    if api_key.lower() in INSECURE_API_KEYS or len(api_key) < 32:
        raise SystemExit(
            "Refusing to start on Railway: set API_REQUEST_KEY to a private "
            "random value of at least 32 characters."
        )

    allowed_origins = {
        origin.strip().lower()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    }
    if not allowed_origins or allowed_origins & INSECURE_ALLOWED_ORIGINS:
        raise SystemExit(
            "Refusing to start on Railway: set ALLOWED_ORIGINS to the explicit "
            "HTTPS origin of the frontend."
        )


def prepare_cache_directory(cache_dir: str, user_name: str = APP_USER) -> None:
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)

    if os.geteuid() != 0:
        return

    user = pwd.getpwnam(user_name)
    for current_dir, directory_names, file_names in os.walk(path):
        os.chown(current_dir, user.pw_uid, user.pw_gid)
        for item_name in directory_names + file_names:
            item_path = Path(current_dir) / item_name
            try:
                os.chown(item_path, user.pw_uid, user.pw_gid, follow_symlinks=False)
            except FileNotFoundError:
                pass


def drop_privileges(user_name: str = APP_USER) -> None:
    if os.geteuid() != 0:
        return

    user = pwd.getpwnam(user_name)
    os.environ["HOME"] = user.pw_dir
    os.environ["USER"] = user.pw_name
    os.environ["LOGNAME"] = user.pw_name
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)


def build_server_command(port: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "src.server:server",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--workers",
        "1",
    ]


def main() -> None:
    cache_dir = os.getenv("TELEMETRY_CACHE_DIR", DEFAULT_CACHE_DIR)
    port = os.getenv("PORT", DEFAULT_PORT)

    validate_railway_configuration()
    prepare_cache_directory(cache_dir)
    drop_privileges()
    os.execv(sys.executable, build_server_command(port))


if __name__ == "__main__":
    main()
