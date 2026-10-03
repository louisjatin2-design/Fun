"""Logging to console and a rotating file in %APPDATA%/SupComBot/logs."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import config

_configured = False


def setup(debug: bool = False) -> logging.Logger:
    global _configured
    log = logging.getLogger("supcombot")
    if _configured:
        log.setLevel(logging.DEBUG if debug else logging.INFO)
        return log
    config.ensure_dirs()
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.handlers.RotatingFileHandler(config.LOG_DIR / "supcombot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    _configured = True
    return log


def get(name: str = "") -> logging.Logger:
    return logging.getLogger("supcombot" + ("." + name if name else ""))
