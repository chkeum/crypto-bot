import logging
from pathlib import Path


def setup_logger() -> logging.Logger:
    """Configure logger with console output and level-based log files."""
    logger = logging.getLogger("crypto_bot")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    Path("logs").mkdir(exist_ok=True)

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handlers for each level
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    for name, level in levels.items():
        fh = logging.FileHandler(f"logs/{name}.log")
        fh.setLevel(level)
        fh.addFilter(lambda record, lvl=level: record.levelno == lvl)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
