import orjson
import pytest
from astria_contracts.events.narration_completed import Narasi
from fixtures import AKUN, HOST_SUMBER, HOST_TERDAMPAK, IP_SUMBER, NILAI_ASLI, card, narasi_samar

from astria_narrative import pseudonym


def test_map_numbers_per_kind_in_packet_order() -> None:
    assert pseudonym.build_map(card().kode) == {
        AKUN: "AKUN_1",
        HOST_SUMBER: "HOST_1",
        HOST_TERDAMPAK: "HOST_2",
        IP_SUMBER: "IP_1",
    }


def test_samarkan_removes_every_real_value_but_keeps_evidence_ids() -> None:
    kode = card().kode
    paket = pseudonym.samarkan(kode, pseudonym.build_map(kode))
    teks = orjson.dumps(paket).decode()
    for nilai in NILAI_ASLI:
        assert nilai not in teks
    assert paket["judul"] == "Dugaan pengambilalihan akun layanan AKUN_1 di HOST_2"
    assert paket["faktor"][-1]["alasan"] == "logon dari IP_1 (HOST_1)"
    assert [b["id"] for b in paket["bukti"]] == [b.id.root for b in kode.bukti]


def test_case_insensitive() -> None:
    kode = card().kode.model_copy(update={"judul": "Login SVC-BACKUP ke ws-adm-04"})
    assert pseudonym.samarkan(kode, pseudonym.build_map(kode))["judul"] == "Login AKUN_1 ke HOST_2"


def test_whole_word_only() -> None:
    kode = card().kode.model_copy(update={"judul": "Sumber 10.20.8.315 dan 10.20.8.31."})
    paket = pseudonym.samarkan(kode, pseudonym.build_map(kode))
    assert paket["judul"] == "Sumber 10.20.8.315 dan IP_1."


def test_restore_round_trip() -> None:
    kode = card().kode
    peta = pseudonym.build_map(kode)
    narasi = pseudonym.restore(Narasi.model_validate(narasi_samar()), peta)
    assert narasi.ringkasan[0].klaim == f"Akun {AKUN} gagal logon berulang dari {HOST_SUMBER} ({IP_SUMBER})."
    assert narasi.ringkasan[0].nilai_dikutip == {"TargetUserName": AKUN}
    assert narasi.hipotesis_utama.teks == f"{AKUN} diambil alih lewat tebakan kata sandi di {HOST_TERDAMPAK}."
    # Samarkan lagi hasil pemulihan memberi placeholder yang sama.
    assert pseudonym.samarkan(kode, peta)["entitas"][1]["nilai"] == "HOST_1"


def test_unknown_placeholder_rejected() -> None:
    with pytest.raises(pseudonym.PlaceholderAsing, match="HOST_9"):
        pseudonym.restore(Narasi.model_validate(narasi_samar(host="HOST_9")), pseudonym.build_map(card().kode))


def test_identifiers_in_free_text_that_are_not_entities_are_masked_too() -> None:
    judul = "Logon AKUN svc-backup ke WS-FIN-07 dari 10.9.9.9 pola P-AKUN-DIAMBILALIH, masing-masing via e-mail (T1110)"
    kode = card().kode.model_copy(update={"judul": judul})
    peta = pseudonym.build_map(kode)
    assert peta["WS-FIN-07"] == "ENTITAS_1" and peta["10.9.9.9"] == "IP_2"
    paket = pseudonym.samarkan(kode, peta)
    assert paket["judul"] == (
        "Logon AKUN AKUN_1 ke ENTITAS_1 dari IP_2 pola P-AKUN-DIAMBILALIH, masing-masing via e-mail (T1110)"
    )
    narasi = Narasi.model_validate(
        {
            "ringkasan": [{"klaim": "Logon ke ENTITAS_1 dari IP_2.", "bukti": [kode.bukti[0].id.root]}],
            "hipotesis_utama": {"teks": "AKUN_1 diambil alih.", "bukti": [kode.bukti[0].id.root]},
            "hipotesis_tandingan": [],
            "belum_diketahui": [],
        }
    )
    assert pseudonym.restore(narasi, peta).ringkasan[0].klaim == "Logon ke WS-FIN-07 dari 10.9.9.9."


def test_contract_example_title_host_no_longer_leaves() -> None:
    from astria_contracts import example
    from astria_contracts.events.card_skeleton_created import CardSkeletonCreated

    kode = CardSkeletonCreated.model_validate(example("card.skeleton.created")["data"]).kode
    teks = orjson.dumps(pseudonym.samarkan(kode, pseudonym.build_map(kode))).decode()
    assert "WS-ADM-04" not in teks and "svc-backup" not in teks
