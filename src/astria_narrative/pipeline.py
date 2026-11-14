"""Satu kartu, satu transaksi: `card.skeleton.created` masuk, `narration.completed` keluar lewat outbox.

Rantai backend dicoba berurutan. `replay` hanya membaca cache `model_call` (tanpa jaringan); `online` (model daring)
dan `lokal` (model sendiri di jaringan privat) memanggil model dengan paket yang disamarkan lalu memulihkan placeholder;
`templat` selalu berhasil sehingga kartu tetap terbit. Setiap percobaan model dicatat di `model_call`, dan keluaran
`ok`-nya menjadi sumber `replay` berikutnya.
Kode skor dan band tidak pernah diubah di sini.

Bila verifier meminta ulang (`narration.retry_requested`, hanya kode kegagalan), percobaan 2 memakai paket yang
disimpan di `paket_kartu` saat kartu pertama kali masuk, lalu paket itu dihapus (note app-narrative 3.3 dan 5.2).
"""

from __future__ import annotations

from collections.abc import Sequence

from astria_common.envguard import EnvironmentGuardError
from astria_common.events import new_event
from astria_common.log import get_logger
from astria_common.outbox import enqueue
from astria_contracts import Envelope
from astria_contracts.events.card_skeleton_created import CardSkeletonCreated
from astria_contracts.events.narration_completed import Narasi
from astria_contracts.events.narration_retry_requested import NarrationRetryRequested
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from astria_narrative import cache, pseudonym
from astria_narrative.cache import paket_kartu
from astria_narrative.online import OnlineBackend
from astria_narrative.template import build_narasi

log = get_logger(__name__)

SUPPORTED = ("replay", "online", "lokal", "templat")
TEMPLAT_MODEL_ID = "templat-v1"


def parse_chain(raw: str) -> tuple[str, ...]:
    chain = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = [b for b in chain if b not in SUPPORTED]
    if unknown:
        raise ValueError(f"backend belum didukung: {unknown} (didukung: {', '.join(SUPPORTED)})")
    if not chain or chain[-1] != "templat":
        raise ValueError("rantai backend wajib diakhiri 'templat'")
    if len(set(chain)) != len(chain):
        raise ValueError("backend tidak boleh diulang di rantai")
    return chain


PROD_FORBIDDEN = ("replay", "online")
"""`replay` memutar rekaman demo, `online` memanggil model daring: keduanya dilarang di `ASTRIA_ENV=prod`.
`lokal` boleh: pagar egress-nya hanya mengizinkan alamat privat atau loopback (`egress.check_lokal`)."""


def enforce_env(env: str, chain: Sequence[str]) -> None:
    """Pagar `ASTRIA_ENV` khusus narrative (infra#9); dipanggil sebelum runtime dirakit atau cache disentuh.

    Pagar bersama `astria_common.envguard` hanya membaca field tunggal `model_backend`, sedangkan narrative memakai
    rantai `ASTRIA_NARRATIVE_CHAIN` (bawaan `replay,templat`), jadi aturannya diperiksa di sini.
    """
    if env != "prod":
        return
    forbidden = [b for b in chain if b in PROD_FORBIDDEN]
    if forbidden:
        raise EnvironmentGuardError(
            env,
            [
                f"backend narasi {', '.join(forbidden)} dilarang di produksi "
                "(replay = rekaman demo, online = model daring); "
                "pakai ASTRIA_NARRATIVE_CHAIN=templat atau lokal,templat"
            ],
        )


def _kartu(envelope: Envelope) -> tuple[str, int]:
    card_id, version = envelope.correlation.card_id, envelope.correlation.version
    if card_id is None or version is None:
        raise ValueError(f"{envelope.type} tanpa correlation card_id/version")
    return card_id, version


class CardPipeline:
    """Handler dua konsumen: `card.skeleton.created` (percobaan 1) dan `narration.retry_requested` (percobaan 2)."""

    def __init__(
        self, chain: Sequence[str], online: OnlineBackend | None = None, lokal: OnlineBackend | None = None
    ) -> None:
        self.chain = tuple(chain)
        self.model = {"online": online, "lokal": lokal}
        """Backend model per nama rantai; None = nonaktif (tidak dikonfigurasi) dan dilewati."""

    async def on_kartu(self, conn: AsyncConnection, envelope: Envelope, data: BaseModel) -> None:
        assert isinstance(data, CardSkeletonCreated)
        card_id, version = _kartu(envelope)
        await conn.execute(
            insert(paket_kartu)
            .values(card_id=card_id, version=version, paket=data.model_dump(mode="json"))
            .on_conflict_do_nothing()
        )
        await self._terbitkan(conn, envelope, data, card_id, version, attempt=1)

    async def on_ulang(self, conn: AsyncConnection, envelope: Envelope, data: BaseModel) -> None:
        assert isinstance(data, NarrationRetryRequested)
        card_id, version = _kartu(envelope)
        kunci = {"card_id": card_id, "version": version}
        paket = (await conn.execute(select(paket_kartu.c.paket).filter_by(**kunci))).scalar()
        if paket is None:
            raise ValueError(f"paket kartu {card_id}/v{version} tidak ada untuk percobaan {data.attempt}")
        await self._terbitkan(
            conn,
            envelope,
            CardSkeletonCreated.model_validate(paket),
            card_id,
            version,
            attempt=data.attempt,
            kegagalan=[(k.klaim_no, k.kode) for k in data.kegagalan],
        )
        # Percobaan 2 adalah yang terakhir.
        await conn.execute(delete(paket_kartu).filter_by(**kunci))

    async def _terbitkan(
        self,
        conn: AsyncConnection,
        envelope: Envelope,
        data: CardSkeletonCreated,
        card_id: str,
        version: int,
        *,
        attempt: int,
        kegagalan: Sequence[tuple[int, str]] = (),
    ) -> None:
        key = cache.cache_key(data.paket_hash.root, kegagalan=kegagalan)
        backend, model_id, narasi, cache_hit = await self._narrate(
            conn, key, data, card_id, version, attempt, kegagalan
        )
        event = new_event(
            "narration.completed",
            {
                "attempt": attempt,
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
        log.info(
            "narasi_terbit", card_id=card_id, version=version, attempt=attempt, backend=backend, cache_hit=cache_hit
        )

    async def _narrate(
        self,
        conn: AsyncConnection,
        key: str,
        data: CardSkeletonCreated,
        card_id: str,
        version: int,
        attempt: int,
        kegagalan: Sequence[tuple[int, str]],
    ) -> tuple[str, str, Narasi, bool]:
        peta = pseudonym.build_map(data.kode)
        if "replay" in self.chain:
            hit = await cache.lookup(conn, key)
            if hit is not None:
                try:
                    return "replay", hit[0], pseudonym.restore(hit[1], peta), True
                except pseudonym.PlaceholderAsing:
                    log.warning("replay_placeholder_asing", card_id=card_id, attempt=attempt, cache_key=key)
            else:
                log.info("replay_tidak_ada", card_id=card_id, attempt=attempt, cache_key=key)
        for nama in self.chain:
            backend = self.model.get(nama)
            if backend is None:
                continue
            hasil = await backend.narrate(pseudonym.samarkan(data.kode, peta), kegagalan)
            outcome, narasi = hasil.outcome, None
            if hasil.narasi is not None:
                try:
                    narasi = pseudonym.restore(hasil.narasi, peta)
                except pseudonym.PlaceholderAsing:
                    outcome = "placeholder_asing"
            await cache.record(
                conn,
                card_id=card_id,
                version=version,
                attempt=attempt,
                key=key,
                backend=nama,
                model_id=backend.model_id,
                outcome=outcome,
                output=hasil.narasi if narasi is not None else None,  # bentuk placeholder, bukan nilai asli
                latency_ms=hasil.latency_ms,
            )
            if narasi is not None:
                return nama, backend.model_id, narasi, False
        # templat: ujung rantai, selalu berhasil; jejaknya dicatat di model_call.
        narasi = build_narasi(data.kode)
        await cache.record(
            conn,
            card_id=card_id,
            version=version,
            attempt=attempt,
            key=key,
            backend="templat",
            model_id=TEMPLAT_MODEL_ID,
            outcome="templat",
            output=narasi,
        )
        return "templat", TEMPLAT_MODEL_ID, narasi, False
