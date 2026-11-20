# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Madhu Kumar and PulseDeck contributors
"""Structured application logging.

Logs go to a rotating file in the user's data directory (JSON lines, easy to
grep and attach to bug reports) and to stderr in a human-readable form.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
from pathlib import Path

from pulsedeck.core import platform


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO, log_file: Path | None = None) -> Path:
    log_file = log_file or platform.log_dir() / "pulsedeck.log"
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)

    if sys.stderr is not None:  # windowed PyInstaller builds have no stderr
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(console)

    def _excepthook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        logging.getLogger("pulsedeck").critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _excepthook
    return log_file
