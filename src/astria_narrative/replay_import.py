"""Impor keluaran terekam ke cache replay.

Pemakaian: `python -m astria_narrative.replay_import <berkas.jsonl>`. Satu baris JSON per keluaran:
`{"card_id", "version", "cache_key", "model_id", "backend", "narasi"}`. Kunci yang sudah ada dilewati.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import orjson
from astria_common import envguard
from astria_common.envguard import EnvironmentGuardError
from astria_common.service import standard_runtime

from astria_narrative import cache
from astria_narrative.settings import Settings


async def run(records: list[dict], settings: Settings) -> int:
    db = standard_runtime(settings, metadata=[cache.metadata]).require_db()
    await db.start()
    try:
        await db.wait_ready(30)
        async with db.engine.begin() as conn:
            return await cache.import_records(conn, records)
    finally:
        await db.stop()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("pemakaian: python -m astria_narrative.replay_import <berkas.jsonl>")
    settings = Settings()
    # Rekaman replay adalah data demo: ditolak di prod sebelum berkas dibaca atau basis data dibuka (infra#9).
    if settings.env == "prod":
        raise EnvironmentGuardError(settings.env, ["impor rekaman replay (data demo) dilarang di produksi"])
    envguard.enforce(settings)
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    imported = asyncio.run(run([orjson.loads(line) for line in lines if line.strip()], settings))
    print(f"diimpor {imported} keluaran")


if __name__ == "__main__":
    main()
