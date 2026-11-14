"""Konfigurasi narrative dari env `ASTRIA_*`.

Provider model online (keputusan pemilik 2026-11-08, narrative#2): dua provider didukung dan dipilih lewat
konfigurasi, bukan lewat kode: `anthropic` (API Messages Anthropic) dan `openai_compat` (endpoint
OpenAI-compatible: API online, vLLM, llama-server). Nilai awal dari env; nilai non-rahasia (provider, base URL,
id model) boleh ditimpa dari menu Konfigurasi lewat layanan `config` (lihat `providers.resolve_provider`).
Kunci API hanya dari env atau berkas secret, tidak pernah disimpan di `config`.
"""

from typing import Literal

from astria_common.settings import AstriaSettings
from pydantic import SecretStr

ProviderName = Literal["anthropic", "openai_compat"]


class Settings(AstriaSettings):
    service_name: str = "narrative"

    narrative_online_provider: ProviderName = "anthropic"
    """`anthropic` atau `openai_compat`. Hanya dipakai bila backend `online` ada di rantai."""
    narrative_online_base_url: str | None = None
    """Anthropic: kosong = https://api.anthropic.com. openai_compat: wajib (mis. https://host/v1)."""
    narrative_online_model_id: str | None = None
    narrative_local_base_url: str = "http://llama:8080/v1"
    """Backend lokal selalu `openai_compat` (llama-server atau server privat). Host wajib mengarah ke alamat privat
    atau loopback (`egress.check_lokal`); http boleh."""
    narrative_local_model_id: str | None = None
    """Kosong berarti backend `lokal` nonaktif dan rantai lanjut ke backend berikutnya."""
    narrative_local_api_key: SecretStr | None = None
    """Kunci llama-server (`--api-key`) atau server privat lain; bukan ASTRIA_MODEL_API_KEY."""
    narrative_local_timeout_s: float = 90.0
    """Batas satu panggilan backend lokal. Model CPU lebih lambat dari API daring (note inferensi LFM 2026-11-14)."""
    narrative_local_connect_timeout_s: float = 3.0
    """Batas buka koneksi ke server lokal; VM model yang mati gagal cepat ke `templat`."""

    model_api_key: SecretStr | None = None
    """Kunci API model online (ASTRIA_MODEL_API_KEY). Dilarang di produksi oleh pagar `ASTRIA_ENV`."""

    narrative_chain: str = "replay,templat"
    """Urutan backend, dipisah koma (ASTRIA_NARRATIVE_CHAIN): `replay`, `online`, `lokal`, `templat`; `templat` wajib
    terakhir karena tidak pernah gagal. Demo dengan model online: `replay,online,templat`; model sendiri:
    `replay,lokal,templat` (demo) atau `lokal,templat` (produksi)."""
    narrative_timeout_s: float = 45.0
    """Batas satu panggilan model, termasuk resolusi DNS (note app-narrative 5.2)."""
    narrative_egress_allowlist: str = "api.anthropic.com"
    """Host yang boleh dihubungi backend online, dipisah koma. Host base URL `openai_compat` wajib ditambahkan."""
    narrative_egress_allow_private: bool = False
    """Izinkan host di allowlist yang mengarah ke alamat privat atau loopback (server model privat)."""
