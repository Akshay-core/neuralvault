# Akshay-core
__author__ = "Akshay-core"

# FILE: app/utils/logger.py
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.ownership import signature_label

def get_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    Path(log_dir).mkdir(exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        f"%(asctime)s | %(levelname)-8s | %(name)s | {signature_label()} | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = RotatingFileHandler(
        f"{log_dir}/app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        errors="backslashreplace",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    eh = RotatingFileHandler(
        f"{log_dir}/errors.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
        errors="backslashreplace",
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.addHandler(eh)
    return logger
