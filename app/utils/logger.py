from __future__ import annotations

import logging
import queue
from logging.handlers import RotatingFileHandler

from app.utils.paths import LOG_FILE, ensure_project_dirs


class QueueLogHandler(logging.Handler):
    """Forward short log messages to the GUI without touching widgets off-thread."""

    def __init__(self, log_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


def setup_logging(gui_queue: "queue.Queue[str] | None" = None) -> logging.Logger:
    ensure_project_dirs()
    logger = logging.getLogger("pixel_automation")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
    )
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(console)

    if gui_queue is not None:
        gui_handler = QueueLogHandler(gui_queue)
        gui_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(gui_handler)

    return logger
