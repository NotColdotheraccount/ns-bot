"""Logging configuration.

Privacy rule for this project: log *events*, never *content*.

We record which feature handled a message, whether it succeeded, and how long
it took. We never record the text of her messages, reassurance content, AI
prompts, or anything she leaves for you. Logs end up in a hosting provider's
dashboard, and this is a relationship, not a system under audit.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that are far too chatty at DEBUG level.
_NOISY_LOGGERS = (
    "aiogram.event",
    "aiohttp.access",
    "asyncio",
)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging. Safe to call once, at startup."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Clear existing handlers so repeated calls (e.g. in tests) don't duplicate
    # every log line.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
