import asyncio
from collections.abc import Callable

import httpx
import orjson
import pytest
from fixtures import ANTHROPIC, KEY, NILAI_ASLI, narasi_samar, publik
from fixtures import paket_samar as paket
from pydantic import SecretStr

from astria_narrative.online import ANTHROPIC_VERSION, OnlineBackend, build_online, parse_narasi
from astria_narrative.providers import ProviderConfig
from astria_narrative.settings import Settings

pytestmark = pytest.mark.anyio
OPENAI = ProviderConfig("online", "openai_compat", "https://llm.example.org/v1", "qwen-test", SecretStr(KEY))
ALLOW = frozenset({"api.anthropic.com", "llm.example.org"})


def anthropic_body(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


def openai_body(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def backend(cfg: ProviderConfig, handler: Callable[[httpx.Request], httpx.Response], **kw) -> OnlineBackend:
    return OnlineBackend(
        cfg, allowlist=ALLOW, transport=httpx.MockTransport(handler), resolver=kw.pop("resolver", publik), **kw
    )


VALID = orjson.dumps(narasi_samar()).decode()


async def test_anthropic_ok_and_no_real_values_leave() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=anthropic_body("Berikut JSON:\n" + VALID))

    hasil = await backend(ANTHROPIC, handler).narrate(paket())
    assert hasil.outcome == "ok"
    assert hasil.narasi is not None and hasil.narasi.ringkasan[0].bukti[0].root == "EV-hb01-004217"
    [req] = seen
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"] == ANTHROPIC_VERSION
    body = orjson.loads(req.content)
    assert body["model"] == "claude-test" and body["max_tokens"] == 800
    assert "temperature" not in body and "top_p" not in body
    for nilai in NILAI_ASLI:
        assert nilai not in req.content.decode()


async def test_openai_compat_ok() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=openai_body(VALID))

    hasil = await backend(OPENAI, handler).narrate(paket(), [(1, "ID_TIDAK_DITEMUKAN")])
    assert hasil.outcome == "ok"
    [req] = seen
    assert str(req.url) == "https://llm.example.org/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = orjson.loads(req.content)
    assert (body["temperature"], body["max_tokens"]) == (0, 800)
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "klaim 1: ID_TIDAK_DITEMUKAN" in body["messages"][1]["content"]


@pytest.mark.parametrize("cfg", [ANTHROPIC, OPENAI])
@pytest.mark.parametrize("status", [401, 429, 500, 503])
async def test_http_error_is_backend_gagal(cfg: ProviderConfig, status: int) -> None:
    hasil = await backend(cfg, lambda r: httpx.Response(status, json={"error": "x"})).narrate(paket())
    assert (hasil.outcome, hasil.narasi) == ("backend_gagal", None)


@pytest.mark.parametrize("cfg", [ANTHROPIC, OPENAI])
@pytest.mark.parametrize(
    ("exc", "outcome"), [(httpx.ConnectError, "backend_gagal"), (httpx.ReadTimeout, "batas_waktu")]
)
async def test_transport_errors(cfg: ProviderConfig, exc: type[httpx.TransportError], outcome: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("gagal", request=request)

    assert (await backend(cfg, handler).narrate(paket())).outcome == outcome


async def test_total_timeout_covers_slow_dns() -> None:
    async def lambat(host: str, port: int) -> list[str]:
        await asyncio.sleep(5)
        return ["1.1.1.1"]

    b = backend(ANTHROPIC, lambda r: httpx.Response(200), resolver=lambat, timeout_s=0.05)
    assert (await b.narrate(paket())).outcome == "batas_waktu"


@pytest.mark.parametrize(
    "text",
    [
        "bukan JSON",
        '{"ringkasan": [',
        orjson.dumps({**narasi_samar(), "saran_langkah": ["isolasi host"]}).decode(),  # extra=forbid
        orjson.dumps({**narasi_samar(), "hipotesis_utama": {"teks": "x", "bukti": ["bukan-id"]}}).decode(),
    ],
)
@pytest.mark.parametrize(("cfg", "wrap"), [(ANTHROPIC, anthropic_body), (OPENAI, openai_body)])
async def test_bad_output_is_skema_gagal(cfg: ProviderConfig, wrap: Callable[[str], dict], text: str) -> None:
    hasil = await backend(cfg, lambda r: httpx.Response(200, json=wrap(text))).narrate(paket())
    assert (hasil.outcome, hasil.narasi) == ("skema_gagal", None)


async def test_unknown_response_shape_is_skema_gagal() -> None:
    hasil = await backend(OPENAI, lambda r: httpx.Response(200, json={"choices": []})).narrate(paket())
    assert hasil.outcome == "skema_gagal"


async def test_egress_rejected_sends_nothing() -> None:
    async def privat(host: str, port: int) -> list[str]:
        return ["10.0.0.5"]

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("permintaan tidak boleh terkirim")

    assert (await backend(OPENAI, handler, resolver=privat).narrate(paket())).outcome == "egress_ditolak"
    luar = ProviderConfig("online", "openai_compat", "https://lain.example.net/v1", "m", None)
    assert (await backend(luar, handler).narrate(paket())).outcome == "egress_ditolak"


async def test_key_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    await backend(ANTHROPIC, lambda r: httpx.Response(500)).narrate(paket())
    await backend(ANTHROPIC, lambda r: httpx.Response(200, json=anthropic_body(VALID))).narrate(paket())
    out = capsys.readouterr()
    assert "panggilan_online" in out.out + out.err
    assert KEY not in out.out + out.err
    assert "AKUN_1 gagal logon" not in out.out + out.err  # keluaran model tidak dicatat


def test_parse_takes_outermost_object() -> None:
    assert parse_narasi(f"```json\n{VALID}\n```").hipotesis_utama.bukti[0].root == "EV-hb01-004231"


def test_build_online_disabled_without_config() -> None:
    assert build_online(Settings(env="test")) is None
    cfg = Settings(
        env="test",
        narrative_online_provider="openai_compat",
        narrative_online_base_url="https://llm.example.org/v1",
        narrative_online_model_id="qwen",
        narrative_egress_allowlist="llm.example.org",
    )
    b = build_online(cfg)
    assert b is not None and b.allowlist == frozenset({"llm.example.org"}) and b.timeout_s == 45.0
