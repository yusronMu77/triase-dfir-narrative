"""Rakit aplikasi narrative: komponen standar (PostgreSQL, NATS, relay outbox), konsumen kartu dan permintaan
ulang, dan router.

Dev memakai `uvicorn astria_narrative.main:build_app --factory --reload`; image memakai `astria-narrative`.
"""

from astria_common.app import create_app
from astria_common.consumer import Consumer
from astria_common.service import standard_runtime
from fastapi import FastAPI

from astria_narrative import api, cache
from astria_narrative.pipeline import CardPipeline, parse_chain
from astria_narrative.settings import Settings


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    chain = parse_chain(settings.narrative_chain)
    runtime = standard_runtime(settings, metadata=[cache.metadata])
    if runtime.db is not None and runtime.bus is not None:
        pipeline = CardPipeline(chain)
        for durable, event_type, handler in (
            ("narrative", "card.skeleton.created", pipeline.on_kartu),
            ("narrative-ulang", "narration.retry_requested", pipeline.on_ulang),
        ):
            runtime.add(Consumer(runtime.bus, runtime.db, durable=durable, event_type=event_type, handler=handler))
    return create_app(settings, components=runtime.components, routers=[api.router])
