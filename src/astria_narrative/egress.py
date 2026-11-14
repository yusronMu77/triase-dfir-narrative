"""Pagar egress backend online: hanya https ke host di allowlist yang tidak mengarah ke alamat non-publik.

Alamat privat atau loopback hanya boleh bila diizinkan eksplisit (server model privat di jaringan sendiri); https
tetap wajib, sama dengan `providers.resolve_online`.
Backend `lokal` memakai `check_lokal`: kebalikannya, hanya alamat privat atau loopback.
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


def _jaringan_sendiri(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Alamat privat (RFC 1918, ULA) atau loopback; link-local (termasuk metadata 169.254.169.254) tidak."""
    if addr.is_link_local or addr.is_multicast or addr.is_unspecified or addr.is_reserved:
        return False
    return addr.is_loopback or (addr.is_private and not addr.is_global)


async def check_lokal(url: str, *, resolver: Resolver = resolve) -> None:
    """Pagar backend `lokal`: server model harus di jaringan sendiri, bukan provider daring yang diberi nama lokal.

    http boleh (llama-server di jaringan privat), tetapi setiap alamat hasil resolusi wajib privat atau loopback.
    Host yang mengarah ke alamat publik ditolak, sehingga mengganti nama provider daring menjadi `lokal` tidak
    melewati larangan `online` di produksi.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host:
        raise EgressDitolak("skema harus http atau https")
    alamat = await resolver(host, parts.port or (443 if parts.scheme == "https" else 80))
    if not alamat:
        raise EgressDitolak(f"host {host!r} tidak punya alamat")
    for ip in alamat:
        if not _jaringan_sendiri(ipaddress.ip_address(ip.split("%")[0])):
            raise EgressDitolak(f"host {host!r} bukan alamat jaringan sendiri (privat atau loopback)")
