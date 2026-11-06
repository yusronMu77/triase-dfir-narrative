# Astria narrative

Narasi model bahasa; setiap klaim menunjuk ID bukti.

> Status: kerangka awal, belum ada kode. Repo ini adalah submodule dari workspace `triase-dfir` (folder `narrative/`). Rancangan: `notes/2026-11-06-triase-dfir-app-narrative.md` di repo root. Lajur developer: 2.

## Tech stack

Python 3.14, FastAPI, klien model (tanpa LiteLLM), NATS JetStream, uv

## Perintah

```text
uv sync
uv run pytest
```

## Alur git

Branch `{type}/{yyyyMMdd}-{taskId}-{nama}`; commit `{type}({yyyyMMddHHmm}): [{taskId}] {pesan}`, satu baris, tanpa trailer. `main` hanya berubah lewat pull request (merge rebase); jangan push langsung ke `main` dan jangan `--no-verify`.
