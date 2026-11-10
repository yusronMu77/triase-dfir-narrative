"""Pagar egress backend online: hanya https ke host di allowlist yang tidak mengarah ke alamat non-publik.

Alamat privat atau loopback hanya boleh bila diizinkan eksplisit (server model privat di jaringan sendiri); https
tetap wajib, sama dengan `providers.resolve_online`.
IP hasil resolusi belum disematkan ke koneksi (DNS rebinding); lihat sisa di note app-narrative 5.4.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

Resolver = Callable[[str, int], Awaitable[list[str]]]


class EgressDitolak(Exception):
    """Permintaan keluar ditolak kebijakan; backend dilewati."""


def parse_allowlist(raw: str) -> frozenset[str]:
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def check(url: str, allowlist: frozenset[str], *, allow_private: bool, resolver: Resolver = resolve) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise EgressDitolak("skema harus https")
    if host not in allowlist:
        raise EgressDitolak(f"host {host!r} tidak di allowlist")
    if allow_private:
        return
    for ip in await resolver(host, parts.port or 443):
        if not ipaddress.ip_address(ip.split("%")[0]).is_global:
            raise EgressDitolak(f"host {host!r} mengarah ke alamat non-publik")
