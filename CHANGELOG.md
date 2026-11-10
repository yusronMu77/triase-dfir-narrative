# Changelog

## [Unreleased]

### Added

- Percobaan 2 sesuai rancangan (note app-narrative 3.3 dan 5.2): konsumen `narration.retry_requested` (durable `narrative-ulang`), tabel `paket_kartu` untuk menyimpan paket kartu sampai percobaan 2 terbit, kode kegagalan masuk ke kunci cache, dan `model_call.attempt` terisi. Butuh `astria-contracts` v0.2.0.
- narrative#3: konsumen `card.skeleton.created` dengan backend `replay` (cache `model_call`) dan `templat`, `narration.completed` lewat outbox, `ASTRIA_NARRATIVE_CHAIN`, dan impor cache `python -m astria_narrative.replay_import`.
- Kerangka layanan Tahap 0 dari templat `common` v0.1.0: `/health`, `/ready`, `/metrics`, token layanan, Dockerfile non-root, CI (lint, uji, gitleaks, build image, smoke `/ready`).
- Logo Astria di kepala README (`.github/assets/`, dari kit logo di repo `triase-dfir-uiux`).
