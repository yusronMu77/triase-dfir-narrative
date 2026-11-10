"""Kartu uji dengan beberapa entitas (contoh kontrak hanya punya satu akun)."""

from __future__ import annotations

from typing import Any

from astria_contracts import example
from astria_contracts.events.card_skeleton_created import CardSkeletonCreated
from pydantic import SecretStr

from astria_narrative import pseudonym
from astria_narrative.providers import ProviderConfig

AKUN, HOST_SUMBER, HOST_TERDAMPAK, IP_SUMBER = "svc-backup", "WS-HR-11", "WS-ADM-04", "10.20.8.31"
NILAI_ASLI = (AKUN, HOST_SUMBER, HOST_TERDAMPAK, IP_SUMBER)
KEY = "sk-test-rahasia"
ANTHROPIC = ProviderConfig("online", "anthropic", "https://api.anthropic.com", "claude-test", SecretStr(KEY))


async def publik(host: str, port: int) -> list[str]:
    """Resolver palsu: semua host mengarah ke alamat publik, tanpa DNS sungguhan."""
    return ["1.1.1.1"]


def card_data() -> dict[str, Any]:
    data = example("card.skeleton.created")["data"]
    bukti = ["EV-hb01-004217"]
    data["kode"]["faktor"].append({"nama": "sumber", "nilai": 5, "alasan": f"logon dari {IP_SUMBER} ({HOST_SUMBER})"})
    data["kode"]["entitas"] += [
        {"jenis": "host", "nilai": HOST_SUMBER, "peran": "SUMBER_SERANGAN", "bukti": bukti},
        {"jenis": "host", "nilai": HOST_TERDAMPAK, "peran": "TERDAMPAK", "bukti": bukti},
        {"jenis": "ip", "nilai": IP_SUMBER, "peran": "SUMBER_SERANGAN", "bukti": bukti},
    ]
    return data


def card() -> CardSkeletonCreated:
    return CardSkeletonCreated.model_validate(card_data())


def paket_samar() -> dict[str, Any]:
    kode = card().kode
    return pseudonym.samarkan(kode, pseudonym.build_map(kode))


def narasi_samar(host: str = "HOST_1") -> dict[str, Any]:
    """Keluaran model dalam bentuk placeholder, valid terhadap kontrak `Narasi`."""
    return {
        "ringkasan": [
            {
                "klaim": f"Akun AKUN_1 gagal logon berulang dari {host} (IP_1).",
                "bukti": ["EV-hb01-004217"],
                "nilai_dikutip": {"TargetUserName": "AKUN_1"},
            }
        ],
        "hipotesis_utama": {
            "teks": "AKUN_1 diambil alih lewat tebakan kata sandi di HOST_2.",
            "bukti": ["EV-hb01-004231"],
        },
        "hipotesis_tandingan": [
            {"teks": "Skrip cadangan memakai sandi kedaluwarsa.", "pembantah": "Ada logon sukses."}
        ],
        "belum_diketahui": ["Log HOST_1 tidak tersedia."],
    }
