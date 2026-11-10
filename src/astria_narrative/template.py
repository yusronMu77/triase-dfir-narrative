"""Backend `templat`: narasi deterministik dari bagian kode kartu, tanpa model bahasa.

Ujung rantai backend: selalu berhasil dan selalu lolos skema karena dibangun langsung sebagai model kontrak.
Setiap klaim hanya memuat nilai yang ada di `kode` (judul, pola, skor, band, entitas) dan menunjuk ID bukti
kartu itu sendiri, sehingga verifier bisa menelusurinya.
"""

from __future__ import annotations

from astria_contracts.events.card_skeleton_created import Kode
from astria_contracts.events.narration_completed import Narasi

MAX_KLAIM = 6
MAX_BUKTI = 8
JENIS = {"akun": "Akun", "host": "Host", "ip": "Alamat IP", "proses": "Proses", "berkas": "Berkas"}
CATATAN_TEMPLAT = "Narasi disusun dari templat tanpa model bahasa; hipotesis tandingan belum dinilai."


def _peran(peran: str) -> str:
    return peran.replace("_", " ").lower()


def build_narasi(kode: Kode) -> Narasi:
    semua_bukti = [b.id.root for b in kode.bukti][:MAX_BUKTI]
    ringkasan = [
        {
            "klaim": f"Triage menilai insiden ini {kode.band} dengan skor {kode.skor} untuk pola {kode.pola}.",
            "bukti": semua_bukti,
        }
    ]
    for e in kode.entitas[: MAX_KLAIM - 1]:
        jenis = JENIS.get(e.jenis, e.jenis.capitalize())
        ringkasan.append(
            {
                "klaim": f"{jenis} {e.nilai} tercatat dengan peran {_peran(e.peran)}.",
                "bukti": [b.root for b in e.bukti][:MAX_BUKTI],
            }
        )
    return Narasi.model_validate(
        {
            "ringkasan": ringkasan,
            "hipotesis_utama": {"teks": kode.judul.rstrip(".") + ".", "bukti": semua_bukti},
            "hipotesis_tandingan": [],
            "belum_diketahui": [CATATAN_TEMPLAT],
        }
    )
