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


def _skeleton(card_id: str = "IC-20261110-003", version: int = 1):
    raw = example("card.skeleton.created")
    return decode(encode(new_event(raw["type"], raw["data"], correlation={"card_id": card_id, "version": version})))


async def _published(db: Database) -> list:
    async with db.engine.connect() as conn:
        rows = (await conn.execute(select(outbox.outbox.c.envelope).order_by(outbox.outbox.c.created_at))).all()
    return [decode(orjson.dumps(r.envelope)) for r in rows]


async def test_template_when_cache_empty(db: Database) -> None:
    envelope, data = _skeleton()
    async with db.engine.begin() as conn:
        await CardPipeline(("replay", "templat"))(conn, envelope, data)

    [(out, narration)] = await _published(db)
    assert out.type == "narration.completed"
    assert out.trace_id == envelope.trace_id
    assert out.correlation.card_id == "IC-20261110-003"
    assert narration.model.backend == "templat" and narration.model.cache_hit is False
    async with db.engine.connect() as conn:
        outcomes = (await conn.execute(select(cache.model_call.c.outcome))).scalars().all()
    assert outcomes == ["templat"]


async def test_replay_hit_after_import(db: Database) -> None:
    envelope, data = _skeleton(version=2)
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
        await CardPipeline(("replay", "templat"))(conn, envelope, data)

    [(_, narration)] = await _published(db)
    assert narration.model.backend == "replay"
    assert narration.model.model_id == "demo-model"
    assert narration.model.cache_hit is True
    assert narration.narasi.model_dump(mode="json") == recorded
