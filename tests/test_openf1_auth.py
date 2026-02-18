import asyncio

import httpx

from src.live.providers import OpenF1Provider


def test_openf1_uses_cached_auth_token():
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/token":
            token_calls += 1
            return httpx.Response(
                200,
                request=request,
                json={"access_token": "token-1", "expires_in": 3600},
            )
        if request.url.path == "/v1/sessions":
            assert request.headers.get("Authorization") == "Bearer token-1"
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "session_key": 111,
                        "session_name": "Race",
                        "meeting_key": 1,
                        "meeting_name": "Test GP",
                    }
                ],
            )
        return httpx.Response(404, request=request, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OpenF1Provider(
        base_url="https://api.openf1.org/v1",
        username="user@example.com",
        password="secret",
        token_url="https://api.openf1.org/token",
        client=client,
    )

    async def run_case() -> None:
        await provider.fetch_current_session()
        await provider.fetch_current_session()
        await client.aclose()

    asyncio.run(run_case())
    assert token_calls == 1


def test_openf1_refreshes_token_after_unauthorized():
    token_calls = 0
    sessions_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, sessions_calls
        if request.url.path == "/token":
            token_calls += 1
            token = f"token-{token_calls}"
            return httpx.Response(
                200,
                request=request,
                json={"access_token": token, "expires_in": 3600},
            )
        if request.url.path == "/v1/sessions":
            sessions_calls += 1
            if sessions_calls == 1:
                return httpx.Response(401, request=request, json={"detail": "unauthorized"})
            assert request.headers.get("Authorization") == "Bearer token-2"
            return httpx.Response(
                200,
                request=request,
                json=[{"session_key": 222, "session_name": "Qualifying"}],
            )
        return httpx.Response(404, request=request, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OpenF1Provider(
        base_url="https://api.openf1.org/v1",
        username="user@example.com",
        password="secret",
        token_url="https://api.openf1.org/token",
        client=client,
    )

    async def run_case() -> None:
        session = await provider.fetch_current_session()
        assert session["session_key"] == 222
        await client.aclose()

    asyncio.run(run_case())
    assert token_calls == 2
