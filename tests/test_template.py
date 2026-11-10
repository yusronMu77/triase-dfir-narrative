from astria_contracts import example
from astria_contracts.events.card_skeleton_created import CardSkeletonCreated

from astria_narrative.template import CATATAN_TEMPLAT, MAX_KLAIM, build_narasi


def _kode(**overrides):
    data = example("card.skeleton.created")["data"]
    data["kode"] |= overrides
    return CardSkeletonCreated.model_validate(data).kode


def test_template_cites_only_card_evidence() -> None:
    kode = _kode()
    narasi = build_narasi(kode)
    card_ids = {b.id.root for b in kode.bukti}
    cited = {i.root for k in narasi.ringkasan for i in k.bukti} | {i.root for i in narasi.hipotesis_utama.bukti}
    assert cited <= card_ids
    assert all(k.bukti for k in narasi.ringkasan)


def test_template_repeats_code_values_verbatim() -> None:
    kode = _kode()
    ringkasan = build_narasi(kode).ringkasan
    first = ringkasan[0].klaim
    assert kode.band in first and f"skor {kode.skor}" in first and kode.pola in first
    entity_claim = ringkasan[1].klaim
    assert entity_claim == "Akun svc-backup tercatat dengan peran diduga terbobol."


def test_template_is_deterministic_and_bounded() -> None:
    many = [
        {"jenis": "host", "nilai": f"WS-{i:02d}", "peran": "TERDAMPAK", "bukti": ["EV-hb01-004217"]} for i in range(10)
    ]
    kode = _kode(entitas=many)
    narasi = build_narasi(kode)
    assert narasi == build_narasi(kode)
    assert len(narasi.ringkasan) == MAX_KLAIM
    assert narasi.hipotesis_tandingan == []
    assert [b.root for b in narasi.belum_diketahui] == [CATATAN_TEMPLAT]


def test_hypothesis_is_card_title() -> None:
    kode = _kode(judul="Judul tanpa titik")
    assert build_narasi(kode).hipotesis_utama.teks == "Judul tanpa titik."
