from __future__ import annotations

import logging

from schemas.config import LoggingSettings


def configure_logging(settings: LoggingSettings) -> None:
    handlers: list[logging.Handler] = []

    if settings.rich:
        try:
            from rich.logging import RichHandler

            handlers.append(RichHandler(rich_tracebacks=True, markup=False))
        except ImportError:
            handlers.append(logging.StreamHandler())
    else:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, settings.level.upper(), logging.INFO),
        format="%(message)s",
        handlers=handlers,
        force=True,
    )

