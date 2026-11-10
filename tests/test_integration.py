"""Uji integrasi pipeline dengan PostgreSQL sungguhan (`ASTRIA_TEST_DATABASE_URL`, tersedia di kontainer py devenv).

Handler dipanggil langsung dalam transaksi; jalur NATS dan relay sudah diuji di common dan smoke devenv.
"""

from __future__ import annotations

import os
import uuid

import orjson
import pytest
from astria_common import outbox
from astria_common.db import Database
from astria_common.events import decode, encode, new_event
from astria_contracts import example
from pydantic import SecretStr
from sqlalchemy import select, text

from astria_narrative import cache
from astria_narrative.pipeline import CardPipeline

DB_URL = os.environ.get("ASTRIA_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not DB_URL, reason="ASTRIA_TEST_DATABASE_URL tidak diisi"),
]


@pytest.fixture
async def db():
    schema = f"t_{uuid.uuid4().hex[:8]}"
    database = Database(SecretStr(DB_URL or ""), schema=schema, metadata=[outbox.metadata, cache.metadata])
    await database.start()
    await database.wait_ready(10)
    yield database
    async with database.engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await database.stop()


def _event(event_type: str, card_id: str = "IC-20261110-003", version: int = 1):
    raw = example(event_type)["data"]
    return decode(encode(new_event(event_type, raw, correlation={"card_id": card_id, "version": version})))


async def _published(db: Database) -> list:
    async with db.engine.connect() as conn:
        rows = (await conn.execute(select(outbox.outbox.c.envelope).order_by(outbox.outbox.c.created_at))).all()
    return [decode(orjson.dumps(r.envelope)) for r in rows]


async def test_template_when_cache_empty(db: Database) -> None:
    envelope, data = _event("card.skeleton.created")
    async with db.engine.begin() as conn:
        await CardPipeline(("replay", "templat")).on_kartu(conn, envelope, data)

    [(out, narration)] = await _published(db)
    assert out.type == "narration.completed"
    assert out.trace_id == envelope.trace_id
    assert out.correlation.card_id == "IC-20261110-003"
    assert narration.model.backend == "templat" and narration.model.cache_hit is False
    async with db.engine.connect() as conn:
        outcomes = (await conn.execute(select(cache.model_call.c.outcome))).scalars().all()
    assert outcomes == ["templat"]


async def test_replay_hit_after_import(db: Database) -> None:
    envelope, data = _event("card.skeleton.created", version=2)
    recorded = example("narration.completed")["data"]["narasi"]
    key = cache.cache_key(data.paket_hash.root)
    record = {
        "card_id": "IC-20261110-003",
        "version": 1,
        "cache_key": key,
        "model_id": "demo-model",
        "narasi": recorded,
    }
    async with db.engine.begin() as conn:
        assert await cache.import_records(conn, [record, record]) == 1
    async with db.engine.begin() as conn:
        await CardPipeline(("replay", "templat")).on_kartu(conn, envelope, data)

    [(_, narration)] = await _published(db)
    assert narration.model.backend == "replay"
    assert narration.model.model_id == "demo-model"
    assert narration.model.cache_hit is True
    assert narration.narasi.model_dump(mode="json") == recorded


async def test_retry_writes_attempt_2_from_stored_card(db: Database) -> None:
    pipeline = CardPipeline(("replay", "templat"))
    async with db.engine.begin() as conn:
        await pipeline.on_kartu(conn, *_event("card.skeleton.created"))
    async with db.engine.begin() as conn:
        await pipeline.on_ulang(conn, *_event("narration.retry_requested"))

    published = await _published(db)
    assert [(e.type, d.attempt) for e, d in published] == [("narration.completed", 1), ("narration.completed", 2)]
    assert published[1][1].model.backend == "templat"
    async with db.engine.connect() as conn:
        rows = (await conn.execute(select(cache.model_call.c.attempt, cache.model_call.c.cache_key))).all()
    assert sorted(r.attempt for r in rows) == [1, 2]
    assert len({r.cache_key for r in rows}) == 2
    async with db.engine.connect() as conn:
        assert (await conn.execute(select(cache.paket_kartu))).first() is None


async def test_retry_without_stored_card_fails(db: Database) -> None:
    async with db.engine.begin() as conn:
        with pytest.raises(ValueError, match="paket kartu"):
            await CardPipeline(("templat",)).on_ulang(conn, *_event("narration.retry_requested", version=9))
