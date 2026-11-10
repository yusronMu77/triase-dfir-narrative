"""Backend `online`: adaptor httpx tipis untuk API Messages Anthropic dan endpoint OpenAI-compatible (tanpa LiteLLM).

Setiap panggilan lewat pagar egress, dibatasi waktu, dan keluarannya divalidasi dengan model kontrak `Narasi`
(`extra=forbid`). Hasilnya satu kode `outcome` untuk `model_call`; kegagalan apa pun membuat router lanjut ke backend
berikutnya. Kunci API, prompt, dan keluaran tidak pernah dicatat di log; yang dicatat hanya `prompt_sha256`.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
import orjson
from astria_common.log import get_logger
from astria_contracts.events.narration_completed import Narasi

from astria_narrative import egress, prompt
from astria_narrative.cache import PARAMS
from astria_narrative.providers import ProviderConfig, ProviderConfigError, resolve_online
from astria_narrative.settings import Settings

log = get_logger(__name__)

# Versi API ini menolak `temperature`/`top_p`; model Anthropic terkini hanya menerima nilai bawaan.
ANTHROPIC_VERSION = "2026-10-21"


@dataclass(frozen=True, slots=True)
class Hasil:
    outcome: str
    """`ok`, `skema_gagal`, `batas_waktu`, `backend_gagal`, atau `egress_ditolak`."""
    narasi: Narasi | None = None
    latency_ms: int | None = None


def parse_narasi(text: str) -> Narasi:
    """Ambil objek JSON terluar dari teks model, lalu validasi dengan kontrak. Gagal: `ValueError`."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("keluaran tanpa objek JSON")
    return Narasi.model_validate(orjson.loads(text[start : end + 1]))


class OnlineBackend:
    def __init__(
        self,
        cfg: ProviderConfig,
        *,
        allowlist: frozenset[str],
        allow_private: bool = False,
        timeout_s: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: egress.Resolver = egress.resolve,
    ) -> None:
        self.cfg = cfg
        self.allowlist = allowlist
        self.allow_private = allow_private
        self.timeout_s = timeout_s
        self.transport = transport
        self.resolver = resolver

    @property
    def model_id(self) -> str:
        return self.cfg.model_id

    def _request(self, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        key = self.cfg.api_key.get_secret_value() if self.cfg.api_key is not None else None
        if self.cfg.provider == "anthropic":
            headers = {"anthropic-version": ANTHROPIC_VERSION}
            if key:
                headers["x-api-key"] = key
            body: dict[str, Any] = {
                "model": self.cfg.model_id,
                "max_tokens": PARAMS["max_tokens"],
                # Tugas ringkas: pemikiran sedikit agar anggaran 800 token tidak habis sebelum JSON selesai.
                "output_config": {"effort": "low"},
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            return f"{self.cfg.base_url}/v1/messages", headers, body
        headers = {"authorization": f"Bearer {key}"} if key else {}
        body = {
            "model": self.cfg.model_id,
            "max_tokens": PARAMS["max_tokens"],
            "temperature": PARAMS["temperature"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        return f"{self.cfg.base_url}/chat/completions", headers, body

    def _text(self, body: Any) -> str:
        if self.cfg.provider == "anthropic":
            return "".join(b["text"] for b in body["content"] if b.get("type") == "text")
        return body["choices"][0]["message"]["content"]

    async def _call(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> Narasi:
        await egress.check(url, self.allowlist, allow_private=self.allow_private, resolver=self.resolver)
        async with httpx.AsyncClient(
            timeout=self.timeout_s, follow_redirects=False, trust_env=False, transport=self.transport
        ) as client:
            response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        return parse_narasi(self._text(response.json()))

    async def narrate(self, paket: dict[str, Any], kegagalan: Sequence[tuple[int, str]] = ()) -> Hasil:
        """Satu panggilan untuk paket yang sudah disamarkan. Tidak pernah melempar galat backend."""
        system, user = prompt.build(paket, kegagalan)
        url, headers, body = self._request(system, user)
        narasi, alasan = None, None
        mulai = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_s):
                narasi = await self._call(url, headers, body)
            outcome = "ok"
        except egress.EgressDitolak as exc:
            outcome, alasan = "egress_ditolak", str(exc)
        except TimeoutError, httpx.TimeoutException:
            outcome = "batas_waktu"
        except httpx.HTTPStatusError as exc:
            outcome, alasan = "backend_gagal", f"HTTP {exc.response.status_code}"
        except (httpx.HTTPError, OSError) as exc:
            outcome, alasan = "backend_gagal", type(exc).__name__
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:  # respons, JSON, atau skema
            outcome, alasan = "skema_gagal", type(exc).__name__
        latency_ms = round((time.monotonic() - mulai) * 1000)
        log.info(
            "panggilan_online",
            provider=self.cfg.provider,
            model_id=self.cfg.model_id,
            outcome=outcome,
            alasan=alasan,
            latency_ms=latency_ms,
            prompt_sha256=hashlib.sha256(f"{system}\n{user}".encode()).hexdigest(),
        )
        return Hasil(outcome, narasi, latency_ms)


def build_online(settings: Settings) -> OnlineBackend | None:
    """Backend online dari konfigurasi, atau None (dinonaktifkan, alasan dicatat) agar rantai tetap jalan."""
    try:
        cfg = resolve_online(settings)
    except ProviderConfigError as exc:
        log.warning("online_nonaktif", alasan=str(exc))
        return None
    if cfg is None:
        log.warning("online_nonaktif", alasan="ASTRIA_NARRATIVE_ONLINE_MODEL_ID atau BASE_URL kosong")
        return None
    return OnlineBackend(
        cfg,
        allowlist=egress.parse_allowlist(settings.narrative_egress_allowlist),
        allow_private=settings.narrative_egress_allow_private,
        timeout_s=settings.narrative_timeout_s,
    )
