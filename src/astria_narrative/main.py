"""Rakit aplikasi narrative: komponen standar (PostgreSQL, NATS, relay outbox), konsumen kartu dan permintaan
ulang, dan router.

Dev memakai `uvicorn astria_narrative.main:build_app --factory --reload`; image memakai `astria-narrative`.
"""

from astria_common.app import create_app
from astria_common.consumer import Consumer
from astria_common.service import standard_runtime
from fastapi import FastAPI

from astria_narrative import api, cache
from astria_narrative.online import build_online
from astria_narrative.pipeline import CardPipeline, enforce_env, parse_chain
from astria_narrative.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    chain = parse_chain(settings.narrative_chain)
    enforce_env(settings.env, chain)
    runtime = standard_runtime(settings, metadata=[cache.metadata])
    if runtime.db is not None and runtime.bus is not None:
        pipeline = CardPipeline(chain, online=build_online(settings) if "online" in chain else None)
        # Konsumen common mengambil sampai 10 pesan dan memprosesnya berurutan, masing-masing bisa menunggu satu
        # panggilan model; ack_wait bawaan 30 detik membuat pesan terakhir dikirim ulang di tengah proses.
        ack_wait = 10 * settings.narrative_timeout_s + 30
        for durable, event_type, handler in (
            ("narrative", "card.skeleton.created", pipeline.on_kartu),
            ("narrative-ulang", "narration.retry_requested", pipeline.on_ulang),
        ):
            runtime.add(
                Consumer(
                    runtime.bus, runtime.db, durable=durable, event_type=event_type, handler=handler, ack_wait=ack_wait
                )
            )
    return create_app(settings, components=runtime.components, routers=[api.router])
