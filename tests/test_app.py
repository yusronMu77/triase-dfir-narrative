import pytest
from astria_common.envguard import EnvironmentGuardError
from fastapi.testclient import TestClient
from pydantic import SecretStr

from astria_narrative.main import build_app
from astria_narrative.settings import Settings


def test_health_and_ready_without_dependencies() -> None:
    with TestClient(build_app(Settings(env="test"))) as client:
        health = client.get("/health").json()
        assert health["service"] == "narrative"
        assert health["env"] == "test"
        assert client.get("/ready").status_code == 200
        assert "astria_service_info" in client.get("/metrics").text


def test_card_and_retry_consumers_are_wired_when_db_and_nats_configured() -> None:
    url = SecretStr("postgresql+psycopg://u:p@postgres:5432/narrative_dev")
    app = build_app(Settings(env="dev", database_url=url, nats_url="nats://nats:4222"))
    assert {"consumer:narrative", "consumer:narrative-ulang"} <= set(app.state.components)


def test_rejects_unsupported_backend_chain() -> None:
    with pytest.raises(ValueError):
        build_app(Settings(env="test", narrative_chain="replay,vllm,templat"))


def test_refuses_to_start_with_non_dev_database_in_dev() -> None:
    url = SecretStr("postgresql+psycopg://u:p@postgres:5432/astria")
    with pytest.raises(EnvironmentGuardError):
        build_app(Settings(env="dev", database_url=url))
