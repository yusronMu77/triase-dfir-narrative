"""Jalankan layanan: `astria-narrative` atau `python -m astria_narrative`."""

from astria_common.app import run

from astria_narrative.main import build_app
from astria_narrative.settings import Settings


def main() -> None:
    settings = Settings()
    run(build_app(settings), settings)


if __name__ == "__main__":
    main()
