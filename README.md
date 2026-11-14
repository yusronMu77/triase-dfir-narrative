<!-- astria-logo -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/astria-logo-reverse.svg">
    <img src=".github/assets/astria-logo.svg" alt="Astria" width="320">
  </picture>
</p>

# Astria narrative

Narasi model bahasa; setiap klaim menunjuk ID bukti.

> Status: Tahap 1 (narrative#3, narrative#4). Konsumen `card.skeleton.created` (percobaan 1) dan `narration.retry_requested` (percobaan 2) menerbitkan `narration.completed` lewat outbox dengan rantai backend `replay`, `online` (model online untuk demo, paket disamarkan), lalu `templat`; backend `lokal` menyusul. Repo ini adalah submodule dari workspace `triase-dfir` (folder `narrative/`). Rancangan: `notes/2026-11-06-triase-dfir-app-narrative.md` di repo root. Lajur developer: 2.

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
| `pipeline.py` | Satu kartu, satu transaksi: cari cache `replay`, lalu `online`, lalu `templat`, dan `narration.completed` ke outbox (trace dan `card_id` ikut). Setiap percobaan `online` dicatat di `model_call` (`ok`, `skema_gagal`, `placeholder_asing`, `batas_waktu`, `backend_gagal`, `egress_ditolak`); keluaran `ok` disimpan dalam bentuk samaran dan diputar ulang oleh `replay`. Paket disimpan di `paket_kartu` agar permintaan ulang verifier bisa ditulis sebagai percobaan 2, lalu dihapus setelah percobaan 2 terbit |
| `pseudonym.py` | Samaran: nilai entitas kartu menjadi `AKUN_1`, `HOST_1`, `IP_1`, dan seterusnya di seluruh paket sebelum keluar, ditambah IP dan identifier lain di judul dan alasan faktor (mis. host yang bukan entitas menjadi `ENTITAS_n`; kode Astria dan kata umum tidak); peta dihitung ulang dari kartu, tidak disimpan. Keluaran dipulihkan ke nilai asli; placeholder yang tidak dikenal berarti `placeholder_asing` dan backend berikutnya dicoba |
| `prompt.py` | Petunjuk Bahasa Indonesia dan paket kartu di dalam pagar `<<DATA:sha256>>`; percobaan 2 hanya menambahkan indeks klaim dan kode kegagalan |
| `online.py` | Adaptor httpx tipis untuk API Messages Anthropic (`POST /v1/messages`) dan endpoint OpenAI-compatible (`POST {base}/chat/completions`), tanpa LiteLLM: batas waktu, validasi kontrak `Narasi` (`extra=forbid`), log tanpa kunci, prompt, atau keluaran |
| `egress.py` | Hanya https ke host di allowlist yang tidak mengarah ke alamat privat, loopback, atau link-local (kecuali diizinkan eksplisit) |
| `template.py` | Narasi deterministik dari `kode` kartu: band, skor, pola, peran tiap entitas, dan judul sebagai hipotesis utama; setiap klaim menunjuk ID bukti kartu |
| `cache.py` | Tabel `model_call`: kunci `sha256(prompt_versi, paket_hash, params)` ditambah kode kegagalan pada percobaan 2, satu baris `ok` per kunci (sumber `replay`), jejak `templat` dengan nomor percobaan |
| `replay_import.py` | `python -m astria_narrative.replay_import <berkas.jsonl>`: impor keluaran terekam (`card_id`, `version`, `cache_key`, `model_id`, `backend`, `narasi`) |

Konfigurasi: `ASTRIA_NARRATIVE_CHAIN` (bawaan `replay,templat`; wajib diakhiri `templat`). Kode skor dan band tidak pernah diubah.

Pagar `ASTRIA_ENV=prod` (infra#9): `replay` (rekaman demo) dan `online` (model daring) dilarang, jadi produksi wajib
`ASTRIA_NARRATIVE_CHAIN=templat` (backend `lokal` menyusul); rantai bawaan membuat layanan menolak start. Impor
`replay_import` juga ditolak di `prod` sebelum berkas dibaca. `dev`, `demo`, dan `test` tidak berubah.

Backend `online` untuk demo (contoh nilai; kunci hanya dari env atau berkas secret, tidak pernah di repo):

| Variabel | Contoh | Keterangan |
|---|---|---|
| `ASTRIA_NARRATIVE_CHAIN` | `replay,online,templat` | `online` di rantai |
| `ASTRIA_NARRATIVE_ONLINE_PROVIDER` | `anthropic` | atau `openai_compat` |
| `ASTRIA_NARRATIVE_ONLINE_MODEL_ID` | `claude-opus-5-5` | kosong berarti `online` nonaktif dan rantai lanjut ke backend berikutnya |
| `ASTRIA_NARRATIVE_ONLINE_BASE_URL` | kosong (Anthropic) atau `https://host/v1` | wajib untuk `openai_compat` |
| `ASTRIA_MODEL_API_KEY` | `<kunci>` | wajib untuk `anthropic`; dilarang di `prod` |
| `ASTRIA_NARRATIVE_EGRESS_ALLOWLIST` | `api.anthropic.com` | host base URL `openai_compat` wajib ditambahkan |
| `ASTRIA_NARRATIVE_EGRESS_ALLOW_PRIVATE` | `false` | `true` hanya untuk server model privat |
| `ASTRIA_NARRATIVE_TIMEOUT_S` | `45` | batas satu panggilan, lewat dari itu `batas_waktu` |

Anthropic dipanggil dengan `anthropic-version: 2026-10-21`, `max_tokens` 800, dan `output_config.effort` `low`, tanpa
`temperature` (versi API ini menolaknya; model terkini hanya menerima nilai bawaan), jadi id model harus model
generasi 4.6 ke atas. `openai_compat` dipanggil dengan `temperature` 0 dan `max_tokens` 800. Bila provider atau
jaringan gagal, kartu tetap terbit lewat `templat`, dan kartu yang pernah berhasil diputar ulang dari cache.
Permintaan ulang hanya berisi indeks klaim dan kode gagal, tanpa teks klaim atau kutipan log; tanpa rekaman replay untuk percobaan 2, hasilnya `templat`.

## Alur git

Branch `{type}/{yyyyMMdd}-{taskId}-{nama}`; commit `{type}({yyyyMMddHHmm}): [{taskId}] {pesan}`, satu baris, tanpa trailer. `main` hanya berubah lewat pull request (merge rebase); jangan push langsung ke `main` dan jangan `--no-verify`.
