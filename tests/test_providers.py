import pytest
from astria_common.envguard import EnvironmentGuardError, enforce
from pydantic import SecretStr

from astria_narrative.providers import (
    ANTHROPIC_DEFAULT_BASE_URL,
    ProviderConfigError,
    resolve_local,
    resolve_online,
)
from astria_narrative.settings import Settings


def settings(**kw: object) -> Settings:
    return Settings(env="test", **kw)  # type: ignore[arg-type]


def test_defaults_disable_online_until_configured() -> None:
    assert resolve_online(settings()) is None
    assert resolve_local(settings()) is None


def test_anthropic_from_env() -> None:
    cfg = resolve_online(
        settings(
            narrative_online_provider="anthropic",
            narrative_online_model_id="claude-sonnet-5-5",
            model_api_key=SecretStr("sk-test"),
        )
    )
    assert cfg is not None
    assert (cfg.provider, cfg.base_url, cfg.model_id) == ("anthropic", ANTHROPIC_DEFAULT_BASE_URL, "claude-sonnet-5-5")


def test_anthropic_requires_key() -> None:
    with pytest.raises(ProviderConfigError, match="ASTRIA_MODEL_API_KEY"):
        resolve_online(settings(narrative_online_model_id="claude-sonnet-5-5"))


def test_openai_compat_from_env_key_optional() -> None:
    cfg = resolve_online(
        settings(
            narrative_online_provider="openai_compat",
            narrative_online_base_url="https://llm.example.org/v1/",
            narrative_online_model_id="gpt-x",
        )
    )
    assert cfg is not None
    assert (cfg.provider, cfg.base_url, cfg.api_key) == ("openai_compat", "https://llm.example.org/v1", None)


def test_openai_compat_without_base_url_is_disabled() -> None:
    assert resolve_online(settings(narrative_online_provider="openai_compat", narrative_online_model_id="m")) is None


def test_settings_menu_override_switches_provider_but_key_stays_in_env() -> None:
    base = settings(
        narrative_online_provider="anthropic",
        narrative_online_model_id="claude-sonnet-5-5",
        model_api_key=SecretStr("sk-test"),
    )
    cfg = resolve_online(
        base, {"provider": "openai_compat", "base_url": "https://llm.example.org/v1", "model_id": "qwen"}
    )
    assert cfg is not None
    assert (cfg.provider, cfg.model_id) == ("openai_compat", "qwen")
    assert cfg.api_key is not None and cfg.api_key.get_secret_value() == "sk-test"


def test_api_key_cannot_be_overridden_from_config() -> None:
    with pytest.raises(ProviderConfigError, match="tidak boleh ditimpa"):
        resolve_online(settings(), {"api_key": "x"})


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ProviderConfigError, match="tidak dikenal"):
        resolve_online(settings(), {"provider": "gemini"})


def test_online_requires_https_and_no_credentials() -> None:
    with pytest.raises(ProviderConfigError, match="https"):
        resolve_online(
            settings(
                narrative_online_provider="openai_compat",
                narrative_online_base_url="http://llm.example.org/v1",
                narrative_online_model_id="m",
            )
        )
    with pytest.raises(ProviderConfigError, match="kredensial"):
        resolve_online(
            settings(
                narrative_online_provider="openai_compat",
                narrative_online_base_url="https://user:pw@llm.example.org/v1",
                narrative_online_model_id="m",
            )
        )


def test_local_is_openai_compat_and_allows_http() -> None:
    cfg = resolve_local(settings(narrative_local_model_id="qwen3.5-4b"))
    assert cfg is not None
    assert (cfg.provider, cfg.base_url) == ("openai_compat", "http://llama:8080/v1")
    with pytest.raises(ProviderConfigError, match="hanya mendukung openai_compat"):
        resolve_local(settings(narrative_local_model_id="m"), {"provider": "anthropic"})


def test_repr_never_leaks_key() -> None:
    cfg = resolve_online(settings(narrative_online_model_id="m", model_api_key=SecretStr("sk-secret-123")))
    assert cfg is not None
    assert "sk-secret-123" not in repr(cfg)
    assert "api_key=set" in repr(cfg)


def test_prod_guard_still_forbids_online_key() -> None:
    with pytest.raises(EnvironmentGuardError):
        enforce(Settings(env="prod", model_api_key=SecretStr("sk-test")))
