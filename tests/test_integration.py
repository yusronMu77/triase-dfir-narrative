"""Uji integrasi pipeline dengan PostgreSQL sungguhan (`ASTRIA_TEST_DATABASE_URL`, tersedia di kontainer py devenv).

Handler dipanggil langsung dalam transaksi; jalur NATS dan relay sudah diuji di common dan smoke devenv.
"""

from __future__ import annotations

import os
import uuid

import httpx
import orjson
import pytest
from astria_common import outbox
from astria_common.db import Database
from astria_common.events import decode, encode, new_event
from astria_contracts import example
from astria_contracts.events.narration_completed import Narasi
from fixtures import AKUN, ANTHROPIC, HOST_SUMBER, IP_SUMBER, NILAI_ASLI, card_data, narasi_samar, publik
from pydantic import SecretStr
from sqlalchemy import select, text

from astria_narrative import cache
from astria_narrative.lokal import LokalBackend
from astria_narrative.online import OnlineBackend
from astria_narrative.pipeline import CardPipeline
from astria_narrative.providers import ProviderConfig

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


# --- backend online (httpx.MockTransport, tanpa jaringan) ---

CARD = "IC-20261110-003"


def _online(handler) -> OnlineBackend:
    return OnlineBackend(
        ANTHROPIC, allowlist=frozenset({"api.anthropic.com"}), transport=httpx.MockTransport(handler), resolver=publik
    )


def _card_event(version: int = 1):
    return decode(
        encode(new_event("card.skeleton.created", card_data(), correlation={"card_id": CARD, "version": version}))
    )


def _jawab(narasi: dict, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content.decode())
        return httpx.Response(200, json={"content": [{"type": "text", "text": orjson.dumps(narasi).decode()}]})

    return handler


async def _model_calls(db: Database) -> list:
    async with db.engine.connect() as conn:
        q = select(cache.model_call.c.backend, cache.model_call.c.outcome, cache.model_call.c.output)
        return (await conn.execute(q.order_by(cache.model_call.c.created_at))).all()


async def test_online_ok_then_replay_serves_cache(db: Database) -> None:
    calls: list[str] = []
    pipeline = CardPipeline(("replay", "online", "templat"), online=_online(_jawab(narasi_samar(), calls)))
    async with db.engine.begin() as conn:
        await pipeline.on_kartu(conn, *_card_event(version=1))
    async with db.engine.begin() as conn:
        await pipeline.on_kartu(conn, *_card_event(version=2))  # paket sama, kunci cache sama

    assert len(calls) == 1
    assert not any(nilai in calls[0] for nilai in NILAI_ASLI)
    [(_, pertama), (_, kedua)] = await _published(db)
    assert (pertama.model.backend, pertama.model.model_id, pertama.model.cache_hit) == ("online", "claude-test", False)
    assert (kedua.model.backend, kedua.model.model_id, kedua.model.cache_hit) == ("replay", "claude-test", True)
    assert pertama.narasi == kedua.narasi
    assert pertama.narasi.ringkasan[0].klaim == f"Akun {AKUN} gagal logon berulang dari {HOST_SUMBER} ({IP_SUMBER})."
    [(backend, outcome, output)] = await _model_calls(db)
    assert (backend, outcome) == ("online", "ok")
    assert output == Narasi.model_validate(narasi_samar()).model_dump(mode="json")  # disimpan dalam bentuk samaran


@pytest.mark.parametrize(
    ("handler", "outcome"),
    [
        (lambda r: httpx.Response(503), "backend_gagal"),
        (_jawab({"ringkasan": "rusak"}, []), "skema_gagal"),
        (_jawab(narasi_samar(host="HOST_7"), []), "placeholder_asing"),
    ],
)
async def test_online_failure_falls_back_to_template(db: Database, handler, outcome: str) -> None:
    async with db.engine.begin() as conn:
        await CardPipeline(("replay", "online", "templat"), online=_online(handler)).on_kartu(conn, *_card_event())

    [(_, narration)] = await _published(db)
    assert narration.model.backend == "templat"
    assert [(b, o, out is None) for b, o, out in await _model_calls(db)] == [
        ("online", outcome, True),
        ("templat", "templat", False),
    ]


async def test_online_without_replay_keeps_one_ok_row_per_key(db: Database) -> None:
    calls: list[str] = []
    pipeline = CardPipeline(("online", "templat"), online=_online(_jawab(narasi_samar(), calls)))
    for version in (1, 2):
        async with db.engine.begin() as conn:
            await pipeline.on_kartu(conn, *_card_event(version=version))

    assert len(calls) == 2
    assert [(b, o) for b, o, _ in await _model_calls(db)] == [("online", "ok")]


# --- backend lokal (llama-server di jaringan privat; httpx.MockTransport) ---

LOKAL = ProviderConfig("local", "openai_compat", "http://10.184.0.4:8080/v1", "lfm-test", SecretStr("kunci-lokal"))


async def _privat(host: str, port: int) -> list[str]:
    return ["10.184.0.4"]


def _lokal(handler) -> LokalBackend:
    return LokalBackend(
        LOKAL, allowlist=frozenset(), timeout_s=5, transport=httpx.MockTransport(handler), resolver=_privat
    )


def _jawab_openai(narasi: dict, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": orjson.dumps(narasi).decode()}}]})

    return handler


async def test_lokal_ok_recorded_then_replay_serves_cache(db: Database) -> None:
    calls: list[str] = []
    pipeline = CardPipeline(("replay", "lokal", "templat"), lokal=_lokal(_jawab_openai(narasi_samar(), calls)))
    for version in (1, 2):
        async with db.engine.begin() as conn:
            await pipeline.on_kartu(conn, *_card_event(version=version))

    assert len(calls) == 1
    assert '"json_schema"' in calls[0]
    assert not any(nilai in calls[0] for nilai in NILAI_ASLI)
    [(_, pertama), (_, kedua)] = await _published(db)
    assert (pertama.model.backend, pertama.model.model_id, pertama.model.cache_hit) == ("lokal", "lfm-test", False)
    assert (kedua.model.backend, kedua.model.cache_hit) == ("replay", True)
    assert [(b, o) for b, o, _ in await _model_calls(db)] == [("lokal", "ok")]


def _putus(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("VM inferensi mati", request=request)


def _lambat(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("tidak menjawab", request=request)


@pytest.mark.parametrize(
    ("handler", "outcome"),
    [
        (_putus, "backend_gagal"),
        (_lambat, "batas_waktu"),
        (_jawab_openai({"ringkasan": "rusak"}, []), "skema_gagal"),
        (_jawab_openai(narasi_samar(host="HOST_7"), []), "placeholder_asing"),
    ],
)
async def test_lokal_failure_falls_back_to_template(db: Database, handler, outcome: str) -> None:
    async with db.engine.begin() as conn:
        await CardPipeline(("lokal", "templat"), lokal=_lokal(handler)).on_kartu(conn, *_card_event())

    [(_, narration)] = await _published(db)
    assert narration.model.backend == "templat"
    assert [(b, o, out is None) for b, o, out in await _model_calls(db)] == [
        ("lokal", outcome, True),
        ("templat", "templat", False),
    ]
