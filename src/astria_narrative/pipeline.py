"""Satu kartu, satu transaksi: `card.skeleton.created` masuk, `narration.completed` keluar lewat outbox.

Rantai backend dicoba berurutan. `replay` hanya membaca cache `model_call` (tanpa jaringan); `templat` selalu
berhasil sehingga kartu tetap terbit. Kode skor dan band tidak pernah diubah di sini.
"""

from __future__ import annotations

from collections.abc import Sequence

from astria_common.events import new_event
from astria_common.log import get_logger
from astria_common.outbox import enqueue
from astria_contracts import Envelope
from astria_contracts.events.card_skeleton_created import CardSkeletonCreated
from astria_contracts.events.narration_completed import Narasi
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from astria_narrative import cache
from astria_narrative.template import build_narasi

log = get_logger(__name__)

SUPPORTED = ("replay", "templat")
TEMPLAT_MODEL_ID = "templat-v1"


def parse_chain(raw: str) -> tuple[str, ...]:
    chain = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = [b for b in chain if b not in SUPPORTED]
    if unknown:
        raise ValueError(f"backend belum didukung: {unknown} (Tahap 1: {', '.join(SUPPORTED)})")
    if not chain or chain[-1] != "templat":
        raise ValueError("rantai backend wajib diakhiri 'templat'")
    return chain


class CardPipeline:
    """Handler konsumen untuk `card.skeleton.created`."""

    def __init__(self, chain: Sequence[str]) -> None:
        self.chain = tuple(chain)

    async def __call__(self, conn: AsyncConnection, envelope: Envelope, data: BaseModel) -> None:
        assert isinstance(data, CardSkeletonCreated)
        card_id, version = envelope.correlation.card_id, envelope.correlation.version
        if card_id is None or version is None:
            raise ValueError("card.skeleton.created tanpa correlation card_id/version")

        key = cache.cache_key(data.paket_hash.root)
        backend, model_id, narasi, cache_hit = await self._narrate(conn, key, data, card_id, version)
        event = new_event(
            "narration.completed",
            {
                "attempt": 1,
                "model": {
                    "backend": backend,
                    "model_id": model_id,
                    "cache_hit": cache_hit,
                    "prompt_versi": cache.PROMPT_VERSI,
                },
                "narasi": narasi.model_dump(mode="json"),
                "pemeriksa_siap": True,
            },
            correlation={"card_id": card_id, "version": version},
            trace_id=envelope.trace_id,
        )
        await enqueue(conn, event)
        log.info("narasi_terbit", card_id=card_id, version=version, backend=backend, cache_hit=cache_hit)

    async def _narrate(
        self, conn: AsyncConnection, key: str, data: CardSkeletonCreated, card_id: str, version: int
    ) -> tuple[str, str, Narasi, bool]:
        if "replay" in self.chain:
            hit = await cache.lookup(conn, key)
            if hit is not None:
                return "replay", hit[0], hit[1], True
            log.info("replay_tidak_ada", card_id=card_id, cache_key=key)
        # templat: ujung rantai, selalu berhasil; jejaknya dicatat di model_call.
        narasi = build_narasi(data.kode)
        await cache.record(
            conn,
            card_id=card_id,
            version=version,
            key=key,
            backend="templat",
            model_id=TEMPLAT_MODEL_ID,
            outcome="templat",
            output=narasi,
        )
        return "templat", TEMPLAT_MODEL_ID, narasi, False
