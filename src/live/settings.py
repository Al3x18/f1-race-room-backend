import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class AppSettings:
    openf1_base_url: str = "https://api.openf1.org/v1"
    openf1_api_key: str = ""
    live_poll_ms: int = 800
    live_heartbeat_sec: int = 10
    allowed_origins: List[str] = None
    provider: str = "signalr"
    provider_order: List[str] = None
    signalr_connection_url: str = "wss://livetiming.formula1.com/signalrcore"
    signalr_negotiate_url: str = "https://livetiming.formula1.com/signalrcore/negotiate"
    signalr_timeout_sec: int = 8
    signalr_no_auth: bool = True
    signalr_access_token: str = ""
    signalr_verify_ssl: bool = True

    @staticmethod
    def _parse_csv(value: str) -> List[str]:
        return [item.strip().lower() for item in value.split(",") if item.strip()]

    @staticmethod
    def _parse_bool(value: str, default: bool) -> bool:
        if value is None:
            return default
        return value.strip().lower() not in {"0", "false", "no", "off"}

    @classmethod
    def from_env(cls) -> "AppSettings":
        origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
        origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
        if not origins:
            origins = ["*"]

        provider_order_raw = os.getenv("PROVIDER_ORDER", "")
        provider_order = cls._parse_csv(provider_order_raw) if provider_order_raw.strip() else None

        return cls(
            openf1_base_url=os.getenv("OPENF1_BASE_URL", "https://api.openf1.org/v1"),
            openf1_api_key=os.getenv("OPENF1_API_KEY", ""),
            live_poll_ms=int(os.getenv("LIVE_POLL_MS", "800")),
            live_heartbeat_sec=int(os.getenv("LIVE_HEARTBEAT_SEC", "10")),
            allowed_origins=origins,
            provider=os.getenv("PROVIDER", "signalr").strip().lower(),
            provider_order=provider_order,
            signalr_connection_url=os.getenv(
                "SIGNALR_CONNECTION_URL",
                "wss://livetiming.formula1.com/signalrcore",
            ),
            signalr_negotiate_url=os.getenv(
                "SIGNALR_NEGOTIATE_URL",
                "https://livetiming.formula1.com/signalrcore/negotiate",
            ),
            signalr_timeout_sec=int(os.getenv("SIGNALR_TIMEOUT_SEC", "8")),
            signalr_no_auth=cls._parse_bool(os.getenv("SIGNALR_NO_AUTH"), True),
            signalr_access_token=os.getenv("SIGNALR_ACCESS_TOKEN", ""),
            signalr_verify_ssl=cls._parse_bool(os.getenv("SIGNALR_VERIFY_SSL"), True),
        )
