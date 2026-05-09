"""Auth + rate-limiting end-to-end tests via FastAPI's TestClient.

We construct the real app (with a per-test SQLite + ChromaDB) and run
it as a context-manager so the FastAPI lifespan handler creates the
schema before any test runs. Then we exercise:

- Registration and login round-trip return a usable JWT.
- Bad credentials get 401, duplicate emails get 400.
- `GET /api/v1/auth/me` requires a token.
- Anonymous chat is allowed but rate-limited (config tightened to a
  small number for the duration of the test) and authenticated users
  bypass the anonymous bucket.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from backend.main import create_app


pytestmark = pytest.mark.usefixtures("isolated_env")


def _build_client() -> TestClient:
    app = create_app()
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    return TestClient(app)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _build_client() as test_client:
        yield test_client


def test_register_and_login_round_trip(client: TestClient) -> None:
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "supersecret123"},
    )
    assert register.status_code == 200, register.text
    payload = register.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"]["email"] == "alice@example.com"

    token = payload["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "ALICE@example.com", "password": "supersecret123"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == payload["user"]["id"]


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    payload = {"email": "bob@example.com", "password": "supersecret123"}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 200
    second = client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 400
    assert "already" in second.json()["detail"].lower()


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "short"},
    )
    # Pydantic v2 returns 422 for min_length violations, our own 400 for
    # the secondary domain check; either is acceptable here.
    assert response.status_code in (400, 422)


def test_login_with_wrong_password_returns_401(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "dan@example.com", "password": "supersecret123"},
    )
    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "dan@example.com", "password": "wrongguess1"},
    )
    assert bad.status_code == 401


def test_me_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_rejects_garbage_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


def test_anonymous_chat_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RATE_LIMIT_CHAT_ANONYMOUS", "2/minute")
    from backend import config

    config.get_settings.cache_clear()
    with respx.mock(base_url="http://ollama.test", assert_all_called=False) as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "ok"}}
            )
        )
        with _build_client() as test_client:
            first = test_client.post(
                "/api/v1/chat",
                json={"message": "hello", "agent_override": "communication"},
            )
            second = test_client.post(
                "/api/v1/chat",
                json={"message": "hello", "agent_override": "communication"},
            )
            third = test_client.post(
                "/api/v1/chat",
                json={"message": "hello", "agent_override": "communication"},
            )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 429


def test_authenticated_chat_uses_higher_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With anonymous=1/minute and authenticated=10/minute, two calls
    from the same logged-in user should both succeed."""
    monkeypatch.setenv("RATE_LIMIT_CHAT_ANONYMOUS", "1/minute")
    monkeypatch.setenv("RATE_LIMIT_CHAT_AUTHENTICATED", "10/minute")
    from backend import config

    config.get_settings.cache_clear()
    with respx.mock(base_url="http://ollama.test", assert_all_called=False) as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "ok"}}
            )
        )
        with _build_client() as test_client:
            register = test_client.post(
                "/api/v1/auth/register",
                json={"email": "eve@example.com", "password": "supersecret123"},
            )
            assert register.status_code == 200, register.text
            token = register.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            first = test_client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "hi", "agent_override": "communication"},
            )
            second = test_client.post(
                "/api/v1/chat",
                headers=headers,
                json={"message": "hi", "agent_override": "communication"},
            )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


async def test_password_hash_round_trip() -> None:
    from backend.security.auth import hash_password, verify_password

    hashed = hash_password("supersecret123")
    assert hashed != "supersecret123"
    assert verify_password("supersecret123", hashed) is True
    assert verify_password("not-it", hashed) is False
