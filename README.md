<!-- astria-logo -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/astria-logo-reverse.svg">
    <img src=".github/assets/astria-logo.svg" alt="Astria" width="320">
  </picture>
</p>

# Astria narrative

Narasi model bahasa; setiap klaim menunjuk ID bukti.

> Status: Tahap 1 (narrative#3). Konsumen `card.skeleton.created` menerbitkan `narration.completed` lewat outbox dengan rantai backend `replay` lalu `templat`; backend `online` dan `lokal` menyusul (narrative#4). Repo ini adalah submodule dari workspace `triase-dfir` (folder `narrative/`). Rancangan: `notes/2026-11-06-triase-dfir-app-narrative.md` di repo root. Lajur developer: 2.

## Tech stack

Python 3.14, FastAPI, klien model (tanpa LiteLLM), NATS JetStream, uv

## Perintah

```text
uv sync                                   # butuh akses ke repo privat contracts dan common (tag git)
uv run ruff format --check . && uv run ruff check .
uv run pytest
sh ../common/template/localtest.sh        # di kontainer py devenv: uji terhadap salinan kerja common dan contracts
```

Menjalankan bersama layanan lain: `pwsh ../devenv/scripts/dev.ps1 up`, lalu `dev.ps1 smoke`.

Uji integrasi (`tests/test_integration.py`) butuh `ASTRIA_TEST_DATABASE_URL`; di kontainer `py` devenv isi dengan
`postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@postgres:5432/postgres`. Tanpa variabel itu uji tersebut dilewati.

## Cara kerja

| Bagian | Isi |
|---|---|
| `pipeline.py` | Satu kartu, satu transaksi: cari cache `replay`, bila tidak ada pakai `templat`, lalu `narration.completed` ke outbox (trace dan `card_id` ikut) |
| `template.py` | Narasi deterministik dari `kode` kartu: band, skor, pola, peran tiap entitas, dan judul sebagai hipotesis utama; setiap klaim menunjuk ID bukti kartu |
| `cache.py` | Tabel `model_call`: kunci `sha256(prompt_versi, paket_hash, params)`, satu baris `ok` per kunci (sumber `replay`), jejak `templat` |
| `replay_import.py` | `python -m astria_narrative.replay_import <berkas.jsonl>`: impor keluaran terekam (`card_id`, `version`, `cache_key`, `model_id`, `backend`, `narasi`) |

Konfigurasi: `ASTRIA_NARRATIVE_CHAIN` (bawaan `replay,templat`; wajib diakhiri `templat`). Kode skor dan band tidak pernah diubah.
`narration.retry_requested` belum ada di kontrak, jadi `attempt` selalu 1.

## Alur git

Branch `{type}/{yyyyMMdd}-{taskId}-{nama}`; commit `{type}({yyyyMMddHHmm}): [{taskId}] {pesan}`, satu baris, tanpa trailer. `main` hanya berubah lewat pull request (merge rebase); jangan push langsung ke `main` dan jangan `--no-verify`.
