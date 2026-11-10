"""Tabel `model_call`: cache keluaran tervalidasi (sumber backend `replay`) dan jejak tiap percobaan backend.
Tabel `paket_kartu`: paket kartu untuk percobaan 2, karena narrative tidak bisa membacanya ulang dari triage.

Kunci cache dihitung dari versi prompt, `paket_hash` kartu, dan parameter model, bukan dari id model, supaya
keluaran terekam bisa diputar ulang di mesin tanpa model. Percobaan 2 menambahkan kode kegagalan dari verifier ke
kunci, sama seperti kegagalan itu masuk ke prompt (note app-narrative 3.3), sehingga tidak memutar ulang keluaran
percobaan 1 yang ditolak. Hanya baris `outcome = 'ok'` yang dipakai `replay`;
indeks unik parsial menjamin satu keluaran per kunci.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import orjson
from astria_contracts.events.narration_completed import Narasi
from sqlalchemy import Column, DateTime, Index, Integer, MetaData, SmallInteger, Table, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncConnection

PROMPT_VERSI = "narasi-v1"
PARAMS: dict[str, Any] = {"max_tokens": 800, "temperature": 0, "top_p": 1}

metadata = MetaData()

model_call = Table(
    "model_call",
    metadata,
    Column("id", Text, primary_key=True),
    Column("card_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("attempt", SmallInteger, nullable=False, server_default="1"),
    Column("cache_key", Text, nullable=False),
    Column("backend", Text, nullable=False),
    Column("model_id", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("output", JSONB, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("model_call_cache_ok", model_call.c.cache_key, unique=True, postgresql_where=model_call.c.outcome == "ok")
Index("model_call_card", model_call.c.card_id, model_call.c.version)

paket_kartu = Table(
    "paket_kartu",
    metadata,
    Column("card_id", Text, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("paket", JSONB, nullable=False),
    Column("diterima_pada", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def cache_key(
    paket_hash: str,
    *,
    kegagalan: Iterable[tuple[int, str]] = (),
    prompt_versi: str = PROMPT_VERSI,
    params: Mapping[str, Any] = PARAMS,
) -> str:
    isi: dict[str, Any] = {"paket_hash": paket_hash, "params": dict(params), "prompt_versi": prompt_versi}
    if gagal := sorted(kegagalan):
        isi["kegagalan"] = gagal
    return hashlib.sha256(orjson.dumps(isi, option=orjson.OPT_SORT_KEYS)).hexdigest()


async def lookup(conn: AsyncConnection, key: str) -> tuple[str, Narasi] | None:
    """Keluaran `ok` untuk kunci ini sebagai (model_id, narasi), atau None."""
    row = (
        await conn.execute(
            select(model_call.c.model_id, model_call.c.output).where(
                model_call.c.cache_key == key, model_call.c.outcome == "ok"
            )
        )
    ).first()
    if row is None:
        return None
    return row.model_id, Narasi.model_validate(row.output)


async def record(
    conn: AsyncConnection,
    *,
    card_id: str,
    version: int,
    attempt: int,
    key: str,
    backend: str,
    model_id: str,
    outcome: str,
    output: Narasi | None,
) -> None:
    await conn.execute(
        model_call.insert().values(
            id=str(uuid.uuid4()),
            card_id=card_id,
            version=version,
            attempt=attempt,
            cache_key=key,
            backend=backend,
            model_id=model_id,
            outcome=outcome,
            output=output.model_dump(mode="json") if output is not None else None,
        )
    )


async def import_records(conn: AsyncConnection, records: Iterable[Mapping[str, Any]]) -> int:
    """Impor keluaran terekam (mis. dari samples) sebagai baris `ok`. Kunci yang sudah ada dilewati."""
    imported = 0
    for rec in records:
        narasi = Narasi.model_validate(rec["narasi"])
        result = await conn.execute(
            insert(model_call)
            .values(
                id=str(uuid.uuid4()),
                card_id=rec["card_id"],
                version=int(rec["version"]),
                cache_key=rec["cache_key"],
                backend=rec.get("backend", "online"),
                model_id=rec["model_id"],
                outcome="ok",
                output=narasi.model_dump(mode="json"),
            )
            .on_conflict_do_nothing(index_elements=["cache_key"], index_where=model_call.c.outcome == "ok")
            .returning(model_call.c.id)
        )
        imported += result.first() is not None
    return imported
