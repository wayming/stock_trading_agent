"""Shared logging setup — console + file, via DEBUG env var."""

import logging
import os
import sys
from pathlib import Path

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(name: str) -> logging.Logger:
    """
    Configure root logger with console + file handlers.
    Set DEBUG=1 for debug level; defaults to INFO.
    """
    debug = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")
    level = logging.DEBUG if debug else logging.INFO

    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)

    file_path = os.path.join(LOG_DIR, f"{name}.log")
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False
    logger.info("Logging to %s  level=%s", file_path, logging.getLevelName(level))
    return logger
