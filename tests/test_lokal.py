import re

import httpx
import orjson
import pytest
from fixtures import KEY, NILAI_ASLI, narasi_samar
from fixtures import paket_samar as paket
from pydantic import SecretStr

from astria_narrative import egress
from astria_narrative.lokal import LokalBackend, build_lokal, skema_narasi
from astria_narrative.providers import ProviderConfig
from astria_narrative.settings import Settings

pytestmark = pytest.mark.anyio
LOKAL_KEY = "llama-kunci-uji"
LOKAL = ProviderConfig("local", "openai_compat", "http://10.184.0.10:8080/v1", "lfm-test", SecretStr(LOKAL_KEY))


def resolver(*ips: str):
    async def resolve(host: str, port: int) -> list[str]:
        return list(ips)

    return resolve


def backend(handler, *, ips: tuple[str, ...] = ("10.184.0.10",), cfg: ProviderConfig = LOKAL) -> LokalBackend:
    return LokalBackend(
        cfg,
        allowlist=frozenset(),
        timeout_s=5,
        connect_timeout_s=1,
        transport=httpx.MockTransport(handler),
        resolver=resolver(*ips),
    )


def openai_body(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


VALID = orjson.dumps(narasi_samar()).decode()


@pytest.mark.parametrize(
    ("url", "ips"),
    [
        ("http://10.184.0.10:8080/v1", ["10.184.0.10"]),
        ("http://llama:8080/v1", ["172.18.0.5"]),
        ("http://127.0.0.1:8181/v1", ["127.0.0.1"]),
        ("https://llm.internal/v1", ["192.168.1.20", "fd00::5"]),
    ],
)
async def test_check_lokal_accepts_private_and_loopback(url: str, ips: list[str]) -> None:
    await egress.check_lokal(url, resolver=resolver(*ips))


@pytest.mark.parametrize(
    ("url", "ips", "alasan"),
    [
        ("http://api.example.com/v1", ["1.1.1.1"], "jaringan sendiri"),  # provider daring yang diberi nama lokal
        ("http://campur.example/v1", ["10.0.0.5", "8.8.8.8"], "jaringan sendiri"),
        ("http://metadata.google.internal/v1", ["169.254.169.254"], "jaringan sendiri"),
        ("http://0.0.0.0:8080/v1", ["0.0.0.0"], "jaringan sendiri"),
        ("ftp://10.0.0.5/v1", ["10.0.0.5"], "skema"),
        ("http://kosong/v1", [], "tidak punya alamat"),
    ],
)
async def test_check_lokal_rejects_public_metadata_and_bad_scheme(url: str, ips: list[str], alasan: str) -> None:
    with pytest.raises(egress.EgressDitolak, match=alasan):
        await egress.check_lokal(url, resolver=resolver(*ips))


def test_schema_limits_evidence_ids_and_placeholders_to_this_card() -> None:
    p = paket()
    skema = skema_narasi(p)
    ids = [b["id"] for b in p["bukti"]]
    klaim = skema["properties"]["ringkasan"]["items"]
    assert klaim["properties"]["bukti"]["items"]["enum"] == ids
    assert set(klaim["properties"]) == {"klaim", "bukti"}  # nilai_dikutip tidak ditawarkan
    assert klaim["additionalProperties"] is False
    pola = re.compile(klaim["properties"]["klaim"]["pattern"])
    assert pola.fullmatch("Akun AKUN_1 gagal logon dari HOST_1 (IP_1).")
    assert not pola.fullmatch("Logon dari IP_9.")  # samaran yang tidak ada di paket
    assert not pola.fullmatch("nama_field")  # contoh prompt yang dulu ditiru harfiah
    assert not pola.fullmatch('kutip " memutus JSON')
    for nilai in NILAI_ASLI:
        assert nilai not in orjson.dumps(skema).decode()


async def test_request_uses_schema_local_key_and_private_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=openai_body(VALID))

    hasil = await backend(handler).narrate(paket())
    assert hasil.outcome == "ok"
    [req] = seen
    assert str(req.url) == "http://10.184.0.10:8080/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {LOKAL_KEY}"
    body = orjson.loads(req.content)
    assert body["model"] == "lfm-test" and body["temperature"] == 0 and body["max_tokens"] == 800
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == skema_narasi(paket())
    for nilai in (*NILAI_ASLI, KEY):
        assert nilai not in req.content.decode()


async def test_public_host_is_refused_before_sending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("permintaan tidak boleh terkirim")

    hasil = await backend(handler, ips=("34.101.64.72",)).narrate(paket())
    assert (hasil.outcome, hasil.narasi) == ("egress_ditolak", None)


@pytest.mark.parametrize(
    ("exc", "outcome"),
    [(httpx.ConnectError, "backend_gagal"), (httpx.ConnectTimeout, "batas_waktu"), (httpx.ReadTimeout, "batas_waktu")],
)
async def test_server_down_or_slow_falls_through(exc: type[httpx.TransportError], outcome: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("gagal", request=request)

    assert (await backend(handler).narrate(paket())).outcome == outcome


async def test_invalid_output_is_skema_gagal() -> None:
    teks = orjson.dumps({**narasi_samar(), "skor": 5}).decode()
    hasil = await backend(lambda r: httpx.Response(200, json=openai_body(teks))).narrate(paket())
    assert (hasil.outcome, hasil.narasi) == ("skema_gagal", None)


async def test_log_has_no_key_prompt_or_output(capsys: pytest.CaptureFixture[str]) -> None:
    await backend(lambda r: httpx.Response(200, json=openai_body(VALID))).narrate(paket())
    out = capsys.readouterr()
    assert "panggilan_lokal" in out.out + out.err
    assert LOKAL_KEY not in out.out + out.err
    assert "AKUN_1 gagal logon" not in out.out + out.err


def test_build_lokal() -> None:
    assert build_lokal(Settings(env="test")) is None
    b = build_lokal(
        Settings(
            env="test",
            narrative_local_base_url="http://10.184.0.10:8080/v1",
            narrative_local_model_id="lfm",
            model_api_key=SecretStr(KEY),
        )
    )
    assert b is not None and b.timeout_s == 90.0 and b.connect_timeout_s == 3.0
    assert b.cfg.api_key is None  # kunci model daring tidak pernah dipakai backend lokal
