# Changelog

## [Unreleased]

### Changed

- infra#9: `ASTRIA_ENV=prod` menolak start bila `ASTRIA_NARRATIVE_CHAIN` memuat `replay` atau `online` (termasuk rantai bawaan `replay,templat`), sebelum runtime dirakit; pagar bersama hanya membaca field `model_backend` yang tidak dimiliki narrative, jadi rekaman demo sebelumnya bisa aktif di produksi. `replay_import` juga ditolak di `prod`. Uji `tests/test_startup_env.py` lewat titik masuk `astria-narrative`.

- Samaran tahan spasi dan pemotongan judul (temuan lab injeksi e2e#2): nilai entitas dicocokkan dengan spasi longgar karena triage merapatkan spasi saat mengisi `judul`, dan awal nilai entitas yang terpotong di ujung judul 200 karakter (`…`) ikut disamarkan. Sebelumnya nama akun berisi spasi ganda, baris baru, atau lebih dari sekitar 170 karakter keluar ke model tanpa samaran lewat `judul`.
- Samaran juga mencakup IP dan token berbentuk identifier di `judul` dan `faktor.alasan` yang bukan entitas (keputusan PM 2026-11-10, temuan uji narrative#5: host di judul ikut terkirim ke provider). Aturan identifier sama dengan pengenal entitas verifier; nomor placeholder entitas tidak berubah, jadi keluaran cache lama tetap bisa dipulihkan.

### Added

- Backend `lokal`: llama-server OpenAI-compatible di jaringan sendiri (demo: VM `astria-demo-llm`, LFM2.5-1.2B-Instruct Q4_K_M). Permintaan membawa `response_format` JSON schema per kartu: ID bukti berupa enum milik kartu, teks hanya boleh memuat placeholder kartu itu. Ini membalik hasil uji 2026-11-10 (0/6) menjadi 38/42 LULUS dan 0 JSON atau placeholder gagal. Pagar `egress.check_lokal` hanya menerima alamat privat atau loopback (link-local, multicast, publik ditolak), jadi `lokal` boleh di `prod` (`lokal,templat`) tanpa membuka jalan bagi penyedia daring. Kunci terpisah `ASTRIA_NARRATIVE_LOCAL_API_KEY` (`ASTRIA_MODEL_API_KEY` tidak dipakai), batas `ASTRIA_NARRATIVE_LOCAL_TIMEOUT_S` 90 s dan `ASTRIA_NARRATIVE_LOCAL_CONNECT_TIMEOUT_S` 3 s. Rantai menolak backend ganda. Uji `tests/test_lokal.py` dan uji integrasi PostgreSQL untuk `lokal` (ok lalu replay; jatuh ke templat pada sambungan putus, batas waktu, skema, placeholder asing).
- narrative#4: backend `online` untuk demo (note app-narrative 3.5, 4.3, 5.1 sampai 5.5): adaptor httpx untuk `anthropic` dan `openai_compat`, samaran entitas sebelum paket keluar dan pemulihan sesudahnya (`placeholder_asing` bila ada placeholder asing), prompt dengan pagar DATA bertanda sha256, pagar egress (allowlist, tolak alamat non-publik), batas 45 detik, validasi kontrak `Narasi`, setiap percobaan dicatat di `model_call` dan keluaran `ok` menjadi sumber `replay`. Variabel baru: `ASTRIA_NARRATIVE_TIMEOUT_S`, `ASTRIA_NARRATIVE_EGRESS_ALLOWLIST`, `ASTRIA_NARRATIVE_EGRESS_ALLOW_PRIVATE`. Dependensi langsung `httpx`. `ack_wait` konsumen dinaikkan ke `10 x ASTRIA_NARRATIVE_TIMEOUT_S + 30` detik agar pesan tidak dikirim ulang saat menunggu model.
- Percobaan 2 sesuai rancangan (note app-narrative 3.3 dan 5.2): konsumen `narration.retry_requested` (durable `narrative-ulang`), tabel `paket_kartu` untuk menyimpan paket kartu sampai percobaan 2 terbit, kode kegagalan masuk ke kunci cache, dan `model_call.attempt` terisi. Butuh `astria-contracts` v0.2.0.
- narrative#3: konsumen `card.skeleton.created` dengan backend `replay` (cache `model_call`) dan `templat`, `narration.completed` lewat outbox, `ASTRIA_NARRATIVE_CHAIN`, dan impor cache `python -m astria_narrative.replay_import`.
- Kerangka layanan Tahap 0 dari templat `common` v0.1.0: `/health`, `/ready`, `/metrics`, token layanan, Dockerfile non-root, CI (lint, uji, gitleaks, build image, smoke `/ready`).
- Logo Astria di kepala README (`.github/assets/`, dari kit logo di repo `triase-dfir-uiux`).
