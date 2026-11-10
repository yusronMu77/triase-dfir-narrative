import pytest

from astria_narrative.cache import cache_key
from astria_narrative.pipeline import parse_chain

PAKET = "sha256:" + "a" * 64


def test_parse_chain_accepts_phase_one_backends() -> None:
    assert parse_chain("replay, templat") == ("replay", "templat")
    assert parse_chain("templat") == ("templat",)


@pytest.mark.parametrize("raw", ["", "replay", "templat,replay", "online,templat", "replay,lokal,templat"])
def test_parse_chain_rejects_unsupported_or_unterminated(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_chain(raw)


def test_cache_key_is_deterministic_and_sensitive() -> None:
    assert cache_key(PAKET) == cache_key(PAKET)
    assert len(cache_key(PAKET)) == 64
    assert cache_key(PAKET) != cache_key("sha256:" + "b" * 64)
    assert cache_key(PAKET) != cache_key(PAKET, prompt_versi="narasi-v2")
    assert cache_key(PAKET) != cache_key(PAKET, params={"max_tokens": 400})


def test_retry_failures_change_the_key_but_not_attempt_1() -> None:
    gagal = [(2, "VALID_TAPI_SALAH"), (0, "TANPA_BUKTI")]
    assert cache_key(PAKET, kegagalan=[]) == cache_key(PAKET)
    assert cache_key(PAKET, kegagalan=gagal) != cache_key(PAKET)
    assert cache_key(PAKET, kegagalan=gagal) == cache_key(PAKET, kegagalan=list(reversed(gagal)))
