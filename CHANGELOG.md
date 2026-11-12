# Changelog

## [Unreleased]

### Changed

- Samaran tahan spasi dan pemotongan judul (temuan lab injeksi e2e#2): nilai entitas dicocokkan dengan spasi longgar karena triage merapatkan spasi saat mengisi `judul`, dan awal nilai entitas yang terpotong di ujung judul 200 karakter (`…`) ikut disamarkan. Sebelumnya nama akun berisi spasi ganda, baris baru, atau lebih dari sekitar 170 karakter keluar ke model tanpa samaran lewat `judul`.
- Samaran juga mencakup IP dan token berbentuk identifier di `judul` dan `faktor.alasan` yang bukan entitas (keputusan PM 2026-11-10, temuan uji narrative#5: host di judul ikut terkirim ke provider). Aturan identifier sama dengan pengenal entitas verifier; nomor placeholder entitas tidak berubah, jadi keluaran cache lama tetap bisa dipulihkan.

### Added

- narrative#4: backend `online` untuk demo (note app-narrative 3.5, 4.3, 5.1 sampai 5.5): adaptor httpx untuk `anthropic` dan `openai_compat`, samaran entitas sebelum paket keluar dan pemulihan sesudahnya (`placeholder_asing` bila ada placeholder asing), prompt dengan pagar DATA bertanda sha256, pagar egress (allowlist, tolak alamat non-publik), batas 45 detik, validasi kontrak `Narasi`, setiap percobaan dicatat di `model_call` dan keluaran `ok` menjadi sumber `replay`. Variabel baru: `ASTRIA_NARRATIVE_TIMEOUT_S`, `ASTRIA_NARRATIVE_EGRESS_ALLOWLIST`, `ASTRIA_NARRATIVE_EGRESS_ALLOW_PRIVATE`. Dependensi langsung `httpx`. `ack_wait` konsumen dinaikkan ke `10 x ASTRIA_NARRATIVE_TIMEOUT_S + 30` detik agar pesan tidak dikirim ulang saat menunggu model.
- Percobaan 2 sesuai rancangan (note app-narrative 3.3 dan 5.2): konsumen `narration.retry_requested` (durable `narrative-ulang`), tabel `paket_kartu` untuk menyimpan paket kartu sampai percobaan 2 terbit, kode kegagalan masuk ke kunci cache, dan `model_call.attempt` terisi. Butuh `astria-contracts` v0.2.0.
- narrative#3: konsumen `card.skeleton.created` dengan backend `replay` (cache `model_call`) dan `templat`, `narration.completed` lewat outbox, `ASTRIA_NARRATIVE_CHAIN`, dan impor cache `python -m astria_narrative.replay_import`.
- Kerangka layanan Tahap 0 dari templat `common` v0.1.0: `/health`, `/ready`, `/metrics`, token layanan, Dockerfile non-root, CI (lint, uji, gitleaks, build image, smoke `/ready`).
- Logo Astria di kepala README (`.github/assets/`, dari kit logo di repo `triase-dfir-uiux`).
