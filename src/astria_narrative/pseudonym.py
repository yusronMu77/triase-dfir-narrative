"""Samaran nilai identitas sebelum paket keluar ke backend online, dan pemulihannya (note app-narrative 5.4).

Peta tidak disimpan: dihitung ulang dari `kode` kartu yang sama (urutan entitas di paket), sehingga placeholder untuk
kartu yang sama selalu sama dan keluaran cache dalam bentuk placeholder bisa dipulihkan kapan pun. Yang disamarkan:
nilai entitas kartu, di mana pun nilai itu muncul sebagai kata utuh (judul, alasan faktor, nilai entitas). Nilai di
luar daftar entitas tidak dikenali dan tetap terkirim; verifier menandainya bila muncul di klaim.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from astria_contracts.events.card_skeleton_created import Kode
from astria_contracts.events.narration_completed import Narasi

JENIS = {"akun": "AKUN", "host": "HOST", "ip": "IP", "proses": "PROSES", "berkas": "PATH"}
PLACEHOLDER = re.compile(r"\b(?:AKUN|HOST|IP|PROSES|PATH|ENTITAS)_\d+\b")


class PlaceholderAsing(ValueError):
    """Keluaran memuat placeholder yang tidak ada di peta kartu ini."""


def build_map(kode: Kode) -> dict[str, str]:
    """Peta nilai asli ke placeholder, bernomor menurut kemunculan pertama per jenis."""
    peta: dict[str, str] = {}
    nomor: Counter[str] = Counter()
    for e in kode.entitas:
        if e.nilai in peta:
            continue
        jenis = JENIS.get(e.jenis, "ENTITAS")
        nomor[jenis] += 1
        peta[e.nilai] = f"{jenis}_{nomor[jenis]}"
    return peta


def _walk(obj: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk(v, fn) for v in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    return obj


def samarkan(kode: Kode, peta: dict[str, str]) -> dict[str, Any]:
    """`kode` sebagai dict JSON dengan nilai entitas diganti placeholder."""
    paket = kode.model_dump(mode="json", exclude_none=True)
    if not peta:
        return paket
    # Nilai terpanjang dulu, dan hanya sebagai kata utuh: `10.0.0.1` tidak memotong `10.0.0.15`, dan nilai pendek
    # tidak merusak ID bukti seperti `EV-hb01-004217`. Tanpa beda huruf besar-kecil (`WS-ADM-04` = `ws-adm-04`).
    per_huruf = {k.casefold(): v for k, v in peta.items()}
    nilai = sorted(peta, key=len, reverse=True)
    pola = re.compile("|".join(rf"(?<![\w-]){re.escape(v)}(?![\w-])" for v in nilai), re.IGNORECASE)
    return _walk(paket, lambda s: pola.sub(lambda m: per_huruf[m.group(0).casefold()], s))


def restore(narasi: Narasi, peta: dict[str, str]) -> Narasi:
    """Ganti placeholder dengan nilai asli; placeholder yang tidak dikenal menjadi `PlaceholderAsing`."""
    asli = {v: k for k, v in peta.items()}

    def ganti(m: re.Match[str]) -> str:
        if m.group(0) not in asli:
            raise PlaceholderAsing(m.group(0))
        return asli[m.group(0)]

    return Narasi.model_validate(_walk(narasi.model_dump(mode="json"), lambda s: PLACEHOLDER.sub(ganti, s)))
