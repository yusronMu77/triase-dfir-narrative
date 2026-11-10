"""Samaran nilai identitas sebelum paket keluar ke backend online, dan pemulihannya (note app-narrative 5.4).

Peta tidak disimpan: dihitung ulang dari `kode` kartu yang sama (urutan entitas di paket), sehingga placeholder untuk
kartu yang sama selalu sama dan keluaran cache dalam bentuk placeholder bisa dipulihkan kapan pun. Yang disamarkan:
nilai entitas kartu, lalu IP dan token berbentuk identifier (mis. `WS-ADM-04`) di judul dan alasan faktor yang bukan
entitas (keputusan PM 2026-11-10: nama host di judul tidak boleh keluar). Aturan identifier sama dengan pengenal
entitas verifier; kode Astria (`EV-`, `P-`, `K-`, `S-`, `IC-`, `T1234`) dan kata umum tidak disamarkan.
"""

from __future__ import annotations

import ipaddress
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from astria_contracts.events.card_skeleton_created import Kode
from astria_contracts.events.narration_completed import Narasi

JENIS = {"akun": "AKUN", "host": "HOST", "ip": "IP", "proses": "PROSES", "berkas": "PATH"}
PLACEHOLDER = re.compile(r"\b(?:AKUN|HOST|IP|PROSES|PATH|ENTITAS)_\d+\b")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\\-]*[A-Za-z0-9]")
KODE_ASTRIA = re.compile(r"^(?:EV|P|K|S|IC)-|^T\d{4}")
KATA_UMUM = frozenset({"e-mail", "log-in", "log-on", "non-aktif", "real-time", "follow-up"})


class PlaceholderAsing(ValueError):
    """Keluaran memuat placeholder yang tidak ada di peta kartu ini."""


def _identifier(token: str) -> bool:
    if KODE_ASTRIA.match(token) or token.casefold() in KATA_UMUM or not any(c.isalpha() for c in token):
        return False
    bagian = token.casefold().split("-")
    if len(bagian) > 1 and len(set(bagian)) == 1:
        return False  # kata ulang: masing-masing
    return any(c in "._\\-" for c in token) or any(c.isdigit() for c in token)


def _teks_bebas(teks: str) -> list[tuple[str, str]]:
    """(nilai, jenis) untuk IP valid dan identifier di teks bebas, urut kemunculan."""
    hasil = []
    for m in IPV4.finditer(teks):
        try:
            ipaddress.ip_address(m.group(0))
        except ValueError:
            continue
        hasil.append((m.start(), m.group(0), "IP"))
    sisa = IPV4.sub(lambda m: " " * len(m.group(0)), teks)
    hasil += [(m.start(), m.group(0), "ENTITAS") for m in IDENT.finditer(sisa) if _identifier(m.group(0))]
    return [(nilai, jenis) for _, nilai, jenis in sorted(hasil)]


def build_map(kode: Kode) -> dict[str, str]:
    """Peta nilai asli ke placeholder, bernomor menurut kemunculan pertama per jenis: entitas dulu, lalu teks bebas."""
    calon = [(e.nilai, JENIS.get(e.jenis, "ENTITAS")) for e in kode.entitas]
    for teks in (kode.judul, *(f.alasan for f in kode.faktor)):
        calon += _teks_bebas(teks)
    peta: dict[str, str] = {}
    sudah = set()
    nomor: Counter[str] = Counter()
    for nilai, jenis in calon:
        if nilai.casefold() in sudah:
            continue
        sudah.add(nilai.casefold())
        nomor[jenis] += 1
        peta[nilai] = f"{jenis}_{nomor[jenis]}"
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
