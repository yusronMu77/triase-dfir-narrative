"""Pemilihan provider model: `anthropic` atau `openai_compat`, dari env atau menu Konfigurasi.

Urutan prioritas: override dari layanan `config` (menu Konfigurasi), lalu env. Hanya kunci non-rahasia yang boleh
ditimpa (`provider`, `base_url`, `model_id`); kunci API tidak pernah lewat `config`. Fungsi ini hanya memvalidasi
dan menyusun konfigurasi. Klien HTTP dan kebijakan egress dibuat di backend (note app-narrative 5.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

from astria_narrative.settings import ProviderName, Settings

ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
OVERRIDABLE = frozenset({"provider", "base_url", "model_id"})
Role = Literal["online", "local"]


class ProviderConfigError(ValueError):
    """Konfigurasi provider tidak lengkap atau tidak aman; backend itu dinonaktifkan dan alasan dicatat."""


@dataclass(frozen=True, slots=True, repr=False)
class ProviderConfig:
    role: Role
    provider: ProviderName
    base_url: str
    model_id: str
    api_key: SecretStr | None

    def __repr__(self) -> str:  # kunci tidak boleh muncul di log
        key = "set" if self.api_key is not None else "unset"
        return (
            f"ProviderConfig(role={self.role}, provider={self.provider}, base_url={self.base_url}, "
            f"model_id={self.model_id}, api_key={key})"
        )


def _clean(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _check_overrides(overrides: Mapping[str, object]) -> None:
    unknown = set(overrides) - OVERRIDABLE
    if unknown:
        raise ProviderConfigError(f"kunci tidak boleh ditimpa dari config: {sorted(unknown)}")


def _validate_url(url: str, *, require_https: bool) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ProviderConfigError(f"base URL tidak valid: {url!r}")
    if require_https and parts.scheme != "https":
        raise ProviderConfigError("backend online wajib https")
    if parts.username or parts.password:
        raise ProviderConfigError("base URL tidak boleh memuat kredensial")
    return url.rstrip("/")


def resolve_online(settings: Settings, overrides: Mapping[str, object] | None = None) -> ProviderConfig | None:
    """Konfigurasi backend online, atau None bila dinonaktifkan (tanpa model id dan tanpa base URL openai_compat)."""
    ov = dict(overrides or {})
    _check_overrides(ov)
    provider = _clean(ov.get("provider")) or settings.narrative_online_provider
    if provider not in ("anthropic", "openai_compat"):
        raise ProviderConfigError(f"provider tidak dikenal: {provider!r} (anthropic atau openai_compat)")
    base_url = _clean(ov.get("base_url")) or settings.narrative_online_base_url
    model_id = _clean(ov.get("model_id")) or settings.narrative_online_model_id

    if provider == "anthropic":
        base_url = base_url or ANTHROPIC_DEFAULT_BASE_URL
        if model_id is None:
            return None  # belum dikonfigurasi: backend online nonaktif
        if settings.model_api_key is None:
            raise ProviderConfigError("anthropic: ASTRIA_MODEL_API_KEY wajib diisi")
    else:
        if base_url is None or model_id is None:
            return None  # kosong berarti backend online nonaktif (note 5.5)
    return ProviderConfig(
        role="online",
        provider=provider,  # type: ignore[arg-type]  # sudah divalidasi di atas
        base_url=_validate_url(base_url, require_https=True),
        model_id=model_id,
        api_key=settings.model_api_key,
    )


def resolve_local(settings: Settings, overrides: Mapping[str, object] | None = None) -> ProviderConfig | None:
    """Backend lokal: selalu openai_compat (llama-server atau server privat). None bila id model kosong."""
    ov = dict(overrides or {})
    _check_overrides(ov)
    if "provider" in ov and _clean(ov["provider"]) not in (None, "openai_compat"):
        raise ProviderConfigError("backend lokal hanya mendukung openai_compat")
    model_id = _clean(ov.get("model_id")) or settings.narrative_local_model_id
    if model_id is None:
        return None
    base_url = _clean(ov.get("base_url")) or settings.narrative_local_base_url
    return ProviderConfig(
        role="local",
        provider="openai_compat",
        base_url=_validate_url(base_url, require_https=False),
        model_id=model_id,
        api_key=settings.narrative_local_api_key,
    )
