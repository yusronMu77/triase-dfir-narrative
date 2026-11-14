"""Backend `lokal`: model yang dihosting sendiri (llama-server) di jaringan privat, lewat transport OpenAI-compatible.

Bedanya dengan `online`:

- Pagar egress `egress.check_lokal`: host wajib mengarah ke alamat privat atau loopback (bukan metadata link-local),
  http boleh. Provider daring tidak bisa dipakai sebagai `lokal`, jadi `lokal` boleh di `ASTRIA_ENV=prod`.
- Kunci `ASTRIA_MODEL_API_KEY` tidak pernah dipakai; server lokal memakai `ASTRIA_NARRATIVE_LOCAL_API_KEY` sendiri.
- Constrained decoding: setiap permintaan membawa `response_format` JSON schema yang disusun dari kartu itu. ID bukti
  hanya boleh dari daftar bukti kartu (enum), `nilai_dikutip` tidak ditawarkan, dan teks bebas tidak boleh memuat garis
  bawah kecuali sebagai samaran yang ada di paket, sehingga model kecil tidak bisa mengarang ID bukti atau samaran
  baru (uji 2026-11-10: `IP_1` karangan). Skema hanya mempersempit keluaran; validasi kontrak `Narasi`, pemulihan
  samaran, dan verifier tetap berjalan seperti backend lain.
- Batas buka koneksi pendek (`ASTRIA_NARRATIVE_LOCAL_CONNECT_TIMEOUT_S`): VM model yang mati gagal cepat ke `templat`.
"""

from __future__ import annotations

import re
from typing import Any

from astria_common.log import get_logger

from astria_narrative import egress, pseudonym
from astria_narrative.online import OnlineBackend
from astria_narrative.providers import ProviderConfigError, resolve_local
from astria_narrative.settings import Settings

log = get_logger(__name__)

MAKS_RINGKASAN, MAKS_TANDINGAN, MAKS_BELUM = 6, 3, 5
"""Batas jumlah butir sesuai aturan prompt (`prompt.PETUNJUK` butir 3 dan 5)."""


def _samaran(paket: dict[str, Any]) -> list[str]:
    teks = repr(paket)  # cukup untuk mencari token samaran; urutan tidak penting
    return sorted(set(pseudonym.PLACEHOLDER.findall(teks)))


def _teks(samaran: list[str]) -> dict[str, Any]:
    """String tanpa garis bawah, kecuali samaran yang ada di paket. Kutip, backslash, dan kontrol tidak diizinkan agar
    grammar tidak bisa menghasilkan JSON rusak."""
    biasa = r'[^_"\\\x00-\x1f]'
    pilihan = "|".join([biasa, *(re.escape(s) for s in samaran)])
    return {"type": "string", "minLength": 1, "pattern": f"^({pilihan})+$"}


def skema_narasi(paket: dict[str, Any]) -> dict[str, Any]:
    """JSON schema kontrak `Narasi` yang dipersempit ke kartu ini (paket sudah disamarkan)."""
    ids = [b["id"] for b in paket["bukti"]]
    bukti = {"type": "array", "items": {"type": "string", "enum": ids}, "minItems": 1, "maxItems": min(len(ids), 8)}
    teks = _teks(_samaran(paket))

    def objek(props: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    return objek(
        {
            "ringkasan": {
                "type": "array",
                "items": objek({"klaim": teks, "bukti": bukti}),
                "minItems": 1,
                "maxItems": MAKS_RINGKASAN,
            },
            "hipotesis_utama": objek({"teks": teks, "bukti": bukti}),
            "hipotesis_tandingan": {
                "type": "array",
                "items": objek({"teks": teks, "pembantah": teks}),
                "maxItems": MAKS_TANDINGAN,
            },
            "belum_diketahui": {"type": "array", "items": teks, "maxItems": MAKS_BELUM},
        }
    )


class LokalBackend(OnlineBackend):
    role = "lokal"
    log_event = "panggilan_lokal"

    def _body_extra(self, paket: dict[str, Any]) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "narasi", "strict": True, "schema": skema_narasi(paket)},
            }
        }

    async def _check_egress(self, url: str) -> None:
        await egress.check_lokal(url, resolver=self.resolver)


def build_lokal(settings: Settings) -> LokalBackend | None:
    """Backend lokal dari konfigurasi, atau None (dinonaktifkan, alasan dicatat) agar rantai tetap jalan."""
    try:
        cfg = resolve_local(settings)
    except ProviderConfigError as exc:
        log.warning("lokal_nonaktif", alasan=str(exc))
        return None
    if cfg is None:
        log.warning("lokal_nonaktif", alasan="ASTRIA_NARRATIVE_LOCAL_MODEL_ID kosong")
        return None
    return LokalBackend(
        cfg,
        allowlist=frozenset(),
        timeout_s=settings.narrative_local_timeout_s,
        connect_timeout_s=settings.narrative_local_connect_timeout_s,
    )
