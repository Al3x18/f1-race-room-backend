import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AppSettings:
    # If empty, API key authentication is disabled.
    api_request_key: str = ""
    api_key_header: str = "X-API-Key"
    allowed_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> "AppSettings":
        origins = [
            origin.strip()
            for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
            if origin.strip()
        ]
        return cls(
            api_request_key=os.getenv("API_REQUEST_KEY", "").strip(),
            api_key_header=(
                os.getenv("API_KEY_HEADER", "X-API-Key").strip() or "X-API-Key"
            ),
            allowed_origins=origins or ["*"],
        )
