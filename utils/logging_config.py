"""Shared logging configuration for all SafeHoods pipeline scripts.

Configures two handlers on the root logger (once, on first call):
  - RotatingFileHandler → logs/pipeline.log  (5 MB max, 5 backups)
  - StreamHandler       → stdout

Log format: %(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s

Usage in any pipeline script:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.logging_config import get_logger
    logger = get_logger(__name__)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_HERE)

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")

LOG_FORMAT = "%(asctime)s  %(name)-20s  %(levelname)-8s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure():
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(LOGS_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # File handler — persists across sessions, rotates at 5 MB
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Stream handler — visible in terminal for interactive / on-demand runs
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    root.addHandler(sh)


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given name.

    The root logger is configured on first call; subsequent calls reuse it.
    """
    _configure()
    return logging.getLogger(name)
