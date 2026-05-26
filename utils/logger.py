import logging
import os
from datetime import datetime


def setup_logger(name: str, level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
    """
    Створює логер, який пише у файл + консоль.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")

    # Console output
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File output
    fh = logging.FileHandler(log_path)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
