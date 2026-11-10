import pytest

from astria_narrative import egress

ALLOW = egress.parse_allowlist(" api.anthropic.com, LLM.example.org ,")
pytestmark = pytest.mark.anyio


def resolver(*ips: str):
    async def resolve(host: str, port: int) -> list[str]:
        return list(ips)

    return resolve


def test_parse_allowlist() -> None:
    assert ALLOW == frozenset({"api.anthropic.com", "llm.example.org"})


async def test_public_host_in_allowlist_passes() -> None:
    await egress.check(
        "https://api.anthropic.com/v1/messages", ALLOW, allow_private=False, resolver=resolver("1.1.1.1")
    )


@pytest.mark.parametrize(
    ("url", "ips", "alasan"),
    [
        ("https://evil.example.com/v1", ["1.1.1.1"], "allowlist"),
        ("http://api.anthropic.com/v1", ["1.1.1.1"], "https"),
        ("https://llm.example.org/v1", ["1.1.1.1", "10.0.0.5"], "non-publik"),
        ("https://llm.example.org/v1", ["127.0.0.1"], "non-publik"),
        ("https://llm.example.org/v1", ["169.254.169.254"], "non-publik"),
        ("https://llm.example.org/v1", ["::1"], "non-publik"),
    ],
)
async def test_rejected(url: str, ips: list[str], alasan: str) -> None:
    with pytest.raises(egress.EgressDitolak, match=alasan):
        await egress.check(url, ALLOW, allow_private=False, resolver=resolver(*ips))


async def test_private_allowed_only_when_explicit_and_still_https_in_allowlist() -> None:
    await egress.check("https://llm.example.org/v1", ALLOW, allow_private=True, resolver=resolver("10.0.0.5"))
    with pytest.raises(egress.EgressDitolak, match="https"):
        await egress.check("http://llm.example.org/v1", ALLOW, allow_private=True, resolver=resolver("10.0.0.5"))
    with pytest.raises(egress.EgressDitolak, match="allowlist"):
        await egress.check("https://llama:8080/v1", ALLOW, allow_private=True, resolver=resolver("10.0.0.5"))
