import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging():
    # Basic structured-ish format
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Rotating file handler
    log_path = os.getenv("LOG_PATH", "tankbot.log")
    try:
        fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # If file logging fails (permissions), keep console logging only.
        pass

    logging.getLogger("discord").setLevel(logging.WARNING)
